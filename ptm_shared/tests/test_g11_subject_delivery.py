"""Frozen subject delivery boundaries. Static scientific rows; fixture RAG only."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
from unittest.mock import patch

import pandas as pd
import pytest

from ptm_shared.tests.test_astra_evidence_catalog import saved, small
from ptm_shared.tests.test_astra_science import config
from ptm_shared.tests.test_astra_literature_review import setup, TypedModel
from ptm_shared.tests.test_astra_literature import Retriever, selection
from ptm_shared import astra_literature_review as review
from ptm_shared.astra_evidence_catalog import EvidenceCatalog, write_evidence_access
from ptm_shared.astra_package import write_tables
from ptm_shared.generic_workflow import json_write, object_hash
from ptm_shared.annotation_registry import digest


@pytest.fixture
def frozen(saved,tmp_path):
    root,tables,catalog,plan,links=setup(saved)
    links['link_id']=['fixture_link_'+str(i) for i in range(len(links))]
    tables['reader/full_question_links']=links
    tables['evidence/emergence_evidence']['contrast_id']='one_base'
    dictionary=json.loads((root/'reproducibility/data_dictionary.json').read_text())
    dictionary.update(write_tables({k:tables[k] for k in ['reader/full_question_links','evidence/emergence_evidence']},root))
    json_write(root/'reproducibility/data_dictionary.json',dictionary)
    write_evidence_access(root);catalog=EvidenceCatalog(root)
    ids=plan.loc[plan.subject_type.isin(['observation','method_result'])].groupby('subject_type').head(1).review_subject_id.tolist()
    with patch('ptm_shared.finding_literature.time.sleep'):
        pin=review.execute_review(catalog,plan,ids,tables,{},selection(),reason='fixture only',
            max_subjects=len(ids),retriever=Retriever(),llm=TypedModel())
    run='g0-'+'a'*32;output=tmp_path/'order';source=output/'enrichment_free_runs'/run
    shutil.copytree(root,source)
    (source/'references').mkdir(exist_ok=True)
    (root/'references').mkdir(exist_ok=True)
    json_write(source/review.EXECUTION_PIN,pin)
    json_write(source/'provenance.json',{'run_id':run})
    json_write(source/'reproducibility/replay_config.json',{'snapshot':{},'literature':selection()})
    json_write(source/'manifest.json',{'files':{review.EXECUTION_PIN:{'sha256':digest(source/review.EXECUTION_PIN),'bytes':(source/review.EXECUTION_PIN).stat().st_size}}})
    request={'mode':'reuse_frozen','requested_subject_ids':ids,'request_reason':'explicit frozen fixture',
        'max_subjects':len(ids),'budget':pin['execution_contract']['budget'],'pin_ref':{'run_id':run,'sha256':pin['sha256']}}
    return root,tables,catalog,pin,request,source,output


def test_frozen_delivery_is_summary_independent_and_has_zero_runtime_calls(frozen):
    root,tables,catalog,pin,request,source,output=frozen
    for maximum in [0,5,15,50]:
        variant=deepcopy(tables);packet=json.loads(variant['reader/packet'].iloc[0].packet_json)
        packet['reader_cards']=packet['reader_cards'][:maximum]
        variant['reader/findings']=variant['reader/findings'].iloc[:maximum]
        variant['reader/packet'].loc[:,'packet_json']=json.dumps(packet)
        with patch.object(review,'execute_review',side_effect=AssertionError('no new execution')),patch('ptm_shared.astra_literature._runtime',side_effect=AssertionError('no runtime')):
            result,binding=review.run_requested_review(root,variant,{review.REQUEST_FIELD:request},{},selection(),output_root=output,run_id='consumer')
        assert result==pin and binding['current_cost']=={'queries':0,'model_calls':0}
        assert binding['source_run_id']==source.name and binding['consumer_run_id']=='consumer'
        assert binding['requested_scope_status']=='completed' and binding['whole_scope_status']=='partial'
        assert variant[review.EXECUTION[:-4]].review_subject_id.tolist()==request['requested_subject_ids']


def test_invalid_request_source_scope_and_frozen_provenance_fail_closed(frozen):
    root,tables,catalog,pin,request,source,output=frozen
    for patch_value in [{'mode':'other'},{'pin_ref':{'run_id':'../../outside','sha256':'f'*64}},
                        {'budget':{'max_queries':-1}},{'path':'/unregistered.json'}]:
        with pytest.raises(ValueError):review.review_request({review.REQUEST_FIELD:{**request,**patch_value}})
    with pytest.raises(ValueError,match='hash mismatch'):
        review.registered_execution(output,{**request['pin_ref'],'sha256':'f'*64})
    def check(value):return review.validate_frozen_request(value,request,catalog,tables,{},selection(),source)
    for kind,message in [('hash','pin mismatch'),('source','value mismatch'),('fk','FK mismatch')]:
        bad=deepcopy(pin)
        if kind=='hash':bad['sha256']='bad'
        elif kind=='source':bad['source_value_hashes'][request['requested_subject_ids'][0]]='bad'
        else:bad['subject_evidence'].pop(request['requested_subject_ids'][0])
        if kind!='hash':bad['sha256']=object_hash({k:v for k,v in bad.items() if k!='sha256'})
        with pytest.raises(ValueError,match=message):check(bad)
    changed=selection();changed['documents']=[{'sha256':'f'*64}]
    with pytest.raises(ValueError,match='selection/corpus'):
        review.validate_frozen_request(pin,request,catalog,tables,{},changed,source)


def test_incomplete_request_preserves_previous_pointer_and_unrequested_is_noop(frozen):
    root,tables,catalog,pin,request,source,output=frozen
    pointer=output/'enrichment_free_current.json';pointer.write_text('old success')
    sid=request['requested_subject_ids'][0]
    pin=deepcopy(pin);pin['retrieval']['records'][sid]['execution_status']='budget_deferred';pin['deferred_subject_ids']=[sid]
    pin['sha256']=object_hash({k:v for k,v in pin.items() if k!='sha256'})
    json_write(source/review.EXECUTION_PIN,pin)
    json_write(source/'manifest.json',{'files':{review.EXECUTION_PIN:{'sha256':digest(source/review.EXECUTION_PIN),'bytes':(source/review.EXECUTION_PIN).stat().st_size}}})
    request['pin_ref']['sha256']=pin['sha256']
    with pytest.raises(ValueError,match='Incomplete requested'):
        review.run_requested_review(root,tables,{review.REQUEST_FIELD:request},{},selection(),output_root=output,run_id='failed')
    assert pointer.read_text()=='old success'
    assert review.run_requested_review(root,tables,{},None,None,output_root=output,run_id='unused')==(None,None)


def test_required_execution_cannot_silently_disappear(frozen):
    root,tables,catalog,pin,request,source,output=frozen
    with pytest.raises(ValueError,match='Required literature subject execution pin missing'):
        review.validate_execution(catalog,required=True)
    assert review.validate_execution(catalog)['available'] is False


def test_normal_writer_restore_and_mandatory_artifacts(frozen):
    from ptm_shared.astra_reader import write_reader
    root,tables,catalog,pin,request,source,output=frozen
    review.run_requested_review(root,tables,{review.REQUEST_FIELD:request},{},selection(),output_root=output,run_id='consumer')
    dictionary=json.loads((root/'reproducibility/data_dictionary.json').read_text())
    dictionary.update(write_tables({'reader/packet':tables['reader/packet']},root))
    json_write(root/'reproducibility/data_dictionary.json',dictionary)
    json_write(root/'provenance.json',{'run_id':'consumer'})
    with patch.object(review,'execute_review',side_effect=AssertionError('writer may not execute')):
        artifacts=write_reader(root,tables,review_execution=pin)
    assert set(review.EXECUTION_ARTIFACTS)<=set(artifacts)
    catalog=EvidenceCatalog(root)
    assert review.validate_execution(catalog,required=True)['requested_scope_status']=='completed'
    (root/'study').mkdir(exist_ok=True)
    json_write(root/'study/study_context.json',{review.REQUEST_FIELD:request})
    assert review.validate_execution(catalog,required=True)['requested_scope_status']=='completed'
    bad=deepcopy(request);bad['requested_subject_ids']=bad['requested_subject_ids'][:1]
    json_write(root/'study/study_context.json',{review.REQUEST_FIELD:bad})
    with pytest.raises(ValueError,match='context/request'):review.validate_execution(catalog,required=True)
    json_write(root/'study/study_context.json',{review.REQUEST_FIELD:request})
    stored=(root/review.BINDING).read_bytes();(root/review.BINDING).unlink()
    with pytest.raises(ValueError,match='binding missing'):review.validate_execution(catalog,required=True)
    (root/review.BINDING).write_bytes(stored)
    for name in review.EXECUTION_ARTIFACTS:
        path=root/name;data=path.read_bytes();path.unlink()
        with pytest.raises(ValueError,match='missing'):review.validate_execution(catalog,required=True)
        path.write_bytes(data)
    fresh={'reader/packet':tables['reader/packet'].copy()}
    assert review.restore_execution(fresh,root)==pin
    assert fresh['reader/packet'].iloc[0].packet_json==tables['reader/packet'].iloc[0].packet_json
    review.restore_execution(fresh,root,consumer_run_id='revision')
    binding=json.loads(fresh['reader/packet'].iloc[0].packet_json)['literature_subject_execution']['binding']
    assert binding['consumer_run_id']=='revision' and binding['source_run_id']==source.name


def test_explicit_execution_is_called_only_at_requested_stage(frozen):
    root,tables,catalog,pin,request,source,output=frozen
    requested={k:v for k,v in request.items() if k!='pin_ref'};requested['mode']='execute'
    with patch.object(review,'execute_review',return_value=pin) as execute:
        result,binding=review.run_requested_review(root,tables,{review.REQUEST_FIELD:requested},{},selection(),output_root=output,run_id='explicit-consumer')
        assert execute.call_args.kwargs['run_id']=='explicit-consumer'
    assert execute.call_count==1 and execute.call_args.kwargs['settings']['budget']==requested['budget']
    assert result==pin and binding['source_run_id']=='explicit-consumer' and binding['effective_mode']=='explicit_execution'


def test_ordinary_replay_forwards_pin_without_running_science(frozen,tmp_path):
    from ptm_shared import astra_package as package
    from ptm_shared.astra_reader import write_reader
    root,tables,catalog,pin,request,source,output=frozen
    review.run_requested_review(root,tables,{review.REQUEST_FIELD:request},{},selection(),output_root=output,run_id='consumer')
    fields=[{'source_field_path':'fixture'}];tables['study/input_field_manifest']=pd.DataFrame(fields)
    dictionary=write_tables(tables,root);json_write(root/'reproducibility/data_dictionary.json',dictionary)
    write_reader(root,tables,review_execution=pin)
    json_write(root/'references/source_pin.json',{})
    design=json.loads(tables['reader/packet'].iloc[0].packet_json)['canonical_study_design']
    json_write(root/'reproducibility/replay_config.json',{'engine_profile':'astra_analysis.v6','inputs':{},'design':design,'context':{},'snapshot':{},'literature':selection()})
    # This is a forwarding boundary test, not numerical replay or package
    # integrity validation. The actual archive checks run in the g11 integration.
    class WriterReached(Exception):pass
    def checked_writer(directory,frames,**kwargs):
        assert kwargs['review_execution']==pin
        assert kwargs['source_root']==root.resolve()
        assert frames[review.EXECUTION[:-4]].review_subject_id.tolist()==pin['requested_subject_ids']
        raise WriterReached
    with patch.object(package,'validate_package'),patch.object(package,'compute_science',return_value=(deepcopy(tables),)),\
         patch.object(package,'transfer_contract',return_value=(fields,None,None)),patch.object(package,'validate_science'),\
         patch.object(package,'write_tables'),\
         patch('ptm_shared.astra_reader.write_reader',side_effect=checked_writer),\
         patch.object(review,'execute_review',side_effect=AssertionError('no calculation')):
        with pytest.raises(WriterReached):package.replay_package(root,tmp_path/'ordinary-replay')


def test_frozen_inventory_mapping_is_not_current_corpus_cache_permission():
    frozen={'collections':[{'version':'a','version_scope':'immutable_index_snapshot'}],
        'documents':[{'document_id':1,'sha256':'a'*64}]}
    current={'collections':[{'version':'catalog-date','version_scope':'catalog_updated_at'}],
        'documents':[{'document_id':99,'sha256':'a'*64}]}
    match=review.frozen_selection_match(frozen,current)
    assert match['new_execution_cache_compatible'] is False and match['current_index_verified'] is False
    current['collections']=[{'version':'different','version_scope':'immutable_index_snapshot'}]
    with pytest.raises(ValueError,match='immutable corpus'):review.frozen_selection_match(frozen,current)


def test_request_only_changes_literature_dependency(config):
    from ptm_shared.astra_evidence_v6 import resolve_plan
    # Fingerprinting is pure; no quantification or scientific method runs.
    context=config['experimental_context']
    before=resolve_plan(context)
    after=resolve_plan({**context,review.REQUEST_FIELD:{'mode':'execute','requested_subject_ids':['review_subject_'+'a'*20]}})
    assert before['fingerprints']==after['fingerprints']
