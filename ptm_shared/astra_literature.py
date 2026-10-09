"""Finding literature bridge: existing retrieval, immutable pins, reader projection.

This stage never selects findings or recalculates measurement/scientific tables.
A literal source anchor validates a quotation, not the model's biological judgment.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pandas as pd
from .astra_inputs import stable_id
from .generic_workflow import object_hash, json_write
from .finding_literature import cards_for_selected_findings, retrieve_finding_literature, VERSION as RETRIEVAL_VERSION, PROMPT_VERSION
from .literature_cards import _literature_cards

VERSION = 'astra_finding_literature.v1'
TABLE_KEYS = {'reader/literature_search': ['finding_id'], 'reader/literature_sources': ['source_key'],
              'reader/literature_comparisons': ['comparison_id']}
ARTIFACTS = ['reader/LITERATURE.md', 'reader/literature_summary.json', 'references/finding_literature_pin.json']


def inputs(tables, snapshot, literature):
    packet = json.loads(tables['reader/packet'].iloc[0].packet_json)
    ids = tables['reader/findings'].finding_id.tolist()
    cards = cards_for_selected_findings(packet['reader_cards'], ids, key='finding_id')
    if [c['finding_id'] for c in cards] != ids:
        raise ValueError('Literature selected finding identity/order mismatch')
    original = (snapshot or {}).get('original', {})
    context = deepcopy(original.get('analysis_context') or {})
    # Retain the stored whole context and original question; no dose/time inference.
    study = {k: context[k] for k in ('species','cell_type','cell_model','treatment','special_conditions',
        'biological_question','pre_treatment','acquisition_metadata','acquisition','study_design') if k in context}
    study['canonical_study'] = packet.get('canonical_study_design', {})
    study['species'] = study.get('species') or original.get('species') or study['canonical_study'].get('study', {}).get('species')
    study['original_questions'] = packet['original_questions']
    study['replication'] = packet['study_metadata_provenance']['replication_declaration']
    arms = study['canonical_study'].get('arms', [])
    study['recorded_treatments'] = [a for a in arms if a.get('treatments')]
    study['treatment'] = study.get('treatment') or '; '.join(t['name'] for a in arms for t in a.get('treatments', []))
    study['recorded_conditions_query'] = json.dumps({k:study[k] for k in ('recorded_treatments','pre_treatment','special_conditions') if k in study}, ensure_ascii=False)
    for c in cards:
        c['literature_input'] = {k:c.get(k) for k in ('finding_id','card_id','form_id','taxon_ids','feature_identity',
            'feature_label','source_bindings','trajectory','interpretation_limits','opposite_signed_observations')}
        c['literature_input']['observed_grid'] = [{k:b.get(k) for k in ('target_label','reference_label','time_min','reference_time_min','localization_status')} for b in c['source_bindings']]
        c['literature_input']['axis_contract'] = packet['quantitation_estimator_contract']
        comparison_context={'time':c['literature_input']['observed_grid'],
            'readout':packet['quantitation_estimator_contract']['axis_fields'],
            'perturbation':study['recorded_treatments']}
        recorded_dose=(context.get('acquisition_metadata') or {}).get('insulin_concentration')
        if recorded_dose is not None:comparison_context['insulin_dose']=recorded_dose
        c['literature_input']['comparison_context']=comparison_context
    return cards, study


class _UnavailableRetriever:
    def __init__(self, names, reason): self.collection_names, self.reason = names, reason
    def query(self, *args, **kwargs): raise RuntimeError(self.reason)


def _runtime(literature, settings):
    """Load only the existing RAG/LLM boundaries. Never discover other collections."""
    names = [c['chromadb_name'] for c in literature.get('collections', []) if c.get('chromadb_name')]
    if not names: return _UnavailableRetriever([], 'no_resolved_pinned_collection'), None, {'status':'not_needed_no_pinned_collections'}
    try:
        from report_generation.core.rag_retriever import RAGRetriever
        retriever = RAGRetriever(collection_names=names)
    except ImportError:
        return _UnavailableRetriever(names, 'rag_runtime_dependency_unavailable'), None, {'status':'rag_runtime_dependency_unavailable'}
    try:
        from common.llm_client import LLMClient
        llm = LLMClient(provider=settings.get('llm_provider', 'ollama'), model=settings.get('llm_model'))
        model = {'provider':llm.provider, 'model':llm.model, 'prompt_version':PROMPT_VERSION}
        if not llm.is_available(): return retriever, None, {**model, 'status':'model_unavailable'}
        return retriever, llm, {**model, 'status':'available'}
    except ImportError:
        return retriever, None, {'status':'model_runtime_dependency_unavailable'}


def collect(tables, snapshot, literature, *, settings=None, cache_root=None, retriever=None, llm=None):
    """Reuse the report function and checkpoint cache, then seal exported evidence.

    Only a complete, versioned result is cached. Failed/partial/model-unavailable
    searches can be retried; their frozen package records still replay exactly.
    """
    cards, study = inputs(tables, snapshot, literature)
    settings = settings or {}
    options = ((snapshot or {}).get('original', {}).get('report_options') or {})
    policy = (options.get('report_config') or {}).get('finding_review_policy')
    model = {'provider':getattr(llm,'provider',None),'model':getattr(llm,'model',None), 'prompt_version':PROMPT_VERSION,
             'status':'injected_runtime' if llm else 'not_available'}
    if retriever is None: retriever, llm, model = _runtime(literature, {**options, **settings})
    allowed = {c['chromadb_name'] for c in literature.get('collections', []) if c.get('chromadb_name')}
    if set(retriever.collection_names) != allowed: raise ValueError('Retriever scope differs from pinned selection')
    request = {'version':VERSION,'retrieval_version':RETRIEVAL_VERSION,'cards':cards,'study':study,
               'literature':literature,'policy':policy,'model':model,
               'transport_code_sha256':_transport_hash(retriever),
               'code':{n:hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest()
                       for n in ('astra_literature.py','finding_literature.py','literature_cards.py')}}
    fingerprint = object_hash(request)
    def run():
        result = retrieve_finding_literature(cards,retriever,study,llm=llm,policy=policy)
        for c in cards:
            r = result['records'][c['finding_id']]
            r['finding_id'] = c['finding_id']
            r['source_row_ids'] = [b['adapter_row_id'] for b in c['source_bindings']]
            if not allowed:
                r['reason'] = ('pinned_collection_search_name_missing' if literature.get('collections') else
                               'explicit_empty_selection' if literature.get('requested_ids') == [] else 'no_active_collections_in_frozen_selection')
            if llm is None and r['retrieved_count']: r['review_reason'] = model['status']
        return result
    # A missing resource or an unversioned collection is not a permanent no-hit.
    class Incomplete(Exception):
        def __init__(self, result): self.result = result
    def complete():
        result = run()
        if any(r.get('status') in {'retrieval_failed','budget_exhausted','retrieved_comparison_pending'} or
               r.get('partial_retrieval_failure') for r in result['records'].values()): raise Incomplete(result)
        return result
    versioned = bool(allowed) and all(c.get('version') and c.get('version_scope')=='immutable_index_snapshot' for c in literature.get('collections', []))
    reuse = {'status':'not_cached','reason':'no_versioned_searchable_collection' if not allowed else 'index_version_not_immutable'}
    if cache_root and versioned:
        from .evidence_stage_cache import cached_stage
        try: result,reuse = cached_stage(cache_root,'finding_literature',fingerprint,complete)
        except Incomplete as e: result=e.result;reuse={'status':'not_cached','reason':'incomplete_retryable_result'}
    else: result=run()
    exported = _export_result(result,literature)
    pin = {'schema_version':VERSION,'input_sha256':object_hash({'cards':cards,'study':study,'literature':literature}),
           'request_sha256':fingerprint,'selected_finding_ids':[c['finding_id'] for c in cards],
           'literature_selection':deepcopy(literature),'retrieval':exported,'model':model,'cache':reuse,
           'documents':document_inventory(literature, exported), 'replay_scope':'frozen_retrieval_and_quote_anchored_proposals_not_semantic_validation'}
    pin['sha256']=object_hash(pin)
    return pin



def _transport_hash(retriever):
    import inspect
    try:
        path=Path(inspect.getfile(type(retriever)))
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except (TypeError,OSError):return None



def _document_id(metadata):
    # Existing document_tasks stores doc_id; newer inventories use document_id.
    values={str(metadata[k]) for k in ('document_id','doc_id') if metadata.get(k) is not None}
    return next(iter(values)) if len(values)==1 else None


def document_inventory(literature, result=None):
    read_ids={str(_document_id(r.get("metadata") or {})) for r in (result or {}).get("references",[])}
    return [{**d, 'internal_search_status':('indexed_catalog_record' if d.get('source_status')=='indexed' else 'not_indexed_or_not_recorded'),
             'read_scope':'retrieved_chunks_only' if str(d.get('document_id')) in read_ids else 'not_read_by_finding_stage',
             'restriction':None if str(d.get('document_id')) in read_ids else 'attachment_not_indexed_or_no_retrieved_chunk; no_external_paper_read_inferred_from_citations',
             'package_content_status':d.get('content_status','unknown')} for d in literature.get('documents', [])]


def _export_result(result, literature):
    """PDF permission and internal retrieval are separate. Never export unpermitted spans/prompts."""
    result=deepcopy(result)
    permissions={str(d['document_id']):d.get('evidence_export_permission',
                 'permitted' if d.get('content_status')=='full_text_included' else 'unknown') for d in literature.get('documents', [])}
    permitted_collections={c['chromadb_name'] for c in literature.get('collections', []) if c.get('evidence_export_permission')=='permitted'}
    restricted=False
    for ref in result.get('references', []):
        meta=ref.get('metadata') or {}
        permitted=ref.get('collection') in permitted_collections or permissions.get(str(_document_id(meta)))=='permitted'
        ref['source_sha256']=hashlib.sha256(str(ref.get('document','')).encode()).hexdigest()
        ref['read_scope']=meta.get('content_scope','retrieved_chunk_scope_unknown')
        ref['evidence_location']={k:meta[k] for k in ('page','section','chunk_index','source') if k in meta}
        ref['evidence_location']['chunk_id']=ref.get('source_id')
        ref['metadata']={k:v for k,v in meta.items() if k in {'document_id','doc_id','collection_id','title','authors','year','journal','doi','pmid','page','section','chunk_index','content_scope','doc_type'}}
        ref['export_status']='evidence_excerpt_included' if permitted else 'metadata_only_export_permission_unconfirmed'
        if not permitted:
            restricted=True
            for k in ('document','reader_excerpt','excerpt','feature_comparisons'): ref.pop(k,None)
    if restricted:
        for r in result['records'].values():
            r.pop('resolved_prompt',None);r.pop('comparison_generation',None)
            r['comparison_export_status']='restricted_source_text_not_exported'
    return result


def apply(tables, pin, snapshot, literature):
    """Deterministic reader projection; replay enters here without a retriever/LLM."""
    if object_hash({k:v for k,v in pin.items() if k!='sha256'}) != pin.get('sha256'): raise ValueError('Literature pin hash mismatch')
    cards,study=inputs(tables,snapshot,literature)
    if object_hash({'cards':cards,'study':study,'literature':literature}) != pin['input_sha256']: raise ValueError('Literature pin input mismatch')
    if [c['finding_id'] for c in cards] != pin['selected_finding_ids']: raise ValueError('Literature finding order mismatch')
    result=pin['retrieval']; records=result['records']; sources=[]; comparisons=[]
    for ref in result.get('references',[]):
        sid=stable_id('lit_source',[ref.get('collection'),ref.get('collection_version'),ref.get('source_id'),ref['source_sha256']])
        copy={k:v for k,v in ref.items() if k!='feature_comparisons'}
        if not any(r['source_key']==sid for r in sources): sources.append({'source_key':sid,'source_json':json.dumps(copy,ensure_ascii=False,sort_keys=True),'schema_version':VERSION})
        for c in ref.get('feature_comparisons',[]):
            fid=c.get('finding_id') or c.get('reader_feature_id')
            if fid not in records: raise ValueError('Literature comparison finding FK mismatch')
            cid=stable_id('lit_comparison',[fid,sid,c])
            comparisons.append({'comparison_id':cid,'finding_id':fid,'source_key':sid,
                'relationship':c['relationship'],'comparison_json':json.dumps(c,ensure_ascii=False,sort_keys=True),'schema_version':VERSION})
    search=[{'finding_id':fid,'status':records[fid]['status'],'record_json':json.dumps(records[fid],ensure_ascii=False,sort_keys=True),
             'schema_version':VERSION} for fid in pin['selected_finding_ids']]
    tables.update({'reader/literature_search':pd.DataFrame(search,columns=['finding_id','status','record_json','schema_version']),
        'reader/literature_sources':pd.DataFrame(sources,columns=['source_key','source_json','schema_version']),
        'reader/literature_comparisons':pd.DataFrame(comparisons,columns=['comparison_id','finding_id','source_key','relationship','comparison_json','schema_version']).drop_duplicates('comparison_id')})
    summary={'schema_version':VERSION,'selected_findings':len(cards), 'collections':len(literature.get('collections',[])),
        'source_chunks_read':len(sources),'publications_read':len({(r.get('doi') or r.get('pmid')) for r in result.get('references',[]) if r.get('doi') or r.get('pmid')}),
        'anchored_proposals':len(tables['reader/literature_comparisons']),
        'internal_compared_findings':sum(bool(r.get('comparisons')) for r in records.values()),
        'comparison_executed_findings':sum(r.get('comparison_execution',{}).get('status')=='completed' for r in records.values()),
        'comparison_failed_findings':sum(r.get('comparison_execution',{}).get('status')=='failed' for r in records.values()),
        'documents_read':len({str(_document_id(r.get('metadata') or {})) for r in result.get('references',[]) if _document_id(r.get('metadata') or {}) is not None}),
        'export_restricted_chunks':sum(r.get('export_status')=='metadata_only_export_permission_unconfirmed' for r in result.get('references',[])),
        'semantically_verified_comparable_findings':0,'comparison_validation':'source_anchors_only_semantic_review_required',
        'status_counts':dict(pd.Series([r['status'] for r in search],dtype='str').value_counts().items()),
        'model':pin['model'],'cache':pin['cache'],'cost':result['cost'],
        'read_scope_counts':dict(pd.Series([r.get('read_scope','unknown') for r in result.get('references',[])],dtype='str').value_counts().items()),
        'independent_validation':'not_performed','literature_pin_sha256':pin['sha256']}
    packet=json.loads(tables['reader/packet'].iloc[0].packet_json)
    packet['literature_comparison_status']='source_anchored_review_pending' if comparisons else ('internal_comparison_performed_export_restricted' if summary['internal_compared_findings'] else 'retrieved_comparison_pending' if sources else 'not_performed_no_accessible_evidence')
    packet['literature']={'status_authority':'reader/literature_search.csv; inherited card status describes original card generation only',
                          'summary':summary,'pin':pin,'reference_cards':_literature_cards(result.get('references',[])),
                          'finding_records':records,'source_table':'reader/literature_sources.csv', 'comparison_table':'reader/literature_comparisons.csv'}
    summary['status']=packet['literature_comparison_status']
    packet['coverage_inventory']['literature_comparison']=summary['status']
    packet['mode']='citation_complete' if packet['literature']['reference_cards'] else 'data_only'
    for q in packet['research_question_evidence_map']['questions']:
        matching=[records[f] for f in q['finding_ids']]
        q['literature_comparison_status']=packet['literature_comparison_status'] if matching else 'no_linked_findings'
        q['missing_evidence']=[x for x in q.get('missing_evidence',[]) if not x.startswith(('No literature comparison','Literature source/condition comparability'))] + ['Literature source/condition comparability and semantic interpretation require review; independent perturbation validation not performed.']
        q['literature_evidence']={'finding_ids':q['finding_ids'],'search_statuses':{r['finding_id']:r['status'] for r in matching},
            'answer_scope':'Only source-bound external context; agreement/disagreement proposals require semantic review. No independent validation.'}
    tables['reader/packet'].loc[:,'packet_json']=json.dumps(packet,ensure_ascii=False,sort_keys=True)
    validate(tables)
    return summary


def validate(tables):
    if not set(TABLE_KEYS)<=set(tables): raise ValueError('Incomplete literature tables')
    packet=json.loads(tables['reader/packet'].iloc[0].packet_json);pin=packet['literature']['pin']
    if object_hash({k:v for k,v in pin.items() if k!='sha256'})!=pin['sha256']:raise ValueError('Literature pin hash mismatch')
    findings=set(tables['reader/findings'].finding_id)
    rows={r.finding_id:set(json.loads(r.source_row_ids_json)) for r in tables['reader/findings'].itertuples()}
    if tables['reader/literature_search'].finding_id.tolist()!=tables['reader/findings'].finding_id.tolist():raise ValueError('Literature search finding order/FK mismatch')
    cards={c['finding_id']:c for c in packet['reader_cards'] if c.get('finding_id')}
    for r in tables['reader/literature_search'].itertuples():
        record=json.loads(r.record_json)
        if set(record['source_row_ids'])!=rows[r.finding_id] or record!=pin['retrieval']['records'][r.finding_id]:raise ValueError('Literature search/source row mismatch')
        observation=record['search_input']['observation']
        if observation['source_bindings']!=cards[r.finding_id]['source_bindings'] or observation['feature_identity']!=cards[r.finding_id]['feature_identity']:
            raise ValueError('Literature input changed measured evidence')
    sources={r.source_key:json.loads(r.source_json) for r in tables['reader/literature_sources'].itertuples()}
    for sid,s in sources.items():
        if sid!=stable_id('lit_source',[s.get('collection'),s.get('collection_version'),s.get('source_id'),s['source_sha256']]):raise ValueError('Literature source identity mismatch')
        if 'document' in s and hashlib.sha256(s['document'].encode()).hexdigest()!=s['source_sha256']:raise ValueError('Literature source digest mismatch')
    for r in tables['reader/literature_comparisons'].itertuples():
        if r.finding_id not in findings or r.source_key not in sources:raise ValueError('Literature comparison FK mismatch')
        c=json.loads(r.comparison_json);s=sources[r.source_key];text=s.get('document','');quote=c['quote']
        if not quote or text[c['source_offset']:c['source_offset']+len(quote)]!=quote or hashlib.sha256(text.encode()).hexdigest()!=c['source_sha256']:raise ValueError('Literature quote/source mismatch')
        if c['measured_relation'] or c['claim_support_status']!='not_verified':raise ValueError('Unreviewed literature promotion')
    return {'finding_records':len(rows),'source_chunks':len(sources),'source_anchor_validation':'passed','semantic_validation':'not_performed'}


def write(directory,tables):
    p=Path(directory);(p/'references').mkdir(parents=True,exist_ok=True);(p/'reader').mkdir(parents=True,exist_ok=True)
    packet=json.loads(tables['reader/packet'].iloc[0].packet_json);data=packet['literature']
    json_write(p/'references/finding_literature_pin.json',data['pin']);json_write(p/'reader/literature_summary.json',data['summary'])
    lines=['# 선정 관측의 문헌 검색과 비교', '[주요 관측](READ_ME.md) · [검색 기록](literature_search.csv) · [출처](literature_sources.csv) · [비교](literature_comparisons.csv)',
        '검색 성공·인용문 일치·생물학적 판단 검증은 서로 다릅니다. 제안된 일치/상이는 원문 의미 검토 전까지 배경 근거로 유지합니다. 미검색은 반대 결과가 아닙니다. 본문/PDF 재배포 여부는 내부 검색 여부와 별도입니다.',
        '```json\n'+json.dumps(data['summary'],ensure_ascii=False,indent=2)+'\n```']
    comps=tables['reader/literature_comparisons']; refs={r.source_key:json.loads(r.source_json) for r in tables['reader/literature_sources'].itertuples()}
    for card in [c for c in packet['reader_cards'] if c.get('finding_id')]:
        r=data['finding_records'][card['finding_id']]
        lines.extend([f"## {card['feature_label']} — {card['finding_id']}",f"검색: {r['status']}; 사유: {r.get('reason',r.get('review_reason','none'))}. 원본: {', '.join(r['source_row_ids'])}"])
        for row in comps.loc[comps.finding_id.eq(card['finding_id'])].itertuples():
            c=json.loads(row.comparison_json);ref=refs[row.source_key]
            lines.extend([f"{row.comparison_id}: {ref.get('title')} ({ref.get('year')}); DOI={ref.get('doi')}, PMID={ref.get('pmid')}",
                f"관계: {c['relationship']}; 제안: {c.get('proposed_relationship')}; {c['comparison_status']}",
                '> '+c['quote'], '근거 위치: '+json.dumps(ref['evidence_location'],ensure_ascii=False),
                '조건 비교: '+json.dumps(c['condition_differences'],ensure_ascii=False)])
        if not r.get('comparisons'):lines.append('평가 가능한 문헌 비교 없음. 반대 근거를 생성하지 않았습니다.')
    lines.append('## 선택 문서 접근 상태\n\n'+json.dumps(data['pin']['documents'],ensure_ascii=False,indent=2))
    (p/'reader/LITERATURE.md').write_text('\n\n'.join(lines)+'\n',encoding='utf-8')
    return ARTIFACTS
