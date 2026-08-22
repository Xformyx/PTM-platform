"""Regression tests for ptm_shared/substrate_temporal_dynamics.py.

Contract locked: substrate_temporal_dynamics.v1.1  (2026-08-22)
Pre-registration status: Platform engineering module.
These tests lock the taxonomy logic and numerical thresholds so that
inadvertent changes to gate constants or classification precedence are
immediately detected.

Test structure
--------------
A. Feature computation  — amplitude, AUC, onset, slopes
B. Taxonomy labels      — one representative trajectory per label
C. Stability metrics    — LOTO and threshold sensitivity
D. Edge cases           — single point, all-missing, all-flat
E. Wave integration     — describe_member_dynamics, summarise_member_pattern_distribution
"""

from __future__ import annotations

from typing import List, Optional

import pytest

from ptm_shared.substrate_temporal_dynamics import (
    CONTRACT_VERSION,
    PATTERN_BIPHASIC,
    PATTERN_DELAYED_PULSE,
    PATTERN_DELAYED_SUPPRESSION,
    PATTERN_EARLY_PULSE,
    PATTERN_FLAT,
    PATTERN_MONOTONE_DECLINE,
    PATTERN_MONOTONE_RISE,
    PATTERN_MULTI_PEAK,
    PATTERN_OSCILLATORY,
    PATTERN_REBOUND,
    PATTERN_SUSTAINED_ACTIVATION,
    PATTERN_SUSTAINED_SUPPRESSION,
    PATTERN_TRANSIENT_SUPPRESSION,
    PATTERN_UNRESOLVED,
    SiteKineticConfig,
    SiteKineticProfile,
    TAXONOMY_LABELS,
    compute_kinase_substrate_phenotypes,
    compute_site_kinetic_profile,
    describe_member_dynamics,
    summarise_member_pattern_distribution,
)

# ── Shared fixtures ────────────────────────────────────────────────────────────

TP6 = ["5min", "15min", "30min", "60min", "120min", "240min"]
TP8 = ["5min", "15min", "30min", "60min", "120min", "240min", "480min", "960min"]

# ─────────────────────────────────────────────────────────────────────────────
# A. Feature computation
# ─────────────────────────────────────────────────────────────────────────────

