"""Lossless research-input inventory. Operational order fields are never serialized."""
import hashlib
import json
import re
from pathlib import Path

VERSION = 'astra_research_input.v2'
CONTEXT_CONTRACT = 'study_context_roles.v2'
RESEARCH_FIELDS = ('project_name', 'order_code', 'species', 'organism_code', 'ptm_type',
                  'sample_config', 'analysis_context', 'analysis_options', 'report_options',
                  'rag_collections', 'secondary_ptm_type', 'secondary_sample_config')
FILE_FIELDS = ('pr_matrix_path', 'pg_matrix_path', 'fasta_path', 'config_xlsx_path',
               'secondary_pr_matrix_path', 'secondary_pg_matrix_path',
               'diann_report_path', 'diann_site_report_path', 'run_crosswalk_path', 'search_fasta_path', 'transgene_manifest_path', 'taxonomy_mapping_path', 'specificity_manifest_path', 'perturbation_manifest_path', 'calibration_policy_path')
SECRET = re.compile(r'(^|_)(password|passwd|token|secret|credential|api_key|authorization|cookie)(_|$)', re.I)


def stable_id(prefix, value):
    return prefix + '_' + hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                                    allow_nan=False, default=str).encode()).hexdigest()[:20]


def sanitize_research(value, path='', excluded=None):
    excluded = excluded if excluded is not None else []
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            target = f'{path}/' + str(key).replace('~', '~0').replace('/', '~1')
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
    result = {'schema_version': VERSION, 'context_contract': CONTEXT_CONTRACT,
            'source_record_id': str(get('id')), 'original': original,
            'excluded_fields': excluded,
            'research_questions_status': 'provided' if 'research_questions' in (get('report_options') or {})
            else 'not_persisted_in_source_order'}
    result['source_receipt'] = source_receipt(result)
    return result


def leaves(value, path=''):
    if isinstance(value, dict) and value:
        for key, item in value.items():
            yield from leaves(item, path + '/' + str(key).replace('~', '~0').replace('/', '~1'))
    elif isinstance(value, list) and value:
        for i, item in enumerate(value):
            yield from leaves(item, path + '/' + str(i))
    else:
        yield path, value


def value_hash(value):
    """JSON types are significant: false, zero, null and empty are distinct."""
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def source_receipt(snapshot):
    return {'source_record_id': snapshot['source_record_id'],
            'original_sha256': value_hash(snapshot['original']),
            'fields': {p: {'sha256': value_hash(v), 'type': type(v).__name__}
                       for p, v in leaves(snapshot['original'])}}


def verify_snapshot(snapshot, receipt=None, stage='worker_snapshot'):
    """Check a frozen source receipt, not a second call to capture_order."""
    expected = receipt or (snapshot or {}).get('source_receipt')
    if not expected:
        return {'status': 'legacy_unverified', 'stage': stage, 'errors': []}
    errors = []
    actual = dict(leaves((snapshot or {}).get('original', {})))
    for path, item in expected['fields'].items():
        reason = ('missing' if path not in actual else 'type_changed'
                  if type(actual[path]).__name__ != item['type'] else 'value_changed'
                  if value_hash(actual[path]) != item['sha256'] else None)
        if reason: errors.append({'stage': stage, 'field_path': path, 'reason': reason})
    if (snapshot or {}).get('source_record_id') != expected['source_record_id']:
        errors.append({'stage': stage, 'field_path': '/source_record_id', 'reason': 'stale_source'})
    if value_hash((snapshot or {}).get('original', {})) != expected['original_sha256'] and not errors:
        errors.append({'stage': stage, 'field_path': '/original', 'reason': 'stale_source'})
    if errors: raise ValueError('Research input delivery: ' + json.dumps(errors, ensure_ascii=False))
    return {'status': 'verified', 'stage': stage, 'errors': []}


def verify_order_capture(order, snapshot):
    """Compare the allowlisted ORM values with the snapshot before dispatch."""
    get = order.get if isinstance(order, dict) else lambda key: getattr(order, key, None)
    for key in RESEARCH_FIELDS:
        value = sanitize_research(get(key))
        if key == 'analysis_options' and isinstance(value, dict) and value.get('protein_list_path'):
            value['protein_list_path'] = {'filename': Path(value['protein_list_path']).name,
                'status': 'provided_supporting_input', 'server_path_excluded': True}
        if value_hash(value) != value_hash(snapshot['original'].get(key)):
            raise ValueError('Research input delivery: saved_order /' + key + ' value_or_type_changed')
    for key in FILE_FIELDS:
        expected = {'filename': Path(get(key)).name if get(key) else None,
                    'status': 'provided' if get(key) else 'not_provided'}
        if snapshot['original']['input_files'].get(key) != expected:
            raise ValueError('Research input delivery: saved_order /input_files/' + key)
    verify_snapshot(snapshot, stage='saved_order_capture')


