"""M4 frozen typed execution publication; fixture RAG, no actual model/network."""
from copy import deepcopy
import json
from unittest.mock import patch

import pytest

from ptm_shared.tests.test_astra_evidence_catalog import saved, small, config
from ptm_shared.tests.test_astra_literature_review import setup, TypedModel
from ptm_shared.tests.test_astra_literature import Retriever, selection
from ptm_shared import astra_literature_review as review
from ptm_shared.astra_evidence_catalog import EvidenceCatalog, read_source
from ptm_shared.generic_workflow import object_hash


def execute(tables,catalog,plan,subject_ids,**kwargs):
    with patch('ptm_shared.finding_literature.time.sleep'):
        return review.execute_review(catalog,plan,subject_ids,tables,{},selection(),reason='M4 fixture only',
            max_subjects=len(subject_ids),retriever=Retriever(),llm=TypedModel(),**kwargs)


def test_frozen_projection_preserves_scientific_and_legacy_states(saved):
    root,tables,catalog,plan,_=setup(saved)
    ids=plan.loc[plan.subject_type.isin(['observation','method_result'])].groupby('subject_type').head(1).review_subject_id.tolist()
    before=json.loads(tables['reader/packet'].iloc[0].packet_json)
    pin=execute(tables,catalog,plan,ids)
    summary=review.attach_review_execution(tables,pin,catalog)
    packet=json.loads(tables['reader/packet'].iloc[0].packet_json)
    for key in ('reader_cards','research_question_evidence_map','literature','original_questions'):
        assert packet.get(key)==before.get(key)
    assert summary['requested_scope_status']=='completed' and summary['status']=='partial'
    assert summary['comparison_executed_subjects']==2 and summary['semantically_approved_subjects']==0
    assert summary['external_astra_review_status']=='not_recorded'
    assert len(tables[review.SUBJECT_LINKS[:-4]])>=2
    assert all(r=='review_required' for r in tables[review.EXECUTION[:-4]].semantic_status)
    bad=deepcopy(pin);bad['retrieval']['records'][ids[0]]['record']['coverage'][0]['source_id']='missing'
    bad['sha256']=object_hash({k:v for k,v in bad.items() if k!='sha256'})
    with pytest.raises(ValueError,match='coverage/source FK'):review.project_review(bad,catalog)


def test_runtime_digest_changes_per_subject_cache(saved,tmp_path):
    _,tables,catalog,plan,_=setup(saved);ids=plan.loc[plan.subject_type.eq('observation')].head(1).review_subject_id.tolist()
    a=execute(tables,catalog,plan,ids,settings={'runtime_identity':{'model_digest':'a'}},cache_root=tmp_path)
    b=execute(tables,catalog,plan,ids,settings={'runtime_identity':{'model_digest':'b'}},cache_root=tmp_path)
    assert a['request_hashes']!=b['request_hashes']
    assert b['current_cost']['model_calls']==1


def test_partial_pin_cannot_hide_deferred_status(saved):
    _,tables,catalog,plan,_=setup(saved);ids=plan.loc[plan.subject_type.eq('observation')].head(1).review_subject_id.tolist()
    pin=execute(tables,catalog,plan,ids,settings={'budget':{'max_queries':0}})
    assert pin['deferred_subject_ids']==ids
    pin['deferred_subject_ids']=[];pin['sha256']=object_hash({k:v for k,v in pin.items() if k!='sha256'})
    with pytest.raises(ValueError,match='deferred status'):review.replay_review(pin,catalog)


def test_published_execution_replays_and_failed_scope_preserves_success(config,tmp_path):
    from ptm_shared import astra_evidence_v6 as engine
    from ptm_shared.astra_reader_revision import read_tables,revise_temporal
    from ptm_shared.astra_package import validate_package
    from ptm_shared.annotation_registry import digest
    config['experimental_context']['quantitation_export_mode']='astra_analysis.v6'
    result=engine.run('m4-fixture',config,tmp_path/'source')
    source=tmp_path/'source/enrichment_free_runs'/result['run_id']
    tables=read_tables(source);catalog=EvidenceCatalog(source)
    plan=read_source(source,review.PLAN,catalog.catalog['sources'][review.PLAN])
    ids=plan.loc[plan.subject_type.eq('observation')].head(1).review_subject_id.tolist()
    pin=execute(tables,catalog,plan,ids)
    with patch.object(review,'execute_review',side_effect=AssertionError('frozen publication only')):
        result=revise_temporal(source,tmp_path/'revision',review_execution=pin)
    root=tmp_path/'revision/enrichment_free_runs'/result['run_id']
    assert review.validate_execution(EvidenceCatalog(root))['comparison_executed_subjects']==1
    validate_package(root)
    manifest=json.loads((source/'manifest.json').read_text())
    for name in manifest['files']:
        if name.startswith(('quant/','science/','kinase/','temporal/','figures/','references/')):
            assert digest(source/name)==digest(root/name), name
    assert digest(source/'reader/findings.csv')==digest(root/'reader/findings.csv')
    # Fresh output has no references directory; replay must prepare it and use
    # the archived code without network, not the repository writer.
    import subprocess,sys
    replay=subprocess.run([sys.executable,'scripts/replay_astra_reader.py','--package',str(root),
        '--output',str(tmp_path/'offline-reader')],capture_output=True,text=True)
    assert replay.returncode==0,replay.stdout+replay.stderr
    replay_result=json.loads((tmp_path/'offline-reader/READER_REPLAY_VALIDATION.json').read_text())
    assert replay_result['frozen_typed_literature_rebuilt'] and replay_result['network_requests']==0
    pointer=tmp_path/'revision/enrichment_free_current.json';before=pointer.read_bytes()
    failed=execute(tables,catalog,plan,ids,settings={'budget':{'max_queries':0}})
    with pytest.raises(ValueError,match='Incomplete requested'):
        revise_temporal(source,tmp_path/'revision',review_execution=failed)
    assert pointer.read_bytes()==before
    def reject_at_pointer():
        if list((tmp_path/'revision').glob('.astra_current_*.json')):raise ValueError('offline gate fixture failed')
    with pytest.raises(ValueError,match='offline gate fixture failed'):
        revise_temporal(source,tmp_path/'revision',review_execution=pin,checkpoint=reject_at_pointer)
    assert pointer.read_bytes()==before
    with patch('ptm_shared.astra_package.seal_archive',side_effect=ValueError('seal fixture failed')):
        with pytest.raises(ValueError,match='seal fixture failed'):
            revise_temporal(source,tmp_path/'revision',review_execution=pin)
    assert pointer.read_bytes()==before
