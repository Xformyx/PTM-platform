"""Finding/source joins, evidence boundaries and immutable literature replay."""
import copy
import json
from unittest.mock import patch
import pandas as pd
import pytest
from ptm_shared.tests.test_astra_card_inputs import small, config
from ptm_shared.tests.test_astra_reader import projected
from ptm_shared.astra_reader import build_reader_tables, validate_reader
from ptm_shared import astra_literature as lit


@pytest.fixture
def reader(small):
    tables,design=projected(small)
    snapshot={'original':{'species':'human','analysis_context':{'species':'human','cell_type':'recorded model',
        'biological_question':'完整 질문\nDo PTM and protein differ?'},'report_options':{'research_questions':['Compare published evidence']}}}
    tables.update(build_reader_tables(tables,design,snapshot))
    return tables,design,snapshot


def selection(permission='permitted'):
    return {'selection':'explicit','requested_ids':[1], 'collections':[{'id':1,'name':'Display only',
             'chromadb_name':'pinned_collection','version':'frozen-1','version_scope':'immutable_index_snapshot','evidence_export_permission':permission}], 'documents':[]}


class Retriever:
    collection_names=['pinned_collection']
    def __init__(self, fail=False):self.calls=[];self.fail=fail
    def query_for_purpose(self,q,*,purpose,n_results,strict):
        self.calls.append((purpose,q))
        if self.fail:raise RuntimeError('test service unavailable')
        return [{'title':'Synthetic source only','doi':'10.1000/fixture','authors':'Fixture','year':'2026',
            'document':f'SameLabel S2 increased in human cells after insulin at 30min. {"Opposite condition" if purpose=="counterevidence" else "Primary condition"}.',
            'collection':'pinned_collection','collection_version':'frozen-1','source_id':'negative' if purpose=='counterevidence' else 'positive',
            'metadata':{'section':'Results','chunk_index':2,'content_scope':'full_text_excerpt'}}]


class Model:
    provider='fixture';model='fixture-model'
    def __init__(self,relation='known_agreement'):self.relation=relation;self.prompts=[]
    def generate(self,prompt,**kwargs):
        self.prompts.append(prompt)
        data=json.loads(prompt[prompt.index('{'):])
        assert data['observation']['source_bindings'][0]['U_all']==3
        assert data['observation']['source_bindings'][0]['U_joint']==2
        assert data['observation']['trajectory'][1]['ptm_protein_adjusted_log2fc'] is None
        assert data['study']['original_questions']['biological_question'].startswith('完整')
        quote='SameLabel S2 increased in human cells after insulin at 30min.'
        return json.dumps({'comparisons':[{'source_index':0,'quote':quote,'external_finding':'S2 increased',
            'reference_scope':'gene','relationship':self.relation,'species':'human','cell_type':'human cells',
            'insulin_dose':'','time':'30min','readout':'','perturbation':'insulin'}]})


@pytest.mark.parametrize('relation',['known_agreement','disagreement','context_difference'])
def test_existing_retrieval_comparison_and_identity_scope(reader,tmp_path,relation):
    tables,design,snapshot=reader;before={k:v.copy(deep=True) for k,v in tables.items()}
    rag=Retriever();model=Model(relation)
    with patch('ptm_shared.finding_literature.time.sleep'):
        pin=lit.collect(tables,snapshot,selection(),retriever=rag,llm=model,cache_root=tmp_path)
    summary=lit.apply(tables,pin,snapshot,selection())
    assert len(tables['reader/literature_search'])==6 # same gene, multiple references/taxa remain distinct
    assert {p for p,q in rag.calls}=={'literature_background','gene_function_context','direct_site_evidence','counterevidence'}
    assert summary['source_chunks_read']==2 and summary['publications_read']==1
    assert summary['anchored_proposals']==6
    for c in tables['reader/literature_comparisons'].comparison_json.map(json.loads):
        assert c['proposed_relationship']==relation and c['relationship']=='literature_background'
        assert not c['measured_relation'] and c['claim_support_status']=='not_verified'
        assert c['finding_id'] in set(tables['reader/findings'].finding_id)
    for name,df in before.items():
        if name!='reader/packet':pd.testing.assert_frame_equal(df,tables[name])
    validate_reader(tables)
    # Reconstruct with no retrieval or model; values/order/reasons exactly preserved.
    replay=copy.deepcopy(before)
    with patch.object(lit,'retrieve_finding_literature',side_effect=AssertionError('no network on replay')):
        lit.apply(replay,pin,snapshot,selection())
    for name in ['reader/packet',*lit.TABLE_KEYS]:pd.testing.assert_frame_equal(tables[name],replay[name])
    # Identical full request/resource/config can reuse the existing checkpoint cache.
    with patch.object(lit,'retrieve_finding_literature',side_effect=AssertionError('cached')):
        again=lit.collect(before,snapshot,selection(),retriever=Retriever(),llm=Model(relation),cache_root=tmp_path)
    assert again['cache']['status']=='reused'
    assert again['retrieval']==pin['retrieval']


