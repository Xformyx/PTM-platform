from ptm_shared.dual_track_evidence import build_dual_track_evidence, classify_dual_track_kinase


def _score(values, site="G_S1", tier="tmm_prior_assisted"):
    conditions = ["1min", "5min", "15min"]
    return {
        "weighted_up_sums": dict(zip(conditions, values)),
        "weighted_down_sums": {},
        "contribution_details": [{"ptm_key": site, "contribution_ratio": 1.0}],
        "tmm_evidence": {"confidence_tier": tier},
    }


def test_dual_track_classifies_concordance_with_prior_boundary():
    result = classify_dual_track_kinase(
        _score([0.1, 1.0, 0.4]),
        _score([0.2, 0.9, 0.3]),
        ["1min", "5min", "15min"],
        correlation_threshold=0.5,
        peak_index_tolerance=1,
    )
    assert result["classification"] == "dual_track_concordant"
    assert result["reportability"] == "dual_track_observed_prior_limited"


def test_dual_track_keeps_single_track_and_direction_discordance_distinct():
    relative_only = classify_dual_track_kinase(
        _score([0.1, 1.0, 0.4]), {}, ["1min", "5min", "15min"]
    )
    discordant = classify_dual_track_kinase(
        _score([0.1, 1.0, 0.4]),
        _score([-0.1, -1.0, -0.4]),
        ["1min", "5min", "15min"],
    )
    assert relative_only["classification"] == "relative_only"
    assert discordant["classification"] == "direction_discordant"


def test_dual_track_contract_returns_auditable_summary():
    contract = build_dual_track_evidence(
        {"K1": _score([0.1, 1.0, 0.4])},
        {"K1": _score([0.2, 0.9, 0.3])},
        ["1min", "5min", "15min"],
    )
    assert contract["summary"]["kinase_count"] == 1
    assert contract["summary"]["classification_counts"]["dual_track_concordant"] == 1