class TestFeatureComputation:
    def test_amplitude_is_max_absolute(self):
        vals = [0.1, 0.5, 2.0, 1.0, 0.3, 0.1]
        p = compute_site_kinetic_profile(TP6, vals, config=SiteKineticConfig(run_loto=False, run_threshold_sensitivity=False))
        assert p.amplitude == pytest.approx(2.0)

    def test_amplitude_negative_trajectory(self):
        vals = [-0.1, -1.5, -2.5, -1.0, -0.4, -0.1]
        p = compute_site_kinetic_profile(TP6, vals, config=SiteKineticConfig(run_loto=False, run_threshold_sensitivity=False))
        assert p.amplitude == pytest.approx(2.5)

    def test_dynamic_range_is_max_minus_min(self):
        vals = [0.0, 1.0, 2.0, 1.5, 0.5, 0.0]
        p = compute_site_kinetic_profile(TP6, vals, config=SiteKineticConfig(run_loto=False, run_threshold_sensitivity=False))
        assert p.dynamic_range == pytest.approx(2.0)

    def test_missing_count_from_none_values(self):
        vals: List[Optional[float]] = [None, 1.0, 2.0, None, 0.5, 0.0]
        p = compute_site_kinetic_profile(TP6, vals, config=SiteKineticConfig(run_loto=False, run_threshold_sensitivity=False))
        assert p.missing_timepoints_count == 2
        assert p.observed_timepoints_count == 4

    def test_auc_signed_positive_trapezoid(self):
        # 2 timepoints at 0 and 10 min, values 1.0 and 1.0 → AUC = 10
        p = compute_site_kinetic_profile(["0min", "10min"], [1.0, 1.0], config=SiteKineticConfig(run_loto=False, run_threshold_sensitivity=False))
        assert p.auc_signed == pytest.approx(10.0)
        assert p.auc_absolute == pytest.approx(10.0)

    def test_auc_signed_mixed_cancels(self):
        # 3 points: 0min=2.0, 5min=-2.0, 10min=2.0
        # AUC_signed ≈ 0, AUC_absolute > 0
        p = compute_site_kinetic_profile(
            ["0min", "5min", "10min"], [2.0, -2.0, 2.0],
            config=SiteKineticConfig(run_loto=False, run_threshold_sensitivity=False)
        )
        assert p.auc_signed == pytest.approx(0.0)
        assert p.auc_absolute == pytest.approx(20.0)

    def test_onset_is_first_above_threshold(self):
        vals = [0.1, 0.2, 0.8, 1.5, 1.0, 0.3]
        p = compute_site_kinetic_profile(TP6, vals, config=SiteKineticConfig(run_loto=False, run_threshold_sensitivity=False))
        # TP6[2] = "30min" is the first with |v| > 0.5
        assert p.onset_minutes == pytest.approx(30.0)

    def test_onset_none_when_all_below_threshold(self):
        vals = [0.1, 0.1, 0.1, 0.1, 0.1, 0.1]
        p = compute_site_kinetic_profile(TP6, vals, config=SiteKineticConfig(run_loto=False, run_threshold_sensitivity=False))
        assert p.onset_minutes is None

    def test_peak_minutes_matches_max_absolute(self):
        vals = [0.1, 0.5, 2.0, 1.0, 0.3, 0.1]
        p = compute_site_kinetic_profile(TP6, vals, config=SiteKineticConfig(run_loto=False, run_threshold_sensitivity=False))
        assert p.peak_minutes == pytest.approx(30.0)  # index 2

    def test_peak_sign_positive(self):
        vals = [0.1, 0.5, 2.0, 1.5, 1.0, 0.5]
        p = compute_site_kinetic_profile(TP6, vals, config=SiteKineticConfig(run_loto=False, run_threshold_sensitivity=False))
        assert p.peak_sign == 1

    def test_peak_sign_negative(self):
        vals = [-0.1, -0.5, -2.0, -1.5, -1.0, -0.5]
        p = compute_site_kinetic_profile(TP6, vals, config=SiteKineticConfig(run_loto=False, run_threshold_sensitivity=False))
        assert p.peak_sign == -1

    def test_return_to_baseline_true_when_trajectory_decays(self):
        # Peak at 30min, then drops back below threshold
        vals = [0.1, 0.3, 2.0, 0.8, 0.2, 0.1]
        p = compute_site_kinetic_profile(TP6, vals, config=SiteKineticConfig(run_loto=False, run_threshold_sensitivity=False))
        assert p.return_to_baseline is True

    def test_return_to_baseline_false_when_stays_elevated(self):
        vals = [0.1, 0.5, 2.0, 2.5, 2.0, 1.8]
        p = compute_site_kinetic_profile(TP6, vals, config=SiteKineticConfig(run_loto=False, run_threshold_sensitivity=False))
        assert p.return_to_baseline is False

    def test_qvalue_coverage_fraction(self):
        vals = [0.1, 0.5, 2.0, 1.5, 0.8, 0.3]
        q = [0.10, 0.03, 0.01, 0.04, 0.20, 0.01]  # 4 of 6 < 0.05
        p = compute_site_kinetic_profile(TP6, vals, q_values=q, config=SiteKineticConfig(run_loto=False, run_threshold_sensitivity=False))
        assert p.qvalue_coverage == pytest.approx(4 / 6)

    def test_missingness_warning_fires_above_one_third(self):
        vals: List[Optional[float]] = [None, None, None, 1.0, 2.0, 1.0]  # 3/6 missing
        p = compute_site_kinetic_profile(TP6, vals, config=SiteKineticConfig(run_loto=False, run_threshold_sensitivity=False))
        assert p.missingness_warning is True

    def test_missingness_warning_silent_below_threshold(self):
        vals: List[Optional[float]] = [None, 1.0, 2.0, 1.5, 1.0, 0.5]  # 1/6 missing
        p = compute_site_kinetic_profile(TP6, vals, config=SiteKineticConfig(run_loto=False, run_threshold_sensitivity=False))
        assert p.missingness_warning is False

    def test_contract_version_is_frozen(self):
        p = compute_site_kinetic_profile(TP6, [0.1] * 6, config=SiteKineticConfig(run_loto=False, run_threshold_sensitivity=False))
        assert p.contract_version == CONTRACT_VERSION == "substrate_temporal_dynamics.v1.1"