def test_empty_unresolved_failure_and_export_permission_are_separate(reader):
    tables,_,snapshot=reader
    for selected,reason in [({'requested_ids':[],'collections':[]},'explicit_empty_selection'),
            ({'requested_ids':None,'collections':[]},'no_active_collections_in_frozen_selection'),
            ({'collections':[{'name':'Display only','version':'v1'}]},'pinned_collection_search_name_missing')]:
        pin=lit.collect(tables,snapshot,selected)
        assert all(r['reason']==reason and r['status']=='not_searched' for r in pin['retrieval']['records'].values())
    with patch('ptm_shared.finding_literature.time.sleep'):
        failed=lit.collect(tables,snapshot,selection(),retriever=Retriever(True))
        restricted=lit.collect(tables,snapshot,selection('unknown'),retriever=Retriever(),llm=Model())
    assert {r['status'] for r in failed['retrieval']['records'].values()}=={'retrieval_failed'}
    assert restricted['retrieval']['cost']['queries']>0
    assert all(r['export_status']=='metadata_only_export_permission_unconfirmed' and 'document' not in r for r in restricted['retrieval']['references'])
    assert all('resolved_prompt' not in r and 'comparison_generation' not in r for r in restricted['retrieval']['records'].values())
    lit.apply(tables,restricted,snapshot,selection('unknown'))
    assert tables['reader/literature_comparisons'].empty
    packet=json.loads(tables['reader/packet'].iloc[0].packet_json)
    assert packet['literature_comparison_status']=='internal_comparison_performed_export_restricted'
    assert packet['literature']['summary']['internal_compared_findings']==6


def test_stale_pin_source_tamper_selection_and_row_join_fail_closed(reader):
    tables,_,snapshot=reader;selected={'collections':[]}
    pin=lit.collect(tables,snapshot,selected)
    broken=copy.deepcopy(pin);broken['retrieval']['records'].pop(next(iter(broken['retrieval']['records'])))
    with pytest.raises(ValueError,match='pin hash'):lit.apply(tables,broken,snapshot,selected)
    changed=copy.deepcopy(snapshot);changed['original']['analysis_context']['cell_type']='different study'
    with pytest.raises(ValueError,match='input mismatch'):lit.apply(tables,pin,changed,selected)
    tables['reader/findings']=tables['reader/findings'].iloc[::-1].reset_index(drop=True)
    with pytest.raises(ValueError,match='input mismatch|order'):lit.apply(tables,pin,snapshot,selected)


def test_live_order_condition_key_order_matches_archived_replay(reader):
    tables,_,snapshot=reader
    snapshot['original']['analysis_context']['pre_treatment']={'name':'recorded starvation','unit':'h','duration':12}
    selected={'collections':[]}
    pin=lit.collect(tables,snapshot,selected)
    archived=json.loads(json.dumps(snapshot,sort_keys=True))
    lit.apply(tables,pin,archived,selected)
    changed=copy.deepcopy(archived)
    changed['original']['analysis_context']['pre_treatment']['duration']=6
    with pytest.raises(ValueError,match='input mismatch'):
        lit.apply(tables,pin,changed,selected)


