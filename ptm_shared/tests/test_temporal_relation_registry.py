"""Tests for P2: temporal_relation_registry.py"""
from __future__ import annotations
import pytest

from ptm_shared.replicate_event_adapter import EventRecord, EventStatus
from ptm_shared.temporal_relation_registry import (
    CONTRACT_VERSION,
    EvidenceTier,
    KnownRelationRegistry,
    RelationSpec,
    directed_precedence_concordance,
    within_wave_synchrony_test,
)
from ptm_shared.study_temporal_context import INSULIN_TEMPORAL_CONTEXT


# ── Fixtures ───────────────────────────────────────────────────────────────

def _make_record(key, onset=None, peak=5.0, exit_t=None,
                 status=EventStatus.resolved) -> EventRecord:
    return EventRecord(
        site_key=key,
        event_status=status,
        onset_t50_min=onset,
        peak_t_min=peak,
        exit_t50_min=exit_t,
        replicate_bootstrap_stability=0.85,
    )

@pytest.fixture()
def insulin_registry():
    return KnownRelationRegistry.stub_insulin_registry()

@pytest.fixture()
def simple_wave_contract():
    return {
        "timepoints": ["1min", "5min", "15min"],
        "waves": [{
            "wave_id": "TW-01",
            "members": ["A_S1", "B_S1"],
            "member_details": [],
        }],
    }

@pytest.fixture()
def event_records_with_onsets():
    return {
        "A_S1": _make_record("A_S1", onset=3.0, peak=10.0),
        "B_S1": _make_record("B_S1", onset=4.0, peak=12.0),
        "C_S2": _make_record("C_S2", onset=30.0, peak=45.0),
    }


# ── RelationSpec ──────────────────────────────────────────────────────────

def test_relation_spec_valid():
    rel = RelationSpec(
        source_site="A_S1", target_site="B_S1",
        allowed_lag_min=0.0, allowed_lag_max=10.0,
        expected_direction="source_before_target",
        evidence_tier=EvidenceTier.known_literature,
        evidence_note="test", study_id="test",
    )
    assert rel.allowed_lag_min < rel.allowed_lag_max

def test_relation_spec_invalid_lag():
    with pytest.raises(ValueError):
        RelationSpec(
            source_site="A", target_site="B",
            allowed_lag_min=10.0, allowed_lag_max=5.0,
            expected_direction="source_before_target",
            evidence_tier=EvidenceTier.known_literature,
            evidence_note="", study_id="test",
        )

def test_relation_spec_invalid_direction():
    with pytest.raises(ValueError):
        RelationSpec(
            source_site="A", target_site="B",
            allowed_lag_min=0.0, allowed_lag_max=5.0,
            expected_direction="invalid_direction",
            evidence_tier=EvidenceTier.known_literature,
            evidence_note="", study_id="test",
        )


# ── KnownRelationRegistry ─────────────────────────────────────────────────

def test_stub_insulin_registry_has_3_relations(insulin_registry):
    assert len(insulin_registry.relations) == 3

def test_stub_insulin_registry_study_id(insulin_registry):
    assert insulin_registry.study_id == "insulin_signaling_rat_phosphoproteomics"

def test_coverage_report_no_sites(insulin_registry):
    report = insulin_registry.coverage_report({})
    assert report["n_covered"] == 0
    assert report["n_eligible"] == 0


# ── Within-Wave event synchrony (Test A) ─────────────────────────────────

def test_synchrony_test_status(simple_wave_contract, event_records_with_onsets):
    result = within_wave_synchrony_test(
        simple_wave_contract,
        event_records_with_onsets,
        study_context=INSULIN_TEMPORAL_CONTEXT,
        permutation_n=50,
        seed=42,
    )
    assert result["status"] in ("computed", "skipped_no_evaluable_onset_pairs")

def test_synchrony_test_claim_limit_present(simple_wave_contract, event_records_with_onsets):
    result = within_wave_synchrony_test(
        simple_wave_contract,
        event_records_with_onsets,
        study_context=INSULIN_TEMPORAL_CONTEXT,
        permutation_n=20,
    )
    if result["status"] == "computed":
        assert "claim_limit" in result
        assert "kinase" not in result["claim_limit"].lower() or "attribution" in result["claim_limit"].lower()

