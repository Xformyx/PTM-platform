"""Real routes, SQLite job state, full worker pipeline and immutable synthetic artifacts.

SQLite does not validate MySQL locking, Redis delivery or process-kill recovery.
"""
import asyncio
import csv
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.core.database import Base
from app.models.order import Order
from app.models.analysis_job import AnalysisJob, AnalysisHead
from app.api import analysis_jobs as routes
from app.services import analysis_jobs, production_tmm_executor as executor
from ptm_shared.analysis_revision import publish_analysis_input, verify_result


def setup_order(tmp_path, monkeypatch):
    async def setup():
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'jobs.sqlite'}")
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(lambda c: Base.metadata.create_all(c, tables=[Order.__table__, AnalysisJob.__table__, AnalysisHead.__table__]))
        async with factory() as db:
            db.add(Order(id=1, order_code="SYNTHETIC", project_name="synthetic", ptm_type="phosphorylation", species="mouse",
                         sample_config={}, report_options={}, pr_matrix_path="fixture", pg_matrix_path="fixture", fasta_path="fixture",
                         analysis_context={}))
            await db.commit()
        return engine, factory
    engine, factory = asyncio.run(setup())
    root = tmp_path/"SYNTHETIC"
    root.mkdir()
    rows = [{"Gene.Name": f"Rps{i}", "PTM_Position": "S2", "Precursor.Id": f"p{i}", "Precursor.Charge": "2",
             "Modified.Sequence": "AS(UniMod:21)AA", "Protein.Group": f"P{i}", "FASTA_Taxonomy_ID": "10090",
             "Condition": c, "PTM_ProteinAdjusted_Log2FC": v, "PTM_Unadjusted_Log2FC": v,
             "Predicted_Regulator": "K1", "Motif_Evidence_Policy": "modified_residue_anchor.v1"}
            for i in range(4) for c,v in zip(("1min","5min","10min","20min"), (1,2,1,.5))]
    with (root/"ptm_vector_data_normalized_phospho.tsv").open("w") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0], delimiter="\t")
        writer.writeheader(); writer.writerows(rows)
    publish_analysis_input(root, config={"ptm_type": "phosphorylation"})
    settings = SimpleNamespace(OUTPUT_DIR=str(tmp_path))
    monkeypatch.setattr(analysis_jobs, "get_settings", lambda: settings)
    monkeypatch.setattr(executor, "get_settings", lambda: settings)
    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    monkeypatch.setattr(analysis_jobs, "enqueue_job", lambda job_id: job_id)
    monkeypatch.setattr(routes, "_check_order_access_async", AsyncMock())
    monkeypatch.setattr(routes, "_require_write_access", AsyncMock())
    async def db_dependency():
        async with factory() as db: yield db
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.get_db] = db_dependency
    app.dependency_overrides[routes.get_current_user] = lambda: SimpleNamespace(id=1, role="admin")
    return engine, factory, root, TestClient(app)


