"""Contract tests for the TMM identifiability diagnostics.

Each test constructs a synthetic mixture whose identifiability status is known
by construction, so a passing suite means the diagnostic separates "the data
determines this attribution" from "the solver picked one of many equally good
answers".
"""

from __future__ import annotations

import numpy as np
import pytest

from ptm_shared.tmm_identifiability import (
    VERDICT_EQUAL_WEIGHT_FALLBACK,
    VERDICT_IDENTIFIABLE,
    VERDICT_NON_IDENTIFIABLE,
    VERDICT_NO_SIGNAL,
    VERDICT_WEAK,
    ambiguity_aware_attribution,
    diagnose_site,
    group_parallel_columns,
    max_column_coherence,
    normalized_ratios,
    solve_nnls,
    summarize_bias,
    summarize_diagnostics,
    zero_imputation_bias,
)


def _bump(n_timepoints: int, peak: float, width: float = 1.0) -> np.ndarray:
    """A max-normalised non-negative profile, matching the production convention."""
    grid = np.arange(n_timepoints, dtype=float)
    profile = np.exp(-0.5 * ((grid - peak) / width) ** 2)
    return profile / profile.max()


def _design(*columns: np.ndarray) -> np.ndarray:
    return np.column_stack(columns)


# ---------------------------------------------------------------------------
# Solver contract
# ---------------------------------------------------------------------------


def test_solve_nnls_returns_non_negative_solution_and_matching_rss():
    design = _design(_bump(8, 1.0), _bump(8, 6.0))
    target = 0.7 * design[:, 0] + 0.3 * design[:, 1]

    coefficients, rss = solve_nnls(design, target)

    assert np.all(coefficients >= 0.0)
    assert coefficients == pytest.approx(np.array([0.7, 0.3]), abs=1e-6)
    residual = design @ coefficients - target
    assert rss == pytest.approx(float(residual @ residual), abs=1e-12)


def test_normalized_ratios_flags_collapse_with_uniform_weights():
    assert normalized_ratios(np.array([0.0, 0.0, 0.0])) == pytest.approx(
        np.array([1 / 3, 1 / 3, 1 / 3])
    )
    assert normalized_ratios(np.array([3.0, 1.0])) == pytest.approx(np.array([0.75, 0.25]))


def test_coherence_is_scale_free():
    first = _bump(10, 2.0)
    second = _bump(10, 7.0)
    plain, _ = max_column_coherence(_design(first, second))
    rescaled, _ = max_column_coherence(_design(first, 17.0 * second))
    assert plain == pytest.approx(rescaled, abs=1e-12)


# ---------------------------------------------------------------------------
# Identifiable versus non-identifiable designs
# ---------------------------------------------------------------------------


def test_well_separated_profiles_are_identifiable():
    design = _design(_bump(8, 1.0, 0.9), _bump(8, 6.0, 0.9))
    target = 0.7 * design[:, 0] + 0.3 * design[:, 1]

    result = diagnose_site(
        "GENE_S1", target, design, ["EARLY", "LATE"], relative_noise=0.05, seed=7
    )

    assert result.verdict == VERDICT_IDENTIFIABLE
    assert result.top1_kinase == "EARLY"
    assert result.unique_solution is True
    assert result.structurally_underdetermined is False
    assert result.ratio_ambiguity_radius < 0.15
    assert result.ambiguity_set == ()
    assert all(entry["required"] for entry in result.leave_one_out)
    assert result.top1_stability == 1.0


def test_collinear_profiles_are_not_identifiable():
    early = _bump(8, 3.0, 1.5)
    nearly_identical = _bump(8, 3.05, 1.5)
    design = _design(early, nearly_identical)
    target = 0.5 * early + 0.5 * nearly_identical

    result = diagnose_site(
        "GENE_S2", target, design, ["AKT1", "SGK1"], relative_noise=0.05, seed=7
    )

    assert result.max_column_coherence > 0.99
    assert result.verdict == VERDICT_NON_IDENTIFIABLE
    assert result.top1_kinase in result.ambiguity_set
    assert [pair["kinase_a"] for pair in result.substitutable_pairs] == ["AKT1"]
    # Neither candidate is required: removing one leaves the residual unchanged.
    assert not any(entry["required"] for entry in result.leave_one_out)


