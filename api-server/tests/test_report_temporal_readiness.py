"""Source-level contract checks for temporal evidence readiness before Report reruns."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ORDERS_API = ROOT / "api-server" / "app" / "api" / "orders.py"
RERUN_MODAL = ROOT / "frontend" / "src" / "components" / "RerunOptionsModal.tsx"
ORDER_DETAIL = ROOT / "frontend" / "src" / "pages" / "OrderDetail.tsx"
KINASE_MODULE = ROOT / "frontend" / "src" / "components" / "KinaseModuleAnalysis.tsx"


def test_order_detail_exposes_production_temporal_evidence_readiness() -> None:
    source = ORDERS_API.read_text(encoding="utf-8")
    assert "def _temporal_evidence_readiness" in source
    assert '"temporal_evidence_readiness": temporal_evidence_readiness' in source
    assert '"kinase_activity_heatmap": order.kinase_activity_heatmap' in source
    assert '"temporal_ptm_protein_analysis_v2.json"' in source
    assert "evaluate_temporal_evidence_readiness" in source


def test_missing_sidecar_rerun_dispatches_preparation_before_report() -> None:
    source = ORDERS_API.read_text(encoding="utf-8")
    assert "temporal_preparation_required" in source
    assert '"rag_enrichment.tasks.prepare_temporal_evidence_for_report"' in source
    assert '"stage": "temporal_evidence_preparation"' in source
    assert '"preparation_dispatched": temporal_preparation_required' in source
    assert 'new_status = "rag_enrichment" if temporal_preparation_required' in source


def test_rerun_ui_distinguishes_kinase_modules_from_temporal_evidence() -> None:
    modal = RERUN_MODAL.read_text(encoding="utf-8")
    detail = ORDER_DETAIL.read_text(encoding="utf-8")
    assert "Temporal evidence ready" in modal
    assert "Temporal evidence will be prepared before Report generation" in modal
    assert "Prepare Temporal Evidence + Re-run Report" in detail
    kinase_module = KINASE_MODULE.read_text(encoding="utf-8")
    assert 'dynamic_co_wave_transition_contract_version === "dynamic_co_wave_transition.v2"' in kinase_module
