"""Round07: bind existing report cards to immutable Astra rows and serialize them.

Selection and descriptions come from the shared legacy report functions. This
module performs no quantification, kinase inference, literature search or LLM call.
"""
import json
from collections import Counter
from pathlib import Path

import pandas as pd

from .astra_card_inputs import clean, encode, equivalent, consumer_states
from .astra_inputs import stable_id
from .measured_feature_cards import (build_feature_observation_cards,
    build_quantitation_comparison_cards, select_finding_cards)
from .research_questions import build_question_map
from .reader_authoring import build_authoring_packet

VERSION = 'astra_reader.v1'
TABLE_KEYS = {'reader/cards': ['card_id'], 'reader/findings': ['finding_id'],
              'reader/coverage': ['adapter_row_id'], 'reader/packet': ['packet_id']}
ARTIFACTS = ['reader/READ_ME.md', 'reader/authoring_packet.json', 'reader/coverage_summary.json',
             'reader/question_map.json', 'reader/selection_audit.json']
AXES = [('ptm_unadjusted_log2fc', 'U_joint'), ('protein_log2fc', 'P_joint'),
        ('ptm_protein_adjusted_log2fc', 'A')]
LIMITS = ['Descriptive same-experiment observations; not kinase activation or causal validation.',
          'U_joint, P_joint and A use the recorded joint masks; U_all/P_all remain separate.',
          'Technical injections and substrate counts are not independent biological replicates.',
          'Sequence mapping does not establish MS localization; inspect per-contrast localization.',
          'Same-experiment parent protein is denominator/context evidence, not independent validation.',
          'Literature comparison and independent validation were not performed by this reader stage.']


def _replace_ids(value, replacements):
    if isinstance(value, dict): return {k: _replace_ids(v, replacements) for k, v in value.items()}
    if isinstance(value, list): return [_replace_ids(v, replacements) for v in value]
    return replacements.get(value, value) if isinstance(value, str) else value


def _bind(card, state, source):
    old = card['card_id']
    cid = stable_id('reader_card', [VERSION, state['consumer_state_id'], card['category'], card.get('condition')])
    card = _replace_ids(card, {old: cid})
    selected_rows = [source[p['condition']] for p in card['trajectory']] if card.get('trajectory') else [source[card['condition']]]
    first = selected_rows[0]
    card.update(selection_unit_id=state['consumer_state_id'],
                selection_scope=encode([first['arm_id'], first['reference_id'], first['pairing']]),
                form_id=first['form_id'], measurement_group_ids=first['measurement_group_ids'],
                taxon_ids=first['taxa'], consumer_state_id=state['consumer_state_id'],
                replication_declaration=state['replication_declaration'], units='log2 fold change',
                interpretation_limits=LIMITS, literature_comparison_status='not_performed',
                independent_validation_status='not_performed', unadjusted_source='U_joint',
                source_bindings=[{k: r.get(k) for k in [
                    'adapter_row_id','form_id','contrast_id','arm_id','target_condition_id','reference_condition_id',
                    'target_label','reference_label','time_min','reference_time_min','pairing',
                    'U_joint','P_joint','A','U_all','P_all','included','exclusion_reasons',
                    'reference_joint_run_ids','target_joint_run_ids','reference_joint_n','target_joint_n',
                    'statistical_unit','inference_status','estimator_version','mapping_ids','membership_ids',
                    'mapping_status','localization_ids','localization_status','source_refs']} for r in selected_rows])
    # A generic caution is not opposing experimental evidence.
    card['interpretation_limits'] = LIMITS + [card.pop('counterevidence', '')]
    card['opposing_evidence_status'] = 'inspect_all_timepoints_and_parent_comparisons; no_independent_counterexperiment'
    if card['category'] == 'quantitation_comparison':
        card['reader_summary'] = card['reader_summary'].replace('independently calculated unadjusted PTM contrast', 'unadjusted PTM contrast on the joint mask (U_joint)')
        # Comparison builder's legacy identity omits taxonomy; copy the recorded
        # identity, never infer a taxon or synthesize a precursor.
        card['feature_identity'].update({k: first['identity'][k] for k in first['identity'] if k not in {'reader_feature_id','reader_display_identity'}})
    return card


