from ptm_shared.substrate_temporal_dynamics import SiteKineticConfig, compute_site_kinetic_profile
from ptm_shared.time_varying_comovement import (
    TimeVaryingCoMovementConfig,
    compute_time_varying_comovement,
)


LABELS = ["0min", "5min", "10min", "15min"]


def _profile(values):
    return compute_site_kinetic_profile(
        LABELS,
        values,
        config=SiteKineticConfig(run_loto=False, run_threshold_sensitivity=False),
    )


def test_transition_engine_detects_split_recruitment_and_exit_without_causal_claims():
    trajectories = {
        "A_S1": [0.0, 2.0, 0.1, 0.0],
        "B_S2": [0.0, 1.8, 0.1, 0.0],
        "C_S3": [0.0, 2.1, 2.0, 2.0],
        "D_S4": [0.0, 0.0, 1.9, 2.0],
    }
    profiles = {key: _profile(values) for key, values in trajectories.items()}
    result = compute_time_varying_comovement(LABELS, trajectories, profiles=profiles)
    pair_types = {item.transition_type for item in result.pair_transitions}
    site_types = {item.transition_type for item in result.site_transitions}
    assert "split" in pair_types
    assert "recruitment" in pair_types
    assert "exit" in site_types
    assert result.contract_version == "time_varying_comovement.v1"


def test_transition_engine_excludes_atlas_ineligible_profiles():
    trajectories = {
        "ordered": [0.0, 2.0, 1.0, 0.2],
        "bad_input": [0.0, 2.0, 1.0, 0.2],
    }
    profiles = {
        "ordered": _profile(trajectories["ordered"]),
        "bad_input": compute_site_kinetic_profile(
            ["0min", "10min", "5min", "15min"],
            trajectories["bad_input"],
            config=SiteKineticConfig(run_loto=False, run_threshold_sensitivity=False),
        ),
    }
    result = compute_time_varying_comovement(LABELS, trajectories, profiles=profiles)
    assert "bad_input" in result.excluded_sites
    assert "needs_input_audit_time_ordering" in result.excluded_sites["bad_input"]
    assert all(item.site_key != "bad_input" for item in result.memberships)


def test_independent_activation_requires_no_new_coactive_partner():
    trajectories = {
        "A_S1": [0.0, 2.0, 2.0, 0.0],
        "B_S2": [0.0, 0.0, -2.0, -2.0],
    }
    profiles = {key: _profile(values) for key, values in trajectories.items()}
    result = compute_time_varying_comovement(LABELS, trajectories, profiles=profiles)
    assert any(
        item.site_key == "B_S2" and item.transition_type == "independent_activation"
        for item in result.site_transitions
    )


def test_missing_endpoint_is_not_evaluable_not_inactive():
    trajectories = {
        "A_S1": [0.0, 1.5, None],
        "B_S2": [0.0, 1.3, None],
    }
    result = compute_time_varying_comovement(
        ["0min", "5min", "15min"],
        trajectories,
        config=TimeVaryingCoMovementConfig(
            activity_threshold_fc=0.4,
            min_window_observed=2,
            require_atlas_eligible=False,
            include_inert_site_observations=False,
        ),
    ).to_dict()
    states = {
        (row["site_key"], row["window_label"]): row["activity_state"]
        for row in result["memberships"]
    }
    assert states[("A_S1", "5min→15min")] == "not_evaluable"
    assert states[("B_S2", "5min→15min")] == "not_evaluable"
    assert result["pair_transitions"] == []
    assert result["pair_scope"]["non_evaluable_pair_window_comparison_count"] == 1
    assert result["event_exposure"]["non_evaluable_site_transition_count"] == 2
