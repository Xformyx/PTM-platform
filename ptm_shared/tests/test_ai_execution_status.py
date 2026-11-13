from copy import deepcopy
import json
import pytest


def test_current_typed_execution_supersedes_historical_m2_text():
    from ptm_shared.astra_execution_status import attach_current_status
    packet={'whole_evidence':{'literature_execution_scope':'unchanged; M3/M4 not performed'},
        'literature_subject_execution':{'summary':{'requested_subjects':3,'comparison_executed_subjects':3,
            'execution_status_counts':{'retrieved':3},'requested_scope_status':'completed','status':'partial',
            'exported_anchored_proposals':0,'semantically_approved_subjects':0},
            'binding':{'effective_mode':'frozen_results_reused','current_cost':{'queries':0,'model_calls':0}}}}
    old=deepcopy(packet);state=attach_current_status(packet)
    assert state['typed_subject_review']['model_comparison']=='completed'
    assert state['typed_subject_review']['requested_scope']=='completed' and state['typed_subject_review']['whole_scope']=='partial'
    assert state['typed_subject_review']['exported_anchored_proposals']==0
    assert state['typed_subject_review']['consumer_cost']=={'queries':0,'model_calls':0}
    assert packet['whole_evidence']['literature_execution_scope']!='unchanged; M3/M4 not performed'
    assert state['historical_origin']['whole_evidence.literature_execution_scope']==old['whole_evidence']['literature_execution_scope']
    assert state['selected_finding_review']['retrieval']=='unknown'
    assert state==attach_current_status(packet)
    assert packet['literature_subject_execution']==old['literature_subject_execution']


@pytest.mark.parametrize('statuses,expected',[({'no_hit':2},'completed_no_hit'),({'retrieved':1,'retrieval_failed':1},'partial'),({'not_requested':2},'not_requested'),({},'unknown')])
def test_retrieval_status_and_counts_are_not_interchangeable(statuses,expected):
    from ptm_shared.astra_execution_status import project_current_status
    p={'literature_subject_execution':{'summary':{'execution_status_counts':statuses,'semantic_status':'review_required'}}}
    s=project_current_status(p)['typed_subject_review']
    assert s['retrieval']==expected and s['unique_chunks'] is None
    assert s['semantic_review']=='not_performed' and s['external_review']=='not_recorded'


def test_empty_comparison_and_absent_trace_are_distinct():
    from ptm_shared.astra_execution_status import project_current_status
    p={'literature':{'finding_records':{'f':{'status':'retrieved_comparison_pending',
        'comparison_execution':{'status':'completed'},'comparisons':[]}},
        'summary':{'selected_findings':1,'comparison_executed_findings':1,'anchored_proposals':0}}}
    s=project_current_status(p)['selected_finding_review']
    assert s['model_comparison']=='completed' and s['exported_anchored_proposals']==0
    assert project_current_status({})['selected_finding_review']['model_comparison']=='unknown'
    assert project_current_status({})['selected_finding_review']['semantic_review']=='unknown'
