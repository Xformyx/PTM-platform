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
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.pool import NullPool

from app.api.orders import global_kinase_modules, kinase_activity_heatmap
from app.config import get_settings
from app.models.benchmark_run import BenchmarkRun
from app.models.order import Order
from app.models.user import User
from app.services.benchmark_artifact import build_score_artifact, build_temporal_request
from ptm_shared.temporal_optimization_config import (
    SITE_AGGREGATION,
    TMM_CONFIG,
    WAVE_CONFIG,
    provenance as temporal_optimization_provenance,
)

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


_STAGE_LABELS: dict[str, str] = {
    "building_temporal_request": "Preparing canonical temporal Wave input",
    "computing_global_kinase_modules": "Computing production kinase modules",
    "computing_tmm_heatmap": "Computing TMM full temporal attribution",
    "writing_truth_free_artifact": "Archiving truth-free analysis artifact",
    "queueing_locked_score": "Queueing offline locked scoring",
}


async def _record_tmm_heartbeat(db, run: BenchmarkRun, stage: str) -> None:
    """Persist worker liveness so a stranded queue task becomes retryable promptly.

    Also appends an entry to provenance["log_entries"] so the UI can render a
    chronological stage log without a dedicated log-streaming endpoint.
    """

    now = datetime.now(timezone.utc).isoformat()
    provenance = dict(run.provenance or {})
    provenance["tmm_worker_stage"] = stage
    provenance["tmm_heartbeat_utc"] = now
    if "tmm_worker_started_at_utc" not in provenance:
        provenance["tmm_worker_started_at_utc"] = now
    entries: list[dict] = list(provenance.get("log_entries") or [])
    entries.append({"at_utc": now, "stage": stage, "label": _STAGE_LABELS.get(stage, stage)})
    provenance["log_entries"] = entries
    run.provenance = provenance
    flag_modified(run, "provenance")
    await db.commit()


async def execute_benchmark_tmm(run_id: int, user_id: int | None) -> dict[str, object]:
    """Persist a full-TMM artifact, or persist a terminal error for this run.

    A fresh NullPool engine is created per invocation so the async session is
    always bound to the event loop started by asyncio.run() in the Celery task.
    The module-level pooled engine (used by the web app) is intentionally avoided
    here: reusing a pool-attached connection across event loops raises
    "Future attached to a different loop" in asyncmy.
    """

    settings = get_settings()
    local_engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    LocalSession = async_sessionmaker(local_engine, class_=AsyncSession, expire_on_commit=False)

    logger.info("Durable blind TMM worker started for BenchmarkRun %s", run_id)
    try:
        result_dict = await _run_tmm_with_session(run_id, user_id, LocalSession)
    finally:
        await local_engine.dispose()
    return result_dict


async def _run_tmm_with_session(
    run_id: int,
    user_id: int | None,
    LocalSession: async_sessionmaker,
) -> dict[str, object]:
    """Inner implementation; separated so the engine is always disposed on exit."""

    async with LocalSession() as db:
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
                build_temporal_request,
                output_dir=output_dir,
                ptm_type=child.ptm_type,
                wave_config=WAVE_CONFIG,
                site_aggregation=SITE_AGGREGATION,
            )
            await _record_tmm_heartbeat(db, run, "computing_global_kinase_modules")
            annotated = await global_kinase_modules(
                child.id,
                {
                    "ptms": temporal_request["ptms"],
                    "cowave_modules": temporal_request["cowave_modules"],
                    "allow_motif_only_seed": True,
                    "include_tmm_candidate_modules": True,
                    "force_refresh": True,
                },
                db,
                service_user,
            )
            annotation_modules = (
                annotated.get("tmm_candidate_modules")
                or annotated.get("kinase_modules")
                or []
            )
            tmm_modules = [
                {
                    "kinase": module.get("canonical") or module.get("kinase"),
                    "evidence_tier": module.get("evidence_tier", "direct_or_contextual"),
                    "sources": module.get("sources", []),
                    "motif_candidate_count": module.get("motif_candidate_count", 0),
                    "ptms": [
                        {
                            "gene": member.get("gene"),
                            "position": member.get("position"),
                            "candidate_probability": member.get("candidate_probability"),
                            "candidate_raw_support": member.get("candidate_raw_support"),
                            "candidate_support_class": member.get("candidate_support_class"),
                            "candidate_likelihood_contract": member.get("candidate_likelihood_contract"),
                            "empirical_background_match_rate": member.get("empirical_background_match_rate"),
                            "empirical_information_bits": member.get("empirical_information_bits"),
                            "sequence_pattern_confirmed": member.get("sequence_pattern_confirmed"),
                            "hierarchy_family": member.get("hierarchy_family"),
                            "candidate_resolution_level": member.get("candidate_resolution_level"),
                        }
                        for member in module.get("members", [])
                        if member.get("gene") and member.get("position")
                    ],
                }
                for module in annotation_modules
            ]
            await _record_tmm_heartbeat(db, run, "computing_tmm_heatmap")
            tmm = await kinase_activity_heatmap(
                child.id,
                {
                    "kinase_modules": tmm_modules,
                    "tmm_config": TMM_CONFIG,
                    "force_refresh": True,
                },
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
                wave_config=WAVE_CONFIG,
                site_aggregation=SITE_AGGREGATION,
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
            "temporal_optimization": temporal_optimization_provenance(),
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