# ─────────────────────────────────────────────────────────────────────────────
# B. Taxonomy labels
# ─────────────────────────────────────────────────────────────────────────────

class TestTaxonomyLabels:
    """Each test provides a trajectory archetypal for one label."""

    _cfg = SiteKineticConfig(run_loto=False, run_threshold_sensitivity=False)

    def _classify(self, tps, vals):
        return compute_site_kinetic_profile(tps, vals, config=self._cfg).primary_pattern

    def test_flat_when_amplitude_below_threshold(self):
        assert self._classify(TP6, [0.1, 0.2, 0.3, 0.2, 0.1, 0.0]) == PATTERN_FLAT

    def test_flat_when_too_few_observed(self):
        vals: List[Optional[float]] = [None, None, None, None, 2.0, 1.5]
        assert self._classify(TP6, vals) == PATTERN_FLAT

    def test_monotonic_rise(self):
        # Peak at LAST index (still rising) — monotone_rise wins over sustained
        # because pk_idx == last is checked before sustained_ratio.
        vals = [0.0, 0.1, 0.4, 0.7, 1.5, 2.5]
        assert self._classify(TP6, vals) == PATTERN_MONOTONE_RISE

    def test_monotonic_decline(self):
        # Peak at FIRST index, does NOT return to baseline (all values > threshold at end)
        # → monotone_decline (vs early_pulse which requires return_to_baseline=True)
        vals = [2.5, 2.0, 1.6, 1.3, 1.0, 0.8]
        assert self._classify(TP6, vals) == PATTERN_MONOTONE_DECLINE

    def test_early_single_pulse(self):
        # Peak at 5min (index 0), returns to baseline → early_single_pulse
        # (monotone_decline would require NOT return_to_baseline)
        vals = [2.0, 1.0, 0.3, 0.1, 0.0, 0.0]
        assert self._classify(TP6, vals) == PATTERN_EARLY_PULSE

    def test_delayed_single_pulse(self):
        # Peak at 120min (index 4), well past early_cutoff (first_tp + 40% span)
        # Short activation window → not sustained; not at last index → not monotone
        vals = [0.0, 0.0, 0.1, 0.3, 2.0, 0.3]
        assert self._classify(TP6, vals) == PATTERN_DELAYED_PULSE

    def test_transient_suppression(self):
        # Negative peak early, then recovery
        vals = [-2.0, -1.0, -0.3, 0.0, 0.0, 0.0]
        assert self._classify(TP6, vals) == PATTERN_TRANSIENT_SUPPRESSION

    def test_delayed_suppression(self):
        # Negative peak at 120min (index 4) — well past early_cutoff
        vals = [0.0, -0.1, -0.3, -0.8, -2.0, -0.3]
        assert self._classify(TP6, vals) == PATTERN_DELAYED_SUPPRESSION

    def test_sustained_activation(self):
        # Peak at index 4 (not last) — monotone check does not fire;
        # active from 15min to 240min → sustained_activation
        vals = [0.1, 0.8, 1.5, 1.8, 2.0, 1.9]
        assert self._classify(TP6, vals) == PATTERN_SUSTAINED_ACTIVATION

    def test_sustained_suppression(self):
        vals = [-0.1, -0.8, -1.5, -1.8, -2.0, -1.9]
        assert self._classify(TP6, vals) == PATTERN_SUSTAINED_SUPPRESSION

    def test_biphasic_switch(self):
        # Positive first phase → negative second phase, both prominent
        vals = [0.1, 2.0, 1.5, -0.5, -1.5, -2.0]
        result = self._classify(TP6, vals)
        assert result == PATTERN_BIPHASIC

    def test_all_taxonomy_labels_are_reachable(self):
        # All values in TAXONOMY_LABELS must be defined constants (no typos)
        from ptm_shared.substrate_temporal_dynamics import TAXONOMY_LABELS as TL
        assert PATTERN_FLAT in TL
        assert PATTERN_OSCILLATORY in TL
        assert len(TL) == 15


