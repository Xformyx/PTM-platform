"""Reference assignment inside the common study resolver; no numerical estimator.

The requested policy is editable input. Effective policy and point assignments
are an immutable part of each execution design, never a replacement condition ID.
"""
from copy import deepcopy
import json
from pathlib import Path

VERSION = 'control_comparison.v1'
STRATEGIES = {'shared_reference', 'time_matched', 'explicit_custom'}
LABELS = json.loads(Path(__file__).with_name('study_display.json').read_text())['control_comparison']


def condition_order(condition):
    minutes = (condition.get('time') or {}).get('minutes')
    return (float('inf') if minutes is None else minutes, condition.get('arm_id', ''), condition['condition_id'])


def reference_family(condition):
    # An explicit family takes precedence. The one reference arm is a known
    # family scope; this never infers a vehicle from free-form study prose.
    return condition.get('control_family') or condition['arm_id']


def resolve_assignments(context, conditions, previous, preserved, default_pairing):
    from .study_design import same_time, stable_id, issue
    indexed = {c['condition_id']: c for c in conditions}
    references = [c for c in conditions if c.get('role') == 'reference']
    targets = sorted([c for c in conditions if c.get('role') != 'reference'], key=condition_order)
    old_extension = previous.get('control_comparison') or {}
    requested = deepcopy(context.get('control_comparison') if 'control_comparison' in context else old_extension.get('requested_policy'))
    if requested is not None and not isinstance(requested, dict):
        raise ValueError('control_comparison must be an object')
    if requested and requested.get('schema_version', VERSION) != VERSION:
        raise ValueError('Unsupported control comparison policy version')
    if requested and requested.get('strategy') not in STRATEGIES:
        raise ValueError('Unknown control comparison strategy')
    for key in ['mappings', 'arm_control_families']:
        if requested and key in requested:
            mapping=requested[key]
            if not isinstance(mapping,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in mapping.items()):
                raise ValueError('control_comparison.' + key + ' must map string IDs to string IDs')
    if requested and requested.get('reference_condition_id') is not None and not isinstance(requested['reference_condition_id'],str):
        raise ValueError('control_comparison.reference_condition_id must be a string ID')
    changed = requested is not None and requested != old_extension.get('requested_policy')
    families = {reference_family(c) for c in references}
    def family(target):
        return (requested or {}).get('arm_control_families', {}).get(target['arm_id']) or target.get('control_family') or (next(iter(families)) if len(families) == 1 else None)
    def matches(target):
        f = family(target)
        return [r for r in references if f and reference_family(r) == f and
                same_time((r.get('time') or {}).get('minutes'), (target.get('time') or {}).get('minutes'))]
    # Old, explicitly confirmed mappings are restored rather than reclassified
    # as time-matched merely because their times happen to coincide.
    protected = {c['target_condition_id']: c for c in preserved} if not changed else {}
    condition_overrides = {c['condition_id']: c['reference_condition_id'] for c in targets if c.get('reference_condition_id')} if not changed else {}
    historical = list(protected.values()) + [{'target_condition_id': k, 'reference_condition_id': v} for k,v in condition_overrides.items()]
    if requested:
        effective = {**requested, 'schema_version': VERSION, 'source': requested.get('source', 'user_input')}
    elif historical:
        refs = {c['reference_condition_id'] for c in historical}
        is_shared = len(refs)==1 and all(indexed.get(ref,{}).get('role')=='reference' for ref in refs)
        effective = {'schema_version': VERSION, 'strategy': 'shared_reference' if is_shared else 'explicit_custom',
                     'source': 'restored_mapping', 'mappings': {c['target_condition_id']: c['reference_condition_id'] for c in historical}}
        if len(refs) == 1: effective['reference_condition_id'] = next(iter(refs))
    elif len(references) == 1:
        effective = {'schema_version': VERSION, 'strategy': 'shared_reference', 'reference_condition_id': references[0]['condition_id'], 'source': 'automatic_selection'}
    elif targets and all(len(matches(t)) == 1 for t in targets):
        effective = {'schema_version': VERSION, 'strategy': 'time_matched', 'source': 'automatic_selection'}
    else:
        effective = {'schema_version': VERSION, 'strategy': None, 'source': 'unresolved'}
    if effective['strategy']=='shared_reference' and not effective.get('reference_condition_id') and len(references)==1:
        effective['reference_condition_id']=references[0]['condition_id']
    strategy = effective['strategy']; errors = []; contrasts = []; assignments = []
    old = previous.get('contrasts') or []
    for target in targets:
        tid = target['condition_id']; f = family(target); local = []; candidates = []; reference = None
        confirmed = protected.get(tid)
        source = effective['source']
        if confirmed:
            reference = confirmed['reference_condition_id']; source = confirmed.get('reference_assignment_source', 'preserved_confirmed_mapping')
        elif tid in condition_overrides:
            reference = condition_overrides[tid]; source = 'declared_condition_reference'
        elif strategy == 'shared_reference':
            reference = effective.get('reference_condition_id') or (references[0]['condition_id'] if len(references) == 1 else None)
            if reference is None:
                local.append(issue('shared_reference_missing', 'control_comparison.reference_condition_id', '모든 처리 조건에 사용할 공통 Control을 지정하세요.'))
        elif strategy == 'explicit_custom':
            reference = effective.get('mappings', {}).get(tid)
            if reference is None:
                local.append(issue('custom_reference_missing', 'control_comparison.mappings.'+tid, target['label']+': 사용할 Control을 지정하세요.'))
        elif strategy == 'time_matched':
            if not f:
                local.append(issue('control_family_unresolved', 'control_comparison.arm_control_families.'+target['arm_id'], target['label']+': 대응 Control family를 지정하세요.'))
            else:
                candidates = matches(target)
                if len(candidates) == 1: reference = candidates[0]['condition_id']
                elif not candidates:
                    local.append(issue('matched_reference_missing', 'conditions.'+tid+'.reference_condition_id', target['label']+': 같은 시간의 대응 Control이 없습니다.'))
                else:
                    local.append(issue('matched_reference_ambiguous', 'conditions.'+tid+'.reference_condition_id',
                        f"{target['label']}: 대응 가능한 Control이 {len(candidates)}개입니다. 사용할 Control을 지정하세요.",
                        candidate_count=len(candidates), candidate_ids=sorted(c['condition_id'] for c in candidates)))
        else:
            local.append(issue('reference_unresolved', 'conditions.'+tid+'.reference_condition_id', '모든 처리 조건에 사용할 공통 Control을 지정하세요. 또는 시간대별 Control 기준을 선택하세요.'))
        ref = indexed.get(reference)
        if reference and (ref is None or reference == tid or (ref.get('role') != 'reference' and not confirmed and not (tid in condition_overrides and not requested))):
            local.append(issue('control_reference_invalid', 'conditions.'+tid+'.reference_condition_id', target['label']+': 지정된 Control 조건이 유효하지 않습니다.'))
        if ref and strategy == 'time_matched' and (not f or reference_family(ref) != f or not same_time((target.get('time') or {}).get('minutes'), (ref.get('time') or {}).get('minutes'))):
            local.append(issue('confirmed_reference_conflict', 'conditions.'+tid+'.reference_condition_id', target['label']+': 확정된 Control 연결이 현재 시간 또는 control family와 충돌합니다. 해당 연결을 수정하세요.'))
        if ref and strategy == 'shared_reference' and effective.get('reference_condition_id') and reference != effective['reference_condition_id']:
            local.append(issue('confirmed_reference_conflict', 'conditions.'+tid+'.reference_condition_id', target['label']+': 확정된 연결이 공통 Control 설정과 다릅니다.'))
        errors.extend({**e, 'target_condition_id': tid} for e in local)
        previous_same = next((c for c in old if c['target_condition_id'] == tid and c['reference_condition_id'] == reference), None)
        previous_target = next((c for c in old if c['target_condition_id'] == tid), None)
        kind = ('matched_treatment_effect' if strategy == 'time_matched' else 'baseline_change' if strategy == 'shared_reference' and ref and (ref.get('time') or {}).get('minutes') == 0 else 'reference_change' if strategy == 'shared_reference' else 'custom_contrast')
        contrast = None
        if reference and (not local or confirmed):
            contrast = deepcopy(confirmed) if confirmed else {
                'contrast_id': (previous_same or {}).get('contrast_id') or stable_id('contrast', tid+'|'+reference),
                'target_condition_id': tid, 'reference_condition_id': reference,
                'pairing': previous_target['pairing'] if changed and previous_target else default_pairing,
                'purpose': 'target_vs_declared_reference',
                'source': source if strategy != 'shared_reference' or len(references) != 1 else 'single_existing_reference_group'}
            contrast.update(reference_strategy=strategy, effect_kind=kind, control_family=f if strategy=='time_matched' else reference_family(ref) if ref else None,
                            reference_assignment_source=source, reference_policy_version=VERSION, assignment_status='conflict' if local else 'resolved')
            contrasts.append(contrast)
        assignments.append({'target_condition_id': tid, 'target_label': target['label'], 'target_time': deepcopy(target.get('time')),
            'arm_id': target['arm_id'], 'reference_condition_id': reference, 'reference_label': ref.get('label') if ref else None,
            'reference_time': deepcopy(ref.get('time')) if ref else None, 'control_family': f,
            'contrast_id': contrast['contrast_id'] if contrast else None, 'pairing': contrast['pairing'] if contrast else default_pairing,
            'reference_strategy': strategy, 'effect_kind': kind, 'source': source,
            'status': 'unresolved' if local or not contrast else 'resolved', 'issues': local})
    # Explicit historical comparisons with reference-role targets (e.g. control
    # drift) are retained, never quietly discarded by a new basic UI policy.
    retained_ids={c['contrast_id'] for c in contrasts}
    for c in preserved:
        if c['contrast_id'] in retained_ids or (changed and c['target_condition_id'] in {t['condition_id'] for t in targets}):continue
        contrasts.append(deepcopy(c))
        target=indexed.get(c['target_condition_id'],{});ref=indexed.get(c['reference_condition_id'],{})
        assignments.append({'target_condition_id':c['target_condition_id'],'target_label':target.get('label',c['target_condition_id']),
            'target_time':deepcopy(target.get('time')),'arm_id':target.get('arm_id'),'reference_condition_id':c['reference_condition_id'],
            'reference_label':ref.get('label',c['reference_condition_id']),'reference_time':deepcopy(ref.get('time')),
            'contrast_id':c['contrast_id'],'pairing':c['pairing'],'reference_strategy':c.get('reference_strategy'),
            'effect_kind':c.get('effect_kind'),'source':'preserved_confirmed_mapping','status':'resolved','issues':[]})
    extension = {'schema_version': VERSION, 'requested_policy': requested, 'effective_policy': effective,
        'assignments': assignments, 'status': 'draft' if errors else 'resolved',
        'readiness': {'design_assignment': 'supported', 'contrast_quantification': 'existing_estimator',
                      'matched_temporal': 'descriptive_effect_series_v2', 'biological_pq': 'not_implemented', 'legacy_multiple_controls': 'unsupported'}}
    return contrasts, extension, errors


