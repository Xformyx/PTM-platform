"""RAG/report use the same server-owned temporal job as the interactive API."""
import json
import logging
import os
import time
from pathlib import Path

from celery.exceptions import TimeoutError as CeleryTimeout
from celery.result import allow_join_result
from celery_app import app
from common.db_engine import get_engine
from sqlalchemy import text
from ptm_shared.analysis_revision import verify_result

logger = logging.getLogger("ptm-workers.production-analysis")

PRODUCTION_TMM_QUEUE = "production_tmm"
PRODUCTION_TMM_TASK = "app.tasks.production_tmm.submit_order"

CONSUMER_WAIT_SECONDS = 30
"""No-consumer fail-fast window.

docs/BUILD_AND_DEPLOY.md §5, declared 2026-09-21 before this path landed.
Operational gate only. Changing it does not change TMM scores or τ.
"""

HEARTBEAT_SECONDS = 120
"""TMM-wait order_log interval.

docs/BUILD_AND_DEPLOY.md §5, declared 2026-09-21.
Must stay below WATCHDOG_NO_PROGRESS_STALL_MINUTES (60). Not a scientific
interval. Changing it does not change TMM output.
"""

JOIN_TIMEOUT_SECONDS = 21780
"""Existing join ceiling; matches production_tmm time_limit 21720.

docs/BUILD_AND_DEPLOY.md §5. Used by complete_production_analysis before
2026-09-21. Not a measurement constant.
"""


def _queue_name(entry):
    if isinstance(entry, dict):
        return entry.get("name") or entry.get("routing_key")
    return entry


def production_tmm_queue_has_consumer(inspector=None, queue=PRODUCTION_TMM_QUEUE) -> bool:
    """True when any Celery worker is consuming the production TMM queue."""
    inspect = inspector or app.control.inspect(timeout=5.0)
    try:
        queues = inspect.active_queues()
    except Exception as exc:
        logger.warning("production_tmm consumer inspect failed: %s", exc)
        return False
    if not queues:
        return False
    for _worker, qlist in queues.items():
        for entry in qlist or []:
            if _queue_name(entry) == queue:
                return True
    return False


def require_production_tmm_consumer(
    *,
    wait_seconds=CONSUMER_WAIT_SECONDS,
    poll_seconds=2.0,
    has_consumer=None,
):
    """Fail before enqueue when nobody is listening on production_tmm.

    구현 대상: docs/BUILD_AND_DEPLOY.md §5 CONSUMER_WAIT_SECONDS
    사전등록: 해당 없음 (운영 게이트, 2026-09-21).
    해석 한계: 워커 유무만 본다. TMM 수렴·kinase 귀속을 말하지 않는다.
    주장 금지: 이 검사로 분석 품질을 논하지 않는다.
    """
    checker = has_consumer or production_tmm_queue_has_consumer
    deadline = time.monotonic() + wait_seconds
    while True:
        if checker():
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(
                "production_tmm_worker_unavailable: no consumer on queue "
                f"{PRODUCTION_TMM_QUEUE!r} after {wait_seconds}s"
            )
        time.sleep(min(poll_seconds, remaining))


def _tmm_wait_snapshot(order_id: int) -> str:
    try:
        with get_engine().connect() as connection:
            row = connection.execute(
                text(
                    "SELECT execution_status, heartbeat_at FROM analysis_jobs "
                    "WHERE order_id=:oid ORDER BY created_at DESC LIMIT 1"
                ),
                {"oid": order_id},
            ).mappings().first()
        if not row:
            return "job=pending"
        status = row["execution_status"] or "unknown"
        heartbeat = row["heartbeat_at"]
        if heartbeat:
            return f"job={status}, tmm_heartbeat={heartbeat}"
        return f"job={status}"
    except Exception:
        return "job=unknown"


