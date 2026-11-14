"""Canonical saved evidence through query, bounded bundle, source and claims."""
import json
from unittest.mock import patch
from test_ai_catalog import saved_points
from ptm_shared.astra_evidence_catalog import EvidenceCatalog
from ptm_shared.effect_series import resolve_series
from ptm_shared.annotation_registry import digest


def test_effect_scope_to_bundle_source_and_claims_without_new_execution(tmp_path):
    root,_,design=saved_points(tmp_path/'p',(7.5,45,240),mixed=True)
    catalog=EvidenceCatalog(root);sid=next(iter(resolve_series(design)[0]))
    before={name:digest(root/name) for name in catalog.catalog['sources']}
    with patch('socket.socket.connect',side_effect=AssertionError('network forbidden')), \
         patch('ptm_shared.generic_workflow.calculate',side_effect=AssertionError('science forbidden')), \
         patch('ptm_shared.official_method_tracks.execute_tracks',side_effect=AssertionError('native forbidden')), \
         patch('ptm_shared.astra_literature.collect',side_effect=AssertionError('retrieval forbidden')):
        expected=catalog.query({'effect_series_id':sid},page_size=10000)['items']
        for budget in (1,5,100):
            cursor=None;items=[]
            while True:
                response=catalog.bundle({'scope':{'effect_series_id':sid},'row_budget':budget,
                    'byte_budget':150000,'continuation':cursor})
                assert response['returned_count']>0
                items+=response['items'];cursor=response['next_cursor']
                if cursor is None:break
            assert [r['evidence_ref']['evidence_id'] for r in items]==[r['evidence_id'] for r in expected]
        points=[r for r in items if r['evidence_ref']['source_table']=='quant/comparisons.csv']
        minutes={c['condition_id']:c['time']['minutes'] for c in design['conditions']}
        assert [r['values']['time_min'] for r in points]==sorted(minutes[c['target_condition_id']] for c in design['contrasts'])
        refs=[r['evidence_ref'] for r in points]
        sources=catalog.resolve([r['evidence_id'] for r in refs]);claims=[]
        for item,source in zip(points,sources):
            assert source['source_row']==item['values']
            v=item['values'];ref=item['evidence_ref']
            claims.append({'claim_id':ref['evidence_id'],'run_id':ref['run_id'],'catalog_id':ref['catalog_id'],
                'evidence_refs':[ref],'field_path':'A','asserted_value':v['A'],'unit':'log2_ratio','claim_level':'relative_effect',
                'target_condition_id':v['target_condition_id'],'reference_condition_id':v['reference_condition_id'],
                'target_time_min':v['time_min'],'reference_time_min':v['reference_time_min'],'comparison_kind':'matched_treatment_effect'})
        checked=catalog.check_claims(claims)
        assert all(c['verification_status']=='mechanically_validated_not_semantically_reviewed' for c in checked['claims'])
        assert all(c['semantic_review_status']=='not_performed' for c in checked['claims'])
        assert catalog.query({'selected_for_summary':False})['total_count']>0
        raw=[r for r in items if r['evidence']['evidence_type']=='raw_ptm']
        assert raw and all(r['evidence']['selected_for_summary'] is False for r in raw)
        coverage=catalog.bundle({'scope':{'source_table':'reader/coverage.csv'}})['items']
        assert coverage and all(r['values']['card_status']=='withheld' for r in coverage)
        no_call=catalog.bundle({'scope':{'evidence_type':'inference'}})['items']
        assert no_call[0]['values']['resolution']=='no_call'
    assert before=={name:digest(root/name) for name in before}