def test_actual_route_worker_result_and_display_budget_invariance(tmp_path, monkeypatch):
    engine, factory, root, client = setup_order(tmp_path, monkeypatch)
    first = client.post("/orders/1/analysis-jobs", json={"analysis_scope":"full_eligible", "n":20, "ptms":[]})
    assert first.status_code == 202, first.text
    a = first.json()
    b = client.post("/orders/1/analysis-jobs", json={"n":500, "checked_feature_ids":["invisible"], "rag_budget":2}).json()
    assert a["job_id"] == b["job_id"]
    result = asyncio.run(executor.execute_production_tmm(a["job_id"], session_factory=factory))
    assert result["execution_status"] == "completed"
    status = client.get(a["status_url"]).json()
    assert all(s["execution_status"] == "completed" for s in status["stage_status"].values())
    response = client.get(a["result_url"])
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["coverage"]["source_rows"] == 16
    assert payload["coverage"]["analysis_features"] == 4
    assert payload["coverage"]["mapped_features"] == 4
    assert payload['inventory_status']=='paged'
    assert 'inventory' not in payload['analysis_manifest']
    member_page=client.get(payload['membership_page_url']+'?kind=members&kinase=K1&limit=2').json()
    assert member_page['count']==4 and len(member_page['records'])==2
    next_page=client.get(payload['membership_page_url'],params={'kind':'members','kinase':'K1','limit':2,'after':member_page['next_cursor']}).json()
    assert {r['feature_id'] for r in member_page['records']}.isdisjoint(r['feature_id'] for r in next_page['records'])
    assert payload["kinase_scores"][0]["up_sums"]["5min"] == 8
    download=client.get(a["status_url"]+"/artifacts/result")
    assert download.status_code==200
    assert download.headers['X-Analysis-Revision']==result['revision_id']
    assert download.json()['coverage']==payload['coverage']
    assert client.get(a['status_url']+'/artifacts/unregistered').status_code==404
    repeat = client.post("/orders/1/analysis-jobs", json={"n":50}).json()
    assert repeat["result_revision"] == result["revision_id"]
    assert client.get("/orders/2/analysis-jobs/"+a["job_id"]).status_code == 404
    asyncio.run(engine.dispose())


def test_cancel_and_failed_stage_preserve_previous_success(tmp_path, monkeypatch):
    engine, factory, root, client = setup_order(tmp_path, monkeypatch)
    queued = client.post("/orders/1/analysis-jobs", json={}).json()
    cancelled = client.post(queued["status_url"]+"/cancel").json()
    assert cancelled["execution_status"] == "cancelled"
    assert asyncio.run(executor.execute_production_tmm(queued["job_id"], session_factory=factory))["execution_status"] == "cancelled"
    job = client.post("/orders/1/analysis-jobs", json={}).json()
    monkeypatch.setattr(executor, "trajectory_diagnostics", lambda *args: (_ for _ in ()).throw(RuntimeError("synthetic stage failure")))
    with pytest.raises(RuntimeError, match="synthetic stage failure"):
        asyncio.run(executor.execute_production_tmm(job["job_id"], session_factory=factory))
    failed = client.get(job["status_url"]).json()
    assert failed["execution_status"] == "failed"
    assert failed["stage_status"]["score"]["execution_status"] == "completed"
    assert client.get(job["result_url"]).status_code == 409
    async def check():
        async with factory() as db:
            assert (await db.get(AnalysisHead, 1)).current_revision is None
    asyncio.run(check())
    asyncio.run(engine.dispose())


def test_explicit_subset_revision_never_supersedes_full_analysis(tmp_path, monkeypatch):
    engine, factory, root, client = setup_order(tmp_path, monkeypatch)
    full = client.post('/orders/1/analysis-jobs', json={}).json()
    asyncio.run(executor.execute_production_tmm(full['job_id'], session_factory=factory))
    payload = client.get(full['result_url']).json()
    ids = [r['feature_id'] for r in client.get(payload['membership_page_url']+'?limit=1').json()['records']]
    async def pointers():
        async with factory() as db:
            head = await db.get(AnalysisHead, 1)
            return (head.current_job_id, head.current_revision, head.requested_job_id, head.generation,
                    dict((await db.get(Order, 1)).kinase_activity_heatmap))
    before = asyncio.run(pointers())
    subset = client.post('/orders/1/analysis-jobs', json={'analysis_scope':'explicit_subset',
        'analysis_feature_ids':ids, 'subset_reason':'synthetic focused exploration'}).json()
    assert asyncio.run(pointers()) == before
    asyncio.run(executor.execute_production_tmm(subset['job_id'], session_factory=factory))
    result = client.get(subset['result_url']).json()
    assert result['analysis_scope'] == 'explicit_subset'
    assert result['coverage']['analysis_features'] == 1
    assert result['revision_manifest']['revision_id'] != before[1]
    assert asyncio.run(pointers()) == before
    asyncio.run(engine.dispose())


