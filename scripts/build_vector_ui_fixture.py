"""Generate synthetic responses using the actual route and durable executor.

Run with PYTHONPATH=.:api-server:api-server/tests and installed API test deps.
No biological correctness is implied by synthetic labels or regulator K1.
"""
import argparse
import asyncio
import csv
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from pytest import MonkeyPatch
from test_analysis_job_lifecycle import setup_order
from app.api import orders
from app.services.production_tmm_executor import execute_production_tmm
from app.services.vector_view import load_vector_view
import app.config

parser=argparse.ArgumentParser()
parser.add_argument('--output',type=Path,required=True)
root=parser.parse_args().output
root.mkdir(parents=True,exist_ok=False)
with MonkeyPatch.context() as m:
    engine,factory,directory,client=setup_order(root,m)
    job=client.post('/orders/1/analysis-jobs',json={}).json()
    asyncio.run(execute_production_tmm(job['job_id'],session_factory=factory))
    payload=client.get(job['result_url']).json()
    assert payload['execution_status']=='completed'
    for name,data in [('job-response.json',payload),('job-stage-metrics.json',client.get(job['status_url']).json()),
                      ('job-members-response.json',client.get(payload['membership_page_url']+'?kind=members&kinase=K1').json()),
                      ('job-vector-response.json',load_vector_view(directory,'_phospho'))]:
        (root/name).write_text(json.dumps(data,allow_nan=False))
    rows=[{'Gene.Name':gene,'PTM_Position':'S2','Precursor.Id':precursor,'Precursor.Charge':charge,
        'Modified.Sequence':'AS(UniMod:21)AA','Protein.Group':'P-fixture','FASTA_Taxonomy_ID':10090,
        'Condition':condition,'PTM_ProteinAdjusted_Log2FC':value,'Protein_Log2FC':0}
        for gene,precursor,charge,values in [('Rps6','p1',2,[('1min',6),('5min',4)]),
             ('Rps6','p2',3,[('1min',0),('180min',2)]),('Akt1','p3',2,[('5min',-3)])]
        for condition,value in values]
    # Change only the synthetic live fixture after pinning the completed job;
    # the job's immutable source copies are deliberately preserved.
    with (directory/'ptm_vector_data_normalized_phospho.tsv').open('w') as stream:
        writer=csv.DictWriter(stream,fieldnames=rows[0],delimiter='\t');writer.writeheader();writer.writerows(rows)
    m.setattr(app.config,'get_settings',lambda:SimpleNamespace(OUTPUT_DIR=str(root)))
    m.setattr(orders,'_check_order_access_async',AsyncMock())
    client.app.include_router(orders.router)
    response=client.get('/orders/1/vector-plot-data')
    assert response.status_code==200,response.text
    (root/'response.json').write_text(json.dumps(response.json(),allow_nan=False))
    for n in (1,2,50):
        view=client.get(f'/orders/1/vector-plot-data?mode=global_top_n&n={n}').json()
        (root/f'response_global_{n}.json').write_text(json.dumps(view,allow_nan=False))
    asyncio.run(engine.dispose())
