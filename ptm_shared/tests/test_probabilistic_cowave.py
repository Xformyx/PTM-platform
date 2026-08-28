"""Tests for ptm_shared/probabilistic_cowave.py.

Verifies GP posterior properties, P(active) calibration, and the full
wave-level annotation contract.
"""
import math

import pytest

from ptm_shared.probabilistic_cowave import (
    CONTRACT_VERSION,
    ACTIVITY_THRESHOLD_FC,
    estimate_trajectory_posterior,
    p_same_derivative_direction,
    probabilistic_transition_annotation,
)


# ── Shared fixtures ────────────────────────────────────────────────────────

def _simple_wave_contract() -> dict:
    labels = ["1min", "5min", "15min", "30min", "60min"]
    members = {
        "A_S1": {"1min": 0.0, "5min": 1.2, "15min": 1.4, "30min": 0.5, "60min": 0.1},
        "B_S1": {"1min": 0.0, "5min": 1.0, "15min": 1.3, "30min": 0.3, "60min": 0.0},
        "C_S1": {"1min": 0.0, "5min": -0.1, "15min": 0.1, "30min": 1.1, "60min": 1.2},
    }
    return {
        "timepoints": labels,
        "waves": [
            {
                "wave_id": "TW-01",
                "members": list(members.keys()),
                "member_details": [
                    {"key": key, "temporal_values": vals}
                    for key, vals in members.items()
                ],
            }
        ],
    }


# ── estimate_trajectory_posterior ─────────────────────────────────────────

def test_posterior_shape_matches_input() -> None:
    labels = ["1min", "5min", "15min", "30min", "60min"]
    fcs = [0.0, 1.2, 1.4, 0.5, 0.1]
    result = estimate_trajectory_posterior(labels, fcs)
    assert len(result["posterior_mean"]) == len(labels)
    assert len(result["posterior_std"]) == len(labels)
    assert len(result["p_active"]) == len(labels)
    assert len(result["p_inactive"]) == len(labels)
    assert result["contract_version"] == CONTRACT_VERSION


def test_p_active_sums_correctly() -> None:
    labels = ["1min", "5min", "15min"]
    fcs = [0.0, 1.5, 0.5]
    result = estimate_trajectory_posterior(labels, fcs)
    for i in range(len(labels)):
        p_sum = result["p_positive_active"][i] + result["p_negative_active"][i] + result["p_inactive"][i]
        assert math.isclose(p_sum, 1.0, abs_tol=1e-5), f"probabilities don't sum to 1 at index {i}: {p_sum}"


def test_high_fc_gives_high_p_active() -> None:
    labels = ["1min", "5min"]
    # Clear activation: well above threshold
    fcs = [2.0, 2.5]
    result = estimate_trajectory_posterior(labels, fcs, activity_threshold_fc=0.4)
    for p in result["p_active"]:
        assert p > 0.8, f"Expected high P(active) for large FC, got {p}"


def test_zero_fc_gives_low_p_active() -> None:
    labels = ["1min", "5min", "15min"]
    fcs = [0.0, 0.0, 0.0]
    result = estimate_trajectory_posterior(labels, fcs, activity_threshold_fc=0.4)
    for p in result["p_active"]:
        assert p < 0.2, f"Expected low P(active) for zero FC, got {p}"


def test_missing_values_handled() -> None:
    labels = ["1min", "5min", "15min", "30min"]
    fcs = [None, 1.2, None, 0.8]
    result = estimate_trajectory_posterior(labels, fcs)
    assert len(result["posterior_mean"]) == 4
    assert all(not math.isnan(v) for v in result["posterior_mean"])


def test_all_missing_returns_prior() -> None:
    labels = ["1min", "5min", "15min"]
    fcs = [None, None, None]
    result = estimate_trajectory_posterior(labels, fcs, signal_var=1.0)
    # Prior mean = 0 → all p_active should be moderate (near 0.5 for threshold=0)
    assert all(not math.isnan(v) for v in result["posterior_mean"])


