"""Lifecycle helpers for Order-linked blind benchmark runs.

A BenchmarkRun is the user-visible record. The child Order is only a sanitized
snapshot runtime. Ordinary Order start/re-run must not create extra runs, must
not chain into RAG/LLM, and must keep the source Benchmark tab in sync.
"""

from __future__ import annotations

from typing import Any


CHILD_PIPELINE_STATUSES = frozenset(
    {"queued", "preprocessing", "rag_enrichment", "report_generation"}
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
    if run_status in IN_FLIGHT_RUN_STATUSES:
        return True
    if child_status in CHILD_PIPELINE_STATUSES:
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
    if child_status in CHILD_PIPELINE_STATUSES:
        return "preprocessing", None
    if child_status == "failed":
        return "failed", child_error or run_error
    if child_status == "cancelled":
        return "cancelled", "Blind snapshot was cancelled. This leftover run is not the active score path."
    if child_status == "completed" and run_status in {"failed", "registered", "cancelled"}:
        return "preprocessing", None
    return run_status, run_error


def run_phase(run_status: str, child_status: str | None) -> str:
    """UI phase for a stored run. History rows stay; only one is usually actionable."""

    status, _ = overlay_run_status(run_status, child_status, None, None)
    if status in {"completed", "scoring", "scoring_queued", "temporal_analysis"}:
        return status
    if child_status == "completed":
        return "ready_for_tmm"
    if child_status in CHILD_PIPELINE_STATUSES:
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