def resolve_pointer(document, pointer):
    if not pointer: return document
    if not pointer.startswith('/'): raise ValueError('Invalid JSON pointer')
    for token in pointer[1:].split('/'):
        token = token.replace('~1', '/').replace('~0', '~')
        document = document[int(token)] if isinstance(document, list) else document[token]
    return document


def transfer_contract(snapshot, design, context, literature):
    """Every provided leaf has one disposition; raw-only is an explicit valid outcome."""
    from .study_display import DISPLAY, study_display, study_display_markdown
    from .control_comparison import comparison_markdown
    original = snapshot['original']; fields = []
    direct = {'species', 'ptm_type', 'organism_code'}
    study_fields = set(design.get('study', {}))
    for path, value in sorted(leaves(original), key=lambda item: item[0]):
        parts = path.strip('/').split('/'); root = parts[0]
        canonical = None
        if root in direct and ('taxonomy_id' if root == 'organism_code' else root) in study_fields:
            canonical = 'study/study_design.json#/study/' + ('taxonomy_id' if root == 'organism_code' else root)
        elif root == 'analysis_context' and len(parts) == 2 and parts[1] in study_fields:
            canonical = 'study/study_design.json#/study/' + parts[1]
        elif root == 'sample_config' and len(parts) > 1 and parts[1] == 'samples':
            canonical = 'study/study_design.json#/injections'
        elif root == 'rag_collections' and 'collections' in literature:
            canonical = 'references/literature_pin.json#/collections'
        fields.append({'source_field_path': path, 'source_record_id': snapshot['source_record_id'],
            **({'display_name': DISPLAY['biological_question']['label'], 'field_description': DISPLAY['biological_question']['description']} if parts[-1]=='biological_question' else {}),
            'scope': 'injection' if root == 'sample_config' else 'study',
            'original_value_ref': 'study/user_input_snapshot.json#/original' + path,
            'canonical_value_ref': canonical, 'value_status': 'null' if value is None else 'provided',
            'raw_value_sha256': value_hash(value), 'raw_value_type': type(value).__name__,
            'information_status': 'not_recorded' if value is None else 'provided_structured' if canonical else 'provided_raw',
            'semantic_role': 'research_question' if path.startswith('/report_options/research_questions') else 'study_design_context',
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
        'validation_scope': 'inventory_only_pending_file_readback',
        'raw_transferred': None, 'canonical_mapped': sum(f['disposition'] == 'canonical_and_raw' for f in fields),
        'raw_only': sum(f['disposition'] == 'raw_only' for f in fields),
        'justified_exclusions': len(snapshot.get('excluded_fields', [])), 'unexpected_missing': None,
        'exactly_one_disposition': len(paths) == len(set(paths)), 'unicode_and_null_false_zero_empty_preserved': None}
    questions = (original.get('report_options') or {}).get('research_questions')
    brief = ['# Study brief', f"Project: {original.get('project_name')}", f"Order: {original.get('order_code')}",
             f"{len(design['injections'])} injections / {len(design['materials'])} materials / {len(design['conditions'])} conditions / {len(design['contrasts'])} contrasts",
             f"Replication declaration: {design['replication_declaration']}. Actual computed/not-computed status: evidence/readiness.json and science/inference_results.csv.",
             '[Common context, roles and source locators](../reader/STUDY_CONTEXT.md). Design prose is context; report_options.research_questions is a separate input.',
             '## Conditions and references', '| Condition ID | Arm | Label | Original time | Minutes |', '|---|---|---|---|---|']
    for c in design['conditions']:
        brief.append(f"| {c['condition_id']} | {c['arm_id']} | {c['label']} | {c.get('time')} | {(c.get('time') or {}).get('minutes')} |")
    brief += [study_display_markdown(study_display(design, context)),comparison_markdown(design),
              '## Contrasts', json.dumps(design['contrasts'], ensure_ascii=False, indent=2),
              '## User research questions — complete original', json.dumps(questions, ensure_ascii=False, indent=2),
              '## Experimental context — complete original', json.dumps(original.get('analysis_context'), ensure_ascii=False, indent=2),
              '## Requested analysis and report preferences', json.dumps({k: original.get(k) for k in ('analysis_options','report_options')}, ensure_ascii=False, indent=2),
              'Legacy LLM/report execution options are writing preferences only in this package workflow.',
              '## Literature inclusion', json.dumps(literature, ensure_ascii=False, indent=2),
              '## Unresolved facts', json.dumps(design.get('issues', []), ensure_ascii=False, indent=2),
              'Unknown acquisition, upstream normalization, localization and biological replication must not be invented.',
              'See user_input_snapshot.json for every remaining raw research field and input_field_manifest.csv for its disposition.']
    return fields, validation, '\n\n'.join(brief) + '\n'


def write_delivery_receipt(directory, snapshot):
    """Bind written metadata to the saved source; no scientific tables are changed."""
    root = Path(directory)
    if snapshot.get('schema_version') != VERSION: return
    verify_snapshot(snapshot)
    names = ['study/user_input_snapshot.json', 'study/study_context.json', 'study/study_design.json']
    receipt = {'schema_version': 'input_delivery.v1', 'source': snapshot['source_receipt'],
               'document_sha256': {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in names}}
    if (root/'provenance.json').is_file():
        receipt['run_id'] = json.loads((root/'provenance.json').read_text()).get('run_id')
    (root/'study/input_delivery_receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')


def validate_delivery(directory, archive=None):
    """Read back exact JSON pointers/values and bytes, including the sealed ZIP.

    Old packages have no source receipt: do not claim an end-to-end verification.
    Errors contain field paths and reasons, never supplied values or secrets.
    """
    import csv
    import io
    root = Path(directory)
    stage = 'zip' if archive is not None else 'package_json'
    def read(name):
        if Path(name).is_absolute() or '..' in Path(name).parts: raise ValueError('Unsafe input locator')
        return archive.read(name) if archive is not None else (root/name).read_bytes()
    try: packet = json.loads(read('reader/authoring_packet.json'))
    except (FileNotFoundError, KeyError): packet = None
    if packet and packet.get('study_context_delivery', {}).get('file'):
        from .study_context_delivery import verify_context_binding
        verify_context_binding(root, packet['study_context_delivery'], read=read)
    try: receipt = json.loads(read('study/input_delivery_receipt.json'))
    except (FileNotFoundError, KeyError):
        try: version = json.loads(read('study/user_input_snapshot.json')).get('schema_version')
        except (FileNotFoundError, KeyError): version = None
        if version == VERSION: raise ValueError('Research input delivery: ' + stage + ' /source_receipt missing')
        return {'status': 'legacy_unverified', 'validation_scope': stage}
    errors = []
    snapshot = json.loads(read('study/user_input_snapshot.json'))
    verify_snapshot(snapshot, receipt['source'], stage=stage)
    if packet and not packet.get('study_context_delivery', {}).get('file'):
        errors.append({'stage': stage, 'field_path': 'reader/authoring_packet.json#/study_context_delivery', 'reason': 'consumer_binding_missing'})
    for name, expected in receipt['document_sha256'].items():
        try: actual = hashlib.sha256(read(name)).hexdigest()
        except (FileNotFoundError, KeyError): actual = None
        if actual != expected: errors.append({'stage': stage, 'field_path': name, 'reason': 'missing' if actual is None else 'stale_source'})
    if receipt.get('run_id'):
        provenance = json.loads(read('provenance.json'))
        if receipt['run_id'] not in {provenance.get('run_id'), provenance.get('execution_snapshot_run_id')}:
            errors.append({'stage': stage, 'field_path': 'provenance.json#/run_id', 'reason': 'stale_source'})
    fields = list(csv.DictReader(io.StringIO(read('study/input_field_manifest.csv').decode('utf-8'))))
    design = json.loads(read('study/study_design.json')); context = json.loads(read('study/study_context.json'))
    literature = json.loads(read('references/literature_pin.json'))
    expected = {f['source_field_path']: f for f in transfer_contract(snapshot, design, context, literature)[0]}
    seen = set(); verified = 0
    for field in fields:
        path = field['source_field_path']
        if path in seen or path not in expected:
            errors.append({'stage': stage, 'field_path': path, 'reason': 'duplicate_or_unknown_field'}); continue
        seen.add(path); wanted = expected[path]
        if field['disposition'] == 'excluded':
            if wanted['disposition'] != 'excluded' or field.get('original_value_ref'):
                errors.append({'stage': stage, 'field_path': path, 'reason': 'invalid_exclusion'})
            continue
        for key in ['original_value_ref', 'canonical_value_ref']:
            locator = field.get(key)
            if (locator or None) != (wanted.get(key) or None):
                errors.append({'stage': stage, 'field_path': path, 'reason': 'wrong_' + key}); continue
            if not locator: continue
            try:
                name, pointer = locator.split('#', 1)
                value = resolve_pointer(json.loads(read(name)), pointer)
                if key == 'original_value_ref':
                    if type(value).__name__ != field['raw_value_type']: raise TypeError('type_changed')
                    if value_hash(value) != field['raw_value_sha256']: raise TypeError('value_changed')
                    verified += 1
            except (KeyError, IndexError, ValueError, TypeError, FileNotFoundError) as exc:
                errors.append({'stage': stage, 'field_path': path, 'reason': str(exc) if isinstance(exc, TypeError) else 'unresolved_' + key})
    for path in expected.keys() - seen:
        errors.append({'stage': stage, 'field_path': path, 'reason': 'manifest_field_missing'})
    if errors: raise ValueError('Research input delivery: ' + json.dumps(errors, ensure_ascii=False))
    return {'schema_version': 'input_delivery.v1', 'status': 'verified', 'validation_scope': stage,
            'source_record_id': snapshot['source_record_id'], 'raw_transferred': verified,
            'unexpected_missing': 0, 'exactly_one_disposition': True,
            'unicode_and_null_false_zero_empty_preserved': True,
            'context_completeness': 'not_assessed', 'semantic_review': 'not_performed'}
