"""Synthetic display scale experiment; never a biological benchmark. Requires a fresh output directory."""
import sys,time,csv,json,resource,platform
from pathlib import Path
from ptm_shared.vector_columnar import publish_vector_columnar,VectorColumnar
import argparse
parser=argparse.ArgumentParser()
parser.add_argument('rows',type=int)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args();n=args.rows;root=args.output
if n < 4 or n % 4: raise ValueError('rows must be a positive multiple of four')
root.mkdir(parents=True,exist_ok=False)
path=root/'ptm_vector_data_normalized_phospho.tsv'
with path.open('w') as f:
 w=csv.writer(f,delimiter='\t');w.writerow(['Gene.Name','PTM_Position','Precursor.Id','Precursor.Charge','Modified.Sequence','Protein.Group','FASTA_Taxonomy_ID','Condition','PTM_ProteinAdjusted_Log2FC','PTM_Unadjusted_Log2FC','Protein_Log2FC'])
 for i in range(n):
  v='' if i%97==0 else (-40 if i==1 else 40 if i==2 else (i%401-200)/50)
  w.writerow([f'Rps{i//4}','S2',f'p{i//4}',2,'AS(UniMod:21)AA',f'P{i//4}',10090,f'{[1,5,10,20][i%4]}min',v,v,(i%101-50)/20])
t=time.perf_counter();m=publish_vector_columnar(root,'_phospho');ingest=time.perf_counter()-t
s=VectorColumnar(root,'_phospho');t=time.perf_counter();counts=s.manifest_counts();count_time=time.perf_counter()-t
t=time.perf_counter();d=s.density();density_time=time.perf_counter()-t
assert counts['source_rows']==n and counts['identified_features']==n//4
assert d['count']==n-(n+96)//97 and d['bounds'][2:]==[-40,40]
page=s.feature_page(limit=200);r=s.trajectories(page['feature_ids']);assert len(r)==800
out={'rows':n,'ingest_s':ingest,'count_s':count_time,'density_s':density_time,'density_response_bytes':len(json.dumps(d).encode()),'parquet_bytes':(root/m['filename']).stat().st_size,'peak_rss_native':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'counts':counts,'density_count':d['count'],'bounds':d['bounds'],'platform':platform.platform(),'python':platform.python_version(),'schema_version':m['schema_version'],'fresh_publication':True}
(root/'measurement.json').write_text(json.dumps(out,indent=2));print(json.dumps(out));s.close()
