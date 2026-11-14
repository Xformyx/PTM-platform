from ptm_shared.atlas_context import build_atlas_context_evidence


def test_context_join_preserves_evidence_types_without_causal_upgrade():
    sites = [
        {"site_key": "AKT1_S473", "gene": "AKT1", "position": "S473"},
        {"site_key": "STAT3_Y705", "gene": "STAT3", "position": "Y705"},
    ]
    contexts = build_atlas_context_evidence(
        sites,
        kinase_activity_heatmap={
            "kinase_scores": [{
                "kinase": "AKT1",
                "peak_condition": "10min",
                "confidence": 0.8,
                "substrates": [{"gene": "STAT3", "site": "Y705", "cluster": "dominant"}],
                "self_ptm": [{"site": "S473", "relationship": "concordant", "correlation_with_activity": 0.9}],
            }],
        },
        substrate_go_localization={"gene_localizations": {"STAT3": ["nucleus", "cytoplasm"]}},
        signal_propagation_data={"nonptm_effectors": [{"gene": "STAT3", "protein_log2fc": 1.2, "role": "effector"}]},
    )
    assert contexts["AKT1_S473"]["self_ptm_candidates"][0]["evidence_type"] == "regulator_self_ptm_temporal_candidate"
    assert contexts["STAT3_Y705"]["kinase_context"][0]["evidence_type"] == "kinase_module_substrate_membership"
    assert contexts["STAT3_Y705"]["nuclear_context"]["nucleus_annotated"] is True
    assert contexts["STAT3_Y705"]["non_ptm_follow_through"][0]["evidence_type"] == "persisted_non_ptm_temporal_context"
    assert "do not establish" in contexts["STAT3_Y705"]["interpretation_boundary"]


def test_exact_feature_key_does_not_collapse_same_site_or_taxon():
    sites=[{'site_key':'G_S1|F1','feature_id':'F1','gene':'G','position':'S1'},
           {'site_key':'G_S1|F2','feature_id':'F2','gene':'G','position':'S1'}]
    heatmap={'kinase_scores':[{'kinase':'K','substrates':[{'gene':'G','position':'S1','feature_id':'F2'},{'gene':'G','position':'S1'}]}]}
    result=build_atlas_context_evidence(sites,kinase_activity_heatmap=heatmap)
    assert result['G_S1|F1']['kinase_context']==[]
    assert len(result['G_S1|F2']['kinase_context'])==1
