"""Reader projection keeps canonical scope, missing values and method semantics."""
import pandas as pd
import pytest
from ptm_shared.astra_reader import phosx_time_views, write_phosx_time_views
from ptm_shared.contrast_quantification import KEY_COLUMNS


def fixture():
    comps=[]; executions=[]; results=[]; members=[]
    for cid,time,ref in [('aaa',180,'control'),('zzz',1,'control'),('bbb',1,'other')]:
        meta=dict.fromkeys(KEY_COLUMNS)
        meta.update(contrast_id=cid,arm_id='arm',condition_id=cid,target_condition_id=cid,
                    reference_condition_id=ref,time_min=time,reference_time_min=0,
                    target_label=str(time)+' min',reference_label=ref,pairing='unpaired')
        comps.extend([{**meta,'form_id':f,'included':True,'A':value} for f,value in [('st',2.),('tyr',9.)]])
        executions.append(dict(contrast_id=cid,method_id='PhosX_native_functions',execution_id=cid+'-exec',status='executed',reason=None))
        for candidate in ['human-assay','unknown-assay']:
            enough=cid=='zzz' and candidate=='human-assay'
            results.append(dict(method_result_id=cid+candidate,contrast_id=cid,candidate_id=candidate,
                method_id='PhosX_native_functions',native_score=1.7 if enough else 0.,
                score=1.7 if enough else None,method_p=.04 if enough else None,method_q=.1 if enough else None,
                eligible_site_count=1,universe_count=1,status='computed_method_enrichment' if enough else 'insufficient_coverage',
                membership_ids=cid+candidate+'-member',multiple_testing_family=cid+':PhosX:ST'))
            members.append(dict(contrast_id=cid,candidate_id=candidate,measurement_group_id='shared',selected=True))
    return {'quant/comparisons':pd.DataFrame(comps),'kinase/method_executions':pd.DataFrame(executions),
        'kinase/method_scores':pd.DataFrame(results),'kinase/method_membership':pd.DataFrame(members),
        'science/site_identity_audit':pd.DataFrame([dict(form_id=f,site_id=f,measurement_group_id='shared',site_attribution_eligible=True) for f in ['st','tyr']]),
        'science/specificity_scores':pd.DataFrame([dict(form_id=f,site_id=f,measurement_group_id='shared',
            status='scored' if f=='st' else 'not_evaluable',membership_selected=f=='st') for f in ['st','tyr']]),
        'kinase/kinase_candidate_edges':pd.DataFrame([dict(candidate_id=c,candidate_accession='Same label',
            edge_type='experimental_specificity_prediction') for c in ['human-assay','unknown-assay']])}


def test_time_scope_na_labels_and_existing_result_ids(tmp_path):
    tables=fixture();timeline,assays=phosx_time_views(tables)
    assert timeline.contrast_id.tolist()==['zzz','aaa','bbb']  # other reference stays distinct
    assert timeline.time_min.tolist()==[1,180,1]  # not ID order or a fabricated Control score
    assert timeline.included_joint_A_forms.tolist()==[2]*3
    assert timeline.scored_forms.tolist()==[1]*3  # unscored Y not counted as ST
    assert timeline.native_ranked_measurement_groups.tolist()==[1]*3
    assert len(assays)==6 and assays.candidate_id.nunique()==2
    assert assays.score.isna().sum()==5 and assays.method_q.isna().sum()==5
    assert assays.loc[assays.status.eq('insufficient_coverage'),'native_score'].eq(0).all()
    columns=list(tables['kinase/method_scores'].columns)
    pd.testing.assert_frame_equal(assays[columns].sort_values('method_result_id').reset_index(drop=True),
        tables['kinase/method_scores'].sort_values('method_result_id').reset_index(drop=True))
    shuffled={k:v.sample(frac=1,random_state=12) for k,v in tables.items()}
    again=phosx_time_views(shuffled)
    for left,right in zip((timeline,assays),again):pd.testing.assert_frame_equal(left.reset_index(drop=True),right.reset_index(drop=True))
    (tmp_path/'reader').mkdir(); files=write_phosx_time_views(tmp_path,tables)
    assert len(files)==3
    text=(tmp_path/files[0]).read_text()
    assert 'Same label — `human-assay`' in text and 'Same label — `unknown-assay`' in text
    assert '| NA | NA | NA |' in text and '전체 시간축의 통합 FDR' in text
    assert '\n\n| --- |' not in text  # table delimiter must immediately follow its header
    assert text.index('| 1 | 1 min / control') < text.index('| 180 | 180 min / control')