def _questions(snapshot, metadata):
    original = (snapshot or {}).get('original', {})
    context = original.get('analysis_context') or metadata['recorded_context']
    report = original.get('report_options') or {}
    raw = {'biological_question': context.get('biological_question'),
           'research_questions': report.get('research_questions'),
           'research_questions_status': ('persisted' if 'research_questions' in report
                                         else 'not_persisted_in_source_order')}
    questions = []
    if raw['biological_question'] is not None:
        questions.append({'text': raw['biological_question'], 'question_id': 'BQ-001',
                          'origin': 'analysis_context.biological_question'})
    for i, value in enumerate(raw['research_questions'] or [], 1):
        record = dict(value) if isinstance(value, dict) else {'text': value}
        record.update(question_id=f'RQ-{i:03}', origin='report_options.research_questions')
        questions.append(record)
    return raw, questions


def build_reader_tables(tables, design, snapshot=None):
    """Consume Round06 projections. Every source row receives one disposition."""
    projected = tables['reader_adapter/form_contrasts']
    raw_by_id = {}
    for r in projected.itertuples():
        raw_by_id[r.adapter_row_id] = {**json.loads(r.row_json), 'adapter_row_id': r.adapter_row_id}
    metadata = json.loads(tables['reader_adapter/study_metadata'].iloc[0].metadata_json)
    observations, comparisons, state_cards = [], [], {}
    for state in consumer_states(tables):
        source = {raw_by_id[rid]['condition']: raw_by_id[rid] for rid in state['source_adapter_row_ids']}
        observed = [_bind(c, state, source) for c in build_feature_observation_cards(state, minimum_points=1)]
        compared = [_bind(c, state, source) for c in build_quantitation_comparison_cards(state, maximum=len(source))]
        observations.extend(observed); comparisons.extend(compared)
        state_cards[state['consumer_state_id']] = [c['card_id'] for c in observed]
    # Freeze findings before question routing. No study expectation can affect
    # numeric scores, membership, or even this descriptive selection.
    selected, audit = select_finding_cards(observations, maximum=15)
    by_card = {c['card_id']: c for c in observations}
    selected = [by_card[c['card_id']] for c in selected]
    all_cards = observations + comparisons
    selected_ids = {c['card_id'] for c in selected}
    selected_states = {c['consumer_state_id'] for c in selected}
    finding_ids = {c['card_id']: stable_id('finding', [VERSION, c['card_id']]) for c in selected}
    raw_questions, questions = _questions(snapshot, metadata)
    question_map = build_question_map(questions, observations)
    for q in question_map['questions']:
        matches = set(q['evidence_ids'])
        q.update(finding_ids=[finding_ids[c['card_id']] for c in selected if c['card_id'] in matches],
                 matching_card_ids=sorted(matches), literature_comparison_status='not_performed',
                 answer_scope='Recorded U_joint/P_joint/A and sampled temporal/parent context only.' if matches else 'No matching reader-card evidence; inspect the complete tables and coverage exclusions.',
                 missing_evidence=['Mechanistic or kinase-specific attribution is not established by these observation cards.',
                                   'No literature comparison or independent perturbation validation in this stage.'])
    for card in all_cards:
        card['question_ids'] = [q['question_id'] for q in question_map['questions'] if card['card_id'] in q['evidence_ids']]
        if card['category'] == 'quantitation_comparison':
            card['question_ids'] = sorted({q for c in selected if c['consumer_state_id'] == card['consumer_state_id'] for q in c['question_ids']})
    # The full grid, including missing points, remains in every observation card.
    # Source-row IDs, not copies of the same card, express opposite signed levels.
    for card in observations:
        positive = [b['adapter_row_id'] for b in card['source_bindings'] if b['A'] is not None and b['A'] > 0]
        negative = [b['adapter_row_id'] for b in card['source_bindings'] if b['A'] is not None and b['A'] < 0]
        card['opposite_signed_observations'] = {'positive_A_rows': positive, 'negative_A_rows': negative,
            'status': 'both_signs_observed' if positive and negative else 'no_opposite_signed_A_observed',
            'meaning': 'Signed measured levels across this series, not independent validation or a significance test.'}
        card['parent_comparison_card_ids'] = [c['card_id'] for c in comparisons if c['consumer_state_id'] == card['consumer_state_id']]
    excluded = {r.get('selection_unit_id', r.get('reader_feature_id')): r['reason'] for r in audit['exclusions']}
    coverage = []
    for r in projected.itertuples():
        raw = raw_by_id[r.adapter_row_id]; cards = state_cards.get(r.consumer_state_id, [])
        reasons = [x for x in str(r.restriction_reasons or '').split(';') if x and x != 'nan']
        if r.consumer_state_status == 'raw_only_excluded_finite_contrast': reasons.append(r.consumer_state_status)
        if cards:
            status = 'card_numeric_observation' if any(raw[k] is not None for k in ['U_joint','A']) else 'card_missing_timepoint'
            disposition = 'selected' if r.consumer_state_id in selected_states else 'not_selected'
            reason = 'additional_parent_pattern_or_question' if disposition == 'selected' else excluded.get(r.consumer_state_id, 'summary_capacity')
        else:
            status = 'withheld'; disposition = 'raw_only'; reason = ';'.join(sorted(set(reasons))) or 'no_eligible_consumer_card'
        coverage.append({'adapter_row_id': r.adapter_row_id, 'form_id': r.form_id, 'contrast_id': r.contrast_id,
            'consumer_state_id': r.consumer_state_id, 'input_eligible': bool(r.card_input_eligible),
            'card_status': status, 'summary_disposition': disposition, 'reason': reason,
            'restriction_reasons': ';'.join(sorted(set(reasons))), 'card_ids_json': encode(cards),
            'source_table': 'quant/comparisons.csv', 'source_adapter_table': 'reader_adapter/form_contrasts.csv',
            'schema_version': VERSION})
    coverage = pd.DataFrame(coverage, columns=['adapter_row_id','form_id','contrast_id','consumer_state_id','input_eligible',
        'card_status','summary_disposition','reason','restriction_reasons','card_ids_json','source_table','source_adapter_table','schema_version'])
    card_rows = coverage.card_status.ne('withheld'); selected_rows = coverage.summary_disposition.eq('selected')
    summary = {'schema_version': VERSION, 'total_forms': len(tables['reader_adapter/form_identity']),
        'total_form_contrasts': len(projected), 'adapter_eligible_rows': int(projected.card_input_eligible.sum()),
        'adapter_eligible_forms': int(projected.loc[projected.card_input_eligible, 'form_id'].nunique()),
        'card_forms': int(coverage.loc[card_rows, 'form_id'].nunique()), 'card_grid_rows': int(card_rows.sum()),
        'card_numeric_rows': int(coverage.card_status.eq('card_numeric_observation').sum()),
        'card_missing_timepoints': int(coverage.card_status.eq('card_missing_timepoint').sum()),
        'withheld_rows': int((~card_rows).sum()), 'forms_with_withheld_rows': int(coverage.loc[~card_rows, 'form_id'].nunique()),
        'fully_withheld_forms': len(set(coverage.form_id) - set(coverage.loc[card_rows, 'form_id'])),
        'withheld_reason_counts': dict(Counter(x for r in coverage.loc[~card_rows].itertuples() for x in r.reason.split(';'))),
        'observation_cards': len(observations), 'comparison_cards': len(comparisons), 'selected_findings': len(selected),
        'selected_forms': len({c['form_id'] for c in selected}), 'selected_grid_rows': int(selected_rows.sum()),
        'unselected_source_rows_retained': int((~selected_rows).sum()),
        'all_source_rows_retained': True, 'card_possible_denominator': 'existing_precursor_card_contract; per form/arm/reference/pairing',
        'reason_counts_can_overlap': True, 'selection_before_question_routing': True,
        'literature_comparison': 'not_performed', 'independent_validation': 'not_performed'}
    estimator = {'schema_version': 'astra_reader_estimator.v1', 'source': 'quant/comparisons.csv',
        'axis_fields': {'unadjusted':'U_joint', 'protein':'P_joint', 'adjusted':'A'}, 'units':'log2 fold change',
        'authoring_instruction': 'At form level A = U_joint - P_joint on identical recorded joint masks and linear weights. U_all/P_all have separate masks. No new normalization, imputation or quantification in this reader. A is relative parent-adjusted PTM change, not occupancy or kinase activity.'}
    packet = build_authoring_packet(state={'sample_manifest': metadata['sample_manifest'],
        'source_observation_inventory': summary}, observations=selected, question_map=question_map,
        has_traceable_literature=False, reader_cards=selected + [c for c in comparisons if c['consumer_state_id'] in selected_states],
        metadata_contract=metadata['contract'], observation_selection_audit=audit, candidate_transfer_audit={},
        estimator_contract=estimator, figure_cards=[], section_claim_budget={'results':['O1','O2']}, story_contract={})
    packet.update(astra_reader_version=VERSION, coverage_inventory=summary, original_questions=raw_questions,
        study_metadata_provenance=metadata, canonical_study_design=design,
        feature_identity_audit={'source':'reader_adapter/form_identity.csv', 'card_source':'reader/cards.csv',
                                'all_rows_accounted': True},
        literature_comparison_status='not_performed', interpretation_limits=LIMITS,
        full_evidence={'forms':'quant/summary.csv','comparisons':'quant/comparisons.csv',
            'emergence':'evidence/emergence_evidence.csv','proteins':'quant/protein_contrasts.csv',
            'kinase_inference':'science/inference_results.csv','card_exclusions':'reader/coverage.csv'},
        inference_status_counts=(clean(tables['science/inference_results'].inference_status.value_counts().to_dict())
                                 if 'science/inference_results' in tables else {}))
    for bundle in packet['module_evidence_index']['bundles']:
        bundle['study_frame_ref'] = 'study/STUDY_BRIEF.md'
    packet['authoring_rules']['required_evidence_anchor'] = 'Use exact supplied card_id evidence markers; do not invent IDs. Source row keys are preserved in each source_binding.'
    findings = [{'finding_id': finding_ids[c['card_id']], 'card_id': c['card_id'], 'form_id': c['form_id'],
        'consumer_state_id': c['consumer_state_id'], 'question_ids_json': encode(c['question_ids']),
        'source_row_ids_json': encode([b['adapter_row_id'] for b in c['source_bindings']]),
        'selection_reason': 'additional_parent_pattern_or_question', 'schema_version': VERSION} for c in selected]
    for c in packet['reader_cards']:
        c['finding_id'] = finding_ids.get(c['card_id'])
    return {'reader/cards': pd.DataFrame([{'card_id':c['card_id'],'form_id':c['form_id'],
        'consumer_state_id':c['consumer_state_id'], 'category':c['category'], 'selected':c['card_id'] in selected_ids,
        'card_json':encode(c), 'schema_version':VERSION} for c in all_cards],
        columns=['card_id','form_id','consumer_state_id','category','selected','card_json','schema_version']),
        'reader/findings': pd.DataFrame(findings, columns=['finding_id','card_id','form_id','consumer_state_id','question_ids_json','source_row_ids_json','selection_reason','schema_version']),
        'reader/coverage': coverage,
        'reader/packet': pd.DataFrame([{'packet_id':'reader','packet_json':encode(packet),'schema_version':VERSION}])}