def test_unresolved_shared_only_analysis_is_not_an_evaluated_zero(tmp_path, monkeypatch):
    engine, factory, root, client = setup_order(tmp_path, monkeypatch)
    source=root/'ptm_vector_data_normalized_phospho.tsv'
    source.write_text(source.read_text().replace('\tK1\t','\tK1;K2\t'))
    publish_analysis_input(root, config={'ptm_type':'phosphorylation'})
    job=client.post('/orders/1/analysis-jobs',json={}).json()
    asyncio.run(executor.execute_production_tmm(job['job_id'],session_factory=factory))
    result=client.get(job['result_url']).json()
    assert result['execution_status']=='completed'
    assert result['evaluation_status']=='not_evaluable'
    assert result['coverage']['individual_no_call_kinases']==2
    assert len(result['kinase_scores'])==2
    for score in result['kinase_scores']:
        assert score['observation_counts']['5min']==4
        assert set(score['scores'].values())=={None}
    asyncio.run(engine.dispose())


def test_stale_lease_requires_free_execution_lock_and_heartbeat_is_fenced(tmp_path,monkeypatch):
    import fcntl
    from datetime import timedelta
    from app.services import analysis_job_recovery as recovery
    engine,factory,root,client=setup_order(tmp_path,monkeypatch)
    monkeypatch.setattr(recovery,'get_settings',lambda:SimpleNamespace(OUTPUT_DIR=str(tmp_path)))
    job=client.post('/orders/1/analysis-jobs',json={}).json()
    old=recovery.utcnow()-timedelta(seconds=300)
    async def stale():
        async with factory() as db:
            stored=await db.get(AnalysisJob,job['job_id'])
            stored.execution_status='running';stored.attempt_token='live-token';stored.heartbeat_at=old
            await db.commit()
    async def timestamp():
        async with factory() as db:return (await db.get(AnalysisJob,job['job_id'])).heartbeat_at
    asyncio.run(stale())
    asyncio.run(recovery.heartbeat_once(factory,job['job_id'],'stale-token'))
    assert asyncio.run(timestamp())==old
    asyncio.run(recovery.heartbeat_once(factory,job['job_id'],'live-token'))
    assert asyncio.run(timestamp())>old
    asyncio.run(stale())
    stop,thread=recovery.start_heartbeat(factory,job['job_id'],'live-token',interval=.03)
    import time
    time.sleep(.15)  # the owning event loop is deliberately not running
    stop.set();thread.join(5)
    assert not thread.is_alive() and asyncio.run(timestamp())>old
    asyncio.run(stale())
    storage=root/'.analysis_results';storage.mkdir(exist_ok=True)
    queued=[]
    async def recover():
        async with factory() as db:return await recovery.recover_job(db,job['job_id'],enqueue=queued.append)
    with (storage/f"{job['job_id']}.lock").open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert asyncio.run(recover())['recovery']=='execution_still_owned'
        assert not queued
    assert asyncio.run(recover())['recovery']=='requeued'
    assert queued==[job['job_id']]
    assert asyncio.run(recover())['recovery']=='lease_current'
    asyncio.run(executor.execute_production_tmm(job['job_id'],session_factory=factory))
    assert client.get(job['status_url']).json()['execution_status']=='completed'
    asyncio.run(engine.dispose())


