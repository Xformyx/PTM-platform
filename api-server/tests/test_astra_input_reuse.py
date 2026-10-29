"""Real resolve/upload/PATCH/SQLite reload/dispatch and package metadata boundary.

No broker, scientific worker execution, provider calls, archive or production DB.
"""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import orders
from app.core.database import Base
from app.models.order import Order
from app.models.rag_collection import RagCollection
from app.services.astra_input_capture import prepare_astra_inputs
from ptm_shared.astra_package import write_study_inputs
from ptm_shared.tests.test_study_input_reuse import inputs
from ptm_shared.study_display import study_display


@pytest.mark.parametrize('replicates,planned', [(2,2),(3,4)])
def test_resolve_save_reload_rerun_dispatch_and_package_metadata(tmp_path, monkeypatch, replicates, planned):
    context, rows, manifest = inputs()
    if replicates == 3:
        extra = [{**r,'sample_id':r['sample_id'][:-1]+'3','replicate':3} for r in rows if r['replicate']==2]
        rows += extra
        manifest['samples'] += [{**r,'biological_unit':'donor_3','technical_injection':'1'} for r in extra]
    context.update(biological_question='  모델 α · 시간 및 반복 설계\n분석 목적 원문  ',
                   replication_plan={'default_replicates_per_condition':planned,'source':'user_input'})
    context.update(science={'diann_version': '2.7.0'},
                   acquisition={'instrument': {'value': 'recorded instrument'}},
                   astra_source_pin_sha256=None)
    settings = SimpleNamespace(INPUT_DIR=str(tmp_path/'uploads'), OUTPUT_DIR=str(tmp_path/'outputs'), REFERENCE_DIR=str(tmp_path/'references'))
    monkeypatch.setattr(orders, 'get_settings', lambda: settings)
    monkeypatch.setattr('app.config.get_settings', lambda: settings)
    monkeypatch.setenv('OUTPUT_DIR', settings.OUTPUT_DIR)
    monkeypatch.delenv('PTM_ASTRA_EVIDENCE_V6', raising=False)
    app = FastAPI(); app.include_router(orders.router)
    app.dependency_overrides[orders.get_current_user] = lambda: SimpleNamespace(id=0, role='admin')
    headers = '\t'.join(r['sample_id'] for r in rows)
    quantities = '\t'.join('10' for _ in rows)
    matrix = f'Protein.Group\t{headers}\nP1\t{quantities}\n'.encode()

    async def exercise():
        engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path}/orders.sqlite')
        async with engine.begin() as conn:
            await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=[Order.__table__, RagCollection.__table__]))
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async def database():
            async with sessions() as db: yield db
        app.dependency_overrides[orders.get_db] = database
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
            body = {'species': 'human', 'ptm_type': 'phosphorylation', 'sample_config': rows, 'analysis_context': context}
            preview = await client.post('/orders/resolve-design', json=body)
            assert preview.status_code == 200, preview.text
            initial = preview.json()['analysis_context']
            assert initial['study_design']['materials'] == []
            display = preview.json()['study_display']
            assert display == study_display(initial['study_design'],initial)
            assert display['biological_question']['value'] == context['biological_question']
            assert display['replication']['summary'] == f'등록 반복: 조건별 {replicates}반복 · 총 {len(rows)}개 측정 파일'
            response = await client.post('/orders', data={'project_name': 'Input_reuse_synthetic', 'species': 'human', 'ptm_type': 'phosphorylation',
                'sample_config': json.dumps(rows), 'analysis_context': json.dumps(initial), 'rag_collections': '[]',
                'report_options': json.dumps({'research_questions': ['Recorded research question']})},
                files={'pr_matrix': ('PR.tsv', matrix), 'pg_matrix': ('PG.tsv', matrix),
                       'fasta_file': ('reference.fasta', b'>sp|P1|P1 GN=GENE OX=9606\nMASKASK\n')})
            assert response.status_code == 201, response.text
            order_id = response.json()['id']
            patched = await client.patch(f'/orders/{order_id}', json={'analysis_context': {'sample_manifest': manifest}})
            assert patched.status_code == 200, patched.text
            resolved = patched.json()['analysis_context']
            assert len(resolved['study_design']['materials']) == len(rows)
            direct = await client.post('/orders/resolve-design', json={**body, 'analysis_context': {**context, 'sample_manifest': manifest}})
            assert resolved['study_design'] == direct.json()['study_design']
            # Omitted fields survive; resolving an unchanged draft is idempotent.
            again = await client.patch(f'/orders/{order_id}', json={'analysis_context': {}})
            assert again.json()['analysis_context'] == resolved
            changed_rows = deepcopy(rows)
            for row in changed_rows:
                if row['condition'] == '0.5h': row['condition'] = '0.75h'
            changed_manifest = deepcopy(manifest)
            for row in changed_manifest['samples']:
                if row['condition'] == '0.5h': row['condition'] = '0.75h'
            for row in changed_manifest['conditions']:
                if row['condition'] == '0.5h': row.update(condition='0.75h', time_minutes=45)
            changed = await client.patch(f'/orders/{order_id}', json={'sample_config': changed_rows,
                'analysis_context': {'time_points': '0,0.75,1,3,6,24h', 'sample_manifest': changed_manifest}})
            assert changed.status_code == 200, changed.text
            final = changed.json()['analysis_context']
            assert '0.5h' not in {c['label'] for c in final['study_design']['conditions']}
            # A completed-order GET must not resolve or persist a design.
            async with sessions() as db:
                order = (await db.execute(select(Order).where(Order.id == order_id))).scalar_one()
                order.status = 'completed'; await db.commit()
            read = await client.get(f'/orders/{order_id}')
            assert read.status_code == 200, read.text
            assert read.json()['analysis_context']['biological_question'] == context['biological_question']
            assert read.json()['analysis_context']['replication_plan'] == context['replication_plan']
            assert read.json()['report_options']['research_questions'] == ['Recorded research question']
            async with sessions() as db:
                order = (await db.execute(select(Order).where(Order.id == order_id))).scalar_one()
                assert order.analysis_context == final
                snapshot, literature = await prepare_astra_inputs(order, db, settings.REFERENCE_DIR)
            dispatch = {k: getattr(order, k) for k in ['pr_matrix_path', 'pg_matrix_path', 'fasta_path', 'order_code']}
            dispatch.update(species_tax_id='9606', user_input_snapshot=snapshot, literature_pin=literature)
            orders._attach_enrichment_free_profile(order, dispatch)
            execution = dispatch['experimental_context']
            assert execution['study_design'] == final['study_design']
            assert execution['science']['diann_version'] == execution['study_design']['study']['processing']['software_version']['value'] == '2.7.0'
            (tmp_path/'package-metadata/study').mkdir(parents=True)
            write_study_inputs(tmp_path/'package-metadata', snapshot, execution, execution['study_design'])
            saved = json.loads((tmp_path/'package-metadata/study/study_design.json').read_text())
            assert saved == final['study_design']
            saved_display = json.loads((tmp_path/'package-metadata/study/study_display.json').read_text())
            assert saved_display == study_display(final['study_design'],final)
            assert saved_display['biological_question']['value'] == context['biological_question']
            assert saved_display['replication']['injection_count'] == len(rows)
            assert saved['study']['original_context']['cell_type'] == context['cell_type']
            assert saved['study']['acquisition']['instrument']['value'] == 'recorded instrument'
            assert snapshot['original']['rag_collections'] == []
            assert snapshot['original']['report_options']['research_questions'] == ['Recorded research question']
            assert snapshot['original']['analysis_context']['sample_manifest'] == changed_manifest
            # Exercise the actual worker dispatch branch, replacing only runtime
            # infrastructure and the scientific engine with a metadata-only sink.
            import preprocessing.tasks as worker
            import common.run_control as control
            import ptm_shared.enrichment_free_workflow as workflow
            monkeypatch.setattr(worker, 'OUTPUT_DIR', settings.OUTPUT_DIR)
            for name in ['update_order_status', 'publish_progress', 'send_step_webhook']:
                monkeypatch.setattr(worker, name, lambda *a, **k: None)
            for name in ['bind_run_generation', 'is_stale_generation', 'abort_if_superseded']:
                monkeypatch.setattr(control, name, lambda *a, **k: None)
            monkeypatch.setattr(worker._redis, 'from_url', lambda *a, **k: Mock())
            monkeypatch.setattr('common.db_engine.get_engine', Mock(side_effect=RuntimeError('isolated fixture')))
            received = []
            def metadata_only(order_id, config, output, **kwargs):
                received.append(deepcopy(config['experimental_context']))
                (output/'study').mkdir(parents=True)
                write_study_inputs(output, config['user_input_snapshot'], config['experimental_context'], config['experimental_context']['study_design'])
                return {'run_id': 'metadata-only', 'provenance': {'provenance_id': 'fixture'}, 'artifacts': {'astra': {'path': 'not-generated.zip'}}}
            monkeypatch.setattr(workflow, 'run_primary_analysis', metadata_only)
            assert worker.run_preprocessing.run(order_id, dispatch)['status'] == 'completed'
            assert received == [execution]
        await engine.dispose()
    asyncio.run(exercise())
