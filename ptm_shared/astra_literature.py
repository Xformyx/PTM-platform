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


def inputs(tables, snapshot, literature, *, observation_cards=None):
    packet = json.loads(tables['reader/packet'].iloc[0].packet_json)
    if observation_cards is None:
        ids = tables['reader/findings'].finding_id.tolist()
        cards = cards_for_selected_findings(packet['reader_cards'], ids, key='finding_id')
        if [c['finding_id'] for c in cards] != ids:
            raise ValueError('Literature selected finding identity/order mismatch')
    else:
        # M3 accepts genuine resolved observation cards, never fabricated raw cards.
        cards = deepcopy(observation_cards)
        if any(c.get('category') != 'measured_feature_observation' for c in cards):
            raise ValueError('Observation adapter requires real observation cards')
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
    # This text is both a query and a hashed input. JSON files sort object keys;
    # preserve semantic identity across live Order objects and archived replay.
    study['recorded_conditions_query'] = json.dumps({k:study[k] for k in ('recorded_treatments','pre_treatment','special_conditions') if k in study}, ensure_ascii=False, sort_keys=True)
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


def _execution_contract(options, settings):
    """Frozen-result reuse contract; does not assert that a live index is immutable."""
    requested = {**options, **settings}
    return {'version': VERSION, 'retrieval_version': RETRIEVAL_VERSION, 'prompt_version': PROMPT_VERSION,
            'provider': requested.get('llm_provider', 'ollama'), 'model': requested.get('llm_model'),
            'policy': (options.get('report_config') or {}).get('finding_review_policy'),
            'code': {n: hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest()
                     for n in ('astra_literature.py', 'finding_literature.py', 'literature_cards.py')}}


def _execution_code(source):
    """Hash executable retrieval/export logic, excluding reader and reuse decisions."""
    import ast
    tree=ast.parse(source)
    excluded={'apply','write','validate','_execution_contract','_execution_code','_compatible_contract'}
    nodes=[]
    for node in tree.body:
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
            if node.name in excluded:continue
            if node.name=='collect':
                # The setup and actual retrieval/export body are scientific input;
                # the frozen-pin cache decision is not a new retrieval operation.
                body=[]
                for part in node.body:
                    if isinstance(part,ast.If) and isinstance(part.test,ast.Name) and part.test.id=='frozen_pin':continue
                    if isinstance(part,ast.Assign) and any(isinstance(t,ast.Subscript) and isinstance(t.slice,ast.Constant) and t.slice.value=='_literature_reuse' for t in part.targets):continue
                    body.append(part)
                nodes.extend(body)
                continue
        nodes.append(node)
    return hashlib.sha256(ast.dump(ast.Module(body=nodes,type_ignores=[]),include_attributes=False).encode()).hexdigest()


def _compatible_contract(previous, current, archived_code):
    if previous==current:return True
    if not archived_code:return False
    previous=deepcopy(previous or {});current=deepcopy(current)
    old_digest=previous.get('code',{}).pop('astra_literature.py',None)
    current.get('code',{}).pop('astra_literature.py',None)
    # Require the exact archived implementation bound by the old pin, then
    # prove unchanged retrieval/export logic; never trust a version label alone.
    return (previous==current and hashlib.sha256(archived_code.encode()).hexdigest()==old_digest and
            _execution_code(archived_code)==_execution_code(Path(__file__).read_text()))


