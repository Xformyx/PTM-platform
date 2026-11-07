"""Bounded C05-A actual-input regression; never edits the source package.

Use an existing extracted archive, not an invented time-matched fixture. This
checks quantification only; it does not claim a queue run or native PhosX replay.
"""
import argparse
from collections import Counter
from copy import deepcopy
import ctypes
import json
import os
from pathlib import Path
import shutil
import sys


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def budget(root, minimum_free=20 * 2**30):
    if shutil.disk_usage(root).free < minimum_free:
        raise RuntimeError('Disk reserve reached; source data must not be deleted')


def immutable_copy(source, target):
    """APFS COW when available, otherwise a new ordinary copy; never hardlinks."""
    source, target = Path(source), Path(target)
    if target.exists():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == 'darwin':
        lib = ctypes.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True)
        if lib.clonefile(os.fsencode(source), os.fsencode(target), 0) == 0:
            return
    shutil.copyfile(source, target)


def inventory(source, output):
    from ptm_shared.annotation_registry import digest
    from ptm_shared.study_execution import resolve_context
    from ptm_shared.study_design import require_resolved
    from ptm_shared.study_display import study_display
    cfg = read(source / 'reproducibility/replay_config.json')
    original = cfg['snapshot']['original']
    old = cfg['design']
    references = [c['condition_id'] for c in old['conditions'] if c['role'] == 'reference']
    if len(references) != 1:
        raise ValueError('This actual shared-Control regression requires exactly one recorded reference; never choose the first of several')
    context = deepcopy(cfg['context'])
    context['control_comparison'] = {'schema_version': 'control_comparison.v1',
        'strategy': 'shared_reference', 'source': 'user_input',
        'reference_condition_id': references[0]}
    resolved = resolve_context(context, original['sample_config'],
        taxonomy_id=old['study']['taxonomy_id'], species=old['study']['species'], ptm_type=old['study']['ptm_type'])
    design = require_resolved(resolved['study_design'])
    for collection, fields in [('conditions', ['condition_id', 'arm_id', 'role', 'time']),
            ('injections', ['injection_id', 'condition_id', 'input_column', 'material_id', 'technical_injection_id', 'legacy_replicate']),
            ('materials', ['material_id', 'biological_unit_id', 'pair_id']),
            ('contrasts', ['contrast_id', 'target_condition_id', 'reference_condition_id', 'pairing'])]:
        project = lambda rows: sorted([{k: r.get(k) for k in fields} for r in rows], key=lambda r: r[fields[0]])
        assert project(old[collection]) == project(design[collection]), collection + ' changed'
    assert old['replication_declaration'] == design['replication_declaration']
    inputs = {}
    for key, relative in cfg['inputs'].items():
        path = source / relative
        inputs[key] = {'source': str(path), 'sha256': digest(path), 'bytes': path.stat().st_size}
    provenance = read(source / 'provenance.json')
    for key, item in inputs.items():
        assert item['sha256'] == provenance['input_hashes'][key], key
    files = read(source / 'manifest.json')['files']
    protected = {name: digest(source / name) for name in files}
    assert all(value == files[name]['sha256'] for name, value in protected.items()), 'Source manifest mismatch'
    result = {'source_package': str(source), 'source_run_id': source.name,
        'input_files': inputs, 'source_manifest_verified_files': len(protected),
        'source_pin_sha256': provenance['source_pin_sha256'],
        'source_pin_file_sha256': protected['references/source_pin.json'],
        'replication_declaration': design['replication_declaration'],
        'pairing': dict(Counter(c['pairing'] for c in design['contrasts'])),
        'materials': design['materials'], 'conditions': design['conditions'],
        'display': study_display(design, resolved), 'same_numeric_mapping': True,
        'actual_time_matched_input': False}
    write(output / 'SOURCE_HASHES.json', protected)
    write(output / 'RESOLVED_CONTEXT.json', resolved)
    write(output / 'ACTUAL_INPUT.json', result)
    return cfg, resolved, inputs


