import copy
import pytest
from ptm_shared.time_window_comparison import compare_time_windows


def fixture():
    conditions=['1min','5min','15min','30min','60min','180min']
    shapes={'A':[1,2,1,1,2,1],'B':[2,1,1,2,1,1]}
    manifest={'measurement_revision':'synthetic','conditions':conditions,
        'candidate_modules':[{'canonical':k,'members':[{'key':'F'}]} for k in shapes]}
    scores={'relative':{k:{'profile_type':'data_driven','profile_values':dict(zip(conditions,v)),
        'kinase_profile_provenance':{'support_unit':'measurement_group.v1','independent_group_count':3}} for k,v in shapes.items()}}
    inp={'features':{'F':{}},'ptm_timeseries':{'F':dict(zip(conditions,[-v for v in [2.,2.5,1.5,2.5,2.,1.5]]))}}
    return manifest,inp,scores


def test_two_window_model_recovers_synthetic_mix_sign_and_mass_without_changing_primary():
    manifest,inp,scores=fixture();before=copy.deepcopy(scores)
    result=compare_time_windows(manifest,inp,scores,penalty=0)
    row=result['records'][0]
    assert row['evaluation_status']=='evaluated' and row['coefficients']==pytest.approx([1,.5,.5,1])
    for allocation in row['allocations']:
        assert sum(allocation['shares'].values())==pytest.approx(1)
        assert sum(allocation['weighted_observations'].values())==pytest.approx(inp['ptm_timeseries']['F'][allocation['condition']])
    assert before==scores and result['default_model_promoted'] is False


def test_identical_profiles_prior_only_and_missing_windows_are_withheld():
    manifest,inp,scores=fixture()
    scores['relative']['B']['profile_values']=scores['relative']['A']['profile_values']
    row=compare_time_windows(manifest,inp,scores)['records'][0]
    assert row['resolution']=='ambiguous_group' and row['allocations']==[]
    scores['relative']['B']['profile_type']='gaussian_fallback'
    assert compare_time_windows(manifest,inp,scores)['records'][0]['reason']=='independent_observed_anchors_required'
    manifest,inp,scores=fixture();inp['ptm_timeseries']['F'].pop('5min')
    assert compare_time_windows(manifest,inp,scores)['records'][0]['reason']=='insufficient_observations_per_window'
