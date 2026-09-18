"""Durable production analysis admission, fencing and revision lookup."""
import json
import os
from pathlib import Path
from uuid import uuid4
from sqlalchemy import select
from fastapi import HTTPException
from app.models.analysis_job import AnalysisJob, AnalysisHead
from app.models.order import Order
from app.config import get_settings
from ptm_shared.analysis_universe import signature
from ptm_shared.analysis_revision import input_directory, verify_result
from ptm_shared.tmm_feature_allocation import ALLOCATION_VERSION, RNG_POLICY_VERSION
from ptm_shared.report_revision import file_sha256


def runtime_signature():
    return _runtime_signature()


from functools import lru_cache
@lru_cache(maxsize=1)
def _runtime_signature():
    # Code is immutable during a worker process lifetime; restart on deployment.
    # Include every shared adapter/solver, not a prefix of kinase names.
    import importlib.metadata
    import ptm_shared
    shared = Path(ptm_shared.__file__).parent
    services = Path(__file__).parent
    paths = [("ptm_shared/" + p.name, p) for p in shared.glob("*.py")]
    paths += [("services/" + name, services/name) for name in (
        "analysis_jobs.py", "analysis_job_recovery.py", "analysis_universe.py", "production_temporal_analysis.py",
        "production_tmm_executor.py", "temporal_kinase_scoring.py")]
    return {"code": {name: file_sha256(path) for name, path in sorted(paths)},
            "dependencies": {name: importlib.metadata.version(name) for name in ("numpy", "scipy", "pandas")}}


def reference_signature():
    return {key: file_sha256(path) if (path := os.getenv(key)) and Path(path).is_file() else "unavailable"
            for key in ("PTM_MAPPING_SOURCE_BUNDLE_PATH", "PTM_RELATION_SOURCE_BUNDLE_PATH")}


def job_payload(job):
    return {"job_id": job.job_id, "order_id": job.order_id, "execution_status": job.execution_status,
            "evaluation_status": job.evaluation_status, "failure_reason": job.failure_reason,
            "stage_status": job.stage_status, "input_revision": job.input_revision,
            "input_signature": job.input_signature, "result_revision": job.result_revision,
            "cancel_requested": job.cancel_requested,
            "heartbeat_at": job.heartbeat_at.isoformat() if job.heartbeat_at else None,
            "recovery_count": job.recovery_count,
            "status_url": f"/orders/{job.order_id}/analysis-jobs/{job.job_id}",
            "result_url": f"/orders/{job.order_id}/analysis-jobs/{job.job_id}/result"}


async def submit_analysis(db, order, user_id, request, *, enqueue=True):
    root = Path(get_settings().OUTPUT_DIR) / order.order_code
    try:
        directory = input_directory(root, request.get("input_revision"))
        frozen = json.loads((directory/"manifest.json").read_text())
    except FileNotFoundError as exc:
        raise HTTPException(409, detail={"reason": "immutable_analysis_input_missing", "action": "publish_preprocessing_snapshot"}) from exc
    scope = request.get("analysis_scope", "full_eligible")
    if scope not in {"full_eligible", "explicit_subset"}:
        raise HTTPException(422, "invalid analysis_scope")
    if scope == "explicit_subset" and (not request.get("analysis_feature_ids") or not request.get("subset_reason")):
        raise HTTPException(422, "explicit subset requires feature IDs and a reason")
    from app.services.production_temporal_analysis import effective_production_config
    try:
        effective_tmm = effective_production_config(request.get("tmm_config") or {})
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    config = {"analysis_scope": scope, "tmm_config": effective_tmm,
              "analysis_feature_ids": sorted(set(request.get("analysis_feature_ids") or [])) if scope == "explicit_subset" else [],
              "subset_reason": request.get("subset_reason") if scope == "explicit_subset" else None,
              "allocation_version": ALLOCATION_VERSION, "rng_policy": RNG_POLICY_VERSION,
              "runtime": runtime_signature(), "references": reference_signature(),
              "analysis_context": {**(frozen.get("config", {}).get("experimental_context") or {}),
                  **(frozen.get("config", {}).get("analysis_context") or {}), **(order.analysis_context or {}),
                  "sample_manifest": frozen.get("config", {}).get("sample_manifest") or (order.analysis_context or {}).get("sample_manifest", {})},
              "parent_generation": frozen.get("parent_generation"), "input_options": frozen.get("config", {}).get("analysis_options", {}), "ptm_type": order.ptm_type}
    digest = signature({"order_id": order.id, "input_revision": frozen["input_revision"], "config": config})
    # An Order row already exists and is the admission lock even before its head
    # row is created. This avoids the race of locking a nonexistent head.
    await db.execute(select(Order.id).where(Order.id == order.id).with_for_update())
    existing = (await db.execute(select(AnalysisJob).where(AnalysisJob.order_id == order.id,
        AnalysisJob.input_signature == digest, AnalysisJob.execution_status.in_(["queued", "running", "completed"]))
        .order_by(AnalysisJob.created_at.desc()))).scalars().first()
    if existing:
        if existing.execution_status == "completed":
            import asyncio
            await asyncio.to_thread(verify_result, root / existing.result_path)
        await db.commit()
        return existing
    head = None
    if scope == "full_eligible":
        head = await db.get(AnalysisHead, order.id)
        if head is None:
            head = AnalysisHead(order_id=order.id, generation=0)
            db.add(head)
        head.generation += 1
    job = AnalysisJob(job_id=str(uuid4()), order_id=order.id, user_id=user_id,
        input_revision=frozen["input_revision"], input_signature=digest,
        active_key=f"{order.id}:{digest}", generation=head.generation if head else 0,
        request_config=config, execution_status="queued", evaluation_status="not_evaluable", stage_status={})
    if head is not None:
        head.requested_job_id = job.job_id
    db.add(job)
    await db.commit()
    if enqueue:
        try:
            enqueue_job(job.job_id)
        except Exception as exc:
            job.execution_status, job.failure_reason, job.active_key = "failed", "broker_unavailable", None
            await db.commit()
            raise HTTPException(503, detail=job_payload(job)) from exc
    return job


def enqueue_job(job_id):
    from app.tasks.production_tmm import celery_app
    return celery_app.send_task("app.tasks.production_tmm.execute", args=[job_id], task_id=job_id, queue="production_tmm")


async def authorized_job(db, order_id, job_id):
    job = await db.get(AnalysisJob, job_id)
    if job is None or job.order_id != order_id:
        raise HTTPException(404, "Analysis job not found")
    return job
