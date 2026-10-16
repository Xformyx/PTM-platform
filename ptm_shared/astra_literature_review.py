"""M3 literature subjects: whole-evidence planning and explicitly requested review.

The default package path only writes locators. Retrieval is an explicit operation
using the existing RAG/comparison/export/cache boundaries, never a writer side effect.
"""
from collections import Counter, defaultdict
from copy import deepcopy
import json
from pathlib import Path

import pandas as pd

from .astra_card_inputs import encode
from .astra_inputs import stable_id
from .astra_evidence_catalog import EvidenceCatalog, read_source, CATALOG
from .astra_reader_temporal import source_row
from .annotation_registry import digest
from .generic_workflow import json_write, object_hash

VERSION = 'literature_review_subjects.v1'
PLAN = 'reader/literature_review_subjects.csv'
META = 'reader/literature_review_plan.json'
GUIDE = 'reader/LITERATURE_REVIEW_PLAN.md'
TABLE_KEYS = {PLAN[:-4]: ['review_subject_id']}
ARTIFACTS = [PLAN, META, GUIDE]
# A disposition row is not another measurement. Its original restrictions remain
# accessible through M1 links. All other indexed representations remain explicit.
READOUTS = {
    'observation': 'observed joint PTM/parent contrasts; U_joint/P_joint/A, log2',
    'comparison': 'one saved PTM/parent contrast; no new estimate',
    'raw_ptm': 'raw form-contrast including withheld/NA; original eligibility only',
    'ptm_contrast': 'saved PTM contrast with original joint mask and eligibility',
    'form': 'form identity/mapping context; not an additional measurement',
    'protein': 'protein abundance contrast; not kinase activity',
    'detection': 'detection counts/pattern; not biological replicate count or fold change',
    'emergence': 'detection emergence/post-reference evidence; no invented baseline fold change',
    'method_result': 'method-specific score/p/q/null/coverage; not biological p/q or activity proof',
    'inference': 'saved call/no-call and calibration restrictions; no-call is not inactivity',
}
COLUMNS = ['review_subject_id', 'evidence_id', 'source_table', 'source_key_json', 'subject_type',
           'finding_alias', 'question_ids_json', 'request_reason', 'eligibility', 'eligibility_reason',
           'priority_reason', 'execution_status', 'comparison_status', 'semantic_status',
           'scope_json', 'status_json', 'restrictions_json', 'readout', 'schema_version']


def attach_review_plan(tables):
    packet = json.loads(tables['reader/packet'].iloc[0].packet_json)
    packet['literature_review_plan'] = {
        'schema_version': VERSION, 'subjects': PLAN, 'manifest': META, 'guide': GUIDE,
        'scope': 'whole indexed evidence; summary-independent; typed inputs resolved on request',
        'execution': 'not_requested', 'new_searches': 0, 'new_model_calls': 0,
        'legacy_results': 'reader/literature_search.csv and references/finding_literature_pin.json unchanged',
        'limits': 'Planning/access is not retrieval, comparison, semantic approval or independent validation. M4 not performed.'}
    packet['authoring_rules']['literature_review_subjects'] = (
        'Use review_subject_id and exact M1 source refs for unselected/withheld/method evidence. '
        'Resolve M2 question/time/citation links before requesting review. Preserve readout, scope and exclusions. '
        'Legacy finding IDs are aliases; selected_finding_ids is not the new subject universe. '
        'Current plan not_requested does not erase prior frozen review execution.')
    tables['reader/packet'].loc[:, 'packet_json'] = encode(packet)