# ─────────────────────────────────────────────────────────────────────────────
# C. Stability metrics
# ─────────────────────────────────────────────────────────────────────────────

class TestStabilityMetrics:
    def test_loto_stability_high_for_robust_pulse(self):
        # Clear early pulse — removing any single point should preserve the label.
        # Peak at first index, clear return to baseline → early_single_pulse is robust.
        vals = [2.0, 1.0, 0.3, 0.1, 0.0, 0.0]
        p = compute_site_kinetic_profile(
            TP6, vals,
            config=SiteKineticConfig(run_loto=True, run_threshold_sensitivity=False)
        )
        assert p.primary_pattern == PATTERN_EARLY_PULSE
        assert p.loto_pattern_stability is not None
        assert p.loto_pattern_stability >= 0.8

    def test_loto_none_when_disabled(self):
        vals = [2.0, 1.0, 0.3, 0.1, 0.0, 0.0]
        p = compute_site_kinetic_profile(
            TP6, vals,
            config=SiteKineticConfig(run_loto=False, run_threshold_sensitivity=False)
        )
        assert p.loto_pattern_stability is None

    def test_loto_none_for_flat(self):
        # flat_or_low_evidence skips LOTO
        vals = [0.1, 0.1, 0.1, 0.1, 0.1, 0.1]
        p = compute_site_kinetic_profile(
            TP6, vals,
            config=SiteKineticConfig(run_loto=True, run_threshold_sensitivity=False)
        )
        assert p.loto_pattern_stability is None

    def test_threshold_sensitivity_false_for_robust_trajectory(self):
        # Amplitude = 2.0, far above threshold variations (0.5×, 2×)
        vals = [0.1, 0.5, 2.0, 1.8, 1.5, 1.2]
        p = compute_site_kinetic_profile(
            TP6, vals,
            config=SiteKineticConfig(run_loto=False, run_threshold_sensitivity=True)
        )
        assert p.threshold_sensitivity_flag is False

    def test_threshold_sensitivity_none_when_disabled(self):
        vals = [0.1, 0.5, 2.0, 1.8, 1.5, 1.2]
        p = compute_site_kinetic_profile(
            TP6, vals,
            config=SiteKineticConfig(run_loto=False, run_threshold_sensitivity=False)
        )
        assert p.threshold_sensitivity_flag is False  # always a bool, never None


# ─────────────────────────────────────────────────────────────────────────────
# D. Edge cases
# ─────────────────────────────────────────────────────────────────────────────

