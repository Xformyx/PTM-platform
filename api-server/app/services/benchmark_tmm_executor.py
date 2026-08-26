"""Durable executor for the strict-primary TMM stage.

This module deliberately contains no benchmark truth.  It runs the same
production global-kinase/TMM endpoints against the sanitized child Order and
persists a truth-free artifact before handing it to the isolated scorer queue.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from celery import Celery
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.api.orders import global_kinase_modules, kinase_activity_heatmap
from app.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.benchmark_run import BenchmarkRun
from app.models.order import Order
from app.models.user import User
from app.services.benchmark_artifact import build_score_artifact, build_temporal_request

logger = logging.getLogger(__name__)


class _ServiceUser:
    """Minimal server-side identity accepted by production temporal endpoints."""

    def __init__(self, source_user: object | None) -> None:
        self.id = getattr(source_user, "id", None)
        self.role = getattr(source_user, "role", "admin")


def enqueue_benchmark_tmm(run_id: int, user_id: int | None) -> str:
    celery_app = Celery("ptm_benchmark_tmm")
    celery_app.conf.broker_url = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/1")
    celery_app.conf.result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/2")
    task = celery_app.send_task(
        "app.tasks.benchmark_tmm.run_benchmark_tmm",
        args=[run_id, user_id],
        queue="benchmark_tmm",
    )
    return task.id


def enqueue_locked_score(run_id: int) -> str:
    celery_app = Celery("ptm_benchmark_runner")
    celery_app.conf.broker_url = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/1")
    celery_app.conf.result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/2")
    task = celery_app.send_task("benchmarking.tasks.score_benchmark_run", args=[run_id], queue="benchmark")
    return task.id


async def _record_tmm_heartbeat(db, run: BenchmarkRun, stage: str) -> None:
    """Persist worker liveness so a stranded queue task becomes retryable promptly."""

    provenance = dict(run.provenance or {})
    provenance["tmm_worker_stage"] = stage
    provenance["tmm_heartbeat_utc"] = datetime.now(timezone.utc).isoformat()
    if "tmm_worker_started_at_utc" not in provenance:
        provenance["tmm_worker_started_at_utc"] = provenance["tmm_heartbeat_utc"]
    run.provenance = provenance
    flag_modified(run, "provenance")
    await db.commit()


async def execute_benchmark_tmm(run_id: int, user_id: int | None) -> dict[str, object]:
    """Persist a full-TMM artifact, or persist a terminal error for this run."""

    logger.info("Durable blind TMM worker started for BenchmarkRun %s", run_id)
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(BenchmarkRun).where(BenchmarkRun.id == run_id))
        run = result.scalar_one_or_none()
        if not run or not run.benchmark_order_id:
            raise ValueError("BenchmarkRun or sanitized child Order is missing")
        child_result = await db.execute(select(Order).where(Order.id == run.benchmark_order_id))
        child = child_result.scalar_one_or_none()
        if not child:
            run.status = "failed"
            run.error_message = "Blind temporal analysis failed: sanitized child Order is missing"
            await db.commit()
            return {"benchmark_run_id": run_id, "status": "failed"}
        user = None
        if user_id:
            user_result = await db.execute(select(User).where(User.id == user_id))
            user = user_result.scalar_one_or_none()
        service_user = _ServiceUser(user)
        settings = get_settings()
        output_dir = Path(settings.OUTPUT_DIR) / child.order_code
        try:
            await _record_tmm_heartbeat(db, run, "building_temporal_request")
            temporal_request = await asyncio.to_thread(
                build_temporal_request, output_dir=output_dir, ptm_type=child.ptm_type
            )
            await _record_tmm_heartbeat(db, run, "computing_global_kinase_modules")
            annotated = await global_kinase_modules(
                child.id,
                {
                    "ptms": temporal_request["ptms"],
                    "cowave_modules": temporal_request["cowave_modules"],
                    "force_refresh": True,
                },
                db,
                service_user,
            )
            tmm_modules = [
                {
                    "kinase": module.get("canonical") or module.get("kinase"),
                    "ptms": [
                        {"gene": member.get("gene"), "position": member.get("position")}
                        for member in module.get("members", [])
                        if member.get("gene") and member.get("position")
                    ],
                }
                for module in annotated.get("kinase_modules", [])
            ]
            await _record_tmm_heartbeat(db, run, "computing_tmm_heatmap")
            tmm = await kinase_activity_heatmap(
                child.id,
                {"kinase_modules": tmm_modules, "force_refresh": True},
                db,
                service_user,
            )
            await _record_tmm_heartbeat(db, run, "writing_truth_free_artifact")
            artifact = await asyncio.to_thread(
                build_score_artifact,
                output_dir=output_dir,
                fasta_path=Path(child.fasta_path),
                ptm_type=child.ptm_type,
                production_contract=run.production_contract,
                tmm_result=tmm,
            )
            artifact_path = output_dir / "benchmark_blind_analysis_artifact.json"
            artifact_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            await _record_tmm_heartbeat(db, run, "queueing_locked_score")
            score_task_id = enqueue_locked_score(run.id)
        except Exception as exc:
            logger.exception("Blind TMM failed for BenchmarkRun %s", run_id)
            run.status = "failed"
            run.error_message = f"Blind temporal analysis failed: {exc}"[:2000]
            await db.commit()
            return {"benchmark_run_id": run_id, "status": "failed", "error": str(exc)}

        run.artifact_path = str(artifact_path)
        run.status = "scoring_queued"
        run.error_message = None
        provenance = {
            **(run.provenance or {}),
            "tmm_full_temporal_completed": True,
            "locked_score_task_id": score_task_id,
        }
        run.provenance = provenance
        flag_modified(run, "provenance")
        await db.commit()
        return {
            "benchmark_run_id": run_id,
            "status": "scoring_queued",
            "artifact_path": str(artifact_path),
            "locked_score_task_id": score_task_id,
        }
