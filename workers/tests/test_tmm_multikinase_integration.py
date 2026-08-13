from ptm_shared.tmm_multikinase_integration import (
    build_kinase_cowave_groups,
    build_tmm_evidence_profile,
    build_tmm_kinase_pair_directionality,
    build_tmm_weighted_temporal_cascade,
)


CONDITIONS = ["0min", "5min", "15min", "30min"]


def _scores():
    return [
        {
            "kinase": "AKT1",
            "canonical": "AKT1",
            "tmm_weighted_up_sums": {"0min": 0.0, "5min": 1.4, "15min": 1.0, "30min": 0.2},
            "tmm_weighted_down_sums": {condition: 0.0 for condition in CONDITIONS},
            "tmm_weighted_up_counts": {"0min": 0.0, "5min": 2.0, "15min": 1.0, "30min": 0.0},
            "tmm_weighted_down_counts": {condition: 0.0 for condition in CONDITIONS},
            "tmm_n_exclusive": 4,
            "tmm_n_shared": 2,
            "tmm_profile_type": "data_driven",
            "tmm_evidence": build_tmm_evidence_profile({"profile_type": "data_driven", "n_exclusive": 4, "n_shared": 2}),
        },
        {
            "kinase": "S6K",
            "canonical": "S6K",
            "tmm_weighted_up_sums": {"0min": 0.0, "5min": 0.1, "15min": 0.5, "30min": 1.6},
            "tmm_weighted_down_sums": {condition: 0.0 for condition in CONDITIONS},
            "tmm_weighted_up_counts": {"0min": 0.0, "5min": 0.0, "15min": 1.0, "30min": 2.0},
            "tmm_weighted_down_counts": {condition: 0.0 for condition in CONDITIONS},
            "tmm_n_exclusive": 1,
            "tmm_n_shared": 5,
            "tmm_profile_type": "gaussian_fallback",
            "tmm_evidence": build_tmm_evidence_profile({"profile_type": "gaussian_fallback", "n_exclusive": 1, "n_shared": 5}),
        },
    ]


def test_sparse_and_fallback_profiles_are_explicitly_prior_assisted():
    profile = build_tmm_evidence_profile({"profile_type": "gaussian_fallback", "n_exclusive": 1, "n_shared": 4})
    assert profile["confidence_tier"] == "tmm_prior_assisted"
    assert "expected_peak_gaussian_fallback" in profile["confidence_flags"]


def test_weighted_cascade_keeps_fractional_activity_separate_from_raw_membership():
    cascade = build_tmm_weighted_temporal_cascade(_scores(), CONDITIONS)
    assert cascade["score_provenance"] == "tmm_weighted"
    assert cascade["timepoints"][1]["active_kinases"][0]["kinase"] == "AKT1"
    assert cascade["timepoints"][3]["active_kinases"][0]["kinase"] == "S6K"
    assert cascade["timepoints"][3]["active_kinases"][0]["tmm_evidence"]["confidence_tier"] == "tmm_prior_assisted"


def test_tmm_weighted_groups_and_kinase_pair_directionality_preserve_noncausal_boundary():
    scores = _scores()
    groups = build_kinase_cowave_groups(scores, CONDITIONS, provenance="tmm_weighted")
    assert isinstance(groups, list)
    cascade = build_tmm_weighted_temporal_cascade(scores, CONDITIONS)
    relations = build_tmm_kinase_pair_directionality(cascade, CONDITIONS)
    for relation in relations:
        assert relation["source_type"] == "tmm_weighted_kinase_profile"
        assert relation["causality_status"] == "not_tested"
