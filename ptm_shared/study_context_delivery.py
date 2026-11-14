"""Read-only context views of an execution snapshot; never resolve experimental facts."""
import hashlib
import json
from pathlib import Path
from .astra_inputs import CONTEXT_CONTRACT, resolve_pointer, value_hash
from .study_display import study_display
from .control_comparison import comparison_summary

VERSION = 'study_context_delivery.v1'
PATH = 'reader/STUDY_CONTEXT.json'
GUIDE = 'reader/STUDY_CONTEXT.md'
SOURCES = ('study/user_input_snapshot.json', 'study/study_context.json', 'study/study_design.json')
RAW_FIELDS = ('biological_question', 'cell_type', 'tissue', 'species', 'model', 'treatment',
              'special_conditions', 'time_points', 'treatment_arms', 'dose', 'vehicle', 'exposure',
              'enrichment', 'pre_treatment', 'acquisition', 'processing', 'science',
              'sample_manifest', 'replication_plan')


def source_ref(root, name, pointer=''):
    path = root/name
    return {'file': name, 'pointer': pointer,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def context_projection(root):
    root = Path(root)
    docs = {name: json.loads((root/name).read_text()) for name in SOURCES}
    snapshot, context, design = [docs[name] for name in SOURCES]
    original = snapshot['original']; raw = original.get('analysis_context') or {}
    fields = {}
    for key in RAW_FIELDS:
        value = raw.get(key)
        exists = key in raw
        preview = value[:1200] if isinstance(value, str) else value
        fields[key] = {'information_status': 'not_recorded' if value is None else
                       'provided_structured' if isinstance(value, (dict, list)) else 'provided_raw',
                       'preview': preview, 'preview_truncated': isinstance(value, str) and len(value)>1200,
                       'source_ref': source_ref(root, SOURCES[0], '/original/analysis_context/'+key) if exists else None,
                       'scope': 'study', 'relationship_inference': 'not_performed'}
    explicit = (original.get('report_options') or {})
    roles = {
        'study_design_context': {'fields': fields, 'complete_original': source_ref(root, SOURCES[0], '/original'),
            'study_species': original.get('species'), 'organism_code': original.get('organism_code'),
            'species_scope': 'recorded_study_metadata; does_not_replace_transgene_or_feature_taxon'},
        'execution_design': {'source_ref': source_ref(root, SOURCES[2]),
            'resolved_context_ref': source_ref(root, SOURCES[1]),
            'display': study_display(design, context), 'control_comparison': comparison_summary(design),
            'arms': design.get('arms', []), 'conditions': design.get('conditions', []),
            'contrasts': design.get('contrasts', []), 'issues': design.get('issues', []),
            'validity': design.get('status'), 'context_completeness': 'not_assessed'},
        'research_question': {'values': explicit.get('research_questions'),
            'information_status': 'provided_structured' if 'research_questions' in explicit else 'not_recorded',
            'source_ref': source_ref(root, SOURCES[0], '/original/report_options/research_questions')
                          if 'research_questions' in explicit else None},
        'expectation_or_hypothesis': {'information_status': 'provided_raw' if any(k in raw for k in ('expectation','hypothesis','expected_pathways')) else 'not_recorded_as_separate_field',
            'recorded_fields': {k: {'value': raw[k], 'source_ref': source_ref(root, SOURCES[0], '/original/analysis_context/'+k)}
                                for k in ('expectation','hypothesis','expected_pathways') if k in raw},
            'rule': 'Expectations embedded in the original prose remain prose; no extraction or factual promotion.'}}
    return {'schema_version': VERSION, 'source_record_id': snapshot.get('source_record_id'),
        'question_contract': snapshot.get('context_contract', 'legacy_question_contract'),
        'source_refs': [source_ref(root, name) for name in SOURCES], 'roles': roles,
        'execution_run_id': (json.loads((root/'study/input_delivery_receipt.json').read_text()).get('run_id')
                             if (root/'study/input_delivery_receipt.json').is_file() else None),
        'publication_run_ref': 'provenance.json#/run_id',
        'execution_records': {name: {'file': name, 'status': 'read_if_present_in_execution_manifest'}
                             for name in ['evidence/readiness.json', 'methods/normalization.json', 'methods/method_registry.json',
                                          'science/inference_results.csv', 'reader/EXECUTION_STATUS.json']},
        'whole_evidence': {'catalog': 'reader/EVIDENCE_ACCESS.md', 'questions': 'reader/FULL_EVIDENCE.md',
                           'signal_flow': 'reader/SUBSTRATE_SIGNAL_FLOW.md', 'selected_findings_is_scope_limit': False},
        'consumer_binding_status': 'connected_to_reading_material', 'semantic_review_status': 'not_performed'}


def context_markdown(projection):
    context = projection['roles']['study_design_context']['fields']['biological_question']
    return ('# 연구 맥락과 실행 설계\n\n'
        'Biological Design → 실제 실행 설계·Control → 전체 관측 → 시간/kinase 근거 → 문헌·가설 → source 검증 순으로 읽습니다.\n\n'
        '설계 원문은 측정 결과나 연구 질문이 아닙니다. 기대·문헌 prior·관측·AI 해석을 구분하세요. 이미 제공한 정보를 다시 요청하지 마세요.\n\n'
        '## Biological Design preview\n\n' + (str(context['preview']) if context['preview'] is not None else '미기록') +
        ('\n\n미리보기 일부 생략. 전체 원문은 아래 snapshot locator에서 읽습니다.' if context['preview_truncated'] else '') +
        '\n\n원문: `study/user_input_snapshot.json#/original/analysis_context/biological_question` (미기록인 경우 locator 없음).\n\n'
        '[구조화 맥락과 정확한 원문 locator](STUDY_CONTEXT.json) · [원문 전체 및 실행 비교](../study/STUDY_BRIEF.md) · '
        '[전체 관측](EVIDENCE_ACCESS.md) · [실제 실행 상태](../evidence/readiness.json).\n\n'
        '등록 반복/주입/material/biological unit/pair는 별개입니다. execution_design.display의 저장된 집계를 사용하고 원문을 새 확정 사실로 파싱하지 마세요. '
        '자료 연결은 모델 검토 또는 의미 승인이 아닙니다.\n')


def write_context(directory, *, source_root=None):
    from .generic_workflow import json_write
    directory = Path(directory); root = Path(source_root or directory)
    if not all((root/name).is_file() for name in SOURCES):
        return [], {'status': 'unavailable', 'reason': 'execution_snapshot_not_available'}
    projection = context_projection(root)
    # This view is replayable independently of whether another view has already been written.
    projection['execution_records']['reader/EXECUTION_STATUS.json']['status'] = 'see_current_execution_projection'
    json_write(directory/PATH, projection)
    (directory/GUIDE).write_text(context_markdown(projection), encoding='utf-8')
    return [PATH, GUIDE], {'schema_version': VERSION, 'file': PATH,
        'sha256': hashlib.sha256((directory/PATH).read_bytes()).hexdigest(),
        'source_record_id': projection['source_record_id'], 'source_refs': projection['source_refs'],
        'status': 'connected_to_reading_material', 'semantic_review_status': 'not_performed'}


def verify_context_binding(root, binding, read=None):
    root = Path(root); read = read or (lambda name: (root/name).read_bytes())
    if binding.get('file') != PATH: raise ValueError('Research context: consumer wrong pointer')
    if hashlib.sha256(read(PATH)).hexdigest() != binding.get('sha256'):
        raise ValueError('Research context: consumer stale projection hash')
    projection = json.loads(read(PATH))
    for ref in projection['source_refs']:
        if ref['file'] not in SOURCES or hashlib.sha256(read(ref['file'])).hexdigest() != ref['sha256']:
            raise ValueError('Research context: stale source ' + ref['file'])
    def walk(value):
        if isinstance(value, dict):
            if set(('file','pointer','sha256')) <= set(value):
                if value['file'] not in SOURCES: raise ValueError('Research context: wrong source locator')
                data = read(value['file'])
                if hashlib.sha256(data).hexdigest() != value['sha256']: raise ValueError('Research context: stale locator')
                try: resolve_pointer(json.loads(data), value['pointer'])
                except (KeyError, IndexError, ValueError): raise ValueError('Research context: unresolved locator ' + value['pointer']) from None
            else:
                for v in value.values(): walk(v)
        elif isinstance(value, list):
            for v in value: walk(v)
    walk(projection)
    if binding.get('source_refs') != projection['source_refs']:
        raise ValueError('Research context: consumer source refs differ')
    if projection['roles'] != context_projection(root)['roles']:
        raise ValueError('Research context: projected value or role differs from execution snapshot')
    return projection


def load_report_context(order_root):
    from .substrate_signal_view import published_root
    try: root = published_root(order_root)
    except FileNotFoundError: return {'status': 'unavailable', 'reason': 'published_execution_snapshot_unavailable'}
    provenance = json.loads((root/'provenance.json').read_text())
    path = root/'reader/authoring_packet.json'
    if not path.is_file(): return {'status': 'unavailable', 'reason': 'reader_not_published'}
    manifest = json.loads((root/'manifest.json').read_text())['files']
    for name in ['reader/authoring_packet.json', *SOURCES]:
        if hashlib.sha256((root/name).read_bytes()).hexdigest() != manifest.get(name, {}).get('sha256'):
            raise ValueError('Research context: published metadata hash mismatch ' + name)
    binding = json.loads(path.read_text()).get('study_context_delivery')
    if not binding: return {'status': 'unavailable', 'reason': 'legacy_reader_without_context_projection'}
    projection = verify_context_binding(root, binding)
    snapshot=json.loads((root/SOURCES[0]).read_text())
    execution_context=json.loads((root/SOURCES[1]).read_text())
    raw=snapshot['original'].get('analysis_context') or {}
    if 'biological_question' in raw: execution_context['biological_question']=raw['biological_question']
    return {'binding': binding, 'context': projection, 'status': 'connected_to_report_input',
            'recorded_context': execution_context,
            'recorded_questions': (snapshot['original'].get('report_options') or {}).get('research_questions'),
            'publication_run_id': provenance.get('run_id'), 'semantic_review_status': 'not_performed'}


def format_report_context(packet):
    if not packet or packet.get('status') != 'connected_to_report_input': return ''
    return '\n=== SAVED STUDY CONTEXT (not measured results) ===\n' + json.dumps({k:v for k,v in packet.items() if k not in {'recorded_context','recorded_questions'}}, ensure_ascii=False) + '\n'


def bind_report_state(state, saved):
    """Use the published context for this report input without changing the draft."""
    from copy import deepcopy
    if saved.get('status') != 'connected_to_report_input': return dict(state)
    result = {**state, 'study_context_delivery': saved,
              'experimental_context': deepcopy(saved['recorded_context'])}
    if saved['context']['question_contract'] == CONTEXT_CONTRACT:
        questions = deepcopy(saved.get('recorded_questions') or [])
        result.update(original_research_questions=questions, research_questions=questions)
    return result
