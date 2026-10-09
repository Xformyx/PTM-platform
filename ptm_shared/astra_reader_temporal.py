"""Saved temporal evidence -> reader references. No estimation, selection or fit.

Identity joins use canonical keys, never display labels. Values (including JSON
vectors and their NA masks) are copied from saved rows. This projection can run
on an archived package without an estimator, method runtime or network.
"""
from collections import Counter
import json
from pathlib import Path

import pandas as pd

from .astra_card_inputs import clean, encode

VERSION = 'saved_temporal_reader.v1'
SERIES = 'temporal/temporal_series'
PTM = 'temporal/ptm_temporal_features'
PROTEIN = 'temporal/protein_temporal_features'
KINASE = 'temporal/kinase_temporal_features'
INTERVAL = 'temporal/interval_contrasts'
FIXED = 'temporal/kinase_fixed_membership'
ANCHOR = 'temporal/target_excluded_anchors'
COWAVE = 'temporal/group_excluded_cowave'
PROFILE = 'kinase/kinase_temporal_profiles'
CONTRIBUTION = 'kinase/substrate_contributions'
KEYS = {
    SERIES: ['series_id'], PTM: ['feature_id'], PROTEIN: ['feature_id'], KINASE: ['feature_id'],
    INTERVAL: ['interval_id'], FIXED: ['candidate_id', 'series_id', 'contrast_id', 'track'],
    ANCHOR: ['candidate_id', 'series_id', 'track', 'site_key'], COWAVE: ['cowave_id'],
    PROFILE: ['candidate_id', 'contrast_id', 'track'], CONTRIBUTION: ['contribution_id'],
    'quant/summary': ['form_id'], 'quant/comparisons': ['form_id', 'contrast_id'],
    'quant/protein_contrasts': ['protein_group', 'contrast_id'],
    'quant/strict_unmodified_proteins': ['protein_group', 'contrast_id'],
}
SOURCE_TABLES = list(KEYS)
ARTIFACTS = ['reader/TEMPORAL_EVIDENCE.md', 'reader/temporal_evidence.json', 'reader/temporal_links.csv']
LIMITS = [
    'Saved observations only; no temporal calculation, scientific scoring or finding selection is performed here.',
    'observed_peak_time_min is the time of maximum ABSOLUTE observed effect; signed_peak retains its sign. It is not necessarily a positive peak.',
    'Onset/recovery are sampled observation brackets, not precisely measured event times. Preserve censoring, NA masks and irregular spacing; never bridge gaps.',
    'PTM A is inclusion-masked; U_joint/P_joint and U_all are distinct saved tracks. PG and strict_unmodified protein tracks are separate from joint-mask P_joint.',
    'Adjacent U_joint/P_joint/A and run IDs are saved interval contrasts, never differences between two baseline contrasts.',
    'AUC only covers the stored supported duration; report gap_intervals alongside it. Threshold sensitivity and LOTO are same-data robustness diagnostics.',
    'Available/fixed membership and target/gene/measurement-group exclusion are same-data consistency checks, not independent validation, biological significance or kinase-site causality.',
    'First-time entered_sites is initialization of the compared membership sets, not baseline-undetected emergence. No common sites means fixed score NA, not zero.',
    'Descriptive footprint values are log2 relative changes; PhosX native scores and method p/q are separate. Do not apply footprint onset/peak rules to PhosX native scores.',
    'Technical injections are not biological replicates. Stored statistical_unit names describe aggregation, not evidence for population inference. No-call, unmeasured localization and literature review restrictions remain in force.',
]


def _parts(value):
    return str(value).split(';') if value is not None and not pd.isna(value) else []


def source_row(value):
    row = clean(value)
    # Nullable boolean columns are object/string when read using the archived
    # dictionary, but bool/NA under pandas inference. Keep one typed meaning.
    for name in ('parent_pattern_agreement', 'normalization_pattern_agreement'):
        if row.get(name) in ('True', 'False'):
            row[name] = row[name] == 'True'
    return row


