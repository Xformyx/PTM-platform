"""C02: real estimator on tiny matrices; no PhosX, providers, or full workflow."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
import pytest

from test_generic_study import generic_fixture, write_inputs
from test_control_comparison import inputs, resolved
from ptm_shared.contrast_quantification import quantify_contrasts
from ptm_shared.astra_evidence_v6 import resolve_plan


def quantitative_fixture():
    context,rows=inputs('time_matched');context=resolved(context,rows)
    pr,pg,fasta,_,_,oldrows=generic_fixture()
    pr=pr.drop(columns=[r['sample_id'] for r in oldrows]);pg=pg.drop(columns=[r['sample_id'] for r in oldrows])
    amounts={'Control 0min':10.,'Control 30min':20.,'Control 60min':40.,'Drug 0.5h':40.,'Drug 60min':80.}
    for row in rows:pr[row['sample_id']]=amounts[row['condition']];pg[row['sample_id']]=2.
    return pr,pg,fasta,context,rows


def test_matched_and_shared_contrasts_use_real_samples_and_joint_masks():
    pr,pg,fasta,context,rows=quantitative_fixture();design=context['study_design']
    matched=quantify_contrasts(pr,pg,fasta,design);comp=matched['comparisons']
    np.testing.assert_allclose(comp.A,[1.,1.],atol=1e-12,rtol=0)
    np.testing.assert_allclose(comp.U_joint,[1.,1.],atol=1e-12,rtol=0)
    np.testing.assert_allclose(comp.P_joint,0,atol=1e-12,rtol=0)
    assert comp.reference_joint_n.eq(3).all() and comp.target_joint_n.eq(3).all()
    assert len(matched['runlevel'])==15 and matched['runlevel'].injection_id.nunique()==15
    assert comp.biological_p_value.isna().all() and comp.biological_q_value.isna().all()
    zero=next(c['condition_id'] for c in design['conditions'] if c['label']=='Control 0min')
    shared=resolved({**context,'control_comparison':{'strategy':'shared_reference','reference_condition_id':zero,'source':'user_input'}},rows)
    baseline=quantify_contrasts(pr,pg,fasta,shared['study_design'])
    np.testing.assert_allclose(baseline['comparisons'].sort_values('time_min').A,[2.,3.],atol=1e-12,rtol=0)
    assert len(baseline['runlevel'])==15  # Registered unused controls are not silently dropped.
    pr.loc[0,'f3_1']=np.nan;pg.loc[0,'f3_2']=np.nan
    masked=quantify_contrasts(pr,pg,fasta,design)['comparisons'].set_index('time_min')
    assert masked.loc[30,'target_joint_n']==1 and masked.loc[60,'target_joint_n']==3
    np.testing.assert_allclose(masked.A,masked.U_joint-masked.P_joint,atol=1e-12,rtol=0)


def test_fingerprint_depends_on_mapping_not_labels_sources_or_input_order():
    _,_,_,context,rows=quantitative_fixture();before=resolve_plan(context,{'PR':'pr','PG':'pg','FASTA':'same'},'same-pin')
    display=deepcopy(context)
    for c in display['study_design']['conditions']:
        c['label']='Display only '+c['label'];c['time']['original']='display only'
    for c in display['study_design']['contrasts']:c['reference_assignment_source']='confirmed_display_source'
    assert resolve_plan(display,{'PR':'pr','PG':'pg','FASTA':'same'},'same-pin')['fingerprints']['quant']==before['fingerprints']['quant']
    reordered=resolved({k:v for k,v in context.items() if k!='study_design'},list(reversed(rows)))
    assert resolve_plan(reordered,{'PR':'pr','PG':'pg','FASTA':'same'},'same-pin')['fingerprints']['quant']==before['fingerprints']['quant']
    zero=next(c['condition_id'] for c in context['study_design']['conditions'] if c['label']=='Control 0min')
    changed=resolved({**context,'control_comparison':{'strategy':'shared_reference','reference_condition_id':zero,'source':'user_input'}},rows)
    after=resolve_plan(changed,{'PR':'pr','PG':'pg','FASTA':'same'},'same-pin')
    for key in ['quant','discovery','temporal','inference']:assert before['fingerprints'][key]!=after['fingerprints'][key]
    # v6 binds source_pin in discovery, independently of the primary quant plan.
    alternate_pin=resolve_plan(context,{'PR':'pr','PG':'pg','FASTA':'same'},'different-pin')
    assert alternate_pin['fingerprints']['quant']==before['fingerprints']['quant']
    assert alternate_pin['fingerprints']['discovery']!=before['fingerprints']['discovery']


def test_whole_study_normalization_once_and_cache_reuses_only_identical_mapping(tmp_path):
    from ptm_shared import generic_workflow as workflow
    from ptm_shared.astra_package import quant_cached
    pr,pg,fasta,context,rows=quantitative_fixture();design=context['study_design']
    config=write_inputs(tmp_path,pr,pg,fasta)
    files={name:config[key] for name,key in [('PR','pr_matrix_path'),('PG','pg_matrix_path'),('FASTA','fasta_path')]}
    with patch.object(workflow,'normalize_supplied_matrices',wraps=workflow.normalize_supplied_matrices) as normalization:
        result,reuse=quant_cached(files,design,context,tmp_path/'cache','fixture-quant')
        assert normalization.call_count==1
        assert result[1]['applications']==1 and result[1]['scope']=='whole_study'
        assert len(result[1]['sample_columns'])==15
    relabel=deepcopy(design)
    for c in relabel['conditions']:c['label']='new '+c['label']
    with patch.object(workflow,'normalize_supplied_matrices',side_effect=AssertionError('must reuse')):
        cached,reuse=quant_cached(files,relabel,context,tmp_path/'cache','fixture-quant')
        assert reuse['status']=='reused'
        assert cached[0]['comparisons'].target_label.str.startswith('new ').all()
    # Even a mistakenly supplied old fingerprint cannot relabel old quantities
    # as a new target/reference contrast: validate actual saved metadata.
    zero=next(c['condition_id'] for c in design['conditions'] if c['label']=='Control 0min')
    changed=resolved({**context,'control_comparison':{'strategy':'shared_reference','reference_condition_id':zero}},rows)
    with patch.object(workflow,'normalize_supplied_matrices',wraps=workflow.normalize_supplied_matrices) as normalization:
        result,reuse=quant_cached(files,changed['study_design'],changed,tmp_path/'cache','fixture-quant')
        assert reuse['status']=='computed' and normalization.call_count==1
        np.testing.assert_allclose(result[0]['comparisons'].sort_values('time_min').A,[2.,3.],atol=1e-12,rtol=0)


def test_package_records_execution_policy_and_ignores_later_draft(tmp_path):
    from ptm_shared.astra_inputs import capture_order,transfer_contract
    from ptm_shared.astra_package import write_study_inputs
    _,_,_,context,rows=quantitative_fixture();design=context['study_design']
    snapshot=capture_order({'id':'synthetic-control','analysis_context':context,'sample_config':rows})
    (tmp_path/'study').mkdir();write_study_inputs(tmp_path,snapshot,context,design)
    saved=(tmp_path/'study/control_comparison.json').read_bytes()
    record=json.loads(saved)
    assert record['label']=='시간대별 Control 기준'
    assert record['effective_policy']['strategy']=='time_matched'
    for p in record['assignments']:
        assert p['target_time']['minutes']==p['reference_time']['minutes']
        assert p['target_time_source']['source']=='sample_config.condition'
        assert p['reference_time_source']['source']=='sample_config.condition'
    _,_,brief=transfer_contract(snapshot,design,context,{})
    assert '시간대별 Control 기준' in brief
    for c in design['contrasts']:
        assert c['contrast_id'] in brief and c['reference_condition_id'] in brief
    context['control_comparison']={'strategy':'shared_reference'}
    assert (tmp_path/'study/control_comparison.json').read_bytes()==saved
