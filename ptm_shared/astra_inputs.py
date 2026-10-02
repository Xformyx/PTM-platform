"""Lossless research-input inventory. Operational order fields are never serialized."""
import hashlib
import json
import re
from pathlib import Path

VERSION = 'astra_research_input.v1'
RESEARCH_FIELDS = ('project_name', 'order_code', 'species', 'organism_code', 'ptm_type',
                  'sample_config', 'analysis_context', 'analysis_options', 'report_options',
                  'rag_collections', 'secondary_ptm_type', 'secondary_sample_config')
FILE_FIELDS = ('pr_matrix_path', 'pg_matrix_path', 'fasta_path', 'config_xlsx_path',
               'secondary_pr_matrix_path', 'secondary_pg_matrix_path',
               'diann_report_path', 'diann_site_report_path', 'run_crosswalk_path', 'search_fasta_path', 'transgene_manifest_path', 'taxonomy_mapping_path', 'specificity_manifest_path', 'perturbation_manifest_path')
SECRET = re.compile(r'(^|_)(password|passwd|token|secret|credential|api_key|authorization|cookie)(_|$)', re.I)


def stable_id(prefix, value):
    return prefix + '_' + hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                                    allow_nan=False, default=str).encode()).hexdigest()[:20]


def sanitize_research(value, path='', excluded=None):
    excluded = excluded if excluded is not None else []
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            target = f'{path}/{key}'
            if str(key)=='stored_path':
                excluded.append({'source_field_path': target, 'disposition': 'excluded', 'reason': 'server_storage_path'})
            elif SECRET.search(re.sub(r'([a-z0-9])([A-Z])',r'\1_\2',str(key))):
                excluded.append({'source_field_path': target, 'disposition': 'excluded', 'reason': 'credential_field'})
            else:
                result[key] = sanitize_research(item, target, excluded)
        return result
    if isinstance(value, (list, tuple)):
        return [sanitize_research(v, f'{path}/{i}', excluded) for i, v in enumerate(value)]
    return value


def capture_order(order):
    """Accept an ORM object or fixture mapping; do not inspect arbitrary attributes."""
    get = (lambda key: order.get(key)) if isinstance(order, dict) else (lambda key: getattr(order, key, None))
    excluded = []
    original = sanitize_research({key: get(key) for key in RESEARCH_FIELDS}, excluded=excluded)
    options=original.get('analysis_options')
    if isinstance(options,dict) and options.get('protein_list_path'):
        options['protein_list_path']={'filename':Path(options['protein_list_path']).name,'status':'provided_supporting_input','server_path_excluded':True}
    original['input_files'] = {key: {'filename': Path(get(key)).name if get(key) else None,
                                    'status': 'provided' if get(key) else 'not_provided'} for key in FILE_FIELDS}
    return {'schema_version': VERSION, 'source_record_id': str(get('id')), 'original': original,
            'excluded_fields': excluded,
            'research_questions_status': 'provided' if 'research_questions' in (get('report_options') or {})
            else 'not_persisted_in_source_order'}


def leaves(value, path=''):
    if isinstance(value, dict) and value:
        for key, item in value.items():
            yield from leaves(item, path + '/' + str(key).replace('~', '~0').replace('/', '~1'))
    elif isinstance(value, list) and value:
        for i, item in enumerate(value):
            yield from leaves(item, path + '/' + str(i))
    else:
        yield path, value


