import pytest
from app.services.temporal_kinase_scoring import build_kinase_profiles_from_data
from app.services.production_temporal_analysis import score_tracks
from ptm_shared.temporal_wave_benchmark import _scores_from_rows


def test_duplicate_charge_features_do_not_satisfy_independent_profile_support():
    conditions=['1min','5min','15min']
    modules=[{'canonical':'K1','members':[{'key':k} for k in ['p2','p3','p4']]}]
    series={k:dict(zip(conditions,[1,2,1])) for k in ['p2','p3','p4']}
    membership={k:['K1'] for k in series}
    identities={k:{'protein_group':'P1','modified_sequence':'AS(UniMod:21)K','precursor_charge':k[1:], 'fasta_taxonomy_id':'10090'} for k in series}
    old=build_kinase_profiles_from_data(modules,series,membership,conditions)['K1']
    new=build_kinase_profiles_from_data(modules,series,membership,conditions,ptm_identities=identities,
        profile_support_unit='measurement_group.v1',profile_prior_policy='observed_support_only.v1')['K1']
    assert old['profile_type']=='data_driven'
    assert new['profile_type']=='insufficient_observed_profile' and new['n_independent_measurement_groups']==1
    assert new['n_exclusive_features']==3 and new['peak_condition'] is None


def test_expected_window_cannot_change_discovery_rank_but_historical_mode_is_explicit():
    rows=[{'gene':'G1','position':'S1','condition':'5min','ptm_relative_log2fc':2,'candidate_kinases':['K1']},
          {'gene':'G2','position':'S2','condition':'5min','ptm_relative_log2fc':1,'candidate_kinases':['K2']}]
    windows={'K1':{'min_minutes':30,'max_minutes':60}}
    assert _scores_from_rows(rows,{})==_scores_from_rows(rows,windows)=={'K1':2,'K2':1}
    assert _scores_from_rows(rows,windows,scoring_mode='prior_assisted_benchmark')=={'K1':0,'K2':1}


def test_magnitude_comparison_retains_negative_shared_observations_without_default_promotion():
    conditions=['1min','5min','15min','30min','60min','180min']
    shapes={'K1':[.2,1,2,1,.2,.1],'K2':[.1,.1,.2,1,2,1]}
    modules=[];series={}
    for kinase,values in shapes.items():
        keys=[f'{kinase}_{i}' for i in range(3)]
        for key in keys:series[key]=dict(zip(conditions,values))
        modules.append({'canonical':kinase,'members':[{'key':key} for key in keys+['shared']]})
    series['shared']=dict(zip(conditions,[a+.5*b for a,b in zip(shapes['K1'],shapes['K2'])]))
    manifest={'candidate_modules':modules,'conditions':conditions}
    def run(sign,transform):
        inputs={'ptm_timeseries':{k:{c:sign*v for c,v in ts.items()} for k,ts in series.items()},
                'ptm_qvalues':{},'features':{},'ptm_is_denovo':set(),'occupancy_timeseries':{},'occupancy_qvalues':{}}
        return score_tracks(manifest,inputs,{'tmm_config':{'target_transform':transform}})
    positive=run(1,'magnitude');negative=run(-1,'magnitude')
    assert positive['allocation_ledger']['features']['shared']['evaluation_status']=='evaluated'
    assert negative['allocation_ledger']['features']['shared']['evaluation_status']=='evaluated'
    for k in shapes:
        assert negative['relative'][k]['weighted_down_sums']['15min']==pytest.approx(-positive['relative'][k]['weighted_up_sums']['15min'])
        detail=next(d for d in positive['relative'][k]['contribution_details'] if d['ptm_key']=='shared')
        assert detail['condition_evaluations']['1min']['passes_score_rule'] is False
    legacy=run(-1,'signed')
    assert legacy['allocation_ledger']['features']['shared']['reason']=='no_non_negative_explanation'


def test_window_comparison_consumes_production_profile_support_and_preserves_signed_mass():
    from ptm_shared.time_window_comparison import compare_time_windows
    conditions=['1min','5min','15min','30min','60min','180min']
    shapes={'A':[1,2,1,1,2,1],'B':[2,1,1,2,1,1]}
    series={};identities={};modules=[]
    for kinase,values in shapes.items():
        keys=[f'{kinase}_{i}' for i in range(3)]
        for key in keys:
            series[key]=dict(zip(conditions,values))
            identities[key]={'protein_group':key,'modified_sequence':'AS(UniMod:21)K'}
        modules.append({'canonical':kinase,'members':[{'key':k} for k in keys+['shared']]})
    series['shared']=dict(zip(conditions,[-2.,-2.5,-1.5,-2.5,-2.,-1.5]))
    identities['shared']={'protein_group':'S','modified_sequence':'AS(UniMod:21)K'}
    manifest={'candidate_modules':modules,'conditions':conditions,'measurement_revision':'synthetic'}
    inputs={'features':identities,'ptm_timeseries':series,'ptm_qvalues':{},'ptm_is_denovo':set(),
        'occupancy_timeseries':{},'occupancy_qvalues':{}}
    primary=score_tracks(manifest,inputs,{'tmm_config':{}})
    result=compare_time_windows(manifest,inputs,primary,penalty=0)
    shared=next(r for r in result['records'] if r['feature_id']=='shared')
    assert shared['evaluation_status']=='evaluated'
    for record in shared['allocations']:
        assert sum(record['weighted_observations'].values())==pytest.approx(series['shared'][record['condition']])
    assert primary['allocation_ledger']['features']['shared']['reason']=='no_non_negative_explanation'
    assert result['default_model_promoted'] is False
