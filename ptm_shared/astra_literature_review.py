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
EXECUTION_PIN = 'references/literature_subject_execution_pin.json'
EXECUTION = 'reader/literature_subject_execution.csv'
SUBJECT_LINKS = 'reader/literature_subject_links.csv'
SUMMARY = 'reader/literature_subject_summary.json'
EXECUTION_GUIDE = 'reader/LITERATURE_SUBJECT_REVIEW.md'
BINDING = 'references/literature_subject_binding.json'
REQUEST_FIELD = 'literature_subject_review'
EXECUTION_ARTIFACTS = [EXECUTION_PIN, EXECUTION, SUBJECT_LINKS, SUMMARY, EXECUTION_GUIDE]
TABLE_KEYS.update({EXECUTION[:-4]: ['review_subject_id'], SUBJECT_LINKS[:-4]: ['link_id']})
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


def review_request(context):
    """Public JSON contract: IDs and budgets, never a caller-supplied file path."""
    import re
    raw = deepcopy((context or {}).get(REQUEST_FIELD) or {'mode': 'not_requested'})
    if not isinstance(raw, dict) or set(raw)-{'mode','requested_subject_ids','request_reason','max_subjects','budget','pin_ref'}:
        raise ValueError('Invalid literature subject review fields')
    mode = raw.get('mode', 'not_requested')
    if mode not in {'not_requested','reuse_frozen','execute'}:
        raise ValueError('Invalid literature subject review mode')
    if mode == 'not_requested':
        if set(raw)-{'mode'}: raise ValueError('Unrequested review cannot carry execution inputs')
        return {'mode': mode}
    ids = raw.get('requested_subject_ids')
    if not isinstance(ids,list) or not ids or any(not isinstance(s,str) or not re.fullmatch(r'review_subject_[0-9a-f]{20}',s) for s in ids) or len(set(ids))!=len(ids):
        raise ValueError('Explicit unique review subject IDs required')
    if not isinstance(raw.get('request_reason'),str) or not raw['request_reason'].strip():
        raise ValueError('Explicit review request reason required')
    if type(raw.get('max_subjects')) is not int or raw['max_subjects']<0:
        raise ValueError('Explicit subject budget required')
    budget=raw.get('budget')
    if not isinstance(budget,dict) or set(budget)!={'max_queries','max_model_calls','max_prompt_bytes'} or any(type(v) is not int or v<0 for v in budget.values()):
        raise ValueError('Explicit query/model/prompt budgets required')
    ref=raw.get('pin_ref')
    if mode=='reuse_frozen':
        if not isinstance(ref,dict) or set(ref)!={'run_id','sha256'} or not re.fullmatch(r'g\d+-[0-9a-f]{32}',str(ref.get('run_id',''))) or not re.fullmatch(r'[0-9a-f]{64}',str(ref.get('sha256',''))):
            raise ValueError('Registered same-order run and pin hash required')
    elif ref is not None: raise ValueError('Execute and frozen pin reuse are distinct requests')
    return raw


def registered_execution(output_root, pin_ref):
    """Resolve only an immutable archive in the already-authorized Order root."""
    from .astra_evidence_catalog import safe_path
    import re
    run=str(pin_ref.get('run_id',''))
    if not re.fullmatch(r'g\d+-[0-9a-f]{32}',run):raise ValueError('Invalid review source run')
    source=safe_path(output_root,'enrichment_free_runs/'+run)
    path=safe_path(source,EXECUTION_PIN)
    manifest=json.loads(safe_path(source,'manifest.json').read_text())
    entry=manifest['files'].get(EXECUTION_PIN)
    if not entry or entry['sha256']!=digest(path) or entry['bytes']!=path.stat().st_size:
        raise ValueError('Registered review pin manifest mismatch')
    pin=json.loads(path.read_text())
    if pin.get('sha256')!=pin_ref.get('sha256') or object_hash({k:v for k,v in pin.items() if k!='sha256'})!=pin.get('sha256'):
        raise ValueError('Registered review pin hash mismatch')
    if json.loads((source/'provenance.json').read_text())['run_id']!=run:
        raise ValueError('Registered review source run mismatch')
    return pin,source


