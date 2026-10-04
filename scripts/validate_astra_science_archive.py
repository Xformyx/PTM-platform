"""Upgrade a frozen v4 test package into a NEW current Astra run, offline.

The supplied archive is immutable. This checks engineering parity, not biological
performance. Source bytes are pinned; no remote reference is requested.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch
import zipfile
import pandas as pd
from ptm_shared.astra_science import run
from ptm_shared.astra_package import replay_package


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--replay',action='store_true');args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=False);baseline=args.output/'baseline';baseline.mkdir()
    with zipfile.ZipFile(args.archive) as archive:
        for member in archive.infolist():
            path=(baseline/member.filename).resolve()
            if not path.is_relative_to(baseline.resolve()):raise ValueError('Unsafe archive path')
        archive.extractall(baseline)
    saved=json.loads((baseline/'reproducibility/replay_config.json').read_text());context=saved['context']
    # A saved order may have requested live refresh. This comparison must use
    # the archived source bytes even in that case, with network still disabled.
    context.update(quantitation_export_mode='astra_analysis.v5',refresh_references=False)
    context.setdefault('science',{}).pop('experimental_enabled',None)
    design=saved['design'];design['schema_version']='study_design.v4'
    design['study'].update(design_axis='time_course',analysis_target='phosphoproteomics');context['study_design']=design
    source=baseline/'references/source_pin.json';sha=hashlib.sha256(source.read_bytes()).hexdigest()
    registry=args.output/'registry/source_pins';registry.mkdir(parents=True);(registry/(sha+'.json')).write_bytes(source.read_bytes())
    config={'experimental_context':context,'species':design['study']['species'],'species_tax_id':str(design['study']['taxonomy_id']),
        'order_code':'frozen_input_science_comparison','reference_root':str(args.output/'registry'),'source_pin_sha256':sha,
        'user_input_snapshot':saved['snapshot'],'literature_pin':saved['literature'],
        **{key:str(baseline/saved['inputs'][short]) for short,key in [('PR','pr_matrix_path'),('PG','pg_matrix_path'),('FASTA','fasta_path')]}}
    # Original attachments are copied from the already sanitized archive paths.
    for doc in config['literature_pin'].get('documents',[]):
        if doc.get('content_status')=='full_text_included':
            payload=(baseline/doc['package_file']).read_bytes()
            if hashlib.sha256(payload).hexdigest()!=doc['sha256']:raise ValueError('Literature checksum mismatch')
            objects=args.output/'registry/literature_objects';objects.mkdir(exist_ok=True)
            (objects/doc['sha256']).write_bytes(payload)
    with patch('socket.socket',side_effect=AssertionError('Offline validation attempted network')):
        result=run('frozen-input-validation',config,args.output/'v5',progress=lambda message:print(message,flush=True))
        root=args.output/'v5/enrichment_free_runs'/result['run_id'];checks=[]
        for old in sorted((baseline/'quant').glob('*.csv')):
            name=old.stem;new=root/'quant'/(name+'.csv')
            if not new.exists():raise ValueError('Missing quantitative table: '+name)
            a,b=pd.read_csv(old),pd.read_csv(new)
            pd.testing.assert_frame_equal(a,b,check_exact=False,atol=1e-10,rtol=1e-10)
            checks.append({'table':name,'rows':len(a),'numeric_text_mask_equivalent':True,'byte_identical':old.read_bytes()==new.read_bytes()})
        if args.replay:
            subprocess.run([sys.executable,str((root/'replay.py').resolve()),'--output',str((args.output/'offline_replay').resolve())],
                cwd=args.output.resolve(),env={**os.environ,'PYTHONPATH':''},check=True)
    report={'passed':True,'archive_sha256':hashlib.sha256(args.archive.read_bytes()).hexdigest(),'run_id':result['run_id'],
        'quantitative_comparisons':checks,'counts':result['counts'],'source_pin_sha256':sha,
        'replay_performed':args.replay,'scope':'same_input_reference_engineering_regression_not_independent_biological_validation'}
    (args.output/'validation.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))


if __name__=='__main__':main()
