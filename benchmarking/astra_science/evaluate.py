"""Study-disjoint manifests and selective metrics; unknown labels stay unknown."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path

PROTOCOL = json.loads(Path(__file__).with_name('protocol.json').read_text())
REQUIRED = ('dataset_id', 'study_id', 'cohort_id', 'raw_sha256', 'taxon', 'split',
            'truth_scope', 'license', 'independent_unit_definition', 'source_overlap')


def validate_manifest(rows):
    seen = set(); groups = defaultdict(set)
    for r in rows:
        missing = [k for k in REQUIRED if k not in r]
        if missing: raise ValueError('missing_manifest_fields:' + ','.join(missing))
        if r['dataset_id'] in seen: raise ValueError('duplicate_dataset')
        seen.add(r['dataset_id'])
        if r['split'] not in PROTOCOL['splits']: raise ValueError('invalid_split')
        if len(r['raw_sha256']) != 64: raise ValueError('invalid_input_digest')
        if r.get('used_for_development') and r['split'] != 'development':
            raise ValueError('development_data_is_not_unseen')
        for field in PROTOCOL['group_fields'] + ['raw_sha256']:
            if r.get(field): groups[(field, r[field])].add(r['split'])
    if any(len(s) > 1 for s in groups.values()): raise ValueError('study_or_ancestry_leakage')
    return {'datasets': len(rows), 'split_check': 'passed', 'protocol_sha256':
            hashlib.sha256(Path(__file__).with_name('protocol.json').read_bytes()).hexdigest()}


def selective_metrics(rows):
    """Rows are predeclared evaluation units, including abstentions/unsupported targets."""
    result = []
    for resolution in ('kinase', 'family'):
        eligible = [r for r in rows if r['evaluation_resolution'] == resolution]
        calls = [r for r in eligible if r['resolution'] == resolution]
        known = [r for r in calls if r.get('correct') is not None]
        result.append({'resolution': resolution, 'evaluation_n': len(eligible), 'call_n': len(calls),
                       'truth_evaluable_call_n': len(known),
                       'call_coverage': len(calls)/len(eligible) if eligible else None,
                       'truth_evaluable_fraction': len(known)/len(calls) if calls else None,
                       'selective_risk': sum(r['correct'] is False for r in known)/len(known) if known else None,
                       'biological_population_error_rate': None})
    return result


def comparator_contract(name, code_pin=None, resource_pin=None, executable=None):
    if name not in PROTOCOL['comparators']: raise ValueError('unknown_comparator')
    return {'method': name, 'code_pin': code_pin, 'resource_pin': resource_pin,
            'executable': executable, 'status': 'ready_not_run' if all((code_pin, resource_pin, executable))
            else 'not_run_pinned_implementation_or_resource_unavailable'}