def wait_for_production_tmm_result(
    task,
    order_id,
    *,
    timeout=JOIN_TIMEOUT_SECONDS,
    heartbeat_seconds=HEARTBEAT_SECONDS,
    has_consumer=None,
    now=None,
):
    """Block on the TMM AsyncResult and keep order_logs alive for the watchdog.

    구현 대상: docs/BUILD_AND_DEPLOY.md §5 HEARTBEAT_SECONDS
    사전등록: 해당 없음 (운영 게이트, 2026-09-21).
    해석 한계: 로그 heartbeat는 대기 중임을 알릴 뿐 sidecar 내용을 바꾸지 않는다.
    주장 금지: heartbeat 횟수로 분석이 진행·개선되었다고 쓰지 않는다.
    """
    from common.progress import publish_progress
    from common.run_control import abort_if_superseded

    checker = has_consumer or production_tmm_queue_has_consumer
    clock = now or time.monotonic
    deadline = clock() + timeout
    started = clock()
    missing_since = None
    with allow_join_result():
        while True:
            abort_if_superseded(order_id)
            if not checker():
                if missing_since is None:
                    missing_since = clock()
                elif clock() - missing_since >= CONSUMER_WAIT_SECONDS:
                    raise RuntimeError(
                        "production_tmm_worker_unavailable: consumer disappeared "
                        f"while waiting for {getattr(task, 'id', 'unknown')}"
                    )
            else:
                missing_since = None
            remaining = deadline - clock()
            if remaining <= 0:
                raise TimeoutError(
                    f"production_tmm_join_timeout: no result after {timeout}s"
                )
            slice_s = min(heartbeat_seconds, remaining)
            try:
                return task.get(timeout=slice_s, propagate=True)
            except CeleryTimeout:
                elapsed = int(clock() - started)
                publish_progress(
                    order_id,
                    "rag_enrichment",
                    "temporal_evidence_preparation",
                    "running",
                    90,
                    f"Waiting for production TMM ({elapsed}s, {_tmm_wait_snapshot(order_id)})",
                )


def complete_production_analysis(order_id, config):
    """Wait for the dedicated production TMM job and return its sidecar.

    구현 대상: docs/BUILD_AND_DEPLOY.md §5 (consumer fail-fast + wait heartbeat)
    사전등록: 해당 없음 (운영 게이트, 2026-09-21 선언).
    해석 한계: 워커 유무와 로그 heartbeat만 다룬다. TMM 점수·τ를 바꾸지 않는다.
    주장 금지: 이 대기가 kinase 예측을 개선했다고 쓰지 않는다.
    """
    from common.run_control import abort_if_superseded

    abort_if_superseded(order_id)
    require_production_tmm_consumer()
    task = app.send_task(
        PRODUCTION_TMM_TASK,
        args=[order_id, {"analysis_scope": "full_eligible", "tmm_config": config.get("tmm_config") or {}}],
        queue=PRODUCTION_TMM_QUEUE,
    )
    # This orchestration worker waits; all computation lives in the dedicated
    # queue. A disconnected browser has no bearing on this dependency.
    response = wait_for_production_tmm_result(task, order_id)
    abort_if_superseded(order_id)
    if response.get("execution_status") != "completed":
        raise RuntimeError("required_production_analysis_" + str(response.get("execution_status")))
    with get_engine().connect() as connection:
        row = connection.execute(text("SELECT j.result_path, o.order_code FROM analysis_jobs j JOIN orders o ON o.id=j.order_id WHERE j.job_id=:job AND j.order_id=:oid AND j.execution_status='completed'"),
                                 {"job": response["job_id"], "oid": order_id}).mappings().one()
    directory = Path(os.getenv("OUTPUT_DIR", "/app/data/outputs")) / row["order_code"] / row["result_path"]
    revision = verify_result(directory)
    result = json.loads((directory/"result.json").read_text())
    candidates = json.loads((directory/"candidates.json").read_text())["manifest"]
    summary = result["temporal_ptm_protein_analysis"]
    summary["artifact_path"] = str((directory/"temporal_diagnostics.json").relative_to(directory.parents[2]))
    return {"kinase_analysis_data": {"analysis_manifest_id": candidates["analysis_manifest_id"],
                "result_path": row["result_path"], "revision_id": revision["revision_id"], "analysis_job_id": response["job_id"],
                "coverage": result["coverage"], "kinase_modules": candidates["candidate_modules"],
                "temporal_ptm_protein_analysis": summary},
            "kinase_activity_heatmap": result, "temporal_ptm_protein_analysis": summary,
            "analysis_revision": revision, "analysis_job_id": response["job_id"]}
