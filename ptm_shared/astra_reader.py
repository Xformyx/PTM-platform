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
from .astra_reader_temporal import (attach_temporal, validate_temporal, write_temporal, _parts,
                                    SOURCE_TABLES as TEMPORAL_SOURCE_TABLES)
from .astra_evidence_catalog import attach_access, write_evidence_access

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


def finding_id_for_card(card_id):
    return stable_id('finding', [VERSION, card_id])


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
    finding_ids = {c['card_id']: finding_id_for_card(c['card_id']) for c in selected}
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
            card['question_ids'] = sorted({q for c in observations if c['consumer_state_id'] == card['consumer_state_id'] for q in c['question_ids']})
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
    result = {'reader/cards': pd.DataFrame([{'card_id':c['card_id'],'form_id':c['form_id'],
        'consumer_state_id':c['consumer_state_id'], 'category':c['category'], 'selected':c['card_id'] in selected_ids,
        'card_json':encode(c), 'schema_version':VERSION} for c in all_cards],
        columns=['card_id','form_id','consumer_state_id','category','selected','card_json','schema_version']),
        'reader/findings': pd.DataFrame(findings, columns=['finding_id','card_id','form_id','consumer_state_id','question_ids_json','source_row_ids_json','selection_reason','schema_version']),
        'reader/coverage': coverage,
        'reader/packet': pd.DataFrame([{'packet_id':'reader','packet_json':encode(packet),'schema_version':VERSION}])}
    combined = {**tables, **result}
    attach_temporal(combined)
    attach_reading_guidance(combined)
    attach_access(combined)
    from .astra_reader_full import attach_full
    attach_full(combined)
    from .astra_literature_review import attach_review_plan
    attach_review_plan(combined)
    result['reader/cards'] = combined['reader/cards']
    result['reader/packet'] = combined['reader/packet']
    return result


def attach_reading_guidance(tables):
    """선정 관측과 문헌 단계, PhosX 실행 여부를 서로 다른 안내로 남긴다.

    구현 대상: docs/astra_evidence_integration/MIGRATION_AND_OPERATIONS_KO.md «문헌 검토 단계»
    사전등록: 2026-10-13. 선정 규칙과 문헌 승인 조건은 바꾸지 않는다.
    해석 한계: 안내는 읽기 범위다. 선정 finding 수나 z-score 행 수가 PhosX 실행이나 cascade 구성이 아니다.
    주장 금지: 15개 관측이나 repository_measured_gene_zscore로 kinase 귀속 정확도를 논하지 않는다.
    """
    packet=json.loads(tables['reader/packet'].iloc[0].packet_json)
    executions=tables.get('kinase/method_executions',pd.DataFrame())
    method_path='reader/PHOSX_TIME_COURSE.md' if len(executions) else 'kinase/method_executions.csv'
    packet['authoring_rules']['reading_order']=[
        {'step':1,'purpose':'Original questions, design and actual stage readiness',
         'paths':['study/STUDY_BRIEF.md','reader/READ_ME.md#저장된-연구-질문','evidence/readiness.json']},
        {'step':2,'purpose':'Selected observations are not the full signaling network. Do not build a cascade from the selected findings or from an expected insulin pathway. Choose card_id values from findings.csv and question_map.json; do not read all of cards.csv or authoring_packet.json. Precursor membership_ids are not kinase-candidate contributions; count those from substrate_contributions form_id tokens. Continue to the full emergence, protein, and kinase tables.',
         'paths':['reader/READ_ME.md','reader/findings.csv','reader/question_map.json','reader/coverage_summary.json','evidence/emergence_evidence.csv','quant/protein_contrasts.csv','kinase/substrate_contributions.csv','science/inference_results.csv']},
        {'step':3,'purpose':'Saved temporal, native method and literature evidence with limits',
         'paths':['reader/TEMPORAL_EVIDENCE.md',method_path,'reader/LITERATURE.md']},
        {'step':4,'purpose':'Trace a claim to exact source row keys; large source pin only as needed',
         'paths':['reader/cards.csv','quant/comparisons.csv','references/source_query_ledger.csv','references/source_pin.json']}]
    packet['authoring_rules']['readiness_semantics']=[
        'research_full is an acquisition policy, not evidence of completed collection; inspect source_execution.',
        'Calculation completion, partial references, literature retrieval/comparison and missing localization are separate states.',
        'PSSM percentile is not correctness probability; native method p/q is not biological replicate significance.',
        'Keep literature proposals distinct from semantically reviewed claims; preserve no-call and uncertainty.',
        'Search completion, model comparison, citation verification, biological review, and external delivery are separate literature stages. packet mode citation_complete only means reference cards exist.',
        'repository_measured_gene_zscore rows are not PhosX. PhosX results require method_id PhosX_native_functions and rows in kinase/method_executions.csv.',
        'PhosX execution and method_scores row counts are not significant kinase-activity detection. insufficient_coverage is not inactivity, and a no-call is not evidence that v6 was not applied.',
        'Precursor membership_ids on source bindings are not kinase-candidate contributions.']
    if packet.get('whole_evidence'):
        from .astra_reader_full import reading_order
        packet['authoring_rules']['reading_order']=reading_order()
    tables['reader/packet'].loc[tables['reader/packet'].index[0],'packet_json']=json.dumps(packet,ensure_ascii=False,sort_keys=True)


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
    validate_temporal(tables)
    return {'source_rows_checked':len(projected),'cards_checked':len(cards),'findings_checked':len(findings),'values_times_NA_masks_ids':'passed'}