def test_v6_package_calls_existing_transport_and_revision_replays_without_science(config,tmp_path):
    from ptm_shared import astra_evidence_v6 as engine
    from ptm_shared.astra_reader_revision import revise_literature
    from ptm_shared.astra_package import validate_package
    from scripts.replay_astra_reader import PROGRAM
    import subprocess,sys,os
    class ContextModel:
        provider='fixture';model='context-fixture'
        def generate(self,prompt,**kwargs):
            return json.dumps({'comparisons':[{'source_index':0,
                'quote':'SameLabel S2 increased in human cells after insulin at 30min.',
                'external_finding':'increased in human cells','reference_scope':'study','relationship':'context_difference',
                'species':'human','cell_type':'human cells','insulin_dose':'','time':'30min','readout':'','perturbation':'insulin'}]})
    config['experimental_context']['quantitation_export_mode']='astra_analysis.v6'
    config['literature_pin']=selection()
    rag=Retriever();model=ContextModel()
    with patch.object(lit,'_runtime',return_value=(rag,model,{'provider':model.provider,'model':model.model,'status':'injected_fixture'})), \
         patch('ptm_shared.finding_literature.time.sleep'),patch.object(lit,'collect',wraps=lit.collect) as spy:
        run=engine.run('round08-synthetic',config,tmp_path/'out')
    assert spy.call_count==1 and rag.calls
    root=tmp_path/'out/enrichment_free_runs'/run['run_id'];validate_package(root)
    initial=pd.read_csv(root/'reader/findings.csv')
    assert run['analysis_readiness']['literature']['anchored_proposals']>0
    # Resource-only v6 execution may explicitly reuse an integrity-checked pin;
    # it must never retry an LLM comparison simply because prior review is pending.
    config['finding_literature_pin']=json.loads((root/'references/finding_literature_pin.json').read_text())
    with patch.object(lit,'collect',side_effect=AssertionError('frozen literature must not run retrieval')):
        reused=engine.run('round08-synthetic',config,tmp_path/'frozen')
    reused_root=tmp_path/'frozen/enrichment_free_runs'/reused['run_id']
    assert (reused_root/'references/finding_literature_pin.json').read_bytes()==(root/'references/finding_literature_pin.json').read_bytes()
    pointer=tmp_path/'frozen/enrichment_free_current.json';saved=pointer.read_bytes()
    config['finding_literature_pin']['sha256']='0'*64
    with patch.object(lit,'collect',side_effect=AssertionError('no fallback retrieval')),pytest.raises(ValueError,match='pin hash'):
        engine.run('round08-synthetic',config,tmp_path/'frozen')
    assert pointer.read_bytes()==saved
    config.pop('finding_literature_pin')
    # A package revision reuses all scientific tables and frozen finding IDs.
    with patch('ptm_shared.astra_package.compute_science',side_effect=AssertionError('science forbidden')), \
         patch('ptm_shared.astra_package.resolve_sources',side_effect=AssertionError('source refresh forbidden')), \
         patch('ptm_shared.astra_reader.build_reader_tables',side_effect=AssertionError('selection forbidden')), \
         patch.object(lit,'_runtime',return_value=(rag,model,{'provider':model.provider,'model':model.model,'status':'injected_fixture'})), \
         patch('ptm_shared.finding_literature.time.sleep'):
        revised=revise_literature(root,tmp_path/'revision')
    target=tmp_path/'revision/enrichment_free_runs'/revised['run_id']
    pd.testing.assert_frame_equal(initial,pd.read_csv(target/'reader/findings.csv'))
    dictionary=json.loads((root/'reproducibility/data_dictionary.json').read_text())
    for name in dictionary:
        if name=='reader/packet.csv' or name[:-4] in lit.TABLE_KEYS:continue
        assert (root/name).read_bytes()==(target/name).read_bytes()
    env={k:v for k,v in os.environ.items() if k!='PYTHONPATH'}
    process=subprocess.run([sys.executable,'-I','-c',PROGRAM,str(target),str(tmp_path/'offline')],cwd='/tmp',env=env,capture_output=True,text=True)
    assert process.returncode==0,process.stdout+process.stderr
    result=json.loads((tmp_path/'offline/READER_REPLAY_VALIDATION.json').read_text())
    assert result['passed'] and result['network_requests']==0 and len(result['files'])==18
    # Failed validation cannot publish a new current pointer.
    pointer=tmp_path/'revision/enrichment_free_current.json';before=pointer.read_bytes()
    with patch.object(lit,'collect',side_effect=ValueError('injected integrity failure')):
        with pytest.raises(ValueError,match='integrity failure'):revise_literature(root,tmp_path/'revision')
    assert pointer.read_bytes()==before


