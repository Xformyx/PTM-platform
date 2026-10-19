"""Synthetic transport only: exact anchors, unchanged approval, private traces."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
import pytest
from ptm_shared import finding_literature as finding
from ptm_shared.astra_literature import _export_result
from common.generation_trace import capture_generation, record_generation_event


QUOTE='KIN S2 increased in human cells at 5min.'
SECOND='KIN S2 decreased in mouse cells at 30min.'


def candidate(**changes):
    return {**dict.fromkeys(finding.CONTEXT_FIELDS,''), 'source_index':0,'quote':QUOTE,
        'external_finding':'S2 increased','reference_scope':'site','relationship':'direct_site_evidence',**changes}


class Retriever:
    collection_names=['fixture']
    def query(self,*args,**kwargs):
        return [{'collection':'fixture','collection_version':'fixed','source_id':key,
            'document':text,'doi':'10.1000/test','metadata':{'document_id':1,'chunk_index':i,'page':i+1}}
            for i,(key,text) in enumerate([('z-first',QUOTE),('a-second',SECOND)])]


class Model:
    model='fixture-model';provider='fixture'
    def __init__(self,value,finish='stop'):self.value=value;self.finish=finish
    def generate(self,prompt,**kwargs):
        sources=json.loads(prompt[prompt.index('{'):])['sources']
        assert [s['text'] for s in sources]==[QUOTE,SECOND]
        record_generation_event(event_type='request',request_payload={'prompt':prompt,**kwargs},transport_attempt=1)
        raw=self.value if isinstance(self.value,str) else json.dumps(self.value)
        record_generation_event(response={'response':raw},finish_reason=self.finish,usage={'tokens':3})
        return raw


def execute(tmp_path, proposals, *, typed=False, allow=True, finish='stop'):
    card={'finding_id':'finding-one','card_id':'card-one','source_bindings':[
        {'adapter_row_id':'row-one','form_id':'form-one','contrast_id':'contrast-one'}],
        'feature_identity':{'reader_feature_id':'reader-one','gene':'KIN','candidate_residue_annotation':'S2'},
        'reader_summary':{'measured':'fixture'}}
    if typed:card.update(review_subject_id='subject-one',subject_type='method_result',
        entity_identity=deepcopy(card['feature_identity']),allow_site_comparison=allow,readout='method enrichment, not activity')
    with patch.object(finding.time,'sleep'):
        return finding.retrieve_finding_literature([card],Retriever(),{'species':'human'},
            llm=Model(proposals,finish),trace_directory=tmp_path,
            trace_context={'run_id':'fixture-run','stage_id':'fixture-stage','request_sha256':'f'*64,
                'evidence_refs':[{'evidence_id':'evidence-one','source_table':'fixture.csv','source_key':{'id':'one'}}]})


@pytest.mark.parametrize('changes,typed,allow,gate,accepted',[
    ({},False,True,None,True),
    ({'source_index':9},False,True,'source_index',False),
    ({'source_index':1},False,True,'literal_quote',False),
    ({'quote':'KIN S2 rose.'},False,True,'literal_quote',False),
    ({'quote':'KIN … human cells'},False,True,'literal_quote',False),
    ({'quote':'KIN S2 증가'},False,True,'literal_quote',False),
    ({'quote':''},False,True,'nonempty_quote',False),
    ({'quote':'human cells'},False,True,'scope_identifier',False),
    ({'quote':'KIN'},False,True,'site_identifier',False),
    ({'species':'rat'},False,True,'context',False),
    ({},True,False,'typed_site',False),
    ({'reference_scope':'gene','relationship':'gene_function_context'},True,False,None,True),
    ({'relationship':'unrecognized'},False,True,'relationship',False),
    ({'external_finding':''},False,True,'claim',False),
])
def test_all_gate_diagnostics_agree_with_unchanged_production_expression(tmp_path,changes,typed,allow,gate,accepted):
    result=execute(tmp_path,{'comparisons':[candidate(**changes)]},typed=typed,allow=allow)
    record=next(iter(result['records'].values()));diag=record['comparison_diagnostics'];p=diag['proposals'][0]
    assert bool(record['comparisons'])==accepted==p['production_accepted']==p['accepted_by_anchor_gates']
    assert p['gate_parity'] and diag['prompt_validation_sources_match']
    assert diag['source_map'][0]['source_key']['source_id']=='z-first'
    assert diag['source_map'][1]['source_key']['source_id']=='a-second'
    if gate:assert p['gates'][gate] is False
    if changes.get('source_index')==1:
        assert p['other_source_indices']==[0] and 'quote_present_in_other_prompt_source' in p['diagnoses']
    if typed and not allow and gate=='typed_site':
        assert p['first_failure_reason']==record['excluded_comparisons'][0]['reason']=='typed_site_comparison_not_allowed'
    if accepted:
        comparison=result['references'][0]['feature_comparisons'][0]
        assert comparison['claim_support_status']=='not_verified'
        assert comparison['comparison_status']=='source_anchored_semantic_review_required'
    stored=diag['internal_trace'];path=tmp_path/'generation_traces'/f"{stored['trace_id']}.json"
    assert hashlib.sha256(path.read_bytes()).hexdigest()==stored['sha256']
    assert path.stat().st_mode & 0o777==0o600
    trace=json.loads(path.read_text())
    assert trace['diagnostics']['attempt_id']==diag['attempt_id']
    assert trace['diagnostics']['run_id']=='fixture-run'
    assert trace['diagnostics']['evidence_refs'][0]['source_key']=={'id':'one'}
    assert hashlib.sha256(trace['resolved_prompt'].encode()).hexdigest()==diag['prompt_sha256']
    assert hashlib.sha256(trace['generation']['provider_raw_text'].encode()).hexdigest()==diag['raw_output_sha256']
    assert trace['diagnostics']['parsed_output']=={'comparisons':[candidate(**changes)]}


@pytest.mark.parametrize('response,finish,parse,status,truncation',[
    ('{"comparisons":[','length','failed','schema_or_parse_failure','observed'),
    ('not json',None,'failed','schema_or_parse_failure','unknown'),
    ({'comparisons':[]},'stop','parsed','empty','not_reported_by_provider'),
    ({'comparisons':'wrong'},'stop','parsed','schema_or_parse_failure','not_reported_by_provider'),
    ({'comparisons':[None]},'stop','parsed','proposals_returned','not_reported_by_provider'),
])
def test_parse_empty_truncation_and_invalid_proposals_remain_distinct(tmp_path,response,finish,parse,status,truncation):
    result=execute(tmp_path,response,finish=finish);record=next(iter(result['records'].values()))
    diag=record['comparison_diagnostics']
    assert diag['parse_status']==parse and diag['comparisons_status']==status
    assert diag['truncation_status']==truncation and not record['comparisons']
    assert diag['internal_trace']['status']=='stored'


@pytest.mark.parametrize('permission',['permitted','unknown'])
def test_export_never_leaks_restricted_proposals_or_provider_payloads(tmp_path,permission):
    result=execute(tmp_path,{'comparisons':[candidate(quote='REJECTED PRIVATE QUOTE',species='PRIVATE CONTEXT')]})
    original=deepcopy(result)
    exported=_export_result(result,{'collections':[{'chromadb_name':'fixture','evidence_export_permission':permission}]})
    assert original==result
    diag=next(iter(exported['records'].values()))['comparison_diagnostics']
    assert 'prompt_sources' not in diag and 'parsed_output' not in diag
    assert 'provider_raw_text' not in json.dumps(diag) and 'request_payload' not in json.dumps(diag)
    assert diag['proposals'][0]['first_failure_reason']=='quote_not_in_retrieved_chunk'
    if permission=='unknown':
        text=json.dumps(exported)
        for secret in (QUOTE,SECOND,'REJECTED PRIVATE QUOTE','PRIVATE CONTEXT'):
            assert secret not in text
        assert 'candidate' not in diag['proposals'][0] and 'source_offset' not in diag['proposals'][0]
    else:
        assert diag['proposals'][0]['candidate']['quote']=='REJECTED PRIVATE QUOTE'
    private=json.loads(next((tmp_path/'generation_traces').glob('*.json')).read_text())
    assert private['diagnostics']['proposals'][0]['candidate']['quote']=='REJECTED PRIVATE QUOTE'


@pytest.mark.parametrize('provider',['ollama','openai'])
def test_existing_model_transport_captures_final_payload_without_credentials(monkeypatch,provider):
    from common.llm_client import LLMClient
    class Response:
        status_code=200
        def raise_for_status(self):pass
        def json(self):return {'model':'fixture-model','response':'{"comparisons":[]}', 'done_reason':'stop',
            'choices':[{'message':{'content':'{"comparisons":[]}'},'finish_reason':'stop'}]}
    bodies=[]
    def post(*args,**kwargs):bodies.append(deepcopy(kwargs['json']));return Response()
    monkeypatch.setattr('common.llm_client.requests.post',post)
    monkeypatch.setattr('common.llm_client._cloud_rate_limiter.wait',lambda:None)
    client=LLMClient(provider=provider,model='fixture-model',api_key='test-credential-must-not-be-traced')
    with capture_generation() as events:
        client.generate('exact prompt',max_tokens=4096,response_format={'type':'json_schema','json_schema':{'schema':finding.SCHEMA}})
    request=next(e for e in events if e.get('event_type')=='request')
    assert request['request_payload']==bodies[0]
    assert request['client_truncation']=='none'
    assert 'test-credential-must-not-be-traced' not in json.dumps(events)
    assert any(e.get('finish_reason')=='stop' for e in events)


def test_unrequested_model_does_not_require_worker_transport(monkeypatch):
    """Legacy metadata/no-model use must not gain a worker import dependency."""
    import builtins
    original=builtins.__import__
    def guarded(name,*args,**kwargs):
        if name=='common' or name.startswith('common.'):raise ImportError('worker intentionally absent')
        return original(name,*args,**kwargs)
    monkeypatch.setattr(builtins,'__import__',guarded)
    retriever=Retriever();retriever.collection_names=[]
    result=finding.retrieve_finding_literature([{'finding_id':'none','feature_identity':{'reader_feature_id':'none'}}],
        retriever,{'species':'human'})
    assert result['cost']=={'queries':0,'model_calls':0,'cache_entries':0}
    assert result['records']['none']['status']=='not_searched'
