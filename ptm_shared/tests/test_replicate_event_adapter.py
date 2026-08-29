"""Tests for P1: replicate_event_adapter.py"""
from __future__ import annotations
import math
import pytest
import numpy as np

from ptm_shared.replicate_event_adapter import (
    CONTRACT_VERSION,
    EventRecord,
    EventStatus,
    _event_times_from_trajectory,
    _find_crossing_time,
    _gp_parametric_uncertainty,
    build_event_records_for_wave_contract,
    extract_event_record,
    extract_event_record_from_replicates,
    not_evaluable_record,
)
from ptm_shared.study_temporal_context import INSULIN_TEMPORAL_CONTEXT


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture()
def insulin_labels():
    return ["1min", "5min", "15min", "30min", "60min", "180min"]

@pytest.fixture()
def resolved_fcs():
    """Clear onset+peak+exit within grid."""
    return [0.0, 1.8, 2.0, 1.5, 0.3, 0.0]

@pytest.fixture()
def right_censored_fcs():
    """Stays elevated through 180min."""
    return [0.0, 1.0, 1.8, 2.0, 2.1, 2.2]

@pytest.fixture()
def unresolved_fcs():
    """Never reaches threshold."""
    return [0.0, 0.1, 0.2, 0.1, 0.0, 0.0]

@pytest.fixture()
def wave_contract(insulin_labels):
    labels = insulin_labels
    return {
        "contract_version": "temporal_wave_contract.v1",
        "timepoints": labels,
        "threshold_provenance": {"config_sha256": "test"},
        "waves": [{
            "wave_id": "TW-01",
            "members": ["A_S1", "B_S1"],
            "member_details": [
                {"key": "A_S1", "temporal_values": dict(zip(labels, [0.0, 1.8, 2.0, 1.5, 0.3, 0.0]))},
                {"key": "B_S1", "temporal_values": dict(zip(labels, [0.0, 0.2, 0.1, 0.0, 0.0, 0.0]))},
            ],
        }],
    }


# ── _find_crossing_time ────────────────────────────────────────────────────

def test_find_crossing_up():
    t = np.array([0.0, 5.0, 15.0, 30.0])
    v = np.array([0.0, 0.1, 0.5, 0.9])
    result = _find_crossing_time(t, v, 0.2, direction="up")
    assert result is not None
    assert 5.0 < result < 15.0

def test_find_crossing_down():
    t = np.array([0.0, 5.0, 15.0, 30.0])
    v = np.array([1.0, 0.8, 0.3, 0.1])
    result = _find_crossing_time(t, v, 0.5, direction="down")
    assert result is not None
    assert 5.0 < result < 15.0

def test_find_crossing_not_found():
    t = np.array([0.0, 5.0, 15.0])
    v = np.array([0.0, 0.1, 0.2])
    assert _find_crossing_time(t, v, 1.0, direction="up") is None


# ── _event_times_from_trajectory ──────────────────────────────────────────

def test_event_times_resolved():
    t = np.array([1.0, 5.0, 15.0, 30.0, 60.0, 180.0])
    v = np.array([0.0, 1.8, 2.0, 1.5, 0.3, 0.0])
    result = _event_times_from_trajectory(t, v, 0.4)
    assert result["status"] == EventStatus.resolved
    assert result["onset_t"] is not None
    assert result["peak_t"] is not None
    assert result["exit_t"] is not None

def test_event_times_unresolved():
    t = np.array([1.0, 5.0, 15.0, 30.0, 60.0, 180.0])
    v = np.array([0.0, 0.1, 0.2, 0.1, 0.0, 0.0])
    result = _event_times_from_trajectory(t, v, 0.4)
    assert result["status"] == EventStatus.unresolved

def test_event_times_right_censored():
    t = np.array([1.0, 5.0, 15.0, 30.0, 60.0, 180.0])
    v = np.array([0.0, 0.5, 1.5, 2.0, 2.1, 2.2])
    result = _event_times_from_trajectory(t, v, 0.4)
    assert result["status"] == EventStatus.right_censored
    assert result["exit_t"] is None

