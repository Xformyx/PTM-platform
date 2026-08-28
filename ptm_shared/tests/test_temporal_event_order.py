from __future__ import annotations

from ptm_shared.temporal_event_order import (
    CONTRACT_VERSION,
    bootstrap_event_time_uncertainty,
    build_temporal_event_order_evidence,
    extract_observed_event_time,
)
from ptm_shared.enrichment_free_temporal_sidecar import (
    build_v2_sidecar,
    summarize_temporal_ptm_protein_analysis,
)


def test_interpolates_half_amplitude_time_without_inventing_a_peak() -> None:
    row = extract_observed_event_time(
        "AKT1_S473",
        ["0min", "5min", "15min", "30min"],
        [0.0, 0.4, 1.2, 0.6],
    )
    assert row["event_status"] == "resolved_interpolated"
    assert row["direction"] == "up"
    assert row["t50_minutes"] == 7.5
    assert row["t50_interval"] == {"left_minutes": 5.0, "right_minutes": 15.0}
    assert row["peak_time_status"] == "observed"


def test_marks_left_censoring_when_first_observation_is_already_high() -> None:
    row = extract_observed_event_time(
        "ERK1_T202",
        ["1min", "5min", "15min", "30min"],
        [1.2, 1.0, 0.4, 0.1],
    )
    assert row["event_status"] == "left_censored_before_first_observed"
    assert row["t50_minutes"] is None
    assert row["t50_interval"] == {"upper_bound_minutes": 1.0}


def test_marks_endpoint_peak_as_right_censored() -> None:
    row = extract_observed_event_time(
        "S6_S235",
        ["0min", "5min", "15min", "30min"],
        [0.0, 0.1, 0.5, 1.0],
    )
    assert row["event_status"] == "resolved_at_observed_timepoint"
    assert row["peak_time_status"] == "right_censored"


def test_replicate_bootstrap_ci_is_deterministic_and_does_not_persist_raw_values() -> None:
    replicates = {
        "0min": [0.0, 0.02, -0.01],
        "5min": [0.25, 0.35, 0.30],
        "15min": [1.10, 1.20, 1.30],
        "30min": [0.50, 0.60, 0.55],
    }
    first = bootstrap_event_time_uncertainty("AKT1_S473", list(replicates), replicates, config={"bootstrap_repeats": 60})
    second = bootstrap_event_time_uncertainty("AKT1_S473", list(replicates), replicates, config={"bootstrap_repeats": 60})
    assert first == second
    assert first["replicate_uncertainty_status"] == "bootstrap_ci95_available"
    assert first["t50_bootstrap_ci95"]["lower_minutes"] <= first["t50_bootstrap_ci95"]["upper_minutes"]
    assert "replicates" not in first


def test_replicate_bootstrap_refuses_incomplete_timepoint_coverage() -> None:
    result = bootstrap_event_time_uncertainty(
        "AKT1_S473",
        ["0min", "5min", "15min", "30min"],
        {"0min": [0.0, 0.0], "5min": [0.2], "15min": [1.0, 1.1], "30min": [0.5, 0.6]},
    )
    assert result["replicate_uncertainty_status"] == "not_evaluable_incomplete_replicate_coverage"


def test_invalid_axis_is_rejected_instead_of_silently_sorted() -> None:
    row = extract_observed_event_time(
        "X_S1",
        ["5min", "1min", "15min", "30min"],
        [0.0, 0.1, 0.9, 0.6],
    )
    assert row["event_status"] == "invalid_time_axis"
    assert "non_strictly_increasing_time_axis" in row["quality_flags"]


def test_contract_is_additive_and_explicit_about_missing_replicates() -> None:
    wave_contract = {
        "timepoints": ["0min", "5min", "15min", "30min"],
        "waves": [{
            "wave_id": "TW-01",
            "member_details": [
                {"key": "A_S1", "temporal_values": {"0min": 0.0, "5min": 0.4, "15min": 1.2, "30min": 0.5}},
                {"key": "B_S1", "temporal_values": {"0min": 0.0, "5min": 0.2, "15min": 0.9, "30min": 0.3}},
            ],
        }],
    }
    result = build_temporal_event_order_evidence(wave_contract)
    assert result["contract_version"] == CONTRACT_VERSION
    assert result["status"] == "computed_condition_mean_only"
    assert result["summary"]["temporal_order_validation_status"] == "not_evaluable_replicate_missing"
    assert result["provenance"]["membership_mutation"] == "forbidden"
    assert result["provenance"]["benchmark_truth_used"] is False
    assert len(result["site_events"]) == 2


def test_sidecar_projects_event_contract_without_mutating_dynamic_or_tmm(tmp_path) -> None:
    wave_contract = {
        "timepoints": ["0min", "5min", "15min", "30min"],
        "waves": [{
            "wave_id": "TW-01",
            "members": ["A_S1", "B_S1"],
            "member_details": [
                {"key": "A_S1", "temporal_values": {"0min": 0.0, "5min": 0.4, "15min": 1.2, "30min": 0.5}},
                {"key": "B_S1", "temporal_values": {"0min": 0.0, "5min": 0.2, "15min": 0.9, "30min": 0.3}},
            ],
            "mean_profile": {"0min": 0.0, "5min": 0.3, "15min": 1.05, "30min": 0.4},
        }],
    }
    sidecar = build_v2_sidecar(
        output_dir=tmp_path,
        ptm_type="phosphorylation",
        site_observations=[],
        wave_contract=wave_contract,
        tmm_result={"conditions": ["0min", "5min", "15min", "30min"], "kinase_scores": []},
    )
    compact = summarize_temporal_ptm_protein_analysis(sidecar)
    assert sidecar["temporal_wave_contract"] == wave_contract
    assert sidecar["temporal_event_order"]["contract_version"] == CONTRACT_VERSION
    assert sidecar["temporal_event_order"]["summary"]["site_event_count"] == 2
    assert sidecar["dynamic_co_wave_transition"]["contract_version"] == "dynamic_co_wave_transition.v2"
    assert compact["temporal_event_order_status"] == "computed_condition_mean_only"
    assert compact["temporal_event_order_validation_status"] == "not_evaluable_replicate_missing"
