import numpy as np
from ptm_shared.temporal_wave_engine import analyze_temporal_waves
from ptm_shared.enrichment_free_temporal_sidecar import _paired_wave_replicates
from ptm_shared.pathway_membership_index import build_pathway_result
from ptm_shared.analysis_validation_registry import compare_engine_bindings


def test_missing_replicates_are_not_zero_stability_and_real_paired_rows_are_used():
    conditions=['1min','5min','15min','30min']
    series={f'F{i}':dict(zip(conditions,[0,2,1,0])) for i in range(3)}
    config={'minimum_cluster_size':2,'bootstrap_repeats':20}
    absent=analyze_temporal_waves(series,conditions,config=config)
    assert absent['consensus_membership']['status']=='not_evaluable'
    assert absent['waves'][0]['evidence_profile']['replicate_stability'] is None
    raw={k:{'matrix':[[0,2,1,0],[0,2.1,1.1,0]],'timepoints':[1.,5.,15.,30.],
             'biological_units':['b1','b2'],'estimator_id':'paired_biological_sample_ratio_contrast.v1'} for k in series}
    replicate=_paired_wave_replicates(raw,conditions)
    present=analyze_temporal_waves(series,conditions,config=config,replicate_time_series=replicate,paired_biological_units=True)
    assert present['consensus_membership']['usable_replicate_site_count']==3
    assert present['waves'][0]['evidence_profile']['replicate_stability']==1
    assert present['waves'][0]['members']==absent['waves'][0]['members']
    assert _paired_wave_replicates({'F':{'matrix':[[1,2,3,4]]}},conditions)=={}


def test_pathway_membership_keeps_precursors_taxa_ambiguity_and_background():
    identities={'a':{'protein_group':'P1','fasta_taxonomy_id':'10090'},
                'b':{'protein_group':'P1','fasta_taxonomy_id':'10090'},
                'c':{'protein_group':'P1','fasta_taxonomy_id':'9606'},
                'd':{'protein_group':'P1;P2','fasta_taxonomy_id':'10090'},
                'e':{'protein_group':'P2','fasta_taxonomy_id':'10090'}}
    inp={'features':identities,'ptm_timeseries':{k:{'1min':v} for k,v in zip(identities,[2,-2,8,10,4])}}
    paths=[{'pathway_key':'P','protein_accessions':['P1'],'taxon':'10090'}]
    result=build_pathway_result({'conditions':['1min']},inp,paths,{'sha256':'fixture','status':'available'})
    assert {r['feature_id'] for r in result['memberships']}=={'a','b','d'}
    score=result['pathways'][0]['scores'][0]
    assert score['value']==0 and score['hit_proteins']==1 and score['background_proteins']==2
    assert score['evaluated_features']==2
    assert result['pathways'][0]['ambiguous_feature_count']==1
    assert result['unmapped_feature_ids']==['c','e']


def test_historical_benchmark_is_not_production_parity_without_complete_bindings():
    result=compare_engine_bindings({'analysis_scope':'full_eligible'},{'analysis_scope':'legacy_explicit_subset'})
    assert result['status']=='historical_comparator'
    assert 'analysis_scope' in result['different_fields'] and 'engine_signature' in result['missing_fields']


def test_parity_includes_biological_design_time_grid_track_and_discovery_mode():
    binding={'measurement_revision':'m','feature_identity_version':'precursor_identity.v2',
        'analysis_scope':'full_eligible','candidate_graph_hash':'c','reference_snapshots':{'db':'r'},
        'effective_config':{'target_transform':'signed'},'engine_signature':'e',
        'sample_manifest_hash':'paired-three-units','condition_grid':['1min','5min'],
        'primary_track':'protein_adjusted_relative_ptm_log2_contrast','inference_mode':'discovery_blind'}
    assert compare_engine_bindings(binding,dict(binding))['status']=='equivalent'
    for field,value in [('sample_manifest_hash','unpaired-six-units'),('condition_grid',['1min','15min']),
                        ('primary_track','unadjusted'),('inference_mode','context_assisted')]:
        result=compare_engine_bindings(binding,{**binding,field:value})
        assert result['status']=='historical_comparator' and result['different_fields']==[field]
        legacy={k:v for k,v in binding.items() if k!=field}
        assert field in compare_engine_bindings(binding,legacy)['missing_fields']
