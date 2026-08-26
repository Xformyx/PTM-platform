from ptm_shared.tmm_multikinase_integration import build_tmm_weighted_temporal_cascade


CONDITIONS = ["1min", "5min", "15min"]


def _entry(name, sums, counts):
    return {
        "kinase": name,
        "canonical": name,
        "tmm_weighted_up_sums": dict(zip(CONDITIONS, sums)),
        "tmm_weighted_down_sums": {condition: 0.0 for condition in CONDITIONS},
        "tmm_weighted_up_counts": dict(zip(CONDITIONS, counts)),
        "tmm_weighted_down_counts": {condition: 0.0 for condition in CONDITIONS},
        "tmm_evidence": {"confidence_tier": "tmm_data_anchored"},
    }


def test_default_weighted_sum_preserves_legacy_rank_and_parallel_tracks() -> None:
    cascade = build_tmm_weighted_temporal_cascade(
        [_entry("LARGE", [10, 8, 6], [10, 10, 10]), _entry("SMALL", [5, 4, 3], [1, 1, 1])],
        CONDITIONS,
    )
    first = cascade["timepoints"][0]["active_kinases"]
    assert [row["kinase"] for row in first] == ["LARGE", "SMALL"]
    assert first[0]["raw_weighted_sum"] == 10.0
    assert first[0]["activity_effect_size"] == 1.0
    assert cascade["kinase_profiles"] == cascade["kinase_profiles_raw_sum"]


def test_weighted_mean_separates_effect_size_from_evidence_mass() -> None:
    cascade = build_tmm_weighted_temporal_cascade(
        [_entry("LARGE", [10, 8, 6], [10, 10, 10]), _entry("SMALL", [5, 4, 3], [1, 1, 1])],
        CONDITIONS,
        activity_metric="weighted_mean",
    )
    first = cascade["timepoints"][0]["active_kinases"]
    assert [row["kinase"] for row in first] == ["SMALL", "LARGE"]
    assert first[0]["selected_activity"] == 5.0
    assert first[0]["evidence_mass"] == 1.0
    assert cascade["kinase_profiles"] == cascade["kinase_profiles_effect_size"]


def test_shrunken_mean_penalizes_low_support_without_discarding_effect_size() -> None:
    cascade = build_tmm_weighted_temporal_cascade(
        [_entry("LOW_SUPPORT", [5, 5, 5], [1, 1, 1])],
        CONDITIONS,
        activity_metric="shrunken_mean",
        shrinkage_prior_support=4.0,
        activity_threshold=0.0,
    )
    row = cascade["timepoints"][0]["active_kinases"][0]
    assert row["activity_effect_size"] == 5.0
    assert row["shrinkage_factor"] == 0.2
    assert row["shrunken_activity"] == 1.0
    assert row["selected_activity"] == 1.0
