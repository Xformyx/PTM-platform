import copy
import pytest
from ptm_shared.kinase_model_comparison import run_footprint_comparisons


def example():
    manifest={'measurement_revision':'synthetic','conditions':['1min','5min','15min','30min'],
              'candidate_modules':[{'canonical':'K1','members':[{'key':'a'},{'key':'b'}]},
                                   {'canonical':'K2','members':[{'key':'c'},{'key':'d'}]}]}
    inputs={'features':{k:{'protein_group':k,'modified_sequence':'AS(UniMod:21)K'} for k in 'abcdef'},
            'ptm_timeseries':{k:{c:v+i*.1 for i,c in enumerate(manifest['conditions'])} for k,v in zip('abcdef',[2,3,-2,-3,.1,-.1])}}
    return manifest,inputs


def test_footprint_directions_no_call_and_precursor_duplicate_invariance():
    manifest,inputs=example()
    before=copy.deepcopy(inputs)
    output=run_footprint_comparisons(manifest,inputs,['ksea_z.v1','ulm_t.v1','mlm_t.v1'])
    assert before==inputs
    for model in output['models']:
        values={r['kinase']:r['score'] for r in model['records'] if r['condition']=='1min'}
        assert values['K1']>0>values['K2']
        assert model['default_model_promoted'] is False
        assert model['false_positive_rate'] is None
    inputs['features']['a-copy']=inputs['features']['a'].copy()
    inputs['ptm_timeseries']['a-copy']=inputs['ptm_timeseries']['a'].copy()
    manifest['candidate_modules'][0]['members'].append({'key':'a-copy'})
    duplicate=run_footprint_comparisons(manifest,inputs,['ksea_z.v1','ulm_t.v1','mlm_t.v1'])
    for first,second in zip(output['models'],duplicate['models']):
        assert first['records']==second['records']


def test_rank_deficiency_withholds_individual_mlm_and_partial_model_keeps_gap():
    manifest,inputs=example()
    manifest['candidate_modules'][1]['members']=manifest['candidate_modules'][0]['members']
    inputs['ptm_timeseries']['a'].pop('5min')
    output=run_footprint_comparisons(manifest,inputs,['mlm_t.v1','partial_linear.v1'])
    mlm,partial=output['models']
    assert all(r['score'] is None for r in mlm['records'])
    assert all(r['reason']=='insufficient_independent_measurement_groups' for r in mlm['records'] if r['condition']=='5min')
    assert all(r['reason'].startswith('rank_deficient') for r in mlm['records'] if r['condition']!='5min')
    record=next(r for r in partial['records'] if r['feature_id']=='a')
    assert record['evaluation_status']=='evaluated' and record['missing_conditions']==['5min']
    assert '5min' not in record['predicted_values'] and partial['observation_imputation'] is False