def test_conflicts_not_silently_first_aggregated():
    tables=fixture();tables['quant/comparisons'].loc[0,'time_min']=99
    with pytest.raises(ValueError,match='Conflicting PhosX'):phosx_time_views(tables)
    assert phosx_time_views({}) is None


def test_parity_comparator_scopes_union_without_claiming_other_times(tmp_path):
    """Comparator boundary fixture; not official-resource numerical parity."""
    import json
    from scripts.validate_phosx_parity import compare
    ref=tmp_path/'ref';actual=tmp_path/'actual';ref.mkdir()
    for name in ['science','kinase']:(actual/name).mkdir(parents=True)
    (ref/'reference.json').write_text(json.dumps(dict(contrast_id='target',matrix_sha256='m',background_sha256='b',
        eligible_sites=1,excluded_sites=0,input_hash='input')))
    for name,value in [('raw',1.234),('percentile',96.),('selection',True)]:
        pd.DataFrame({'K':[value]},index=['AAAAASAAAA']).to_csv(ref/(name+'.csv'))
    pd.DataFrame([dict(form_id='f',site_id='s',sequence='AAAAASAAAA')]).to_csv(ref/'reference_sites.csv',index=False)
    (ref/'excluded_sites.csv').write_text('\n')  # valid empty exclusion export
    pd.DataFrame({'Activity Score':[.57],'p value':[.1],'FDR q value':[.2]},index=['K']).to_csv(ref/'native_results.csv')
    pd.DataFrame({'K':[True]}).to_csv(ref/'native_membership.csv')
    pd.DataFrame([dict(measurement_group_id='g',sequence='AAAAASAAAA',A=2.)]).to_csv(ref/'input_bindings.csv',index=False)
    pd.DataFrame({'input_row_index':[0]}).to_csv(ref/'input_order.csv',index=False)
    pd.DataFrame([dict(form_id=f,site_id=s,status='scored',matrix_sha256='m',background_sha256='b',
        sequence_window='AAAAASAAAA',kinase_accession='K',score=value,percentile=96.,membership_selected=True)
        for f,s,value in [('f','s',1.234),('other','other',999.)]]).to_csv(actual/'science/specificity_scores.csv',index=False)
    pd.DataFrame([dict(edge_type='experimental_specificity_prediction',candidate_id='candidate',candidate_accession='K')]).to_csv(actual/'kinase/kinase_candidate_edges.csv',index=False)
    method=pd.DataFrame([dict(method_id='PhosX_native_functions',contrast_id=c,candidate_id='candidate',
        native_score=v,method_p=.1,method_q=.2) for c,v in [('target',.57),('unverified',999.)]])
    method.to_csv(actual/'kinase/method_scores.csv',index=False)
    pd.DataFrame([dict(method_id='PhosX_native_functions',contrast_id=c,candidate_id='candidate',measurement_group_id='g',
        selected=True,sequence='AAAAASAAAA',ranking_statistic=2.) for c in ['target','unverified']]).to_csv(actual/'kinase/method_membership.csv',index=False)
    pd.DataFrame([dict(method_id='PhosX_native_functions',contrast_id=c,status='executed',input_hash='input')
        for c in ['target','unverified']]).to_csv(actual/'kinase/method_executions.csv',index=False)
    result=compare(ref,actual)
    assert result['contrast_id']=='target' and result['scored_rows_compared']==result['native_results_compared']==1
    method.loc[0,'native_score']=10.;method.to_csv(actual/'kinase/method_scores.csv',index=False)
    with pytest.raises(AssertionError):compare(ref,actual)