def test_more_candidates_than_timepoints_is_structurally_underdetermined():
    design = _design(*[_bump(4, peak, 1.2) for peak in (0.0, 0.8, 1.6, 2.4, 3.0, 3.6)])
    target = design[:, 0] + design[:, 4]

    result = diagnose_site(
        "GENE_S3", target, design, [f"K{i}" for i in range(6)], relative_noise=0.05
    )

    assert result.n_candidates == 6
    assert result.design_rank <= 4
    assert result.structurally_underdetermined is True
    assert result.verdict == VERDICT_NON_IDENTIFIABLE


def test_ambiguity_radius_grows_with_assumed_noise():
    design = _design(_bump(8, 2.0, 1.4), _bump(8, 5.0, 1.4))
    target = 0.6 * design[:, 0] + 0.4 * design[:, 1]

    def radius_and_verdict(relative_noise: float):
        result = diagnose_site(
            "GENE_S4", target, design, ["A", "B"], relative_noise=relative_noise, n_bootstrap=0
        )
        return result.ratio_ambiguity_radius, result.verdict

    tight_radius, tight_verdict = radius_and_verdict(0.02)
    mid_radius, mid_verdict = radius_and_verdict(0.30)
    loose_radius, loose_verdict = radius_and_verdict(1.20)

    assert tight_radius < mid_radius < loose_radius
    assert tight_verdict == VERDICT_IDENTIFIABLE
    assert mid_verdict == VERDICT_WEAK
    assert loose_verdict == VERDICT_NON_IDENTIFIABLE


# ---------------------------------------------------------------------------
# Failure modes that currently surface as confident numbers
# ---------------------------------------------------------------------------


def test_negative_trajectory_collapses_to_equal_weight_fallback():
    design = _design(_bump(6, 1.0), _bump(6, 4.0))
    target = -1.0 * np.abs(0.5 * design[:, 0] + 0.5 * design[:, 1])

    result = diagnose_site("GENE_S5", target, design, ["A", "B"], relative_noise=0.10)

    assert result.equal_weight_fallback is True
    assert result.verdict == VERDICT_EQUAL_WEIGHT_FALLBACK
    assert result.reported_ratios == pytest.approx({"A": 0.5, "B": 0.5})
    assert set(result.ambiguity_set) == {"A", "B"}
    assert result.y_negative_fraction == 1.0


def test_zero_trajectory_is_reported_as_no_signal():
    design = _design(_bump(6, 1.0), _bump(6, 4.0))

    result = diagnose_site("GENE_S6", np.zeros(6), design, ["A", "B"])

    assert result.verdict == VERDICT_NO_SIGNAL
    assert result.reported_ratios == {}


def test_prior_derived_column_is_tracked_through_to_the_winner():
    design = _design(_bump(8, 1.0, 0.9), _bump(8, 6.0, 0.9))
    target = 0.2 * design[:, 0] + 0.8 * design[:, 1]

    result = diagnose_site(
        "GENE_S7",
        target,
        design,
        ["DATA_DRIVEN", "GAUSSIAN_PRIOR"],
        relative_noise=0.05,
        prior_columns=[False, True],
    )

    assert result.top1_kinase == "GAUSSIAN_PRIOR"
    assert result.prior_column_fraction == pytest.approx(0.5)
    assert result.top1_from_prior is True


# ---------------------------------------------------------------------------
# Zero-imputation bias
# ---------------------------------------------------------------------------


def test_zero_imputation_can_reverse_the_winning_kinase():
    late = np.array([0.0, 0.1, 0.3, 0.6, 1.0, 0.7])
    early = np.array([0.3, 0.7, 1.0, 0.6, 0.3, 0.1])
    design = _design(late, early)
    observed = np.array([True, True, True, True, False, False])
    zero_filled = np.where(observed, late, 0.0)

    record = zero_imputation_bias(
        "GENE_S8", zero_filled, design, ["LATE", "EARLY"], observed
    )

    assert record["evaluated"] is True
    assert record["n_observed"] == 4
    assert record["missing_fraction"] == pytest.approx(1 / 3)
    assert record["top1_observed_only"] == "LATE"
    assert record["top1_zero_imputed"] == "EARLY"
    assert record["top1_changed"] is True
    assert record["ratio_total_variation"] > 0.5


def test_zero_imputation_bias_skips_complete_and_too_sparse_sites():
    design = _design(_bump(6, 1.0), _bump(6, 4.0))
    target = design[:, 0]

    complete = zero_imputation_bias(
        "GENE_S9", target, design, ["A", "B"], np.ones(6, dtype=bool)
    )
    sparse = zero_imputation_bias(
        "GENE_S10",
        target,
        design,
        ["A", "B"],
        np.array([True, False, False, False, False, False]),
    )

    assert complete["evaluated"] is False
    assert sparse["evaluated"] is False


