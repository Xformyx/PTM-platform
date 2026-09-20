"""Order-authorized read-only views of published immutable run components."""
import asyncio
import json
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select
from app.api.analysis_jobs import access, get_db, get_current_user
from app.config import get_settings
from app.models.analysis_job import AnalysisJob
from app.services.analysis_jobs import authorized_job
from ptm_shared.run_evidence_bundle import verify_bundle, verify_report_bundle
from ptm_shared.signaling_evidence_index import explorer_page, iter_explorer_records, KINDS

router = APIRouter(prefix="/orders", tags=["signaling-explorer"])


def _directory(order, job):
    root = (Path(get_settings().OUTPUT_DIR)/order.order_code).resolve()
    directory = (root/(job.result_path or "")).resolve()
    if not directory.is_relative_to(root/".analysis_results"):
        raise ValueError("analysis_artifact_outside_order")
    return directory


async def bound(db, user, order_id, bundle_id):
    order = await access(db, user, order_id)
    job_id = bundle_id.split(".", 1)[0]
    job = await authorized_job(db, order_id, job_id)
    if job.execution_status != "completed":
        raise HTTPException(409, "bundle_not_published")
    try:
        directory = _directory(order, job)
        order_root=Path(get_settings().OUTPUT_DIR)/order.order_code
        index_path=order_root/".evidence_runs"/"index.json"
        index=json.loads(index_path.read_text()) if index_path.is_file() else {}
        if bundle_id in index:
            bundle=await asyncio.to_thread(verify_report_bundle,order_root,order_id=order_id,bundle_id=bundle_id)
        else:
            bundle = await asyncio.to_thread(verify_bundle, directory, order_id=order_id, bundle_id=bundle_id)
        if bundle["revisions"]["analysis"] != job.result_revision:
            raise ValueError("bundle_database_revision_mismatch")
    except FileNotFoundError as exc:
        raise HTTPException(404, "legacy_unbound") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return directory, bundle


@router.get("/{order_id}/evidence-runs")
async def runs(order_id: int, db=Depends(get_db), user=Depends(get_current_user)):
    order = await access(db, user, order_id)
    jobs = (await db.execute(select(AnalysisJob).where(AnalysisJob.order_id == order_id)
        .order_by(AnalysisJob.created_at.desc()).limit(100))).scalars().all()
    records = []
    order_root=Path(get_settings().OUTPUT_DIR)/order.order_code
    index_path=order_root/".evidence_runs"/"index.json"
    index=json.loads(index_path.read_text()) if index_path.is_file() else {}
    for job in jobs:
        record = {"run_id": job.job_id, "bundle_id": None, "execution_status": job.execution_status,
                  "created_at": job.created_at.isoformat() if job.created_at else None,
                  "explorer_status": "preparing" if job.execution_status in {"queued", "running"} else "legacy_unbound",
                  "reason": job.failure_reason}
        if job.execution_status == "completed":
            try:
                bundle = await asyncio.to_thread(verify_bundle, _directory(order, job), order_id=order_id)
                record.update({k:bundle[k] for k in ("bundle_id", "explorer_status", "revisions", "coverage", "input_scope", "components")})
            except FileNotFoundError:
                record["reason"] = "completed_revision_without_bundle"
            except ValueError:
                record.update(explorer_status="stale_or_incompatible", reason="component_integrity_failed")
        derived_records=[]
        if job.execution_status == "completed":
            for bundle_id, binding in sorted(index.items(),key=lambda item:(item[1].get("publication_order",0),item[0]),reverse=True):
                if binding["analysis_job_id"] != job.job_id: continue
                try:
                    derived=await asyncio.to_thread(verify_report_bundle,order_root,order_id=order_id,bundle_id=bundle_id)
                    derived_records.append({**record,**{k:derived[k] for k in ("bundle_id","explorer_status","revisions","components")},
                                    "report_revision":binding["report_revision"]})
                except (ValueError,FileNotFoundError):
                    derived_records.append({**record,"bundle_id":bundle_id,"explorer_status":"stale_or_incompatible","reason":"report_binding_integrity_failed"})
        records.extend(derived_records+[record])
    return {"schema_version": "signaling_explorer.v1", "records": records,
            "status": "available" if records else "legacy_unbound", "legacy_observations_available": None,
            "legacy_reason": "observation_view_has_independent_source_availability",
            "list_scope": "most_recent_100_runs", "returned_count": len(records)}