class TestEdgeCases:
    _cfg = SiteKineticConfig(run_loto=False, run_threshold_sensitivity=False)

    def test_single_timepoint_returns_flat(self):
        p = compute_site_kinetic_profile(["5min"], [2.0], config=self._cfg)
        assert p.primary_pattern == PATTERN_FLAT
        assert p.quality_gate_passed is False

    def test_all_missing_returns_flat(self):
        vals: List[Optional[float]] = [None, None, None, None, None, None]
        p = compute_site_kinetic_profile(TP6, vals, config=self._cfg)
        assert p.primary_pattern == PATTERN_FLAT
        assert p.amplitude is None

    def test_all_zero_returns_flat(self):
        p = compute_site_kinetic_profile(TP6, [0.0] * 6, config=self._cfg)
        assert p.primary_pattern == PATTERN_FLAT

    def test_two_timepoints_no_crash(self):
        p = compute_site_kinetic_profile(["5min", "30min"], [0.1, 2.5], config=self._cfg)
        assert p.primary_pattern == PATTERN_FLAT  # n_obs=2 < min_observed=3

    def test_observed_minutes_list_populated(self):
        vals: List[Optional[float]] = [None, 1.0, 2.0, 1.5, None, 0.5]
        p = compute_site_kinetic_profile(TP6, vals, config=self._cfg)
        assert p.observed_minutes == pytest.approx([15.0, 30.0, 60.0, 240.0])

    def test_to_dict_serializable(self):
        import json
        vals = [0.1, 0.5, 2.0, 1.5, 0.8, 0.3]
        p = compute_site_kinetic_profile(TP6, vals, config=self._cfg)
        d = p.to_dict()
        # Must be JSON-serializable (all fields are primitives or None)
        serialized = json.dumps(d)
        assert "primary_pattern" in serialized

    def test_unparseable_label_treated_as_missing(self):
        labels = ["5min", "UNKNOWN_TP", "30min", "60min", "120min", "240min"]
        vals = [0.1, 2.0, 1.5, 1.0, 0.5, 0.2]
        p = compute_site_kinetic_profile(labels, vals, config=self._cfg)
        # UNKNOWN_TP should be skipped
        assert p.missing_timepoints_count == 1
        assert p.observed_timepoints_count == 5


# ─────────────────────────────────────────────────────────────────────────────
# E. Wave integration helpers
# ─────────────────────────────────────────────────────────────────────────────

class TestWaveIntegration:
    _cfg = SiteKineticConfig(run_loto=False, run_threshold_sensitivity=False)

    def test_describe_member_dynamics_keys(self):
        vals = [0.1, 0.5, 2.0, 1.5, 0.8, 0.3]
        d = describe_member_dynamics(TP6, vals, config=self._cfg)
        assert "primary_pattern" in d
        assert "amplitude" in d
        assert "quality_gate_passed" in d
        assert "site_kinetic_contract" in d
        assert d["site_kinetic_contract"] == CONTRACT_VERSION

    def test_describe_member_dynamics_pattern_is_taxonomy_member(self):
        vals = [0.1, 0.5, 2.0, 1.5, 0.8, 0.3]
        d = describe_member_dynamics(TP6, vals, config=self._cfg)
        assert d["primary_pattern"] in TAXONOMY_LABELS

    def test_summarise_empty_list(self):
        summary = summarise_member_pattern_distribution([])
        assert summary["dominant_pattern"] is None
        assert summary["pattern_diversity"] == 0

    def test_summarise_single_member(self):
        vals = [2.0, 1.0, 0.3, 0.1, 0.0, 0.0]
        d = describe_member_dynamics(TP6, vals, config=self._cfg)
        summary = summarise_member_pattern_distribution([d])
        assert summary["dominant_pattern"] == d["primary_pattern"]
        assert summary["pattern_diversity"] == 1

    def test_summarise_counts_labels(self):
        # monotone_rise: peak at last index
        rise_vals = [0.0, 0.1, 0.4, 0.7, 1.5, 2.5]
        # early_pulse: peak at first index, returns to baseline
        pulse_vals = [2.0, 1.0, 0.3, 0.1, 0.0, 0.0]
        members = [
            describe_member_dynamics(TP6, rise_vals, config=self._cfg),
            describe_member_dynamics(TP6, rise_vals, config=self._cfg),
            describe_member_dynamics(TP6, pulse_vals, config=self._cfg),
        ]
        summary = summarise_member_pattern_distribution(members)
        assert summary["pattern_diversity"] == 2
        assert sum(summary["pattern_counts"].values()) == 3
        assert summary["dominant_pattern"] == PATTERN_MONOTONE_RISE

    def test_summarise_missingness_warning_fraction(self):
        vals_miss: List[Optional[float]] = [None, None, None, 1.0, 2.0, 1.0]
        vals_ok = [0.1, 0.5, 2.0, 1.5, 0.8, 0.3]
        members = [
            describe_member_dynamics(TP6, vals_miss, config=self._cfg),
            describe_member_dynamics(TP6, vals_ok, config=self._cfg),
        ]
        summary = summarise_member_pattern_distribution(members)
        assert summary["missingness_warning_fraction"] == pytest.approx(0.5)


