import numpy as np

from ptm_shared.replicate_event_adapter import (
    EventStatus,
    _event_specific_details,
    _event_times_from_trajectory,
    extract_event_record,
)
from ptm_shared.study_temporal_context import StudyTemporalContext


TIMES = np.asarray([1.0, 5.0, 15.0, 30.0])


def _context():
    return StudyTemporalContext(
        study_id="generic_test_context",
        time_unit_label="minutes",
        nominal_grid_interval_minutes=4.0,
        gp_length_scale_min_minutes=8.0,
        synchrony_tau_minutes=4.0,
        gp_length_scale_source="focused unit-test contract",
        chemical_holdout_description="not applicable to timing contract fixture",
        pre_registration_date="2026-09-10",
        pre_registered=True,
    )


def test_event_details_preserve_left_censored_onset_and_right_censored_exit_simultaneously():
    event = _event_times_from_trajectory(
        TIMES,
        np.asarray([1.0, 2.0, 1.5, 1.0]),
        amplitude_threshold=0.5,
        raw_first_abs_fc=1.0,
        raw_last_abs_fc=1.0,
    )
    onset, peak, exit_record = _event_specific_details(TIMES, event)

    assert event["status"] == EventStatus.left_censored
    assert onset["censoring_type"] == "left"
    assert onset["sampled_interval_min"] == [None, 1.0]
    assert exit_record["censoring_type"] == "right"
    assert exit_record["sampled_interval_min"] == [30.0, None]
    assert peak["effect_direction"] == "positive"


def test_threshold_crossings_between_sampled_times_are_interval_censored_model_estimates():
    event = _event_times_from_trajectory(
        TIMES,
        np.asarray([0.0, 1.0, 0.0, 0.0]),
        amplitude_threshold=0.8,
        raw_first_abs_fc=0.0,
        raw_last_abs_fc=0.0,
    )
    onset, _, exit_record = _event_specific_details(TIMES, event)

    assert onset["censoring_type"] == "interval"
    assert onset["sampled_interval_min"] == [1.0, 5.0]
    assert onset["estimate_type"] == "model_interpolated"
    assert exit_record["censoring_type"] == "interval"
    assert exit_record["sampled_interval_min"] == [5.0, 15.0]
    assert exit_record["estimate_type"] == "model_interpolated"


def test_unresolved_response_marks_onset_not_observed_and_exit_not_applicable():
    event = _event_times_from_trajectory(
        TIMES,
        np.asarray([0.0, 0.1, 0.1, 0.0]),
        amplitude_threshold=0.5,
        raw_first_abs_fc=0.0,
        raw_last_abs_fc=0.0,
    )
    onset, peak, exit_record = _event_specific_details(TIMES, event)

    assert event["status"] == EventStatus.unresolved
    assert onset["observation_status"] == "not_observed_within_window"
    assert onset["censoring_type"] == "right"
    assert peak["observation_status"] == "below_activity_threshold"
    assert exit_record["observation_status"] == "not_applicable"


def test_public_condition_mean_builder_populates_event_specific_records_and_legacy_fields():
    record = extract_event_record(
        "GENE1_S2",
        ["1min", "5min", "15min", "30min"],
        [0.0, 1.0, 0.2, 0.0],
        study_context=_context(),
        amplitude_threshold=0.5,
        n_bootstrap=20,
        seed=17,
    )

    assert record.contract_version == "replicate_event_adapter.v2"
    assert record.event_detail_contract_version == "temporal_event_details.v1"
    assert record.onset_event["observation_status"] == "observed_within_window"
    assert record.peak_event["effect_direction"] == "positive"
    assert record.exit_event["observation_status"] in {"observed_within_window", "ambiguous"}
    assert record.peak_t_min is not None
