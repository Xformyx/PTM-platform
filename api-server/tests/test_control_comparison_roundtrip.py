"""C02 actual SQLite/API/dispatch/worker metadata round-trip; scientific sink only."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import Mock
import httpx
from fastapi import FastAPI, HTTPException
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.api import orders
from app.core.database import Base
from app.models.order import Order
from app.models.rag_collection import RagCollection
from app.services.astra_input_capture import prepare_astra_inputs
from ptm_shared.tests.test_control_comparison import inputs
from ptm_shared.astra_package import write_study_inputs


def test_policy_save_reload_dispatch_worker_snapshot(tmp_path, monkeypatch):
    context, samples = inputs('time_matched')
    settings=SimpleNamespace(INPUT_DIR=str(tmp_path/'inputs'),OUTPUT_DIR=str(tmp_path/'outputs'),REFERENCE_DIR=str(tmp_path/'references'))
    monkeypatch.setattr(orders,'get_settings',lambda:settings)
    monkeypatch.setattr('app.config.get_settings',lambda:settings)
    monkeypatch.setenv('OUTPUT_DIR',settings.OUTPUT_DIR)
    app=FastAPI();app.include_router(orders.router)
    app.dependency_overrides[orders.get_current_user]=lambda:SimpleNamespace(id=0,role='admin')
    columns='\t'.join(r['sample_id'] for r in samples)
    values='\t'.join('10' for _ in samples)
    matrix=f'Protein.Group\t{columns}\nP1\t{values}\n'.encode()
    async def exercise():
        engine=create_async_engine(f'sqlite+aiosqlite:///{tmp_path}/orders.sqlite')
        async with engine.begin() as conn:
            await conn.run_sync(lambda c:Base.metadata.create_all(c,tables=[Order.__table__,RagCollection.__table__]))
        sessions=async_sessionmaker(engine,expire_on_commit=False)
        async def database():
            async with sessions() as db:yield db
        app.dependency_overrides[orders.get_db]=database
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://fixture') as client:
            preview=await client.post('/orders/resolve-design',json={'species':'human','ptm_type':'phosphorylation','sample_config':samples,'analysis_context':context})
            assert preview.status_code==200,preview.text
            initial=preview.json()['analysis_context'];design=initial['study_design']
            created=await client.post('/orders',data={'project_name':'Control_synthetic','species':'human','ptm_type':'phosphorylation',
                'sample_config':json.dumps(samples),'analysis_context':json.dumps(initial),'rag_collections':'[]'},
                files={'pr_matrix':('PR.tsv',matrix),'pg_matrix':('PG.tsv',matrix),
                    'fasta_file':('reference.fasta',b'>sp|P1|P1 GN=GENE OX=9606\nMASKASK\n')})
            assert created.status_code==201,created.text
            oid=created.json()['id']
            read=await client.get(f'/orders/{oid}')
            assert read.json()['analysis_context']['study_design']==design
            zero=next(c['condition_id'] for c in design['conditions'] if c['time']['minutes']==0)
            changed=await client.patch(f'/orders/{oid}',json={'analysis_context':{'control_comparison':{
                'strategy':'shared_reference','reference_condition_id':zero,'source':'user_input'}}})
            assert changed.status_code==200,changed.text
            final=changed.json()['analysis_context'];actual=final['study_design']
            assert actual['materials']==design['materials'] and actual['injections']==design['injections']
            assert {c['reference_condition_id'] for c in actual['contrasts']}=={zero}
            assert {c['pairing'] for c in actual['contrasts']}=={'unpaired'}
            async with sessions() as db:
                order=await db.get(Order,oid)
                order.status='completed';await db.commit()
                snapshot,literature=await prepare_astra_inputs(order,db,settings.REFERENCE_DIR)
            dispatch={k:getattr(order,k) for k in ['pr_matrix_path','pg_matrix_path','fasta_path','order_code']}
            dispatch.update(species_tax_id='9606',user_input_snapshot=snapshot,literature_pin=literature)
            orders._attach_enrichment_free_profile(order,dispatch)
            assert dispatch['experimental_context']['study_design']==actual
            reloaded=await client.get(f'/orders/{oid}')
            assert reloaded.json()['analysis_context']==final
            import preprocessing.tasks as worker
            import common.run_control as control
            import ptm_shared.enrichment_free_workflow as workflow
            monkeypatch.setattr(worker,'OUTPUT_DIR',settings.OUTPUT_DIR)
            for name in ['update_order_status','publish_progress','send_step_webhook']:
                monkeypatch.setattr(worker,name,lambda *a,**k:None)
            for name in ['bind_run_generation','is_stale_generation','abort_if_superseded']:
                monkeypatch.setattr(control,name,lambda *a,**k:None)
            monkeypatch.setattr(worker._redis,'from_url',lambda *a,**k:Mock())
            monkeypatch.setattr('common.db_engine.get_engine',Mock(side_effect=RuntimeError('isolated fixture')))
            received=[]
            def metadata_only(order_id,config,output,**kwargs):
                execution=config['experimental_context'];received.append(deepcopy(execution['study_design']))
                (output/'study').mkdir(parents=True)
                write_study_inputs(output,config['user_input_snapshot'],execution,execution['study_design'])
                policy=json.loads((output/'study/control_comparison.json').read_text())
                assert policy['effective_policy']['strategy']=='shared_reference'
                assert {a['contrast_id'] for a in policy['assignments']}=={c['contrast_id'] for c in actual['contrasts']}
                assert {a['reference_condition_id'] for a in policy['assignments']}=={zero}
                return {'run_id':'metadata-only','provenance':{'provenance_id':'fixture'},'artifacts':{'astra':{'path':'not-generated.zip'}}}
            monkeypatch.setattr(workflow,'run_primary_analysis',metadata_only)
            assert worker.run_preprocessing.run(oid,dispatch)['status']=='completed'
            assert received==[actual]
        await engine.dispose()
    asyncio.run(exercise())


def test_legacy_multiple_controls_cannot_enter_pooling_execution():
    context, samples=inputs('time_matched')
    order=SimpleNamespace(analysis_context={'mode':'legacy','control_comparison':context['control_comparison']},
        sample_config=samples,secondary_sample_config=None,species='human',ptm_type='phosphorylation')
    with pytest.raises(HTTPException) as error:
        orders._updated_analysis_context(order,{},for_execution=True)
    assert error.value.status_code==422
    assert 'Control' in str(error.value.detail)
