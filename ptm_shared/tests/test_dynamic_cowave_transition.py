from benchmarking.dynamic_cowave_evaluation import evaluate_dynamic_candidate
from ptm_shared.dynamic_cowave_transition import (
    DEFAULT_CONFIG,
    analyze_dynamic_co_wave_transitions,
    dynamic_transition_config_sha256,
)
from ptm_shared.enrichment_free_temporal_sidecar import summarize_temporal_ptm_protein_analysis
from ptm_shared.temporal_optimization_config import (
    DYNAMIC_COWAVE_CONFIG,
    DYNAMIC_COWAVE_CONTRACT_VERSION,
)
from ptm_shared.time_varying_comovement import (
    TimeVaryingCoMovementConfig,
    compute_time_varying_comovement,
)


def _wave_contract() -> dict:
    labels = ["1min", "5min", "15min", "30min", "60min"]
    members = {
        "A_S1": [0.0, 1.0, 1.1, 0.2, 0.0],
        "B_S1": [0.0, 1.2, 1.0, 0.1, 0.0],
        "C_S1": [0.0, 0.0, 0.2, 1.2, 1.1],
        "D_S1": [0.0, 0.0, 0.1, 1.1, 1.3],
    }
    return {
        "contract_version": "temporal_wave_contract.v1",
        "timepoints": labels,
        "threshold_provenance": {"config_sha256": "static"},
        "waves": [
            {
                "wave_id": "TW-01",
                "members": list(members),
                "member_details": [
                    {"key": key, "temporal_values": dict(zip(labels, values))}
                    for key, values in members.items()
                ],
            }
        ],
    }


def test_dynamic_annotation_preserves_static_membership_and_records_transitions() -> None:
    contract = _wave_contract()
    before = list(contract["waves"][0]["members"])
    result = analyze_dynamic_co_wave_transitions(contract, config={"activity_threshold_fc": 0.5, "minimum_observed_timepoints": 4})
    assert contract["waves"][0]["members"] == before
    assert result["provenance"]["membership_mutation"] == "forbidden"
    assert result["summary"]["transition_supported_wave_count"] == 1
    assert result["summary"]["transition_resolution"] is not None
    assert result["lotto"]["evaluable_pair_fold_count"] > 0
    assert "pair_transitions" not in result
    assert result["transition_examples"]["truncation"]["full_event_sets_used_for_metrics"] is True
    wave_summary = result["per_wave_summary"][0]
    assert sum(wave_summary["pair_transition_type_counts"].values()) == wave_summary["pair_transition_count"]
    assert sum(wave_summary["site_transition_type_counts"].values()) == wave_summary["site_transition_count"]


def test_dynamic_default_config_matches_frozen_production_baseline() -> None:
    assert DEFAULT_CONFIG["activity_threshold_fc"] == DYNAMIC_COWAVE_CONFIG["activity_threshold_fc"]
    assert DEFAULT_CONFIG["minimum_observed_timepoints"] == DYNAMIC_COWAVE_CONFIG["minimum_observed_timepoints"]
    default_result = analyze_dynamic_co_wave_transitions(_wave_contract())
    explicit_result = analyze_dynamic_co_wave_transitions(_wave_contract(), config=DYNAMIC_COWAVE_CONFIG)
    assert default_result["provenance"]["config_sha256"] == explicit_result["provenance"]["config_sha256"]
    assert default_result["contract_version"] == DYNAMIC_COWAVE_CONTRACT_VERSION


def test_dynamic_scopes_pairs_and_site_partners_to_static_wave() -> None:
    labels = ["1min", "5min", "15min"]
    contract = {
        "contract_version": "temporal_wave_contract.v1",
        "timepoints": labels,
        "waves": [
            {
                "wave_id": "TW-01",
                "members": ["A_S1", "B_S1"],
                "member_details": [
                    {"key": "A_S1", "temporal_values": dict(zip(labels, [0.0, 1.0, 1.0]))},
                    {"key": "B_S1", "temporal_values": dict(zip(labels, [0.0, 0.0, 0.0]))},
                ],
            },
            {
                "wave_id": "TW-02",
                "members": ["C_S1"],
                "member_details": [
                    {"key": "C_S1", "temporal_values": dict(zip(labels, [0.0, 1.0, 1.0]))},
                ],
            },
        ],
    }
    result = analyze_dynamic_co_wave_transitions(
        contract,
        config={"activity_threshold_fc": 0.4, "minimum_observed_timepoints": 3},
    )
    # A and C are co-active at both windows but belong to different static
    # Waves. They must not create partner counts or a group-persistence event.
    assert result["summary"]["site_transition_count"] == 0
    assert result["summary"]["within_wave_candidate_pair_count"] == 1
    assert result["summary"]["cross_wave_pair_excluded_count"] == 2
    assert result["event_exposure"]["inert_site_observation_count"] == 3
    assert result["pair_scope"]["mode"] == "same_group_only"