def test_existing_indexer_doc_id_keeps_permission_and_read_scope(reader):
    tables,_,snapshot=reader
    selected=selection('unknown')
    selected['documents']=[{'document_id':8,'filename':'fixture.txt','source_status':'indexed',
        'content_status':'full_text_included','evidence_export_permission':'permitted'}]
    class Indexed(Retriever):
        def query_for_purpose(self,*args,**kwargs):
            hits=super().query_for_purpose(*args,**kwargs)
            for hit in hits:hit['metadata'].update(doc_id=8,collection_id=1)
            return hits
    with patch('ptm_shared.finding_literature.time.sleep'):
        pin=lit.collect(tables,snapshot,selected,retriever=Indexed(),llm=Model())
    assert all(r['export_status']=='evidence_excerpt_included' for r in pin['retrieval']['references'])
    assert pin['documents'][0]['read_scope']=='retrieved_chunks_only'
    lit.apply(tables,pin,snapshot,selected)
    assert len(tables['reader/literature_comparisons'])==6
    assert lit._document_id({'doc_id':8,'document_id':9}) is None


def test_explicit_selection_revision_preserves_default_and_replay(config,tmp_path):
    from ptm_shared import astra_evidence_v6 as engine
    from ptm_shared.astra_reader_revision import revise_literature
    from scripts.replay_astra_reader import PROGRAM
    import subprocess,sys,os
    config['experimental_context']['quantitation_export_mode']='astra_analysis.v6'
    config['literature_pin']={'schema_version':'selected_literature_pin.v1','selection':'explicit','requested_ids':[], 'collections':[], 'documents':[]}
    run=engine.run('selection-test',config,tmp_path/'base')
    base=tmp_path/'base/enrichment_free_runs'/run['run_id']
    original=(base/'references/literature_pin.json').read_bytes()
    default=revise_literature(base,tmp_path/'default')
    assert (tmp_path/'default/enrichment_free_runs'/default['run_id']/'references/literature_pin.json').read_bytes()==original
    pin={**selection(),'schema_version':'selected_literature_pin.v1','selection_provenance':{'source_environment':'fixture-origin','destination_environment':'fixture-local'}}
    with pytest.raises(ValueError,match='requires a reason'):revise_literature(base,tmp_path/'invalid',literature_pin=pin)
    with pytest.raises(ValueError,match='requires an explicit'):revise_literature(base,tmp_path/'invalid',refresh_reason='missing pin')
    rag=Retriever()
    with patch('ptm_shared.finding_literature.time.sleep'):
        revised=revise_literature(base,tmp_path/'updated',literature_pin=pin,refresh_reason='explicit local mapping',retriever=rag)
    target=tmp_path/'updated/enrichment_free_runs'/revised['run_id']
    assert rag.calls  # no reuse of the old empty-selection result
    replay_config=json.loads((target/'reproducibility/replay_config.json').read_text())
    assert replay_config['literature']==pin and replay_config['snapshot']['original']['rag_collections']==[1]
    assert revised['provenance']['literature_pin_hash']==lit.object_hash(pin)
    assert revised['provenance']['literature_selection_revision']['previous_selection']['requested_ids']==[]
    assert json.loads((target/'study/study_context.json').read_text())['literature_context']['selected_collection_ids']==[1]
    for p in base.rglob('*.csv'):
        rel=p.relative_to(base)
        if str(rel) in {'reader/packet.csv','study/input_field_manifest.csv',*(k+'.csv' for k in lit.TABLE_KEYS)}:continue
        assert p.read_bytes()==(target/rel).read_bytes(),str(rel)
    env={k:v for k,v in os.environ.items() if k!='PYTHONPATH'}
    p=subprocess.run([sys.executable,'-I','-c',PROGRAM,str(target),str(tmp_path/'offline-new-selection')],cwd='/tmp',env=env,capture_output=True,text=True)
    assert p.returncode==0,p.stdout+p.stderr
    assert (base/'references/literature_pin.json').read_bytes()==original
    pointer=tmp_path/'updated/enrichment_free_current.json';previous=pointer.read_bytes()
    with patch.object(lit,'collect',side_effect=RuntimeError('injected search boundary failure')):
        with pytest.raises(RuntimeError):revise_literature(base,tmp_path/'updated',literature_pin=pin,refresh_reason='retry')
    assert pointer.read_bytes()==previous


