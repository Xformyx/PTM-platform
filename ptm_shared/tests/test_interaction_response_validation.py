"""Tests for P4/P5: interaction_response_validation.py"""
from __future__ import annotations
import pytest
import numpy as np

from ptm_shared.interaction_response_validation import (
    CONTRACT_VERSION,
    InteractionContrastInput,
    InteractionContrastResult,
    P4Status,
    P4ValidationResult,
    P5Status,
    P5HoldoutResult,
    check_event_order_enrichment,
    compute_delta_mek,
    run_p4_trametinib_validation,
    run_p5_mirdametinib_holdout,
    validation_status_report,
)


# ── Fixtures ───────────────────────────────────────────────────────────────

def _dummy_data(n_sites=5, n_tp=3, n_rep=3,
                drug="Trametinib", cohort="primary") -> InteractionContrastInput:
    rng = np.random.default_rng(0)
    shape = (n_sites, n_tp, n_rep)
    return InteractionContrastInput(
        insulin_only=rng.normal(0.5, 0.1, shape),
        mek_inhibitor=rng.normal(0.2, 0.1, shape),
        insulin_plus_mek=rng.normal(0.8, 0.1, shape),
        vehicle=rng.normal(0.0, 0.05, shape),
        site_keys=[f"SITE_{i}" for i in range(n_sites)],
        timepoint_labels=["1min", "5min", "15min"],
        drug_name=drug,
        cohort=cohort,
    )


# ── compute_delta_mek ─────────────────────────────────────────────────────

def test_delta_mek_shape():
    data = _dummy_data(n_sites=4, n_tp=3, n_rep=3)
    result = compute_delta_mek(data)
    assert result.delta_mek.shape == (4, 3)
    assert result.delta_mek_std.shape == (4, 3)

def test_delta_mek_formula():
    """ΔMEK = [IM - M] - [I - V]. Verify with known values."""
    n = (3, 2, 2)  # sites, tp, rep
    data = InteractionContrastInput(
        insulin_only=np.ones(n) * 1.0,
        mek_inhibitor=np.ones(n) * 0.5,
        insulin_plus_mek=np.ones(n) * 1.5,
        vehicle=np.zeros(n),
        site_keys=[f"S{i}" for i in range(3)],
        timepoint_labels=["1min", "5min"],
    )
    result = compute_delta_mek(data)
    # ΔMEK = (1.5-0.5) - (1.0-0.0) = 1.0 - 1.0 = 0.0
    assert result.delta_mek == pytest.approx(np.zeros((3, 2)))

def test_delta_mek_raises_on_empty():
    empty_data = InteractionContrastInput(
        insulin_only=np.array([]).reshape(0, 0, 0),
        mek_inhibitor=np.array([]).reshape(0, 0, 0),
        insulin_plus_mek=np.array([]).reshape(0, 0, 0),
        vehicle=np.array([]).reshape(0, 0, 0),
        site_keys=[], timepoint_labels=[],
    )
    with pytest.raises(ValueError, match="PENDING_DATA"):
        compute_delta_mek(empty_data)


# ── check_event_order_enrichment ──────────────────────────────────────────

def test_enrichment_perfect():
    data = _dummy_data(n_sites=5)
    result = compute_delta_mek(data)
    # Force large ΔMEK for top sites
    result.delta_mek[:, :] = 2.0
    ranks = {f"SITE_{i}": float(i) for i in range(5)}
    enrichment = check_event_order_enrichment(result, ranks, top_n=5, enrichment_threshold_fc=0.5)
    assert enrichment["enrichment_score"] == 1.0

def test_enrichment_none_responsive():
    data = _dummy_data(n_sites=5)
    result = compute_delta_mek(data)
    result.delta_mek[:, :] = 0.0
    ranks = {f"SITE_{i}": float(i) for i in range(5)}
    enrichment = check_event_order_enrichment(result, ranks, top_n=5, enrichment_threshold_fc=0.5)
    assert enrichment["enrichment_score"] == 0.0


# ── run_p4_trametinib_validation ──────────────────────────────────────────

def test_p4_returns_pending_when_no_data():
    result = run_p4_trametinib_validation(None, {})
    assert result.status == P4Status.pending_data
    assert "Trametinib" in result.note

def test_p4_with_data_returns_contrast_computed():
    data = _dummy_data()
    ranks = {f"SITE_{i}": float(i) for i in range(5)}
    result = run_p4_trametinib_validation(data, ranks)
    assert result.status == P4Status.contrast_computed
    assert result.enrichment_score is not None
    assert 0.0 <= result.enrichment_score <= 1.0

def test_p4_does_not_auto_pass():
    data = _dummy_data()
    ranks = {f"SITE_{i}": float(i) for i in range(5)}
    result = run_p4_trametinib_validation(data, ranks)
    assert result.status != P4Status.validation_passed


# ── run_p5_mirdametinib_holdout ───────────────────────────────────────────

def test_p5_pending_when_p4_not_complete():
    p4 = P4ValidationResult(status=P4Status.pending_data)
    result = run_p5_mirdametinib_holdout(None, p4, {})
    assert result.status == P5Status.pending_p4

def test_p5_pending_when_data_missing():
    p4 = P4ValidationResult(status=P4Status.contrast_computed)
    result = run_p5_mirdametinib_holdout(None, p4, {})
    assert result.status == P5Status.pending_data

def test_p5_with_data():
    p4 = P4ValidationResult(status=P4Status.contrast_computed)
    data = _dummy_data(drug="mirdametinib", cohort="holdout_Q2")
    ranks = {f"SITE_{i}": float(i) for i in range(5)}
    result = run_p5_mirdametinib_holdout(data, p4, ranks)
    assert result.status == P5Status.holdout_computed
    assert result.q2_direction_concordance is not None
    assert "compound-specific" in result.compound_specific_note.lower()


# ── validation_status_report ──────────────────────────────────────────────

def test_status_report_causal_not_unlocked_by_default():
    p4 = P4ValidationResult(status=P4Status.pending_data)
    p5 = P5HoldoutResult(status=P5Status.pending_p4)
    report = validation_status_report(p4, p5)
    assert report["causal_language_unlocked"] is False
    assert "not yet validated" in report["recommendation"].lower()

def test_status_report_unlocked_on_validation_passed():
    p4 = P4ValidationResult(status=P4Status.validation_passed)
    p5 = P5HoldoutResult(status=P5Status.holdout_computed)
    report = validation_status_report(p4, p5)
    assert report["causal_language_unlocked"] is True
