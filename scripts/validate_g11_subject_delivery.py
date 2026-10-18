"""Local delivery integration with frozen scientific stage doubles, never compute.

Runs the real dispatch attachment, worker engine dispatcher, ordinary builder,
atomic publisher and authenticated download handler. DB/queue and already computed
scientific stages are isolated doubles; this is not an operational UI/Celery test.
"""
import argparse
import asyncio
import hashlib
from contextlib import ExitStack
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from ptm_shared.annotation_registry import digest
from ptm_shared.generic_workflow import json_write
from ptm_shared.astra_reader_revision import read_tables
from ptm_shared import astra_package as package, astra_evidence_v6 as engine
from ptm_shared import astra_literature_review as review


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--pin-package',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();source=a.source.resolve();origin=a.pin_package.resolve();out=a.output.resolve();started=time.monotonic()
    out.mkdir(parents=True,exist_ok=False)
    baseline=json.loads((source/'manifest.json').read_text())['files']
    baseline_run=json.loads((source/'provenance.json').read_text())['run_id']
    for name,item in baseline.items():assert digest(source/name)==item['sha256'],name
    config=json.loads((source/'reproducibility/replay_config.json').read_text())
    pin=json.loads((origin/review.EXECUTION_PIN).read_text())
    order_root=out/'order';registered=order_root/'enrichment_free_runs'/origin.name
    shutil.copytree(origin,registered)
    request={'mode':'reuse_frozen','requested_subject_ids':pin['requested_subject_ids'],
        'request_reason':'G11 follow-up 01: explicit historical frozen delivery, no new retrieval',
        'max_subjects':pin['max_subjects'],'budget':pin['execution_contract']['budget'],
        'pin_ref':{'run_id':origin.name,'sha256':pin['sha256']}}
    context=deepcopy(config['context']);context['refresh_references']=False;context[review.REQUEST_FIELD]=request
    snapshot=deepcopy(config['snapshot']);snapshot['original']['analysis_context']=context
    tables=read_tables(source)
    # These are archive-bound outputs at the existing calculation/cache boundary,
    # not implementations of a second scientific engine.
    scientific={k:v for k,v in tables.items() if not k.startswith(('reader/evidence_','reader/full_','reader/literature_review_'))}
    readiness=json.loads((source/'evidence/readiness.json').read_text())
    normalization=json.loads((source/'methods/normalization.json').read_text())
    motif=json.loads((source/'methods/motif.json').read_text())
    sources=json.loads((source/'references/source_pin.json').read_text())
    counts=dict(zip(tables['evidence/coverage_funnel'].metric,tables['evidence/coverage_funnel']['count']))
    task={'order_code':'order','experimental_context':context,'user_input_snapshot':snapshot,'literature_pin':config['literature'],
        'finding_literature_pin':json.loads((source/'references/finding_literature_pin.json').read_text()),
        'source_pin_sha256':sources['pin_sha256'],'species_tax_id':config['design']['study']['taxonomy_id'],
        'species':config['snapshot']['original']['species'],'reference_root':str(out/'reference'),'run_generation':0}
    for key,field in {'PR':'pr_matrix_path','PG':'pg_matrix_path','FASTA':'fasta_path'}.items():
        task[field]=str(source/config['inputs'][key])
    if 'SPECIFICITY_RESTRICTED' in config['inputs']:task['specificity_manifest_path']=str(source/config['inputs']['SPECIFICITY_RESTRICTED'])
    protected=[n for n in baseline if n.startswith(('quant/','science/','kinase/','temporal/','figures/'))]
    dictionary=json.loads((source/'reproducibility/data_dictionary.json').read_text())
    protected+= [n for n in dictionary if not n.startswith(('reader/','study/'))]
    protected += ['reader/cards.csv','reader/findings.csv','reader/coverage.csv',
                  'references/literature_pin.json','references/finding_literature_pin.json','references/source_pin.json',
                  'reader/literature_search.csv','reader/literature_sources.csv','reader/literature_comparisons.csv']
    protected=sorted(set(protected))
    original_writer=package.write_tables
    def saved_serialization(frames,directory,**kwargs):
        metadata=original_writer(frames,directory,**kwargs)
        for name,frame in frames.items():
            path=name+'.csv'
            if path not in protected:continue
            pd.testing.assert_frame_equal(frame.reset_index(drop=True),tables[name].reset_index(drop=True),check_dtype=False,check_exact=True)
            # Keep the archive's original serialization after exact value/NA check.
            shutil.copyfile(source/path,Path(directory)/path)
        return metadata
    original_artifacts=engine.write_artifacts
    def artifacts(directory,*args):
        original_artifacts(directory,*args)
        for name in protected:
            if name.startswith(('science/','kinase/','temporal/')) and not name.endswith('.csv'):
                target=Path(directory)/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/name,target)
    def figures(_tables,directory,_design):
        shutil.copytree(source/'figures',Path(directory)/'figures',dirs_exist_ok=True)
    def quant_reuse(_inputs,_design,ctx,_root,fingerprint,**kwargs):
        policy=ctx['normalization_policy']
        norm=normalization['primary'] if policy==context['normalization_policy'] else normalization['sensitivity']
        return ({k[6:]:v for k,v in tables.items() if k.startswith('quant/')},norm,deepcopy(readiness)),{
            'status':'validated_archive_stage_double','source_run_id':baseline_run,'fingerprint':fingerprint,'calculation_executed':False}
    def saved_science(*args,**kwargs):
        return deepcopy(scientific),normalization['primary'],normalization['sensitivity'],deepcopy(readiness),motif,counts
    settings=SimpleNamespace(OUTPUT_DIR=str(out),REFERENCE_DIR=str(out/'reference'))
    from app.api import orders
    from ptm_shared.enrichment_free_workflow import run_primary_analysis,recorded_run
    order=SimpleNamespace(**{**snapshot['original'],'id':89,'order_code':'order',
        'analysis_context':context,**{k:task.get(k) for k in ['pr_matrix_path','pg_matrix_path','fasta_path',*engine.INPUT_FIELDS.values()]}})
    with ExitStack() as stack:
        for name in ['socket.create_connection','socket.socket.connect','urllib.request.urlopen','ptm_shared.astra_literature.collect',
                     'ptm_shared.astra_literature._runtime','ptm_shared.astra_literature_review.execute_review',
                     'ptm_shared.official_method_tracks.execute_tracks','ptm_shared.kinase_specificity.score_sites',
                     'ptm_shared.astra_evidence_v6.calculate']:
            stack.enter_context(patch(name,side_effect=AssertionError('Forbidden during frozen integration: '+name)))
        stack.enter_context(patch.object(orders,'get_settings',return_value=settings))
        # Dispatch attachment runs real normalization/preflight. Its stored Order
        # record is a local DB double, not the operating Order 89.
        task=orders._attach_enrichment_free_profile(order,task)
        assert task['experimental_context'][review.REQUEST_FIELD]==request
        task=json.loads(json.dumps(task))  # actual queue wire shape
        stack.enter_context(patch.object(package,'quant_cached',side_effect=quant_reuse))
        stack.enter_context(patch.object(package,'mapped_sites',return_value=(tables['quant/site_mapping'],None,{})))
        stack.enter_context(patch.object(package,'resolve_sources',return_value=sources))
        stack.enter_context(patch.object(package,'compute_science',side_effect=saved_science))
        stack.enter_context(patch.object(package,'write_tables',side_effect=saved_serialization))
        stack.enter_context(patch.object(package,'figure_packet',side_effect=figures))
        stack.enter_context(patch.object(engine,'write_artifacts',side_effect=artifacts))
        result=run_primary_analysis(89,task,order_root,progress=lambda s:print(s,flush=True))
        root=order_root/'enrichment_free_runs'/result['run_id']
        record=recorded_run(order_root)
        class DB:
            async def execute(self,*args):return self
            def scalar_one_or_none(self):return order
        async def access(*args):return None
        stack.enter_context(patch.object(orders,'_check_order_access_async',side_effect=access))
        response=asyncio.run(orders.get_enrichment_free_evidence(89,'astra',DB(),SimpleNamespace(id=1)))
        archive=Path(response.path)
        assert archive==order_root/record['artifacts']['astra']['path']
        assert digest(archive)==record['artifacts']['astra']['sha256']
        downloaded=out/'DOWNLOADED.zip';sent_hash=hashlib.sha256();sent_bytes=0
        async def stream_download():
            nonlocal sent_bytes
            with downloaded.open('wb') as handle:
                async def send(message):
                    nonlocal sent_bytes
                    if message['type']=='http.response.start':assert message['status']==200
                    if message['type']=='http.response.body':
                        data=message.get('body',b'');handle.write(data);sent_hash.update(data);sent_bytes+=len(data)
                await response({'type':'http','method':'GET','headers':[]},None,send)
        asyncio.run(stream_download())
        assert sent_hash.hexdigest()==digest(archive) and sent_bytes==archive.stat().st_size
    for name in protected:assert digest(source/name)==digest(root/name),name
    for name,item in baseline.items():assert digest(source/name)==item['sha256'],name
    env={k:v for k,v in os.environ.items() if k!='PYTHONPATH'}
    replay=subprocess.run([sys.executable,'scripts/replay_astra_reader.py','--package',str(root),'--output',str(out/'offline-reader')],env=env,capture_output=True,text=True)
    (out/'REPLAY.log').write_text(replay.stdout+replay.stderr)
    if replay.returncode:raise RuntimeError('Offline reader replay failed; see REPLAY.log')
    replay_result=json.loads((out/'offline-reader/READER_REPLAY_VALIDATION.json').read_text())
    report={'scope':'local dispatch/builder/publish/download integration; DB/queue and scientific stages doubled using validated archive rows',
        'operating_order_verified':False,'scientific_calculation_calls':0,'new_rag_model_calls':0,'network_calls':0,
        'baseline_run':baseline_run,'source_execution_run':origin.name,'run_id':result['run_id'],
        'package_root':str(root),'zip':str(archive),'zip_sha256':digest(archive),'download_sha256':digest(downloaded),
        'binding':result['analysis_readiness']['literature_subject_review'],
        'download_transport':'real FileResponse ASGI body streamed; DB/auth/queue isolated doubles',
        'download_bytes':sent_bytes,'elapsed_seconds':round(time.monotonic()-started,3),
        'preserved_files':{name:digest(root/name) for name in protected},'reader_replay':replay_result}
    json_write(out/'RESULTS.json',report);print(json.dumps({'run_id':result['run_id'],'passed':True}),flush=True)


if __name__=='__main__':main()
