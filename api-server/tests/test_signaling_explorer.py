"""Synthetic real route -> worker -> immutable bundle -> read-only query.

Reference memberships are fixture assertions, not biological validation data.
"""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException
from test_analysis_job_lifecycle import setup_order
from app.api import signaling_explorer as routes
from app.services import production_tmm_executor as executor


def setup_explorer(tmp_path, monkeypatch):
    engine, factory, root, client = setup_order(tmp_path, monkeypatch)
    client.app.include_router(routes.router)
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(OUTPUT_DIR=str(tmp_path)))
    reference = tmp_path/"reference.json"
    reference.write_text(json.dumps({"schema_version":"canonical_pathway_reference.v1", "pathways":[
        {"provider":"Synthetic", "native_id":"pathA", "taxon":"10090", "release":"fixture.v1", "name":"Fixture pathway A", "protein_accessions":["P0","P1","P2","P3"]},
        {"provider":"OtherSynthetic", "native_id":"pathA", "taxon":"10090", "release":"fixture.v1", "name":"Fixture pathway A", "protein_accessions":["P1"]}]}))
    monkeypatch.setenv("PTM_PATHWAY_SOURCE_BUNDLE_PATH", str(reference))
    job = client.post('/orders/1/analysis-jobs', json={}).json()
    asyncio.run(executor.execute_production_tmm(job['job_id'], session_factory=factory))
    runs = client.get('/orders/1/evidence-runs').json()
    bundle = runs['records'][0]['bundle_id']
    return engine, factory, root, client, '/orders/1/evidence-runs/'+bundle


def test_completed_full_inventory_pathway_scope_cursor_values_and_no_writes(tmp_path, monkeypatch):
    engine, _, root, client, base = setup_explorer(tmp_path, monkeypatch)
    before = {str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()}
    manifest = client.get(base).json()
    assert manifest['coverage']['identified_features'] == 4
    assert manifest['coverage']['pathway_mapped_features'] == 4
    assert manifest['revisions']['report'] is None
    pathways = client.get(base+'/pathways').json()
    assert len(pathways['records']) == 2
    key = next(p['pathway_key'] for p in pathways['records'] if p['member_feature_count']==4)
    first = client.get(base+f'/pathways/{key}/members?limit=2').json()
    assert first['total_count']==4 and len(first['records'])==2
    second = client.get(base+f'/pathways/{key}/members', params={'limit':2,'cursor':first['next_cursor']}).json()
    assert {r['feature_id'] for r in first['records']}.isdisjoint(r['feature_id'] for r in second['records'])
    assert client.get(base+'/features', params={'cursor':first['next_cursor']}).status_code == 422
    fid = first['records'][0]['feature_id']
    feature = client.get(base+'/features/'+fid).json()['records'][0]
    assert feature['trajectories']['relative']['5min']==2
    assert len(feature['trajectories']['relative'])==4
    assert feature['observations']['5min']['source']['source_gene_label'].startswith('Rps')
    batched = client.post(base+'/trajectory-query', json={'feature_ids':[fid]}).json()
    assert batched['records'][0] == feature
    assert client.get(base+'/kinases').json()['records'][0]['up_sums']['5min']==8
    for mode in ('global_top_n','per_condition_top_n'):
        selected=client.get(base+'/features',params={'mode':mode,'n':2,'track':'relative'}).json()
        assert selected['total_count']==2 and selected['universe_count']==4
        assert all(len(f['trajectories']['relative'])==4 for f in selected['records'])
    assert client.get(base+'/evidence',params={'feature_id':fid}).json()['total_count']==1
    assert client.get(base+'/artifacts/explorer_records.jsonl').status_code==200
    assert client.get(base+'/artifacts/unknown').status_code==404
    assert client.get(base.replace('/orders/1/','/orders/2/')).status_code==404
    after = {str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()}
    assert before == after, 'Reads, batch trajectories and export must not mutate or compute'
    asyncio.run(engine.dispose())


