"""M3: typed subjects, summary-independent planning/cache, fixture-only review."""
from copy import deepcopy
import json
from unittest.mock import patch
import pandas as pd
import pytest

from ptm_shared.tests.test_astra_evidence_catalog import saved, small, config
from ptm_shared.tests.test_astra_literature import Retriever, selection
from ptm_shared import astra_literature_review as review
from ptm_shared.astra_evidence_catalog import EvidenceCatalog, write_evidence_access
from ptm_shared.astra_package import write_tables
from ptm_shared.generic_workflow import json_write, object_hash


def setup(saved):
    root,tables,design=saved
    catalog=EvidenceCatalog(root)
    cards=tables['reader/cards'];obs=cards.loc[cards.category.eq('measured_feature_observation')]
    links=pd.DataFrame([{'status':'resolved','evidence_id':r.card_id,'question_id':'BQ-001',
        'subject_evidence_ids_json':json.dumps([r.card_id])} for r in obs.itertuples()])
    # Use only actually recorded fixture questions.
    packet=json.loads(tables['reader/packet'].iloc[0].packet_json)
    qids=[q['question_id'] for q in packet['research_question_evidence_map']['questions']]
    links['question_id']=qids[0] if qids else None
    if not qids:links=links.iloc[:0]
    plan=review.build_plan(catalog,links)
    return root,tables,catalog,plan,links


class TypedModel:
    provider='fixture';model='fixture-only'
    def __init__(self,scope='gene'):self.prompts=[];self.scope=scope
    def generate(self,prompt,**kwargs):
        self.prompts.append(prompt)
        quote='SameLabel S2 increased in human cells after insulin at 30min.'
        return json.dumps({'comparisons':[{'source_index':0,'quote':quote,'external_finding':'S2 increased',
            'reference_scope':self.scope,'relationship':'known_agreement','species':'human','cell_type':'',
            'insulin_dose':'','time':'','readout':'','perturbation':''}]})


def test_plan_summary_independence_and_typed_source_preservation(saved):
    root,tables,catalog,plan,links=setup(saved)
    assert set(plan.evidence_id)==set(catalog.index.loc[catalog.index.evidence_type.ne('disposition'),'evidence_id'])
    assert set(plan.execution_status)=={'not_requested'}
    original=plan.copy()
    for maximum in [5,15,50,0]:
        # Selection flags are display-only; no eligibility/hash/priority/alias change.
        catalog.index['selected_for_summary']=False
        catalog.index.loc[catalog.index.index[:maximum],'selected_for_summary']=True
        pd.testing.assert_frame_equal(review.build_plan(catalog,links),original)
    ids=plan.groupby('subject_type',sort=False).head(1).review_subject_id.tolist()
    payloads,study=review.resolve_subjects(catalog,plan,ids,tables,{},selection())
    for payload in payloads:
        kind=payload['subject_type']
        assert payload['readout']==review.READOUTS[kind]
        if kind!='observation':
            assert payload.get('category')!='measured_feature_observation'
            assert 'source_row' in payload['literature_input']
        if kind=='method_result':
            r=payload['literature_input']['source_row'];assert r['status']=='insufficient_coverage' and r['score'] is None
        if kind=='inference':assert payload['literature_input']['source_row']['resolution']=='no_call'
    withheld=plan.loc[plan.status_json.str.contains('withheld')].iloc[0]
    p=review.resolve_subjects(catalog,plan,[withheld.review_subject_id],tables,{},selection())[0][0]
    assert p['literature_input']['source_status']['card_status']=='withheld'
    assert p['allow_site_comparison'] is False
    assert 'card_json' not in plan and 'trajectory' not in plan