def quantify(source, output, context, records):
    import pandas as pd
    from unittest.mock import patch
    from ptm_shared.annotation_registry import digest
    from ptm_shared import astra_evidence_v6 as engine, generic_workflow
    from ptm_shared.astra_package import quant_cached
    from ptm_shared.generic_workflow import TABLE_KEYS
    inputs = {}
    for key, record in records.items():
        target = output / 'inputs' / Path(record['source']).name
        if not target.exists():
            immutable_copy(record['source'], target)
        assert digest(target) == record['sha256']
        inputs[key] = target
    hashes = {k: v['sha256'] for k, v in records.items()}
    dictionary = read(source / 'reproducibility/data_dictionary.json')
    results = []
    plans = {}
    policies = [context['normalization_policy'], 'legacy_median.v1' if context['normalization_policy'] == 'already_normalized.v1' else 'already_normalized.v1']
    for policy in policies:
        budget(output)
        ctx = {**context, 'normalization_policy': policy}
        plan = engine.resolve_plan(ctx, hashes)
        plans[policy] = plan
        with patch.object(generic_workflow, 'normalize_supplied_matrices', wraps=generic_workflow.normalize_supplied_matrices) as normalizer:
            (tables, norm, readiness), reuse = quant_cached(inputs, ctx['study_design'], ctx, output / 'delivery/C05A_ACTUAL', plan['fingerprints']['quant'], calculator=engine.calculate)
            assert normalizer.call_count == (1 if reuse['status'] == 'computed' else 0)
        assert norm['applications'] == 1 and norm['scope'] == 'whole_study'
        if policy != context['normalization_policy']:
            results.append({'policy': policy, 'cache': reuse, 'normalization': norm, 'comparison': 'sensitivity archive has no full quant tables'})
            continue
        comparisons = []
        for name, current in tables.items():
            relative = 'quant/' + name + '.csv'
            if relative not in dictionary:
                comparisons.append({'table': relative, 'status': 'new_projection', 'rows': len(current)})
                continue
            dtype = {k: 'str' for k, v in dictionary[relative]['dtypes'].items() if v in {'str', 'object'}}
            prior = pd.read_csv(source / relative, float_precision='round_trip', low_memory=False, dtype=dtype)
            cache_file = output / 'delivery/C05A_ACTUAL/.astra_stage_cache' / plan['fingerprints']['quant'] / (name + '.csv')
            current = pd.read_csv(cache_file, float_precision='round_trip', low_memory=False, dtype=dtype)
            added = sorted(set(current) - set(prior))
            removed = sorted(set(prior) - set(current))
            assert not removed, (name, removed)
            keys = TABLE_KEYS.get(name, [])
            if name == 'temporal_protein_summary' and 'series_id' not in prior:
                keys = ['protein_group', 'arm_id', 'reference_condition_id', 'layer']
            a, b = current[list(prior)].copy(), prior.copy()
            if keys:
                a = a.sort_values(keys).reset_index(drop=True)
                b = b.sort_values(keys).reset_index(drop=True)
            # CSV object columns can contain missing strings; compare through
            # the recorded serializer, not inferred biological assertions.
            for col in dtype:
                if col in a:
                    a[col] = a[col].where(a[col].notna(), None).map(lambda x: str(x) if x is not None else None)
                    b[col] = b[col].where(b[col].notna(), None)
            pd.testing.assert_frame_equal(a.isna(), b.isna(), check_exact=True)
            numeric_differences = {}
            for col in a:
                if pd.api.types.is_float_dtype(a[col]) and pd.api.types.is_numeric_dtype(b[col]):
                    delta = (a[col] - b[col]).abs()
                    changed = delta.gt(0)
                    if changed.any():
                        numeric_differences[col] = {'cells': int(changed.sum()), 'maximum_absolute_error': float(delta.max())}
                else:
                    pd.testing.assert_series_equal(a[col], b[col], check_dtype=False, check_exact=True)
            pd.testing.assert_frame_equal(a, b, check_dtype=False, check_exact=False, atol=1e-12, rtol=0)
            comparisons.append({'table': relative, 'rows': len(current),
                'common_values_ids_na_exact': not numeric_differences, 'ids_and_na_exact': True,
                'floating_absolute_tolerance': 1e-12, 'numeric_differences': numeric_differences,
                'added_columns': added, 'old_sha256': digest(source / relative), 'new_sha256': digest(cache_file),
                'byte_equal': digest(source / relative) == digest(cache_file)})
        comp = tables['comparisons']; run = tables['runlevel']
        assert comp.biological_p_value.isna().all() and comp.biological_q_value.isna().all()
        results.append({'policy': policy, 'cache': reuse, 'normalization': norm, 'tables': comparisons,
            'unique_injections': run.injection_id.nunique(), 'runlevel_rows': len(run),
            'comparisons': len(comp), 'biological_pq': 'not_computed',
            'missing_counts': {c: int(comp[c].isna().sum()) for c in ['U_joint', 'P_joint', 'A']}})
        write(output / 'QUANT_REGRESSION.json', results)
    write(output / 'PLANS.json', plans)
    write(output / 'QUANT_REGRESSION.json', results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--quantify', action='store_true')
    args = parser.parse_args()
    source, output = args.package.resolve(), args.output.resolve()
    if source == output or source in output.parents:
        parser.error('Use a new output outside the source package')
    output.mkdir(parents=True, exist_ok=True)
    budget(output)
    cfg, context, inputs = inventory(source, output)
    print('Verified immutable actual input and unchanged numeric mapping', flush=True)
    if args.quantify:
        quantify(source, output, context, inputs)
        print('Actual quantification regression passed', flush=True)


if __name__ == '__main__':
    main()
