"""Tests for P3: temporal_precedence_output.py"""
from __future__ import annotations
import pytest

import pytest
from ptm_shared.replicate_event_adapter import EventRecord, EventStatus
from ptm_shared.temporal_precedence_output import (
    CONTRACT_VERSION,
    TemporalObservationTier,
    TemporalPrecedenceObservation,
    _build_report_phrase,
    build_temporal_precedence_observation,
    build_temporal_precedence_output,
)
from ptm_shared.study_temporal_context import INSULIN_TEMPORAL_CONTEXT


def _record(key, status=EventStatus.resolved, onset=5.0, peak=15.0, exit_t=60.0) -> EventRecord:
    return EventRecord(
        site_key=key,
        event_status=status,
        onset_t50_min=onset,
        peak_t_min=peak,
        exit_t50_min=exit_t,
        replicate_bootstrap_stability=0.85,
    )


@pytest.fixture()
def minimal_wave_contract():
    return {
        "timepoints": ["1min", "5min", "15min"],
        "waves": [{"wave_id": "TW-01", "members": ["A_S1", "B_S1"], "member_details": []}],
    }


# ── Report phrase policy ──────────────────────────────────────────────────

def test_phrase_contains_observed_timing():
    rec = _record("S1")
    phrase = _build_report_phrase(rec)
    assert "observed response timing" in phrase

def test_phrase_no_causal_language_before_p4():
    rec = _record("S1")
    phrase = _build_report_phrase(rec, p4_passed=False)
    assert "causal" in phrase.lower()
    assert "not yet" in phrase.lower() or "requires" in phrase.lower()

def test_phrase_not_evaluable():
    rec = _record("S1", status=EventStatus.not_evaluable_replicate_posterior)
    phrase = _build_report_phrase(rec)
    assert "not evaluable" in phrase.lower() or "not_evaluable" in phrase

def test_phrase_unresolved():
    rec = _record("S1", status=EventStatus.unresolved, onset=None, peak=1.0, exit_t=None)
    rec2 = EventRecord(
        site_key="S1",
        event_status=EventStatus.unresolved,
        peak_t_min=1.0,
    )
    phrase = _build_report_phrase(rec2)
    assert "no significant" in phrase.lower()

def test_phrase_left_censored():
    rec = EventRecord(
        site_key="S1",
        event_status=EventStatus.left_censored,
        onset_t50_min=None,
        peak_t_min=2.0,
    )
    phrase = _build_report_phrase(rec)
    assert "left-censored" in phrase or "before first" in phrase

def test_phrase_right_censored():
    rec = EventRecord(
        site_key="S1",
        event_status=EventStatus.right_censored,
        onset_t50_min=5.0,
        peak_t_min=30.0,
        exit_t50_min=None,
    )
    phrase = _build_report_phrase(rec)
    assert "right-censored" in phrase or "not resolved" in phrase


# ── build_temporal_precedence_observation ────────────────────────────────

def test_observation_tier_mapping():
    for status, expected_tier in [
        (EventStatus.resolved, TemporalObservationTier.resolved_within_grid),
        (EventStatus.left_censored, TemporalObservationTier.left_censored),
        (EventStatus.right_censored, TemporalObservationTier.right_censored),
        (EventStatus.ambiguous, TemporalObservationTier.ambiguous),
        (EventStatus.unresolved, TemporalObservationTier.not_evaluable),
        (EventStatus.not_evaluable_replicate_posterior, TemporalObservationTier.not_evaluable),
    ]:
        rec = EventRecord(site_key="S", event_status=status)
        obs = build_temporal_precedence_observation(rec, p4_passed=False)
        assert obs.tier == expected_tier, f"{status} → expected {expected_tier}, got {obs.tier}"

def test_observation_p4_flag():
    rec = _record("S1")
    obs_no_p4 = build_temporal_precedence_observation(rec, p4_passed=False)
    obs_p4 = build_temporal_precedence_observation(rec, p4_passed=True)
    assert obs_no_p4.p4_gate_passed is False
    assert obs_p4.p4_gate_passed is True


# ── build_temporal_precedence_output ─────────────────────────────────────

def test_build_output_structure(minimal_wave_contract):
    records = {"A_S1": _record("A_S1"), "B_S1": _record("B_S1", status=EventStatus.unresolved)}
    output = build_temporal_precedence_output(records, minimal_wave_contract,
                                               INSULIN_TEMPORAL_CONTEXT)
    assert "observations" in output
    assert "summary" in output
    assert "p4_gate" in output
    assert output["contract_version"] == CONTRACT_VERSION

def test_build_output_requires_explicit_context(minimal_wave_contract):
    """build_temporal_precedence_output requires explicit study_context (no default)."""
    records = {"A_S1": _record("A_S1")}
    with pytest.raises(TypeError):
        build_temporal_precedence_output(records, minimal_wave_contract)  # type: ignore[call-arg]

def test_build_output_mutation_guarantee(minimal_wave_contract):
    original_members = list(minimal_wave_contract["waves"][0]["members"])
    records = {"A_S1": _record("A_S1"), "B_S1": _record("B_S1")}
    build_temporal_precedence_output(records, minimal_wave_contract, INSULIN_TEMPORAL_CONTEXT)
    assert list(minimal_wave_contract["waves"][0]["members"]) == original_members

def test_build_output_mutation_guarantee_text(minimal_wave_contract):
    records = {"A_S1": _record("A_S1")}
    output = build_temporal_precedence_output(records, minimal_wave_contract,
                                               INSULIN_TEMPORAL_CONTEXT)
    assert "not modified" in output["mutation_guarantee"]

def test_build_output_counts(minimal_wave_contract):
    records = {
        "A_S1": _record("A_S1"),
        "B_S1": _record("B_S1", status=EventStatus.unresolved,
                        onset=None, peak=None, exit_t=None),
    }
    output = build_temporal_precedence_output(records, minimal_wave_contract,
                                               INSULIN_TEMPORAL_CONTEXT)
    assert output["summary"]["n_sites"] == 2
    assert output["summary"]["n_evaluable"] == 1

def test_p4_gate_not_passed_by_default(minimal_wave_contract):
    records = {"A_S1": _record("A_S1")}
    output = build_temporal_precedence_output(records, minimal_wave_contract,
                                               INSULIN_TEMPORAL_CONTEXT)
    assert output["p4_gate"]["passed"] is False
    assert "Trametinib" in output["p4_gate"]["note"] or "P4" in output["p4_gate"]["note"]

def test_wave_id_assigned_in_observations(minimal_wave_contract):
    records = {"A_S1": _record("A_S1")}
    output = build_temporal_precedence_output(records, minimal_wave_contract,
                                               INSULIN_TEMPORAL_CONTEXT)
    obs = next(o for o in output["observations"] if o["site_key"] == "A_S1")
    assert obs["wave_id"] == "TW-01"
