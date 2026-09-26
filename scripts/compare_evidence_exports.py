"""Compare CSV evidence with explicit injection-label reconciliation only."""
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd


def compare(reference,actual):
    left_samples=json.loads((reference/'samples.json').read_text())
    right_samples=json.loads((actual/'samples.json').read_text())
    left={s['original_column']:s for s in left_samples}; right={s['original_column']:s for s in right_samples}
    assert set(left)==set(right)
    for key in left:
        assert left[key]['time_min']==right[key]['time_min']
        if 'biological_samples_represented_per_time' in left[key] and 'biological_unit' in right[key]:
            units={s['biological_unit'] for s in right.values() if s['time_min']==right[key]['time_min']}
            assert len(units)==left[key]['biological_samples_represented_per_time']
    replacements={right[key]['run']:left[key]['run'] for key in left if right[key]['run']!=left[key]['run']}
    results={}
    for path in sorted(reference.glob('*.csv')):
        other=actual/path.name
        a,b=pd.read_csv(path),pd.read_csv(other)
        metadata_reconciliation={}
        missing=set(a)-set(b)
        if missing:
            assert path.name=='runlevel.csv' and missing=={'biological_samples_represented_per_time','replication_type'}, (path.name,missing)
            assert set(b)-set(a)=={'biological_unit','condition','technical_injection'}
            metadata_reconciliation={'legacy_summary_columns':sorted(missing),'explicit_manifest_columns':sorted(set(b)-set(a)),
                'biological_unit_counts_checked_against_samples':True}
            a=a.drop(columns=sorted(missing))
        b=b[a.columns].copy()
        if replacements:
            for column in [c for c in b if c=='run' or c.endswith('_runs') or c.endswith('_run_ids')]:
                for old,new in replacements.items():
                    b[column]=b[column].map(lambda value: value.replace(old,new) if isinstance(value,str) else value)
        pd.testing.assert_frame_equal(a,b,check_dtype=False,atol=1e-10,rtol=1e-10)
        max_error=0.0
        for column in a.select_dtypes(include=['number']):
            values=(pd.to_numeric(a[column])-pd.to_numeric(b[column])).abs().dropna()
            if len(values): max_error=max(max_error,float(values.max()))
        results[path.name]={'rows':len(a),'compared_columns':list(a.columns),'metadata_reconciliation':metadata_reconciliation,
            'numeric_text_and_missing_mask_equal':True,
            'max_abs_error':max_error,'byte_equal':path.read_bytes()==other.read_bytes()}
    return {'passed':True,'atol':1e-10,'rtol':1e-10,
        'run_label_reconciliation':replacements,'tables':results,
        'byte_identical_tables':sum(t['byte_equal'] for t in results.values())}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('reference','actual','output'):p.add_argument('--'+name,type=Path,required=True)
    args=p.parse_args(); result=compare(args.reference,args.actual)
    args.output.write_text(json.dumps(result,indent=2))
    print(json.dumps({'passed':True,'tables':len(result['tables']),'byte_identical_tables':result['byte_identical_tables'],
        'run_label_reconciliation_count':len(result['run_label_reconciliation']),
        'max_abs_error':max(t['max_abs_error'] for t in result['tables'].values())},indent=2))