def build_plan(catalog, question_links=None):
    """Thin locators; no vectors/card JSON, inferred question links, or searches."""
    from .astra_reader import finding_id_for_card
    catalog._require()
    questions = defaultdict(set)
    if question_links is None:
        name = 'reader/full_question_links.csv'
        if name not in catalog.catalog['sources']:
            raise ValueError('M3 requires M2 whole question links')
        question_links = read_source(catalog.root, name, catalog.catalog['sources'][name])
    for r in question_links.itertuples():
        if r.status not in {'resolved','linked'}: continue
        questions[r.evidence_id].add(r.question_id)
        for subject in json.loads(r.subject_evidence_ids_json): questions[subject].add(r.question_id)
    rows = []
    for raw in catalog.index.to_dict('records'):
        e = source_row(raw)
        if e['evidence_type'] == 'disposition': continue
        kind = e['evidence_type']; qids = sorted(questions[e['evidence_id']])
        supported = kind in READOUTS
        rows.append({
            'review_subject_id': stable_id('review_subject', [VERSION, e['source_table'], json.loads(e['source_key_json'])]),
            'evidence_id': e['evidence_id'], 'source_table': e['source_table'], 'source_key_json': e['source_key_json'],
            'subject_type': kind,
            'finding_alias': finding_id_for_card(e['card_id']) if kind == 'observation' else None,
            'question_ids_json': encode(qids), 'request_reason': 'not_requested',
            'eligibility': 'eligible_with_source_restrictions' if supported else 'unsupported_subject_type',
            'eligibility_reason': 'typed_readout_preserved; eligibility_is_not_scientific_inclusion' if supported else 'no_lossless_typed_adapter',
            'priority_reason': 'existing_question_link' if qids else 'available_unlinked_evidence',
            'execution_status': 'not_requested', 'comparison_status': 'not_performed', 'semantic_status': 'not_reviewed',
            'scope_json': e['scope_json'], 'status_json': e['status_json'], 'restrictions_json': e['restrictions_json'],
            'readout': READOUTS.get(kind, 'unsupported'), 'schema_version': VERSION})
    plan = pd.DataFrame(rows, columns=COLUMNS)
    if plan.review_subject_id.duplicated().any(): raise ValueError('Duplicate review subject')
    return plan  # M1 scope/numeric time/stable ID order; never summary rank.


