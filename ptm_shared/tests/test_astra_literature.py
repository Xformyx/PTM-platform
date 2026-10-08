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
    assert result['passed'] and result['network_requests']==0 and len(result['files'])==15
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