def test_synchrony_test_does_not_mutate_contract(simple_wave_contract, event_records_with_onsets):
    original_members = list(simple_wave_contract["waves"][0]["members"])
    within_wave_synchrony_test(
        simple_wave_contract, event_records_with_onsets, permutation_n=10
    )
    assert list(simple_wave_contract["waves"][0]["members"]) == original_members

def test_synchrony_test_tau_from_context(simple_wave_contract, event_records_with_onsets):
    result = within_wave_synchrony_test(
        simple_wave_contract, event_records_with_onsets,
        study_context=INSULIN_TEMPORAL_CONTEXT,
        permutation_n=10,
    )
    assert result["tau_minutes"] == INSULIN_TEMPORAL_CONTEXT.synchrony_tau_minutes

def test_synchrony_high_for_close_onsets():
    contract = {
        "timepoints": ["1min", "5min", "15min"],
        "waves": [{"wave_id": "W1", "members": ["A", "B", "C"], "member_details": []}],
    }
    recs = {
        "A": _make_record("A", onset=3.0),
        "B": _make_record("B", onset=3.5),
        "C": _make_record("C", onset=4.0),
    }
    result = within_wave_synchrony_test(contract, recs,
                                        study_context=INSULIN_TEMPORAL_CONTEXT,
                                        permutation_n=50, seed=0)
    if result["status"] == "computed":
        # All onsets within 1 min → all within τ=5 min → synchrony=1.0
        assert result["synchrony_fraction_observed"] == 1.0


# ── Directed precedence concordance (Test B) ─────────────────────────────

def test_concordance_with_evaluable_sites(insulin_registry):
    records = {
        "INSR_Y1158": _make_record("INSR_Y1158", onset=1.0, peak=3.0),
        "IRS1_S302": _make_record("IRS1_S302", onset=3.0, peak=6.0),
        "AKT1_T308": _make_record("AKT1_T308", onset=5.0, peak=10.0),
        "GSK3B_S9": _make_record("GSK3B_S9", onset=8.0, peak=14.0),
    }
    result = directed_precedence_concordance(insulin_registry, records)
    assert result["status"] == "computed"
    assert result["n_relations_total"] == 3
    assert result["n_evaluable"] == 3

def test_concordance_claim_limit_present(insulin_registry):
    records = {
        "INSR_Y1158": _make_record("INSR_Y1158", peak=3.0),
        "IRS1_S302": _make_record("IRS1_S302", peak=6.0),
        "AKT1_T308": _make_record("AKT1_T308", peak=10.0),
        "GSK3B_S9": _make_record("GSK3B_S9", peak=14.0),
    }
    result = directed_precedence_concordance(insulin_registry, records)
    assert "causal" not in result["claim_limit"].lower() or "not causal" in result["claim_limit"].lower()

def test_concordance_with_missing_sites(insulin_registry):
    result = directed_precedence_concordance(insulin_registry, {})
    assert result["n_evaluable"] == 0
    for row in result["per_relation"]:
        assert row["evaluable"] is False

def test_concordance_correct_order_gives_high_p(insulin_registry):
    """INSR → IRS1: INSR peaks at 3 min, IRS1 at 6 min, lag=3 min in [0,5]."""
    records = {
        "INSR_Y1158": _make_record("INSR_Y1158", peak=3.0, onset=1.0),
        "IRS1_S302": _make_record("IRS1_S302", peak=6.0, onset=4.0),
        "AKT1_T308": _make_record("AKT1_T308", peak=10.0),
        "GSK3B_S9": _make_record("GSK3B_S9", peak=14.0),
    }
    result = directed_precedence_concordance(insulin_registry, records, n_samples=500)
    row = next(r for r in result["per_relation"] if "INSR_Y1158" in r["relation"])
    assert row["evaluable"] is True
    assert row["posterior_order_probability"] > 0.5
