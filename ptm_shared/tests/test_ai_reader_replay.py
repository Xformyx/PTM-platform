import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch
import pytest
from ptm_shared.tests.test_astra_evidence_catalog import config


def test_bundled_reader_entry_isolated_and_source_read_only(config,tmp_path):
    from ptm_shared import astra_evidence_v6 as engine
    from ptm_shared.annotation_registry import digest
    config['experimental_context']['quantitation_export_mode']='astra_analysis.v6'
    result=engine.run('reader-entry-fixture',config,tmp_path/'package with spaces')
    root=tmp_path/'package with spaces/enrichment_free_runs'/result['run_id']
    before={str(p.relative_to(root)):digest(p) for p in root.rglob('*') if p.is_file()}
    assert (root/'reader_replay.py').is_file()
    env={k:v for k,v in os.environ.items() if k!='PYTHONPATH'}
    output=tmp_path/'output with spaces'
    r=subprocess.run([sys.executable,'-I','-B',str(root/'reader_replay.py'),'--output',str(output)],cwd='/tmp',env=env,capture_output=True,text=True)
    assert r.returncode==0,r.stderr+r.stdout
    report=json.loads((output/'READER_REPLAY_VALIDATION.json').read_text())
    assert report['passed'] and report['scientific_calls']==0 and report['network_requests']==0
    assert report['validated_manifest_files']==len(json.loads((root/'manifest.json').read_text())['files'])
    assert Path(report['reader_module_file']).is_relative_to(root/'reproducibility/code')
    assert before=={str(p.relative_to(root)):digest(p) for p in root.rglob('*') if p.is_file()}
    assert not list(root.rglob('__pycache__'))
    from ptm_shared.astra_reader_revision import revise_temporal
    revision=revise_temporal(root,tmp_path/'current revision',whole_only=True)
    revised=tmp_path/'current revision/enrichment_free_runs'/revision['run_id']
    r=subprocess.run([sys.executable,'-I','-B',str(revised/'reader_replay.py'),'--output',str(tmp_path/'revision replay')],cwd='/tmp',env=env,capture_output=True,text=True)
    assert r.returncode==0,r.stderr+r.stdout
    dictionary=json.loads((revised/'reproducibility/data_dictionary.json').read_text())
    assert dictionary['quant/comparisons.csv']['field_semantics']['A']['unit']=='log2_ratio'
    assert digest(root/'quant/comparisons.csv')==digest(revised/'quant/comparisons.csv')
    assert before=={str(p.relative_to(root)):digest(p) for p in root.rglob('*') if p.is_file()}
    link=tmp_path/'linked output';link.symlink_to(tmp_path,target_is_directory=True)
    for bad in [root/'bad',link/'new',tmp_path/'a/../escape']:
        r=subprocess.run([sys.executable,'-I','-B',str(root/'reader_replay.py'),'--output',str(bad)],cwd='/tmp',env=env,capture_output=True,text=True)
        assert r.returncode!=0
    # Instrument only this synthetic archive, resign its fixture manifest, and
    # prove a scientific call cannot hide behind an apparently successful reader.
    module=root/'reproducibility/code/ptm_shared/astra_reader.py';original=module.read_bytes()
    module.write_bytes(original+b'\n_original_write_reader=write_reader\ndef write_reader(*a,**k):\n    from .generic_workflow import calculate\n    calculate()\n    return _original_write_reader(*a,**k)\n')
    manifest_path=root/'manifest.json';manifest_bytes=manifest_path.read_bytes();manifest=json.loads(manifest_bytes)
    entry=manifest['files'][str(module.relative_to(root))];entry.update(bytes=module.stat().st_size,sha256=digest(module))
    manifest_path.write_text(json.dumps(manifest))
    r=subprocess.run([sys.executable,'-I','-B',str(root/'reader_replay.py'),'--output',str(tmp_path/'forbidden science')],cwd='/tmp',env=env,capture_output=True,text=True)
    assert r.returncode!=0 and 'execution forbidden during reader replay' in r.stderr
    module.write_bytes(original);manifest_path.write_bytes(manifest_bytes)
    # A scientific input is immutable even though reader replay never recalculates it.
    (root/'quant/comparisons.csv').write_text('tampered')
    r=subprocess.run([sys.executable,'-I','-B',str(root/'reader_replay.py'),'--output',str(tmp_path/'bad source')],cwd='/tmp',env=env,capture_output=True,text=True)
    assert r.returncode!=0 and 'hash' in r.stderr.lower()


def test_revision_captures_dependencies_absent_from_old_code_snapshot(config,tmp_path):
    from ptm_shared import astra_evidence_v6 as engine
    from ptm_shared.astra_reader_revision import revise_temporal
    config['experimental_context']['quantitation_export_mode']='astra_analysis.v6'
    result=engine.run('older-layout-fixture',config,tmp_path/'old')
    root=tmp_path/'old/enrichment_free_runs'/result['run_id']
    manifest=json.loads((root/'manifest.json').read_text())
    absent=['effect_series.py','control_comparison.py','study_display.py','study_display.json','study_input_metadata.py']
    for name in absent:
        rel='reproducibility/code/ptm_shared/'+name
        (root/rel).unlink();manifest['files'].pop(rel)
    (root/'manifest.json').write_text(json.dumps(manifest))
    revised=revise_temporal(root,tmp_path/'revision',whole_only=True)
    destination=tmp_path/'revision/enrichment_free_runs'/revised['run_id']
    metadata=json.loads((destination/'reproducibility/temporal_reader_revision.json').read_text())
    assert set(absent)<=set(metadata['refreshed_code_files'])
    r=subprocess.run([sys.executable,'-I','-B',str(destination/'reader_replay.py'),'--output',str(tmp_path/'replay')],
        cwd='/tmp',env={k:v for k,v in os.environ.items() if k!='PYTHONPATH'},capture_output=True,text=True)
    assert r.returncode==0,r.stderr+r.stdout
