"""Round 04 local audit: reuse verified HIRc-B caches; scope live refresh to Reactome.

Other providers are explicitly not requested in this validation. This is not a
production acquisition mode. Existing SourceClient/resolve_sources do the work.
Partial refreshes must leave the last successful package pointer untouched.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import urllib.request
from unittest.mock import patch
import zipfile

from ptm_shared import astra_evidence_v6 as engine
from ptm_shared.astra_package import resolve_sources as resolve_actual
from ptm_shared.astra_sources import SourceClient,SourceRefreshIncomplete,read_source_pin,SUCCESS


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase',choices=['prepare','reuse','refresh'])
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--baseline-output',type=Path)
    p.add_argument('--reference-root',type=Path)
    p.add_argument('--g1-archive',type=Path)
    p.add_argument('--max-requests',type=int,default=20)
    p.add_argument('--seconds',type=float,default=180)
    a=p.parse_args();root=a.output.resolve()
    if a.phase=='prepare':
        root.mkdir(parents=True,exist_ok=False)
        baseline=json.loads((a.baseline_output/'enrichment_free_current.json').read_text())
        old=a.baseline_output/'enrichment_free_runs'/baseline['run_id']
        saved=json.loads((old/'reproducibility/replay_config.json').read_text())
        assert saved['engine_profile']=='astra_analysis.v6','Keep the already validated v6 engine'
        output=root/'output';output.mkdir();registry=root/'reference';registry.mkdir()
        for folder in ['.astra_stage_cache','evidence_cache']:
            shutil.copytree(a.baseline_output/folder,output/folder)
        # Preserve the old package and its pointer; do not modify the baseline directory.
        (output/'enrichment_free_current.json').write_bytes((a.baseline_output/'enrichment_free_current.json').read_bytes())
        archive=baseline['artifacts']['astra']['path'];shutil.copy2(a.baseline_output/archive,output/archive)
        prior=output/'enrichment_free_runs'/baseline['run_id'];prior.mkdir(parents=True)
        shutil.copytree(old/'references',prior/'references')
        inputs=root/'inputs';inputs.mkdir();config={}
        fields={'PR':'pr_matrix_path','PG':'pg_matrix_path','FASTA':'fasta_path',**engine.INPUT_FIELDS}
        for key,relative in saved['inputs'].items():
            if key not in fields:continue
            dest=inputs/Path(relative).name;shutil.copy2(old/relative,dest);config[fields[key]]=str(dest)
        with zipfile.ZipFile(a.g1_archive) as z:
            g1=json.loads(z.read('reproducibility/replay_config.json'))
            parity={key:hashlib.sha256(z.read(g1['inputs'][key])).hexdigest()==sha(config[fields[key]]) for key in ['PR','PG','FASTA']}
            assert all(parity.values())
        source=read_source_pin(a.reference_root,baseline['source_pin_sha256'])
        pins=registry/'source_pins';pins.mkdir();pinfile=source['pin_sha256']+'.json'
        shutil.copy2(a.reference_root/'source_pins'/pinfile,pins/pinfile)
        imported=[];client=SourceClient(registry)
        from datetime import datetime
        for query in source['queries']:
            if query.get('status') not in SUCCESS or 'parsed_rows' not in query:continue
            if hashlib.sha256(query.get('raw_response','').encode()).hexdigest()!=query.get('response_sha256'):continue
            # Populate the existing cache format from verified prior responses,
            # retaining the original retrieval age; no response is made up.
            record=copy.deepcopy(query);client.accept(record,record['parsed_rows'])
            path=registry/'source_cache'/(record['query_id']+'.json')
            timestamp=datetime.fromisoformat(record['retrieved_utc']).timestamp();os.utime(path,(timestamp,timestamp))
            imported.append(record['query_id'])
        context=saved['context'];context.update(refresh_references=False,quantitation_export_mode='astra_analysis.v6')
        config.update(experimental_context=context,species=context['study_design']['study']['species'],
            species_tax_id=str(context['study_design']['study']['taxonomy_id']),order_code='Round04_HIRcB_local',
            source_pin_sha256=source['pin_sha256'],reference_root=str(registry),user_input_snapshot=saved['snapshot'],literature_pin=saved['literature'])
        for doc in saved['literature'].get('documents',[]):
            if doc.get('content_status')=='full_text_included':
                dest=registry/'literature_objects'/doc['sha256'];dest.parent.mkdir(exist_ok=True);shutil.copy2(old/doc['package_file'],dest)
        write(root/'config.json',config)
        write(root/'baseline.json',{'run_id':baseline['run_id'],'source_pin_sha256':source['pin_sha256'],
            'g1_archive':str(a.g1_archive),'g1_archive_sha256':sha(a.g1_archive),'g1_inputs_exact':parity,
            'cache_imported_query_ids':imported,'quant_cache_origin':str(a.baseline_output/'.astra_stage_cache'),
            'original_pointer_sha256':sha(a.baseline_output/'enrichment_free_current.json'),'original_archive_sha256':sha(a.baseline_output/archive)})
        print(json.dumps({'prepared':True,'same_g1_inputs':parity,'cache_imported_queries':len(imported)}));return
    config=json.loads((root/'config.json').read_text());output=root/'output'
    pointer=output/'enrichment_free_current.json';before=pointer.read_bytes();network=[]
    config['experimental_context']['refresh_references']=a.phase=='refresh'
    config['experimental_context']['acquisition_policy']={'mode':'research_full'}
    old_pin=read_source_pin(config['reference_root'],config['source_pin_sha256'])
    old_bytes=(Path(config['reference_root'])/'source_pins'/(old_pin['pin_sha256']+'.json')).read_bytes()
    real_query=SourceClient.query;real_open=urllib.request.urlopen
    def scoped_query(client,provider,*args,**kwargs):
        original=client.fixtures
        client.fixtures=None if provider=='Reactome' else {provider:{'status':'not_run_budget','reason':'round04_validation_other_providers_not_requested'}}
        try:return real_query(client,provider,*args,**kwargs)
        finally:client.fixtures=original
    def observed_open(request,*args,**kwargs):
        network.append(request.full_url)
        if a.phase!='refresh' or not request.full_url.startswith('https://reactome.org/ContentService/data/mapping/UniProt/'):
            raise AssertionError('Unexpected network request')
        return real_open(request,*args,**kwargs)
    def resolve(*args,**kwargs):
        if a.phase=='refresh':kwargs.update(max_requests=a.max_requests,budget_seconds=a.seconds)
        return resolve_actual(*args,**kwargs)
    initial=set((output/'enrichment_free_runs').iterdir())
    with (patch.object(engine,'calculate',side_effect=AssertionError('Quantification cache miss: stop rather than requantify')),
          patch.object(SourceClient,'query',scoped_query),patch('urllib.request.urlopen',observed_open),
          patch('ptm_shared.astra_package.resolve_sources',resolve)):
        try:
            result=engine.run('round04-local',config,output,progress=lambda stage:print(stage,flush=True))
            assert a.phase=='reuse','Scoped partial refresh must not publish'
            write(root/'reuse_result.json',result)
        except SourceRefreshIncomplete:
            assert a.phase=='refresh'
            assert pointer.read_bytes()==before,'Partial refresh replaced the successful pointer'
    added=set((output/'enrichment_free_runs').iterdir())-initial;assert len(added)==1
    run_dir=added.pop();source=json.loads((run_dir/'references/source_pin.json').read_text())
    execution=json.loads((run_dir/'references/source_execution.json').read_text())
    cache=json.loads((run_dir/'reproducibility/stage_reuse.json').read_text())
    assert all(v['status']=='reused' for v in cache.values())
    assert (Path(config['reference_root'])/'source_pins'/(old_pin['pin_sha256']+'.json')).read_bytes()==old_bytes
    reactome=[q for q in source['queries'] if q['provider']=='Reactome' and not q.get('retained_from_prior_pin')]
    targets=set();by_status={};cache_hits=0
    for q in reactome:
        ids=set(q['query'].get('accessions',[]))|({q['query']['accession']} if q['query'].get('accession') else set())
        targets|=ids;by_status[q['status']]=by_status.get(q['status'],0)+len(ids)
        if q.get('cache_hit'):cache_hits+=len(ids)
    edges=lambda s:{(r.get('accession'),r['record'].get('stId')) for r in s.get('context',[]) if r['provider']=='Reactome'}
    new_edges=edges(source)-edges(old_pin)
    write(root/(a.phase+'_validation.json'),{'run_id':run_dir.name,'source_execution':execution,'quant_cache':cache,
        'validation_budget':{'max_requests_per_provider':a.max_requests,'seconds_per_provider':a.seconds},
        'reactome_target_accessions':len(targets),'reactome_accessions_by_status':by_status,'reactome_cache_reused_accessions':cache_hits,
        'network_attempts':len(network),'network_scope':'Reactome only in refresh; other providers explicitly not requested',
        'new_reactome_accession_pathway_pairs':sorted(new_edges),'new_reactome_pair_count':len(new_edges),
        'previous_pin_bytes_preserved':True,'successful_pointer_preserved':pointer.read_bytes()==before,
        'published':(run_dir/'manifest.json').is_file(),'run_directory':str(run_dir)})
    print(json.dumps({'phase':a.phase,'run_id':run_dir.name,'execution_status':execution['status'],'Reactome':by_status,'new_pairs':len(new_edges),'network_attempts':len(network)}))


if __name__=='__main__':main()
