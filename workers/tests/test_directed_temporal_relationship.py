"""Regression coverage for evidence-aware temporal directionality contracts."""

from ptm_shared.directed_temporal_relationship import (
    CONTRACT_VERSION,
    _tier,
    analyze_directed_temporal_relationship,
    validate_directed_temporal_relationship,
)


TIMEPOINTS = ["0min", "5min", "10min", "15min", "20min"]


def _profile(key, values, replicates=None):
    payload = {"key": key, "temporal_values": dict(zip(TIMEPOINTS, values))}
    if replicates is not None:
        payload["replicates"] = {timepoint: [value - 0.05, value, value + 0.05] for timepoint, value in zip(TIMEPOINTS, values)}
    return payload


def test_directionality_reports_minute_based_precedence_without_a_causal_claim():
    result = analyze_directed_temporal_relationship(
        _profile("TW-01", [0.0, 1.0, 2.0, 1.0, 0.5]),
        _profile("TW-02", [0.0, 0.0, 0.8, 2.0, 1.0]),
        TIMEPOINTS,
        config={"bootstrap_iterations": 0, "permutation_iterations": 0},
    )

    assert result["contract_version"] == CONTRACT_VERSION
    assert result["direction"] == "source_precedes_target"
    assert result["onset_lag_minutes"] == 5.0
    assert result["peak_lag_minutes"] == 5.0
    assert result["causality_status"] == "not_tested"
    assert result["directionality_tier"] == "D1_temporal_precedence"
    assert validate_directed_temporal_relationship(result) == []


def test_biological_support_does_not_promote_a_relationship_without_time_order_permutation_evidence():
    result = analyze_directed_temporal_relationship(
        _profile("PI3K-wave", [0.0, 1.0, 2.0, 1.0, 0.0], replicates=True),
        _profile("AKT-wave", [0.0, 0.0, 1.0, 2.0, 1.0], replicates=True),
        TIMEPOINTS,
        config={"bootstrap_iterations": 40, "permutation_iterations": 0},
        biological_support={"kinase_substrate_consistent": True},
    )

    assert result["evidence_profile"]["bootstrap"]["available"] is True
    assert result["evidence_profile"]["leave_one_timepoint"]["available"] is True
    assert result["directionality_tier"] == "D1_temporal_precedence"
    assert result["causality_status"] == "not_tested"


def test_d3_requires_reproducible_temporal_evidence_and_biological_support():
    tier, _ = _tier(
        {"direction": "source_precedes_target", "quality_flags": []},
        {"available": True, "stability": 0.95},
        {"available": True, "stability": 0.90},
        {"available": True, "p_value": 0.01},
        {"kinase_substrate_consistent": True},
    )
    assert tier == "D3_mechanistically_supported_directionality"


def test_insufficient_timepoints_are_explicitly_unresolved():
    result = analyze_directed_temporal_relationship(
        {"key": "A", "temporal_values": {"0min": 0.0, "5min": 1.0}},
        {"key": "B", "temporal_values": {"0min": 0.0, "5min": 0.5}},
        ["0min", "5min"],
    )

    assert result["direction"] == "unresolved"
    assert result["directionality_tier"] == "D0_unresolved"
    assert result["causality_status"] == "not_tested"