def project_temporal(tables, packet):
    """Return a deterministic row projection and a deduplicated evidence crosswalk.

    Duplicate source keys are rejected. Nonunique series or feature scope is
    reported as ambiguous and not resolved by picking a first row.
    """
    used = {name: set() for name in KEYS}
    links = {}
    for name, keys in KEYS.items():
        frame = tables.get(name, pd.DataFrame())
        if len(frame) and frame.duplicated(keys).any():
            raise ValueError('Duplicate temporal reader source key: ' + name)

    def rows(name, **where):
        frame = tables.get(name, pd.DataFrame())
        if frame.empty: return []
        for key, value in where.items():
            frame = frame.loc[frame[key].eq(value)]
        return sorted((source_row(r) for r in frame.to_dict('records')), key=lambda r: encode([r[k] for k in KEYS[name]]))

    def bind(finding, name, row, role):
        key = {k: row[k] for k in KEYS[name]}
        ref = {'table': name + '.csv', 'key': key}
        identity = encode(key)
        used[name].add(identity)
        lk = (finding, name, identity)
        links.setdefault(lk, {'finding_id': finding, 'source_table': name + '.csv', 'source_key': key, 'roles': []})
        if role not in links[lk]['roles']: links[lk]['roles'].append(role)
        return {'source': ref, 'row': row}

    cards = {c['card_id']: c for c in packet['reader_cards']}
    findings = []
    for f in tables['reader/findings'].to_dict('records'):
        fid, form = f['finding_id'], f['form_id']
        card = cards[f['card_id']]
        bindings = card['source_bindings']
        scopes = {(b['arm_id'], b['reference_condition_id'], b['pairing']) for b in bindings}
        item = {'finding_id': fid, 'card_id': f['card_id'], 'form_id': form,
                'label': card['feature_label'], 'status': 'unlinked', 'reasons': [],
                'features': [], 'intervals': [], 'candidates': [], 'source_observations': []}
        findings.append(item)
        if len(scopes) != 1:
            item.update(status='ambiguous', reasons=['multiple_card_scopes']); continue
        arm, reference, pairing = next(iter(scopes))
        cids = {b['contrast_id'] for b in bindings}
        matches = [r for r in rows(SERIES, arm_id=arm, reference_condition_id=reference, pairing=pairing)
                   if cids.issubset(_parts(r['contrast_ids']))]
        if len(matches) != 1:
            item.update(status='ambiguous' if matches else 'unlinked',
                        reasons=['nonunique_series_scope' if matches else 'no_saved_series_for_card_scope']); continue
        series = matches[0]; sid = series['series_id']
        item['series'] = bind(fid, SERIES, series, 'series')
        item['scope'] = {'series_id': sid, 'arm_id': arm, 'reference_condition_id': reference, 'pairing': pairing}
        # Validate exact contrast membership and canonical numeric times, not ID order.
        design = packet['canonical_study_design']
        conditions = {r['condition_id']: r for r in design['conditions']}
        contrasts = {r['contrast_id']: r for r in design['contrasts']}
        ordered = sorted(_parts(series['contrast_ids']), key=lambda cid: (conditions[contrasts[cid]['target_condition_id']]['time']['minutes'], cid))
        for cid in ordered:
            c = contrasts[cid]; target = conditions[c['target_condition_id']]
            if (target['arm_id'], c['reference_condition_id'], c['pairing']) != (arm, reference, pairing):
                raise ValueError('Temporal series scope conflict: ' + sid)
        item['ordered_contrast_ids'] = ordered
        for cid in ordered:
            for r in rows('quant/comparisons', form_id=form, contrast_id=cid):
                if (r['arm_id'], r['reference_condition_id'], r['pairing']) != (arm, reference, pairing):
                    raise ValueError('Temporal observation scope conflict: ' + cid)
                if r['time_min'] != conditions[contrasts[cid]['target_condition_id']]['time']['minutes']:
                    raise ValueError('Temporal observation time conflict: ' + cid)
                item['source_observations'].append(bind(fid, 'quant/comparisons', r, 'form_observation'))

        def features(name, entity, role, track=None):
            selected = rows(name, entity_id=entity, series_id=sid)
            if track is not None: selected = [r for r in selected if r['track'] == track]
            counts = Counter(r['track'] for r in selected)
            for r in selected:
                if counts[r['track']] != 1:
                    item['reasons'].append('ambiguous_feature_scope:' + role + ':' + r['track']); continue
                if (r['arm_id'], r['reference_condition_id']) != (arm, reference):
                    raise ValueError('Temporal feature scope conflict: ' + r['feature_id'])
                if json.loads(r['times_minutes']) != [conditions[contrasts[cid]['target_condition_id']]['time']['minutes'] for cid in ordered]:
                    raise ValueError('Temporal feature grid conflict: ' + r['feature_id'])
                entry = bind(fid, name, r, role)
                entry['role'] = role
                entry['contrast_ids'] = ordered
                yield entry

        item['features'] = list(features(PTM, form, 'ptm'))
        parents = rows('quant/summary', form_id=form)
        if len(parents) == 1:
            item['form_identity'] = bind(fid, 'quant/summary', parents[0], 'form_parent_identity')
            parent = parents[0].get('parent_pg')
            if parent:
                parent_features = list(features(PROTEIN, parent, 'parent_protein'))
                for feature in parent_features:
                    table = {'PG': 'quant/protein_contrasts', 'strict_unmodified': 'quant/strict_unmodified_proteins'}.get(feature['row']['track'])
                    feature['observations'] = [bind(fid, table, r, 'parent_observation') for cid in ordered
                        for r in rows(table, protein_group=parent, contrast_id=cid)] if table else []
                item['features'] += parent_features
        if not any(r['role'] == 'parent_protein' for r in item['features']): item['reasons'].append('no_saved_parent_feature')
        for r in sorted(rows(INTERVAL, form_id=form, series_id=sid), key=lambda r: (r['from_min'], r['to_min'], r['interval_id'])):
            if r['arm_id'] != arm or any(r[field] not in conditions for field in ('reference_condition_id', 'target_condition_id')):
                raise ValueError('Adjacent interval scope conflict: ' + r['interval_id'])
            if (r['from_min'], r['to_min']) != tuple(conditions[r[k]]['time']['minutes'] for k in ('reference_condition_id', 'target_condition_id')):
                raise ValueError('Adjacent interval time conflict: ' + r['interval_id'])
            allowed = {reference, *(contrasts[cid]['target_condition_id'] for cid in ordered)}
            if not {r['reference_condition_id'], r['target_condition_id']} <= allowed:
                raise ValueError('Adjacent interval outside series: ' + r['interval_id'])
            item['intervals'].append(bind(fid, INTERVAL, r, 'adjacent_joint_contrast'))

        members = tables.get(CONTRIBUTION, pd.DataFrame())
        selected = members.loc[members.form_ids.map(lambda value: form in _parts(value)) & members.contrast_id.isin(ordered)] if len(members) else members
        for (candidate, track), group in selected.groupby(['candidate_id', 'track'], sort=True) if len(selected) else []:
            cm = [clean(r) for r in group.to_dict('records')]
            evidence = {'candidate_id': candidate, 'series_id': sid, 'track': track,
                        'contributions': [bind(fid, CONTRIBUTION, r, 'candidate_contribution') for r in sorted(cm, key=lambda r: (ordered.index(r['contrast_id']), r['contribution_id']))],
                        'profiles': [], 'fixed_membership': [], 'exclusions': []}
            evidence['features'] = list(features(KINASE, candidate, 'descriptive_kinase', track))
            for cid in ordered:
                for r in rows(PROFILE, candidate_id=candidate, contrast_id=cid, track=track):
                    if (r['arm_id'], r['reference_condition_id']) != (arm, reference): raise ValueError('Footprint scope conflict')
                    evidence['profiles'].append(bind(fid, PROFILE, r, 'available_footprint'))
                for r in rows(FIXED, candidate_id=candidate, series_id=sid, contrast_id=cid, track=track):
                    entry = bind(fid, FIXED, r, 'fixed_footprint')
                    entry['unavailable_reason'] = 'no_common_sites' if r['fixed_common_sites'] == 0 else 'saved_score_unavailable' if r['fixed_common_score'] is None else None
                    evidence['fixed_membership'].append(entry)
            for site in sorted({r['site_key'] for r in cm}):
                for name, role in [(ANCHOR, 'target_excluded'), (COWAVE, 'gene_or_group_excluded')]:
                    for r in rows(name, candidate_id=candidate, series_id=sid, track=track, site_key=site):
                        entry = bind(fid, name, r, role)
                        if name == ANCHOR:
                            details = json.loads(r['details'])
                            entry['remaining_support'] = {
                                'site_keys_status': 'not_explicit_in_saved_target_anchor; do_not_infer_gene_or_group_exclusion',
                                'interval_counts': [{k: v for k, v in interval.items() if k in {'interval_id', 'from', 'to', 'n_anchor_groups', 'fixed_common_anchor_groups', 'anchor_status', 'anchor_reason'}}
                                    for interval in details.get('metrics', {}).get('interval_direction_support', [])]}
                        else:
                            entry['remaining_support'] = {'site_keys': _parts(r['remaining_site_keys'])}
                        evidence['exclusions'].append(entry)
            item['candidates'].append(evidence)
        if not item['candidates']: item['reasons'].append('no_saved_candidate_contribution_for_form_and_series')
        if not item['intervals']: item['reasons'].append('no_saved_adjacent_intervals')
        item['status'] = 'ambiguous' if any('ambiguous_' in r for r in item['reasons']) else 'linked' if any(r['role'] == 'ptm' for r in item['features']) else 'unlinked'
        if item['status'] == 'unlinked': item['reasons'].append('no_saved_ptm_feature')
        item['reasons'] = sorted(set(item['reasons']))
    inventory = [{'table': name + '.csv', 'total_rows': len(tables.get(name, [])), 'linked_unique_rows': len(used[name]),
                  'outside_reader_rows': len(tables.get(name, [])) - len(used[name]), 'retained': 'full_source_table'} for name in KEYS if name in tables]
    return {'version': VERSION, 'interpretation_limits': LIMITS, 'findings': findings,
            'coverage': dict(Counter(f['status'] for f in findings)), 'source_inventory': inventory,
            'links': list(links.values()), 'scientific_recalculation': False}


