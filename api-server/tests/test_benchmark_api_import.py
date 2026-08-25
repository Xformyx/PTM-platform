from __future__ import annotations

from pathlib import Path


def test_benchmark_router_exposes_registration_and_execution_endpoints() -> None:
    api_root = Path(__file__).resolve().parents[1] / "app" / "api"
    source = (api_root / "benchmarks.py").read_text(encoding="utf-8")
    main_source = (api_root.parent / "main.py").read_text(encoding="utf-8")
    assert '"/source-orders/{order_id}/preflight"' in source
    assert '"/runs/{run_id}/start"' in source
    assert '"/runs/{run_id}/run-temporal-analysis"' in source
    assert "app.include_router(benchmarks.router, prefix=\"/api\")" in main_source
