from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from app.api.orders import _reject_astra_downstream_stage, _reject_undeclared_export_mode


def test_missing_purpose_is_not_stored_as_legacy():
    with pytest.raises(HTTPException) as exc:
        _reject_undeclared_export_mode(None, {"treatment": "insulin"})
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:
        _reject_undeclared_export_mode({"cell_type": "hepatocyte"}, {"biological_question": "response"})
    assert exc.value.status_code == 422


def test_explicit_purpose_and_inherited_purpose_are_accepted():
    _reject_undeclared_export_mode(None, {"quantitation_export_mode": "astra_analysis.v4"})
    _reject_undeclared_export_mode(
        {"quantitation_export_mode": "legacy_only.v1"},
        {"treatment": "insulin"},
    )
    _reject_undeclared_export_mode(
        {"quantitation_export_mode": "enrichment_free_timecourse.v3"},
        {},
    )


def test_astra_package_orders_do_not_enter_rag_or_report():
    order = SimpleNamespace(analysis_context={"quantitation_export_mode": "astra_analysis.v4"})
    _reject_astra_downstream_stage(order, "preprocessing")
    for stage in ("rag_enrichment", "report_generation"):
        with pytest.raises(HTTPException) as exc:
            _reject_astra_downstream_stage(order, stage)
        assert exc.value.status_code == 409
    legacy = SimpleNamespace(analysis_context={"quantitation_export_mode": "legacy_only.v1"})
    _reject_astra_downstream_stage(legacy, "report_generation")
    historical = SimpleNamespace(analysis_context={"treatment": "insulin"})
    _reject_astra_downstream_stage(historical, "rag_enrichment")
