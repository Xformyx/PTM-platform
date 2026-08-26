from ptm_shared.tmm_multikinase_integration import build_evidence_gated_tmm_directionality


def _cascade(source_tier="tmm_data_anchored", target_tier="tmm_prior_assisted"):
    return {
        "kinase_profiles": {
            "K1": {"1min": 1.0, "5min": 0.2, "15min": 0.0},
            "K2": {"1min": 0.0, "5min": 0.2, "15min": 1.0},
        },
        "tmm_evidence_by_kinase": {
            "K1": {"confidence_tier": source_tier},
            "K2": {"confidence_tier": target_tier},
        },
    }


def test_prior_assisted_endpoint_is_candidate_not_main_edge():
    result = build_evidence_gated_tmm_directionality(_cascade(), ["1min", "5min", "15min"])
    assert result["main_edges"] == []
    assert result["candidate_edges"]
    assert "target_profile_not_data_anchored" in result["candidate_edges"][0]["evidence_gate_reasons"]


def test_d1_relationship_remains_candidate_even_with_data_anchored_profiles():
    result = build_evidence_gated_tmm_directionality(
        _cascade("tmm_data_anchored", "tmm_data_anchored"),
        ["1min", "5min", "15min"],
    )
    assert result["main_edges"] == []
    assert result["candidate_edges"]
    assert "directionality_below_D2" in result["candidate_edges"][0]["evidence_gate_reasons"]