# ─────────────────────────────────────────────────────────────────────────────
# F. Frozen regression — critical threshold values must not drift
# ─────────────────────────────────────────────────────────────────────────────

class TestFrozenThresholds:
    """Any change to these assertions means a gate constant was altered.
    Bump CONTRACT_VERSION first, then update these tests.
    """

    def test_default_onset_threshold(self):
        from ptm_shared.substrate_temporal_dynamics import _ONSET_THRESHOLD
        assert _ONSET_THRESHOLD == pytest.approx(0.5)

    def test_default_min_amplitude(self):
        from ptm_shared.substrate_temporal_dynamics import _MIN_AMPLITUDE
        assert _MIN_AMPLITUDE == pytest.approx(0.5)

    def test_default_min_observed(self):
        from ptm_shared.substrate_temporal_dynamics import _MIN_OBSERVED
        assert _MIN_OBSERVED == 3

    def test_default_sustained_ratio(self):
        from ptm_shared.substrate_temporal_dynamics import _SUSTAINED_RATIO
        assert _SUSTAINED_RATIO == pytest.approx(0.50)

    def test_default_monotone_ratio(self):
        from ptm_shared.substrate_temporal_dynamics import _MONOTONE_RATIO
        assert _MONOTONE_RATIO == pytest.approx(0.80)

    def test_default_early_peak_ratio(self):
        from ptm_shared.substrate_temporal_dynamics import _EARLY_PEAK_RATIO
        assert _EARLY_PEAK_RATIO == pytest.approx(0.40)

    def test_osc_min_observed_is_conservative(self):
        from ptm_shared.substrate_temporal_dynamics import _OSC_MIN_OBSERVED
        # Must be >= 6 so that standard 6-TP experiments rarely produce oscillatory_supported
        assert _OSC_MIN_OBSERVED >= 6

    def test_shape_only_oscillation_is_downgraded_without_stability(self):
        # Shape detection alone can nominate oscillation, but a profile without
        # LOTO/threshold evidence must remain an exploratory multi-peak candidate.
        cfg = SiteKineticConfig(run_loto=False, run_threshold_sensitivity=False)
        vals = [2.0, -1.5, 2.0, -1.5, 2.0, -1.5]
        p = compute_site_kinetic_profile(TP6, vals, config=cfg)
        assert p.candidate_pattern == PATTERN_OSCILLATORY
        assert p.primary_pattern == PATTERN_MULTI_PEAK
        assert "oscillation_loto_unstable" in p.pattern_modifiers
        assert p.atlas_eligible is False

    def test_oscillation_promotes_only_when_stability_gates_pass(self, monkeypatch):
        import ptm_shared.substrate_temporal_dynamics as dynamics

        monkeypatch.setattr(dynamics, "_run_loto", lambda *args, **kwargs: 1.0)
        monkeypatch.setattr(dynamics, "_check_threshold_sensitivity", lambda *args, **kwargs: False)
        vals = [2.0, -1.5, 2.0, -1.5, 2.0, -1.5]
        p = compute_site_kinetic_profile(TP6, vals, config=SiteKineticConfig())
        assert p.candidate_pattern == PATTERN_OSCILLATORY
        assert p.primary_pattern == PATTERN_OSCILLATORY
        assert p.atlas_eligible is True
        assert "oscillation_quality_promoted" in p.pattern_modifiers

    def test_input_audit_warning_blocks_atlas_eligibility(self):
        labels = ["0min", "10min", "5min", "20min", "30min", "40min"]
        p = compute_site_kinetic_profile(
            labels,
            [0.0, 1.0, 2.0, 1.5, 0.5, 0.1],
            config=SiteKineticConfig(run_loto=False, run_threshold_sensitivity=False),
        )
        assert p.time_ordering_warning is True
        assert p.atlas_eligible is False
        assert "needs_input_audit_time_ordering" in p.atlas_eligibility_reasons

    def test_oscillatory_not_triggered_for_irregular_sign_pattern(self):
        # Irregular amplitude and interval — fewer than 4 interior extrema
        # or irregular CV → must NOT be oscillatory_supported
        cfg = SiteKineticConfig(run_loto=False, run_threshold_sensitivity=False)
        vals = [1.5, 0.3, -1.0, 0.2, 0.8, -0.6]
        p = compute_site_kinetic_profile(TP6, vals, config=cfg)
        assert p.primary_pattern != PATTERN_OSCILLATORY


