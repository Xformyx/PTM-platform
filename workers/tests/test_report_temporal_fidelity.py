"""Tests for deterministic Report temporal evidence traceability auditing."""

from report_generation.core.report_temporal_fidelity import (
    audit_report_temporal_fidelity,
    strip_internal_data_labels,
)


def _packet() -> dict:
    return {
        "status": "available",
        "records": [
            {"evidence_id": "DATA-DYNAMIC-SUMMARY"},
            {"evidence_id": "DATA-CROSS-LAYER-1"},
        ],
    }


def test_audit_passes_for_traced_observational_claims():
    audit = audit_report_temporal_fidelity(
        "Wave-local co-movement was observed [DATA-DYNAMIC-SUMMARY]. "
        "A lagged protein candidate was temporally consistent [DATA-CROSS-LAYER-1].",
        _packet(),
    )
    assert audit["status"] == "pass"
    assert audit["cited_dynamic_record_count"] == 1
    assert audit["cited_cross_layer_record_count"] == 1
    assert audit["unsafe_temporal_claim_count"] == 0


def test_audit_flags_unsupported_ids_and_unsafe_temporal_causality():
    audit = audit_report_temporal_fidelity(
        "This transition causes the downstream response [DATA-DYNAMIC-SUMMARY]. "
        "Unknown result [DATA-CROSS-LAYER-99].",
        _packet(),
    )
    assert audit["status"] == "review_required"
    assert audit["unsafe_temporal_claim_count"] == 1
    assert audit["unsupported_record_ids"] == ["DATA-CROSS-LAYER-99"]


def test_audit_flags_uncited_signal_propagation_when_packet_disallows_mechanism_context():
    packet = _packet()
    packet["section_plan"] = {"mechanism_context_allowed": False}
    audit = audit_report_temporal_fidelity(
        "The observed pattern shows signal propagation through the cascade.",
        packet,
        section_type="results",
    )
    assert audit["status"] == "review_required"
    assert audit["unsafe_temporal_claim_count"] == 1
    assert audit["recommended_action"] == "constrained_rewrite_required"


def test_audit_marks_available_packet_without_trace_labels_as_untraced():
    audit = audit_report_temporal_fidelity("No numerical temporal claim.", _packet())
    assert audit["status"] == "untraced"
    assert strip_internal_data_labels("Observed [DATA-DYNAMIC-SUMMARY].") == "Observed ."