def transfer_contract(snapshot, design, context, literature):
    """Every provided leaf has one disposition; raw-only is an explicit valid outcome."""
    original = snapshot['original']; fields = []
    direct = {'species', 'ptm_type', 'organism_code'}
    study_fields = set(design.get('study', {}))
    for path, value in sorted(leaves(original), key=lambda item: item[0]):
        parts = path.strip('/').split('/'); root = parts[0]
        canonical = None
        if root in direct:
            canonical = 'study/study_design.json#/study/' + ('taxonomy_id' if root == 'organism_code' else root)
        elif root == 'analysis_context' and len(parts) == 2 and parts[1] in study_fields:
            canonical = 'study/study_design.json#/study/' + parts[1]
        elif root == 'sample_config':
            canonical = 'study/study_design.json#/injections'
        elif root == 'rag_collections':
            canonical = 'references/literature_pin.json#/collections'
        fields.append({'source_field_path': path, 'source_record_id': snapshot['source_record_id'],
            'scope': 'injection' if root == 'sample_config' else 'study',
            'original_value_ref': 'study/user_input_snapshot.json#/original' + path,
            'canonical_value_ref': canonical, 'value_status': 'null' if value is None else 'provided',
            'source_kind': 'resolver_output_with_field_provenance' if '/study_design/' in path else 'recorded_file_metadata' if root=='input_files' else 'persisted_research_input', 'transform': 'resolver' if canonical else 'identity_UTF8',
            'export_file': 'study/user_input_snapshot.json', 'export_field': '/original' + path,
            'disposition': 'canonical_and_raw' if canonical else 'raw_only', 'reason': None if canonical else 'preserved_for_Astra_interpretation'})
    fields.extend({**e, 'source_record_id': snapshot['source_record_id'], 'scope': 'study',
                   'value_status': 'excluded_without_value', 'source_kind': 'operational_secret',
                   'original_value_ref': None, 'canonical_value_ref': None, 'transform': 'redacted',
                   'export_file': None, 'export_field': None} for e in snapshot.get('excluded_fields', []))
    paths = [f['source_field_path'] for f in fields]
    if len(paths) != len(set(paths)):
        raise ValueError('Duplicate input disposition')
    validation = {'schema_version': VERSION, 'research_input_fields': len(list(leaves(original))),
        'raw_transferred': len(list(leaves(original))), 'canonical_mapped': sum(f['disposition'] == 'canonical_and_raw' for f in fields),
        'raw_only': sum(f['disposition'] == 'raw_only' for f in fields),
        'justified_exclusions': len(snapshot.get('excluded_fields', [])), 'unexpected_missing': 0,
        'exactly_one_disposition': True, 'unicode_and_null_false_zero_empty_preserved': True}
    questions = (original.get('report_options') or {}).get('research_questions')
    brief = ['# Study brief', f"Project: {original.get('project_name')}", f"Order: {original.get('order_code')}",
             f"{len(design['injections'])} injections / {len(design['materials'])} materials / {len(design['conditions'])} conditions / {len(design['contrasts'])} contrasts",
             f"Replication declaration: {design['replication_declaration']}. No biological p/q method is implemented.",
             '## Conditions and references', '| Condition ID | Arm | Label | Original time | Minutes |', '|---|---|---|---|---|']
    for c in design['conditions']:
        brief.append(f"| {c['condition_id']} | {c['arm_id']} | {c['label']} | {c.get('time')} | {(c.get('time') or {}).get('minutes')} |")
    brief += ['## Contrasts', json.dumps(design['contrasts'], ensure_ascii=False, indent=2),
              '## User research questions — complete original', json.dumps(questions, ensure_ascii=False, indent=2),
              '## Experimental context — complete original', json.dumps(original.get('analysis_context'), ensure_ascii=False, indent=2),
              '## Requested analysis and report preferences', json.dumps({k: original.get(k) for k in ('analysis_options','report_options')}, ensure_ascii=False, indent=2),
              'Legacy LLM/report execution options are writing preferences only in this package workflow.',
              '## Literature inclusion', json.dumps(literature, ensure_ascii=False, indent=2),
              '## Unresolved facts', json.dumps(design.get('issues', []), ensure_ascii=False, indent=2),
              'Unknown acquisition, upstream normalization, localization and biological replication must not be invented.',
              'See user_input_snapshot.json for every remaining raw research field and input_field_manifest.csv for its disposition.']
    return fields, validation, '\n\n'.join(brief) + '\n'
