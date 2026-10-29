"""Read-only display projection. Never declares statistical units or changes a design."""
from collections import defaultdict
from copy import deepcopy
import json
import math
from pathlib import Path

DISPLAY = json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))


def _replicate_id(value):
    # Numeric 1 and serialized "1" agree. Explicit "01", "1.0", "A" and "a"
    # remain different IDs; no max(), sequence position or filename inference.
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        return value if value.strip() else None
    if isinstance(value, (int, float)) and math.isfinite(value):
        return str(int(value)) if value == int(value) else str(value)
    return None


def _planned_count(value):
    if isinstance(value, bool): return None
    if isinstance(value, str) and value.isdecimal(): value = int(value)
    return int(value) if isinstance(value, (int, float)) and math.isfinite(value) and value > 0 and int(value) == value else None


def study_display(design, context=None):
    """Project canonical condition IDs and recorded Rep. IDs, including Control once.

    Plans are display metadata, explicitly supplied by a new-experiment source or
    a stored context. Old experiments never acquire a retrospective plan of 3.
    """
    context = context or {}
    study = design.get('study') or {}
    plan = context.get('replication_plan')
    plan = plan if isinstance(plan, dict) else {}
    default_plan = _planned_count(plan.get('default_replicates_per_condition'))
    per_condition = plan.get('per_condition')
    per_condition = per_condition if isinstance(per_condition, dict) else {}
    injections = design.get('injections') or []
    files, injection_ids = set(), set()
    file_assignments, id_assignments = defaultdict(set), defaultdict(set)
    grouped = defaultdict(list)
    for row in injections:
        cid, column, iid = row.get('condition_id'), row.get('input_column'), row.get('injection_id')
        rep = _replicate_id(row.get('legacy_replicate'))
        grouped[cid].append(row)
        if column:
            files.add(column); file_assignments[column].add((cid, iid, rep))
        if iid:
            injection_ids.add(iid); id_assignments[iid].add((cid, column, rep))
    conditions = []
    ordered = sorted(design.get('conditions') or [], key=lambda c: (c.get('time') or {}).get('minutes') if (c.get('time') or {}).get('minutes') is not None else math.inf)
    for condition in ordered:
        cid = condition['condition_id']; rows = grouped[cid]
        columns = {r['input_column'] for r in rows if r.get('input_column')}
        ids = {r['injection_id'] for r in rows if r.get('injection_id')}
        replicates = {}; missing = set(); records = set(); statuses = []
        for row in rows:
            column, iid = row.get('input_column'), row.get('injection_id')
            identity = ('column', column) if column else ('injection', iid)
            rep = _replicate_id(row.get('legacy_replicate'))
            if rep is None: missing.add(identity)
            else: replicates.setdefault(rep, set()).add(identity)
            record = (column, iid, rep)
            if record in records and 'duplicate_injection_records' not in statuses: statuses.append('duplicate_injection_records')
            records.add(record)
        if not rows: statuses.append('no_registered_injections')
        if missing: statuses.append('replicate_id_missing')
        if any(not r.get('input_column') or not r.get('injection_id') for r in rows): statuses.append('injection_identity_missing')
        if any(len(file_assignments[c]) > 1 for c in columns) or any(len(id_assignments[i]) > 1 for i in ids):
            statuses.append('injection_mapping_conflict')
        repeated = [rep for rep, identities in replicates.items() if len(identities) > 1]
        if repeated: statuses.append('multiple_injections_per_replicate_id')
        numeric = [int(rep) for rep in replicates if rep.isdecimal() and str(int(rep)) == rep]
        if numeric and len(numeric) == len(replicates) and sorted(numeric) != list(range(1, len(numeric)+1)):
            statuses.append('nonconsecutive_replicate_ids')
        planned = _planned_count(per_condition[cid]) if cid in per_condition else default_plan
        comparison = ('not_recorded' if planned is None else 'incomplete_registration' if missing or not rows else
                      'matches' if planned == len(replicates) else 'differs')
        conditions.append({'condition_id': cid, 'label': condition.get('label', cid), 'replicate_ids': list(replicates),
            'registered_replicate_count': len(replicates), 'measurement_file_count': len(columns), 'injection_count': len(ids),
            'missing_replicate_id_count': len(missing), 'multiple_injection_replicate_ids': repeated,
            'planned_replicate_count': planned, 'plan_comparison': comparison, 'statuses': statuses})
    counts = {c['registered_replicate_count'] for c in conditions}
    uniform = len(counts) == 1 and next(iter(counts), 0) > 0 and all(not c['missing_replicate_id_count'] and 'injection_mapping_conflict' not in c['statuses'] for c in conditions)
    if uniform:
        registered = f'조건별 {next(iter(counts))}반복'
    else:
        registered = ' · '.join(f"{c['label']} {c['registered_replicate_count']}" +
            (f" (번호 미기록 {c['missing_replicate_id_count']})" if c['missing_replicate_id_count'] else '') for c in conditions) or '등록 없음'
    summary = f'등록 반복: {registered} · 총 {len(files)}개 측정 파일'
    planned_values = {c['planned_replicate_count'] for c in conditions}
    planned_summary = None
    if default_plan is not None and (not conditions or planned_values == {default_plan}):
        planned_summary = f'예정 반복: 조건별 {default_plan} (실제 등록 수와 별도)'
    elif any(c['planned_replicate_count'] is not None for c in conditions):
        planned_summary = '예정 반복: ' + ' · '.join(f"{c['label']} {c['planned_replicate_count']}" for c in conditions if c['planned_replicate_count'] is not None)
    materials = design.get('materials') or []
    return {'schema_version': 'study_display.v1',
        'biological_question': {**DISPLAY['biological_question'], 'storage_key': 'biological_question',
            'value': deepcopy(context['biological_question'] if 'biological_question' in context else study.get('biological_question'))},
        'replication': {'source': 'study_design.injections[].legacy_replicate', 'conditions': conditions,
            'summary': summary, 'planned_summary': planned_summary, 'plan_source': plan.get('source'),
            'measurement_file_count': len(files), 'injection_count': len(injection_ids),
            'material_count': len({m['material_id'] for m in materials}),
            'biological_unit_count': len({m['biological_unit_id'] for m in materials if m.get('biological_unit_id')}),
            'unmapped_injection_count': len({r['injection_id'] for r in injections if r.get('injection_id') and not r.get('material_id')}),
            'replication_type': design.get('replication_declaration') or 'unknown',
            'pairing': list(dict.fromkeys(c.get('pairing') or 'unknown' for c in design.get('contrasts') or [])),
            'interpretation': 'Rep. ID 개수, 측정 파일/주입 수, material/biological unit 수는 서로 다릅니다. 번호만으로 technical/biological/paired를 선언하지 않습니다.'}}


