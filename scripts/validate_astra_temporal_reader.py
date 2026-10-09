"""Validate a saved-temporal reader revision without executing any analysis."""
import argparse
from copy import deepcopy
import json
import math
from pathlib import Path
import re

import pandas as pd

from ptm_shared.annotation_registry import digest
from ptm_shared.astra_card_inputs import clean, encode
from ptm_shared.astra_reader_temporal import KEYS


def validate(before, package):
    baseline=json.loads((before/'manifest.json').read_text())
    dictionary=json.loads((before/'reproducibility/data_dictionary.json').read_text())
    preserved=[name for name in dictionary if name!='reader/packet.csv']
    preserved += [name for name in baseline['files'] if name.startswith(('references/','figures/'))]
    for name in preserved:
        if digest(before/name)!=digest(package/name):raise ValueError('Preservation failed: '+name)
    original=json.loads((before/'reader/authoring_packet.json').read_text())
    packet=json.loads((package/'reader/authoring_packet.json').read_text())
    stripped=deepcopy(packet);projected=stripped.pop('temporal_evidence')
    stripped['authoring_rules'].pop('temporal_evidence');stripped['full_evidence'].pop('saved_temporal')
    for q in stripped['research_question_evidence_map']['questions']:q.pop('temporal_evidence')
    if stripped!=original:raise ValueError('Original finding/question/literature packet changed')
    sources={}
    for name in KEYS:
        path=name+'.csv'
        if path in dictionary:
            frame=pd.read_csv(package/path,low_memory=False,float_precision='round_trip',
                dtype={k:'str' for k,v in dictionary[path]['dtypes'].items() if v in {'str','object'}})
            if frame.duplicated(KEYS[name]).any():raise ValueError('Duplicate original row: '+path)
            sources[path]={encode({k:r[k] for k in KEYS[name]}):clean(r) for r in frame.to_dict('records')}
    checked=0
    def walk(value):
        nonlocal checked
        if isinstance(value,dict):
            if set(value)>={'source','row'}:
                ref=value['source'];source=sources[ref['table']][encode(ref['key'])]
                source=dict(source)
                for key in ('parent_pattern_agreement','normalization_pattern_agreement'):
                    if source.get(key) in ('True','False'):source[key]=source[key]=='True'
                if encode(source)!=encode(value['row']):raise ValueError('Projected value/NA/identity changed: '+encode(ref))
                checked+=1
            for v in value.values():walk(v)
        elif isinstance(value,list):
            for v in value:walk(v)
    walk(projected)
    links=set()
    for link in projected['links']:
        key=encode(link['source_key']);assert key in sources[link['source_table']]
        identity=(link['finding_id'],link['source_table'],key)
        if identity in links:raise ValueError('Duplicate reader connection')
        links.add(identity)
    points=0
    for f in projected['findings']:
        if f['status']!='linked':continue
        for e in f['features']+[e for c in f['candidates'] for e in c['features']]:
            r=e['row'];values=json.loads(r['values']);mask=json.loads(r['observed_mask'])
            times=json.loads(r['times_minutes']);assert len(values)==len(mask)==len(times)==len(e['contrast_ids'])
            for cid,t,v,m in zip(e['contrast_ids'],times,values,mask):
                if e['role']=='ptm':
                    source=sources['quant/comparisons.csv'][encode({'form_id':r['entity_id'],'contrast_id':cid})]
                    expected=source[r['track']]
                    if r['track']=='A' and not source['included']:expected=None
                elif e['role']=='parent_protein':
                    table={'PG':'quant/protein_contrasts.csv','strict_unmodified':'quant/strict_unmodified_proteins.csv'}[r['track']]
                    source=sources[table].get(encode({'protein_group':r['entity_id'],'contrast_id':cid}))
                    expected=source['log2_change'] if source else None
                else:
                    source=sources['kinase/kinase_temporal_profiles.csv'].get(encode({'candidate_id':r['entity_id'],'contrast_id':cid,'track':r['track']}))
                    expected=source['activity_magnitude'] if source else None
                assert (v is not None)==m
                assert (v is None and expected is None) or (v is not None and expected is not None and math.isclose(v,expected,abs_tol=1e-10,rel_tol=1e-10)),(f['finding_id'],r['track'],cid,v,expected)
                if source:assert t==source['time_min']
                points+=1
    paths=['START_HERE_ASTRA.md','reader/READ_ME.md','reader/TEMPORAL_EVIDENCE.md']
    link_count=0
    for name in paths:
        for link in re.findall(r'\]\(([^)]+)\)',(package/name).read_text()):
            if re.match(r'https?://',link):continue
            if not (package/name).parent.joinpath(link.split('#')[0]).is_file():raise ValueError('Missing relative link: '+name+' -> '+link)
            link_count+=1
    # Choose examples by the retained order, not a pathway expectation.
    examples=projected['findings'][:2]
    extra=next((f for f in projected['findings'][2:] if any(e['row']['support_status']=='computed' for c in f['candidates'] for e in c['exclusions'])),None)
    if extra:examples.append(extra)
    examples=[{'finding_id':f['finding_id'],'form_id':f['form_id'],'label':f['label'],
               'ptm_A':next((e for e in f['features'] if e['role']=='ptm' and e['row']['track']=='A'),None),
               'intervals':f['intervals'], 'first_candidate_with_computed_exclusion':next((c for c in f['candidates'] if any(e['row']['support_status']=='computed' for e in c['exclusions'])),None)} for f in examples]
    changed=[name for name in baseline['files'] if digest(before/name)!=digest(package/name)]
    allowed={'reader/packet.csv','reader/authoring_packet.json','reader/question_map.json','reader/READ_ME.md',
             'START_HERE_ASTRA.md','evidence_report.html','provenance.json','reproducibility/data_dictionary.json','study/analysis_plan.json',
             *('reproducibility/code/ptm_shared/'+n for n in ['astra_reader.py','astra_reader_revision.py','astra_evidence_v6.py'])}
    if set(changed)-allowed:raise ValueError('Unexpected file change: '+str(set(changed)-allowed))
    return {'passed':True,'parent_run_id':before.name,'run_id':package.name,
        'scientific_recalculation':False,'preserved_dictionary_tables':len(dictionary)-1,
        'quant_csv_preserved':len([n for n in dictionary if n.startswith('quant/')]),
        'figures_preserved':len([n for n in baseline['files'] if n.startswith('figures/')]),
        'preserved_hashes':{name:digest(package/name) for name in preserved},
        'original_packet_except_temporal_additions_equal':True,'finding_order': [f['finding_id'] for f in projected['findings']],
        'coverage':projected['coverage'],'source_inventory':projected['source_inventory'],
        'findings_with_candidate_contributions':sum(bool(f['candidates']) for f in projected['findings']),
        'exact_projected_rows_checked':checked,'feature_points_checked':points,
        'unique_finding_source_links':len(links),'relative_links_checked':link_count,
        'changed_files':changed,'examples_selection':'first_two_retained_findings_then_first_with_saved_computed_exclusion',
        'examples':examples,'native_method_replay':'not_repeated; method code/resources/inputs/results unchanged'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--before',type=Path,required=True);p.add_argument('--package',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=validate(a.before,a.package)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in {'examples','preserved_hashes','source_inventory','finding_order'}},ensure_ascii=False))


if __name__=='__main__':main()