# ---------------------------------------------------------------------------
# Aggregation and reproducibility
# ---------------------------------------------------------------------------


def test_summaries_report_fractions_and_thresholds():
    design = _design(_bump(8, 1.0, 0.9), _bump(8, 6.0, 0.9))
    identifiable = diagnose_site(
        "OK", 0.7 * design[:, 0] + 0.3 * design[:, 1], design, ["A", "B"], relative_noise=0.05
    )
    collinear = _design(_bump(8, 3.0, 1.5), _bump(8, 3.05, 1.5))
    broken = diagnose_site(
        "BAD", collinear.sum(axis=1), collinear, ["A", "B"], relative_noise=0.05
    )

    summary = summarize_diagnostics([identifiable, broken])

    assert summary["n_sites"] == 2
    assert summary["verdicts"][VERDICT_IDENTIFIABLE] == 1
    assert summary["verdicts"][VERDICT_NON_IDENTIFIABLE] == 1
    assert sum(summary["verdict_fractions"].values()) == pytest.approx(1.0)
    assert summary["rates"]["has_substitutable_pair"] == pytest.approx(0.5)
    assert summary["thresholds"]["coherence_substitutable"] == pytest.approx(0.99)
    assert summary["distributions"]["max_column_coherence"]["max"] > 0.99


def test_bias_summary_counts_reversals():
    records = [
        {"evaluated": True, "top1_changed": True, "ratio_total_variation": 0.8, "missing_fraction": 0.3},
        {"evaluated": True, "top1_changed": False, "ratio_total_variation": 0.1, "missing_fraction": 0.2},
        {"evaluated": False},
    ]

    summary = summarize_bias(records)

    assert summary["n_evaluated"] == 2
    assert summary["n_complete_or_too_sparse"] == 1
    assert summary["top1_reversal_rate"] == pytest.approx(0.5)


def test_diagnosis_is_deterministic_for_a_fixed_seed():
    design = _design(_bump(8, 2.0, 1.3), _bump(8, 4.0, 1.3))
    target = 0.55 * design[:, 0] + 0.45 * design[:, 1]

    first = diagnose_site("GENE_S11", target, design, ["A", "B"], relative_noise=0.2, seed=11)
    second = diagnose_site("GENE_S11", target, design, ["A", "B"], relative_noise=0.2, seed=11)

    assert first.top1_stability == second.top1_stability
    assert first.top1_ratio_std == second.top1_ratio_std
    assert first.to_dict() == second.to_dict()


# ---------------------------------------------------------------------------
# Ambiguity-aware attribution
# ---------------------------------------------------------------------------


def test_parallel_columns_are_merged_into_one_group():
    profile = _bump(8, 3.0, 1.4)
    design = _design(profile, profile.copy())

    result = ambiguity_aware_attribution(
        "GENE_S13", profile, design, ["AKT1", "SGK1"], relative_noise=0.05
    )

    assert result.attribution_supported is True
    assert result.n_groups == 1
    group = result.groups[0]
    assert group.members == ("AKT1", "SGK1")
    assert group.ambiguous is True
    assert group.ratio == pytest.approx(1.0)
    assert group.required is True
    assert result.per_kinase["AKT1"]["ratio"] == pytest.approx(0.5)
    assert result.per_kinase["AKT1"]["group_ratio"] == pytest.approx(1.0)
    assert result.per_kinase["AKT1"]["ambiguous"] is True
    # Once the duplicate is merged the remaining problem is well posed.
    assert result.reduced_diagnosis.verdict == VERDICT_IDENTIFIABLE


def test_distinct_columns_stay_separate():
    design = _design(_bump(8, 1.0, 0.9), _bump(8, 6.0, 0.9))
    target = 0.7 * design[:, 0] + 0.3 * design[:, 1]

    result = ambiguity_aware_attribution(
        "GENE_S14", target, design, ["EARLY", "LATE"], relative_noise=0.05
    )

    assert result.n_groups == 2
    assert all(not group.ambiguous for group in result.groups)
    assert result.per_kinase["EARLY"]["ratio"] == pytest.approx(0.7, abs=1e-4)
    assert result.per_kinase["LATE"]["ratio"] == pytest.approx(0.3, abs=1e-4)


