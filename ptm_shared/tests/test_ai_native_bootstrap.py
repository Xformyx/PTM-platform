import json
import os
from pathlib import Path
import subprocess
import sys
import pandas as pd
import pytest
from ptm_shared import official_method_tracks as native


def scientific():
    return {'quant/comparisons':pd.DataFrame([{'form_id':'f','contrast_id':'c','included':True,'A':1.25}]),
        'science/site_identity_audit':pd.DataFrame([{'form_id':'f','site_id':'s','measurement_group_id':'g','site_attribution_eligible':True}]),
        'science/specificity_scores':pd.DataFrame([{'form_id':'f','site_id':'s','specificity_id':'sp','kinase_accession':'K','status':'scored','sequence_window':'AAAAASAAAA'}]),
        'kinase/kinase_candidate_edges':pd.DataFrame([{'specificity_id':'sp','edge_type':'experimental_specificity_prediction','candidate_id':'k'}])}


def test_worker_child_uses_own_bundle_without_pythonpath(tmp_path,monkeypatch):
    package=tmp_path/'bundle with spaces'/'ptm_shared';package.mkdir(parents=True)
    (package/'__init__.py').write_text('')
    marker=tmp_path/'bootstrap.json'
    adapter=package/'phosx_activity_adapter.py'
    adapter.write_text('import json,sys\nfrom pathlib import Path\nPath('+repr(str(marker))+').write_text(json.dumps({"file":__file__,"args":sys.argv[1:]}))\nraise SystemExit(3)\n')
    # Simulate the production module having been loaded from this archive root.
    monkeypatch.setattr(native,'__file__',str(package/'official_method_tracks.py'))
    meta=tmp_path/'resource.json';meta.write_text(json.dumps({'adapter':'phosx_official.v1',
        'local_use_permission':'permitted','derived_export_permission':'permitted','supported_center_residues':['S','T'],
        'matrix_file':'matrix with spaces.h5','background_file':'bg with spaces.h5','matrix_sha256':'synthetic-bootstrap-only'}))
    run=subprocess.run;captured=[]
    def outside(command,**kwargs):
        captured.append(command)
        return run(command,**kwargs,cwd=tmp_path,env={k:v for k,v in os.environ.items() if k!='PYTHONPATH'})
    monkeypatch.setattr(native.subprocess,'run',outside)
    ctx={'science':{'official_methods':{'PhosX':{'seed':71,'permutations':19}}}}
    _,_,executions=native.execute_tracks(scientific(),{'_LOCAL_SPECIFICITY':meta},ctx,{'status':'official_pssm_scored'})
    assert marker.is_file(),ctx['_method_runtime']
    result=json.loads(marker.read_text());assert Path(result['file']).resolve()==adapter.resolve()
    args=result['args'];assert args[args.index('--seed')+1]=='71' and args[args.index('--permutations')+1]=='19'
    assert args[args.index('--residue')+1]=='ST'
    assert args[args.index('--matrix')+1]==str(tmp_path/'matrix with spaces.h5')
    assert executions.status.tolist()==['failed'] # fake adapter intentionally exits; never scientific execution success
    assert executions.reason.tolist()==['native_process_failed']


def test_missing_bundled_adapter_fails_without_importing_installed_copy(tmp_path,monkeypatch):
    package=tmp_path/'missing bundle'/'ptm_shared';package.mkdir(parents=True);(package/'__init__.py').write_text('')
    monkeypatch.setattr(native,'__file__',str(package/'official_method_tracks.py'))
    command=native.adapter_command(['--seed','7'])
    result=subprocess.run(command,cwd=tmp_path,capture_output=True,text=True,env={k:v for k,v in os.environ.items() if k!='PYTHONPATH'})
    assert result.returncode!=0 and 'bundled adapter' in result.stderr.lower()


def test_bootstrap_parameters_and_root_are_not_cwd_derived(monkeypatch,tmp_path):
    expected=Path(native.__file__).resolve().parent.parent
    monkeypatch.chdir(tmp_path)
    cmd=native.adapter_command(['--input','file name.tsv','--seed','1729','--permutations','10000'])
    assert cmd[0]==sys.executable and '-I' in cmd and '-B' in cmd
    assert str(expected) in cmd and cmd[-6:]==['--input','file name.tsv','--seed','1729','--permutations','10000']


def test_bootstrap_code_invalidates_native_stage_not_quant(monkeypatch):
    from test_ai_detection import inputs
    from ptm_shared import astra_evidence_v6 as engine
    *_,ctx=inputs();before=engine.resolve_plan(ctx)
    digest=engine.digest
    monkeypatch.setattr(engine,'digest',lambda path:'changed-bootstrap' if Path(path).name=='official_method_tracks.py' else digest(path))
    after=engine.resolve_plan(ctx)
    assert before['fingerprints']['quant']==after['fingerprints']['quant']
    assert before['fingerprints']['discovery']!=after['fingerprints']['discovery']
