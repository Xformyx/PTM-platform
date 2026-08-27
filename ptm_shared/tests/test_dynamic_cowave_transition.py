from benchmarking.dynamic_cowave_evaluation import evaluate_dynamic_candidate
from ptm_shared.dynamic_cowave_transition import analyze_dynamic_co_wave_transitions
from ptm_shared.enrichment_free_temporal_sidecar import summarize_temporal_ptm_protein_analysis


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
