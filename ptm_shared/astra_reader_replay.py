"""Common saved-table reader replay. No scientific or retrieval engine is run."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

PROGRAM = r'''
import hashlib,json,socket,sys,shutil
sys.dont_write_bytecode=True
from pathlib import Path
root=Path(sys.argv[1]).resolve();requested=Path(sys.argv[2]).absolute()
if '..' in requested.parts or any(p.is_symlink() for p in [requested,*requested.parents]):raise ValueError('Unsafe output path or symlink')
output=requested.resolve()
if output.exists():raise ValueError('Output must be a new directory')
manifest_path=root/'manifest.json'
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()
manifest_sha=sha(manifest_path);manifest=json.loads(manifest_path.read_text())
def verify_manifest():
    if sha(manifest_path)!=manifest_sha:raise ValueError('Source manifest changed')
    for name,entry in manifest['files'].items():
        relative=Path(name);p=root/relative
        if relative.is_absolute() or '..' in relative.parts or not p.resolve().is_relative_to(root) or p.is_symlink():raise ValueError('Unsafe manifest path')
        if not p.is_file() or p.stat().st_size!=entry['bytes'] or sha(p)!=entry['sha256']:raise ValueError('Source hash mismatch: '+name)
verify_manifest()
source_paths={str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()}

if output==root or root in output.parents:raise ValueError('Never overwrite package')
sys.path.insert(0,str(root/'reproducibility/code'))
def forbidden(*a,**k):raise AssertionError('New network/scientific/retrieval execution forbidden during reader replay')
socket.create_connection=forbidden
socket.socket.connect=forbidden
socket.socket.connect_ex=forbidden
import urllib.request
urllib.request.urlopen=forbidden
import pandas as pd
from ptm_shared.astra_reader import build_reader_tables,validate_reader,write_reader
from ptm_shared.astra_package import write_tables
code_root=(root/'reproducibility/code').resolve()
reader_module=Path(sys.modules['ptm_shared.astra_reader'].__file__).resolve()
if not reader_module.is_relative_to(code_root):raise ValueError('Reader module outside archive code root')
import importlib,subprocess
blocked=[]
for module,names in {
    'contrast_quantification':['quantify_contrasts'], 'generic_workflow':['calculate'],
    'astra_package':['compute_science'], 'official_method_tracks':['execute_tracks'],
    'astra_literature':['collect','_runtime'], 'astra_literature_review':['execute_review','run_requested_review'],
    'finding_literature':['retrieve_finding_literature'], 'astra_discovery':['discover'],
}.items():
    if not (code_root/'ptm_shared'/(module+'.py')).is_file():continue
    m=importlib.import_module('ptm_shared.'+module)
    for name in names:
        if hasattr(m,name):setattr(m,name,forbidden);blocked.append(module+'.'+name)
subprocess.Popen=forbidden

dictionary=json.loads((root/'reproducibility/data_dictionary.json').read_text())
access_revision=False
whole_revision=False
review_revision=False
execution_revision=False
saved_reader_revision=False
review_execution=None
revision_path=root/'reproducibility/temporal_reader_revision.json'
if revision_path.is_file():
    operation=json.loads(revision_path.read_text()).get('operation')
    saved_reader_revision=operation in {'saved_temporal_reader_revision','saved_reader_display_revision'}
    access_revision=operation=='whole_evidence_access_revision'
    whole_revision=operation=='whole_reader_evidence_revision'
    review_revision=operation=='literature_review_plan_revision'
    execution_revision=operation=='literature_subject_execution_revision'
    review_revision=review_revision or execution_revision
names=['quant/summary','quant/comparisons','science/inference_results',
       'reader_adapter/form_identity','reader_adapter/form_contrasts',
       'reader_adapter/precursor_membership','reader_adapter/study_metadata']
if hasattr(sys.modules['ptm_shared.astra_reader'],'phosx_time_views'):
    names += ['science/site_identity_audit','science/specificity_scores',
              'kinase/method_executions','kinase/method_scores','kinase/method_membership','kinase/kinase_candidate_edges']
if hasattr(sys.modules['ptm_shared.astra_reader'],'TEMPORAL_SOURCE_TABLES'):
    names += [name for name in sys.modules['ptm_shared.astra_reader'].TEMPORAL_SOURCE_TABLES if name+'.csv' in dictionary]
if (root/'reproducibility/code/ptm_shared/astra_reader_full.py').is_file():
    names += [n[:-4] for n in dictionary if not n.startswith(('reader/',))]
names=list(dict.fromkeys(names))
if access_revision:names=['reader/packet']
if whole_revision:names=[n[:-4] for n in dictionary if not n.startswith(('reader/full_','reader/evidence_'))]
if review_revision:names=['reader/packet','reader/cards','reader/findings','reader/coverage','reader/full_question_links']
if saved_reader_revision:
    # A reader revision retains an already selected reader and its frozen pin.
    # Re-selecting cards with newer adapters can invalidate that recorded pin.
    names += ['reader/packet','reader/cards','reader/findings','reader/coverage']
# Signal views are rebuilt from registered scientific sources, never from their
# previous output copies (which can be much larger than the underlying inputs).
names=list(dict.fromkeys(n for n in names if not n.startswith('signal_flow/')))
tables={name:pd.read_csv(root/(name+'.csv'),float_precision='round_trip',low_memory=False,
    dtype={k:'str' for k,v in dictionary[name+'.csv']['dtypes'].items() if v in {'str','object'}}) for name in names}
design=json.loads((root/'study/study_design.json').read_text())
snapshot=json.loads((root/'study/user_input_snapshot.json').read_text())
if review_revision:
    from ptm_shared.astra_literature_review import attach_review_plan
    attach_review_plan(tables);reader={'reader/packet':tables['reader/packet']}
    if execution_revision:
        from ptm_shared.astra_literature_review import attach_review_execution,EXECUTION_PIN
        from ptm_shared.astra_evidence_catalog import EvidenceCatalog
        review_execution=json.loads((root/EXECUTION_PIN).read_text())
        attach_review_execution(tables,review_execution,EvidenceCatalog(root))
        reader={'reader/packet':tables['reader/packet']}
elif access_revision:
    from ptm_shared.astra_evidence_catalog import attach_access
    reader={'reader/packet':tables['reader/packet'].copy()};attach_access(reader)
elif whole_revision:
    from ptm_shared.astra_evidence_catalog import attach_access
    from ptm_shared.astra_reader_full import attach_full
    attach_access(tables);attach_full(tables)
    reader={k:tables[k] for k in ['reader/cards','reader/packet']}
elif saved_reader_revision:
    reader={k:tables[k].copy() for k in ['reader/cards','reader/packet','reader/findings','reader/coverage']}
else:reader=build_reader_tables(tables,design,snapshot)
if not (access_revision or whole_revision or review_revision) and (root/'references/finding_literature_pin.json').is_file():
    from ptm_shared.astra_literature import apply
    pin=json.loads((root/'references/finding_literature_pin.json').read_text())
    selection=json.loads((root/'references/literature_pin.json').read_text())
    apply(reader,pin,snapshot,selection)
if (root/'references/literature_subject_execution_pin.json').is_file() and hasattr(sys.modules.get('ptm_shared.astra_literature_review'),'restore_execution'):
    from ptm_shared.astra_literature_review import restore_execution
    review_execution=restore_execution(reader,root)
validation=({'scope':'M3 plan from original M1 index/M2 links; no search/model or prior literature reinterpretation'} if review_revision else {'scope':'M1 catalog/index/links from saved sources; prior interpretation not replayed'} if access_revision else validate_reader({**tables,**reader}))
output.mkdir(parents=True,exist_ok=False);write_tables(reader,output)
if review_execution is not None:(output/'references').mkdir(exist_ok=True)
if access_revision or whole_revision or review_revision:shutil.copyfile(root/'reader/READ_ME.md',output/'reader/READ_ME.md')
options={'source_root':root,'access_only':access_revision} if hasattr(sys.modules['ptm_shared.astra_reader'],'write_evidence_access') else {}
if whole_revision:options['whole_only']=True
if review_revision:options['review_plan_only']=True
if review_execution is not None:options['review_execution']=review_execution
files=write_reader(output,{**tables,**reader},**options)+[name+'.csv' for name in reader]
results=[]
for name in files:
    a,b=[hashlib.sha256((p/name).read_bytes()).hexdigest() for p in (root,output)]
    if a!=b:raise ValueError('Reader byte mismatch: '+name)
    results.append({'file':name,'sha256':a,'byte_equal':True})
result={'passed':True,'scope':('M1_access_projection_from_saved_sources' if access_revision else 'reader_and_optional_frozen_literature_from_archived_adapter_and_scientific_tables'),
        'previous_reader_interpretation_rebuilt':not (access_revision or whole_revision or review_revision or saved_reader_revision),
        'saved_reader_revision_input':saved_reader_revision,
        'literature_review_plan_rebuilt':review_revision,
        'frozen_typed_literature_rebuilt':review_execution is not None,
        'new_model_calls':0,'scientific_calls':0,'guarded_functions':blocked,
        'validated_manifest_files':len(manifest['files']),'reader_module_file':str(reader_module),
        'whole_evidence_projection_rebuilt':whole_revision,
        'projection_inputs':'saved scientific/adapter/card rows and existing question matching; no full_* outputs as inputs' if whole_revision else None,
        'catalog_available':(root/'reader/evidence_catalog.json').is_file(),
        'scientific_requantification':False,'network_requests':0,'repository_code_used':False,
        'run_id':json.loads((root/'provenance.json').read_text())['run_id'],
        'files':results,'validation':validation}
verify_manifest()
if source_paths!={str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()}:raise ValueError('Source file population changed')
for name,module in list(sys.modules.items()):
    if name.startswith('ptm_shared.') and getattr(module,'__file__',None) and not Path(module.__file__).resolve().is_relative_to(code_root):raise ValueError('Non-archive module: '+name)
(output/'READER_REPLAY_VALIDATION.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
'''


def run_replay(package, output):
    root=Path(package).resolve()
    # Prefer the archive's own orchestration version. Old ZIPs retain their own
    # reader modules while the repository runner supplies only the saved-row harness.
    if (root/'reproducibility/code/ptm_shared/astra_reader_replay.py').is_file():
        program="import sys;sys.dont_write_bytecode=True;from pathlib import Path;sys.path.insert(0,str(Path(sys.argv[1])/'reproducibility/code'));from ptm_shared.astra_reader_replay import PROGRAM;exec(compile(PROGRAM,'<archive reader replay>','exec'))"
    else:
        program=PROGRAM
    env={k:v for k,v in os.environ.items() if k!='PYTHONPATH'}
    return subprocess.run([sys.executable,'-I','-B','-c',program,str(root),str(Path(output).absolute())],
                          cwd=root.parent,env=env,check=True).returncode


def main(package=None):
    parser=argparse.ArgumentParser(description=__doc__)
    if package is None:parser.add_argument('--package',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    return run_replay(package or args.package,args.output)


ENTRYPOINT = '''"""Rebuild saved readers using this archive's code; no scientific replay."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
root=Path(__file__).resolve().parent
sys.path.insert(0,str(root/'reproducibility/code'))
from ptm_shared.astra_reader_replay import main
if __name__=='__main__':raise SystemExit(main(root))
'''


def write_entrypoint(directory):
    import json
    root=Path(directory)
    (root/'reader_replay.py').write_text(ENTRYPOINT,encoding='utf-8')
    capabilities={'schema_version':'astra_replay_capabilities.v1',
        'catalog_query':'saved evidence access; no regeneration',
        'reader_replay':{'entrypoint':'python reader_replay.py --output <new-directory>',
            'inputs':'archive code and saved tables; restricted specificity matrix not required',
            'output':'reader artifacts and READER_REPLAY_VALIDATION.json; exact archived reader bytes',
            'new_science_or_retrieval':False},
        'current_code_revision':'separate immutable repository revision; not archive byte replay',
        'full_scientific_replay':'python replay.py --output <new-directory>; conditional external resources and scientific calculation'}
    (root/'reproducibility/replay_capabilities.json').write_text(json.dumps(capabilities,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    note='\n\nReader-only replay: `python reader_replay.py --output <new-directory>` uses archive code and saved tables, without restricted specificity resources or new science/search/model calls. Query, reader replay, current-code immutable revision and full scientific replay are distinct. See [capabilities](reproducibility/replay_capabilities.json).\n'
    start=root/'START_HERE_ASTRA.md'
    if start.is_file() and note not in start.read_text():start.write_text(start.read_text()+note,encoding='utf-8')
