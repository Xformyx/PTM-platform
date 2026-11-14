"""Budgeted saved-row delivery through one EvidenceCatalog session, no search."""
import base64
from collections import defaultdict
import json
from pathlib import Path
import pandas as pd
from .astra_card_inputs import encode
from .astra_evidence_catalog import read_source, evidence_id_for
from .astra_reader_temporal import source_row
from .generic_workflow import object_hash
from .quantitative_fields import field_semantics
from .annotation_registry import digest

VERSION='astra_evidence_bundle.v1'
ROLES={'reader/cards.csv':'direct_observation','reader_adapter/form_contrasts.csv':'direct_observation',
       'quant/summary.csv':'direct_observation','quant/comparisons.csv':'direct_observation',
       'quant/protein_contrasts.csv':'parent_context','kinase/method_scores.csv':'method_context',
       'science/inference_results.csv':'limitation','reader/coverage.csv':'limitation',
       'quant/detection.csv':'detection','evidence/emergence_evidence.csv':'detection'}
ALLOWED_ROLES=set(ROLES.values())|{'opposing_observation','literature_context'}


def _question_population(catalog, base, question, scope):
    name='reader/full_question_links.csv'
    if name not in catalog.catalog['sources']:raise ValueError('question_scope_unavailable: no stored question links')
    catalog._validate_source_keys(name)
    frame=catalog._cached_source(name)
    if frame is None:frame=read_source(catalog.root,name,catalog.catalog['sources'][name])
    ids=question if isinstance(question,list) else [question]
    links=frame if question is None else frame.loc[frame.question_id.isin(ids)]
    known=set(base.evidence_id);rows={};unresolved=[]
    all_index=catalog.index.set_index('evidence_id')
    series_ids=set(catalog._filtered_index({'effect_series_id':scope['effect_series_id']}).evidence_id) if 'effect_series_id' in scope else None
    for raw in links.to_dict('records'):
        r=source_row(raw);eid=r.get('evidence_id')
        subjects=set(json.loads(r.get('subject_evidence_ids_json') or '[]'))
        if scope and eid not in known and not subjects & known:continue
        if r.get('source_table') is None or not r.get('source_key_json'):
            unresolved.append({k:r.get(k) for k in ['question_id','role','status','reason']});continue
        if series_ids is not None and eid in all_index.index and eid not in series_ids:continue
        if eid not in rows:
            if eid in all_index.index:row=source_row(all_index.loc[eid].to_dict());row['evidence_id']=eid
            else:
                row={'evidence_id':eid,'source_table':r['source_table'],'source_key_json':r['source_key_json'],
                     'evidence_type':'linked_context','scope_json':'{}','status_json':encode({'link_status':r.get('status')}),
                     'effect_scope_status':'stored_link_context_no_scalar_scope','effect_memberships_json':'[]',
                     'selected_for_summary':False,'review_status':'not_recorded'}
            rows[eid]={**row,'bundle_roles':[]}
        if r['role'] not in rows[eid]['bundle_roles']:rows[eid]['bundle_roles'].append(r['role'])
    # Existing index ordering remains authoritative; catalog-only contexts follow
    # by stable source key. A context link never invents its own effect series.
    ordered=[rows[eid] for eid in catalog.index.evidence_id if eid in rows]
    ordered += sorted((r for eid,r in rows.items() if eid not in all_index.index),key=lambda r:(r['source_table'],r['source_key_json']))
    return pd.DataFrame(ordered,columns=list(catalog.index.columns)+['bundle_roles']),unresolved


def _cursor(binding, offset):
    return base64.urlsafe_b64encode(encode({'binding':binding,'offset':offset}).encode()).decode()