def write_review_plan(directory, tables, *, source_root=None):
    """Called by the package writer and reader-only replay, no runtime discovery."""
    from .astra_package import write_tables
    root = Path(directory)
    catalog = EvidenceCatalog(root if source_root is None else source_root)
    # During normal generation the refreshed M1/M2 catalog is in directory.
    if source_root is None:
        links = None
    else:
        links = tables.get('reader/full_question_links')
    plan = build_plan(catalog, links)
    metadata = write_tables({PLAN[:-4]: plan}, root)
    dpath = root/'reproducibility/data_dictionary.json'
    if source_root is None:
        dictionary = json.loads(dpath.read_text())
        dictionary.update(metadata)
        json_write(dpath, dictionary)
    cpath = root/CATALOG
    content = json.loads(cpath.read_text())
    content['sources'][PLAN] = {**metadata[PLAN], 'sha256': digest(root/PLAN),
        'descriptor_schema_version': VERSION, 'availability': 'available' if len(plan) else 'available_empty',
        'role': 'literature_review_plan', 'indexed': False, 'access': 'registered_source_and_canonical_key',
        'independent_observation_count': None}
    content['catalog_id'] = object_hash({k:v for k,v in content.items() if k != 'catalog_id'})
    json_write(cpath, content)
    prior = Path(source_root or directory)/'references/finding_literature_pin.json'
    selection = Path(source_root or directory)/'references/literature_pin.json'
    packet=json.loads(tables['reader/packet'].iloc[0].packet_json)
    legacy = packet.get('literature',{}).get('pin') or (json.loads(prior.read_text()) if prior.is_file() else {})
    meta = {'schema_version': VERSION, 'subjects': PLAN, 'subjects_sha256': digest(root/PLAN),
        'subject_count': len(plan), 'by_subject_type': dict(Counter(plan.subject_type)),
        'by_eligibility': dict(Counter(plan.eligibility)), 'current_execution': 'not_requested',
        'current_queries': 0, 'current_model_calls': 0,
        'legacy_finding_pin_sha256': legacy.get('sha256'),
        'literature_selection_file_sha256': digest(selection) if selection.is_file() else None,
        'legacy_selected_finding_ids': legacy.get('selected_finding_ids', []),
        'legacy_execution_authority': 'reader/literature_search.csv; not reset by this plan',
        'execution_extension_schema': 'literature_subject_execution.v1',
        'cache_contract': 'resolved source values/scope/questions + pinned literature + code/model/prompt/policy; summary excluded',
        'population_semantics': 'representations overlap; rows are not independent observations',
        'request_contract': {'requested_subject_ids': 'explicit subset of plan', 'reason': 'required',
            'max_subjects': 'execution only, independent of retrieval layer quotas and max_queries/max_model_calls',
            'resume': 'deferred_subject_ids from frozen execution pin'},
        'review_status': 'not_recorded', 'M4': 'not_performed'}
    json_write(root/META, meta)
    (root/GUIDE).write_text('''# 전체 근거의 문헌 검토 대상 계획 (M3)

[전체 대상](literature_review_subjects.csv) · [계획/분모](literature_review_plan.json) · [원본 조회](EVIDENCE_ACCESS.md) · [질문·시간·인용](FULL_EVIDENCE.md)

선정 findings는 요약입니다. 미선정 관측, 보류 원본, protein, detection, method, no-call도 별도 typed 대상으로 접근합니다.
이 계획은 새 검색/LLM 비교를 수행하지 않습니다. 각 행의 not_requested는 이번 확장 실행 상태입니다.
기존 실제 문헌 실행과 승인 상태는 [기존 검색 기록](literature_search.csv)과 [기존 문헌](LITERATURE.md)을 따릅니다.
여러 행은 같은 근거의 표현일 수 있으며 독립 관측으로 합산하지 않습니다. 과학적 보류를 문헌 eligibility로 해제하지 않습니다.

원본/입력 조회 (네트워크 없음):
```sh
PYTHONPATH=PACKAGE/reproducibility/code python -m ptm_shared.astra_literature_review --package PACKAGE --evidence-id EVIDENCE_ID
```
ID는 evidence_index.csv 또는 M1 query에서 복사합니다. 출력의 review_subject_id가 명시적 요청 단위입니다.
subject ID, 질문, 요청 이유와 실행 예산을 기록해야 검색 경로를 호출할 수 있습니다.
예산은 실행량만 제한하고 자격/전체 분모를 지우지 않습니다. 미실행 목록을 별도로 재개할 수 있습니다.
원문 anchor, 제안된 관계, 의미 승인, 독립 검증을 구분하세요. 검색 실패는 no_hit이 아닙니다.
M4 실제 새 검색/비교는 미수행입니다. 기존 source/reference pin과 문헌 선택 pin은 별개입니다.
''', encoding='utf-8')
    return ARTIFACTS


def validate_plan(catalog):
    """Publication gate: exact M1 population/keys and M2-derived plan semantics."""
    path=catalog.root/META
    if not path.is_file():return {'available':False,'reason':'legacy_package_without_review_plan'}
    meta=json.loads(path.read_text())
    if meta.get('schema_version')!=VERSION or meta.get('subjects_sha256')!=digest(catalog.root/PLAN):
        raise ValueError('Review plan hash/schema mismatch')
    actual=read_source(catalog.root,PLAN,catalog.catalog['sources'][PLAN])
    expected=build_plan(catalog)
    if encode(actual.to_dict('records'))!=encode(expected.to_dict('records')):
        raise ValueError('Review plan population/key/status mismatch')
    if len(actual)!=meta['subject_count']:raise ValueError('Review plan count mismatch')
    return {'available':True,'subjects':len(actual),'execution':'not_requested'}


