from ptm_shared.kinase_footprint_diagnostics import (
    build_exact_footprint_equivalence,
    detection_aware_footprint_value,
    summarize_weighted_footprint,
)


def test_exact_equivalence_requires_identical_site_sets_not_near_overlap():
    groups, by_kinase = build_exact_footprint_equivalence({
        "KIN_A": ["SITE_1", "SITE_2"],
        "KIN_B": ["SITE_2", "SITE_1"],
        "KIN_C": ["SITE_1", "SITE_2", "SITE_3"],
    })

    assert len(groups) == 1
    assert groups[0]["equivalence"] == "exact_substrate_set"
    assert groups[0]["kinases"] == ["KIN_A", "KIN_B"]
    assert by_kinase["KIN_A"]["members"] == ["KIN_A", "KIN_B"]
    assert "KIN_C" not in by_kinase


def test_high_leverage_site_is_exposed_by_leave_one_out_without_score_rewrite():
    summary = summarize_weighted_footprint(
        {
            "SITE_MAJOR": {"T1": 30.0, "T2": 0.0},
            "SITE_MINOR": {"T1": -3.0, "T2": 2.0},
        },
        ["T1", "T2"],
        shrinkage_prior_support=5.0,
        max_leave_one_out=3,
    )

    assert summary["status"] == "computed"
    assert summary["full_peak_condition"] == "T1"
    assert summary["dominant_substrate_fraction"] > 0.8
    major = summary["leave_one_substrate_out"][0]
    assert major["site_key"] == "SITE_MAJOR"
    assert major["direction_preserved"] is False
    assert major["max_score_delta"] == 30.0


def test_effective_support_and_unique_only_comparison_are_weighted_and_diagnostic_only():
    summary = summarize_weighted_footprint(
        {
            "SITE_EXCLUSIVE_A": {"T1": 1.0, "T2": 1.0},
            "SITE_EXCLUSIVE_B": {"T1": 1.0, "T2": 1.0},
            "SITE_SHARED": {"T1": 8.0, "T2": 8.0},
        },
        ["T1", "T2"],
        shrinkage_prior_support=5.0,
        exclusive_site_keys=["SITE_EXCLUSIVE_A", "SITE_EXCLUSIVE_B"],
    )

    assert 1.0 < summary["effective_substrate_number"] < 3.0
    assert 0.0 < summary["support_shrinkage_factor"] < 1.0
    assert summary["unique_only_footprint"]["status"] == "computed"
    assert summary["unique_only_footprint"]["weighted_site_count"] == 2
    assert summary["unique_only_footprint"]["peak_score"] < summary["full_peak_score"]


def test_detection_aware_footprint_never_uses_extreme_denovo_pseudolog2fc():
    value, is_denovo = detection_aware_footprint_value(
        {
            "Conventional_Log2FC_NA": True,
            "Control_Pseudocount_Used": True,
            "DeNovo_Confidence": "high",
            "LOD_Relative_Log2": 99.0,
        },
        99.0,
    )
    conventional, conventional_is_denovo = detection_aware_footprint_value(
        {"Conventional_Log2FC_NA": False, "activity_class": "regulated"},
        99.0,
    )

    assert is_denovo is True
    assert value == 3.2  # frozen LOD cap 4.0 × high heatmap weight 0.80
    assert conventional_is_denovo is False
    assert conventional == 99.0