def test_hyperparameters_recorded() -> None:
    labels = ["1min", "5min"]
    fcs = [1.0, 1.5]
    result = estimate_trajectory_posterior(labels, fcs, length_scale_min=20.0, noise_var_fraction=0.15)
    hyp = result["hyperparameters"]
    assert hyp["length_scale_min"] == 20.0
    assert hyp["noise_var_fraction"] == 0.15


# ── p_same_derivative_direction ───────────────────────────────────────────

def test_same_direction_monotone_increasing() -> None:
    labels = ["1min", "5min", "15min"]
    fcs_a = [0.0, 1.0, 2.0]
    fcs_b = [0.0, 0.8, 1.6]
    post_a = estimate_trajectory_posterior(labels, fcs_a)
    post_b = estimate_trajectory_posterior(labels, fcs_b)
    p = p_same_derivative_direction(post_a, post_b, window_index=0)
    assert p > 0.6, f"Expected high P(same direction) for parallel trajectories, got {p}"


def test_opposite_direction_gives_low_probability() -> None:
    labels = ["1min", "5min", "15min"]
    fcs_a = [0.0, 1.5, 2.5]  # increasing
    fcs_b = [0.0, -1.5, -2.5]  # decreasing
    post_a = estimate_trajectory_posterior(labels, fcs_a)
    post_b = estimate_trajectory_posterior(labels, fcs_b)
    p = p_same_derivative_direction(post_a, post_b, window_index=0)
    assert p < 0.5, f"Expected low P(same direction) for opposite trajectories, got {p}"


def test_out_of_range_window_returns_nan() -> None:
    labels = ["1min", "5min"]
    fcs = [0.0, 1.0]
    post = estimate_trajectory_posterior(labels, fcs)
    p = p_same_derivative_direction(post, post, window_index=10)
    assert math.isnan(p)


# ── probabilistic_transition_annotation ───────────────────────────────────

def test_annotation_status_computed() -> None:
    contract = _simple_wave_contract()
    result = probabilistic_transition_annotation(contract)
    assert result["status"] == "computed"
    assert result["contract_version"] == CONTRACT_VERSION


def test_annotation_covers_all_sites() -> None:
    contract = _simple_wave_contract()
    result = probabilistic_transition_annotation(contract)
    expected_sites = {"A_S1", "B_S1", "C_S1"}
    assert set(result["site_posteriors"].keys()) == expected_sites


def test_annotation_membership_not_mutated() -> None:
    contract = _simple_wave_contract()
    original_members = list(contract["waves"][0]["members"])
    probabilistic_transition_annotation(contract)
    assert contract["waves"][0]["members"] == original_members


def test_annotation_provenance_fields_present() -> None:
    result = probabilistic_transition_annotation(_simple_wave_contract())
    prov = result["provenance"]
    assert prov["membership_mutation"] == "forbidden"
    assert prov["tmm_mutation"] == "forbidden"
    assert "pre_registration_date" in prov
    assert "hyperparameter_sha256" in prov


def test_annotation_summary_fields_present() -> None:
    result = probabilistic_transition_annotation(_simple_wave_contract())
    s = result["summary"]
    assert s["n_sites"] == 3
    assert s["n_windows"] == 4
    assert s["mean_p_active_across_sites_and_windows"] is not None
    assert 0.0 <= s["mean_p_active_across_sites_and_windows"] <= 1.0


def test_annotation_skipped_empty_wave_contract() -> None:
    result = probabilistic_transition_annotation({"timepoints": [], "waves": []})
    assert result["status"] == "skipped_no_timepoints"


def test_pair_soft_coactivity_within_wave_only() -> None:
    contract = _simple_wave_contract()
    result = probabilistic_transition_annotation(contract)
    wave_id = contract["waves"][0]["wave_id"]
    for entry in result["pair_soft_coactivity"]:
        assert entry["wave_id"] == wave_id
        assert 0.0 <= entry["p_both_active"] <= 1.0
