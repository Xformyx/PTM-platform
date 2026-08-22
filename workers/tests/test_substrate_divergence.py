"""Regression tests for ptm_shared/substrate_divergence.py (P2).

Contract locked: substrate_divergence.v1  (2026-08-22)
Pre-registration status: Platform engineering module.

Test structure
--------------
A. compare_site_profiles — delta and ratio fields
B. Divergence score formula — weight components
C. compare_site_trajectories — convenience wrapper
D. Population summary — transitions, aggregate stats
E. Edge cases — missing features, flat profiles, None values
F. Frozen score weights
"""

from __future__ import annotations

from typing import List, Optional

import pytest

from ptm_shared.substrate_divergence import (
    CONTRACT_VERSION,
    PopulationDivergenceSummary,
    SiteConditionDivergence,
    _AMPLITUDE_LOG2_CAP,
    _WEIGHT_AMPLITUDE_MAX,
    _WEIGHT_PATTERN_CHANGE,
    _WEIGHT_PEAK_SHIFT_MAX,
    _WEIGHT_SIGN_REVERSAL,
    compare_site_profiles,
    compare_site_trajectories,
    summarise_population_divergence,
)
from ptm_shared.substrate_temporal_dynamics import (
    PATTERN_EARLY_PULSE,
    PATTERN_FLAT,
    PATTERN_MONOTONE_RISE,
    PATTERN_SUSTAINED_ACTIVATION,
    SiteKineticConfig,
    compute_site_kinetic_profile,
)

TP6 = ["5min", "15min", "30min", "60min", "120min", "240min"]
_CFG = SiteKineticConfig(run_loto=False, run_threshold_sensitivity=False)


def _profile(vals):
    return compute_site_kinetic_profile(TP6, vals, config=_CFG)


# ─────────────────────────────────────────────────────────────────────────────
# A. compare_site_profiles — delta / ratio fields
# ─────────────────────────────────────────────────────────────────────────────