def test_event_times_left_censored():
    t = np.array([1.0, 5.0, 15.0, 30.0, 60.0, 180.0])
    v = np.array([1.5, 2.0, 2.0, 1.0, 0.3, 0.0])
    result = _event_times_from_trajectory(t, v, 0.4)
    assert result["status"] == EventStatus.left_censored
    assert result["onset_t"] is None


# ── extract_event_record ──────────────────────────────────────────────────

def test_extract_resolved_record(insulin_labels, resolved_fcs):
    rec = extract_event_record(
        "TEST_S1", insulin_labels, resolved_fcs,
        study_context=INSULIN_TEMPORAL_CONTEXT,
    )
    assert rec.event_status == EventStatus.resolved
    assert rec.onset_t50_min is not None
    assert rec.peak_t_min is not None
    assert rec.peak_ci95_min is not None
    # condition-mean path: replicate_bootstrap_stability=None; exploratory_model_uncertainty set
    assert rec.replicate_bootstrap_stability is None
    assert rec.exploratory_model_uncertainty is not None
    assert 0.0 <= rec.exploratory_model_uncertainty <= 1.0

def test_extract_right_censored_record(insulin_labels, right_censored_fcs):
    rec = extract_event_record(
        "TEST_S2", insulin_labels, right_censored_fcs,
        study_context=INSULIN_TEMPORAL_CONTEXT,
    )
    assert rec.event_status == EventStatus.right_censored
    assert rec.exit_t50_min is None
    assert rec.censoring_note is not None

def test_extract_unresolved_record(insulin_labels, unresolved_fcs):
    rec = extract_event_record(
        "TEST_S3", insulin_labels, unresolved_fcs,
        study_context=INSULIN_TEMPORAL_CONTEXT,
    )
    assert rec.event_status == EventStatus.unresolved
    assert rec.onset_t50_min is None

def test_extract_record_contract_version(insulin_labels, resolved_fcs):
    rec = extract_event_record("S1", insulin_labels, resolved_fcs,
                               study_context=INSULIN_TEMPORAL_CONTEXT)
    assert rec.contract_version == CONTRACT_VERSION

def test_extract_record_claim_limit_present(insulin_labels, resolved_fcs):
    rec = extract_event_record("S1", insulin_labels, resolved_fcs,
                               study_context=INSULIN_TEMPORAL_CONTEXT)
    assert "causality" in rec.claim_limit.lower() or "activation" in rec.claim_limit.lower()

def test_extract_record_with_missing_values(insulin_labels):
    # FC[0]=None → raw_first unknown → GP-posterior fallback for censoring.
    # GP may show left_censored due to smoothing; all statuses are valid.
    fcs = [None, 1.5, 2.0, 1.8, None, 0.2]
    rec = extract_event_record("S1", insulin_labels, fcs,
                               study_context=INSULIN_TEMPORAL_CONTEXT)
    assert rec.event_status in EventStatus.__members__.values()

def test_extract_record_never_modifies_input(insulin_labels, resolved_fcs):
    fcs_copy = list(resolved_fcs)
    labels_copy = list(insulin_labels)
    extract_event_record("S1", insulin_labels, resolved_fcs,
                         study_context=INSULIN_TEMPORAL_CONTEXT)
    assert list(resolved_fcs) == fcs_copy
    assert list(insulin_labels) == labels_copy

def test_extract_record_hours_grid():
    labels = ["0hr", "2hr", "8hr", "24hr", "48hr"]
    fcs = [0.0, 1.5, 2.0, 1.5, 0.3]
    from ptm_shared.study_temporal_context import HYPOXIA_TEMPORAL_CONTEXT_DRAFT
    rec = extract_event_record("HIF1A_S100", labels, fcs,
                               study_context=HYPOXIA_TEMPORAL_CONTEXT_DRAFT)
    assert rec.event_status in EventStatus.__members__.values()
    if rec.peak_t_min is not None:
        assert rec.peak_t_min >= 0  # in minutes (480.0 = 8hr)


# ── extract_event_record_from_replicates ──────────────────────────────────

