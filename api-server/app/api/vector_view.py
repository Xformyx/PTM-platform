"""Bounded view queries over immutable derived columns; no analysis mutation."""
import asyncio
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from app.api.analysis_jobs import access, get_db, get_current_user
from app.config import get_settings
from ptm_shared.vector_columnar import VectorColumnar

router = APIRouter(prefix="/orders", tags=["vector-view"])


def query(directory, suffix, operation, revision, options):
    try:
        store = VectorColumnar(directory, suffix)
    except FileNotFoundError as exc:
        raise HTTPException(409, detail={"reason":"columnar_snapshot_unavailable","action":"publish_preprocessing_snapshot"}) from exc
    try:
        if revision and revision != store.manifest["measurement_revision"]:
            raise HTTPException(409, detail={"reason":"measurement_revision_changed"})
        functions = {"manifest":store.manifest_counts,"features":store.feature_page,"trajectories":store.trajectories,
                     "density":store.density,"coordinates":store.coordinate_page,"distribution":store.distribution,
                     "diagnostics":store.diagnostics}
        if operation == "annotations":
            from app.services.vector_view import load_annotations
            from ptm_shared.vector_plot import plot_feature_metadata
            annotations, source = load_annotations(directory, suffix)
            page = store.feature_page(**options)
            features = plot_feature_metadata(store.trajectories(page["feature_ids"]), annotations)
            return {**page, "features":features, "annotation_source":source}
        if operation not in functions: raise HTTPException(404,"Unknown vector view operation")
        return functions[operation](**options)
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    finally: store.close()


@router.post("/{order_id}/vector-view/{operation}")
async def vector_query(order_id:int, operation:str, body:dict, db=Depends(get_db), user=Depends(get_current_user)):
    order = await access(db,user,order_id)
    if operation == "preparation_status":
        return (order.analysis_options or {}).get("vector_index_job", {"execution_status":"not_requested"})
    if operation == "prepare":
        await access(db,user,order_id,write=True)
        from uuid import uuid4
        from app.tasks.production_tmm import celery_app
        from sqlalchemy import select
        from app.models.order import Order
        await db.execute(select(Order.id).where(Order.id==order_id).with_for_update())
        await db.refresh(order)
        previous=(order.analysis_options or {}).get("vector_index_job") or {}
        if previous.get("execution_status") in {"queued","running"}: return previous
        task_id=str(uuid4())
        state={"execution_status":"queued","task_id":task_id}
        order.analysis_options={**(order.analysis_options or {}),"vector_index_job":state}
        await db.commit()
        try: celery_app.send_task("app.tasks.production_tmm.prepare_view",args=[order_id,task_id],task_id=task_id,queue="production_tmm")
        except Exception as exc:
            order.analysis_options={**order.analysis_options,"vector_index_job":{**state,"execution_status":"failed","failure_reason":"broker_unavailable"}}
            await db.commit()
            raise HTTPException(503,"vector preparation broker unavailable") from exc
        return state
    suffix = "_phospho" if order.ptm_type == "phosphorylation" else "_ubi"
    return await asyncio.to_thread(query, Path(get_settings().OUTPUT_DIR)/order.order_code, suffix,
                                  operation, body.get("measurement_revision"), body.get("options") or {})


@router.get("/{order_id}/vector-view/export")
async def vector_export(order_id:int, measurement_revision:str | None=None, db=Depends(get_db), user=Depends(get_current_user)):
    order = await access(db,user,order_id)
    suffix = "_phospho" if order.ptm_type == "phosphorylation" else "_ubi"
    directory = Path(get_settings().OUTPUT_DIR)/order.order_code
    def open_pinned():
        try:
            store = VectorColumnar(directory, suffix)
        except FileNotFoundError as exc:
            raise HTTPException(409, "columnar_snapshot_unavailable") from exc
        if measurement_revision and store.manifest["measurement_revision"] != measurement_revision:
            store.close()
            raise HTTPException(409, "measurement_revision_changed")
        return store
    # Resolve before sending a 200 response. The connection keeps this exact
    # immutable Parquet file even if a newer current pointer is published.
    store = await asyncio.to_thread(open_pinned)
    def records():
        try:
            cursor = store.db.execute("SELECT record_json FROM observations ORDER BY source_line")
            while batch := cursor.fetchmany(1000):
                for (record,) in batch: yield record+"\n"
        finally: store.close()
    return StreamingResponse(records(),media_type="application/x-ndjson",
        background=BackgroundTask(store.close),
        headers={"Content-Disposition":"attachment; filename=full_vector_inventory.jsonl",
                 "X-Measurement-Revision":store.manifest["measurement_revision"]})