class TestCompareSiteProfiles:
    def test_identical_profiles_zero_deltas(self):
        vals = [0.0, 0.5, 2.0, 1.5, 0.8, 0.3]
        p = _profile(vals)
        d = compare_site_profiles(p, p)
        assert d.amplitude_delta == pytest.approx(0.0)
        assert d.auc_signed_delta == pytest.approx(0.0)
        assert d.pattern_conserved is True
        assert d.sign_reversal is False
        assert d.peak_shift_minutes == pytest.approx(0.0)

    def test_amplitude_delta_direction(self):
        pa = _profile([0.0, 0.5, 1.0, 0.8, 0.5, 0.2])  # amp ≈ 1.0
        pb = _profile([0.0, 0.5, 2.0, 1.5, 1.0, 0.5])  # amp ≈ 2.0
        d = compare_site_profiles(pa, pb)
        assert d.amplitude_delta == pytest.approx(pb.amplitude - pa.amplitude)
        assert d.amplitude_delta > 0  # B is larger

    def test_amplitude_ratio_direction(self):
        pa = _profile([0.0, 0.5, 1.0, 0.8, 0.5, 0.2])
        pb = _profile([0.0, 0.5, 2.0, 1.5, 1.0, 0.5])
        d = compare_site_profiles(pa, pb)
        assert d.amplitude_ratio == pytest.approx(pb.amplitude / pa.amplitude)
        assert d.amplitude_ratio > 1.0

    def test_amplitude_log2_ratio_is_log2_of_ratio(self):
        import math
        pa = _profile([0.0, 0.5, 1.0, 0.8, 0.5, 0.2])
        pb = _profile([0.0, 0.5, 2.0, 1.5, 1.0, 0.5])
        d = compare_site_profiles(pa, pb)
        expected = math.log2(pb.amplitude / pa.amplitude)
        assert d.amplitude_log2_ratio == pytest.approx(expected)

    def test_peak_shift_positive_when_b_peaks_later(self):
        # A peaks at 30min, B peaks at 120min
        pa = _profile([0.0, 0.5, 2.0, 1.0, 0.3, 0.1])
        pb = _profile([0.0, 0.1, 0.3, 0.8, 2.0, 0.3])
        d = compare_site_profiles(pa, pb)
        assert d.peak_shift_minutes > 0  # B peaks later

    def test_onset_delta_positive_when_b_later(self):
        # A onset at 15min, B onset at 60min
        pa = _profile([0.0, 0.6, 2.0, 1.5, 1.0, 0.5])
        pb = _profile([0.0, 0.1, 0.2, 0.6, 2.0, 1.5])
        d = compare_site_profiles(pa, pb)
        assert d.onset_delta_minutes > 0

    def test_sign_reversal_detected(self):
        pa = _profile([0.0, 0.5, 2.0, 1.5, 1.0, 0.5])  # positive peak
        pb = _profile([0.0, -0.5, -2.0, -1.5, -1.0, -0.5])  # negative peak
        d = compare_site_profiles(pa, pb)
        assert d.sign_reversal is True
        assert d.pattern_conserved is False

    def test_pattern_conserved_when_same(self):
        pa = _profile([0.1, 0.8, 1.5, 1.8, 2.0, 1.9])  # sustained
        pb = _profile([0.2, 0.9, 1.6, 1.7, 1.9, 1.8])  # also sustained
        d = compare_site_profiles(pa, pb)
        assert d.pattern_conserved is True

    def test_quality_gate_flags_both_pass(self):
        pa = _profile([0.0, 0.5, 2.0, 1.5, 1.0, 0.5])
        pb = _profile([0.0, 0.5, 2.0, 1.5, 1.0, 0.5])
        d = compare_site_profiles(pa, pb)
        assert d.both_quality_gate_passed is True
        assert d.only_a_passes_gate is False
        assert d.only_b_passes_gate is False

    def test_quality_gate_flag_only_a_passes(self):
        pa = _profile([0.0, 0.5, 2.0, 1.5, 1.0, 0.5])
        pb = _profile([0.0, 0.1, 0.1, 0.1, 0.1, 0.1])  # flat
        d = compare_site_profiles(pa, pb)
        assert d.only_a_passes_gate is True
        assert d.both_quality_gate_passed is False

    def test_reference_span_inferred_from_profiles(self):
        pa = _profile([0.0, 0.5, 2.0, 1.5, 1.0, 0.5])
        pb = _profile([0.0, 0.5, 2.0, 1.5, 1.0, 0.5])
        d = compare_site_profiles(pa, pb)
        # observed_minutes for TP6 = [5, 15, 30, 60, 120, 240] → span = 235
        assert d.reference_span_minutes == pytest.approx(235.0)

    def test_explicit_reference_span_overrides_inferred(self):
        pa = _profile([0.0, 0.5, 2.0, 1.5, 1.0, 0.5])
        pb = _profile([0.0, 0.5, 2.0, 1.5, 1.0, 0.5])
        d = compare_site_profiles(pa, pb, reference_span_minutes=100.0)
        assert d.reference_span_minutes == pytest.approx(100.0)

    def test_contract_version_present(self):
        pa = _profile([0.0, 0.5, 2.0, 1.5, 1.0, 0.5])
        d = compare_site_profiles(pa, pa)
        assert d.contract_version == CONTRACT_VERSION

    def test_to_dict_serializable(self):
        import json
        pa = _profile([0.0, 0.5, 2.0, 1.5, 1.0, 0.5])
        pb = _profile([0.0, -0.5, -2.0, -1.5, -1.0, -0.5])
        d = compare_site_profiles(pa, pb)
        serialized = json.dumps(d.to_dict())
        assert "divergence_score" in serialized


# ─────────────────────────────────────────────────────────────────────────────
# B. Divergence score formula
# ─────────────────────────────────────────────────────────────────────────────

class TestDivergenceScore:
    def test_identical_profiles_score_zero(self):
        vals = [0.0, 0.5, 2.0, 1.5, 1.0, 0.5]
        p = _profile(vals)
        d = compare_site_profiles(p, p)
        assert d.divergence_score == pytest.approx(0.0)

    def test_sign_reversal_adds_weight(self):
        pa = _profile([0.0, 0.5, 2.0, 1.8, 1.5, 1.2])
        pb = _profile([0.0, -0.5, -2.0, -1.8, -1.5, -1.2])
        d = compare_site_profiles(pa, pb)
        # sign_reversal fires + pattern_change
        assert d.divergence_score >= _WEIGHT_SIGN_REVERSAL

    def test_score_higher_for_sign_reversal_than_no_reversal(self):
        pa = _profile([0.0, 0.5, 2.0, 1.8, 1.5, 1.2])
        pb_same = _profile([0.0, 0.6, 1.8, 1.6, 1.3, 1.0])  # same direction
        pb_rev = _profile([0.0, -0.5, -2.0, -1.8, -1.5, -1.2])  # sign reversal
        d_same = compare_site_profiles(pa, pb_same)
        d_rev = compare_site_profiles(pa, pb_rev)
        assert d_rev.divergence_score > d_same.divergence_score

    def test_score_increases_with_amplitude_difference(self):
        pa = _profile([0.0, 0.5, 1.0, 0.8, 0.5, 0.2])  # amplitude ≈ 1.0
        pb_small = _profile([0.0, 0.5, 1.2, 1.0, 0.7, 0.3])  # amp ≈ 1.2, small change
        pb_large = _profile([0.0, 0.5, 4.0, 3.5, 3.0, 2.5])  # amp = 4.0, large change
        d_small = compare_site_profiles(pa, pb_small)
        d_large = compare_site_profiles(pa, pb_large)
        assert d_large.divergence_score > d_small.divergence_score

    def test_flat_vs_flat_score_zero(self):
        # Both profiles fail quality gate → pattern is flat/flat → no pattern_change penalty
        pa = _profile([0.0, 0.1, 0.1, 0.1, 0.1, 0.1])
        pb = _profile([0.0, 0.1, 0.1, 0.1, 0.1, 0.1])
        d = compare_site_profiles(pa, pb)
        assert d.divergence_score == pytest.approx(0.0)


