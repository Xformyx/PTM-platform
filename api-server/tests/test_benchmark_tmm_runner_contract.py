from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_tmm_endpoint_queues_durable_celery_work_not_an_api_background_task() -> None:
    route_source = (REPO_ROOT / "api-server/app/api/benchmarks.py").read_text(encoding="utf-8")
    assert "enqueue_benchmark_tmm(run.id" in route_source
    assert "asyncio.create_task" not in route_source
    assert "benchmark_tmm" in route_source


def test_compose_declares_durable_truth_free_tmm_runner() -> None:
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "benchmark-tmm-runner:" in compose
    assert "-Q benchmark_tmm" in compose
    tmm_block = compose.split("  benchmark-tmm-runner:", 1)[1].split("  celery-worker-rag:", 1)[0]
    assert "./benchmarks:/opt/benchmarks:ro" not in tmm_block


def test_durable_tmm_executor_records_phase_heartbeats_and_short_stale_recovery() -> None:
    executor = (REPO_ROOT / "api-server/app/services/benchmark_tmm_executor.py").read_text(encoding="utf-8")
    lifecycle = (REPO_ROOT / "api-server/app/services/benchmark_run_lifecycle.py").read_text(encoding="utf-8")
    assert "tmm_heartbeat_utc" in executor
    assert "computing_tmm_heatmap" in executor
    assert "TMM_ACCEPT_STALE_AFTER_SEC = 30 * 60" in lifecycle


def test_benchmark_api_exposes_qualitative_execution_stage_not_inferred_tmm_percentage() -> None:
    route_source = (REPO_ROOT / "api-server/app/api/benchmarks.py").read_text(encoding="utf-8")
    assert '"execution": _execution_status(run, child)' in route_source
    assert "computing_tmm_heatmap" in route_source
    assert "scientifically meaningful percentage" in route_source


def test_strict_runner_uses_frozen_truth_free_config_and_multi_candidate_graph() -> None:
    executor = (REPO_ROOT / "api-server/app/services/benchmark_tmm_executor.py").read_text(encoding="utf-8")
    orders = (REPO_ROOT / "api-server/app/api/orders.py").read_text(encoding="utf-8")
    assert "SITE_AGGREGATION" in executor
    assert "WAVE_CONFIG" in executor
    assert '"tmm_config": TMM_CONFIG' in executor
    assert '"include_tmm_candidate_modules": True' in executor
    assert 'annotated.get("tmm_candidate_modules")' in executor
    assert "include_v2_extensions=True" in executor
    assert "tmm_motif_candidate_members" in orders
    assert '"stage": "pre_temporal_redistribution"' in orders