def test_dynamic_excludes_inert_site_observations_but_keeps_exposure() -> None:
    result = analyze_dynamic_co_wave_transitions(
        _wave_contract(),
        config={"activity_threshold_fc": 5.0, "minimum_observed_timepoints": 4},
    )
    assert result["summary"]["site_transition_count"] == 0
    assert result["event_exposure"]["site_transition_opportunity_count"] == 12
    assert result["event_exposure"]["inert_site_observation_count"] == 12


def test_single_wave_group_scoping_matches_intended_global_pair_semantics() -> None:
    contract = _wave_contract()
    labels = contract["timepoints"]
    trajectories = {
        row["key"]: [row["temporal_values"][label] for label in labels]
        for row in contract["waves"][0]["member_details"]
    }
    config = TimeVaryingCoMovementConfig(
        activity_threshold_fc=0.4,
        min_window_observed=4,
        require_atlas_eligible=False,
        include_inert_site_observations=False,
    )
    global_result = compute_time_varying_comovement(labels, trajectories, config=config).to_dict()
    scoped_result = compute_time_varying_comovement(
        labels,
        trajectories,
        config=config,
        group_by_site={site_key: "TW-01" for site_key in trajectories},
    ).to_dict()
    assert scoped_result["pair_transitions"] == global_result["pair_transitions"]
    assert scoped_result["site_transitions"] == global_result["site_transitions"]
    assert scoped_result["event_exposure"] == global_result["event_exposure"]
    assert scoped_result["pair_scope"]["candidate_pair_count"] == global_result["pair_scope"]["candidate_pair_count"]


def test_low_level_default_preserves_legacy_inert_observations() -> None:
    result = compute_time_varying_comovement(
        ["1min", "5min", "15min"],
        {"A_S1": [0.0, 0.0, 0.0]},
        config=TimeVaryingCoMovementConfig(require_atlas_eligible=False),
    ).to_dict()
    assert [row["transition_type"] for row in result["site_transitions"]] == [
        "state_unchanged_or_inactive"
    ]
    assert result["event_exposure"]["inert_site_observation_count"] == 1


def test_compact_summary_preserves_dynamic_scope_and_exposure_provenance() -> None:
    dynamic = analyze_dynamic_co_wave_transitions(_wave_contract(), config=DYNAMIC_COWAVE_CONFIG)
    dynamic["status"] = "computed"
    summary = summarize_temporal_ptm_protein_analysis({"dynamic_co_wave_transition": dynamic})
    assert summary["dynamic_transition_pair_scope"]["mode"] == "same_group_only"
    assert summary["dynamic_transition_event_exposure"]["recorded_site_transition_count"] == dynamic["summary"]["site_transition_count"]


def test_truth_free_evaluation_never_promotes_causality() -> None:
    artifact = {"temporal_wave_contract": _wave_contract(), "v2_extensions": {"cross_layer_edges": []}}
    result = evaluate_dynamic_candidate(
        artifact,
        config={"activity_threshold_fc": 0.5, "minimum_observed_timepoints": 4},
        adoption_gate={
            "minimum_pair_loto_jaccard": 0.0,
            "minimum_site_loto_jaccard": 0.0,
            "minimum_active_pair_coverage": 0.0,
            "minimum_transition_resolution_exclusive": 0.0,
            "maximum_transition_resolution_exclusive": 1.0,
            "minimum_stable_transition_waves": 1,
        },
    )
    assert result["adoption_gate"]["causality_status"] == "not_tested"
    assert result["selection_boundary"].startswith("Truth-free")


def test_compact_sidecar_summary_reports_disabled_transition_explicitly() -> None:
    summary = summarize_temporal_ptm_protein_analysis(
        {"dynamic_co_wave_transition": {"status": "disabled_by_caller"}}
    )
    assert summary["dynamic_co_wave_transition_status"] == "disabled_by_caller"
    assert summary["dynamic_transition_supported_wave_count"] is None


def test_compact_sidecar_summary_exposes_frozen_dynamic_config_hash() -> None:
    config = {"activity_threshold_fc": 0.4, "minimum_observed_timepoints": 4}
    dynamic = analyze_dynamic_co_wave_transitions(_wave_contract(), config=config)
    dynamic["status"] = "computed"
    summary = summarize_temporal_ptm_protein_analysis(
        {"dynamic_co_wave_transition": dynamic}
    )
    assert summary["dynamic_co_wave_transition_status"] == "computed"
    assert summary["dynamic_co_wave_transition_config_sha256"] == dynamic_transition_config_sha256(config)
