"""Generate browser responses through actual routes and the production executor.

Synthetic reference assertions are not biological validation. No live services.
"""
import argparse
import asyncio
import csv
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT),str(ROOT/'api-server'),str(ROOT/'api-server/tests')]
os.environ.setdefault('DATABASE_URL','sqlite+aiosqlite:///:memory:')
import pytest
from test_analysis_job_lifecycle import setup_order
from app.api import signaling_explorer as routes
from app.services import production_tmm_executor as executor
from ptm_shared.analysis_revision import publish_analysis_input


def bind_synthetic_report(root, directory, parent, feature_id):
    """Sealed synthetic evidence large enough to exercise cursor navigation."""
    from ptm_shared.report_revision import register_revision, file_sha256
    from ptm_shared.run_evidence_bundle import publish_report_bundle
    report=root/'fixture-report.md'
    report.write_text('Synthetic packet binding only; no biological validation.\n')
    sources='\n'.join(f'Synthetic source span {i}.' for i in range(103))
    import hashlib
    assertions=[{'feature_id':feature_id,'quote':line,'source_offset':sources.index(line),
        'source_sha256':hashlib.sha256(sources.encode()).hexdigest(),
        'claim_support_status':'not_verified','quote_status':'exact_span_verified',
        'relationship':'literature_background'} for line in sources.splitlines()]
    payloads={
        'authoring_packet':{'reader_cards':[{'evidence_ids':['observed.browser'],
            'feature_identity':{'feature_id':feature_id},'claim_tier':'O1'}]},
        'prose_trace':{'sections':{'results':{'structured_decode_audit':[
            {'paragraph_index':i,'evidence_ids':['observed.browser'],'retained':True}
            for i in range(103)]}}},
        'finding_literature_retrieval':{'records':{'fixture':{
            'feature_id':feature_id,'status':'source_timeout','retrieved_count':None,
            'resolved_prompt':'PRIVATE FIXTURE PROMPT',
            'comparison_generation':{'provider_raw_text':'PRIVATE MODEL OUTPUT'}}},
            'references':[{'reference_id':'pmid:22222','pmid':'22222','title':'Synthetic source',
                'access_scope':'abstract_only','feature_comparisons':assertions}]}}
    artifacts=[]
    for role,payload in payloads.items():
        path=root/(role+'.json');path.write_text(json.dumps(payload))
        artifacts.append({'path':str(path),'role':role,'sha256':file_sha256(path)})
    revision=register_revision(root,files=[str(report)],manifest={'artifacts':artifacts},
        release={'status':'draft_review_required'},source_revisions=[{
            'revision_id':parent['revisions']['analysis'],'evidence_bundle_id':parent['bundle_id']}])
    return publish_report_bundle(root,directory,order_id=1,report_revision=revision['revision_id'])


