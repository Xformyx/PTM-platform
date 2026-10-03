"""Offline manifest/typed prediction evaluation; never loads truth in production.

python -m benchmarking.astra_science --manifest studies.json --predictions rows.json --output evaluation.json
Predictions are predeclared evaluation units, including unknown labels and no-calls.
Official tool outputs require an explicitly pinned, method-specific normalization
outside production; this CLI never labels an internal baseline as an official tool.
"""
import argparse
import json
from pathlib import Path
from .evaluate import validate_manifest,selective_metrics,comparator_contract,PROTOCOL

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--manifest',type=Path,required=True);p.add_argument('--predictions',type=Path);p.add_argument('--output',type=Path,required=True)
a=p.parse_args();studies=json.loads(a.manifest.read_text());audit=validate_manifest(studies)
result={'manifest_validation':audit,'protocol':PROTOCOL,'comparators':[comparator_contract(n) for n in PROTOCOL['comparators']],
        'evaluation_status':'not_run_predictions_unavailable','metrics':None}
if a.predictions:
    rows=json.loads(a.predictions.read_text());ids={r['dataset_id'] for r in studies}
    if any(r.get('dataset_id') not in ids for r in rows):raise ValueError('Prediction dataset missing from manifest')
    if any(r.get('correct') not in {None,True,False} for r in rows):raise ValueError('Truth must be explicit nullable correctness')
    result.update(evaluation_status='provided_predictions_evaluated_not_independent_tool_execution',metrics=selective_metrics(rows))
if a.output.exists():raise ValueError('Immutable evaluation output already exists')
a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
