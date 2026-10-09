"""Recompute archived PhosX evidence with the identical external resource.

Quantification, source acquisition and literature/LLM comparison are not rerun.
This is conditional method replay, distinct from stored-result reader replay.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys

PROGRAM=r'''
import json,sys,socket,os,hashlib
from pathlib import Path
root=Path(sys.argv[1]).resolve();manifest=Path(sys.argv[2]).resolve();output=Path(sys.argv[3]).resolve()
if output==root or root in output.parents:raise ValueError('Never overwrite source package')
code=root/'reproducibility/code';sys.path.insert(0,str(code));os.environ['PYTHONPATH']=str(code)
def forbidden(*a,**k):raise AssertionError('Network forbidden during conditional method replay')
socket.create_connection=forbidden
import urllib.request,requests
urllib.request.urlopen=forbidden;requests.sessions.Session.request=forbidden
import pandas as pd
from ptm_shared import astra_evidence_v6 as engine
from ptm_shared.astra_package import validate_package
from ptm_shared.astra_reader_revision import read_tables
from ptm_shared.official_method_tracks import execute_tracks
assert str(code) in engine.__file__
validate_package(root);config=json.loads((root/'reproducibility/replay_config.json').read_text())
required=config['required_external_resources']['specificity_manifest_sha256']
if hashlib.sha256(manifest.read_bytes()).hexdigest()!=required:raise ValueError('External specificity manifest hash mismatch')
inputs={k:root/v for k,v in config['inputs'].items()};inputs['_LOCAL_SPECIFICITY']=manifest
context=config['context'];design=config['design'];tables=read_tables(root)
_,reference=engine.normalized_reference(inputs,context)
context={**context,'_runtime_reference':reference}
prepared=engine.prepare_evidence({k.split('/')[-1]:v for k,v in tables.items() if k.startswith('quant/')},inputs,design,context)
canonical=prepared['_canonical_evidence'];actual=canonical['specificity_scores'];expected=tables['science/specificity_scores'].drop(columns='schema_version')
def equal(a,b):
 a=a.reset_index(drop=True).copy();b=b.reset_index(drop=True).copy()
 numeric={'score','native_score','method_p','method_q','biological_p_value',
          'ranking_statistic','eligible_site_count','universe_count','runtime_seconds'}
 for frame in [a,b]:
  # Blank textual fields are CSV nulls; numeric masks are never filled.
  for c in frame.select_dtypes(include=['object','string']).columns:frame[c]=frame[c].replace('',None)
  # Mixed method tables can retain object dtype for nullable p/q. These fields
  # have numeric semantics, unlike accession/row identifiers.
  for c in numeric & set(frame):frame[c]=pd.to_numeric(frame[c],errors='raise')
 pd.testing.assert_frame_equal(a,b,check_dtype=False,check_exact=False,atol=1e-12,rtol=1e-12)
 assert a.isna().equals(b.isna())
equal(actual,expected)
native,membership,executions=execute_tracks(tables,inputs,prepared,canonical['resource'])
old=tables['kinase/method_scores'].loc[lambda f:f.method_id.eq('PhosX_native_functions')]
output.mkdir(parents=True,exist_ok=False)
for name,table in [('specificity_scores',actual),('method_scores',native),('method_membership',membership),('method_executions',executions)]:table.to_csv(output/(name+'.csv'),index=False)
equal(native,old);equal(membership,tables['kinase/method_membership']);equal(executions,tables['kinase/method_executions'])
result={'passed':True,'scope':'archived_code_specificity_and_native_method_from_frozen_quant_tables',
 'run_id':json.loads((root/'provenance.json').read_text())['run_id'],'external_manifest_sha256':required,
 'external_resource_required':True,'quantification_recomputed':False,'reader_replay_is_separate':True,
 'network_requests':0,'permutations':context['science']['official_methods']['PhosX']['permutations'],
 'score_rows':len(actual),'native_results':len(native),'native_membership_rows':len(membership),'atol':1e-12,'rtol':1e-12}
(output/'CONDITIONAL_METHOD_REPLAY.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
'''


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--package',type=Path,required=True);p.add_argument('--specificity-manifest',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    env={k:v for k,v in os.environ.items() if k!='PYTHONPATH'}
    subprocess.run([sys.executable,'-I','-c',PROGRAM,str(a.package.resolve()),str(a.specificity_manifest.resolve()),str(a.output.resolve())],cwd='/tmp',env=env,check=True)


if __name__=='__main__':main()