def test_lossless_prompt_design_reference_and_execution_audit(reader):
    import hashlib
    tables,_,snapshot=reader
    canonical=json.loads(tables['reader/packet'].iloc[0].packet_json)['canonical_study_design']
    snapshot['original']['analysis_context']['study_design']=copy.deepcopy(canonical)
    for equal in [True,False]:
        if not equal:snapshot['original']['analysis_context']['study_design']['audit_note']='distinct record'
        with patch('ptm_shared.finding_literature.time.sleep'):
            pin=lit.collect(tables,snapshot,selection(),retriever=Retriever(),llm=Model())
        for record in pin['retrieval']['records'].values():
            raw=record['resolved_prompt'];payload=json.loads(raw[raw.index('{'):])
            assert ('study_design' not in payload['study'])==equal
            assert payload['study']['canonical_study']==canonical
            def expand(value):
                if isinstance(value,dict):
                    if set(value)=={'$observation_ref'}:return payload['observation_definitions'][value['$observation_ref']]
                    return {k:expand(v) for k,v in value.items()}
                return [expand(v) for v in value] if isinstance(value,list) else value
            assert expand(payload['observation'])==record['search_input']['observation']
            assert record['comparison_execution']['status']=='completed'
            assert record['comparison_execution']['output_sha256']==hashlib.sha256(record['comparison_generation']['provider_raw_text'].encode()).hexdigest()


def test_published_pin_reuses_executed_comparison_without_network_or_semantic_promotion(reader):
    tables,_,snapshot=reader
    settings={'llm_provider':'fixture','llm_model':'fixture-model'}
    with patch('ptm_shared.finding_literature.FINDING_RETRIEVAL_BACKOFF_SECONDS',0):
        pin=lit.collect(tables,snapshot,selection(),settings=settings,retriever=Retriever(),llm=Model())
    frozen=copy.deepcopy(pin)
    with patch.object(lit,'_runtime',side_effect=AssertionError('No runtime access on matching frozen pin')):
        out=lit.collect(tables,snapshot,selection(),settings=settings,frozen_pin=pin)
    assert out==frozen
    assert settings['_literature_reuse']['current_queries']==0
    assert all(c.get('claim_support_status')!='verified' for r in out['retrieval']['references'] for c in r.get('feature_comparisons',[]))
    # A changed question or requested model cannot inherit the old comparison.
    changed=copy.deepcopy(snapshot);changed['original']['analysis_context']['biological_question']='Changed question'
    with patch.object(lit,'_runtime',side_effect=RuntimeError('new collection required')):
        with pytest.raises(RuntimeError,match='new collection'):
            lit.collect(tables,changed,selection(),settings=settings,frozen_pin=pin)
        with pytest.raises(RuntimeError,match='new collection'):
            lit.collect(tables,snapshot,selection(),settings={**settings,'llm_model':'new-model'},frozen_pin=pin)
    broken=copy.deepcopy(pin);next(iter(broken['retrieval']['records'].values()))['comparison_execution']={'status':'failed'}
    broken['sha256']=lit.object_hash({k:v for k,v in broken.items() if k!='sha256'})
    with patch.object(lit,'_runtime',side_effect=RuntimeError('retry failed execution')):
        with pytest.raises(RuntimeError,match='retry failed'):
            lit.collect(tables,snapshot,selection(),settings=settings,frozen_pin=broken)