def validate_assignment_contract(design):
    """Execution validation also checks direct/stale canonical payloads."""
    from .study_design import issue, same_time
    extension = design.get('control_comparison')
    if not extension: return []  # Recorded old designs retain their contract.
    conditions = {c['condition_id']: c for c in design.get('conditions', [])}
    contrasts = {c['contrast_id']: c for c in design.get('contrasts', [])}
    errors = []
    for assignment in extension.get('assignments', []):
        cid = assignment.get('contrast_id'); c = contrasts.get(cid)
        if assignment.get('status') != 'resolved' or not c:
            errors.append(issue('control_assignment_unresolved', 'control_comparison.assignments', assignment.get('target_label','')+': 비교 연결이 미해결입니다.'))
            continue
        for key in ['target_condition_id','reference_condition_id','reference_strategy','effect_kind']:
            if assignment.get(key) != c.get(key): errors.append(issue('control_assignment_mismatch', 'contrasts.'+cid, 'Saved policy and actual contrast disagree: '+key))
        if c.get('reference_strategy') == 'time_matched':
            target, ref = conditions.get(c['target_condition_id'],{}), conditions.get(c['reference_condition_id'],{})
            if not same_time((target.get('time') or {}).get('minutes'), (ref.get('time') or {}).get('minutes')) or reference_family(ref) != c.get('control_family'):
                errors.append(issue('matched_reference_invalid', 'contrasts.'+cid, 'Time-matched contrast must use the same time and control family'))
    return errors


