"""Contract tests for server-side one-click temporal PTM–protein analysis.

These tests intentionally inspect source-level integration seams instead of
requiring a MySQL/Redis/Celery runtime.  Numeric sidecar behavior is covered by
the shared-engine tests; these checks prevent an accidental return-before-TMM,
missing worker import path, or dispatch flag regression from restoring a
frontend-tab-dependent workflow.
"""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RAG_TASKS = ROOT / "workers" / "rag_enrichment" / "tasks.py"
PREPROCESSING_TASKS = ROOT / "workers" / "preprocessing" / "tasks.py"
REPORT_TASKS = ROOT / "workers" / "report_generation" / "tasks.py"
REPORT_SIDECAR_RESOLVER = ROOT / "workers" / "report_generation" / "core" / "temporal_sidecar_resolution.py"
USER_ORDERS = ROOT / "api-server" / "app" / "api" / "user_orders.py"
COMPOSE = ROOT / "docker-compose.yml"
FRONTEND = ROOT / "frontend" / "src" / "components" / "KinaseModuleAnalysis.tsx"


def _function_source(path: Path, name: str) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return "\n".join(source.splitlines()[node.lineno - 1:node.end_lineno])
    raise AssertionError(f"function not found: {name}")


def test_rag_worker_reaches_tmm_before_heatmap_return() -> None:
    heatmap = _function_source(RAG_TASKS, "_compute_kinase_activity_heatmap")
    assert "compute_weighted_kinase_scores" in heatmap
    assert heatmap.index("compute_weighted_kinase_scores") < heatmap.rindex("return {")
    assert '"tmm_execution_status"' in heatmap


def test_worker_builds_and_persists_shared_artifact_server_side() -> None:
    auto_analysis = _function_source(RAG_TASKS, "_auto_run_global_analysis")
    assert "run_temporal_ptm_protein_analysis" in auto_analysis
    assert "build_production_temporal_ptm_protein_analysis" in auto_analysis
    assert "temporal_ptm_protein_analysis_v2.json" in auto_analysis
    assert "temporal_ptm_protein_analysis" in auto_analysis
    assert "temporal_ptm_protein_analysis" in PREPROCESSING_TASKS.read_text(encoding="utf-8")
    assert '"run_temporal_ptm_protein_analysis": True' in USER_ORDERS.read_text(encoding="utf-8")


def test_report_resolves_sidecar_from_chained_config_and_production_artifact() -> None:
    """A DB read-after-write race must not make the Report temporal packet empty."""
    report_task = _function_source(REPORT_TASKS, "run_report_generation")
    assert "config_kinase_analysis_data" in report_task
    assert "config_kinase_activity_heatmap" in report_task
    assert '"temporal_ptm_protein_analysis_v2.json"' in report_task
    assert "resolve_report_temporal_sidecar" in report_task
    assert "kinase_activity_heatmap_for_report" in report_task
    assert '"temporal_ptm_protein_analysis": temporal_ptm_protein_analysis_from_db' in report_task
    resolver = REPORT_SIDECAR_RESOLVER.read_text(encoding="utf-8")
    assert "chained_report_config.kinase_analysis_data" in resolver
    assert "chained_report_config.kinase_activity_heatmap" in resolver
    assert "summarize_temporal_ptm_protein_analysis" in resolver


def test_report_rerun_preparation_task_blocks_empty_packet_dispatch() -> None:
    rag_source = RAG_TASKS.read_text(encoding="utf-8")
    assert 'name="rag_enrichment.tasks.prepare_temporal_evidence_for_report"' in rag_source
    assert "_auto_run_global_analysis(order_id, enriched_data, config)" in rag_source
    assert "canonical temporal sidecar was not produced" in rag_source
    assert "report_generation.tasks.run_report_generation" in rag_source


def test_rag_container_can_import_canonical_api_tmm_scorer() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")
    rag_block = compose.split("  celery-worker-rag:", 1)[1].split("\n  celery-worker", 1)[0]
    assert "./api-server/app:/opt/api_server_app:ro" in rag_block
    assert "PYTHONPATH: /app:/opt:/opt/api_server_app" in rag_block


def test_frontend_marks_server_completed_artifact_ready() -> None:
    frontend = FRONTEND.read_text(encoding="utf-8")
    assert "temporalArtifactReady" in frontend
    assert "Temporal PTM–protein artifact ready" in frontend
    assert "Re-run Global Annotation" in frontend
