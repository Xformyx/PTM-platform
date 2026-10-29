"""Display/metadata only. Synthetic registrations, no scientific execution."""
from copy import deepcopy
import json

import pytest

from ptm_shared.study_execution import resolve_context
from ptm_shared.study_display import study_display, study_display_markdown

LABELS = ['Control', '0.5h', '1h', '3h', '6h', '24h']
DESIGN_TEXT = '  모델 α · 처리 및 시간 계획\n반복 설계와 분석 목적 원문  '


def fixture(counts=(3, 3, 3, 3, 3, 3), rep_ids=None, injections_per_rep=1):
    rows = [{'sample_id': f'f{i}_{n}_{t}', 'condition': label, 'replicate': r,
             'group': 'Control' if i == 0 else 'Treatment'}
            for i, (label, count) in enumerate(zip(LABELS, counts))
            for n, r in enumerate(rep_ids if rep_ids is not None else range(1, count + 1))
            for t in range(injections_per_rep)]
    context = {'quantitation_export_mode': 'astra_analysis.v5', 'time_points': '0,0.5,1,3,6,24h',
               'biological_question': DESIGN_TEXT}
    return resolve_context(context, rows, taxonomy_id=9606, species='human'), rows


def test_registered_ids_survive_unknown_materials_and_shared_control():
    context, rows = fixture()
    design = context['study_design']; before = deepcopy(design)
    display = study_display(design, context); rep = display['replication']
    assert design['status'] == 'resolved' and design['materials'] == []
    assert rep['summary'] == '등록 반복: 조건별 3반복 · 총 18개 측정 파일'
    assert rep['injection_count'] == 18 and rep['material_count'] == rep['biological_unit_count'] == 0
    assert rep['replication_type'] == 'unknown' and rep['pairing'] == ['unknown']
    assert [c['replicate_ids'] for c in rep['conditions']] == [['1','2','3']] * 6
    assert [c['measurement_file_count'] for c in rep['conditions']] == [3] * 6
    assert rep['conditions'][0]['label'] == 'Control'
    assert len({c['reference_condition_id'] for c in design['contrasts']}) == 1
    assert len(design['contrasts']) == 5  # Reference reuse does not multiply registrations.
    assert rep['planned_summary'] is None  # Existing experiment: no retroactive default.
    assert display['biological_question']['value'] == DESIGN_TEXT
    assert design == before
    rerun = resolve_context(context, rows, taxonomy_id=9606, species='human')
    assert rerun == context and study_display(rerun['study_design'], rerun) == display


def test_unequal_registration_and_nonconsecutive_ids_are_not_inferred():
    context, _ = fixture((3, 3, 2, 3, 3, 3))
    rep = study_display(context['study_design'], context)['replication']
    assert rep['summary'] == '등록 반복: Control 3 · 0.5h 3 · 1h 2 · 3h 3 · 6h 3 · 24h 3 · 총 17개 측정 파일'
    context, _ = fixture(rep_ids=[1, 2, 4])
    rep = study_display(context['study_design'], context)['replication']
    assert [c['registered_replicate_count'] for c in rep['conditions']] == [3] * 6
    assert all(c['replicate_ids'] == ['1','2','4'] and c['statuses'] == ['nonconsecutive_replicate_ids'] for c in rep['conditions'])


def test_multiple_injections_per_rep_and_serialization_identity():
    context, _ = fixture(injections_per_rep=2)
    rep = study_display(context['study_design'], context)['replication']
    assert rep['measurement_file_count'] == rep['injection_count'] == 36
    assert all(c['registered_replicate_count'] == 3 and c['injection_count'] == 6 for c in rep['conditions'])
    assert all(c['multiple_injection_replicate_ids'] == ['1','2','3'] for c in rep['conditions'])
    assert rep['replication_type'] == 'unknown'  # IDs do not declare technical or biological.
    context, _ = fixture(rep_ids=[1, '1', '01', '1.0', 'A', 'a'])
    rep = study_display(context['study_design'], context)['replication']
    assert all(c['replicate_ids'] == ['1','01','1.0','A','a'] for c in rep['conditions'])
    assert all(c['registered_replicate_count'] == 5 and c['measurement_file_count'] == 6 for c in rep['conditions'])


