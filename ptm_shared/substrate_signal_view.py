"""Bounded read-only pages of registered signal projections; no computation."""
import base64
import binascii
import json
from pathlib import Path

from .annotation_registry import digest
from .astra_card_inputs import clean, encode
from .astra_evidence_catalog import EvidenceCatalog, read_source, safe_path
from .generic_workflow import object_hash
from .substrate_signal_flow import TABLE_KEYS

KINDS = {name.split('/')[-1]: name+'.csv' for name in TABLE_KEYS}


def published_root(order_root):
    root=Path(order_root).resolve()
    record=json.loads((root/'enrichment_free_current.json').read_text())
    artifact=record['artifacts']['provenance']
    provenance=safe_path(root,artifact['path'])
    if digest(provenance)!=artifact['sha256']: raise ValueError('Published provenance hash mismatch')
    if json.loads(provenance.read_text())['run_id']!=record['run_id']: raise ValueError('Published run mismatch')
    return provenance.parent


def signal_page(catalog, kind, filters=None, cursor=None, limit=25):
    if kind not in KINDS or type(limit) is not int or not 1<=limit<=100: raise ValueError('Invalid signal view request')
    filters=filters or {}
    if set(filters)-{'form_id','effect_series_id','track','bundle_id','trajectory_id','candidate_id'}:
        raise ValueError('Unknown signal filter')
    catalog._require()
    name=KINDS[kind]
    if name not in catalog.catalog['sources']:
        return {'status':'unavailable','reason':'saved_signal_projection_unavailable; reader_revision_required',
                'items':[],'total_count':0,'next_cursor':None}
    catalog._validate_source_keys(name)
    meta=catalog.catalog['sources'][name]
    binding=object_hash([catalog.catalog['catalog_id'],name,filters,'canonical_projection_order.v1'])
    offset=0
    if cursor:
        try:
            token=json.loads(base64.urlsafe_b64decode(cursor))
            if token['binding']!=binding: raise ValueError('Cursor catalog/filter mismatch')
            offset=token['offset']
            if type(offset) is not int or offset<0: raise ValueError('Invalid cursor offset')
        except (KeyError,TypeError,json.JSONDecodeError,binascii.Error) as exc: raise ValueError('Invalid cursor') from exc
    # Read filter/key columns first; large JSON payloads are resolved only for
    # the selected page through the existing bounded catalog source reader.
    columns=set(meta['unique_key']) | (set(filters)&set(meta['columns']))
    if 'form_id' in filters and 'form_id' not in meta['columns']:columns.add('association_form_ids_json')
    if 'bundle_id' in filters and 'bundle_id' not in meta['columns']:columns.update(['from_id','to_id'])
    if not columns<=set(meta['columns']):raise ValueError('Filter not supported for this signal table')
    frame=read_source(catalog.root,name,meta,columns=sorted(columns))
    for key,value in filters.items():
        if key in frame: frame=frame.loc[frame[key].eq(value)]
        elif key=='form_id' and 'association_form_ids_json' in frame:
            frame=frame.loc[frame.association_form_ids_json.map(lambda j:value in json.loads(j))]
        elif key=='bundle_id' and 'from_id' in frame:
            ids={value}
            bundle_name=KINDS['kinase_substrate_bundles']
            bundle_meta=catalog.catalog['sources'][bundle_name]
            bindings=read_source(catalog.root,bundle_name,bundle_meta,columns=['bundle_id','association_id'])
            ids.update(bindings.loc[bindings.bundle_id.eq(value),'association_id'])
            frame=frame.loc[frame.from_id.isin(ids)|frame.to_id.isin(ids)]
        else: raise ValueError('Filter not supported for this signal table: '+key)
    total=len(frame)
    if offset>total: raise ValueError('Cursor outside population')
    page=frame.iloc[offset:offset+limit];following=offset+len(page)
    token=base64.urlsafe_b64encode(encode({'binding':binding,'offset':following}).encode()).decode() if following<total else None
    keys=[{k:r[k] for k in meta['unique_key']} for r in clean(page.to_dict('records'))]
    items=catalog.source_rows(name,keys) if keys else []
    catalog._require()
    return {'status':'available','catalog_id':catalog.catalog['catalog_id'],'source_table':name,
            'items':items,'total_count':total,'returned_count':len(page),'next_cursor':token,
            'count_unit':'projection_rows_not_independent_observations','scope':'all_saved_rows; page_and_pin_do_not_change_population'}