def validate_frozen_request(pin, request, catalog, tables, snapshot, literature, source):
    """Historical execution is replayed as historical, not as current-model cache."""
    replay_review(pin,catalog)
    if pin['requested_subject_ids']!=request['requested_subject_ids']:
        raise ValueError('Review requested subject scope mismatch')
    selection_match=frozen_selection_match(pin['literature_selection'],literature)
    contract=pin.get('execution_contract') or {}
    if (pin.get('review_subject_schema')!=VERSION or not contract.get('code') or
        not contract.get('prompt_version') or not contract.get('retrieval_version') or
        not contract.get('resolved_model') or not contract.get('adapter_sha256')):
        raise ValueError('Review execution provenance incomplete')
    if request['budget']!=contract.get('budget') or request['max_subjects']!=pin.get('max_subjects'):
        raise ValueError('Review execution budget/policy mismatch')
    if set(pin.get('source_value_hashes',{}))!=set(request['requested_subject_ids']):
        raise ValueError('Review source value hashes incomplete')
    # A frozen result may predate newer writer code. Compare source inputs and
    # study against its validated source archive, not today's model/code versions.
    prior=EvidenceCatalog(source)
    replay_review(pin,prior)
    config=json.loads((Path(source)/'reproducibility/replay_config.json').read_text())
    old_tables={'reader/packet':read_source(source,'reader/packet.csv',prior.catalog['sources']['reader/packet.csv'])}
    old_plan=build_plan(prior);new_plan=build_plan(catalog)
    previous,old_study=resolve_subjects(prior,old_plan,request['requested_subject_ids'],old_tables,config['snapshot'],pin['literature_selection'])
    current,new_study=resolve_subjects(catalog,new_plan,request['requested_subject_ids'],tables,snapshot,pin['literature_selection'])
    # source_ref contains a source-file hash, which changes with unrelated rows or
    # summary flags. Canonical key and resolved_source_sha256 bind the used values.
    def semantic(payload):
        payload=deepcopy(payload)
        payload['literature_input']['source_ref']={k:v for k,v in payload['literature_input']['source_ref'].items() if k in {'table','key'}}
        return payload
    if object_hash([semantic(p) for p in previous])!=object_hash([semantic(p) for p in current]) or object_hash(old_study)!=object_hash(new_study):
        raise ValueError('Review source input/study/question mismatch')
    return selection_match


def frozen_selection_match(frozen, current):
    """Cross-environment catalog IDs are not identity; frozen corpus stays historical.

    Only explicit frozen reuse allows matching catalog-only inventory by exact
    document hashes. This does not certify the current live search index or grant
    new export permission, and must never be used for a new-execution cache hit.
    """
    if object_hash(frozen)==object_hash(current):return {'status':'identical_selection_and_corpus'}
    old=frozen.get('documents',[]);new=current.get('documents',[])
    a=[d.get('sha256') for d in old];b=[d.get('sha256') for d in new]
    if not a or any(not h for h in a+b) or len(set(a))!=len(a) or len(set(b))!=len(b) or sorted(a)!=sorted(b):
        raise ValueError('Review literature selection/corpus mismatch')
    snapshots=lambda s:sorted(c.get('version','') for c in s.get('collections',[]) if c.get('version_scope')=='immutable_index_snapshot')
    if not snapshots(frozen) or (snapshots(current) and snapshots(current)!=snapshots(frozen)):
        raise ValueError('Review immutable corpus mismatch')
    return {'status':'same_document_bytes_frozen_historical_corpus_only',
        'current_index_verified':False,'new_execution_cache_compatible':False,
        'frozen_corpus_versions':snapshots(frozen),
        'documents':[{'sha256':d['sha256'],'source_document_id':next(x.get('document_id') for x in old if x['sha256']==d['sha256']),
                      'consumer_document_id':d.get('document_id')} for d in new],
        'export_policy':'retained frozen permission provenance; no new text or permission granted'}