def test_report_bundle_appends_without_modifying_analysis_or_previous_bundle(tmp_path, monkeypatch):
    engine, _, root, client, base = setup_explorer(tmp_path, monkeypatch)
    from ptm_shared.report_revision import register_revision
    from ptm_shared.run_evidence_bundle import publish_report_bundle
    original=client.get(base).json()
    directory=next(root.glob('.analysis_results/*/*/run_evidence_manifest.json')).parent
    before={p.name:p.read_bytes() for p in directory.iterdir() if p.is_file()}
    source=root/'synthetic-report.md';source.write_text('Synthetic report with pinned input, no biological validation.\n')
    fid=client.get(base+'/features').json()['records'][0]['feature_id']
    packet=root/'authoring.json';packet.write_text(json.dumps({'reader_cards':[{
        'evidence_ids':['observed.F'],'feature_identity':{'feature_id':fid},'claim_tier':'O1'}]}))
    trace=root/'trace.json';trace.write_text(json.dumps({'sections':{'results':{
        'resolved_prompt':'PRIVATE PROMPT MUST NOT BE EXPOSED','structured_decode_audit':[{
        'paragraph_index':0,'evidence_ids':['observed.F'],'retained':True,'value_tokens':['V1']} ]}}}))
    literature=root/'literature.json';literature.write_text(json.dumps({'records':{'f':{
        'feature_id':fid,'status':'source_timeout','retrieved_count':None,
        'resolved_prompt':'PRIVATE RETRIEVAL PROMPT',
        'resolved_prompt_sha256':'synthetic_prompt_hash',
        'comparison_generation':{'provider_raw_text':'PRIVATE RAW MODEL RESPONSE',
            'transport':{'request':'PRIVATE TRANSPORT'}}}},'references':[{
        'reference_id':'pmid:22222','pmid':'22222','title':'Synthetic source', 'feature_comparisons':[{
        'feature_id':fid,'quote':'fixture only','source_sha256':'synthetic_hash','source_offset':5,
        'claim_support_status':'not_verified','quote_status':'exact_span_verified','relationship':'disagreement'}]}]}))
    from ptm_shared.report_revision import file_sha256
    artifacts=[{'path':str(p),'sha256':file_sha256(p),'role':role} for p,role in (
        (packet,'authoring_packet'),(trace,'prose_trace'),(literature,'finding_literature_retrieval'))]
    report=register_revision(root,files=[str(source)],manifest={'artifacts':artifacts},release={'status':'draft_review_required'},
        source_revisions=[{'revision_id':original['revisions']['analysis'],'evidence_bundle_id':original['bundle_id']}])
    derived=publish_report_bundle(root,directory,order_id=1,report_revision=report['revision_id'])
    response=client.get('/orders/1/evidence-runs/'+derived['bundle_id'])
    assert response.status_code==200,response.text
    assert response.json()['revisions']['report']==report['revision_id']
    assert response.json()['revisions']['analysis']==original['revisions']['analysis']
    assert before=={p.name:p.read_bytes() for p in directory.iterdir() if p.is_file()}
    assert len(client.get('/orders/1/evidence-runs').json()['records'])==2
    newbase='/orders/1/evidence-runs/'+derived['bundle_id']
    evidence=client.get(newbase+'/evidence',params={'feature_id':fid}).json()
    assert evidence['total_count']==3  # candidate, observation card, literature assertion
    assertion=next(r for r in evidence['records'] if r['source_type']=='literature_assertion')
    assert assertion['pmid']=='22222' and assertion['claim_support_status']=='not_verified'
    claims=client.get(newbase+'/report-claims',params={'feature_id':fid}).json()
    assert claims['records'][0]['value_tokens']==['V1'] and 'PRIVATE PROMPT' not in json.dumps(claims)
    source_response=client.get(newbase+'/source-runs')
    assert any(r['status']=='source_timeout' for r in source_response.json()['records'])
    assert 'PRIVATE' not in source_response.text
    assert 'synthetic_prompt_hash' in source_response.text
    exported=client.get(newbase+'/inventory-export')
    assert exported.status_code==200 and 'PRIVATE' not in exported.text
    rows=[json.loads(line) for line in exported.text.splitlines()]
    assert rows[0]['bundle_id']==derived['bundle_id']
    assert rows[0]['revisions']==derived['revisions']
    assert {r['record']['feature_id'] for r in rows if r['kind']=='features'}=={
        f['feature_id'] for f in client.get(base+'/features').json()['records']}
    assert sum(r['kind']=='report-claims' for r in rows)==claims['total_count']
    assert sum(r['kind']=='evidence' and r['feature_id']==fid for r in rows)==evidence['total_count']
    first_page=client.get(newbase+'/evidence',params={'feature_id':fid,'limit':1}).json()
    next_page=client.get(newbase+'/evidence',params={'feature_id':fid,'limit':1,'cursor':first_page['next_cursor']}).json()
    assert next_page['records']!=first_page['records']
    assert client.get(base+'/evidence',params={'feature_id':fid,'cursor':first_page['next_cursor']}).status_code==422
    assert publish_report_bundle(root,directory,order_id=1,report_revision=report['revision_id'])==derived
    assert client.get(base+'/evidence',params={'feature_id':fid}).json()['total_count']==1
    asyncio.run(engine.dispose())