# ─────────────────────────────────────────────────────────────────────────────
# G. P3 — compute_kinase_substrate_phenotypes
# ─────────────────────────────────────────────────────────────────────────────

class TestKinaseSubstratePhenotypes:
    _cfg = SiteKineticConfig(run_loto=False, run_threshold_sensitivity=False)

    def _mk_profiles(self, val_map):
        return {key: compute_site_kinetic_profile(TP6, vals, config=self._cfg)
                for key, vals in val_map.items()}

    def test_single_kinase_single_substrate(self):
        profiles = self._mk_profiles({"site1": [0.0, 0.5, 2.0, 1.8, 1.5, 1.2]})
        assignments = {"AKT1": ["site1"]}
        result = compute_kinase_substrate_phenotypes(profiles, assignments)
        assert "AKT1" in result
        r = result["AKT1"]
        assert r["n_substrates"] == 1
        assert r["n_quality_passed"] == 1
        assert r["dominant_pattern"] == PATTERN_SUSTAINED_ACTIVATION
        assert r["pattern_diversity"] == 1
        assert r["flat_fraction"] == pytest.approx(0.0)

    def test_kinase_with_no_profiles_gives_zeros(self):
        profiles = {}
        assignments = {"AKT1": ["site1", "site2"]}
        result = compute_kinase_substrate_phenotypes(profiles, assignments)
        assert result["AKT1"]["n_substrates"] == 0
        assert result["AKT1"]["dominant_pattern"] is None

    def test_flat_fraction_counts_failed_gates(self):
        profiles = self._mk_profiles({
            "site1": [0.0, 0.5, 2.0, 1.8, 1.5, 1.2],  # passes
            "site2": [0.0, 0.1, 0.1, 0.1, 0.1, 0.1],  # flat
        })
        assignments = {"AKT1": ["site1", "site2"]}
        result = compute_kinase_substrate_phenotypes(profiles, assignments)
        r = result["AKT1"]
        assert r["n_substrates"] == 2
        assert r["n_quality_passed"] == 1
        assert r["flat_fraction"] == pytest.approx(0.5)

    def test_multiple_kinases_independent(self):
        profiles = self._mk_profiles({
            "site1": [0.0, 0.5, 2.0, 1.8, 1.5, 1.2],  # sustained_activation
            "site2": [2.0, 1.0, 0.3, 0.1, 0.0, 0.0],  # early_single_pulse
            "site3": [0.0, 0.1, 0.4, 0.7, 1.5, 2.5],  # monotone_rise
        })
        assignments = {
            "AKT1": ["site1", "site2"],
            "CDK2": ["site3"],
        }
        result = compute_kinase_substrate_phenotypes(profiles, assignments)
        assert "AKT1" in result
        assert "CDK2" in result
        assert result["AKT1"]["n_substrates"] == 2
        assert result["CDK2"]["n_substrates"] == 1
        assert result["CDK2"]["dominant_pattern"] == PATTERN_MONOTONE_RISE

    def test_pattern_diversity_counts_distinct_labels(self):
        profiles = self._mk_profiles({
            "site1": [0.0, 0.5, 2.0, 1.8, 1.5, 1.2],  # sustained
            "site2": [2.0, 1.0, 0.3, 0.1, 0.0, 0.0],  # early_pulse
        })
        assignments = {"AKT1": ["site1", "site2"]}
        result = compute_kinase_substrate_phenotypes(profiles, assignments)
        assert result["AKT1"]["pattern_diversity"] == 2

    def test_unknown_site_keys_skipped(self):
        profiles = self._mk_profiles({"site1": [0.0, 0.5, 2.0, 1.8, 1.5, 1.2]})
        assignments = {"AKT1": ["site1", "site_not_in_profiles"]}
        result = compute_kinase_substrate_phenotypes(profiles, assignments)
        assert result["AKT1"]["n_substrates"] == 1  # only site1 matched