def test_pinned_report_handoff_and_failed_new_attempt_preserve_success(tmp_path, monkeypatch):
    from ptm_shared.analysis_revision import resolve_analysis_artifacts
    engine, factory, root, client = setup_order(tmp_path, monkeypatch)
    first=client.post('/orders/1/analysis-jobs',json={}).json()
    asyncio.run(executor.execute_production_tmm(first['job_id'],session_factory=factory))
    async def pointers():
        async with factory() as db:
            return dict((await db.get(Order,1)).kinase_analysis_data), (await db.get(AnalysisHead,1)).current_revision
    pointer,revision=asyncio.run(pointers())
    packet=resolve_analysis_artifacts(root,pointer)
    assert packet['evidence_inventory']['analysis_revision']==revision
    assert len(packet['evidence_inventory']['inventory'])==4
    second=client.post('/orders/1/analysis-jobs',json={'tmm_config':{'fc_threshold':.4}}).json()
    monkeypatch.setattr(executor,'temporal_diagnostics',lambda *args: (_ for _ in ()).throw(OSError('synthetic disk full')))
    with pytest.raises(OSError): asyncio.run(executor.execute_production_tmm(second['job_id'],session_factory=factory))
    assert asyncio.run(pointers())==(pointer,revision)
    assert client.get(second['status_url']).json()['failure_reason']=='resource_exhausted'
    # Damaged bytes never resolve as a current success.
    (root/pointer['result_path']/'result.json').write_text('{}')
    with pytest.raises(ValueError,match='integrity'): resolve_analysis_artifacts(root,pointer)
    asyncio.run(engine.dispose())


def test_full_motif_source_and_explicit_subset_do_not_use_rag(tmp_path,monkeypatch):
    from app.services.analysis_universe import prepare_analysis
    engine,factory,root,client=setup_order(tmp_path,monkeypatch)
    source=root/'ptm_vector_data_normalized_phospho.tsv'
    motif=root/'ptm_vector_data_with_motifs_phospho.tsv';motif.write_bytes(source.read_bytes())
    with source.open() as stream: rows=list(csv.DictReader(stream,delimiter='\t'))
    for row in rows: row.pop('Predicted_Regulator');row.pop('Motif_Evidence_Policy')
    with source.open('w') as stream:
        writer=csv.DictWriter(stream,fieldnames=rows[0],delimiter='\t');writer.writeheader();writer.writerows(rows)
    manifest,_,_=prepare_analysis(root,'phosphorylation')
    assert manifest['coverage']['mapped_features']==4
    subset,_,_=prepare_analysis(root,'phosphorylation',scope='explicit_subset',subset_ids=manifest['analysis_feature_ids'][:1],subset_reason='test only')
    assert subset['coverage']['analysis_features']==1
    assert len(subset['candidate_modules'][0]['members'])==1
    assert subset['analysis_manifest_id']!=manifest['analysis_manifest_id']
    asyncio.run(engine.dispose())


def test_redelivery_reuses_verified_stages_and_generation_fences_publication(tmp_path,monkeypatch):
    engine,factory,root,client=setup_order(tmp_path,monkeypatch)
    job=client.post('/orders/1/analysis-jobs',json={}).json()
    original=executor.trajectory_diagnostics
    monkeypatch.setattr(executor,'trajectory_diagnostics',lambda *a: (_ for _ in ()).throw(RuntimeError('interrupted')))
    with pytest.raises(RuntimeError): asyncio.run(executor.execute_production_tmm(job['job_id'],session_factory=factory))
    monkeypatch.setattr(executor,'trajectory_diagnostics',original)
    monkeypatch.setattr(executor,'score_tracks',lambda *a: (_ for _ in ()).throw(AssertionError('completed score must be reused')))
    assert asyncio.run(executor.execute_production_tmm(job['job_id'],session_factory=factory))['execution_status']=='completed'
    first_revision=client.get(job['status_url']).json()['result_revision']
    older=client.post('/orders/1/analysis-jobs',json={'tmm_config':{'fc_threshold':.4}}).json()
    newer=client.post('/orders/1/analysis-jobs',json={'tmm_config':{'fc_threshold':.5}}).json()
    assert asyncio.run(executor.execute_production_tmm(older['job_id'],session_factory=factory))['execution_status']=='superseded'
    async def current():
        async with factory() as db: return (await db.get(AnalysisHead,1)).current_revision
    assert asyncio.run(current())==first_revision
    assert client.get(newer['status_url']).json()['execution_status']=='queued'
    asyncio.run(engine.dispose())
