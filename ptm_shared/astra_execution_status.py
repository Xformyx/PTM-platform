"""Display projection of frozen execution facts; no retrieval or semantic review."""
from collections import Counter
from copy import deepcopy
import json

VERSION = 'astra_current_execution.v1'
PATH = 'reader/EXECUTION_STATUS.json'
CURRENT_SCOPE = 'see current_execution.typed_subject_review and selected_finding_review; scopes remain separate'


def _retrieval(counts):
    states = {k for k,v in counts.items() if v}
    if not states: return 'unknown'
    if states <= {'not_requested'}: return 'not_requested'
    if states <= {'no_hit','no_hits','searched_no_hits','not_explained_by_retrieved_evidence'}: return 'completed_no_hit'
    done = {'retrieved','retrieved_comparison_pending','no_hit','no_hits','searched_no_hits','not_explained_by_retrieved_evidence','compared_no_supported_relationship'}
    if states <= done: return 'completed'
    if states & done: return 'partial'
    if 'partial_retrieval_failure' in states: return 'partial'
    if states <= {'retrieval_failed','failed'}: return 'failed'
    return 'incomplete' if states & {'budget_deferred','not_searched','budget_exhausted'} else 'unknown'


def _comparison(completed, requested, failed=None):
    if completed is None or requested is None: return 'unknown'
    if requested == 0: return 'not_requested'
    if completed == requested: return 'completed'
    if completed: return 'partial'
    return 'failed' if failed else 'not_performed'


def project_current_status(packet):
    selected = packet.get('literature') or {}; ss = selected.get('summary') or {}
    records = selected.get('finding_records') or {}
    typed = packet.get('literature_subject_execution') or {}; ts = typed.get('summary') or {}
    binding = typed.get('binding') or {}
    result = {'schema_version':VERSION,'source':'immutable execution pins and their validated table projections',
        'projection_cost':{'queries':0,'model_calls':0,'scientific_calculations':0},
        'historical_origin':deepcopy((packet.get('current_execution') or {}).get('historical_origin',{}))}
    for name,scope,summary in [('selected_finding_review',selected,ss),('typed_subject_review',typed,ts)]:
        is_typed = name=='typed_subject_review'
        requested = summary.get('requested_subjects' if is_typed else 'selected_findings')
        completed = summary.get('comparison_executed_subjects' if is_typed else 'comparison_executed_findings')
        if not is_typed and records:
            completed = sum(r.get('comparison_execution',{}).get('status')=='completed' for r in records.values())
        counts = summary.get('execution_status_counts' if is_typed else 'status_counts')
        if not is_typed and records:
            counts = dict(Counter('partial_retrieval_failure' if r.get('partial_retrieval_failure') else r.get('status','unknown') for r in records.values()))
        exported = summary.get('exported_anchored_proposals' if is_typed else 'anchored_proposals')
        result[name] = {
            'plan':'available' if packet.get('literature_review_plan') or scope else 'unknown',
            'request':'requested' if requested else 'not_requested' if requested==0 else 'unknown',
            'requested_count':requested,'count_unit':'typed representations' if is_typed else 'selected findings',
            'requested_scope':summary.get('requested_scope_status','unknown') if is_typed else _comparison(completed,requested),
            'whole_scope':summary.get('status','unknown') if is_typed else 'selected_scope_only',
            'retrieval':_retrieval(counts or {}),'retrieval_status_counts':counts or {},
            'model_comparison':_comparison(completed,requested,summary.get('comparison_failed_findings')),
            'comparison_executed_count':completed,'exported_anchored_proposals':exported,
            'anchor_validation':'not_applicable_no_exported_proposals' if exported==0 else 'recorded_source_anchors' if exported else 'unknown',
            'semantic_review':'not_performed' if summary.get('semantic_status') or summary.get('comparison_validation') else 'unknown',
            'semantic_recorded_status':summary.get('semantic_status',summary.get('comparison_validation','unknown')),
            'approved_count':summary.get('semantically_approved_subjects' if is_typed else 'semantically_verified_comparable_findings'),
            'export':'see per-source export_status; access is not redistribution permission',
            'external_review':summary.get('external_astra_review_status','not_recorded'),
            'unique_chunks':summary.get('retrieved_unique_chunks' if is_typed else 'source_chunks_read'),
            'documents_with_chunks':summary.get('retrieved_documents' if is_typed else 'documents_read'),
            'independent_external_publications_with_chunks':summary.get('external_publications_with_retrieved_chunks') if is_typed else None,
            'read_scope':'retrieved chunks only; no claim of whole-paper review',
            'execution_cost':deepcopy(summary.get('current_cost' if is_typed else 'cost')),
            'consumer_cost':deepcopy(binding.get('current_cost')) if is_typed else None,
            'reuse_mode':binding.get('effective_mode','unknown') if is_typed else 'see frozen finding execution pin',
            'pin_sha256':summary.get('pin_sha256' if is_typed else 'literature_pin_sha256')}
    return result