def phosx_time_views(tables):
    """Projection of saved evidence, not a temporal inference or a new ranking.

    Comparison metadata already comes from ContrastEstimator.metadata(). Keep
    arm/reference/pairing scopes distinct and order by canonical numeric time.
    """
    from .contrast_quantification import KEY_COLUMNS
    executions = tables.get('kinase/method_executions', pd.DataFrame())
    if executions.empty: return None
    executions = executions.loc[executions.method_id.eq('PhosX_native_functions')]
    if executions.empty: return None
    comp = tables['quant/comparisons']
    metadata = comp[KEY_COLUMNS].drop_duplicates()
    if metadata.contrast_id.duplicated().any() or executions.contrast_id.duplicated().any():
        raise ValueError('Conflicting PhosX contrast metadata or execution records')
    meta = metadata.merge(executions, on='contrast_id', validate='one_to_one')
    if len(meta) != len(executions): raise ValueError('PhosX execution without canonical contrast')
    meta = meta.sort_values(['arm_id','reference_condition_id','pairing','time_min','contrast_id'], na_position='last')
    ids = tables['science/site_identity_audit']
    scores = tables['science/specificity_scores']
    membership = tables['kinase/method_membership']
    methods = tables['kinase/method_scores'].loc[lambda f: f.method_id.eq('PhosX_native_functions')]
    edges = tables['kinase/kinase_candidate_edges']
    labels = edges.loc[edges.edge_type.eq('experimental_specificity_prediction'),
                       ['candidate_id','candidate_accession']].drop_duplicates()
    if labels.candidate_id.duplicated().any(): raise ValueError('Conflicting PhosX assay label')
    summary = []
    for row in meta.to_dict('records'):
        cid = row['contrast_id']
        joint = comp.loc[comp.contrast_id.eq(cid) & comp.included & comp.A.notna()]
        attributable = ids.loc[ids.site_attribution_eligible & ids.form_id.isin(joint.form_id)]
        keys = attributable[['form_id','site_id']].drop_duplicates()
        scoped = scores.merge(keys, on=['form_id','site_id'], validate='many_to_one')
        scored = scoped.loc[scoped.status.eq('scored')]
        native = membership.loc[membership.contrast_id.eq(cid)]
        results = methods.loc[methods.contrast_id.eq(cid)]
        selected = native.loc[native.selected]
        summary.append({**row, 'included_joint_A_forms':joint.form_id.nunique(),
            'site_attributable_forms':attributable.form_id.nunique(),
            'site_attributable_sites':attributable.site_id.nunique(),
            'site_attributable_form_sites':len(keys),
            'scored_forms':scored.form_id.nunique(), 'scored_sites':scored.site_id.nunique(),
            'scored_form_sites':len(scored[['form_id','site_id']].drop_duplicates()),
            'scored_measurement_groups':scored.measurement_group_id.nunique(),
            'score_rows':len(scored), 'not_evaluable_score_rows':int(scoped.status.eq('not_evaluable').sum()),
            'selected_specificity_rows':int(scored.membership_selected.sum()),
            'native_ranked_measurement_groups':native.measurement_group_id.nunique(),
            'native_selected_memberships':len(selected),
            'native_selected_measurement_groups':selected.measurement_group_id.nunique(),
            'evaluable_assays':int(results.status.eq('computed_method_enrichment').sum()),
            'insufficient_coverage_assays':int(results.status.eq('insufficient_coverage').sum()),
            'assay_results':len(results),
            'comparison_source':'quant/comparisons.csv', 'identity_source':'science/site_identity_audit.csv',
            'score_source':'science/specificity_scores.csv', 'membership_source':'kinase/method_membership.csv',
            'execution_source':'kinase/method_executions.csv'})
    timeline = pd.DataFrame(summary)
    # Preserve every assay result including official zero placeholders, typed
    # unavailable scores/p/q, membership IDs and per-contrast testing family.
    assays = methods.merge(labels, on='candidate_id', how='left', validate='many_to_one')
    assays = assays.merge(meta[KEY_COLUMNS], on='contrast_id', validate='many_to_one')
    if len(assays) != len(methods): raise ValueError('PhosX result without contrast metadata')
    assays = assays.sort_values(['candidate_accession','candidate_id','arm_id','reference_condition_id',
                                'pairing','time_min','contrast_id'], na_position='last').reset_index(drop=True)
    assays['result_source'] = 'kinase/method_scores.csv'
    assays['membership_source'] = 'kinase/method_membership.csv'
    return timeline, assays


