"""AI01 uses actual persisted sources/index/query, never an AST substitute."""
from copy import deepcopy
import json
import pandas as pd
import pytest
from ptm_shared import astra_evidence_catalog as access
from ptm_shared.astra_package import write_tables
from ptm_shared.effect_series import resolve_series
from ptm_shared.generic_workflow import json_write


def saved_points(root, times=(1,5,15,30,60,180), mixed=False, shared=False):
    root.mkdir(parents=True);(root/'reproducibility').mkdir();(root/'study').mkdir()
    conditions=[];contrasts=[];rows=[];bindings=[]
    for i,t in enumerate(times):
        ref='ref_'+str([1,0,4,2,5,3][i % 6]);target='target_'+str(i);cid='c_'+str(i)
        pairing=('paired' if i % 2 else 'unknown') if mixed else 'unpaired'
        conditions.extend([{'condition_id':ref,'label':'Control display '+str(9-i),'role':'reference','arm_id':'vehicle','control_family':'vehicle','time':{'minutes':t}},
            {'condition_id':target,'label':'Target display '+str(9-i),'role':'target','arm_id':'drug','time':{'minutes':t}}])
        contrasts.append({'contrast_id':cid,'target_condition_id':target,'reference_condition_id':ref,'pairing':pairing,
            'reference_strategy':'shared_reference' if shared else 'time_matched','effect_kind':'reference_change' if shared else 'matched_treatment_effect','control_family':'vehicle'})
        rows.append({'form_id':'f','contrast_id':cid,'condition_id':target,'target_condition_id':target,'reference_condition_id':ref,
            'arm_id':'drug','time_min':t,'reference_time_min':t,'pairing':pairing,'A':float(i),'U_joint':float(i+1),'P_joint':1.,'included':True})
        bindings.append({**rows[-1],'adapter_row_id':'raw_'+str(i)})
    if shared:
        for c in contrasts:c['reference_condition_id']=contrasts[0]['reference_condition_id']
        for r in rows+bindings:r.update(reference_condition_id=contrasts[0]['reference_condition_id'],reference_time_min=times[0])
    design={'study':{'design_axis':'time_course'},'conditions':conditions,'contrasts':contrasts,'replication_declaration':'unknown'}
    tables={'quant/summary':pd.DataFrame([{'form_id':'f','parent_pg':'p'}]),'quant/comparisons':pd.DataFrame(rows),
        'quant/protein_contrasts':pd.DataFrame([{**r,'protein_group':'p','gene':'G','log2_change':.1} for r in rows]),
        'quant/detection':pd.DataFrame(rows),'evidence/emergence_evidence':pd.DataFrame(columns=['emergence_id']),
        'reader_adapter/form_identity':pd.DataFrame([{'form_id':'f','identity_json':json.dumps({'gene':'G','protein_group':'p','taxa':['9606']})}]),
        'reader_adapter/form_contrasts':pd.DataFrame([{'adapter_row_id':b['adapter_row_id'],'form_id':'f','contrast_id':b['contrast_id'],'row_json':json.dumps(b)} for b in bindings]),
        'reader/coverage':pd.DataFrame([{'adapter_row_id':b['adapter_row_id'],'form_id':'f','contrast_id':b['contrast_id'],'summary_disposition':'unselected','card_status':'withheld'} for b in bindings]),
        'reader/cards':pd.DataFrame([{'card_id':'card','form_id':'f','selected':False,'card_json':json.dumps({'source_bindings':bindings})}]),
        'kinase/method_scores':pd.DataFrame([{'method_result_id':'method_'+str(i),'candidate_id':'k','contrast_id':r['contrast_id'],'method_id':'native','method_version':'v1','score_name':'activity','score':i,'method_p':None,'method_q':None,'status':'insufficient_coverage'} for i,r in enumerate(rows)]),
        'science/inference_results':pd.DataFrame([{'call_id':'call','proposed_entity_id':'k','contrast_or_window_id':'c_0','resolution':'no_call'}])}
    dictionary=write_tables({k:v.iloc[::-1] for k,v in tables.items()},root)
    json_write(root/'reproducibility/data_dictionary.json',dictionary)
    json_write(root/'study/study_design.json',design)
    json_write(root/'provenance.json',{'run_id':'actual-fixture-run'})
    access.write_evidence_access(root)
    return root,tables,design


