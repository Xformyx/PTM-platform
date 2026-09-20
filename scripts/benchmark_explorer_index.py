"""Synthetic full inventory query benchmark; never an algorithm accuracy test."""
import argparse
import json
import os
import platform
import resource
import tempfile
import time
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ptm_shared.feature_identity import canonical_feature_identity
from ptm_shared.signaling_evidence_index import build_explorer_index, explorer_page


def run(output, count):
    output.mkdir(parents=True,exist_ok=False)
    conditions=['1min','5min','15min','30min','60min','180min']
    manifest={'conditions':conditions,'analysis_scope':'full_eligible','input_scope':{'analysis_mode':'full'},
              'candidate_modules':[],'reference_snapshots':{}}
    identities={};series={}
    for i in range(count):
        identity=canonical_feature_identity({'Gene.Name':f'G{i}','PTM_Position':'S2','Precursor.Id':f'precursor-{i}',
            'Precursor.Charge':'2','Modified.Sequence':'AS(UniMod:21)K','Protein.Group':f'P{i}','FASTA_Taxonomy_ID':'10090'})
        fid=identity['feature_id'];identities[fid]=identity
        series[fid]={c:(i%19-9)*.2+j*.01 for j,c in enumerate(conditions) if i%7 or j!=2}
    inputs={'features':identities,'ptm_timeseries':series,'ptm_qvalues':{},'occupancy_timeseries':{},'occupancy_qvalues':{}}
    reference=output/'reference.json'
    reference.write_text(json.dumps({'schema_version':'canonical_pathway_reference.v1','pathways':[
        {'provider':'Synthetic','native_id':str(j),'taxon':'10090','release':'synthetic.v1','name':f'Overlapping pathway {j}',
         'protein_accessions':[f'P{i}' for i in range(j,count,10)]} for j in range(20)]}))
    scores={'effective_config':{},'relative':{},'occupancy':{}}
    result={'coverage':{'source_rows':count*6,'identified_features':count,'eligible_features':count},'kinase_scores':[]}
    start=time.perf_counter();summary=build_explorer_index(output,manifest,inputs,scores,{},result,pathway_reference=reference)
    build_seconds=time.perf_counter()-start
    durations={};bytes_by_query={}
    for name,opts in [('overview',{'kind':'pathways'}),('features',{'kind':'features','limit':50}),
                      ('top_n',{'kind':'features','mode':'per_condition_top_n','n':50,'track':'relative','limit':50})]:
        timing=[]
        for _ in range(10):
            begin=time.perf_counter();page=explorer_page(output,'synthetic-scale',**opts);timing.append(time.perf_counter()-begin)
        durations[name]={'first_seconds':timing[0],'warm_p95_seconds':sorted(timing[1:])[-1]}
        bytes_by_query[name]=len(json.dumps(page).encode())
    page=explorer_page(output,'synthetic-scale',kind='features',limit=500)
    assert page['total_count']==count
    import duckdb
    with duckdb.connect() as db:
        read=db.read_parquet(str(output/'explorer_records.parquet'));read.create_view('r')
        exact=db.execute("SELECT count(*),count(distinct feature_id) FROM r WHERE kind='features'").fetchone()
        assert exact==(count,count)
    artifact={'schema_version':'explorer_query_benchmark.v1','fixture':'synthetic', 'feature_count':count,
        'feature_condition_rows':count*6,'finite_observations':sum(map(len,series.values())),
        'preserved_features':page['total_count'],'build_seconds':build_seconds,'queries':durations,'response_bytes':bytes_by_query,
        'peak_rss_native':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'rss_unit':'bytes' if sys.platform=='darwin' else 'KiB',
        'platform':platform.platform(),'cpu_count':os.cpu_count(),'python':platform.python_version(),
        'scope':'derived index generation/query only; no model runtime, network, browser heap, or operational concurrency claim'}
    (output/'benchmark.json').write_text(json.dumps(artifact,indent=2));print(json.dumps(artifact))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--features',type=int,default=120000)
    args=parser.parse_args();run(Path(args.output),args.features)