def attach_temporal(tables):
    """Add evidence to the existing packet/questions without modifying cards/findings."""
    if SERIES not in tables or 'reader/packet' not in tables: return
    packet = json.loads(tables['reader/packet'].iloc[0].packet_json)
    projected = project_temporal(tables, packet)
    packet['temporal_evidence'] = projected
    packet['authoring_rules']['temporal_evidence'] = {
        'required_evidence_anchor': 'Additional temporal statements must cite a supplied feature_id, interval_id, cowave_id or exact table + composite key from temporal_evidence.links, together with finding_id. Card IDs alone do not support an added temporal claim.',
        'source_index': 'reader/temporal_links.csv', 'reader': 'reader/TEMPORAL_EVIDENCE.md',
        'limits': LIMITS}
    packet['full_evidence']['saved_temporal'] = 'reader/TEMPORAL_EVIDENCE.md'
    for q in packet['research_question_evidence_map']['questions']:
        connected = [f for f in projected['findings'] if f['finding_id'] in q['finding_ids']]
        q['temporal_evidence'] = {'path': 'reader/TEMPORAL_EVIDENCE.md', 'crosswalk': 'reader/temporal_links.csv',
            'finding_status': {f['finding_id']: {'status': f['status'], 'reasons': f['reasons']} for f in connected},
            'answer_scope': 'Saved sampled brackets/absolute observed peak/adjacent contrasts and same-data sensitivity only; not precise event times, causality or independent validation.',
            'evidence': [link for link in projected['links'] if link['finding_id'] in q['finding_ids']]}
    tables['reader/packet'] = tables['reader/packet'].copy()
    tables['reader/packet'].loc[tables['reader/packet'].index[0], 'packet_json'] = json.dumps(packet, ensure_ascii=False, sort_keys=True)