def collect(tables, snapshot, literature, *, settings=None, cache_root=None, retriever=None, llm=None, frozen_pin=None, frozen_code=None, run_id=None):
    """Reuse the report function and checkpoint cache, then seal exported evidence.

    Only a complete, versioned result is cached. Failed/partial/model-unavailable
    searches can be retried; their frozen package records still replay exactly.
    """
    cards, study = inputs(tables, snapshot, literature)
    settings = settings if settings is not None else {}
    options = ((snapshot or {}).get('original', {}).get('report_options') or {})
    policy = (options.get('report_config') or {}).get('finding_review_policy')
    contract = _execution_contract(options, settings)
    input_hash = object_hash({'cards':cards,'study':study,'literature':literature})
    if frozen_pin:
        valid_hash = object_hash({k:v for k,v in frozen_pin.items() if k!='sha256'}) == frozen_pin.get('sha256')
        records = list(frozen_pin.get('retrieval', {}).get('records', {}).values())
        executed = all(r.get('status') not in {'retrieval_failed','budget_exhausted','not_searched'} and
                       not r.get('partial_retrieval_failure') and
                       not any(s.get('status')=='budget_exhausted' for s in r.get('searches', [])) and
                       (not r.get('retrieved_count') or r.get('comparison_execution', {}).get('status')=='completed')
                       for r in records)
        if (valid_hash and executed and frozen_pin.get('input_sha256') == input_hash and
                _compatible_contract(frozen_pin.get('execution_contract'), contract, frozen_code) and
                frozen_pin.get('selected_finding_ids') == [c['finding_id'] for c in cards]):
            settings['_literature_reuse'] = {'status':'frozen_results_reused', 'pin_sha256':frozen_pin['sha256'],
                'current_queries':0, 'current_model_calls':0,
                'scope':'prior_published_search_and_comparison; semantic_review_status_unchanged'}
            return deepcopy(frozen_pin)
    settings['_literature_reuse'] = {'status':'collect_requested', 'reason':'no_matching_complete_published_pin'}
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
    from .astra_evidence_catalog import evidence_id_for
    evidence_by_subject = {}
    for card in cards:
        refs=[{'source_table':'reader/cards.csv','source_key':{'card_id':card['card_id']}}]
        refs += [{'source_table':'reader_adapter/form_contrasts.csv',
                  'source_key':{'adapter_row_id':binding['adapter_row_id']}}
                 for binding in card.get('source_bindings',[])]
        for ref in refs:ref['evidence_id']=evidence_id_for(ref['source_table'],ref['source_key'])
        evidence_by_subject[card['finding_id']]=refs
    def run():
        result = retrieve_finding_literature(cards,retriever,study,llm=llm,policy=policy,
            trace_directory=cache_root, trace_context={'run_id':run_id,
                'stage_id':'finding_literature', 'request_sha256':fingerprint,
                'evidence_by_subject':evidence_by_subject})
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
    pin = {'schema_version':VERSION,'input_sha256':input_hash, 'execution_contract':contract,
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
    permitted_sources=set()
    for ref in result.get('references', []):
        meta=ref.get('metadata') or {}
        permitted=ref.get('collection') in permitted_collections or permissions.get(str(_document_id(meta)))=='permitted'
        ref['source_sha256']=hashlib.sha256(str(ref.get('document','')).encode()).hexdigest()
        if permitted:
            permitted_sources.add((ref.get('collection'),ref.get('collection_version'),ref.get('source_id'),ref['source_sha256']))
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
    # New diagnostic fields must not become an alternate route for source text.
    # Keep only explicitly safe scalar metadata, hashes and gate results. Even
    # permitted excerpts do not authorize exporting provider envelopes/prompts.
    for record in result.get('records', {}).values():
        diagnostic = record.get('comparison_diagnostics')
        if diagnostic is None: continue  # Frozen legacy pins remain unchanged.
        diagnostic_restricted = restricted or not diagnostic.get('source_map') or any(
            tuple(row['source_key'].get(k) for k in ('collection','collection_version','source_id','content_sha256')) not in permitted_sources
            for row in diagnostic.get('source_map',[]))
        safe = {k:diagnostic[k] for k in (
            'schema_version','run_id','stage_id','stage_request_sha256','attempt_id','attempt_ordinal',
            'finding_id','review_subject_id','prompt_version','model','provider','parse_status',
            'diagnostic_code_sha256','prompt_validation_sources_match',
            'comparisons_status','source_map','source_map_sha256','validator_source_map_sha256',
            'prompt_sha256','prompt_bytes','request_sha256','failure_type','raw_output_sha256',
            'finish_reasons','truncation_status','transport_status','transport_diagnoses','provider_requests','provider_responses','internal_trace') if k in diagnostic}
        safe['proposals'] = [{k:p[k] for k in (
            'proposal_ordinal','proposal_sha256','source_index','gates','accepted_by_anchor_gates',
            'first_failure_reason','exclusion_class','diagnoses','other_source_indices',
            'semantic_status','production_accepted','gate_parity') if k in p}
            for p in diagnostic.get('proposals', [])]
        for p in safe['proposals']:
            if not isinstance(p.get('source_index'),int):p['source_index']=None
        if not diagnostic_restricted:
            for safe_proposal, proposal in zip(safe['proposals'],diagnostic.get('proposals', [])):
                safe_proposal.update(candidate=deepcopy(proposal['candidate']), source_offset=proposal['source_offset'])
        safe['export_status']='hashes_and_gates_only' if diagnostic_restricted else 'permitted_candidate_excerpt'
        # Evidence linkage contains exact existing IDs/keys, not whole row values.
        safe['evidence_refs']=[{k:r[k] for k in ('evidence_id','source_table','source_key','source_key_json',
            'adapter_row_id','form_id','contrast_id','card_id') if k in r}
            for r in diagnostic.get('evidence_refs',[]) if isinstance(r,dict)]
        record['comparison_diagnostics']=safe
        if diagnostic_restricted:
            for excluded in record.get('excluded_comparisons',[]):
                if 'source_index' in excluded and not isinstance(excluded['source_index'],int):
                    excluded['source_index']=None
    return result


def literature_review_stages(summary, records):
    """검색, 모델 비교, 인용 검증, 생물학적 검토, 외부 전달을 서로 다른 상태로 남긴다.

    구현 대상: docs/astra_evidence_integration/MIGRATION_AND_OPERATIONS_KO.md «문헌 검토 단계»
    사전등록: 2026-10-13. 승인 조건은 바꾸지 않는다. semantically_verified_comparable_findings는 0으로 유지한다.
    해석 한계: packet mode citation_complete는 reference card가 있다는 뜻이다. 인용 검증이나 외부 전달 승인이 아니다.
    주장 금지: 단계 이름을 나눴다고 비교가 승인되었다고 하지 않는다. 승인 건수를 늘리려고 기준을 낮추지 않는다.
    """
    classes = {}
    for record in records.values():
        for item in record.get("excluded_comparisons") or []:
            key = item.get("exclusion_class") or "unclassified"
            classes[key] = classes.get(key, 0) + 1
    chunks = int(summary.get("source_chunks_read") or 0)
    selected = int(summary.get("selected_findings") or 0)
    executed = int(summary.get("comparison_executed_findings") or 0)
    restricted = int(summary.get("export_restricted_chunks") or 0)
    if restricted:
        delivery = "source_text_not_exported"
    elif chunks:
        delivery = "source_text_recorded_review_still_required"
    else:
        delivery = "no_retrieved_source_text"
    return {
        "search": "completed" if chunks else "no_retrieved_chunks",
        "model_comparison": "completed" if selected and executed == selected else ("partial" if executed else "not_run"),
        "citation_evidence_verification": "not_verified",
        "biological_meaning_review": "not_performed",
        "external_delivery": delivery,
        "approved_relationships": int(summary.get("semantically_verified_comparable_findings") or 0),
        "exclusion_class_counts": classes,
        "packet_mode_meaning": "citation_complete means reference cards exist. It is not citation verification, biological review, or permission to deliver the claim.",
    }


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
    summary['review_stages']=literature_review_stages(summary, records)
    packet=json.loads(tables['reader/packet'].iloc[0].packet_json)
    packet['literature_comparison_status']='source_anchored_review_pending' if comparisons else ('internal_comparison_performed_export_restricted' if summary['internal_compared_findings'] else 'compared_no_supported_relationship' if summary['comparison_executed_findings']==len(cards) and cards else 'retrieved_comparison_pending' if sources else 'not_performed_no_accessible_evidence')
    packet['literature']={'status_authority':'reader/literature_search.csv; inherited card status describes original card generation only',
                          'summary':summary,'pin':pin,'reference_cards':_literature_cards(result.get('references',[])),
                          'finding_records':records,'source_table':'reader/literature_sources.csv', 'comparison_table':'reader/literature_comparisons.csv'}
    summary['status']=packet['literature_comparison_status']
    packet['authoring_rules']['literature_execution_authority']={
        'path':'reader/literature_search.csv','status':summary['status'],
        'rule':'Raw card literature flags/limits record the earlier card-build stage. Use each finding record for actual search/comparison execution; never turn completed comparison with no supported relation into not_performed. Independent validation remains not_performed.'}
    packet['coverage_inventory']['literature_comparison']=summary['status']
    packet['mode']='citation_complete' if packet['literature']['reference_cards'] else 'data_only'
    packet['literature_stages']=summary['review_stages']
    packet['mode_meaning']=summary['review_stages']['packet_mode_meaning']
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


def _source_field(ref, *names):
    meta = ref.get('metadata') or {}
    for name in names:
        if ref.get(name) not in (None, ''):
            return ref.get(name)
        if meta.get(name) not in (None, ''):
            return meta.get(name)
    return None


def retrieved_source_guidance(records):
    """검색 구간 행의 DOI, PMID, 위치를 source_key마다 옮긴다.

    구현 대상: docs/astra_evidence_integration/MIGRATION_AND_OPERATIONS_KO.md «저장된 결과의 reader 연결»
    사전등록: 2026-10-13. g7 LITERATURE.md가 pin documents의 빈 DOI를 검색 구간 위치로 적은 것을 본 뒤. 탐색적. primary 승격 금지.
    해석 한계: 이미 저장된 출처 필드의 연결이다. 새 검색이 아니고 승인 조건을 낮추지 않는다.
    주장 금지: DOI가 보여도 claim_support_status가 not_verified인 비교를 승인된 문헌 근거로 쓰지 않는다.
    """
    lines = ['## 검색된 구간의 출처',
        '아래는 reader/literature_sources.csv의 검색 구간 식별 metadata다. 원문 페이지나 문장을 만들지 않는다. 이 목록은 인용 검증이나 승인된 비교가 아니다.']
    records = [item for _, item in sorted(enumerate(records), key=lambda item: (str(item[1][0]), item[0]))]
    if not records:
        lines.append('검색 구간 출처 행이 없습니다.')
        return lines
    papers = set()
    for key, ref in records:
        doi = _source_field(ref, 'doi', 'DOI')
        pmid = _source_field(ref, 'pmid', 'PMID')
        if doi:
            papers.add(('doi', str(doi)))
        elif pmid:
            papers.add(('pmid', str(pmid)))
    lines.append(f'검색 구간 {len(records)}개, 고유 논문 {len(papers)}편. 같은 논문의 구간은 각각 유지한다. 구간 수는 승인된 비교 수가 아니다.')
    for key, ref in records:
        meta = ref.get('metadata') or {}
        loc = ref.get('evidence_location') or meta.get('evidence_location') or {}
        fields = [f'source_key={key}', f"title={_source_field(ref, 'title') or '미기록'}",
                  f"DOI={_source_field(ref, 'doi', 'DOI') or '미기록'}", f"PMID={_source_field(ref, 'pmid', 'PMID') or '미기록'}",
                  f"chunk_id={loc.get('chunk_id') if loc.get('chunk_id') is not None else '미기록'}",
                  f"chunk_index={loc.get('chunk_index') if loc.get('chunk_index') is not None else '미기록'}",
                  f"section={loc.get('section') if loc.get('section') is not None else '미기록'}"]
        if loc.get('page') is not None:
            fields.append(f"page={loc.get('page')}")
        access = ref.get('access_restriction') or ref.get('evidence_export_permission') or meta.get('evidence_export_permission') or '미기록'
        export = ref.get('export_status') or ref.get('comparison_export_status') or '미기록'
        fields.extend([f'접근={access}', f'내보내기={export}'])
        lines.append('- ' + '; '.join(str(field) for field in fields))
    return lines


def write(directory,tables, *, pins=True):
    p=Path(directory);(p/'reader').mkdir(parents=True,exist_ok=True)
    packet=json.loads(tables['reader/packet'].iloc[0].packet_json);data=packet['literature']
    if pins:
        (p/'references').mkdir(parents=True,exist_ok=True)
        json_write(p/'references/finding_literature_pin.json',data['pin']);json_write(p/'reader/literature_summary.json',data['summary'])
    lines=['# 선정 관측의 문헌 검색과 비교', '[주요 관측](READ_ME.md) · [검색 기록](literature_search.csv) · [출처](literature_sources.csv) · [비교](literature_comparisons.csv)',
        '검색 완료, 모델 비교 완료, 인용 근거 검증, 생물학적 의미 검토, 외부 전달 가능 여부는 서로 다른 단계다. packet mode가 citation_complete여도 인용 검증이 끝난 것이 아니다.',
        '검색 성공·인용문 일치·생물학적 판단 검증은 서로 다릅니다. 제안된 일치/상이는 원문 의미 검토 전까지 배경 근거로 유지합니다. 미검색은 반대 결과가 아닙니다. 본문/PDF 재배포 여부는 내부 검색 여부와 별도입니다.',
        '승인된 비교는 semantically_verified_comparable_findings입니다. 이 값은 기준을 낮춰 늘리지 않습니다. 제외 사유는 exclusion_class_counts에서 인용 불일치(citation_mismatch), 범위(scope), 조건 비교(condition_comparison)로 나뉩니다.',
        '```json\n'+json.dumps(data['summary'],ensure_ascii=False,indent=2)+'\n```']
    comps=tables['reader/literature_comparisons']
    source_rows=[row for _, row in sorted(enumerate(tables['reader/literature_sources'].itertuples()), key=lambda item: (str(item[1].source_key), item[0]))]
    records=[(row.source_key, json.loads(row.source_json)) for row in source_rows]
    keys=[row.source_key for row in source_rows]
    duplicate_keys={key for key in keys if keys.count(key) > 1}
    refs={}
    for key, ref in records:
        if key not in duplicate_keys and key not in refs:
            refs[key]=ref
    for card in [c for c in packet['reader_cards'] if c.get('finding_id')]:
        r=data['finding_records'][card['finding_id']]
        lines.extend([f"## {card['feature_label']} — {card['finding_id']}",f"검색: {r['status']}; 사유: {r.get('reason',r.get('review_reason','none'))}. 원본: {', '.join(r['source_row_ids'])}"])
        for row in comps.loc[comps.finding_id.eq(card['finding_id'])].itertuples():
            if row.source_key in duplicate_keys:
                lines.append(f'{row.comparison_id}: source_key {row.source_key}가 둘 이상이라 출처를 고르지 않았습니다.')
                continue
            c=json.loads(row.comparison_json);ref=refs[row.source_key]
            lines.extend([f"{row.comparison_id}: {ref.get('title')} ({ref.get('year')}); DOI={ref.get('doi')}, PMID={ref.get('pmid')}",
                f"관계: {c['relationship']}; 제안: {c.get('proposed_relationship')}; {c['comparison_status']}",
                '> '+c['quote'], '근거 위치: '+json.dumps(ref['evidence_location'],ensure_ascii=False),
                '조건 비교: '+json.dumps(c['condition_differences'],ensure_ascii=False)])
        if not r.get('comparisons'):lines.append('평가 가능한 문헌 비교 없음. 반대 근거를 생성하지 않았습니다.')
        for item in r.get('excluded_comparisons') or []:
            lines.append('제외: '+json.dumps({'reason':item.get('reason'),'exclusion_class':item.get('exclusion_class'),'source_index':item.get('source_index')},ensure_ascii=False))
    lines.extend(retrieved_source_guidance(records))
    lines.append('## 패키지 문서 목록')
    lines.append('아래는 pin documents다. 검색 구간의 DOI·PMID·위치는 앞의 출처 절과 literature_sources.csv를 본다. 이 목록의 빈 DOI는 검색 구간에 출처가 없다는 뜻이 아니다.')
    lines.append(json.dumps(data['pin']['documents'],ensure_ascii=False,indent=2))
    (p/'reader/LITERATURE.md').write_text('\n\n'.join(lines)+'\n',encoding='utf-8')
    return ARTIFACTS
