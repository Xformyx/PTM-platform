"""Tests for ptm_shared/inhibitor_prediction_features.py (M1-M3).

Verifies feature extraction correctness, groupkfold boundary, model tier
escalation, and data-leakage prevention invariants.
"""
import pytest

from ptm_shared.inhibitor_prediction_features import (
    CONTRACT_VERSION,
    GROUPKFOLD_COLUMN,
    build_feature_matrix,
    extract_m1_features,
    extract_m2_features,
    extract_m3_features,
)


# ── Shared fixtures ────────────────────────────────────────────────────────

_LABELS = ["1min", "5min", "15min", "30min", "60min"]


def _wave_contract_two_waves() -> dict:
    w1_members = {
        "AKT1_S473": [0.0, 1.5, 1.8, 0.8, 0.2],
        "AKT2_S474": [0.0, 1.2, 1.6, 0.6, 0.1],
    }
    w2_members = {
        "PTEN_S380": [0.0, -0.1, 0.0, 1.2, 1.5],
        "GSK3_S9":   [0.0, -0.2, 0.1, 1.0, 1.4],
    }
    waves = []
    for wid, members in [("TW-01", w1_members), ("TW-02", w2_members)]:
        waves.append({
            "wave_id": wid,
            "members": list(members.keys()),
            "member_details": [
                {"key": k, "temporal_values": dict(zip(_LABELS, v))}
                for k, v in members.items()
            ],
        })
    return {"timepoints": _LABELS, "waves": waves}


def _minimal_cowave_result() -> dict:
    """Minimal stub of a dynamic_cowave_result for M3 tests."""
    return {
        "transition_examples": {
            "site_transitions": [
                {
                    "site_key": "AKT1_S473",
                    "transition_type": "group_persistence",
                    "partner_count_before": 1,
                    "partner_count_after": 1,
                    "from_window": "1min",
                    "to_window": "5min",
                },
                {
                    "site_key": "AKT1_S473",
                    "transition_type": "split_from_group",
                    "partner_count_before": 1,
                    "partner_count_after": 0,
                    "from_window": "30min",
                    "to_window": "60min",
                },
            ],
        },
        "lotto": {
            "mean_pair_transition_jaccard": 0.72,
        },
        "per_wave_summary": [
            {"wave_id": "TW-01", "pair_transition_count": 2},
        ],
    }


# ── M1 features ────────────────────────────────────────────────────────────

def test_m1_basic_fields_present() -> None:
    fcs = [0.0, 1.5, 1.8, 0.8, 0.2]
    result = extract_m1_features("AKT1_S473", _LABELS, fcs, activity_threshold_fc=0.4)
    expected_keys = {
        "site_key", "model_tier", "n_timepoints", "n_observed",
        "peak_abs_fc", "peak_fc", "peak_timepoint_min",
        "onset_timepoint_min", "exit_timepoint_min", "active_span_min",
        "trajectory_auc", "recovery_fraction", "direction", "fraction_active_tps",
    }
    assert expected_keys <= set(result.keys())
    assert result["model_tier"] == "M1"
    assert result["n_timepoints"] == 5
    assert result["n_observed"] == 5


def test_m1_peak_detection() -> None:
    fcs = [0.0, 1.5, 1.8, 0.8, 0.2]
    result = extract_m1_features("GENE_S1", _LABELS, fcs, activity_threshold_fc=0.4)
    assert result["peak_abs_fc"] == pytest.approx(1.8, abs=1e-4)
    assert result["peak_fc"] > 0
    assert result["direction"] == 1


def test_m1_downregulation() -> None:
    fcs = [0.0, -1.5, -2.0, -1.0, -0.2]
    result = extract_m1_features("GENE_S1", _LABELS, fcs, activity_threshold_fc=0.4)
    assert result["direction"] == -1
    assert result["peak_fc"] < 0


def test_m1_all_none_returns_nulls() -> None:
    result = extract_m1_features("GENE_S1", _LABELS, [None] * 5)
    assert result["peak_abs_fc"] is None
    # All values None — function returns early with null row; n_observed is None
    assert result["n_observed"] is None
    assert result["model_tier"] == "M1"


def test_m1_onset_exit_with_gap() -> None:
    # Active at 5min and 60min but not in between
    fcs = [0.0, 1.5, 0.1, 0.1, 1.8]
    result = extract_m1_features("GENE_S1", _LABELS, fcs, activity_threshold_fc=0.4)
    # onset should be 5min (first active), exit should be 60min (last active)
    assert result["onset_timepoint_min"] == pytest.approx(5.0, abs=0.1)
    assert result["exit_timepoint_min"] == pytest.approx(60.0, abs=0.1)


def test_m1_recovery_fraction() -> None:
    # Starts high, ends at half peak
    fcs = [2.0, 2.0, 2.0, 1.0, 1.0]
    result = extract_m1_features("GENE_S1", _LABELS, fcs, activity_threshold_fc=0.4)
    assert result["recovery_fraction"] == pytest.approx(1.0 / 2.0, abs=0.01)


# ── M2 features ────────────────────────────────────────────────────────────

def test_m2_adds_protein_id_and_wave_fields() -> None:
    contract = _wave_contract_two_waves()
    fcs = [0.0, 1.5, 1.8, 0.8, 0.2]
    m1 = extract_m1_features("AKT1_S473", _LABELS, fcs)
    m2 = extract_m2_features(m1, contract)
    assert m2["model_tier"] == "M2"
    assert m2["protein_id"] == "AKT1"
    assert m2["static_wave_id"] == "TW-01"
    assert m2["wave_member_count"] == 2


