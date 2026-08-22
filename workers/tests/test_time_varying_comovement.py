from ptm_shared.substrate_temporal_dynamics import SiteKineticConfig, compute_site_kinetic_profile
from ptm_shared.time_varying_comovement import compute_time_varying_comovement


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