def legacy_support(context, sample_config):
    from .study_design import legacy_samples
    rows = legacy_samples(sample_config)
    references = {(r.get('condition_id') or r['condition'], r.get('control_family'), r.get('arm_id') or r.get('arm'))
                  for r in rows if r.get('role')=='reference' or r['group'].lower()=='control'}
    policy = (context or {}).get('control_comparison') or {}
    unsupported = len(references)>1 or policy.get('strategy')=='time_matched'
    return {'status':'unsupported' if unsupported else 'supported', 'code':'legacy_multiple_controls_unsupported' if unsupported else 'legacy_shared_control',
            'message':'Legacy processing은 시간대별/다중 Control을 지원하지 않습니다. Astra 경로에서 비교를 지정하세요.' if unsupported else 'Legacy shared Control supported'}


def comparison_summary(design):
    """Recorded execution display; no live context or new reference matching."""
    result=deepcopy(design.get('control_comparison'))
    if not result:return None
    policy=result['effective_policy'];strategy=policy.get('strategy')
    result['label']=LABELS[strategy]['label'] if strategy else '미지정'
    result['english_label']=LABELS.get(strategy,{}).get('english_label')
    provenance=design.get('field_provenance') or {}
    for point in result['assignments']:
        for side in ['target','reference']:
            point[side+'_time_source']=deepcopy(provenance.get('conditions.'+str(point[side+'_condition_id'])+'.time'))
    return result


def comparison_markdown(design):
    summary=comparison_summary(design)
    if not summary:return ''
    def cell(value):return str(value if value is not None else '미기록').replace('|','\\|').replace('\n','<br>')
    def time(value):return f"{value['value']} {value['unit']} ({value['minutes']} min)" if value else '미기록'
    lines=['## '+LABELS['label'], '', summary['label'], '', LABELS['sample_note'], '',
           '| Contrast ID | 처리 조건 / ID | 처리 시간 | Control 조건 / ID | Control 시간 | 효과 의미 | 연결 출처 / 상태 |',
           '|---|---|---|---|---|---|---|']
    for p in summary['assignments']:
        lines.append('| '+' | '.join(cell(v) for v in [p['contrast_id'],f"{p['target_label']} / {p['target_condition_id']}",time(p['target_time']),
            f"{p['reference_label']} / {p['reference_condition_id']}",time(p['reference_time']),p['effect_kind'],f"{p['source']} / {p['status']}"])+' |')
    lines+=['','실행 snapshot의 실제 비교입니다. 생물학적 p/q 검정은 수행하지 않습니다.']
    return '\n'.join(lines)