def test_m2_groupkfold_column_is_protein_id() -> None:
    assert GROUPKFOLD_COLUMN == "protein_id"


def test_m2_wave_zscore_present_for_multi_member_wave() -> None:
    contract = _wave_contract_two_waves()
    fcs = [0.0, 1.5, 1.8, 0.8, 0.2]
    m1 = extract_m1_features("AKT1_S473", _LABELS, fcs)
    m2 = extract_m2_features(m1, contract)
    # Wave has 2 members, so zscore can be computed
    assert m2["wave_amplitude_zscore"] is not None


def test_m2_unknown_site_returns_null_wave_fields() -> None:
    contract = _wave_contract_two_waves()
    fcs = [0.0, 1.0, 1.2]
    m1 = extract_m1_features("UNKNOWN_S1", _LABELS[:3], fcs)
    m2 = extract_m2_features(m1, contract)
    assert m2["static_wave_id"] is None
    assert m2["wave_member_count"] is None


# ── M3 features ────────────────────────────────────────────────────────────

def test_m3_adds_dynamic_cowave_fields() -> None:
    contract = _wave_contract_two_waves()
    cowave = _minimal_cowave_result()
    fcs = [0.0, 1.5, 1.8, 0.8, 0.2]
    m1 = extract_m1_features("AKT1_S473", _LABELS, fcs)
    m2 = extract_m2_features(m1, contract)
    m3 = extract_m3_features(m2, cowave)
    assert m3["model_tier"] == "M3"
    assert m3["co_wave_site_windows"] == 2  # 2 transition records for AKT1_S473
    assert m3["group_persistence_fraction"] == pytest.approx(0.5, abs=0.01)
    assert m3["split_fraction"] == pytest.approx(0.5, abs=0.01)
    assert m3["dynamic_transition_entropy"] is not None
    assert m3["dynamic_transition_entropy"] >= 0.0


def test_m3_site_with_no_transitions() -> None:
    contract = _wave_contract_two_waves()
    cowave = _minimal_cowave_result()
    fcs = [0.0, 1.0, 1.3, 0.5, 0.1]
    m1 = extract_m1_features("GSK3_S9", _LABELS, fcs)
    m2 = extract_m2_features(m1, contract)
    m3 = extract_m3_features(m2, cowave)
    # GSK3_S9 not in cowave result — all dynamic fields should be None or 0
    assert m3["co_wave_site_windows"] == 0
    assert m3["group_persistence_fraction"] is None


# ── build_feature_matrix ────────────────────────────────────────────────────

def test_build_m1_matrix() -> None:
    contract = _wave_contract_two_waves()
    result = build_feature_matrix(contract, model_tier="M1")
    assert result["model_tier"] == "M1"
    assert result["n_sites"] == 4
    assert len(result["features"]) == 4
    assert result["contract_version"] == CONTRACT_VERSION


def test_build_m2_matrix() -> None:
    contract = _wave_contract_two_waves()
    result = build_feature_matrix(contract, model_tier="M2")
    assert result["model_tier"] == "M2"
    assert result["groupkfold_column"] == GROUPKFOLD_COLUMN
    for row in result["features"]:
        assert "protein_id" in row
        assert "static_wave_id" in row


def test_build_m3_matrix() -> None:
    contract = _wave_contract_two_waves()
    cowave = _minimal_cowave_result()
    result = build_feature_matrix(contract, dynamic_cowave_result=cowave, model_tier="M3")
    assert result["model_tier"] == "M3"
    assert result["n_sites"] == 4
    for row in result["features"]:
        assert "co_wave_site_windows" in row


def test_build_m3_raises_without_cowave_result() -> None:
    with pytest.raises(ValueError, match="dynamic_cowave_result"):
        build_feature_matrix(_wave_contract_two_waves(), model_tier="M3")


def test_build_invalid_tier_raises() -> None:
    with pytest.raises(ValueError, match="M4"):
        build_feature_matrix(_wave_contract_two_waves(), model_tier="M4")


def test_build_provenance_fields() -> None:
    contract = _wave_contract_two_waves()
    result = build_feature_matrix(contract, model_tier="M2")
    prov = result["provenance"]
    assert "hyperparameter_sha256" in prov
    assert "data_leakage_prevention" in prov
    assert "pre_registration_date" in prov


def test_build_empty_timepoints() -> None:
    result = build_feature_matrix({"timepoints": [], "waves": []}, model_tier="M1")
    assert result["n_sites"] == 0
    assert result["features"] == []


def test_feature_names_match_row_keys() -> None:
    contract = _wave_contract_two_waves()
    result = build_feature_matrix(contract, model_tier="M1")
    if result["features"]:
        row_keys = set(result["features"][0].keys()) - {"site_key", "model_tier"}
        feature_set = set(result["feature_names"])
        assert feature_set <= row_keys


# ── Data leakage prevention invariants ─────────────────────────────────────

def test_groupkfold_column_stable() -> None:
    """GROUPKFOLD_COLUMN must not change — pre-registered 2026-08-28."""
    assert GROUPKFOLD_COLUMN == "protein_id"


def test_feature_matrix_provenance_contains_groupkfold_boundary() -> None:
    contract = _wave_contract_two_waves()
    result = build_feature_matrix(contract, model_tier="M2")
    assert GROUPKFOLD_COLUMN in result["provenance"]["data_leakage_prevention"]
