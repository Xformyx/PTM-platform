"""Offline historical audit. Never query a corpus or generate missing proposals.

Only safe locators/hashes/statuses are written. Snapshot text remains private.
"""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import subprocess


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values(): yield from objects(child)
    elif isinstance(value, list):
        for child in value: yield from objects(child)


def cached_value(value):
    """Decode only the existing JSON cache's containers; never execute pickle."""
    if not isinstance(value,dict): return value
    kind=value.get('type'); item=value.get('value')
    if kind=='dict':return {cached_value(k):cached_value(v) for k,v in item}
    if kind in {'list','tuple'}:return [cached_value(v) for v in item]
    return value


def audit(source, consumer, search_roots, snapshots, output):
    output.mkdir(parents=True, exist_ok=False)
    relative = 'references/finding_literature_pin.json'
    pin = json.loads((source/relative).read_text())
    records = pin['retrieval']['records']
    hashes = {pin[k] for k in ('request_sha256','input_sha256')}
    for record in records.values():
        hashes.update(record['comparison_execution'][k] for k in ('input_sha256','output_sha256'))
    patterns = output/'historical_hashes.txt'
    patterns.write_text('\n'.join(sorted(hashes)))
    command = ['rg','-l','--hidden','-F','-f',str(patterns),'-g','*.json','-g','*.jsonl','-g','*.log',
        '-g','!**/source_pin.json','-g','!**/reader/**','-g','!**/reproducibility/**',
        '-g','!**/g11-followup-02/**', *map(str, search_roots)]
    found = subprocess.run(command, capture_output=True, text=True)
    if found.returncode not in (0,1): raise RuntimeError(found.stderr)
    candidates = sorted(set(found.stdout.splitlines()))
    wanted = {h['source_sha256'] for r in records.values() for h in r['coverage']}
    recovered = {}; prompts = {}; responses = {}
    scanned = []
    for name in sorted(set(candidates + list(map(str,snapshots)))):
        path = Path(name)
        try: content = json.loads(path.read_text())
        except (ValueError, UnicodeError):
            scanned.append({'path':name,'status':'not_json'}); continue
        if isinstance(content,dict) and content.get('version')=='evidence_stage_cache.v1':
            content=cached_value(content['result'])
        scanned.append({'path':name,'sha256':sha(path),'status':'inspected'})
        for obj in objects(content):
            text = obj.get('document')
            if isinstance(text,str):
                digest = hashlib.sha256(text.encode()).hexdigest()
                if digest in wanted:
                    recovered.setdefault(digest,[]).append({'path':name,
                        'snapshot_source_id':obj.get('source_id',obj.get('id')), 'content_sha256':digest})
            for key, destination in [('resolved_prompt',prompts),('provider_raw_text',responses)]:
                text = obj.get(key)
                if isinstance(text,str):
                    digest=hashlib.sha256(text.encode()).hexdigest()
                    if digest in hashes: destination.setdefault(digest,[]).append(name)
    rows=[]
    for fid,record in records.items():
        execution=record['comparison_execution']
        for ordinal,excluded in enumerate(record['excluded_comparisons']):
            index=excluded.get('source_index')
            coverage=record['coverage'][index] if isinstance(index,int) and 0<=index<len(record['coverage']) else {}
            content_hash=coverage.get('source_sha256')
            prompt_found=execution['input_sha256'] in prompts
            response_found=execution['output_sha256'] in responses
            source_found=content_hash in recovered
            # Full causal reconstruction needs the original proposals AND
            # prompt/validator binding. Metadata hashes alone cannot prove it.
            if prompt_found and response_found:
                raise ValueError('Matching raw execution found: inspect parse/source/gate parity before assigning exact reconstruction')
            partial=source_found or prompt_found or response_found
            rows.append({'audit_locator':f'{fid}/excluded_comparisons/{ordinal}',
                'finding_id':fid,'exclusion_ordinal_zero_based':ordinal,'source_index':index,
                'stored_reason':excluded['reason'],'stored_exclusion_class':excluded.get('exclusion_class'),
                'pin_sha256':pin['sha256'],'request_sha256':pin['request_sha256'],
                'input_sha256':execution['input_sha256'],'output_sha256':execution['output_sha256'],
                'collection':coverage.get('collection'),'collection_version':coverage.get('collection_version'),
                'source_id':coverage.get('source_id'),'source_content_sha256':content_hash,
                'source_binding_basis':'stored_coverage[source_index]; final_prompt_order_unverified',
                'classification':'partially_reconstructable' if partial else 'historical_trace_unavailable',
                'same_hash_source_text_available':source_found,'same_hash_prompt_available':prompt_found,
                'same_hash_output_available':response_found,'stored_proposal_available':False,
                'full_gate_results_available':False,'cause':'indeterminate',
                'limitation':'hash_matched_source_only; proposal/prompt/validation_trace_missing' if source_found else
                             'hashes_and_first_failure_only; original_prompt_output_and_validation_trace_missing'})
    with (output/'EXCLUSION_AUDIT.csv').open('w') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(rows[0]),lineterminator='\n');writer.writeheader();writer.writerows(rows)
    preserved={}
    for name in (relative,'references/literature_pin.json','reader/literature_search.csv',
                 'reader/literature_sources.csv','reader/literature_comparisons.csv'):
        preserved[name]={'source_sha256':sha(source/name),'consumer_sha256':sha(consumer/name)}
        assert preserved[name]['source_sha256']==preserved[name]['consumer_sha256']
    result={'schema_version':'g11_historical_exclusion_audit.v1','source':str(source),'consumer':str(consumer),
        'pin_sha256':pin['sha256'],'request_sha256':pin['request_sha256'], 'cache':pin['cache'], 'model':pin['model'],
        'exclusion_count':len(rows),'reasons':dict(Counter(r['stored_reason'] for r in rows)),
        'by_finding':dict(Counter(r['finding_id'] for r in rows)),
        'classifications':dict(Counter(r['classification'] for r in rows)),
        'exactly_reconstructable':0,'causal_explanation_verified':0,
        'unique_historical_source_chunks':len(wanted),'matched_source_chunks':len(recovered),
        'recovered_source_locations':recovered,'matched_prompts':prompts,'matched_outputs':responses,
        'scanned_files':scanned,'search_roots':list(map(str,search_roots)),
        'original_and_round01_preservation':preserved,
        'm4_subject_pin_audited_as_legacy_exclusions':False,'new_queries':0,'new_model_calls':0,
        'operating_server_or_order_checked':False}
    (output/'AUDIT_RESULTS.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps({k:result[k] for k in ('exclusion_count','reasons','classifications','matched_source_chunks','exactly_reconstructable')}))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True,type=Path);parser.add_argument('--consumer',required=True,type=Path)
    parser.add_argument('--search-root',action='append',type=Path,required=True)
    parser.add_argument('--snapshot',action='append',type=Path,default=[])
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    audit(args.source,args.consumer,args.search_root,args.snapshot,args.output)