def validate_reader(tables):
    """Verify bound values, times, masks and identities against canonical rows."""
    if not set(TABLE_KEYS) <= set(tables): raise ValueError('Incomplete reader tables')
    source = {(r['form_id'],r['contrast_id']):clean(r) for r in tables['quant/comparisons'].to_dict('records')}
    projected = {r.adapter_row_id:json.loads(r.row_json) for r in tables['reader_adapter/form_contrasts'].itertuples()}
    coverage = tables['reader/coverage']
    if len(coverage) != len(projected) or set(coverage.adapter_row_id) != set(projected): raise ValueError('Reader coverage population mismatch')
    cards = {}
    for r in tables['reader/cards'].itertuples():
        c = json.loads(r.card_json); cards[r.card_id] = c
        if r.card_id != c['card_id']: raise ValueError('Reader card ID mismatch')
        for b in c['source_bindings']:
            raw = projected[b['adapter_row_id']]; original = source[b['form_id'],b['contrast_id']]
            for key in original:
                if key in b and not equivalent(b[key], original[key]): raise ValueError('Reader source numeric/identity/mask mismatch: '+key)
            for key in ['mapping_ids','membership_ids','localization_ids','localization_status','source_refs']:
                if b[key] != raw[key]: raise ValueError('Reader provenance mismatch: '+key)
            point = next((p for p in c.get('trajectory',[]) if p['condition']==raw['condition']), c)
            for dest, key in AXES:
                if not equivalent(point[dest], raw[key]): raise ValueError('Reader axis mismatch: '+key)
            if c.get('trajectory'):
                if not equivalent(point['time_minutes'],raw['time_min']) or point['reference_id'] != raw['reference_id']: raise ValueError('Reader time/reference mismatch')
                for axis in ['unadjusted','protein','adjusted']:
                    field = {'unadjusted':'U_joint','protein':'P_joint','adjusted':'A'}[axis]
                    if not equivalent(point['axes'][axis]['value'],raw[field]): raise ValueError('Reader axis record mismatch')
                    for side,name in [('control','reference'),('treatment','target')]:
                        if set(point['axes'][axis][side+'_sample_ids'] or []) != set(raw['ptm_unadjusted_'+side+'_sample_ids']): raise ValueError('Reader joint mask mismatch')
            if c['form_id'] != raw['form_id'] or c['taxon_ids'] != raw['taxa']: raise ValueError('Reader measurement identity mismatch')
    findings = tables['reader/findings']
    if len(findings) > 15 or findings.card_id.duplicated().any(): raise ValueError('Reader findings duplicated or over capacity')
    packet = json.loads(tables['reader/packet'].iloc[0].packet_json)
    qids = {q['question_id'] for q in packet['research_question_evidence_map']['questions']}
    for r in findings.itertuples():
        if r.card_id not in cards or not set(json.loads(r.question_ids_json)) <= qids: raise ValueError('Reader finding foreign key mismatch')
        if not set(json.loads(r.source_row_ids_json)) <= set(projected): raise ValueError('Reader row foreign key mismatch')
    for q in packet['research_question_evidence_map']['questions']:
        if not set(q['evidence_ids']) <= set(cards) or not set(q['finding_ids']) <= set(findings.finding_id): raise ValueError('Reader question foreign key mismatch')
    for c in packet['reader_cards']:
        if c != cards.get(c['card_id']): raise ValueError('Reader packet/card mismatch')
    return {'source_rows_checked':len(projected),'cards_checked':len(cards),'findings_checked':len(findings),'values_times_NA_masks_ids':'passed'}