def test_unselected_review_existing_retriever_validator_cache_and_replay(saved,tmp_path):
    root,tables,catalog,plan,_=setup(saved)
    sid=plan.loc[plan.subject_type.eq('observation'),'review_subject_id'].iloc[0]
    tables['reader/findings']=tables['reader/findings'].iloc[:0]
    packet=json.loads(tables['reader/packet'].iloc[0].packet_json);packet['reader_cards']=[]
    tables['reader/packet'].loc[:,'packet_json']=json.dumps(packet)
    model=TypedModel();rag=Retriever()
    with patch('ptm_shared.finding_literature.time.sleep'):
        pin=review.execute_review(catalog,plan,[sid],tables,{},selection(),reason='fixture unselected',
            max_subjects=1,retriever=rag,llm=model,cache_root=tmp_path/'cache')
    record=pin['retrieval']['records'][sid]
    assert record['execution_status']=='retrieved' and record['comparison_status']=='completed'
    assert record['semantic_status']=='review_required'
    assert {p for p,q in rag.calls}=={'literature_background','gene_function_context','direct_site_evidence','counterevidence'}
    assert 'selected_finding_ids' not in pin
    refs=pin['retrieval']['references']
    comps=[c for s in refs for c in s.get('feature_comparisons',[])]
    assert comps and all(c['review_subject_id']==sid and c['claim_support_status']=='not_verified' for c in comps)
    assert all(c['comparison_status']=='source_anchored_semantic_review_required' for c in comps)
    assert review.replay_review(pin,catalog)==pin['retrieval']
    with patch('ptm_shared.finding_literature.retrieve_finding_literature',side_effect=AssertionError('cache required')):
        again=review.execute_review(catalog,plan,[sid],tables,{},selection(),reason='same subject',
            max_subjects=1,retriever=Retriever(),llm=TypedModel(),cache_root=tmp_path/'cache')
    assert again['current_cost']=={'queries':0,'model_calls':0}
    assert again['request_hashes']==pin['request_hashes']
    bad=deepcopy(pin);bad['sha256']='bad'
    with pytest.raises(ValueError,match='pin mismatch'):review.replay_review(bad,catalog)
    # A new source value cannot use a frozen comparison merely because IDs match.
    bad=deepcopy(pin);bad['source_value_hashes'][sid]='bad';bad['sha256']=object_hash({k:v for k,v in bad.items() if k!='sha256'})
    with pytest.raises(ValueError,match='value mismatch'):review.replay_review(bad,catalog)


def test_budget_failure_no_hit_restrictions_and_resume(saved,tmp_path):
    _,tables,catalog,plan,_=setup(saved)
    ids=plan.loc[plan.subject_type.eq('observation'),'review_subject_id'].tolist()[:2]
    with patch('ptm_shared.finding_literature.time.sleep'):
        pin=review.execute_review(catalog,plan,ids,tables,{},selection(),reason='budget fixture',max_subjects=1,retriever=Retriever(),llm=TypedModel())
        assert pin['retrieval']['records'][ids[1]]['execution_status']=='budget_deferred'
        resumed=review.execute_review(catalog,plan,pin['deferred_subject_ids'],tables,{},selection(),reason='resume fixture',max_subjects=2,retriever=Retriever(),llm=TypedModel())
        assert resumed['deferred_subject_ids']==[]
        failed=review.execute_review(catalog,plan,ids[:1],tables,{},selection(),reason='failure fixture',max_subjects=1,retriever=Retriever(True))
        assert failed['retrieval']['records'][ids[0]]['execution_status']=='retrieval_failed'
        empty=Retriever();empty.query_for_purpose=lambda *a,**k:[]
        nohit=review.execute_review(catalog,plan,ids[:1],tables,{},selection(),reason='nohit fixture',max_subjects=1,retriever=empty)
        assert nohit['retrieval']['records'][ids[0]]['execution_status']=='no_hit'
        zero=review.execute_review(catalog,plan,ids,tables,{},selection(),reason='zero budget',max_subjects=2,
            settings={'budget':{'max_queries':0}},retriever=Retriever())
        assert {r['execution_status'] for r in zero['retrieval']['records'].values()}=={'budget_deferred'}
        restricted=review.execute_review(catalog,plan,ids[:1],tables,{},selection('unknown'),reason='export',max_subjects=1,retriever=Retriever(),llm=TypedModel())
        assert all('document' not in r and 'feature_comparisons' not in r for r in restricted['retrieval']['references'])
    assert len(plan)==len(review.build_plan(catalog,pd.DataFrame(columns=['status','evidence_id','question_id','subject_evidence_ids_json'])))


def test_typed_protein_cannot_gain_site_agreement_or_use_empty_aggregate_cache(saved,tmp_path):
    _,tables,catalog,plan,_=setup(saved)
    sid=plan.loc[plan.subject_type.eq('protein'),'review_subject_id'].iloc[0]
    rag=Retriever();model=TypedModel('site')
    empty=review.execute_review(catalog,plan,[],tables,{},selection(),reason='empty request',max_subjects=0,cache_root=tmp_path)
    assert empty['retrieval']['records']=={}
    with patch('ptm_shared.finding_literature.time.sleep'):
        pin=review.execute_review(catalog,plan,[sid],tables,{},selection(),reason='typed',max_subjects=1,retriever=rag,llm=model,cache_root=tmp_path)
    record=pin['retrieval']['records'][sid]['record']
    assert record['excluded_comparisons'] and not record['comparisons']
    assert 'direct_site_evidence' not in {p for p,q in rag.calls}
    assert 'protein abundance contrast; not kinase activity' in model.prompts[0]
    assert 'source_row' in record['search_input']['observation']
    with pytest.raises(ValueError,match='Unknown review subject'):
        review.execute_review(catalog,plan,['invalid'],tables,{},selection(),reason='invalid',max_subjects=1)
    changed=plan.copy();changed.loc[changed.review_subject_id.eq(sid),'source_key_json']='{}'
    with pytest.raises(ValueError,match='key mismatch'):review.resolve_subjects(catalog,changed,[sid],tables,{},selection())