def test_scope_authorization_and_tampered_artifact_are_rejected(tmp_path, monkeypatch):
    engine, _, root, client, base = setup_explorer(tmp_path, monkeypatch)
    from app.api import analysis_jobs
    monkeypatch.setattr(analysis_jobs, '_check_order_access_async', AsyncMock(side_effect=HTTPException(403,'denied')))
    assert client.get(base).status_code==403
    monkeypatch.setattr(analysis_jobs, '_check_order_access_async', AsyncMock())
    index = next(root.glob('.analysis_results/*/*/explorer_records.parquet'))
    with index.open('ab') as f: f.write(b'corrupt')
    assert client.get(base+'/pathways').status_code==409
    asyncio.run(engine.dispose())


def test_preprocessing_completed_is_legacy_not_ready(tmp_path, monkeypatch):
    engine, _, _, client = setup_order(tmp_path, monkeypatch)
    client.app.include_router(routes.router)
    response = client.get('/orders/1/evidence-runs').json()
    assert response['status']=='legacy_unbound' and response['records']==[]
    asyncio.run(engine.dispose())


def test_blind_job_identity_ignores_expected_treatment_and_display_context(tmp_path, monkeypatch):
    engine,factory,_,client=setup_order(tmp_path,monkeypatch)
    from app.models.order import Order
    async def label(value):
        async with factory() as db:
            order=await db.get(Order,1)
            order.analysis_context={'treatment':value,'expected_target_windows':{'K1':[1,5]},'top_n':49}
            await db.commit()
    ids=[]
    for name in ('','insulin','unidentified_compound'):
        asyncio.run(label(name))
        response=client.post('/orders/1/analysis-jobs',json={})
        assert response.status_code==202,response.text
        ids.append(response.json()['job_id'])
    assert len(set(ids))==1
    assert client.post('/orders/1/analysis-jobs',json={'tmm_config':{'profile_prior_policy':'legacy_gaussian'}}).status_code==422
    assert client.post('/orders/1/analysis-jobs',json={'inference_mode':'context_assisted','tmm_config':{'profile_prior_policy':'legacy_gaussian'}}).json()['job_id']!=ids[0]
    asyncio.run(engine.dispose())


def test_requested_comparisons_publish_actual_states_without_replacing_primary(tmp_path, monkeypatch):
    engine,factory,root,client=setup_order(tmp_path,monkeypatch)
    client.app.include_router(routes.router)
    monkeypatch.setattr(routes,'get_settings',lambda:SimpleNamespace(OUTPUT_DIR=str(tmp_path)))
    requested=['partial_linear.v1','proda_label_free.v1','time_window_nnls.v1','tmm_magnitude.v1']
    job=client.post('/orders/1/analysis-jobs',json={'comparison_models':requested}).json()
    asyncio.run(executor.execute_production_tmm(job['job_id'],session_factory=factory))
    run=client.get('/orders/1/evidence-runs').json()['records'][0]
    base='/orders/1/evidence-runs/'+run['bundle_id']
    component=client.get(base).json()['components']['model-comparisons']
    assert component['status']=='partial' and component['requested_count']==4
    assert component['completed_count']==3
    models={m['model_id']:m for m in client.get(base+'/model-comparisons').json()['records']}
    assert models['proda_label_free.v1']['status']=='not_evaluable'
    assert models['proda_label_free.v1']['reason']=='raw_observation_inventory_missing'
    records=client.get(base+'/model-results').json()['records']
    window=[r for r in records if r['model_id']=='time_window_nnls.v1']
    assert len(window)==4 and all(r['reason']=='insufficient_declared_time_grid' for r in window)
    assert all(m.get('default_model_promoted') is False for m in models.values())
    partial=client.get(base+'/model-results',params={'model_id':'partial_linear.v1','limit':2}).json()
    assert partial['total_count']==4 and len(partial['records'])==2
    assert all(r['model_id']=='partial_linear.v1' for r in partial['records'])
    assert client.get(base+'/model-results',params={'model_id':'time_window_nnls.v1','cursor':partial['next_cursor']}).status_code==422
    primary=client.get(job['result_url']).json()
    assert primary['tmm_config']['target_transform']=='signed'
    assert primary['kinase_scores'][0]['up_sums']['5min']==8
    asyncio.run(engine.dispose())
