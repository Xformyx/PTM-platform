"""RAG stage reruns must forward the stored Report audience contract."""

from app.api.orders import _report_chain_fields
from ptm_shared.report_mode import resolve_report_mode_contract


def test_rag_rerun_forwards_stored_researcher_contract():
    fields = _report_chain_fields({
        "report_config": {
            "report_audience": "researcher_manuscript",
            "reader_authoring_mode": "shadow",
            "technical_audit_delivery": "separate_sidecar",
            "technical_audit_explicit": False,
        },
        "research_questions": ["Which sites move?"],
        "analysis_mode": "ptm_only",
    }, secondary_ptm_type=None)
    contract = resolve_report_mode_contract(fields["report_config"])
    assert contract["valid"] is True
    assert contract["report_audience"] == "researcher_manuscript"
    assert contract["effective_reader_mode"] == "shadow"
    assert fields["research_questions"] == ["Which sites move?"]


def test_empty_report_options_do_not_invent_a_technical_audit():
    fields = _report_chain_fields(None)
    contract = resolve_report_mode_contract(fields["report_config"])
    assert contract["valid"] is False
    assert "missing_report_audience_contract" in contract["reason_codes"]
    assert contract["report_audience"] == ""
