import copy
import pytest
from ptm_shared.proda_comparison import prepare_proda_input,run_proda_comparison


def fixture():
    samples=[{'sample_id':f'{condition}-{i}-{repeat}','condition':condition,'biological_unit':f'{condition}-{i}'}
        for condition in ['Control','5min'] for i in range(3) for repeat in range(2)]
    identity={'Precursor.Id':'p','Modified.Sequence':'AS(UniMod:21)K','Precursor.Charge':'2','Protein.Group':'P'}
    data={'sample_manifest':{'samples':samples,'pairing':'unpaired'},'condition_map':{s['sample_id']:s['condition'] for s in samples},
        'records':[{'identity':identity,'source_row':2,'reason':'contrast_inventory_created',
            'sample_observations':{s['sample_id']:None if s['condition']=='Control' else 16 for s in samples}}]}
    return data,{'F':identity}


def test_raw_missingness_and_biological_unit_contract_without_R_execution():
    data,features=fixture();before=copy.deepcopy(data)
    result=prepare_proda_input(data,features,quantification_method='label_free')
    assert len(result['units'])==6  # twelve technical observations, six biological units
    values=result['rows']['F'];assert values.count(None)==3 and values.count(4.)==3
    assert result['imputation'] is False and data==before
    with pytest.raises(ValueError,match='assay_not_declared'):prepare_proda_input(data,features,quantification_method='Astral')
    data['sample_manifest']['pairing']='paired'
    with pytest.raises(ValueError,match='paired_proda'):prepare_proda_input(data,features,quantification_method='label_free')


def test_unavailable_input_is_not_empty_completed_model(tmp_path):
    result=run_proda_comparison(tmp_path,tmp_path/'work',{}, {})
    assert result['status']=='not_evaluable' and result['reason']=='raw_observation_inventory_missing'
    assert not (tmp_path/'work').exists()
