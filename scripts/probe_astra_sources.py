"""Bounded, read-only live provider smoke using actual mapped accessions."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pandas as pd
from ptm_shared.astra_sources import resolve_sources
from ptm_shared.generic_kinase import fasta_taxonomy
from ptm_shared.report_compatible_quantification import read_fasta
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--mapping',type=Path,required=True);p.add_argument('--fasta',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
taxa=fasta_taxonomy(a.fasta);rows=pd.read_csv(a.mapping).drop_duplicates('mapped_accession').head(3).to_dict('records')
for r in rows:r['fasta_taxonomy_id']=taxa.get(r['mapped_accession'])
pin=resolve_sources(a.output,rows,read_fasta(a.fasta),'phosphorylation')
report={'pin_sha256':pin['pin_sha256'],'live_network':True,'requests':[{'provider':r['provider'],'status':r['status'],'reason':r.get('reason'),'response_sha256':r.get('response_sha256')} for r in pin['queries']]}
(a.output/'live_smoke.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