# ─────────────────────────────────────────────────────────────────────────────
# C. compare_site_trajectories convenience wrapper
# ─────────────────────────────────────────────────────────────────────────────

class TestCompareSiteTrajectories:
    def test_returns_three_tuple(self):
        vals_a = [0.0, 0.5, 2.0, 1.5, 1.0, 0.5]
        vals_b = [0.0, -0.5, -2.0, -1.5, -1.0, -0.5]
        result = compare_site_trajectories(TP6, vals_a, vals_b, config=_CFG)
        assert len(result) == 3
        divergence, profile_a, profile_b = result
        assert isinstance(divergence, SiteConditionDivergence)
        assert isinstance(profile_a, __import__("ptm_shared.substrate_temporal_dynamics", fromlist=["SiteKineticProfile"]).SiteKineticProfile)

    def test_matches_compare_site_profiles(self):
        vals_a = [0.0, 0.5, 2.0, 1.5, 1.0, 0.5]
        vals_b = [0.0, -0.5, -2.0, -1.5, -1.0, -0.5]
        divergence, pa, pb = compare_site_trajectories(TP6, vals_a, vals_b, config=_CFG)
        d_direct = compare_site_profiles(pa, pb)
        assert divergence.divergence_score == pytest.approx(d_direct.divergence_score)
        assert divergence.sign_reversal == d_direct.sign_reversal


# ─────────────────────────────────────────────────────────────────────────────
# D. Population summary
# ─────────────────────────────────────────────────────────────────────────────

class TestPopulationDivergenceSummary:
    def test_empty_input_zero_summary(self):
        summary = summarise_population_divergence([])
        assert summary.n_sites == 0
        assert summary.conservation_rate is None

    def test_n_sites_counts_all_records(self):
        pa = _profile([0.0, 0.5, 2.0, 1.8, 1.5, 1.2])
        pb = _profile([0.0, -0.5, -2.0, -1.8, -1.5, -1.2])
        pc = _profile([0.0, 0.5, 1.8, 1.5, 1.2, 0.8])
        divergences = [
            compare_site_profiles(pa, pb),
            compare_site_profiles(pa, pc),
            compare_site_profiles(pb, pc),
        ]
        summary = summarise_population_divergence(divergences)
        assert summary.n_sites == 3

    def test_conservation_rate_correct(self):
        # 2 conserved, 1 diverged (among both-pass sites)
        pa = _profile([0.0, 0.5, 2.0, 1.8, 1.5, 1.2])  # sustained
        pb = _profile([0.0, 0.6, 1.9, 1.7, 1.4, 1.1])  # also sustained
        pc = _profile([0.0, -0.5, -2.0, -1.8, -1.5, -1.2])  # sustained_suppression
        divergences = [
            compare_site_profiles(pa, pb),  # conserved (both sustained)
            compare_site_profiles(pa, pb),  # conserved
            compare_site_profiles(pa, pc),  # diverged + sign reversal
        ]
        summary = summarise_population_divergence(divergences)
        assert summary.n_conserved == 2
        assert summary.n_diverged == 1
        assert summary.conservation_rate == pytest.approx(2 / 3)

    def test_sign_reversal_counted(self):
        pa = _profile([0.0, 0.5, 2.0, 1.8, 1.5, 1.2])
        pb = _profile([0.0, -0.5, -2.0, -1.8, -1.5, -1.2])
        summary = summarise_population_divergence([compare_site_profiles(pa, pb)])
        assert summary.n_sign_reversal == 1

    def test_transition_counts_recorded(self):
        pa = _profile([0.0, 0.5, 2.0, 1.8, 1.5, 1.2])
        pb = _profile([0.0, -0.5, -2.0, -1.8, -1.5, -1.2])
        d = compare_site_profiles(pa, pb)
        summary = summarise_population_divergence([d])
        key = f"{d.pattern_a}\u2192{d.pattern_b}"
        assert key in summary.pattern_transition_counts
        assert summary.pattern_transition_counts[key] == 1

    def test_mean_divergence_score_computed(self):
        pa = _profile([0.0, 0.5, 2.0, 1.8, 1.5, 1.2])
        pb = _profile([0.0, -0.5, -2.0, -1.8, -1.5, -1.2])
        d = compare_site_profiles(pa, pb)
        summary = summarise_population_divergence([d])
        assert summary.mean_divergence_score == pytest.approx(d.divergence_score)

    def test_to_dict_serializable(self):
        import json
        pa = _profile([0.0, 0.5, 2.0, 1.8, 1.5, 1.2])
        pb = _profile([0.0, -0.5, -2.0, -1.8, -1.5, -1.2])
        summary = summarise_population_divergence([compare_site_profiles(pa, pb)])
        serialized = json.dumps(summary.to_dict())
        assert "conservation_rate" in serialized