def resolve_subjects(catalog, plan, subject_ids, tables, snapshot, literature):
    """Read original values on demand through M1; never manufacture a PTM card."""
    from .astra_literature import inputs
    if len(subject_ids) != len(set(subject_ids)): raise ValueError('Duplicate requested review subject')
    by_id = plan.set_index('review_subject_id')
    if set(subject_ids)-set(by_id.index): raise ValueError('Unknown review subject')
    chosen = [source_row(by_id.loc[s].to_dict()) for s in subject_ids]
    resolved = catalog.resolve([r['evidence_id'] for r in chosen])
    _, study = inputs(tables, snapshot, literature, observation_cards=[])
    questions = json.loads(tables['reader/packet'].iloc[0].packet_json)['research_question_evidence_map']['questions']
    qtext = {q['question_id']: q['original_text'] for q in questions}
    result = []
    for sid, p, original in zip(subject_ids, chosen, resolved):
        e, row = original['evidence'], original['source_row']
        if p['source_table'] != e['source_table'] or p['source_key_json'] != e['source_key_json']:
            raise ValueError('Review subject source key mismatch')
        if sid != stable_id('review_subject', [VERSION, e['source_table'], json.loads(e['source_key_json'])]):
            raise ValueError('Review subject identity mismatch')
        if p['eligibility'] != 'eligible_with_source_restrictions': raise ValueError('Unsupported review subject')
        if p['subject_type'] == 'observation':
            card = deepcopy(original['card'])
            # Display-only summary attributes cannot invalidate a subject cache.
            for key in ('finding_id','selected','selected_for_summary','selection_reason'): card.pop(key, None)
            card['finding_id'] = p['finding_alias']
            prepared, _ = inputs(tables, snapshot, literature, observation_cards=[card])
            payload = prepared[0]
            identity = deepcopy(payload['feature_identity'])
        else:
            identity = {'gene': row.get('gene') or row.get('Genes'),
                        'entity_tokens': json.loads(e['entity_tokens_json']),
                        'fasta_taxonomy_id': json.loads(e['taxa_json'])}
            payload = {'literature_input': {'source_row': row, 'scope': json.loads(e['scope_json']),
                       'scientific_status': json.loads(e['status_json']), 'restrictions': json.loads(e['restrictions_json'])},
                       'interpretation_limits': json.loads(e['restrictions_json'])}
            # An existing comparison card remains a comparison, not an observation.
            if original['card']:
                payload['literature_input']['card'] = original['card']
                identity = deepcopy(original['card'].get('feature_identity') or identity)
        payload.update(review_subject_id=sid, subject_type=p['subject_type'], entity_identity=identity,
                       readout=p['readout'], allow_site_comparison=p['subject_type']=='observation')
        payload['literature_input'].update(review_subject_id=sid, evidence_ids=[e['evidence_id']],
            source_ref=original['source_ref'], readout=p['readout'],
            question_ids=json.loads(p['question_ids_json']),
            original_question_texts=[qtext[q] for q in json.loads(p['question_ids_json'])],
            source_status=json.loads(e['status_json']), source_restrictions=json.loads(e['restrictions_json']))
        payload['resolved_source_sha256'] = object_hash(_source_value(original))
        result.append(payload)
    return result, study


def _source_value(resolved):
    """Semantic source bytes for cache/replay, without summary-only card flags."""
    row=deepcopy(resolved['source_row'])
    if resolved['card']:
        card=deepcopy(resolved['card'])
        for k in ('finding_id','selected','selected_for_summary','selection_reason'):card.pop(k,None)
        row.pop('selected',None);row['card_json']=encode(card)
    return row