def test_replicate_record_basic(insulin_labels):
    rep_matrix = np.array([
        [0.0, 1.6, 2.0, 1.5, 0.3, 0.0],
        [0.0, 1.9, 2.1, 1.6, 0.4, 0.1],
        [0.1, 1.7, 1.9, 1.4, 0.2, 0.0],
    ])
    rec = extract_event_record_from_replicates(
        "S1", insulin_labels, rep_matrix,
        study_context=INSULIN_TEMPORAL_CONTEXT,
        n_bootstrap=50,
    )
    assert rec.input_type == "replicate_level_bootstrap"
    assert rec.n_replicates_used == 3
    assert rec.replicate_bootstrap_stability is not None
    assert 0.0 <= rec.replicate_bootstrap_stability <= 1.0


# ── not_evaluable_record ──────────────────────────────────────────────────

def test_not_evaluable_record():
    rec = not_evaluable_record("S1", reason="no_replicates")
    assert rec.event_status == EventStatus.not_evaluable_replicate_posterior
    assert rec.input_type == "not_evaluable_replicate_posterior"
    assert "no_replicates" in rec.claim_limit


# ── build_event_records_for_wave_contract ─────────────────────────────────

def test_build_event_records_for_wave_contract(wave_contract):
    records = build_event_records_for_wave_contract(
        wave_contract, study_context=INSULIN_TEMPORAL_CONTEXT
    )
    assert "A_S1" in records
    assert "B_S1" in records
    assert isinstance(records["A_S1"], EventRecord)

def test_wave_contract_not_mutated(wave_contract):
    original_members = list(wave_contract["waves"][0]["members"])
    build_event_records_for_wave_contract(
        wave_contract, study_context=INSULIN_TEMPORAL_CONTEXT
    )
    assert list(wave_contract["waves"][0]["members"]) == original_members


# ── Fix-1: No silent insulin default ─────────────────────────────────────

def test_no_silent_insulin_default_raises_type_error(insulin_labels, resolved_fcs):
    """Calling without study_context should raise TypeError (required kwarg)."""
    with pytest.raises(TypeError):
        extract_event_record("S1", insulin_labels, resolved_fcs)

def test_replicate_no_silent_default_raises_type_error(insulin_labels):
    mat = np.array([[0.0, 1.8, 2.0, 1.5, 0.3, 0.0]])
    with pytest.raises(TypeError):
        extract_event_record_from_replicates("S1", insulin_labels, mat)

def test_build_contract_no_silent_default_raises_type_error(wave_contract):
    with pytest.raises(TypeError):
        build_event_records_for_wave_contract(wave_contract)


# ── Fix-3: replicate_bootstrap_stability vs exploratory_model_uncertainty ─

def test_condition_mean_sets_model_uncertainty(insulin_labels, resolved_fcs):
    rec = extract_event_record("S1", insulin_labels, resolved_fcs,
                               study_context=INSULIN_TEMPORAL_CONTEXT)
    assert rec.replicate_bootstrap_stability is None
    assert rec.exploratory_model_uncertainty is not None
    assert 0.0 <= rec.exploratory_model_uncertainty <= 1.0

def test_condition_mean_input_type(insulin_labels, resolved_fcs):
    rec = extract_event_record("S1", insulin_labels, resolved_fcs,
                               study_context=INSULIN_TEMPORAL_CONTEXT)
    assert rec.input_type == "condition_mean_gp_parametric_bootstrap"

def test_replicate_level_sets_stability_not_uncertainty(insulin_labels):
    mat = np.array([
        [0.0, 1.6, 2.0, 1.5, 0.3, 0.0],
        [0.0, 1.9, 2.1, 1.6, 0.4, 0.1],
    ])
    rec = extract_event_record_from_replicates(
        "S1", insulin_labels, mat,
        study_context=INSULIN_TEMPORAL_CONTEXT, n_bootstrap=20
    )
    assert rec.replicate_bootstrap_stability is not None
    assert rec.exploratory_model_uncertainty is None
    assert rec.input_type == "replicate_level_bootstrap"