# ─────────────────────────────────────────────────────────────────────────────
# E. Edge cases
# ─────────────────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_flat_vs_signal_both_flags_correct(self):
        pa = _profile([0.0, 0.1, 0.1, 0.1, 0.1, 0.1])  # flat
        pb = _profile([0.0, 0.5, 2.0, 1.5, 1.0, 0.5])  # quality-passed
        d = compare_site_profiles(pa, pb)
        assert d.only_b_passes_gate is True
        assert d.both_quality_gate_passed is False

    def test_neither_passes_gate(self):
        pa = _profile([0.0, 0.1, 0.1, 0.1, 0.1, 0.1])
        pb = _profile([0.0, 0.2, 0.1, 0.1, 0.1, 0.1])
        d = compare_site_profiles(pa, pb)
        assert d.neither_passes_gate is True

    def test_onset_delta_none_when_no_onset(self):
        # Profile with no onset (all below threshold)
        pa = _profile([0.0, 0.1, 0.1, 0.1, 0.1, 0.1])
        pb = _profile([0.0, 0.5, 2.0, 1.5, 1.0, 0.5])
        d = compare_site_profiles(pa, pb)
        assert d.onset_delta_minutes is None  # A has no onset

    def test_amplitude_ratio_none_when_amplitude_zero(self):
        pa = _profile([0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        pb = _profile([0.0, 0.5, 2.0, 1.5, 1.0, 0.5])
        d = compare_site_profiles(pa, pb)
        assert d.amplitude_ratio is None

    def test_auc_delta_none_when_missing_values(self):
        # Profiles with all-None values have no AUC
        from ptm_shared.substrate_temporal_dynamics import SiteKineticConfig
        vals_none: List[Optional[float]] = [None, None, None, None, None, None]
        pa = compute_site_kinetic_profile(TP6, vals_none, config=_CFG)
        pb = _profile([0.0, 0.5, 2.0, 1.5, 1.0, 0.5])
        d = compare_site_profiles(pa, pb)
        assert d.auc_signed_delta is None


# ─────────────────────────────────────────────────────────────────────────────
# F. Frozen score weights
# ─────────────────────────────────────────────────────────────────────────────

class TestFrozenScoreWeights:
    """Any change to these values breaks previously published divergence scores."""

    def test_sign_reversal_weight(self):
        assert _WEIGHT_SIGN_REVERSAL == pytest.approx(3.0)

    def test_pattern_change_weight(self):
        assert _WEIGHT_PATTERN_CHANGE == pytest.approx(1.5)

    def test_amplitude_max_weight(self):
        assert _WEIGHT_AMPLITUDE_MAX == pytest.approx(2.0)

    def test_amplitude_log2_cap(self):
        assert _AMPLITUDE_LOG2_CAP == pytest.approx(2.0)

    def test_peak_shift_max_weight(self):
        assert _WEIGHT_PEAK_SHIFT_MAX == pytest.approx(2.0)

    def test_contract_version_frozen(self):
        assert CONTRACT_VERSION == "substrate_divergence.v1"