def write_phosx_time_views(directory, tables):
    views = phosx_time_views(tables)
    if views is None: return []
    timeline, assays = views
    directory = Path(directory)/'reader'
    timeline.to_csv(directory/'phosx_time_summary.csv', index=False)
    assays.to_csv(directory/'phosx_assay_time_results.csv', index=False)
    fmt = lambda v: 'NA' if pd.isna(v) else str(v)
    lines = ['# PhosX — 시간별 방법 결과',
        '[시간별 분모·실행 ID](phosx_time_summary.csv) · [모든 assay×시점 결과·membership IDs](phosx_assay_time_results.csv) · '
        '[원본 결과](../kinase/method_scores.csv) · [원본 membership](../kinase/method_membership.csv) · '
        '[실행 설정](../kinase/method_executions.csv) · [자원](../science/resource_registry.json)',
        '아래 표는 저장된 결과의 투영입니다. 실행 기록은 부모 패키지에서 재사용될 수 있습니다. 이번 생성의 재계산/재사용은 [runtime](../methods/native_execution_runtime.json)과 [provenance](../provenance.json)의 stage_reuse를 확인하세요. Native Activity Score는 log2 단위의 descriptive specificity_A와 다릅니다. '
        '시점마다 입력 universe와 기질 구성이 달라질 수 있어 최대 score 시점을 kinase 활성 peak로 확정할 수 없습니다. '
        'Method p/q는 해당 contrast의 공식 rank permutation 및 다중 검정 결과이며 biological p/q나 전체 시간축의 통합 FDR가 아닙니다.',
        'Assay label은 검증된 enzyme accession/rat orthology를 대신하지 않습니다. Human assay와 substrate taxon은 구분됩니다. '
        '자원의 지원 범위 밖 residue는 비활성이 아닙니다. 미측정 localization, 기술 반복, calibration 및 no-call 제한은 유지됩니다. '
        + stored_method_limit_sentence(tables['kinase/method_scores']) + ' '
        'NA는 미평가/결측입니다. 공식 native_score가 coverage 부족에서 0을 반환한 경우 CSV 원문은 보존하되 아래 점수는 NA로 표시합니다. '
        'Control 점수를 추가하거나 시점 사이를 보간하지 않습니다.',
        '## 시점별 입력·실행',
        '| 시간 (min) | 조건 / reference | joint A forms | 귀속 적격 form/site | 점수화 form/site | ranked groups | selected memberships | 평가 가능 / coverage 부족 | 상태 |',
        '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for r in timeline.itertuples():
        lines.append(f'| {fmt(r.time_min)} | {r.target_label} / {r.reference_label} ({r.arm_id}) | {r.included_joint_A_forms} | '
                     f'{r.site_attributable_forms}/{r.site_attributable_sites} | {r.scored_forms}/{r.scored_sites} | '
                     f'{r.native_ranked_measurement_groups} | {r.native_selected_memberships} | '
                     f'{r.evaluable_assays}/{r.insufficient_coverage_assays} | {r.status}; {fmt(r.reason)} |')
    for (label,candidate), block in assays.groupby(['candidate_accession','candidate_id'],sort=False,dropna=False):
        lines.extend(['',f'## {label} — `{candidate}`',
            '| 시간 (min) | 조건 / reference | Activity Score | method p | method q | 기여 groups / universe | 상태 | 결과 ID |',
            '| --- | --- | --- | --- | --- | --- | --- | --- |'])
        for r in block.itertuples():
            lines.append(f'| {fmt(r.time_min)} | {r.target_label} / {r.reference_label} ({r.arm_id}) | {fmt(r.score)} | '
                         f'{fmt(r.method_p)} | {fmt(r.method_q)} | {r.eligible_site_count}/{r.universe_count} | '
                         f'{r.status} | `{r.method_result_id}` |')
    rendered = ''.join(('\n' if i and line.startswith('|') and lines[i-1].startswith('|') else '\n\n') + line
                       for i,line in enumerate(lines)).lstrip()+'\n'
    (directory/'PHOSX_TIME_COURSE.md').write_text(rendered,encoding='utf-8')
    return ['reader/PHOSX_TIME_COURSE.md','reader/phosx_time_summary.csv','reader/phosx_assay_time_results.csv']


def _id_tokens(value):
    if isinstance(value, list):
        return [str(item) for item in value if item is not None and str(item) not in {'', 'nan', 'None'}]
    return [part for part in _parts(value) if part not in {'', 'nan', 'None'}]


def selected_kinase_contribution_summary(selected_findings, contributions=None, *, precursor_membership=None, temporal_findings=None):
    """precursor membership과 저장된 후보 기여도를 범위가 해소된 행에서만 따로 센다.

    구현 대상: docs/astra_evidence_integration/MIGRATION_AND_OPERATIONS_KO.md «저장된 결과의 reader 연결»
    사전등록: 2026-10-13. g7에서 membership_ids가 선정 관측 15개 모두에 있어 kinase 연결로 집계된 것을 본 뒤. 탐색적. primary 승격 금지.
    해석 한계: project_temporal이 검증한 후보를 우선한다. 표가 없으면 0개로 바꾸지 않는다. 새 kinase 점수가 아니다.
    주장 금지: 후보 수로 kinase 귀속 정확도, AKT 활성, 또는 AKT 비활성을 논하지 않는다.
    """
    if precursor_membership is None:
        precursor_status, precursor_count = 'absent', None
    elif 'membership_id' not in precursor_membership.columns:
        precursor_status, precursor_count = 'unreadable', None
    else:
        known = {str(item) for item in precursor_membership.membership_id.dropna()}
        precursor_count = sum(1 for card in selected_findings if any(
            token in known for binding in card.get('source_bindings') or [] for token in _id_tokens(binding.get('membership_ids'))))
        precursor_status = 'counted'
    links, candidates, contribution_status = [], set(), 'counted'
    if temporal_findings is not None:
        by_finding = {item.get('finding_id'): item for item in temporal_findings}
        for card in selected_findings:
            item = by_finding.get(card.get('finding_id'))
            if item is None or item.get('status') == 'ambiguous':
                contribution_status = 'not_evaluable'
                break
            matched = sorted({str(candidate.get('candidate_id')) for candidate in item.get('candidates') or [] if candidate.get('candidate_id')})
            if matched:
                candidates.update(matched)
                links.append({'finding_id': card.get('finding_id'), 'feature_label': card.get('feature_label'),
                              'form_id': card.get('form_id'), 'candidate_count': len(matched)})
        if contribution_status != 'counted':
            links, candidates = [], set()
    elif contributions is None:
        contribution_status = 'absent'
    elif not {'form_ids', 'candidate_id', 'contrast_id'} <= set(contributions.columns):
        contribution_status = 'unreadable'
    else:
        for card in selected_findings:
            form = str(card.get('form_id') or '')
            bindings = card.get('source_bindings') or []
            contrasts = {binding.get('contrast_id') for binding in bindings if binding.get('contrast_id')}
            scopes = {(binding.get('arm_id'), binding.get('reference_condition_id'), binding.get('pairing')) for binding in bindings}
            if not form or not contrasts or len(scopes) != 1:
                contribution_status = 'not_evaluable'
                break
            matched = contributions.loc[contributions.form_ids.map(lambda value, form_id=form: form_id in _parts(value))
                                        & contributions.contrast_id.isin(contrasts)]
            arm, reference, pairing = next(iter(scopes))
            for column, expected in (('arm_id', arm), ('reference_condition_id', reference), ('pairing', pairing)):
                if column in matched.columns:
                    matched = matched.loc[matched[column].astype(str).eq(str(expected))]
            matched_candidates = sorted({str(candidate) for candidate in matched.candidate_id.dropna() if str(candidate) not in {'', 'nan'}})
            if matched_candidates:
                candidates.update(matched_candidates)
                links.append({'finding_id': card.get('finding_id'), 'feature_label': card.get('feature_label'),
                              'form_id': form, 'candidate_count': len(matched_candidates)})
        if contribution_status != 'counted':
            links, candidates = [], set()
    return {'selected_findings': len(selected_findings), 'precursor_status': precursor_status,
            'precursor_linked_findings': precursor_count, 'contribution_status': contribution_status,
            'contribution_linked_findings': len(links) if contribution_status == 'counted' else None,
            'candidate_count': len(candidates) if contribution_status == 'counted' else None, 'links': links}


def kinase_link_sentence(summary):
    """저장된 집계를 문장으로 옮긴다. 세 연결을 하나의 수로 합치지 않는다."""
    if summary['precursor_status'] == 'counted':
        precursor = f"precursor membership이 있는 선정 관측은 {summary['precursor_linked_findings']}개입니다. 이 ID는 kinase 후보가 아닙니다."
    elif summary['precursor_status'] == 'unreadable':
        precursor = 'precursor_membership 표에서 membership_id를 읽지 못해 precursor 연결 수는 확인하지 않았습니다.'
    else:
        precursor = 'precursor_membership 표가 없어 precursor 연결 수는 확인하지 않았습니다.'
    if summary['contribution_status'] == 'counted':
        detail = ''
        if summary['links']:
            detail = ' 연결: ' + '; '.join(f"{item['feature_label']} 후보 {item['candidate_count']}개" for item in summary['links']) + '.'
        contribution = (f"저장된 후보 기여도가 연결된 선정 관측은 {summary['contribution_linked_findings']}개이고, "
                        f"서로 다른 candidate_id는 {summary['candidate_count']}개입니다. 후보 수는 활성 확정이 아닙니다.{detail}")
    elif summary['contribution_status'] == 'unreadable':
        contribution = 'substrate contribution 표에서 form_ids와 contrast_id를 읽지 못해 후보 연결 수는 확인하지 않았습니다.'
    elif summary['contribution_status'] == 'not_evaluable':
        contribution = '후보 기여도는 카드의 contrast 범위가 하나로 해소되지 않아 확인하지 않았습니다.'
    else:
        contribution = '저장된 후보 기여도 표가 없어 후보 연결 수는 확인하지 않았습니다.'
    return (f"선정 관측 {summary['selected_findings']}개. {precursor} {contribution} "
            'precursor membership, substrate contribution, PhosX native membership은 하나의 연결 수로 합치지 않습니다.')


def stored_method_limit_sentence(scores=None):
    """저장된 method 상태 개수를 옮긴다. 새 q 임계는 적용하지 않는다.

    구현 대상: docs/astra_evidence_integration/MIGRATION_AND_OPERATIONS_KO.md «저장된 결과의 reader 연결»
    사전등록: 2026-10-13. g7에서 PhosX 실행과 method q 결과를 본 뒤. 탐색적. primary 승격 금지.
    해석 한계: executed와 행 수는 활성 검출이 아니고, insufficient_coverage는 비활성이 아니다.
    주장 금지: 이 문장으로 AKT 활성, AKT 비활성, 또는 v6 미적용을 결론내지 않는다.
    """
    text = ('method_executions의 executed와 method_scores 행 수는 유의한 kinase 활성 검출이 아닙니다. '
            'status가 insufficient_coverage인 행은 그 kinase가 비활성이라는 뜻이 아닙니다. '
            'method q로 특정 kinase의 활성 또는 비활성을 결론내지 않습니다. '
            'no-call은 v6가 적용되지 않았다는 증거가 아닙니다.')
    if scores is None or not len(scores) or 'method_id' not in scores.columns or 'status' not in scores.columns:
        return text
    totals = [f'{method} {int(count)}행' for method, count in scores.groupby('method_id', dropna=False).size().sort_index().items()]
    parts = [f'{method}/{status} {int(count)}행' for (method, status), count in scores.groupby(['method_id', 'status'], dropna=False).size().sort_index().items()]
    return text + f" method_scores 전체 {len(scores)}행: " + ', '.join(totals) + '. 상태: ' + ', '.join(parts) + '.'


def write_reader(directory, tables, *, source_root=None, access_only=False, whole_only=False, review_plan_only=False, review_execution=None):
    """Deterministic JSON/Markdown views of the canonical reader tables."""
    from .generic_workflow import json_write
    directory = Path(directory)
    access_artifacts = write_evidence_access(directory, source_root=source_root)
    packet = json.loads(tables['reader/packet'].iloc[0].packet_json)
    if packet.get('whole_evidence') and not (access_only or review_plan_only):
        from .astra_reader_full import write_full
        access_artifacts += write_full(directory,tables,source_root=source_root)
    if packet.get('literature_review_plan') and not access_only:
        from .astra_literature_review import write_review_plan
        access_artifacts += write_review_plan(directory,tables,source_root=source_root)
    if review_execution is not None:
        from .astra_literature_review import write_review_execution
        access_artifacts += write_review_execution(directory,tables,review_execution,source_root=source_root)
    if review_plan_only:
        json_write(directory/'reader/authoring_packet.json',packet)
        note='\n\n## 전체 문헌 검토 대상 (M3)\n\n[요약과 독립적인 typed 검토 계획](LITERATURE_REVIEW_PLAN.md). 새 검색·비교는 미요청이며 기존 문헌 실행 기록은 보존됩니다.\n'
        if review_execution is not None:
            note='\n\n## 전체 근거의 실제 문헌 실행 (M4)\n\n[명시적 대상의 검색·비교와 미실행 범위](LITERATURE_SUBJECT_REVIEW.md)를 확인하세요. M3는 대상 계획이며 실제 상태는 M4 실행표가 기준입니다. 원래 15개 findings와 문헌 결과는 보존됩니다.\n'
        path=directory/'reader/READ_ME.md';original=path.read_text() if path.exists() else ''
        if note not in original:path.write_text(original+note,encoding='utf-8')
        return access_artifacts+['reader/authoring_packet.json','reader/READ_ME.md']
    if whole_only:
        json_write(directory/'reader/authoring_packet.json',packet)
        json_write(directory/'reader/question_map.json',packet['research_question_evidence_map'])
        note='## 전체 근거 읽기 (M2)\n\n전체 분모 → 질문별 근거·미연결 → 필요한 원본 → 요약 → 시간·방법·기존 문헌. [전체 연결 및 typed 인용](FULL_EVIDENCE.md). 기존 findings는 preview입니다.\n\n'
        path=directory/'reader/READ_ME.md';original=path.read_text() if path.exists() else ''
        if not original.startswith(note):path.write_text(note+original,encoding='utf-8')
        return access_artifacts+['reader/authoring_packet.json','reader/question_map.json','reader/READ_ME.md']
    if access_only:
        # A reader revision must not reinterpret newer archived literature/cards
        # with an older checkout. Keep all existing interpretation bytes intact.
        json_write(directory/'reader/authoring_packet.json', packet)
        note = '\n\n## 전체 근거 접근 (M1)\n\n[전체 인덱스와 조회 절차](EVIDENCE_ACCESS.md). 선정 findings는 요약이며 전체 접근 범위를 제한하지 않습니다. 인덱스 생성은 검토 수행을 뜻하지 않습니다.\n'
        path = directory/'reader/READ_ME.md'
        original = path.read_text() if path.exists() else ''
        if note not in original: path.write_text(original + note, encoding='utf-8')
        return access_artifacts + ['reader/authoring_packet.json', 'reader/READ_ME.md']
    for name,value in [('authoring_packet',packet),('coverage_summary',packet['coverage_inventory']),
            ('question_map',packet['research_question_evidence_map']),('selection_audit',packet['observation_selection_audit'])]:
        json_write(directory/'reader'/f'{name}.json',value)
    coverage = packet['coverage_inventory']
    selected_findings = [c for c in packet['reader_cards'] if c.get('category')=='measured_feature_observation' and c.get('finding_id')]
    temporal = packet.get('temporal_evidence') or {}
    kinase_summary = selected_kinase_contribution_summary(
        selected_findings, tables.get('kinase/substrate_contributions'),
        precursor_membership=tables.get('reader_adapter/precursor_membership'),
        temporal_findings=temporal.get('findings'))
    lines = ['# 주요 관측과 근거 — Astra reader',
        '[전체 문헌 검토 대상 계획](LITERATURE_REVIEW_PLAN.md): 신규 검색/비교와 독립된 계획이며 기존 문헌 상태를 보존합니다.',
        '[전체 근거 catalog와 미선정·보류·no-call 조회](EVIDENCE_ACCESS.md). 선정 findings는 요약입니다. 전체 접근 가능성과 실제 검토 범위는 다릅니다.',
        '[실험 원문과 설계](../study/STUDY_BRIEF.md) · [원문 snapshot](../study/user_input_snapshot.json) · '
        '[전체 카드](cards.csv) · [전체 행의 보류/선정 사유](coverage.csv) · [구조화 packet](authoring_packet.json)',
        'cards.csv는 전체 카드 저장소이며 authoring_packet.json의 reader_cards는 요약 preview입니다. [전체 catalog](EVIDENCE_ACCESS.md)와 [질문 연결](FULL_EVIDENCE.md)에서 필요한 원본·card_id를 조회하세요. 큰 파일 전체를 먼저 읽을 필요는 없습니다.',
        '읽기 순서: **[전체 분모·질문별 연결과 미연결](FULL_EVIDENCE.md) → 필요한 원본 → 요약 → 시간·방법·문헌 근거**. '
        '큰 source pin 전체를 먼저 읽을 필요는 없습니다. research_full은 요청 정책이며 참조 수집 완료를 뜻하지 않습니다.',
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
        '방법 실행은 [method registry](../methods/method_registry.json)와 [실행 범위](../kinase/method_executions.csv), '
        '[specificity 자원](../science/resource_registry.json)을 확인하세요. '
        '[서열 점수](../science/specificity_scores.csv) → [기질 기여도](../kinase/substrate_contributions.csv) → '
        '[native membership](../kinase/method_membership.csv) → [방법 결과](../kinase/method_scores.csv)는 별도 근거입니다. '
        'PSSM percentile은 정답 확률이 아니며 method p/q는 생물학적 반복의 p/q가 아닙니다. '
        '서열 적합성으로 미측정 localization이나 개별 kinase 활성·인과를 확정하지 마세요. '
        + stored_method_limit_sentence(tables.get('kinase/method_scores')),
        '선정: 기존 select_finding_cards의 quality/parent/pattern diversity 및 stable ID 기준, 최대 15개. '
        '질문 연결은 선정 이후 수행하며 경로 기대를 점수에 사용하지 않습니다. '
        + kinase_link_sentence(kinase_summary) + ' '
        '이 선정만으로 insulin cascade를 구성하지 마세요. 전체 emergence, protein, kinase 표로 범위를 넓히세요. '
        'method_id가 repository_measured_gene_zscore인 행은 PhosX 결과가 아닙니다. PhosX_native_functions와 method_executions가 있을 때만 PhosX로 읽습니다.',
        '## 저장된 연구 질문']
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
        limits=list(c['interpretation_limits'])
        if packet.get('literature'):
            limits=[('Literature search/comparison status: '+packet['literature']['finding_records'][c['finding_id']]['status']+'; see reader/literature_search.csv. Independent validation not performed.')
                if v=='Literature comparison and independent validation were not performed by this reader stage.' else v for v in limits]
        effects = sorted({comparisons[cid]['comparison_class'] for cid in c['parent_comparison_card_ids'] if cid in comparisons})
        opposite = c['opposite_signed_observations']
        lines.extend(['Parent 영향 (기존 기술적 분류, 유의성 검정 아님): '+', '.join(effects),
            '반대 방향 관측: '+opposite['status']+'. 실제 양/음의 A 행은 packet의 opposite_signed_observations에서 추적합니다.',
            '제한: '+ ' '.join(limits),
            '전체 joint masks·U_all/P_all·실제 precursor membership·좌표 및 localization ID는 [카드](cards.csv)의 source_bindings와 [adapter 원본](../reader_adapter/form_contrasts.csv)에 보존됩니다.'])
    if packet.get('literature'):
        lines.insert(7, '[선정 관측별 문헌 검색·비교·접근 제한](LITERATURE.md) · [문헌 단계 요약](literature_summary.json)')
    method_artifacts = write_phosx_time_views(directory, tables)
    temporal_artifacts = write_temporal(directory, packet)
    if temporal_artifacts:
        lines.insert(7, '[저장된 시간 특징·인접 비교·기질 구성·제외 민감도](TEMPORAL_EVIDENCE.md) · [finding→원본 시간 근거](temporal_links.csv)')
    if method_artifacts:
        lines.insert(7, '[PhosX 시간별 입력 범위·실행 상태·assay 결과](PHOSX_TIME_COURSE.md)')
    rendered = ''.join(('\n' if i and line.startswith('|') and lines[i-1].startswith('|') else '\n\n') + line
                       for i,line in enumerate(lines)).lstrip()+'\n'
    (directory/'reader/READ_ME.md').write_text(rendered,encoding='utf-8')
    if packet.get("literature"):
        from .astra_literature import write
        return ARTIFACTS + access_artifacts + method_artifacts + temporal_artifacts + write(directory,tables)
    return ARTIFACTS + access_artifacts + method_artifacts + temporal_artifacts