def _registered_population(catalog, name):
    """Explicit table access includes catalog-only rows without inventing scope."""
    if name not in catalog.catalog['sources']:raise ValueError('Unregistered source: '+name)
    catalog._validate_source_keys(name);meta=catalog.catalog['sources'][name]
    rows=[]
    for frame in read_source(catalog.root,name,meta,columns=meta['unique_key'],chunksize=50000):
        for raw in frame.to_dict('records'):
            key=source_row(raw)
            rows.append({'evidence_id':evidence_id_for(name,key),'source_table':name,'source_key_json':encode(key),
                'evidence_type':'registered_source','scope_json':'{}','status_json':'{}',
                'effect_scope_status':'unprojected_registered_source','effect_memberships_json':'[]',
                'selected_for_summary':False,'review_status':'not_recorded',
                'bundle_roles':['literature_context' if 'literature' in name else 'direct_observation']})
    return pd.DataFrame(rows,columns=list(catalog.index.columns)+['bundle_roles'])


def bundle(catalog, request):
    catalog._require()
    allowed={'catalog_id','scope','source_roles','row_budget','byte_budget','continuation'}
    if not isinstance(request,dict) or set(request)-allowed:raise ValueError('Unknown bundle request field')
    cid=catalog.catalog['catalog_id']
    if request.get('catalog_id',cid)!=cid:raise ValueError('Bundle catalog mismatch')
    scope=request.get('scope') or {};roles=request.get('source_roles') or []
    if not isinstance(scope,dict) or not isinstance(roles,list) or set(roles)-ALLOWED_ROLES:raise ValueError('Invalid scope/source roles')
    row_budget=request.get('row_budget',100);byte_budget=request.get('byte_budget',256*1024)
    if type(row_budget)!=int or not 1<=row_budget<=10000:raise ValueError('row_budget must be 1..10000')
    if type(byte_budget)!=int or byte_budget<1000:raise ValueError('byte_budget must be at least 1000')
    provenance=catalog.root/'provenance.json'
    if 'provenance.json' not in catalog._verified:catalog._verify('provenance.json',{'sha256':digest(provenance)})
    run_id=json.loads(provenance.read_text())['run_id']
    binding=object_hash([VERSION,cid,run_id,catalog._verified['provenance.json'][1]['sha256'],scope,sorted(roles),catalog.catalog['query']['sort']])
    offset=0
    if request.get('continuation'):
        try:
            cursor=json.loads(base64.urlsafe_b64decode(request['continuation'].encode()))
            if cursor['binding']!=binding:raise ValueError('Cursor catalog/filter/sort mismatch')
            offset=cursor['offset']
            if type(offset)!=int or offset<0:raise ValueError('Invalid cursor offset')
        except (KeyError,TypeError,UnicodeError,json.JSONDecodeError) as error:raise ValueError('Invalid cursor') from error
    cached=getattr(catalog,'_bundle_population',None)
    if cached is None or cached[0]!=binding:
        filters={k:v for k,v in scope.items() if k!='question_id'}
        population=catalog._filtered_index(filters).copy();unresolved=[]
        if 'question_id' in scope:population,unresolved=_question_population(catalog,population,scope['question_id'],filters)
        elif set(filters)=={'source_table'} and isinstance(filters['source_table'],str) and not len(population):
            population=_registered_population(catalog,filters['source_table'])
        else:
            population['bundle_roles']=population.source_table.map(lambda name:[ROLES.get(name,'direct_observation')])
            if 'source_table' not in filters and 'reader/full_question_links.csv' in catalog.catalog['sources']:
                context,unresolved=_question_population(catalog,population,None,filters)
                role_map={r.evidence_id:r.bundle_roles for r in context.itertuples()}
                population['bundle_roles']=[sorted(set(r.bundle_roles)|set(role_map.get(r.evidence_id,[]))) for r in population.itertuples()]
                # Stored exact links add catalog-only parent/method/literature
                # context; primary rows retain their canonical index ordering.
                context=context.loc[~context.evidence_id.isin(population.evidence_id)]
                population=pd.concat([population,context],ignore_index=True)
        if roles:population=population.loc[population.bundle_roles.map(lambda r:bool(set(r)&set(roles)))]
        catalog._bundle_population=(binding,population,unresolved)
    _,population,unresolved=catalog._bundle_population;total=len(population)
    if offset>total:raise ValueError('Cursor outside result set')
    candidates=population.iloc[offset:offset+row_budget]
    resolved={}
    # Batch every source once per page; canonical keys, not row numbers, join values.
    for name,group in candidates.groupby('source_table',sort=False):
        keys=[json.loads(k) for k in group.source_key_json]
        for row,value in zip(group.to_dict('records'),catalog.source_rows(name,keys)):
            resolved[row['evidence_id']]=value
    current=None
    if 'reader/packet.csv' in catalog.catalog['sources']:
        catalog._validate_source_keys('reader/packet.csv');frame=catalog._cached_source('reader/packet.csv')
        if frame is None:frame=read_source(catalog.root,'reader/packet.csv',catalog.catalog['sources']['reader/packet.csv'])
        from .astra_execution_status import project_current_status
        current=project_current_status(json.loads(frame.iloc[0].packet_json))
    items=[];definitions={}
    context_access=[{'table':name,'rows':meta['rows'],'scope':'whole saved source; not automatically bound to requested claim',
                     'request':{'scope':{'source_table':name}},'review_status':'see recorded source/semantic status'}
                    for name,meta in catalog.catalog['sources'].items() if name in {
                        'reader/literature_sources.csv','reader/literature_search.csv','reader/literature_subject_execution.csv','reader/literature_subject_links.csv'}]
    def response(items,definitions,reason=None):
        following=offset+len(items)
        return {'schema_version':VERSION,'catalog_id':cid,'run_id':run_id,
            'requested_scope':scope,'applied_scope':scope,'source_roles':roles,
            'count_unit':'source_row_representations_not_independent_observations',
            'total_count':total,'returned_count':len(items),'remaining_count':total-following,
            'next_cursor':_cursor(binding,following) if following<total else None,
            'truncation':following<total,'limit_reason':reason,'items':items,'definitions':definitions,
            'current_execution':current if items else None,
            'additional_context_access':context_access if items else [],
            'unresolved_context_links':{'count':len(unresolved),'source':'reader/full_question_links.csv',
                'access':{'scope':{'source_table':'reader/full_question_links.csv'}}} if unresolved else {'count':0},
            'context_scope_rule':'exact stored links; catalog-only context has no invented scalar effect scope',
            'review_status':'not_performed_by_bundle'}
    for raw in candidates.to_dict('records'):
        e=source_row(raw);name=e['source_table'];value=resolved[e['evidence_id']]
        fields={key:field_semantics(name,key,row=value) for key in value}
        # Keep observed null counts and declared dtype from the saved dictionary.
        saved=catalog.catalog['sources'][name].get('field_semantics',{})
        for key in fields:
            for k in ['observed_null_count','dtype','null_status_binding']:
                if k in saved.get(key,{}):fields[key][k]=saved[key][k]
        definition_id=object_hash([name,fields]);candidate_defs={**definitions,definition_id:fields}
        item={'evidence_ref':{'run_id':run_id,'catalog_id':cid,'evidence_id':e['evidence_id'],
            'source_table':name,'source_key':json.loads(e['source_key_json'])},
            'evidence':e,'values':value,'definitions_ref':definition_id,'source_roles':e['bundle_roles']}
        proposed=response(items+[item],candidate_defs,'row_budget' if offset+len(items)+1<total else None)
        required=len(encode(proposed).encode('utf-8'))
        if required>byte_budget:
            result=response(items,definitions,'byte_budget' if items else 'byte_budget_requires_larger_response')
            if not items:result['minimum_required_bytes']=required
            if len(encode(result).encode('utf-8'))>byte_budget:raise ValueError('byte_budget cannot fit response metadata')
            catalog._require();return result
        items.append(item);definitions=candidate_defs
    result=response(items,definitions,'row_budget' if offset+len(items)<total else None)
    if len(encode(result).encode('utf-8'))>byte_budget:raise ValueError('byte_budget cannot fit response metadata')
    catalog._require();return result