def execute_review(catalog, plan, subject_ids, tables, snapshot, literature, *, reason,
                   max_subjects, settings=None, retriever=None, llm=None, cache_root=None):
    """Explicit execution only; M3 tests inject fixtures. Default writers never call it."""
    from . import astra_literature as legacy
    from .finding_literature import retrieve_finding_literature
    from .evidence_stage_cache import cached_stage
    if not reason or not str(reason).strip(): raise ValueError('Explicit review reason required')
    if not isinstance(max_subjects, int) or max_subjects < 0: raise ValueError('Invalid subject budget')
    if len(set(subject_ids)) != len(subject_ids): raise ValueError('Duplicate requested review subject')
    index = plan.set_index('review_subject_id')
    if set(subject_ids)-set(index.index): raise ValueError('Unknown review subject')
    settings = deepcopy(settings or {})
    options = (snapshot or {}).get('original', {}).get('report_options') or {}
    policy = {'max_queries':128, 'max_model_calls':32, 'max_prompt_bytes':100000,
              **((options.get('report_config') or {}).get('finding_review_policy') or {}), **settings.get('budget', {})}
    if any(not isinstance(policy[k], int) or policy[k]<0 for k in ('max_queries','max_model_calls','max_prompt_bytes')):
        raise ValueError('Invalid execution budget')
    contract = legacy._execution_contract(options, settings)
    contract.update(review_subject_schema=VERSION, adapter_sha256=digest(Path(__file__)), budget=policy)
    requested = list(subject_ids)
    eligible = [sid for sid in requested if index.loc[sid,'eligibility']=='eligible_with_source_restrictions']
    scheduled = eligible[:max_subjects]
    payloads, study = resolve_subjects(catalog, plan, scheduled, tables, snapshot, literature)
    records = {sid: {'review_subject_id':sid, 'request_reason':str(reason),
        'execution_status':'not_searched' if sid in scheduled else 'budget_deferred' if sid in eligible else 'unsupported_subject_type',
        'comparison_status':'not_performed', 'semantic_status':'not_reviewed'} for sid in requested}
    references = []; used = {'queries':0,'model_calls':0}; keys = {}; reuse = {}
    if scheduled and retriever is None: retriever, llm, _ = legacy._runtime(literature, {**options,**settings})
    allowed = {c['chromadb_name'] for c in literature.get('collections',[]) if c.get('chromadb_name')}
    if scheduled and set(retriever.collection_names) != allowed: raise ValueError('Retriever scope differs from pinned selection')
    model = {'provider':getattr(llm,'provider',None),'model':getattr(llm,'model',None)}
    contract['resolved_model'] = model
    versioned = bool(allowed) and all(c.get('version') and c.get('version_scope')=='immutable_index_snapshot' for c in literature.get('collections',[]))
    class Incomplete(Exception):
        def __init__(self,result): self.result=result
    for payload in payloads:
        sid = payload['review_subject_id']
        remaining = {**policy, 'max_queries':max(0,policy['max_queries']-used['queries']),
                     'max_model_calls':max(0,policy['max_model_calls']-used['model_calls'])}
        request = {'subject':payload,'study':study,'literature':literature,'contract':contract,
                   'transport':legacy._transport_hash(retriever)}
        keys[sid] = object_hash(request)
        def compute():
            result = retrieve_finding_literature([payload],retriever,study,llm=llm,policy=remaining)
            record = result['records'][sid]
            if (record['status'] in {'not_searched','retrieval_failed','budget_exhausted','retrieved_comparison_pending'} or
                record.get('partial_retrieval_failure') or any(s.get('status')=='budget_exhausted' for s in record.get('searches',[])) or
                (record.get('retrieved_count') and record.get('comparison_execution',{}).get('status')!='completed')):
                raise Incomplete(result)
            return legacy._export_result(result,literature)
        try:
            if cache_root and versioned:
                result, cached = cached_stage(cache_root,'literature_review_subject',keys[sid],compute)
            else: result, cached = compute(), {'status':'not_cached','reason':'immutable_index_snapshot_required'}
        except Incomplete as exc:
            result=legacy._export_result(exc.result,literature);cached={'status':'not_cached','reason':'incomplete_retryable_result'}
        reuse[sid]=cached
        if cached['status']!='reused':
            for key in used: used[key]+=result['cost'][key]
        raw = result['records'][sid]
        status = ('retrieved' if raw.get('retrieved_count') else
                  'retrieval_failed' if raw.get('partial_retrieval_failure') or raw['status']=='retrieval_failed' else
                  'budget_deferred' if raw['status']=='budget_exhausted' or any(s.get('status')=='budget_exhausted' for s in raw.get('searches',[])) else
                  'not_searched' if raw['status']=='not_searched' else 'no_hit')
        records[sid].update(execution_status=status, comparison_status=raw.get('comparison_execution',{}).get('status','not_performed'),
            semantic_status='review_required' if raw.get('comparisons') or raw.get('comparison_execution',{}).get('status')=='completed' else 'not_reviewed',
            record=raw, request_sha256=keys[sid])
        references.extend(result.get('references',[]))
    pin = {'schema_version':'literature_subject_execution.v1', 'review_subject_schema':VERSION,
        'requested_subject_ids':requested, 'request_reason':str(reason), 'max_subjects':max_subjects,
        'subject_evidence':{sid: {'evidence_id':index.loc[sid,'evidence_id'],'source_table':index.loc[sid,'source_table'],
            'source_key':json.loads(index.loc[sid,'source_key_json'])} for sid in requested},
        'request_hashes':keys, 'source_value_hashes':{p['review_subject_id']:p['resolved_source_sha256'] for p in payloads},
        'literature_selection':deepcopy(literature), 'execution_contract':contract,
        'retrieval':{'records':records,'references':references}, 'current_cost':used, 'cache':reuse,
        'deferred_subject_ids':[sid for sid,r in records.items() if r['execution_status'] in {'budget_deferred','not_searched','retrieval_failed'} or
            (r['execution_status']=='retrieved' and r['comparison_status']!='completed') or
            r.get('record',{}).get('partial_retrieval_failure') or
            any(s.get('status')=='budget_exhausted' for s in r.get('record',{}).get('searches',[]))],
        'legacy_pin_action':'unchanged; selected_finding_ids retains its original meaning',
        'semantic_approval':'not_performed', 'replay_scope':'frozen_results_only; not new retrieval or semantic validation'}
    pin['sha256']=object_hash(pin)
    return pin