def run_requested_review(directory, tables, context, snapshot, literature, *, output_root, run_id, settings=None):
    """Explicit calculation-stage hook. Writers/resolvers never discover runtimes."""
    request=review_request(context)
    if request['mode']=='not_requested':return None,None
    catalog=EvidenceCatalog(directory)
    if request['mode']=='reuse_frozen':
        pin,source=registered_execution(output_root,request['pin_ref'])
        selection_match=validate_frozen_request(pin,request,catalog,tables,snapshot,literature,source)
        cost={'queries':0,'model_calls':0}
        source_run=request['pin_ref']['run_id']
    else:
        pin=execute_review(catalog,build_plan(catalog),request['requested_subject_ids'],tables,snapshot,literature,
            reason=request['request_reason'],max_subjects=request['max_subjects'],
            settings={**(settings or {}),'budget':request['budget']},cache_root=Path(output_root)/'.astra_stage_cache', run_id=run_id)
        source_run=run_id;cost=pin['current_cost']
        selection_match={'status':'current_explicit_execution'}
    _,summary=project_review(pin,catalog)
    binding={'schema_version':'literature_subject_binding.v1','request':request,
        'requested_mode':request['mode'],'effective_mode':'frozen_results_reused' if request['mode']=='reuse_frozen' else 'explicit_execution',
        'source_run_id':source_run,'consumer_run_id':run_id,'pin_sha256':pin['sha256'],
        'literature_selection_sha256':object_hash(pin['literature_selection']),
        'consumer_literature_selection_sha256':object_hash(literature),'selection_match':selection_match,
        'execution_contract_sha256':object_hash(pin['execution_contract']),
        'current_cost':cost,'requested_scope_status':summary['requested_scope_status'],
        'whole_scope_status':summary['status'],'model_provenance':'frozen_original_execution',
        'fingerprint':object_hash({'request':request,'source_value_hashes':pin['source_value_hashes'],
            'literature':literature,'execution_contract':pin['execution_contract'],'request_hashes':pin['request_hashes']})}
    json_write(Path(directory)/BINDING,binding)
    if summary['requested_scope_status']!='completed':
        json_write(Path(directory)/EXECUTION_PIN,pin)
        raise ValueError('Incomplete requested literature scope; previous success retained')
    attach_review_execution(tables,pin,catalog)
    packet=json.loads(tables['reader/packet'].iloc[0].packet_json)
    packet['literature_subject_execution']['binding']=binding
    tables['reader/packet'].loc[:,'packet_json']=encode(packet)
    return pin,binding


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
    if packet.get('literature_subject_execution'):
        execution=packet['literature_subject_execution']
        cost=execution.get('binding',{}).get('current_cost',{'queries':0,'model_calls':0})
        meta.update(M4='frozen_execution_available', execution_authority=SUMMARY,
            current_execution='see_subject_execution',current_queries=cost['queries'],current_model_calls=cost['model_calls'],
            requested_scope_status=execution['summary']['requested_scope_status'],
            whole_scope_status=execution['summary']['status'],
            plan_row_semantics='not_requested is eligibility-plan state; execution table takes precedence')
    json_write(root/META, meta)
    (root/GUIDE).write_text('''# 전체 근거의 문헌 검토 대상 계획 (M3)

[전체 대상](literature_review_subjects.csv) · [계획/분모](literature_review_plan.json) · [원본 조회](EVIDENCE_ACCESS.md) · [질문·시간·인용](FULL_EVIDENCE.md)

선정 findings는 요약입니다. 미선정 관측, 보류 원본, protein, detection, method, no-call도 별도 typed 대상으로 접근합니다.
이 계획은 새 검색/LLM 비교를 수행하지 않습니다. 각 행의 not_requested는 대상 계획 상태이며 별도 실행표를 덮어쓰지 않습니다.
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
    if packet.get('literature_subject_execution'):
        text=(root/GUIDE).read_text().replace('M4 실제 새 검색/비교는 미수행입니다.',
            '이번 M4의 실제 검색/비교와 미실행 범위는 [별도 실행 기록](LITERATURE_SUBJECT_REVIEW.md)을 따릅니다.')
        (root/GUIDE).write_text(text,encoding='utf-8')
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
                   max_subjects, settings=None, retriever=None, llm=None, cache_root=None, run_id=None):
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
    if settings.get('runtime_identity'):
        contract['runtime_identity']=deepcopy(settings['runtime_identity'])
    contract['publication_policy']='require_complete_requested_scope; whole population remains partial'
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
            result = retrieve_finding_literature([payload],retriever,study,llm=llm,policy=remaining,
                trace_directory=cache_root, trace_context={'run_id':run_id,
                    'stage_id':'literature_review_subject','request_sha256':keys[sid],
                    'evidence_refs':[{'evidence_id':index.loc[sid,'evidence_id'],
                        'source_table':index.loc[sid,'source_table'],
                        'source_key':json.loads(index.loc[sid,'source_key_json'])}]})
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
    deferred=[]
    for sid,r in pin['retrieval']['records'].items():
        raw=r.get('record',{})
        if (r['execution_status'] in {'budget_deferred','not_searched','retrieval_failed','unsupported_subject_type'} or
            (r['execution_status']=='retrieved' and r['comparison_status']!='completed') or
            raw.get('partial_retrieval_failure') or any(s.get('status')=='budget_exhausted' for s in raw.get('searches',[]))):
            deferred.append(sid)
    if set(deferred)!=set(pin['deferred_subject_ids']):raise ValueError('Review deferred status mismatch')
    return deepcopy(pin['retrieval'])


def project_review(pin, catalog):
    """Frozen M4 results, separately from the unchanged whole eligibility plan.

    Counts describe actual retrieval/comparison, never semantic approval. A chunk
    shared by subjects is counted once and linked N:M by its pinned identity.
    """
    result = replay_review(pin, catalog)
    records = result['records']
    sources = {}
    for ref in result['references']:
        key = (ref.get('collection'), ref.get('collection_version'), ref.get('source_id'), ref['source_sha256'])
        sources[key] = ref
    rows, links = [], []
    for sid in pin['requested_subject_ids']:
        r = records[sid]; raw = r.get('record', {}); evidence = pin['subject_evidence'][sid]
        rows.append({'review_subject_id': sid, **{k:v for k,v in evidence.items() if k != 'source_key'},
            'source_key_json': encode(evidence['source_key']), 'execution_status': r['execution_status'],
            'comparison_status': r['comparison_status'], 'semantic_status': r['semantic_status'],
            'deferred': sid in pin['deferred_subject_ids'], 'request_reason': pin['request_reason'],
            'retrieved_chunks': raw.get('retrieved_count', 0),
            'exclusion_reasons_json': encode(raw.get('excluded_comparisons', [])),
            'record_json': encode(r), 'schema_version': pin['schema_version']})
        for c in raw.get('coverage', []):
            key = (c.get('collection'), c.get('collection_version'), c.get('source_id'), c['source_sha256'])
            if key not in sources: raise ValueError('Review coverage/source FK mismatch')
            ref = sources[key]
            links.append({'link_id': stable_id('review_link', [sid, key]), 'review_subject_id': sid,
                'evidence_id': evidence['evidence_id'], 'source_key': stable_id('lit_source', list(key)),
                'collection': key[0], 'collection_version': key[1], 'chunk_id': key[2], 'source_sha256': key[3],
                'export_status': ref['export_status'], 'schema_version': pin['schema_version']})
    docs = pin['literature_selection'].get('documents', [])
    read_ids = {str((s.get('metadata') or {}).get('doc_id', (s.get('metadata') or {}).get('document_id'))) for s in sources.values()}
    external = {d['sha256'] for d in docs if str(d.get('document_id')) in read_ids and
                (d.get('DOI') or d.get('doi') or d.get('PMID') or d.get('pmid')) and
                d.get('doc_type') not in {'user_method_note', 'same_experiment_manuscript'} and
                d.get('role') != 'user_supplied_research_attachment'}
    requested = len(records); population = len(catalog.index.loc[catalog.index.evidence_type.ne('disposition')])
    comparisons = {object_hash(c) for s in result['references'] for c in s.get('feature_comparisons', [])}
    summary = {'schema_version': pin['schema_version'], 'pin_sha256': pin['sha256'],
        'status': 'partial' if pin['deferred_subject_ids'] or requested < population else 'completed',
        'requested_scope_status': 'partial' if pin['deferred_subject_ids'] else 'completed',
        'eligible_representation_count': population, 'requested_subjects': requested,
        'not_requested_subjects': population-requested, 'deferred_subject_ids': pin['deferred_subject_ids'],
        'execution_status_counts': dict(Counter(r['execution_status'] for r in records.values())),
        'comparison_executed_subjects': sum(r['comparison_status']=='completed' for r in records.values()),
        'retrieved_unique_chunks': len(sources), 'retrieved_documents': len(read_ids),
        'external_publications_with_retrieved_chunks': len(external), 'read_scope': 'retrieved_chunks_only; not whole papers',
        'exported_anchored_proposals': len(comparisons), 'semantically_approved_subjects': 0,
        'semantic_status': 'review_required; source anchors are not scientific approval',
        'external_astra_review_status': 'not_recorded', 'current_cost': pin['current_cost'],
        'model': pin['execution_contract']['resolved_model'],
        'literature_selection_sha256': object_hash(pin['literature_selection']),
        'publication_policy': 'require_complete_requested_scope; whole population remains partial',
        'limits': 'Overlapping representations; no independent observation count. Scientific restrictions and legacy literature unchanged.'}
    frames = {EXECUTION[:-4]: pd.DataFrame(rows, columns=['review_subject_id','evidence_id','source_table','source_key_json',
        'execution_status','comparison_status','semantic_status','deferred','request_reason','retrieved_chunks',
        'exclusion_reasons_json','record_json','schema_version']),
        SUBJECT_LINKS[:-4]: pd.DataFrame(links, columns=['link_id','review_subject_id','evidence_id','source_key',
        'collection','collection_version','chunk_id','source_sha256','export_status','schema_version']).drop_duplicates('link_id')}
    return frames, summary


def attach_review_execution(tables, pin, catalog):
    frames, summary = project_review(pin, catalog)
    from .literature_cards import _literature_cards
    packet = json.loads(tables['reader/packet'].iloc[0].packet_json)
    packet['literature_subject_execution'] = {'pin_path': EXECUTION_PIN, 'summary': summary,
        'execution_table': EXECUTION, 'source_links': SUBJECT_LINKS, 'guide': EXECUTION_GUIDE,
        'reference_cards': _literature_cards(pin['retrieval']['references']),
        'scope': 'explicit typed subjects; legacy selected findings/results unchanged'}
    packet['authoring_rules']['literature_review_subjects'] = (
        'Use whole review plan and explicit subject execution, not summary selection, to find literature. '
        'Cite review_subject_id + M1 evidence_id/source key + pinned chunk/source hash. '
        'Only exported source anchors are inspectable offline; metadata-only internal retrieval is recorded separately. '
        'Proposed relationships are not verified claims. Preserve withheld/no-call/localization and readout restrictions. '
        'Unrequested/deferred subjects are not reviewed. External Astra review is not_recorded.')
    # Preserve old question matching and finding literature status. This is an
    # independent access/execution extension, not a new question-routing engine.
    packet['literature_review_plan']['limits'] = 'Eligibility plan only; actual typed execution is in literature_subject_execution. Legacy results preserved.'
    packet['literature_review_plan']['execution'] = 'see_literature_subject_execution'
    packet['evidence_access']['limits'] = 'Whole evidence access and M2 links; actual typed literature execution is explicitly bounded and recorded separately.'
    tables['reader/packet'].loc[:, 'packet_json'] = encode(packet)
    tables.update(frames)
    return summary


def write_review_execution(directory, tables, pin, *, source_root=None):
    """Writer and offline replay share this projection; no RAG/model discovery."""
    from .astra_package import write_tables
    root=Path(directory); catalog=EvidenceCatalog(source_root or root)
    frames,summary=project_review(pin,catalog)
    metadata=write_tables(frames,root)
    if source_root is None:
        path=root/'reproducibility/data_dictionary.json';dictionary=json.loads(path.read_text())
        dictionary.update(metadata);json_write(path,dictionary)
    path=root/CATALOG;content=json.loads(path.read_text())
    for name,descriptor in metadata.items():
        content['sources'][name]={**descriptor,'sha256':digest(root/name),'descriptor_schema_version':pin['schema_version'],
            'availability':'available' if descriptor['rows'] else 'available_empty','role':'literature_subject_execution',
            'indexed':False,'access':'registered_source_and_canonical_key','independent_observation_count':None}
    content['catalog_id']=object_hash({k:v for k,v in content.items() if k!='catalog_id'});json_write(path,content)
    (root/'references').mkdir(exist_ok=True)
    json_write(root/EXECUTION_PIN,pin);json_write(root/SUMMARY,summary)
    lines=['# 전체 근거 중 명시적으로 실행한 문헌 검토 (M4)',
        '[대상별 상태/원본 key](literature_subject_execution.csv) · [subject→문헌 구간](literature_subject_links.csv) · '
        '[분모와 실행 요약](literature_subject_summary.json) · [고정 결과](../'+EXECUTION_PIN+') · '
        '[전체 대상 계획](LITERATURE_REVIEW_PLAN.md) · [원본 조회](EVIDENCE_ACCESS.md) · [질문·시간·인용](FULL_EVIDENCE.md)',
        f"전체 {summary['eligible_representation_count']}개 표현 중 {summary['requested_subjects']}개 요청; "
        f"비교 실행 {summary['comparison_executed_subjects']}개. 전체 검토는 {summary['status']}, 요청 범위는 {summary['requested_scope_status']}입니다.",
        f"실제 반환 본문은 외부 논문 {summary['external_publications_with_retrieved_chunks']}편을 포함한 "
        f"{summary['retrieved_unique_chunks']}개 고유 구간입니다. 논문 전체를 읽었다는 뜻은 아닙니다.",
        f"Source anchor 검사와 의미 승인은 다릅니다. 의미 승인 대상 {summary['semantically_approved_subjects']}건, 외부 Astra 검토 로그 {summary['external_astra_review_status']}. "
        '검색 실패/no_hit/미실행을 반대 결과로 해석하지 마세요. 같은 실험 첨부물과 방법 메모는 독립 외부 검증이 아닙니다.',
        'Local RAG에서 읽은 범위와 패키지 재배포 허용 범위는 별도입니다. metadata_only 구간은 hash와 위치만 참조하고 원문을 읽었다고 주장하지 마세요. '
        '문헌 결과는 localization 미측정, 기술 반복, no-call 및 protein/method readout의 제한을 해소하지 않습니다.',
        '| review subject | 실행 | 비교 | 의미 상태 | 원본 evidence |','|---|---|---|---|---|']
    for r in frames[EXECUTION[:-4]].itertuples():
        lines.append(f'| {r.review_subject_id} | {r.execution_status} | {r.comparison_status} | {r.semantic_status} | {r.evidence_id} |')
    (root/EXECUTION_GUIDE).write_text('\n\n'.join(lines[:6])+'\n\n'+'\n'.join(lines[6:])+'\n',encoding='utf-8')
    binding=json.loads(tables['reader/packet'].iloc[0].packet_json).get('literature_subject_execution',{}).get('binding')
    if binding:
        with (root/EXECUTION_GUIDE).open('a',encoding='utf-8') as handle:
            handle.write(f"\n원 실행 run: {binding['source_run_id']}; 소비 run: {binding['consumer_run_id']}. "
                f"이번 소비의 신규 query/model 호출: {binding['current_cost']['queries']}/{binding['current_cost']['model_calls']}. "
                'summary.current_cost와 pin의 모델·corpus는 고정된 원 실행 기록입니다. 현재 환경의 새 검색이나 모델 결과가 아닙니다. '
                '[요청·재사용 대응](../'+BINDING+').\n')
    return [EXECUTION,SUBJECT_LINKS,SUMMARY,EXECUTION_GUIDE,EXECUTION_PIN]


def validate_execution(catalog, *, required=False):
    path=catalog.root/EXECUTION_PIN
    packet=json.loads(read_source(catalog.root,'reader/packet.csv',catalog.catalog['sources']['reader/packet.csv']).iloc[0].packet_json)
    required=required or bool(packet.get('literature_subject_execution'))
    if not path.is_file():
        if required:raise ValueError('Required literature subject execution pin missing')
        return {'available':False,'reason':'legacy_or_unrequested'}
    if any(not (catalog.root/name).is_file() for name in EXECUTION_ARTIFACTS):raise ValueError('Required literature subject artifacts missing')
    pin=json.loads(path.read_text());frames,summary=project_review(pin,catalog)
    if summary['requested_scope_status']!='completed':raise ValueError('Incomplete requested literature scope')
    for name,expected in frames.items():
        actual=read_source(catalog.root,name+'.csv',catalog.catalog['sources'][name+'.csv'])
        if encode(actual.to_dict('records'))!=encode(expected.to_dict('records')):raise ValueError('Review execution projection mismatch: '+name)
    if json.loads((catalog.root/SUMMARY).read_text())!=summary:raise ValueError('Review execution summary mismatch')
    if packet['literature_subject_execution']['summary']!=summary:raise ValueError('Review execution packet mismatch')
    binding_path=catalog.root/BINDING
    context_path=catalog.root/'study/study_context.json'
    request=review_request(json.loads(context_path.read_text())) if context_path.is_file() else {'mode':'not_requested'}
    if request['mode']!='not_requested' and not binding_path.is_file():raise ValueError('Required review request binding missing')
    if binding_path.is_file():
        binding=json.loads(binding_path.read_text())
        if packet['literature_subject_execution'].get('binding')!=binding:raise ValueError('Review execution binding mismatch')
        if binding['pin_sha256']!=pin['sha256'] or binding['execution_contract_sha256']!=object_hash(pin['execution_contract']) or binding['literature_selection_sha256']!=object_hash(pin['literature_selection']):
            raise ValueError('Review execution provenance binding mismatch')
        if binding['request']['requested_subject_ids']!=pin['requested_subject_ids']:raise ValueError('Review request scope mismatch')
        if request['mode']!='not_requested' and request!=binding['request']:raise ValueError('Review context/request binding mismatch')
        selection_path=catalog.root/'references/literature_pin.json'
        if selection_path.is_file() and object_hash(json.loads(selection_path.read_text()))!=binding['consumer_literature_selection_sha256']:
            raise ValueError('Review consumer literature selection mismatch')
        provenance=catalog.root/'provenance.json'
        if provenance.is_file() and json.loads(provenance.read_text())['run_id']!=binding['consumer_run_id']:raise ValueError('Review consumer run mismatch')
    if required:
        authoring=json.loads((catalog.root/'reader/authoring_packet.json').read_text())
        if authoring.get('literature_subject_execution')!=packet['literature_subject_execution']:
            raise ValueError('Review authoring packet mismatch')
    return {'available':True,**summary}


def restore_execution(tables, source, *, consumer_run_id=None):
    """Restore the archived consumer binding; no runtime, current clock or model."""
    root=Path(source);path=root/EXECUTION_PIN
    context_path=root/'study/study_context.json'
    requested=context_path.is_file() and review_request(json.loads(context_path.read_text()))['mode']!='not_requested'
    if not path.is_file():
        if requested:raise ValueError('Requested literature execution missing from archive')
        return None
    catalog=EvidenceCatalog(root);validate_execution(catalog,required=requested)
    pin=json.loads(path.read_text());attach_review_execution(tables,pin,catalog)
    if (root/BINDING).is_file():
        packet=json.loads(tables['reader/packet'].iloc[0].packet_json)
        binding=json.loads((root/BINDING).read_text())
        if consumer_run_id:
            binding.update(consumer_run_id=consumer_run_id, effective_mode='frozen_results_reused', current_cost={'queries':0,'model_calls':0})
        packet['literature_subject_execution']['binding']=binding
        tables['reader/packet'].loc[:,'packet_json']=encode(packet)
    return pin


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
