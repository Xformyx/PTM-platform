"""Tests for post-analysis causal-validation proposals and optional evidence."""

from ptm_shared.causal_validation import (
    evaluate_uploaded_perturbation_evidence,
    propose_causal_validation_experiments,
)


def _relationship(tier="D3_mechanistically_supported_directionality"):
    return {
        "source": {"key": "PI3K-wave"},
        "target": {"key": "AKT-wave"},
        "direction": "source_precedes_target",
        "directionality_tier": tier,
        "causality_status": "not_tested",
        "temporal_order_score": 1.0,
        "source_onset_minutes": 5,
        "target_onset_minutes": 10,
        "source_peak_minutes": 10,
        "target_peak_minutes": 15,
        "onset_lag_minutes": 5,
        "peak_lag_minutes": 5,
    }


def test_only_d2_d3_precedence_candidates_receive_post_analysis_recommendations():
    output = propose_causal_validation_experiments([
        _relationship(),
        {**_relationship("D1_temporal_precedence"), "target": {"key": "late-wave"}},
        {**_relationship(), "direction": "target_precedes_source", "target": {"key": "reverse-wave"}},
    ])

    assert output["eligible_relationship_count"] == 1
    assert len(output["recommendations"]) == 1
    assert output["recommendations"][0]["relationship_id"] == "PI3K-wave->AKT-wave"
    assert "not causal conclusions" in output["interpretation_boundary"]


def test_uploaded_evidence_is_condition_scoped_and_requires_matching_discovery_relation():
    output = evaluate_uploaded_perturbation_evidence(
        [_relationship()],
        [
            {
                "source": "PI3K-wave",
                "target": "AKT-wave",
                "control_mean": "1.0",
                "perturbed_mean": "0.2",
                "expected_target_change": "down",
                "q_value": "0.01",
            },
            {
                "source": "unobserved",
                "target": "AKT-wave",
                "control_mean": "1.0",
                "perturbed_mean": "0.2",
                "expected_target_change": "down",
                "q_value": "0.01",
            },
        ],
    )

    assert output["summary"]["perturbation_supported"] == 1
    assert output["evaluations"][0]["causality_status"] == "perturbation_supported"
    assert len(output["rejected_rows"]) == 1
