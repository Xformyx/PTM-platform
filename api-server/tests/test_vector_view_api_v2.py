"""Actual route -> temporary TSV / RAG / Parquet, synthetic quantities only."""
import asyncio
import csv
import json
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api import orders, vector_view
from app.services import vector_view as service
from test_analysis_job_lifecycle import setup_order
from ptm_shared.vector_columnar import publish_vector_columnar


def test_real_route_selection_and_annotation_revision_independence(tmp_path, monkeypatch):
    engine, factory, root, job_client = setup_order(tmp_path, monkeypatch)
    import app.config
    monkeypatch.setattr(app.config, 'get_settings', lambda: type('Settings', (), {'OUTPUT_DIR':str(tmp_path)})())
    monkeypatch.setattr(vector_view, 'get_settings', app.config.get_settings)
    monkeypatch.setattr(orders, '_check_order_access_async', __import__('unittest.mock',fromlist=['AsyncMock']).AsyncMock())
    app=job_client.app
    app.include_router(orders.router);app.include_router(vector_view.router)
    client=TestClient(app)
    rows=[{'Gene.Name':g,'PTM_Position':'S2','Precursor.Id':f'p{i}','Precursor.Charge':2,
           'Modified.Sequence':'AS(UniMod:21)AA','Protein.Group':f'P{i}','FASTA_Taxonomy_ID':10090,
           'Condition':c,'PTM_ProteinAdjusted_Log2FC':v,'Protein_Log2FC':0}
          for i,(g,vs) in enumerate(zip(['Rps6','Akt1','INSR','Opposing'],[[6,.2],[5,4],[1,8],[.5,7]])) for c,v in zip(['1min','5min'],vs)]
    with (root/'ptm_vector_data_normalized_phospho.tsv').open('w') as f:
        writer=csv.DictWriter(f,fieldnames=rows[0],delimiter='\t');writer.writeheader();writer.writerows(rows)
    url='/orders/1/vector-plot-data?n=2&axis=adjusted'
    first=client.get(url).json()
    assert len(first['features'])==4 and len(first['observations'])==8
    base_ids=first['selection']['selected_feature_ids']
    for text,status in [('[]','empty'),('[','failed'),('[{"gene":" RPS6 ","position":"s2","taxon":"10090","accession":"P0"}]','available')]:
        (root/'enriched_ptm_data_phospho.json').write_text(text)
        response=client.get(url);assert response.status_code==200,response.text
        payload=response.json();assert payload['sources']['annotations']['status']==status
        assert payload['selection']['selected_feature_ids']==base_ids
        assert payload['observations']==first['observations']
    global_view=client.get(url+'&mode=global_top_n').json()
    assert len(global_view['features'])==2 and len(global_view['observations'])==4
    publish_vector_columnar(root,'_phospho')
    columnar=client.get(url).json()
    assert columnar['selection']==first['selection']
    assert [(r['feature_id'],r['condition'],r['ptm_protein_adjusted_log2fc']) for r in columnar['observations']]==[(r['feature_id'],r['condition'],r['ptm_protein_adjusted_log2fc']) for r in first['observations']]
    density=client.post('/orders/1/vector-view/density',json={'options':{}}).json()
    assert density['count']==8
    annotations=client.post('/orders/1/vector-view/annotations',json={'options':{'limit':2}}).json()
    assert len(annotations['features'])==2 and annotations['next_cursor']
    assert annotations['annotation_source']['status']=='available'
    diagnostics=client.post('/orders/1/vector-view/diagnostics',json={'options':{}}).json()
    assert diagnostics['count']==0 and diagnostics['records']==[]
    assert client.post('/orders/1/vector-view/density',json={'measurement_revision':'stale'}).status_code==409
    export=client.get('/orders/1/vector-view/export')
    assert len(export.text.splitlines())==8
    assert export.headers['X-Measurement-Revision'] == first['measurement_revision']
    assert client.get('/orders/1/vector-view/export?measurement_revision=stale').status_code == 409
    asyncio.run(engine.dispose())