@pytest.mark.parametrize('times,mixed', [((1,5,15,30,60,180),False),((7.5,45,240),True)])
def test_effect_filters_numeric_order_and_pagination(tmp_path,times,mixed):
    root,tables,design=saved_points(tmp_path/'p',times,mixed)
    c=access.EvidenceCatalog(root);sid=next(iter(resolve_series(design)[0]))
    for typ in ['raw_ptm','ptm_contrast','method_result']:
        filters={'evidence_type':typ,'effect_series_id':sid}
        reference=None
        for size in [1,5,100]:
            rows=[];cursor=None
            while True:
                page=c.query(filters,cursor,size);rows+=page['items'];cursor=page['next_cursor']
                if cursor is None:break
            assert [r['time_min'] for r in rows]==list(times)
            projected=[(r['evidence_id'],r['source_key_json']) for r in rows]
            if reference is not None:assert projected==reference
            reference=projected
        result=c.resolve([r['evidence_id'] for r in rows]);assert len(result)==len(times)
    card=c.query({'evidence_type':'card','effect_series_id':sid})['items'][0]
    assert len(json.loads(card['effect_memberships_json']))==len(times)
    assert json.loads(card['scope_json'])['reference_condition_id'] is None
    if mixed:assert json.loads(card['scope_json'])['pairing'] is None
    cursor=c.query({'effect_series_id':sid},page_size=1)['next_cursor']
    with pytest.raises(ValueError,match='Cursor'):c.query({'source_table':'reader/cards.csv'},cursor)


def test_multi_scope_cards_preserve_all_bindings_and_legacy_ids(tmp_path):
    root,tables,design=saved_points(tmp_path/'p')
    before=access.EvidenceCatalog(root)
    old_ids=set(before.index.evidence_id)
    design['conditions'][1]['arm_id']='other_arm'
    json_write(root/'study/study_design.json',design);access.write_evidence_access(root)
    after=access.EvidenceCatalog(root);scopes,_=resolve_series(design)
    assert set(after.index.evidence_id)==old_ids and len(scopes)==2
    for sid in scopes:assert after.query({'evidence_type':'card','effect_series_id':sid})['total_count']==1
    card=after.query({'evidence_type':'card'})['items'][0]
    assert card['effect_scope_status']=='multiple_canonical_scopes'
    assert json.loads(card['scope_json'])['effect_series_id'] is None
    assert after.catalog['catalog_id']!=before.catalog['catalog_id']


def test_null_time_ties_and_no_invented_legacy_scope(tmp_path):
    root,tables,design=saved_points(tmp_path/'p',(7.5,7.5,45,None),shared=True)
    c=access.EvidenceCatalog(root)
    rows=c.query({'evidence_type':'ptm_contrast'})['items']
    assert [r['time_min'] for r in rows]==[7.5,7.5,45,None]
    assert len({r['contrast_id'] for r in rows})==4
    (root/'study/study_design.json').unlink();access.write_evidence_access(root)
    old=access.EvidenceCatalog(root)
    assert old.index.effect_scope_status.eq('legacy_design_unavailable').all()
    assert all(json.loads(v)['effect_series_id'] is None for v in old.index.scope_json)


def test_snapshot_time_units_binding_filters_and_source_preservation(tmp_path):
    from ptm_shared.annotation_registry import digest
    root,tables,design=saved_points(tmp_path/'p',(30,45),mixed=True)
    before={name:digest(root/name) for name in access.EvidenceCatalog(root).catalog['sources']}
    design['conditions'][1]['time'].update(value=.5,unit='h',source='explicit')
    design['conditions'][0]['time'].update(value=30,unit='min',source='explicit')
    json_write(root/'study/study_design.json',design);access.write_evidence_access(root)
    c=access.EvidenceCatalog(root)
    assert before=={name:digest(root/name) for name in before}
    assert c.query({'evidence_type':'ptm_contrast'})['items'][0]['time_min']==30
    # Both values occur on the card, but on different points: no false conjunction.
    assert c.query({'evidence_type':'card','reference_condition_id':'ref_1','pairing':'paired'})['total_count']==0
    cursor=c.query(page_size=1)['next_cursor']
    other,_,_=saved_points(tmp_path/'other',(7.5,45))
    with pytest.raises(ValueError,match='Cursor'):access.EvidenceCatalog(other).query(cursor=cursor)
    (root/'study/study_design.json').write_text('{}')
    with pytest.raises(ValueError,match='hash'):c.query(cursor=cursor)