def build(output):
    output.mkdir(parents=True,exist_ok=False)
    with tempfile.TemporaryDirectory() as tmp, pytest.MonkeyPatch.context() as patch:
        temporary=Path(tmp)
        engine,factory,root,client=setup_order(temporary,patch)
        source=root/'ptm_vector_data_normalized_phospho.tsv'
        rows=list(csv.DictReader(source.open(),delimiter='\t'))
        for row in rows:
            if row['Precursor.Id']=='p0' and row['Condition']=='5min':row['PTM_ProteinAdjusted_Log2FC']=''
            if row['Precursor.Id']=='p0' and row['Condition']=='1min':row['PTM_ProteinAdjusted_Log2FC']='0'
        rows.extend([{**r,'Precursor.Id':'p0-z3','Precursor.Charge':'3'} for r in rows if r['Precursor.Id']=='p0'])
        with source.open('w') as f:
            writer=csv.DictWriter(f,fieldnames=rows[0],delimiter='\t');writer.writeheader();writer.writerows(rows)
        publish_analysis_input(root,config={'ptm_type':'phosphorylation','analysis_mode':'full'})
        reference=temporary/'reference.json'
        reference.write_text(json.dumps({'schema_version':'canonical_pathway_reference.v1','pathways':[
            {'provider':'Synthetic','native_id':'A','taxon':'10090','release':'fixture.v1','name':'Fixture pathway A','protein_accessions':['P0','P1','P2','P3']},
            {'provider':'Synthetic','native_id':'B','taxon':'10090','release':'fixture.v1','name':'Fixture pathway B','protein_accessions':['P1']}]}))
        patch.setenv('PTM_PATHWAY_SOURCE_BUNDLE_PATH',str(reference))
        patch.setattr(routes,'get_settings',lambda:SimpleNamespace(OUTPUT_DIR=str(temporary)))
        client.app.include_router(routes.router)
        job=client.post('/orders/1/analysis-jobs',json={'comparison_models':['ksea_z.v1','ulm_t.v1','partial_linear.v1']}).json()
        asyncio.run(executor.execute_production_tmm(job['job_id'],session_factory=factory))
        runs=client.get('/orders/1/evidence-runs').json();parent_id=runs['records'][0]['bundle_id']
        parent=client.get('/orders/1/evidence-runs/'+parent_id).json()
        feature_id=client.get('/orders/1/evidence-runs/'+parent_id+'/features').json()['records'][0]['feature_id']
        directory=next(root.glob('.analysis_results/*/*/manifest.json')).parent
        bundle=bind_synthetic_report(root,directory,parent,feature_id)['bundle_id']
        base='/orders/1/evidence-runs/'+bundle
        responses={}
        def get(path):
            response=client.get(path);assert response.status_code==200,response.text
            responses[path]=response.json();return response.json()
        def get_pages(path):
            from urllib.parse import quote
            data=get(path)
            while data.get('next_cursor'):
                data=get(path+('&' if '?' in path else '?')+'cursor='+quote(data['next_cursor'],safe=''))
        get('/orders/1/evidence-runs');get(base)
        for kind in ['pathways','features','kinases','source-runs','validations','unmapped-modules','model-comparisons','mechanism-hypotheses','experiment-suggestions']:
            data=get(base+'/'+kind)
            if kind=='pathways':
                for p in data['records']:get(base+'/features?pathway_key='+p['pathway_key'])
            if kind=='model-comparisons':
                for model in data['records']:get_pages(base+'/model-results?model_id='+model['model_id'])
            if kind=='features':
                for feature in data['records']:
                    get_pages(base+'/evidence?feature_id='+feature['feature_id'])
                    get_pages(base+'/report-claims?feature_id='+feature['feature_id'])
                    for track in ['relative','unadjusted','occupancy']:
                        get(base+'/contributions?feature_id='+feature['feature_id']+'&track='+track)
        from urllib.parse import urlencode
        for pathkey in [None]+[p['pathway_key'] for p in responses[base+'/pathways']['records']]:
            for track in ['relative','unadjusted','occupancy']:
                for mode in ['inventory','all_observed','global_top_n','per_condition_top_n']:
                    for n in ([2,50] if mode.endswith('top_n') else [None]):
                        params={}
                        if pathkey:params['pathway_key']=pathkey
                        params.update(track=track,mode=mode)
                        if n is not None:params['n']=n
                        get(base+'/features?'+urlencode(params))
        # The original analysis bundle is still independently readable.
        parent_base='/orders/1/evidence-runs/'+parent_id
        for path in list(responses):
            if path.startswith(base) and 'cursor=' not in path:
                get(parent_base+path[len(base):])
        from app.api import orders
        from unittest.mock import AsyncMock
        import app.config
        patch.setattr(app.config,'get_settings',lambda:SimpleNamespace(OUTPUT_DIR=str(temporary)))
        patch.setattr(orders,'_check_order_access_async',AsyncMock())
        client.app.include_router(orders.router)
        for axis in ('adjusted','unadjusted'):
            get(f'/orders/1/vector-plot-data?mode=per_condition_top_n&n=50&axis={axis}')
        export=client.get(base+'/inventory-export')
        assert export.status_code==200 and 'PRIVATE' not in export.text
        (output/'inventory-export.jsonl').write_bytes(export.content)
        (output/'responses.json').write_text(json.dumps({'bundle_id':bundle,'parent_bundle_id':parent_id,
            'evidence_feature_id':feature_id,'responses':responses},indent=2))
        from ptm_shared.report_revision import file_sha256
        source_files=['frontend/src/components/SignalingEvidenceExplorer.tsx','api-server/app/api/signaling_explorer.py',
            'ptm_shared/signaling_evidence_index.py','ptm_shared/run_evidence_bundle.py','ptm_shared/report_explorer_index.py',
            'scripts/build_explorer_fixture.py','scripts/validate_explorer_browser.mjs']
        source_files=sorted(set(source_files) | {
            str(p.relative_to(ROOT)) for directory,pattern in (
                ('ptm_shared','*.py'),('api-server/app','*.py'),('frontend/src','*.tsx'),
                ('frontend/src','*.ts'),('frontend/src','*.css'),('frontend/tests','explorer.browser.*'))
            for p in (ROOT/directory).rglob(pattern) if p.is_file()})
        (output/'fixture-manifest.json').write_text(json.dumps({'source_revision':bundle,
            'kind':'synthetic_actual_api_worker_responses','sha256':file_sha256(output/'responses.json'),
            'source_sha256':{name:file_sha256(ROOT/name) for name in source_files},
            'production_order_verified':False},indent=2))
        asyncio.run(engine.dispose())


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True)
    build(Path(parser.parse_args().output))