@router.get("/{order_id}/evidence-runs/{bundle_id}")
async def manifest(order_id: int, bundle_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    _, bundle = await bound(db, user, order_id, bundle_id)
    return bundle


async def page(order_id, bundle_id, kind, db, user, **filters):
    directory, bundle = await bound(db, user, order_id, bundle_id)
    try:
        if bundle.get("report_evidence_index"):
            # Verified by bound(); paths are scoped to this order's root.
            filters["report_index"]=directory.parents[2]/bundle["report_evidence_index"]["filename"]
        payload = await asyncio.to_thread(explorer_page, directory, bundle_id, kind=kind, **filters)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {**payload, "revisions": bundle["revisions"], "analysis_scope": bundle["analysis_scope"],
            "analysis_coverage": bundle["coverage"], "component_status": bundle.get("components", {}).get(kind),
            "evaluation_status": bundle["evaluation_status"]}


@router.get("/{order_id}/evidence-runs/{bundle_id}/pathways/{pathway_key}/members")
async def members(order_id: int, bundle_id: str, pathway_key: str, cursor: str|None=None,
                  limit: int=Query(100, ge=1, le=500), db=Depends(get_db), user=Depends(get_current_user)):
    return await page(order_id, bundle_id, "features", db, user, pathway_key=pathway_key, cursor=cursor, limit=limit)


@router.get("/{order_id}/evidence-runs/{bundle_id}/pathways/{pathway_key}/kinases")
async def contributions(order_id: int, bundle_id: str, pathway_key: str, cursor: str|None=None,
                        db=Depends(get_db), user=Depends(get_current_user)):
    return await page(order_id, bundle_id, "contributions", db, user, pathway_key=pathway_key, cursor=cursor)


@router.get("/{order_id}/evidence-runs/{bundle_id}/features/{feature_id}")
async def feature(order_id: int, bundle_id: str, feature_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    return await page(order_id, bundle_id, "features", db, user, feature_id=feature_id)


@router.post("/{order_id}/evidence-runs/{bundle_id}/trajectory-query")
async def trajectories(order_id: int, bundle_id: str, body: dict, db=Depends(get_db), user=Depends(get_current_user)):
    ids = body.get("feature_ids")
    if not isinstance(ids, list) or len(ids)>100 or not all(isinstance(i,str) for i in ids):
        raise HTTPException(422, "trajectory_query_requires_at_most_100_feature_ids")
    directory, bundle = await bound(db, user, order_id, bundle_id)
    records = []
    for fid in sorted(set(ids)):
        result = await asyncio.to_thread(explorer_page, directory, bundle_id, kind="features", feature_id=fid)
        records.extend(result["records"])
    return {"bundle_id": bundle_id, "revisions": bundle["revisions"], "records": records, "returned_count":len(records),
            "unit":"feature", "schema_version":"signaling_explorer.v1"}


@router.get("/{order_id}/evidence-runs/{bundle_id}/artifacts/{name}")
async def artifact(order_id: int, bundle_id: str, name: str, db=Depends(get_db), user=Depends(get_current_user)):
    directory, bundle = await bound(db, user, order_id, bundle_id)
    record = bundle["artifacts"].get(name)
    if record is None: raise HTTPException(404, "artifact_not_registered")
    return FileResponse(directory/record["filename"], filename=record["filename"],
        headers={"ETag": '"'+record["sha256"]+'"', "X-Evidence-Bundle":bundle_id})


@router.get("/{order_id}/evidence-runs/{bundle_id}/inventory-export")
async def inventory_export(order_id: int, bundle_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    directory, bundle = await bound(db, user, order_id, bundle_id)
    report_index = (directory.parents[2]/bundle["report_evidence_index"]["filename"]
                    if bundle.get("report_evidence_index") else None)

    def stream():
        yield json.dumps({"kind": "export_manifest", "schema_version": "signaling_explorer_export.v1",
            "bundle_id": bundle_id, "revisions": bundle["revisions"], "scope": "complete_bundle_inventory",
            "analysis_scope": bundle["analysis_scope"], "coverage": bundle["coverage"],
            "unit": "typed_record_memberships_are_not_distinct_feature_counts"}, allow_nan=False)+"\n"
        for record in iter_explorer_records(directory, report_index=report_index):
            yield json.dumps(record, allow_nan=False)+"\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson", headers={
        "Content-Disposition": f'attachment; filename="evidence-{bundle_id}.jsonl"',
        "X-Evidence-Bundle": bundle_id})


@router.get("/{order_id}/evidence-runs/{bundle_id}/{kind}")
async def records(order_id: int, bundle_id: str, kind: str, pathway_key: str|None=None, feature_id: str|None=None,
                  kinase: str|None=None, track: str|None=None, cursor: str|None=None, limit: int=Query(100,ge=1,le=500),
                  mode: str="inventory", n: int|None=None, module_id: str|None=None, model_id: str|None=None,
                  db=Depends(get_db), user=Depends(get_current_user)):
    if kind not in KINDS: raise HTTPException(404, "component_not_available")
    return await page(order_id, bundle_id, kind, db, user, pathway_key=pathway_key, feature_id=feature_id,
                      kinase=kinase, track=track, cursor=cursor, limit=limit, mode=mode, n=n,module_id=module_id,model_id=model_id)
