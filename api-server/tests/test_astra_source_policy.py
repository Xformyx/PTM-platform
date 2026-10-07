"""Real preview route + shared create/copy/rerun dispatch contract; no DB writes."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import orders
from ptm_shared.astra_sources import pin_sources,source_execution_record
from ptm_shared.tests.test_astra_science import config


def test_preview_and_dispatch_use_existing_refresh_checkbox(config,tmp_path,monkeypatch):
    settings=SimpleNamespace(REFERENCE_DIR=config['reference_root'],OUTPUT_DIR=str(tmp_path/'outputs'))
    monkeypatch.setattr(orders,'get_settings',lambda:settings)
    monkeypatch.setenv('PTM_ASTRA_EVIDENCE_V6','1')
    old=pin_sources(config['reference_root'],{'acquisition_policy':{'mode':'legacy_bounded'},'queries':[]})
    samples=json.loads((Path(config['fasta_path']).parent/'fixture.json').read_text())['sample_config']
    order=SimpleNamespace(id=9,order_code='round04_fixture',species='human',ptm_type='phosphorylation',sample_config=samples,
        analysis_context=config['experimental_context'],analysis_options={},rag_collections=[],
        **{k:config[k] for k in ['pr_matrix_path','pg_matrix_path','fasta_path']})
    directory=Path(settings.OUTPUT_DIR)/order.order_code;directory.mkdir(parents=True)
    pointer=directory/'enrichment_free_current.json';pointer.write_text(json.dumps({'source_pin_sha256':old['pin_sha256']}))
    original=copy.deepcopy(order.analysis_context)
    context=orders._context_with_recorded_source_pin(order,order.analysis_context)
    assert context['astra_source_pin_sha256']==old['pin_sha256'] and order.analysis_context==original
    app=FastAPI();app.include_router(orders.router)
    app.dependency_overrides[orders.get_current_user]=lambda:SimpleNamespace(id=0,role='admin')
    with TestClient(app) as client:
        for refresh in [False,True]:
            # Normal UI sends v5; the existing flag resolves v6. No new selector.
            context.update(refresh_references=refresh,quantitation_export_mode='astra_analysis.v5')
            response=client.post('/orders/resolve-design',json={'species':'human','ptm_type':'phosphorylation','sample_config':samples,'analysis_context':context})
            assert response.status_code==200,response.text
            preview=response.json()['analysis_plan']['source_execution']
            order.analysis_context=context
            copied=orders._updated_analysis_context(order,{'biological_question':'copy context'})
            assert copied['refresh_references'] is refresh and copied['astra_source_pin_sha256']==old['pin_sha256']
            dispatch={k:config[k] for k in ['species_tax_id','pr_matrix_path','pg_matrix_path','fasta_path']}
            orders._attach_enrichment_free_profile(order,dispatch)
            assert dispatch['experimental_context']['refresh_references'] is refresh
            assert dispatch['source_pin_sha256']==old['pin_sha256']
            assert dispatch['experimental_context']['quantitation_export_mode']=='astra_analysis.v6'
            actual=source_execution_record(dispatch['experimental_context'],dispatch['source_pin_sha256'],None if refresh else old)
            for field in ['requested_policy','effective_pin_policy','pin_reused','refresh_requested','previous_pin_sha256','message']:
                assert actual[field]==preview[field]
    fresh=pin_sources(config['reference_root'],{'acquisition_policy':{'mode':'research_full'},'queries':[]})
    pointer.write_text(json.dumps({'source_pin_sha256':fresh['pin_sha256'],
        'source_execution':source_execution_record(context,old['pin_sha256'],fresh)}))
    # A completed refresh becomes the default reference for the next same-evidence rerun.
    context['refresh_references']=False
    assert orders._context_with_recorded_source_pin(order,context)['astra_source_pin_sha256']==fresh['pin_sha256']