def validate_temporal(tables):
    packet = json.loads(tables['reader/packet'].iloc[0].packet_json)
    if 'temporal_evidence' not in packet: return
    expected = project_temporal(tables, packet)
    def same(a, b):
        if isinstance(a, dict): return isinstance(b, dict) and a.keys() == b.keys() and all(same(v, b[k]) for k, v in a.items())
        if isinstance(a, list): return isinstance(b, list) and len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
        if a is None or b is None: return a is b
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            from math import isclose
            return isclose(a, b, abs_tol=1e-10, rel_tol=1e-10)
        return a == b
    if not same(expected, packet['temporal_evidence']):
        raise ValueError('Temporal reader projection differs from saved source rows')
    for q in packet['research_question_evidence_map']['questions']:
        if q['temporal_evidence']['evidence'] != [r for r in expected['links'] if r['finding_id'] in q['finding_ids']]:
            raise ValueError('Temporal question evidence differs from finding links')


def write_temporal(directory, packet):
    """Render only saved values. Full rows and exact keys remain in JSON/CSV."""
    data = packet.get('temporal_evidence')
    if data is None: return []
    from .generic_workflow import json_write
    directory = Path(directory) / 'reader'; directory.mkdir(parents=True, exist_ok=True)
    json_write(directory/'temporal_evidence.json', data)
    pd.DataFrame([{'finding_id': r['finding_id'], 'source_table': r['source_table'],
                   'source_key_json': encode(r['source_key']), 'roles_json': encode(r['roles'])} for r in data['links']],
                 columns=['finding_id', 'source_table', 'source_key_json', 'roles_json']).to_csv(directory/'temporal_links.csv', index=False)
    def fmt(value):
        return 'NA' if value is None else str(value).replace('|', '\\|').replace('\n', ' ')
    def table(headers, values):
        return ['| ' + ' | '.join(headers) + ' |', '| ' + ' | '.join(['---'] * len(headers)) + ' |',
                *['| ' + ' | '.join(fmt(v) for v in row) + ' |' for row in values], '']
    lines = ['# 저장된 시간 근거 — temporal evidence',
        '[READ_ME](READ_ME.md) · [전체 투영/값/NA/원본 키](temporal_evidence.json) · [finding→원본 행 대응표](temporal_links.csv) · [작성 지침](authoring_packet.json)',
        '기존 findings의 순서를 유지합니다. 새 분석·재정량·선정·문헌 검색은 수행하지 않았습니다. 시간 단위는 min, 변화량은 log2입니다.',
        *LIMITS, '## 전체 자료와 요약 범위',
        *table(['원본', '전체 행', '연결된 고유 행', '요약 밖에 보존'],
            [(f"[{r['table']}](../{r['table']})", r['total_rows'], r['linked_unique_rows'], r['outside_reader_rows']) for r in data['source_inventory']])]
    for f in data['findings']:
        lines += [f"## {f['label']} — {f['finding_id']}",
                  f"form `{f['form_id']}` · card `{f['card_id']}` · 연결: {f['status']}; 사유: {', '.join(f['reasons']) or '없음'}."]
        if 'scope' not in f: continue
        lines += ['범위: `' + encode(f['scope']) + '`',
                  'Peak는 **절댓값 최대 관측**이며 부호는 signed_peak에 남습니다. 구간 경계와 검열은 저장된 값입니다.',
                  *table(['layer/track', 'feature ID', 'times (min)', 'values / NA', '관측 mask'],
                    [(e['role']+'/'+e['row']['track'], e['row']['feature_id'], e['row']['times_minutes'], e['row']['values'], e['row']['observed_mask']) for e in f['features']]),
                  *table(['track / feature ID', 'peak min / signed', 'onset 구간 / left censored', 'recovery 구간 / right censored', 'pattern', 'threshold / sensitive', 'LOTO / n', 'AUC / 지원 min / gaps'],
                    [(r['track']+' / '+r['feature_id'], f"{fmt(r['observed_peak_time_min'])} / {fmt(r['signed_peak'])}",
                      f"[{fmt(r['onset_lower_min'])}, {fmt(r['onset_upper_min'])}] / {r['onset_left_censored']}",
                      f"[{fmt(r['recovery_lower_min'])}, {fmt(r['recovery_upper_min'])}] / {r['right_censored']}",
                      r['pattern'], f"{r['threshold']} / {r['threshold_sensitive']}", f"{fmt(r['loto_pattern_stability'])} / {r['observed_points']}",
                      f"{fmt(r['adjacent_trapezoid_auc'])} / {r['auc_supported_duration_min']} / {r['gap_intervals']}") for r in [e['row'] for e in f['features']]]),
                  '### 인접 joint-mask 비교',
                  '원래 interval_id와 run IDs는 JSON/대응표에 보존됩니다. baseline 대비 값의 차분이 아닙니다.',
                  *table(['min 구간', 'U_joint', 'P_joint', 'A', 'joint n ref/target', '상태', 'interval ID'],
                    [(f"{r['from_min']} → {r['to_min']}", r['U_joint'], r['P_joint'], r['A'], f"{r['reference_joint_n']}/{r['target_joint_n']}", r['status'], r['interval_id']) for r in [e['row'] for e in f['intervals']]])]
        if not f['candidates']: lines += ['이 form/series에 연결된 저장 기질 기여도가 없습니다. 후보 곡선을 gene 이름으로 추정하여 붙이지 않았습니다.']
        for c in f['candidates']:
            profiles = {e['row']['contrast_id']: e['row'] for e in c['profiles']}
            lines += [f"### {c['candidate_id']} / {c['track']}",
                      'Descriptive footprint입니다. PhosX native 점수는 [별도 방법 표](PHOSX_TIME_COURSE.md)를 확인하세요.' if 'specificity' in c['track'] else 'Descriptive footprint입니다. 확정 kinase 활성 또는 독립 검증이 아닙니다.',
                      *table(['min / contrast', 'available score', 'fixed score', 'common / available sites', 'entered / departed', 'turnover', 'NA 사유'],
                        [(f"{fmt(profiles.get(r['contrast_id'], {}).get('time_min'))} / {r['contrast_id']}", profiles.get(r['contrast_id'], {}).get('activity_magnitude'), r['fixed_common_score'],
                          f"{r['fixed_common_sites']} / {r['available_sites']}", f"{r['entered_sites']} / {r['departed_sites']}", r['membership_turnover'], e['unavailable_reason']) for e in c['fixed_membership'] for r in [e['row']]]),
                      'Target/gene/group 제외별 원 대상·남은 기질 및 details는 temporal_evidence.json의 exclusions에 원문 보존됩니다.',
                      *table(['제외 종류', '대상 site', 'signed r', 'interval concordance', 'support status', '원본 키'],
                        [(r.get('excluded_kind', 'target'), r['site_key'], r['signed_correlation'], r['interval_concordance'], r['support_status'], encode(e['source']['key'])) for e in c['exclusions'] for r in [e['row']]])]
    rendered = ''.join(('\n' if i and line.startswith('|') and lines[i-1].startswith('|') else '\n\n') + line for i, line in enumerate(lines)).lstrip()+'\n'
    (directory/'TEMPORAL_EVIDENCE.md').write_text(rendered, encoding='utf-8')
    return ARTIFACTS