def test_missing_duplicate_and_conflicting_records_are_local_and_deduplicated():
    context, _ = fixture(); design = context['study_design']
    first = design['injections'][0]
    first.pop('legacy_replicate')
    design['injections'].append(deepcopy(first))  # Same PR/PG injection must not count twice.
    rep = study_display(design, context)['replication']
    assert rep['injection_count'] == rep['measurement_file_count'] == 18
    control = rep['conditions'][0]
    assert control['registered_replicate_count'] == 2 and control['missing_replicate_id_count'] == 1
    assert set(control['statuses']) == {'replicate_id_missing','duplicate_injection_records','nonconsecutive_replicate_ids'}
    assert all(c['statuses'] == [] for c in rep['conditions'][1:])
    design['injections'][-1]['legacy_replicate'] = 'conflicting-id'
    rep = study_display(design, context)['replication']
    assert 'injection_mapping_conflict' in rep['conditions'][0]['statuses']
    assert all('injection_mapping_conflict' not in c['statuses'] for c in rep['conditions'][1:])
    assert rep['measurement_file_count'] == 18


@pytest.mark.parametrize('planned', [2, 3, 4])
def test_saved_plan_is_separate_from_actual_two_and_numerical_design(planned):
    context, rows = fixture((2,)*6); before = deepcopy(context['study_design'])
    context['replication_plan'] = {'default_replicates_per_condition': planned, 'source': 'user_input'}
    resolved = resolve_context(context, rows, taxonomy_id=9606, species='human')
    assert resolved['replication_plan'] == context['replication_plan']
    assert resolved['study_design'] == before
    rep = study_display(resolved['study_design'], resolved)['replication']
    assert rep['summary'] == '등록 반복: 조건별 2반복 · 총 12개 측정 파일'
    assert rep['planned_summary'] == f'예정 반복: 조건별 {planned} (실제 등록 수와 별도)'
    assert all(c['planned_replicate_count'] == planned for c in rep['conditions'])
    assert all(c['plan_comparison'] == ('matches' if planned == 2 else 'differs') for c in rep['conditions'])


def test_existing_biological_mapping_and_ids_are_preserved():
    from ptm_shared.tests.test_study_input_reuse import inputs
    context, rows, manifest = inputs(); context['sample_manifest'] = manifest
    context = resolve_context(context, rows); before = deepcopy(context)
    display = study_display(context['study_design'], context)
    assert display['replication']['pairing'] == ['paired']
    assert display['replication']['biological_unit_count'] == 2
    assert resolve_context(context, rows) == before


def test_package_metadata_brief_and_reader_share_projection_and_exact_text(tmp_path):
    from ptm_shared.astra_package import write_study_inputs, start_here
    from ptm_shared.astra_inputs import capture_order, transfer_contract
    from ptm_shared.astra_card_inputs import metadata_packet
    from ptm_shared.astra_reader import _questions
    context, rows = fixture(); design = context['study_design']
    snapshot = capture_order({'id': 'synthetic', 'analysis_context': context, 'sample_config': rows,
                              'report_options': {'research_questions': ['별도 연구 질문 그대로']}})
    original = deepcopy(snapshot); expected = study_display(design, context)
    (tmp_path/'study').mkdir()
    write_study_inputs(tmp_path, snapshot, context, design)
    assert json.loads((tmp_path/'study/study_display.json').read_text()) == expected
    assert json.loads((tmp_path/'study/study_context.json').read_text()) == context
    assert json.loads((tmp_path/'study/study_design.json').read_text()) == design
    metadata = metadata_packet(design, context, snapshot)
    assert metadata['study_display'] == expected
    contract, _, brief = transfer_contract(snapshot, design, context, {})
    assert '## Biological Design' in brief and DESIGN_TEXT in brief
    assert expected['replication']['summary'] in brief and '별도 연구 질문 그대로' in brief
    fields = [f for f in contract if f['source_field_path'].endswith('/biological_question')]
    assert fields and all(f['display_name'] == 'Biological Design' and '기존 호환 필드' in f['field_description'] for f in fields)
    assert '|---|---|' in brief and '|\n\n|---|' not in study_display_markdown(expected)
    raw, questions = _questions(snapshot, metadata)
    assert raw['biological_question'] == DESIGN_TEXT
    assert raw['research_questions'] == ['별도 연구 질문 그대로']
    assert [q['question_id'] for q in questions] == ['BQ-001','RQ-001']
    assert snapshot == original
    assert 'Biological Design (compatibility key: biological_question)' in start_here(snapshot, {}, {})
