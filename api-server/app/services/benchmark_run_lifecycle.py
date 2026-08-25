"""Lifecycle helpers for Order-linked blind benchmark runs.

A BenchmarkRun is the user-visible record. The child Order is only a sanitized
snapshot runtime. Ordinary Order start/re-run must not create extra runs, must
not chain into RAG/LLM, and must keep the source Benchmark tab in sync.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

TMM_ACCEPT_STALE_AFTER_SEC = 3 * 60 * 60
"""Seconds after tmm_accepted_at_utc without an artifact before the UI treats TMM as interrupted.

docs/implementation_log.md [2026-08-26] Blind TMM 재시도가 화면에서 무반응으로 보이던 실행 게이트.
측정 상수가 아니다. 이 값으로 점수나 TMM 산출을 바꾸지 않는다.
"""


CHILD_PIPELINE_STATUSES = frozenset(
    {"queued", "preprocessing", "rag_enrichment", "report_generation"}
)
OFFICIAL_CHILD_LIVE_STATUSES = frozenset({"queued", "preprocessing"})
OFF_CONTRACT_CHILD_STATUSES = frozenset({"rag_enrichment", "report_generation"})
OFF_CONTRACT_CHILD_MESSAGE = (
    "Off-contract RAG/report leftover. Locked scoring uses 0층 outputs only."
)
REUSABLE_RUN_STATUSES = frozenset({"registered", "failed"})
IN_FLIGHT_RUN_STATUSES = frozenset(
    {"snapshot_pending", "preprocessing", "temporal_analysis", "scoring_queued", "scoring"}
)
SCORED_RUN_STATUSES = frozenset({"completed", "scoring", "scoring_queued", "temporal_analysis"})


def is_benchmark_child(order: Any) -> bool:
    """True when this Order is a sanitized blind-benchmark snapshot."""

    options = getattr(order, "analysis_options", None) or {}
    if isinstance(options, dict) and options.get("benchmark_blind_mode"):
        return True
    code = str(getattr(order, "order_code", "") or "")
    return code.startswith("bm_bmr-")


def should_reuse_existing_run(run_status: str, child_status: str | None) -> bool:
    """Reuse a leftover run instead of registering another snapshot."""

    if run_status in REUSABLE_RUN_STATUSES:
        return True
    if run_status == "preprocessing" and child_status in {None, "failed", "cancelled"}:
        return True
    return False


def is_run_in_progress(run_status: str, child_status: str | None) -> bool:
    if run_status in IN_FLIGHT_RUN_STATUSES and child_status not in OFF_CONTRACT_CHILD_STATUSES:
        return True
    if child_status in OFFICIAL_CHILD_LIVE_STATUSES:
        return True
    return False


def overlay_run_status(
    run_status: str,
    child_status: str | None,
    child_error: str | None,
    run_error: str | None,
) -> tuple[str, str | None]:
    """Map the child Order's live pipeline onto BenchmarkRun.status.

    Re-analysis from the Order list updates the child Order only. The source
    Order Benchmark tab reads BenchmarkRun rows, so a failed run would otherwise
    stay failed while the child is already running again.
    """

    if run_status in SCORED_RUN_STATUSES:
        return run_status, run_error
    if child_status in OFF_CONTRACT_CHILD_STATUSES:
        return "cancelled", OFF_CONTRACT_CHILD_MESSAGE
    if child_status in OFFICIAL_CHILD_LIVE_STATUSES:
        return "preprocessing", None
    if child_status == "failed":
        return "failed", child_error or run_error
    if child_status == "cancelled":
        return "cancelled", "Blind snapshot was cancelled. This leftover run is not the active score path."
    if child_status == "completed" and run_status in {"failed", "registered", "cancelled"}:
        return "preprocessing", None
    return run_status, run_error


def tmm_job_state(
    run_status: str,
    provenance: dict[str, Any] | None,
    artifact_path: str | None,
) -> str | None:
    """Classify a temporal_analysis row as live or leftover.

    A 524/restart leftover has status temporal_analysis and no accept stamp.
    Retry writes tmm_accepted_at_utc so the Benchmark tab can change immediately.
    """

    if run_status != "temporal_analysis":
        return None
    if artifact_path:
        return "running"
    accepted = (provenance or {}).get("tmm_accepted_at_utc")
    if not accepted:
        return "interrupted"
    try:
        stamp = datetime.fromisoformat(str(accepted).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
    except ValueError:
        return "interrupted"
    age = (datetime.now(timezone.utc) - stamp).total_seconds()
    if age > TMM_ACCEPT_STALE_AFTER_SEC:
        return "interrupted"
    return "running"


def run_phase(run_status: str, child_status: str | None) -> str:
    """UI phase for a stored run. History rows stay; only one is usually actionable."""

    status, _ = overlay_run_status(run_status, child_status, None, None)
    if status in {"completed", "scoring", "scoring_queued", "temporal_analysis"}:
        return status
    if child_status == "completed":
        return "ready_for_tmm"
    if child_status in OFF_CONTRACT_CHILD_STATUSES:
        return "abandoned"
    if child_status in OFFICIAL_CHILD_LIVE_STATUSES:
        return "snapshot_running"
    if status == "cancelled" or child_status == "cancelled":
        return "abandoned"
    if status == "failed":
        return "failed"
    return status


def apply_blind_child_task_config(task_config: dict[str, Any], benchmark_run_id: int) -> dict[str, Any]:
    """Force the 0층-only contract when a child Order is started from Order list."""

    task_config["chain_to_next"] = False
    task_config["benchmark_run_id"] = benchmark_run_id
    task_config["chromadb_collections"] = []
    task_config["research_questions"] = []
    return task_config
