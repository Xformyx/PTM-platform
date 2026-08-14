from ptm_shared.multisite_divergence import TemporalDivergencePair, _gate, compute_divergence_pairs


def test_canonical_pair_uses_observation_first_pattern_and_tmm_divergence():
    matrix = {
        "MAPK1 T185": {"0m": 0.0, "5m": 2.4, "15m": 0.4, "30m": 0.0},
        "MAPK1 Y187": {"0m": 0.0, "5m": 0.1, "15m": -0.3, "30m": -2.2},
    }
    pairs, _ = compute_divergence_pairs(
        matrix,
        ["0m", "5m", "15m", "30m"],
        {"MAPK1 T185": "regulated", "MAPK1 Y187": "regulated"},
        set(),
        tmm_site_contributions={
            "MAPK1 T185": {"MAPK1": 0.9, "MAPK3": 0.1},
            "MAPK1 Y187": {"MAPK1": 0.1, "MAPK3": 0.9},
        },
    )

    assert len(pairs) == 1
    pair = pairs[0]
    assert pair.pattern == "temporally_separated_opposite_direction"
    assert pair.legacy_pattern == "signal_attenuation"
    assert pair.tmm_contribution_divergence["classification"] == "divergent_kinase_mixture"
    assert "No causal intervention was evaluated." in pair.to_ai_sentence()


def test_receptor_gate_requires_reproducible_directionality_and_context():
    pair = TemporalDivergencePair(
        protein="MAPK1",
        siteA="MAPK1 T185",
        siteB="MAPK1 Y187",
        pattern="same_peak_coordination",
        peak_condA="5m",
        peak_condB="5m",
        temporal_lag=0,
        fcA=2.0,
        fcB=1.8,
        fc_ratio=0.9,
        is_denovoA=False,
        is_denovoB=False,
        confidence_tier="High",
        fdr_q_value=0.01,
        directionality_tier="D1_temporal_precedence",
        shared_pathways=["MAPK signaling"],
    )
    ai_eligible, receptor_eligible, _ = _gate(pair)
    assert ai_eligible is True
    assert receptor_eligible is False

    pair.directionality_tier = "D2_reproducible_directionality"
    _, receptor_eligible, _ = _gate(pair)
    assert receptor_eligible is True