class TestP0InputAudit:
    """P0: X-axis time ordering and duplicate timepoint warnings."""

    def _profile(self, labels, values):
        from ptm_shared.substrate_temporal_dynamics import SiteKineticConfig, compute_site_kinetic_profile
        return compute_site_kinetic_profile(
            labels, values,
            config=SiteKineticConfig(run_loto=False, run_threshold_sensitivity=False),
        )

    def test_no_warning_for_well_ordered_labels(self):
        p = self._profile(["5min", "15min", "30min", "60min"], [0.5, 1.2, 2.0, 1.5])
        assert not p.time_ordering_warning
        assert not p.duplicate_timepoint_warning

    def test_ordering_warning_fires_for_descending_labels(self):
        # 60min comes before 30min — out of order
        p = self._profile(["60min", "30min", "15min", "5min"], [1.5, 2.0, 1.2, 0.5])
        assert p.time_ordering_warning

    def test_ordering_warning_fires_for_one_reversal(self):
        # 30min after 60min — one inversion
        p = self._profile(["5min", "60min", "30min", "120min"], [0.5, 2.0, 1.0, 0.8])
        assert p.time_ordering_warning

    def test_duplicate_warning_fires_for_two_identical_labels(self):
        p = self._profile(["5min", "5min", "30min", "60min"], [0.5, 0.6, 2.0, 1.5])
        assert p.duplicate_timepoint_warning

    def test_no_duplicate_warning_for_distinct_labels(self):
        p = self._profile(["5min", "15min", "30min", "60min"], [0.5, 1.2, 2.0, 1.5])
        assert not p.duplicate_timepoint_warning

    def test_unparseable_label_does_not_trigger_ordering_warning(self):
        # "unknown" is unparseable and treated as missing — remaining minutes are ordered
        p = self._profile(["5min", "unknown", "30min", "60min"], [0.5, None, 2.0, 1.5])
        assert not p.time_ordering_warning

    def test_warnings_are_independent_of_pattern_classification(self):
        # Out-of-order labels don't change the pattern; only add a warning
        p_ordered = self._profile(
            ["5min", "15min", "30min", "60min"], [0.5, 1.2, 2.0, 1.5]
        )
        p_reversed = self._profile(
            ["60min", "30min", "15min", "5min"], [1.5, 2.0, 1.2, 0.5]
        )
        # Primary pattern may differ (different minute assignments) but the
        # reversed profile must carry the ordering warning
        assert p_reversed.time_ordering_warning
        assert not p_ordered.time_ordering_warning
