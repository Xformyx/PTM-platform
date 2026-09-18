from pathlib import Path
import asyncio
import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from sqlalchemy import select
from app.api.orders import get_db, get_current_user, _check_order_access_async, _require_write_access
from app.models.order import Order
from app.config import get_settings
from app.services.analysis_jobs import submit_analysis, authorized_job, job_payload
from ptm_shared.analysis_revision import verify_result

router = APIRouter(prefix="/orders", tags=["analysis-jobs"])


async def access(db, user, order_id, write=False):
    order = (await db.execute(select(Order).where(Order.id == order_id))).scalar_one_or_none()
    if order is None:
        raise HTTPException(404, "Order not found")
    await (_require_write_access(order, user, db) if write else _check_order_access_async(order, user, db))
    return order


@router.post("/{order_id}/analysis-jobs")
async def create_job(order_id: int, body: dict, db=Depends(get_db), user=Depends(get_current_user)):
    order = await access(db, user, order_id, write=True)
    job = await submit_analysis(db, order, user.id, body)
    return JSONResponse(job_payload(job), status_code=200 if job.execution_status == "completed" else 202)


@router.get("/{order_id}/analysis-jobs/{job_id}")
async def get_job(order_id: int, job_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    await access(db, user, order_id)
    return job_payload(await authorized_job(db, order_id, job_id))


@router.post("/{order_id}/analysis-jobs/{job_id}/cancel")
async def cancel_job(order_id: int, job_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    await access(db, user, order_id, write=True)
    await db.execute(select(Order.id).where(Order.id == order_id).with_for_update())
    job = await authorized_job(db, order_id, job_id)
    await db.refresh(job, with_for_update=True)
    if job.execution_status in {"queued", "running"}:
        job.cancel_requested = True
        # Running resources remain owned until worker acknowledgement/exit.
        if job.execution_status == "queued":
            job.execution_status, job.active_key = "cancelled", None
        await db.commit()
    return job_payload(job)


@router.get("/{order_id}/analysis-jobs/{job_id}/result")
async def get_result(order_id: int, job_id: str, db=Depends(get_db), user=Depends(get_current_user)):
    order = await access(db, user, order_id)
    job = await authorized_job(db, order_id, job_id)
    if job.execution_status != "completed":
        raise HTTPException(409, detail=job_payload(job))
    directory = Path(get_settings().OUTPUT_DIR) / order.order_code / job.result_path
    manifest = await asyncio.to_thread(verify_result, directory)
    result = await asyncio.to_thread(lambda: json.loads((directory/"result.json").read_text()))
    from app.services.analysis_universe import module_response
    if (directory/'candidate_summary.json').is_file():
        candidates = await asyncio.to_thread(lambda: json.loads((directory/'candidate_summary.json').read_text()))
        return {**candidates, **result, "revision_manifest":manifest, "analysis_job_id":job_id,
                "membership_page_url":f'/orders/{order_id}/analysis-jobs/{job_id}/inventory'}
    candidates = await asyncio.to_thread(lambda: json.loads((directory/"candidates.json").read_text())["manifest"])
    return {**module_response(candidates), **result, "revision_manifest": manifest}


@router.get("/{order_id}/analysis-jobs/{job_id}/inventory")
async def get_inventory(order_id:int, job_id:str, kind:str='features', kinase:str|None=None, status:str|None=None,
                        after:str='', limit:int=100, db=Depends(get_db), user=Depends(get_current_user)):
    order=await access(db,user,order_id)
    job=await authorized_job(db,order_id,job_id)
    if job.execution_status!='completed':raise HTTPException(409,detail=job_payload(job))
    directory=Path(get_settings().OUTPUT_DIR)/order.order_code/job.result_path
    revision=await asyncio.to_thread(verify_result,directory)
    from ptm_shared.analysis_inventory_index import inventory_page
    try:
        page=await asyncio.to_thread(inventory_page,directory,kind=kind,kinase=kinase,status=status,after=after,limit=limit)
    except (ValueError,FileNotFoundError) as exc:
        raise HTTPException(422,str(exc)) from exc
    return {**page,'analysis_revision':revision['revision_id']}


@router.post("/{order_id}/analysis-jobs/{job_id}/retry")
async def retry_job(order_id:int, job_id:str, db=Depends(get_db), user=Depends(get_current_user)):
    await access(db,user,order_id,write=True)
    await authorized_job(db,order_id,job_id)
    from app.services.analysis_job_recovery import recover_job
    result=await recover_job(db,job_id,manual=True)
    if result['recovery']=='execution_still_owned':
        raise HTTPException(409,detail=result)
    return result


@router.get("/{order_id}/analysis-jobs/{job_id}/artifacts/{artifact_name}")
async def get_artifact(order_id:int, job_id:str, artifact_name:str, db=Depends(get_db), user=Depends(get_current_user)):
    order = await access(db, user, order_id)
    job = await authorized_job(db, order_id, job_id)
    if job.execution_status != "completed":
        raise HTTPException(409, detail=job_payload(job))
    directory = Path(get_settings().OUTPUT_DIR)/order.order_code/job.result_path
    manifest = await asyncio.to_thread(verify_result, directory)
    artifact = next((a for a in manifest["artifacts"] if a["name"] == artifact_name), None)
    if artifact is None:
        raise HTTPException(404, "Artifact is not registered for this revision")
    return FileResponse(directory/artifact["filename"], filename=artifact["filename"],
        headers={"X-Analysis-Revision":manifest["revision_id"], "X-Artifact-SHA256":artifact["sha256"]})
