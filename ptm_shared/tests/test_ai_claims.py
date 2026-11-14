from copy import deepcopy
import json
import pytest
from test_ai_catalog import saved_points
from ptm_shared.astra_evidence_catalog import EvidenceCatalog


def claim(c):
    item=c.bundle({'scope':{'evidence_type':'ptm_contrast'},'row_budget':6})['items'][1]
    v=item['values']
    return {'claim_id':'claim1','run_id':item['evidence_ref']['run_id'],'catalog_id':c.catalog['catalog_id'],
        'evidence_refs':[item['evidence_ref']],'field_path':'A','asserted_value':v['A'],'unit':'log2_ratio',
        'target_condition_id':v['target_condition_id'],'reference_condition_id':v['reference_condition_id'],
        'target_time_min':v['time_min'],'reference_time_min':v['reference_time_min'],
        'comparison_kind':'matched_treatment_effect','claim_level':'relative_effect'}


def test_numeric_anchor_scope_and_semantic_status_are_independent(tmp_path):
    root,_,_=saved_points(tmp_path/'p');c=EvidenceCatalog(root);q=claim(c)
    result=c.check_claims([q])['claims'][0]
    assert result['anchor_status']=='validated' and result['numeric_status']=='passed'
    assert result['scope_status']=='passed' and result['restriction_status']=='passed'
    assert result['semantic_review_status']=='not_performed'
    assert result['verification_status']=='mechanically_validated_not_semantically_reviewed'
    wrong=deepcopy(q);wrong['run_id']='old-run'
    assert c.check_claims([wrong])['claims'][0]['anchor_status']=='invalid'


@pytest.mark.parametrize('field,value,status',[('asserted_value',-1.,'numeric_status'),
    ('reference_condition_id','wrong','scope_status'),('target_time_min',999,'scope_status'),
    ('unit','supplied_intensity_unit','restriction_status'),('claim_level','confirmed_kinase_call','restriction_status'),
    ('tolerance',1e9,'numeric_status')])
def test_wrong_sign_time_control_unit_and_promotion_fail(tmp_path,field,value,status):
    root,_,_=saved_points(tmp_path/'p');c=EvidenceCatalog(root);q=claim(c);q[field]=value
    r=c.check_claims([q])['claims'][0]
    assert r[status]=='failed' and r['verification_status']=='rejected'


def test_null_unknown_and_method_biological_statistic_confusion(tmp_path):
    root,_,_=saved_points(tmp_path/'p');c=EvidenceCatalog(root);q=claim(c)
    q.update(field_path='biological_p_value',asserted_value=0.,unit='probability',claim_level='biological_statistic')
    # This sparse fixture never recorded that field: it is unknown, not zero.
    assert c.check_claims([q])['claims'][0]['numeric_status']=='unverifiable'
    e=c.bundle({'scope':{'evidence_type':'method_result'},'row_budget':1})['items'][0]
    q.update(evidence_refs=[e['evidence_ref']],field_path='method_q')
    r=c.check_claims([q])['claims'][0]
    assert r['numeric_status']=='failed' and r['restriction_status']=='failed'
    q['asserted_value']=None
    assert c.check_claims([q])['claims'][0]['numeric_status']=='unverifiable'


def test_no_call_is_citable_but_not_inactivity(tmp_path):
    root,_,_=saved_points(tmp_path/'p');c=EvidenceCatalog(root)
    e=c.bundle({'scope':{'evidence_type':'inference'}})['items'][0]
    q={'claim_id':'no-call','run_id':e['evidence_ref']['run_id'],'catalog_id':c.catalog['catalog_id'],
       'evidence_refs':[e['evidence_ref']],'field_path':'resolution','asserted_value':'no_call','unit':'category','claim_level':'declared_status'}
    good=c.check_claims([q])['claims'][0];assert good['numeric_status']=='passed' and good['restriction_status']=='passed'
    q['claim_level']='kinase_inactivity';assert c.check_claims([q])['claims'][0]['restriction_status']=='failed'


def test_declared_rounding_and_multiple_reference_ambiguity(tmp_path):
    from ptm_shared.astra_claim_check import compare_value
    assert compare_value(.373313567,.373,rounding_precision=3)[0]=='passed'
    assert compare_value(.373313567,-.373,rounding_precision=3)[0]=='failed'
    assert compare_value(.373313567,0.,tolerance=10)[0]=='failed'
    root,_,_=saved_points(tmp_path/'p');c=EvidenceCatalog(root);q=claim(c)
    q['evidence_refs'] += [c.bundle({'scope':{'evidence_type':'ptm_contrast'},'row_budget':1})['items'][0]['evidence_ref']]
    assert c.check_claims([q])['claims'][0]['numeric_status']=='unverifiable'


def test_explicit_nested_binding_and_legacy_unknown_semantics(tmp_path):
    from ptm_shared.quantitative_fields import field_semantics,table_field_semantics
    import pandas as pd
    root,_,_=saved_points(tmp_path/'p');c=EvidenceCatalog(root);q=claim(c)
    card=c.bundle({'scope':{'evidence_type':'card'}})['items'][0]
    q.update(evidence_refs=[card['evidence_ref']],field_path='card_json.source_bindings.1.A')
    assert c.check_claims([q])['claims'][0]['verification_status']=='mechanically_validated_not_semantically_reviewed'
    q['field_path']='card_json.source_bindings.A'
    assert c.check_claims([q])['claims'][0]['numeric_status']=='unverifiable'
    old=field_semantics('quant/detection','eligible_A',row={'eligible_A':0.})
    assert old['status']=='unknown' and old['unknown_reason']=='legacy_detection_semantics_not_versioned'
    new=table_field_semantics('quant/detection',pd.DataFrame([{'eligible_A':0.,'detection_version':'target_arm_post_reference.v2'}]))
    assert new['field_semantics']['eligible_A']['status']=='known'


def test_fragment_anchor_does_not_approve_whole_paper_or_localization():
    from ptm_shared.astra_claim_check import _restrictions
    from ptm_shared.quantitative_fields import field_semantics
    fragment=field_semantics('reader/literature_sources','source_json.document')
    assert _restrictions({'claim_level':'literature_fragment','unit':'text'},fragment,{})[0]=='passed'
    assert _restrictions({'claim_level':'whole_paper_review','unit':'text'},fragment,{})[0]=='failed'
    loc=field_semantics('quant/comparisons','localization_probability')
    assert _restrictions({'claim_level':'high_localization_confidence','unit':'probability'},loc,{})[0]=='failed'