def test_group_shares_are_unchanged_by_duplicating_a_candidate():
    early = _bump(8, 1.0, 0.9)
    late = _bump(8, 6.0, 0.9)
    target = 0.7 * early + 0.3 * late

    plain = ambiguity_aware_attribution(
        "GENE_S15", target, _design(early, late), ["EARLY", "LATE"], relative_noise=0.05
    )
    duplicated = ambiguity_aware_attribution(
        "GENE_S15",
        target,
        _design(early, early.copy(), late),
        ["EARLY", "EARLY_COPY", "LATE"],
        relative_noise=0.05,
    )

    assert [group.ratio for group in plain.groups] == pytest.approx(
        [group.ratio for group in duplicated.groups], abs=1e-6
    )
    assert duplicated.per_kinase["EARLY"]["group_ratio"] == pytest.approx(
        plain.per_kinase["EARLY"]["ratio"], abs=1e-6
    )
    assert duplicated.per_kinase["EARLY"]["ratio"] == pytest.approx(
        plain.per_kinase["EARLY"]["ratio"] / 2, abs=1e-6
    )


def test_grouping_is_transitive_along_a_near_parallel_chain():
    design = _design(_bump(9, 4.0, 2.0), _bump(9, 4.02, 2.0), _bump(9, 4.04, 2.0))

    groups, empty = group_parallel_columns(design)

    assert empty == []
    assert len(groups) == 1
    assert groups[0] == [0, 1, 2]


def test_unexplainable_trajectory_is_marked_unsupported_instead_of_uniform():
    design = _design(_bump(6, 1.0), _bump(6, 4.0))
    target = -1.0 * np.abs(0.5 * design[:, 0] + 0.5 * design[:, 1])

    result = ambiguity_aware_attribution("GENE_S16", target, design, ["A", "B"])

    assert result.attribution_supported is False
    assert result.unsupported_reason == "no_non_negative_explanation"
    assert result.resolved_ratios == pytest.approx({"A": 0.0, "B": 0.0})
    assert all(entry["attribution_supported"] is False for entry in result.per_kinase.values())
    # The deployed solver reports 0.5/0.5 for exactly this input.
    assert normalized_ratios(solve_nnls(design, target)[0]) == pytest.approx([0.5, 0.5])


def test_empty_profile_candidates_are_reported_separately():
    design = _design(_bump(6, 1.0, 0.9), np.zeros(6), _bump(6, 4.0, 0.9))
    target = design[:, 0] + design[:, 2]

    result = ambiguity_aware_attribution(
        "GENE_S17", target, design, ["A", "EMPTY", "B"], relative_noise=0.05
    )

    assert result.empty_profile_members == ("EMPTY",)
    assert result.n_groups == 2
    assert result.per_kinase["EMPTY"]["ratio"] == 0.0
    assert result.per_kinase["EMPTY"]["reason"] == "empty_profile"
    assert sum(result.resolved_ratios.values()) == pytest.approx(1.0)


def test_supported_attribution_ratios_sum_to_one():
    design = _design(_bump(8, 2.0, 1.2), _bump(8, 2.01, 1.2), _bump(8, 6.0, 1.2))
    target = 0.6 * design[:, 0] + 0.4 * design[:, 2]

    result = ambiguity_aware_attribution(
        "GENE_S18", target, design, ["A", "A_TWIN", "B"], relative_noise=0.05
    )

    assert result.n_groups == 2
    assert sum(result.resolved_ratios.values()) == pytest.approx(1.0)
    assert sum(group.ratio for group in result.groups) == pytest.approx(1.0)


def test_attribution_to_dict_is_json_safe():
    import json

    profile = _bump(6, 2.0, 1.0)
    result = ambiguity_aware_attribution(
        "GENE_S19", profile, _design(profile, profile.copy()), ["A", "B"]
    )

    encoded = json.dumps(result.to_dict())

    assert "Infinity" not in encoded
    assert "NaN" not in encoded


def test_to_dict_is_json_safe():
    import json

    design = _design(*[_bump(4, peak, 1.2) for peak in (0.0, 1.0, 2.0, 3.0, 3.5)])
    result = diagnose_site("GENE_S12", design[:, 0], design, [f"K{i}" for i in range(5)])

    encoded = json.dumps(result.to_dict())

    assert "Infinity" not in encoded
    assert "NaN" not in encoded
