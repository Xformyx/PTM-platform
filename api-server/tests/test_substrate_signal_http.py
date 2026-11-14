"""Production read-only API over a sealed synthetic saved-source boundary."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
import json

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from app.api import vector_view
from ptm_shared.annotation_registry import digest
from ptm_shared.astra_package import write_tables
from ptm_shared.astra_evidence_catalog import write_evidence_access
from ptm_shared.generic_workflow import json_write
from ptm_shared.substrate_signal_reader import write_signal_flow
from test_substrate_signal_flow import fixture, kinase_fixture


def test_saved_snapshot_access_pagination_and_tamper(tmp_path, monkeypatch):
    root,tables,design,registry=fixture(tmp_path/'ORDER')
    kinase_fixture(tables,design,registry)
    dictionary=write_tables(tables,root)
    json_write(root/'reproducibility/data_dictionary.json',dictionary)
    write_evidence_access(root);write_signal_flow(root,tables)
    json_write(tmp_path/'ORDER/enrichment_free_current.json',{'run_id':'actual-fixture-run','artifacts':{
        'provenance':{'path':'source/provenance.json','sha256':digest(root/'provenance.json')}}})
    access=AsyncMock(return_value=SimpleNamespace(order_code='ORDER'))
    monkeypatch.setattr(vector_view,'access',access)
    monkeypatch.setattr(vector_view,'get_settings',lambda:SimpleNamespace(OUTPUT_DIR=str(tmp_path)))
    vector_view._signal_session.cache_clear()
    app=FastAPI();app.include_router(vector_view.router)
    app.dependency_overrides[vector_view.get_db]=lambda:object()
    app.dependency_overrides[vector_view.get_current_user]=lambda:object()
    client=TestClient(app)
    path='/orders/1/substrate-signal/kinase_substrate_bundles'
    first=client.post(path,json={'filters':{'form_id':'f'},'limit':1})
    assert first.status_code==200,first.text
    first=first.json();assert first['total_count']==2 and first['next_cursor']
    second=client.post(path,json={'filters':{'form_id':'f'},'limit':1,'cursor':first['next_cursor']}).json()
    assert second['items'][0]['bundle_id']!=first['items'][0]['bundle_id']
    assert vector_view._signal_session.cache_info().hits>=1
    bundle=first['items'][0]
    links=client.post('/orders/1/substrate-signal/temporal_evidence_links',json={'filters':{'bundle_id':bundle['bundle_id']}}).json()
    assert any(r['to_id']==bundle['association_id'] for r in links['items'])
    assert client.post(path,json={'filters':{'candidate_id':'different'},'cursor':first['next_cursor']}).status_code==409
    assert client.post(path,json={'cursor':'!a'}).status_code==409
    access.side_effect=HTTPException(403,'no access')
    assert client.post(path,json={}).status_code==403
    access.side_effect=None
    source=root/'signal_flow/kinase_substrate_bundles.csv'
    source.write_text(source.read_text()+'\n')
    assert client.post(path,json={}).status_code==409
    vector_view._signal_session.cache_clear()
