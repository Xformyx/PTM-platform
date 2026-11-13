import pandas as pd
from ptm_shared.astra_package import write_tables


def test_column_contracts_preserve_bytes_and_null_semantics(tmp_path):
    frame=pd.DataFrame({'form_id':['f','g'],'contrast_id':['c','c'],'A':[1.,None],'U_joint':[2.,None],
        'P_joint':[1.,None],'U_all':[2.,3.],'biological_p_value':[None,None],
        'localization_probability':[None,None],'reference_joint_n':[3,0],
        'reference_biological_n':[1,None],'time_min':[30.,None],'joint_observed':[True,False],
        'unregistered_measure':[0.,None]})
    d=write_tables({'quant/comparisons':frame},tmp_path)['quant/comparisons.csv']
    fields=d['field_semantics']
    assert set(fields)==set(frame)
    assert fields['A']['unit']=='log2_ratio' and fields['A']['observed_null_count']==1
    assert fields['biological_p_value']['statistical_unit']=='biological_unit_or_declared_pair'
    assert fields['reference_joint_n']['statistical_unit']=='injection'
    assert fields['reference_biological_n']['statistical_unit']=='biological_unit'
    assert fields['localization_probability']['nullable'] is True
    assert fields['unregistered_measure']['status']=='unknown' and fields['unregistered_measure']['unknown_reason']
    assert (tmp_path/'quant/comparisons.csv').read_bytes()==frame.to_csv(index=False).encode()


def test_method_discriminators_use_recorded_native_semantics(tmp_path):
    frame=pd.DataFrame([{'method_result_id':'m','contrast_id':'c','candidate_id':'k','method_id':'PhosX_native_functions','method_version':'0.23.1',
        'score_name':'Activity Score','score':2.,'method_p':.02,'method_q':.04,
        'null_model':'official_site_rank_permutation_not_biological_units',
        'multiple_testing_family':'c:PhosX:ST','direction_semantics':'signed_rank_enrichment_not_causal_activation',
        'statistical_unit':'measurement_group','biological_p_value':None,'status':'computed_method_enrichment'}])
    comparisons=pd.DataFrame([{'form_id':'f','contrast_id':'c','arm_id':'a','reference_condition_id':'r','pairing':'unknown','time_min':30,'reference_time_min':0}])
    d=write_tables({'kinase/method_scores':frame,'quant/comparisons':comparisons},tmp_path)['kinase/method_scores.csv']
    variants=d['method_semantics'];v=variants[0]
    assert v['discriminator']=={'method_id':'PhosX_native_functions','method_version':'0.23.1','score_name':'Activity Score'}
    assert v['fields']['score']['unit']=='native_activity_score'
    assert v['fields']['method_q']['null_model']==frame.iloc[0].null_model
    assert v['fields']['method_q']['multiple_testing_family']==frame.iloc[0].multiple_testing_family
    assert 'log2' not in v['fields']['score']['meaning']
    assert d['field_semantics']['biological_p_value']['observed_null_count']==1


def test_non_native_scores_and_unknowns_are_not_invented_log_effects():
    from ptm_shared.quantitative_fields import field_semantics
    z=field_semantics('kinase/method_scores','score',row={'method_id':'repository_measured_gene_zscore','method_version':'1','score_name':'z_score'})
    assert z['unit']=='standardized_score' and z['restriction_class']=='descriptive_footprint'
    old=field_semantics('kinase/method_scores','score',row={'method_id':'unknown'})
    assert old['status']=='unknown' and old['unit']=='unknown'
    footprint=field_semantics('kinase/kinase_temporal_profiles','activity_magnitude')
    assert footprint['restriction_class']=='descriptive_footprint'
