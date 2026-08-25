from app.services.benchmark_run_lifecycle import (
    apply_blind_child_task_config,
    is_benchmark_child,
    is_run_in_progress,
    overlay_run_status,
    run_phase,
    should_reuse_existing_run,
)


class _Order:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def test_is_benchmark_child_from_options_or_code() -> None:
    assert is_benchmark_child(_Order(analysis_options={"benchmark_blind_mode": True}, order_code="x"))
    assert is_benchmark_child(_Order(analysis_options={}, order_code="bm_bmr-abc"))
    assert not is_benchmark_child(_Order(analysis_options={}, order_code="Insulin_Signaling_Dynamic_V1_All_PTMs"))


def test_failed_and_orphaned_preprocessing_runs_are_reused() -> None:
    assert should_reuse_existing_run("failed", "failed")
    assert should_reuse_existing_run("registered", None)
    assert should_reuse_existing_run("preprocessing", "failed")
    assert not should_reuse_existing_run("completed", "completed")
    assert not should_reuse_existing_run("preprocessing", "preprocessing")


def test_live_child_keeps_benchmark_tab_in_progress() -> None:
    assert overlay_run_status("failed", "preprocessing", None, "old") == ("preprocessing", None)
    assert overlay_run_status("failed", "rag_enrichment", None, "old")[0] == "cancelled"
    assert overlay_run_status("failed", "completed", None, "old") == ("preprocessing", None)
    assert overlay_run_status("failed", "failed", "child boom", "old") == ("failed", "child boom")
    assert overlay_run_status("failed", "cancelled", None, "old")[0] == "cancelled"
    assert overlay_run_status("scoring", "completed", None, None) == ("scoring", None)
    assert not is_run_in_progress("failed", "rag_enrichment")
    assert is_run_in_progress("preprocessing", "preprocessing")
    assert run_phase("failed", "completed") == "ready_for_tmm"
    assert run_phase("failed", "cancelled") == "abandoned"
    assert run_phase("preprocessing", "rag_enrichment") == "abandoned"


def test_child_start_cannot_chain_to_rag() -> None:
    config = apply_blind_child_task_config(
        {"chain_to_next": True, "chromadb_collections": ["c"], "research_questions": ["q"]},
        17,
    )
    assert config["chain_to_next"] is False
    assert config["benchmark_run_id"] == 17
    assert config["chromadb_collections"] == []
    assert config["research_questions"] == []
