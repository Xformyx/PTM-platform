"""Signed interval diagnostics. Does not change TMM scores."""
from ptm_shared.kinase_trajectory_evidence import (
    CONTRACT_VERSION,
    compute_kinase_trajectory_evidence,
    compute_target_trajectory_evidence,
    scheduled_intervals,
)


CONDITIONS = ["1min", "5min", "15min", "30min"]


def _series(values):
    return {condition: value for condition, value in zip(CONDITIONS, values) if value is not None}


def test_same_endpoint_different_middle_is_preserved():
    timeseries = {
        "T": _series([0.0, 2.0, 0.2, 1.0]),
        "A1": _series([0.0, 0.1, 1.8, 1.0]),
        "A2": _series([0.0, 0.2, 1.6, 0.9]),
    }
    result = compute_target_trajectory_evidence(
        candidate="K1",
        target_key="T",
        timeseries=timeseries,
        conditions=CONDITIONS,
        eligible_keys=["T", "A1", "A2"],
    )
    comparisons = [row["comparison"] for row in result["metrics"]["interval_direction_support"]]
    assert "opposite_direction" in comparisons
    assert result["metrics"]["signed_profile_correlation"]["value"] is not None


def test_missing_middle_is_not_bridged():
    timeseries = {
        "T": {"1min": 0.0, "15min": 1.0, "30min": 1.2},
        "A1": {"1min": 0.0, "15min": 1.0, "30min": 1.1},
        "A2": {"1min": 0.1, "15min": 0.9, "30min": 1.0},
    }
    result = compute_target_trajectory_evidence(
        candidate="K1",
        target_key="T",
        timeseries=timeseries,
        conditions=CONDITIONS,
        eligible_keys=["T", "A1", "A2"],
    )
    by_id = {row["interval_id"]: row for row in result["metrics"]["interval_direction_support"]}
    assert by_id["1min->5min"]["comparison"] == "not_evaluable"
    assert by_id["5min->15min"]["comparison"] == "not_evaluable"
    assert "1min->15min" not in by_id
    assert all(row["from"] + "->" + row["to"] == row["interval_id"] for row in scheduled_intervals(CONDITIONS))


def test_uneven_minutes_and_unknown_time_are_explicit():
    conditions = ["1min", "mystery", "1hr"]
    intervals = scheduled_intervals(conditions)
    assert intervals[0]["status"] == "not_evaluable"
    assert intervals[0]["reason"] == "unknown_elapsed_time"
    assert intervals[1]["status"] == "not_evaluable"


def test_flat_and_two_interval_correlation_are_not_strong_support():
    timeseries = {
        "T": _series([0.0, 0.0, 0.0, 0.0]),
        "A1": _series([1.0, 2.0, 3.0, 4.0]),
        "A2": _series([1.1, 2.1, 3.1, 4.1]),
    }
    result = compute_target_trajectory_evidence(
        candidate="K1",
        target_key="T",
        timeseries=timeseries,
        conditions=CONDITIONS,
        eligible_keys=["T", "A1", "A2"],
    )
    fraction = result["metrics"]["direction_concordance_fraction"]
    assert fraction["value"] is None
    assert fraction["both_flat"] or fraction["one_flat"]
    two_point = compute_target_trajectory_evidence(
        candidate="K1",
        target_key="T",
        timeseries={"T": {"1min": 0.0, "5min": 1.0}, "A1": {"1min": 0.0, "5min": 1.0}},
        conditions=["1min", "5min"],
        eligible_keys=["T", "A1"],
    )
    assert two_point["metrics"]["interval_rate_correlation"]["status"] == "not_evaluable"


def test_charge_group_exclusion_leaves_no_anchor():
    identities = {
        "T": {"modified_sequence": "PEPTIDE", "protein_group": "P1"},
        "T2": {"modified_sequence": "PEPTIDE", "protein_group": "P1"},
    }
    result = compute_kinase_trajectory_evidence(
        candidate="K1",
        target_keys=["T", "T2"],
        timeseries={"T": _series([0, 1, 2, 3]), "T2": _series([0, 1, 2, 3])},
        conditions=CONDITIONS,
        identities=identities,
    )
    assert result["support_status"] == "not_evaluable"
    assert result["targets"][0]["metrics"]["interval_direction_support"][0]["anchor_reason"] == "no_eligible_anchor_after_group_exclusion"


def test_unclear_group_is_not_pooled():
    identities = {"T": {}, "A1": {}}
    result = compute_target_trajectory_evidence(
        candidate="K1",
        target_key="T",
        timeseries={"T": _series([0, 1, 2, 3]), "A1": _series([0, 1, 2, 3])},
        conditions=CONDITIONS,
        eligible_keys=["T", "A1"],
        identities=identities,
    )
    assert result["measurement_group"] == "ungrouped:T"
    assert result["metrics"]["direction_concordance_fraction"]["value"] == 1.0


def test_loto_does_not_bridge_omitted_time():
    timeseries = {
        "T": _series([0.0, 1.0, 2.0, 3.0]),
        "A1": _series([0.0, 1.1, 2.1, 3.1]),
        "A2": _series([0.2, 1.2, 2.2, 3.2]),
    }
    result = compute_target_trajectory_evidence(
        candidate="K1",
        target_key="T",
        timeseries=timeseries,
        conditions=CONDITIONS,
        eligible_keys=["T", "A1", "A2"],
    )
    omitted = next(row for row in result["metrics"]["timepoint_omission_robustness"] if row["omitted_condition"] == "5min")
    assert omitted["bridged"] is False
    assert omitted["remaining_scheduled_intervals"] == 1


def test_denovo_targets_are_excluded():
    result = compute_kinase_trajectory_evidence(
        candidate="K1",
        target_keys=["T", "A1"],
        timeseries={"T": _series([0, 1, 2, 3]), "A1": _series([0, 1, 2, 3])},
        conditions=CONDITIONS,
        denovo_keys={"T": True, "A1": False},
    )
    assert result["n_targets_eligible"] == 1
    assert result["contract_version"] == CONTRACT_VERSION