def test_prompt_projection_roundtrips_repeated_masks_without_dropping_observations():
    from ptm_shared.finding_literature import _prompt_observation
    mask={'runs':['injection_'+str(i) for i in range(30)],'values':[None,0,2.3],'same_injection':True}
    observation={'source_bindings':[mask], 'trajectory':[{'time_minutes':t,'quality':mask,'A':a} for t,a in [(1,0),(5,None),(180,-2)]]}
    projected,definitions=_prompt_observation(observation)
    def expand(value):
        if isinstance(value,dict):
            if set(value)=={'$observation_ref'}:return definitions[value['$observation_ref']]
            return {k:expand(v) for k,v in value.items()}
        return [expand(v) for v in value] if isinstance(value,list) else value
    assert definitions and expand(projected)==observation
    assert projected['source_bindings']==observation['source_bindings']
    assert len(json.dumps([projected,definitions])) < len(json.dumps(observation))


def test_reader_change_can_reuse_only_hash_bound_identical_execution():
    import hashlib
    from pathlib import Path
    source=Path(lit.__file__).read_text()
    prior=source.replace("'compared_no_supported_relationship'", "'old_reader_label'")
    contract=lit._execution_contract({}, {})
    old=copy.deepcopy(contract);old['code']['astra_literature.py']=hashlib.sha256(prior.encode()).hexdigest()
    assert lit._compatible_contract(old,contract,prior)
    assert not lit._compatible_contract(old,contract,None)
    assert not lit._compatible_contract(old,contract,prior+'# unbound bytes')
    changed=prior.replace("'raw_observation_never_present'", "'unused'").replace("'retrieved_chunks_only'", "'invented_full_text'")
    old['code']['astra_literature.py']=hashlib.sha256(changed.encode()).hexdigest()
    assert not lit._compatible_contract(old,contract,changed)


def test_completed_empty_comparison_is_not_pending(reader):
    tables,_,snapshot=reader
    class EmptyModel(Model):
        def generate(self,*args,**kwargs):return '{"comparisons":[]}'
    with patch('ptm_shared.finding_literature.FINDING_RETRIEVAL_BACKOFF_SECONDS',0):
        pin=lit.collect(tables,snapshot,selection(),retriever=Retriever(),llm=EmptyModel())
    summary=lit.apply(tables,pin,snapshot,selection())
    assert summary['comparison_executed_findings']==summary['selected_findings']
    assert summary['status']=='compared_no_supported_relationship'
    assert summary['semantically_verified_comparable_findings']==0


def test_repeated_reader_revision_keeps_original_literature_execution_proof(reader,tmp_path):
    from pathlib import Path
    import hashlib
    from ptm_shared.astra_package import finding_execution_code
    tables,_,snapshot=reader
    current=Path(lit.__file__).read_text()
    old=current.replace("'compared_no_supported_relationship'", "'prior_reader_label'")
    with patch('ptm_shared.finding_literature.FINDING_RETRIEVAL_BACKOFF_SECONDS',0):
        pin=lit.collect(tables,snapshot,selection(),retriever=Retriever(),llm=Model())
    pin['execution_contract']['code']['astra_literature.py']=hashlib.sha256(old.encode()).hexdigest()
    pin['sha256']=lit.object_hash({k:v for k,v in pin.items() if k!='sha256'})
    runs=tmp_path/'enrichment_free_runs';first=runs/('g1-'+'a'*32);second=runs/('g2-'+'b'*32)
    source=first/'reproducibility/code/ptm_shared/astra_literature.py';source.parent.mkdir(parents=True);source.write_text(old)
    updated=second/'reproducibility/code/ptm_shared/astra_literature.py';updated.parent.mkdir(parents=True);updated.write_text(current)
    proof=finding_execution_code(tmp_path,pin,second.name);assert proof==old
    transported=second/'references/finding_literature_execution.py';transported.parent.mkdir();transported.write_text(proof)
    source.unlink() # the next reuse works from the second package alone
    with patch.object(lit,'_runtime',side_effect=AssertionError('must not re-query on second reuse')):
        again=lit.collect(tables,snapshot,selection(),frozen_pin=pin,frozen_code=finding_execution_code(tmp_path,pin,second.name))
    assert again==pin
    transported.write_text(proof+'# corrupted')
    assert finding_execution_code(tmp_path,pin,second.name) is None