def study_display_markdown(projection):
    field = projection['biological_question']; replication = projection['replication']
    lines = ['## '+field['label'], field['description'], field['value'] if field['value'] is not None else '미기록',
             '## 등록 반복과 반복 설계', replication['summary']]
    if replication['planned_summary']: lines.append(replication['planned_summary'])
    lines += [f"반복 유형: {replication['replication_type']} · material {replication['material_count']} · biological unit {replication['biological_unit_count']} · injection {replication['injection_count']}",
              'Pairing: '+(', '.join(replication['pairing']) or 'unknown'), replication['interpretation']]
    table = ['| Condition | 등록 Rep. ID | 등록 반복 | 측정 파일 | 주입 | 예정 반복 | 상태 |', '|---|---|---|---|---|---|---|']
    def cell(value): return str(value).replace('|', '\\|').replace('\n', '<br>')
    for c in replication['conditions']:
        table.append('| '+' | '.join(cell(v) for v in [c['label'], ', '.join(c['replicate_ids']), c['registered_replicate_count'],
            c['measurement_file_count'], c['injection_count'], c['planned_replicate_count'] if c['planned_replicate_count'] is not None else '미기록',
            ', '.join(c['statuses']) or 'recorded'])+' |')
    return '\n\n'.join(lines + ['\n'.join(table)])
