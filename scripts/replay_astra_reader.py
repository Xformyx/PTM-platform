"""Replay only Round07 reader outputs with a package's own code and saved tables.

Full scientific replay remains available as package/replay.py. This command checks
the changed serialization boundary without recomputing quantification or sources.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

PROGRAM = r'''
import hashlib,json,socket,sys,shutil
sys.dont_write_bytecode=True
from pathlib import Path
root=Path(sys.argv[1]).resolve();output=Path(sys.argv[2]).resolve()
if output==root or root in output.parents:raise ValueError('Never overwrite package')
sys.path.insert(0,str(root/'reproducibility/code'))
def forbidden(*a,**k):raise AssertionError('Network forbidden during reader replay')
socket.create_connection=forbidden
import urllib.request
urllib.request.urlopen=forbidden
import pandas as pd
from ptm_shared.astra_reader import build_reader_tables,validate_reader,write_reader
from ptm_shared.astra_package import write_tables
assert str(root/'reproducibility/code') in sys.modules['ptm_shared.astra_reader'].__file__
dictionary=json.loads((root/'reproducibility/data_dictionary.json').read_text())
access_revision=False
revision_path=root/'reproducibility/temporal_reader_revision.json'
if revision_path.is_file():
    access_revision=json.loads(revision_path.read_text()).get('operation')=='whole_evidence_access_revision'
names=['quant/summary','quant/comparisons','science/inference_results',
       'reader_adapter/form_identity','reader_adapter/form_contrasts',
       'reader_adapter/precursor_membership','reader_adapter/study_metadata']
if hasattr(sys.modules['ptm_shared.astra_reader'],'phosx_time_views'):
    names += ['science/site_identity_audit','science/specificity_scores',
              'kinase/method_executions','kinase/method_scores','kinase/method_membership','kinase/kinase_candidate_edges']
if hasattr(sys.modules['ptm_shared.astra_reader'],'TEMPORAL_SOURCE_TABLES'):
    names += [name for name in sys.modules['ptm_shared.astra_reader'].TEMPORAL_SOURCE_TABLES if name+'.csv' in dictionary]
names=list(dict.fromkeys(names))
if access_revision:names=['reader/packet']
tables={name:pd.read_csv(root/(name+'.csv'),float_precision='round_trip',low_memory=False,
    dtype={k:'str' for k,v in dictionary[name+'.csv']['dtypes'].items() if v in {'str','object'}}) for name in names}
design=json.loads((root/'study/study_design.json').read_text())
snapshot=json.loads((root/'study/user_input_snapshot.json').read_text())
if access_revision:
    from ptm_shared.astra_evidence_catalog import attach_access
    reader={'reader/packet':tables['reader/packet'].copy()};attach_access(reader)
else:reader=build_reader_tables(tables,design,snapshot)
if not access_revision and (root/'references/finding_literature_pin.json').is_file():
    from ptm_shared.astra_literature import apply
    pin=json.loads((root/'references/finding_literature_pin.json').read_text())
    selection=json.loads((root/'references/literature_pin.json').read_text())
    apply(reader,pin,snapshot,selection)
validation=({'scope':'M1 catalog/index/links from saved sources; prior interpretation not replayed'} if access_revision else validate_reader({**tables,**reader}))
output.mkdir(parents=True,exist_ok=False);write_tables(reader,output)
if access_revision:shutil.copyfile(root/'reader/READ_ME.md',output/'reader/READ_ME.md')
options={'source_root':root,'access_only':access_revision} if hasattr(sys.modules['ptm_shared.astra_reader'],'write_evidence_access') else {}
files=write_reader(output,{**tables,**reader},**options)+[name+'.csv' for name in reader]
results=[]
for name in files:
    a,b=[hashlib.sha256((p/name).read_bytes()).hexdigest() for p in (root,output)]
    if a!=b:raise ValueError('Reader byte mismatch: '+name)
    results.append({'file':name,'sha256':a,'byte_equal':True})
result={'passed':True,'scope':('M1_access_projection_from_saved_sources' if access_revision else 'reader_and_optional_frozen_literature_from_archived_adapter_and_scientific_tables'),
        'previous_reader_interpretation_rebuilt':not access_revision,
        'catalog_available':(root/'reader/evidence_catalog.json').is_file(),
        'scientific_requantification':False,'network_requests':0,'repository_code_used':False,
        'run_id':json.loads((root/'provenance.json').read_text())['run_id'],
        'files':results,'validation':validation}
(output/'READER_REPLAY_VALIDATION.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
'''


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--package',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    env={k:v for k,v in os.environ.items() if k!='PYTHONPATH'}
    completed=subprocess.run([sys.executable,'-I','-c',PROGRAM,str(a.package.resolve()),str(a.output.resolve())],
                             cwd='/tmp',env=env,check=True)
    return completed.returncode


if __name__=='__main__':raise SystemExit(main())