def replay_review(pin, catalog):
    """Validate frozen typed execution, IDs and literal anchors without any runtime."""
    if pin.get('schema_version')!='literature_subject_execution.v1' or object_hash({k:v for k,v in pin.items() if k!='sha256'})!=pin.get('sha256'):
        raise ValueError('Review execution pin mismatch')
    refs = pin['subject_evidence']
    if set(refs)!=set(pin['requested_subject_ids']) or set(refs)!=set(pin['retrieval']['records']): raise ValueError('Review subject FK mismatch')
    resolved = catalog.resolve([r['evidence_id'] for r in refs.values()])
    for (sid,ref), original in zip(refs.items(),resolved):
        if original['source_ref']!={'table':ref['source_table'],'key':ref['source_key']} or sid!=stable_id('review_subject',[VERSION,ref['source_table'],ref['source_key']]):
            raise ValueError('Review source mismatch')
        expected=pin.get('source_value_hashes',{}).get(sid)
        if expected and expected!=object_hash(_source_value(original)):raise ValueError('Review source value mismatch')
    for source in pin['retrieval']['references']:
        import hashlib
        if 'document' in source and hashlib.sha256(source['document'].encode()).hexdigest()!=source['source_sha256']: raise ValueError('Review source hash mismatch')
        for c in source.get('feature_comparisons',[]):
            if c.get('review_subject_id') not in refs: raise ValueError('Comparison subject FK mismatch')
            quote=c.get('quote','');offset=c.get('source_offset',-1)
            if not quote or source.get('document','')[offset:offset+len(quote)]!=quote or c.get('source_sha256')!=source['source_sha256']: raise ValueError('Comparison anchor mismatch')
            if c.get('measured_relation') or c.get('claim_support_status')!='not_verified': raise ValueError('Unreviewed semantic promotion')
    return deepcopy(pin['retrieval'])


def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--package',required=True);p.add_argument('--evidence-id',required=True)
    a=p.parse_args();root=Path(a.package);catalog=EvidenceCatalog(root)
    plan=read_source(root,PLAN,catalog.catalog['sources'][PLAN])
    ids=plan.loc[plan.evidence_id.eq(a.evidence_id),'review_subject_id'].tolist()
    if not ids:raise ValueError('No review subject for evidence ID')
    tables={'reader/packet':read_source(root,'reader/packet.csv',catalog.catalog['sources']['reader/packet.csv'])}
    config=json.loads((root/'reproducibility/replay_config.json').read_text())
    inputs,study=resolve_subjects(catalog,plan,ids,tables,config['snapshot'],config['literature'])
    print(encode({'subjects':inputs,'study':study,'execution':'not_requested','network_requests':0}))


if __name__=='__main__':main()