def test_request_hash_changes_with_evidence_question_resource_and_model(saved,tmp_path):
    _,tables,catalog,plan,_=setup(saved)
    sid=plan.loc[plan.subject_type.eq('observation'),'review_subject_id'].iloc[0]
    def run(t=tables,selected=None,model=None):
        with patch('ptm_shared.finding_literature.time.sleep'):
            return review.execute_review(catalog,plan,[sid],t,{},selected or selection(),reason='cache contract',
                max_subjects=1,retriever=Retriever(),llm=model or TypedModel(),cache_root=tmp_path)
    base=run();changed=deepcopy(tables)
    packet=json.loads(changed['reader/packet'].iloc[0].packet_json)
    packet['original_questions']['biological_question']='Changed recorded question'
    changed['reader/packet'].loc[:,'packet_json']=json.dumps(packet)
    q=run(changed);resource=selection();resource['collections'][0]['version']='frozen-2'
    r=run(selected=resource);model=TypedModel();model.model='different-fixture';m=run(model=model)
    assert len({p['request_hashes'][sid] for p in [base,q,r,m]})==4
    assert all(p['current_cost']['queries']>0 for p in [base,q,r,m])


def test_plan_publication_is_required_and_failure_keeps_previous_success(config,tmp_path):
    from ptm_shared import astra_evidence_v6 as engine
    from ptm_shared.astra_reader_revision import revise_temporal
    config['experimental_context']['quantitation_export_mode']='astra_analysis.v6'
    with patch('ptm_shared.astra_literature_review.execute_review',side_effect=AssertionError('no automatic review')):
        result=engine.run('m3-normal-fixture',config,tmp_path/'source')
    source=tmp_path/'source/enrichment_free_runs'/result['run_id']
    assert (source/review.PLAN).is_file() and (source/review.META).is_file()
    assert review.validate_plan(EvidenceCatalog(source))['subjects']>0
    out=tmp_path/'revision';out.mkdir();pointer=out/'enrichment_free_current.json';pointer.write_text('previous_success')
    with patch('ptm_shared.astra_literature_review.write_review_plan',side_effect=ValueError('review plan failed')):
        with pytest.raises(ValueError,match='review plan failed'):revise_temporal(source,out,review_plan_only=True)
    assert pointer.read_text()=='previous_success'


def test_method_queries_use_recorded_entities_without_fabricated_gene_site(saved):
    _,tables,catalog,plan,_=setup(saved)
    sid=plan.loc[plan.subject_type.eq('method_result'),'review_subject_id'].iloc[0]
    rag=Retriever()
    with patch('ptm_shared.finding_literature.time.sleep'):
        pin=review.execute_review(catalog,plan,[sid],tables,{},selection(),reason='method context fixture',
            max_subjects=1,retriever=rag,llm=TypedModel())
    assert any('AKT1' in q for layer,q in rag.calls if layer=='gene_function_context')
    assert any('AKT1' in q for layer,q in rag.calls if layer=='counterevidence')
    record=pin['retrieval']['records'][sid]['record']
    assert record['search_input']['identity']['gene'] is None
    assert not record['comparisons'] and record['excluded_comparisons']
    assert record['search_input']['observation']['source_row']['status']=='insufficient_coverage'


def test_partial_retrieval_and_layer_budget_remain_resumable_after_comparison(saved):
    _,tables,catalog,plan,_=setup(saved)
    sid=plan.loc[plan.subject_type.eq('observation'),'review_subject_id'].iloc[0]
    rag=Retriever();query=rag.query_for_purpose
    def partial(q,**kwargs):
        if kwargs['purpose']=='counterevidence':raise RuntimeError('fixture counterevidence unavailable')
        return query(q,**kwargs)
    rag.query_for_purpose=partial
    with patch('ptm_shared.finding_literature.time.sleep'):
        failed=review.execute_review(catalog,plan,[sid],tables,{},selection(),reason='partial retrieval fixture',
            max_subjects=1,retriever=rag,llm=TypedModel())
        bounded=review.execute_review(catalog,plan,[sid],tables,{},selection(),reason='layer budget fixture',
            max_subjects=1,settings={'budget':{'max_queries':1}},retriever=Retriever(),llm=TypedModel())
    for pin in [failed,bounded]:
        record=pin['retrieval']['records'][sid]
        assert record['execution_status']=='retrieved' and record['comparison_status']=='completed'
        assert pin['deferred_subject_ids']==[sid]
        assert pin['cache'][sid]['status']=='not_cached'
