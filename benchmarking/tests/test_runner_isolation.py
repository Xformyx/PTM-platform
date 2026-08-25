from __future__ import annotations


def test_offline_runner_task_imports_without_production_api_dependency() -> None:
    from benchmarking import tasks

    assert tasks.score_benchmark_run.name == "benchmarking.tasks.score_benchmark_run"
