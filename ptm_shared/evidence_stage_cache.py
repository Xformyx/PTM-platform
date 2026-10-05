"""Content-checked checkpoints for pure evidence stages, without pickle or network.

Context text is never restored from a computational cache. Only stage outputs are
stored, and a complete manifest is atomically published after all object writes.
"""
import json
import math
from pathlib import Path
from uuid import uuid4
import numpy as np
import pandas as pd
from .annotation_registry import digest
from .astra_inputs import stable_id

VERSION='evidence_stage_cache.v1'


def cached_stage(root,stage,fingerprint,compute):
    key=stable_id('stage',[VERSION,stage,fingerprint]);target=Path(root)/key
    def read():
        manifest=json.loads((target/'complete.json').read_text())
        if manifest['version']!=VERSION or manifest['fingerprint']!=fingerprint:raise ValueError('cache_contract_mismatch')
        for name,sha in manifest['files'].items():
            path=(target/name).resolve()
            if not path.is_relative_to(target.resolve()) or digest(path)!=sha:raise ValueError('cache_checksum_mismatch')
        def decode(value):
            if not isinstance(value,dict):return value
            kind=value['type'];item=value.get('value')
            if kind=='table':return pd.read_parquet(target/item)
            if kind=='array':return np.asarray(decode(item),dtype=value['dtype'])
            if kind=='float':return float(item)
            if kind=='dict':return {decode(k):decode(v) for k,v in item}
            if kind in {'tuple','list'}:
                items=[decode(v) for v in item]
                return tuple(items) if kind=='tuple' else items
            raise ValueError('unsupported_cache_type')
        return decode(manifest['result'])
    if (target/'complete.json').is_file():
        try:return read(),{'status':'reused','fingerprint':fingerprint,'stage':stage}
        except (OSError,ValueError,KeyError,TypeError):pass
    result=compute();Path(root).mkdir(parents=True,exist_ok=True)
    temporary=Path(root)/('.'+key+'-'+uuid4().hex);temporary.mkdir()
    files={}
    def encode(value):
        if isinstance(value,pd.DataFrame):
            name=f'table_{len(files)}.parquet';value.to_parquet(temporary/name,index=True)
            files[name]=digest(temporary/name);return {'type':'table','value':name}
        if isinstance(value,np.ndarray):return {'type':'array','value':encode(value.tolist()),'dtype':str(value.dtype)}
        if isinstance(value,np.generic):value=value.item()
        if isinstance(value,float) and not math.isfinite(value):return {'type':'float','value':str(value)}
        if isinstance(value,dict):return {'type':'dict','value':[[encode(k),encode(v)] for k,v in value.items()]}
        if isinstance(value,(tuple,list)):return {'type':'tuple' if isinstance(value,tuple) else 'list','value':[encode(v) for v in value]}
        if value is None or isinstance(value,(str,int,float,bool)):return value
        raise TypeError('Unsupported checkpoint value: '+type(value).__name__)
    payload=encode(result)
    (temporary/'complete.json').write_text(json.dumps({'version':VERSION,'fingerprint':fingerprint,'files':files,'result':payload},allow_nan=False))
    # An interrupted temporary directory is never read as a completed stage.
    try:temporary.rename(target)
    except OSError:
        if not target.exists():raise
        # Concurrent writer or invalid old cache: preserve both, never overwrite
        # an immutable object with an unverified replacement.
    return result,{'status':'computed','fingerprint':fingerprint,'stage':stage}
