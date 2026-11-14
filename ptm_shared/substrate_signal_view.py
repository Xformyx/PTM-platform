"""Bounded read-only pages of registered signal projections; no computation."""
import base64
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
        except (KeyError,TypeError,json.JSONDecodeError) as exc: raise ValueError('Invalid cursor') from exc
    frame=read_source(catalog.root,name,meta)
    for key,value in filters.items():
        if key in frame: frame=frame.loc[frame[key].eq(value)]
        elif key=='form_id' and 'edges_json' in frame:
            frame=frame.loc[frame.edges_json.map(lambda j:any(e.get('form_id')==value for e in json.loads(j)))]
        elif key=='bundle_id' and 'from_id' in frame:
            frame=frame.loc[frame.from_id.eq(value)|frame.to_id.eq(value)]
        else: raise ValueError('Filter not supported for this signal table: '+key)
    total=len(frame)
    if offset>total: raise ValueError('Cursor outside population')
    page=frame.iloc[offset:offset+limit];following=offset+len(page)
    token=base64.urlsafe_b64encode(encode({'binding':binding,'offset':following}).encode()).decode() if following<total else None
    catalog._require()
    return {'status':'available','catalog_id':catalog.catalog['catalog_id'],'source_table':name,
            'items':clean(page.to_dict('records')),'total_count':total,'returned_count':len(page),'next_cursor':token,
            'count_unit':'projection_rows_not_independent_observations','scope':'all_saved_rows; page_and_pin_do_not_change_population'}