def attach_current_status(packet):
    state = project_current_status(packet)
    whole = packet.get('whole_evidence')
    if whole is not None:
        previous = whole.get('literature_execution_scope')
        if previous and previous != CURRENT_SCOPE:
            state['historical_origin'].setdefault('whole_evidence.literature_execution_scope',previous)
        whole['literature_execution_scope'] = CURRENT_SCOPE
        whole['current_execution'] = PATH
    for q in packet.get('research_question_evidence_map',{}).get('questions',[]):
        if 'whole_evidence' in q:
            q['whole_evidence']['literature_scope'] = CURRENT_SCOPE
    if packet.get('evidence_access'):
        packet['evidence_access']['limits']='Whole evidence access is separate from bounded literature execution; see reader/EXECUTION_STATUS.json.'
    packet['current_execution'] = state
    return state


def status_markdown(packet):
    state = project_current_status(packet)
    lines = ['## 현재 문헌 실행 상태', '[공통 실행 상태](EXECUTION_STATUS.json). 원 생성 단계의 설명은 historical_origin이며 현재 실행을 덮어쓰지 않습니다.',
             '| 범위 | 검색 | 모델 비교 | 요청 범위 | 전체 범위 | 내보낸 anchor 제안 |', '|---|---|---|---|---|---|']
    for key in ('selected_finding_review','typed_subject_review'):
        s=state[key]
        lines.append('| '+' | '.join(str(x) for x in [key,s['retrieval'],s['model_comparison'],s['requested_scope'],s['whole_scope'],s['exported_anchored_proposals']])+' |')
    lines.append('Anchor와 수치 추적은 의미 승인이 아닙니다. 미요청·no_hit·정상 빈 비교·부분 실패를 구분하며, 새 조회/모델 호출 없이 저장 기록만 투영했습니다.')
    return '\n\n'.join(lines[:2])+'\n\n'+'\n'.join(lines[2:])+'\n'


def write_status_views(directory, packet, *, source_root=None):
    """Only display files in a new output directory; pin/table bytes untouched."""
    import re
    from pathlib import Path
    root=Path(directory);state=attach_current_status(packet);artifacts=[PATH]
    (root/PATH).write_text(json.dumps(state,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    note='<!-- current-execution-start -->\n'+status_markdown(packet)+'<!-- current-execution-end -->'
    for name in ['READ_ME.md','FULL_EVIDENCE.md','LITERATURE.md','LITERATURE_SUBJECT_REVIEW.md']:
        p=root/'reader'/name
        if not p.exists() and source_root is not None:
            source=Path(source_root)/'reader'/name
            if source.is_file():p.write_bytes(source.read_bytes())
        if p.is_file():
            content=re.sub(r'\n*<!-- current-execution-start -->.*?<!-- current-execution-end -->','',p.read_text(),flags=re.S)
            p.write_text(content.rstrip()+'\n\n'+note+'\n',encoding='utf-8')
            artifacts.append('reader/'+name)
    return artifacts