def write_reader(directory, tables):
    """Deterministic JSON/Markdown views of the canonical reader tables."""
    from .generic_workflow import json_write
    directory = Path(directory)
    packet = json.loads(tables['reader/packet'].iloc[0].packet_json)
    for name,value in [('authoring_packet',packet),('coverage_summary',packet['coverage_inventory']),
            ('question_map',packet['research_question_evidence_map']),('selection_audit',packet['observation_selection_audit'])]:
        json_write(directory/'reader'/f'{name}.json',value)
    coverage = packet['coverage_inventory']
    lines = ['# 주요 관측과 근거 — Astra reader',
        '[실험 원문과 설계](../study/STUDY_BRIEF.md) · [원문 snapshot](../study/user_input_snapshot.json) · '
        '[전체 카드](cards.csv) · [전체 행의 보류/선정 사유](coverage.csv) · [구조화 packet](authoring_packet.json)',
        f"전체 {coverage['total_forms']} forms / {coverage['total_form_contrasts']} form×contrast. "
        f"카드 {coverage['card_forms']} forms / 수치 관측 {coverage['card_numeric_rows']}행 / 결측 시점 {coverage['card_missing_timepoints']}행. "
        f"보류 {coverage['withheld_rows']}행. 주요 결과 {coverage['selected_findings']}개; 미선정 원본 {coverage['unselected_source_rows_retained']}행은 보존됩니다.",
        '이는 관측 요약입니다. 확정 kinase call이나 독립 검증이 아닙니다. NA는 결측이며 0이 아닙니다. '
        'U는 U_joint, P는 P_joint, A는 동일 joint mask의 단백질 보정 PTM 변화이며 단위는 log2 fold change입니다. '
        'U_all/P_all과 같은 값으로 간주하지 마세요. 시료 반복 유형: '+str(packet['study_metadata_provenance']['replication_declaration']),
        '기술 반복은 biological n이 아닙니다. FASTA 좌표는 MS localization 확률이 아닙니다. '
        'Parent protein은 같은 실험의 근거이며 독립 검증이 아닙니다. 문헌 비교: '+packet['literature_comparison_status']+'.',
        '전체 [emergence](../evidence/emergence_evidence.csv), [protein](../quant/protein_contrasts.csv), '
        '[kinase 판정](../science/inference_results.csv)은 별도 원본 표를 확인하세요. '
        '카드에서 보류된 복수 precursor·종 모호성·parent 결측 항목이 이 자료에서 사라진 것은 아닙니다.',
        '선정: 기존 select_finding_cards의 quality/parent/pattern diversity 및 stable ID 기준, 최대 15개. '
        '질문 연결은 선정 이후 수행하며 경로 기대를 점수에 사용하지 않습니다.', '## 저장된 연구 질문']
    for q in packet['research_question_evidence_map']['questions']:
        lines.extend([f"### {q['question_id']}", q['original_text'], f"상태: {q['answer_status']}; {q['answer_scope']}",
                      '연결 결과: '+(', '.join(q['finding_ids']) or '없음'), '부족한 근거: '+' '.join(q['missing_evidence'])])
    if not packet['original_questions']['research_questions']:
        lines.append('추가 research_questions: '+packet['original_questions']['research_questions_status']+' (원문 값은 packet에 그대로 보존).')
    comparisons = {c['card_id']: c for c in packet['reader_cards'] if c['category']=='quantitation_comparison'}
    for c in packet['reader_cards']:
        if c['category'] != 'measured_feature_observation': continue
        lines.extend([f"## {c['feature_label']} — {c['finding_id']}",
            f"form: `{c['form_id']}`; taxon: {c['taxon_ids']}; [원본 정량](../quant/comparisons.csv); "
            f"card: `{c['card_id']}`; 질문: {', '.join(c['question_ids']) or '직접 연결 없음'}.",
            '관측 시간 패턴: '+c['axis_patterns']['adjusted']['label']+' (sampled observations; no biological significance).',
            '| 시점 (min) | 비교 | U_joint | P_joint | A | joint n (ref/target) | 원본 contrast ID |',
            '| --- | --- | --- | --- | --- | --- | --- |'])
        for b in c['source_bindings']:
            fmt=lambda value: 'NA' if value is None else str(value)
            lines.append('| '+' | '.join([fmt(b['time_min']),str(b['target_label'])+' vs '+str(b['reference_label']),
                fmt(b['U_joint']),fmt(b['P_joint']),fmt(b['A']),f"{b['reference_joint_n']}/{b['target_joint_n']}",b['contrast_id']])+' |')
        effects = sorted({comparisons[cid]['comparison_class'] for cid in c['parent_comparison_card_ids'] if cid in comparisons})
        opposite = c['opposite_signed_observations']
        lines.extend(['Parent 영향 (기존 기술적 분류, 유의성 검정 아님): '+', '.join(effects),
            '반대 방향 관측: '+opposite['status']+'. 실제 양/음의 A 행은 packet의 opposite_signed_observations에서 추적합니다.',
            '제한: '+ ' '.join(c['interpretation_limits']),
            '전체 joint masks·U_all/P_all·실제 precursor membership·좌표 및 localization ID는 [카드](cards.csv)의 source_bindings와 [adapter 원본](../reader_adapter/form_contrasts.csv)에 보존됩니다.'])
    if packet.get('literature'):
        lines.insert(2, '[선정 관측별 문헌 검색·비교·접근 제한](LITERATURE.md) · [문헌 단계 요약](literature_summary.json)')
    rendered = ''.join(('\n' if i and line.startswith('|') and lines[i-1].startswith('|') else '\n\n') + line
                       for i,line in enumerate(lines)).lstrip()+'\n'
    (directory/'reader/READ_ME.md').write_text(rendered,encoding='utf-8')
    if packet.get("literature"):
        from .astra_literature import write
        return ARTIFACTS + write(directory,tables)
    return ARTIFACTS
