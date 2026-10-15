"""Audit an M1 reader revision against saved source bytes, without recalculation."""
import argparse
import json
from pathlib import Path

from ptm_shared.annotation_registry import digest
from ptm_shared.astra_evidence_catalog import EvidenceCatalog, REQUIRED, read_source, encode
from ptm_shared.astra_reader_temporal import source_row


def validate(baseline, revised):
    old=json.loads((baseline/'manifest.json').read_text())
    dictionary=json.loads((baseline/'reproducibility/data_dictionary.json').read_text())
    c=EvidenceCatalog(revised)
    preserved=[name for name in dictionary if name!='reader/packet.csv']
    preserved += [name for name in old['files'] if name.startswith(('figures/','references/'))]
    checks={name:{'baseline':digest(baseline/name),'revision':digest(revised/name)} for name in sorted(set(preserved))}
    assert all(v['baseline']==v['revision'] for v in checks.values())
    accounting={}
    for name in REQUIRED:
        meta=c.catalog['sources'][name];keys=meta['unique_key']
        original={encode(dict(zip(keys,values))) for chunk in read_source(baseline,name,meta,columns=keys,chunksize=20000)
                  for values in chunk[keys].itertuples(index=False,name=None)}
        found=c.index.loc[c.index.source_table.eq(name)]
        assert set(found.source_key_json)==original and len(found)==len(original)
        accounting[name]={'rows':len(found),'unique_keys':len(original),'missing':0,'duplicate_keys':0}
    coverage=json.loads((baseline/'reader/coverage_summary.json').read_text())
    assert coverage['card_numeric_rows']+coverage['card_missing_timepoints']+coverage['withheld_rows']==coverage['total_form_contrasts']
    # Traverse whole index, not only summary. Distinct page sizes produce the same order/set.
    populations=[]
    for size in [701,10000]:
        cursor=None;seen=[]
        while True:
            page=c.query({},cursor,size);seen.extend(r['evidence_id'] for r in page['items']);cursor=page['next_cursor']
            if cursor is None:break
        assert len(seen)==len(set(seen))==page['total_count'];populations.append(seen)
    assert populations[0]==populations[1]
    examples={}
    cases={'MAPK1':'form_97aa4b58cee5c391','GSK3A':'form_6618452f34b3cbbc','PTPRK':'form_92f581e44d9b44cf',
           'TAOK1':'form_09766dc39811d4c7','IRS1':'form_9951a8944f668c17','MAPK3':'form_eeaed22a5119b2f5',
           'INSR_shared':'form_d4f68593541e8e86'}
    # These IDs are documented g10 acceptance examples, never production exceptions.
    for label,fid in cases.items():
        query=c.query({'form_id':fid,'source_table':'quant/comparisons.csv'})
        if not query['items']:
            examples[label]={'status':'not_in_this_fixture'};continue
        resolved=c.resolve([r['evidence_id'] for r in query['items']])
        rows=[r['source_row'] for r in resolved]
        exact=c.source_rows('quant/comparisons.csv',[r['source_ref']['key'] for r in resolved])
        assert rows==exact
        detection=c.query({'form_id':fid,'evidence_type':'detection'})
        detected=[r['source_row'] for r in c.resolve([r['evidence_id'] for r in detection['items']])]
        adapter=c.query({'form_id':fid,'evidence_type':'raw_ptm'})
        examples[label]={'status':'resolved','form_id':fid,'selected_for_summary':any(r['selected_for_summary'] for r in query['items']),
            'comparisons':[{k:r.get(k) for k in ['form_id','contrast_id','arm_id','reference_condition_id','pairing','time_min','U_joint','P_joint','A','included','exclusion_reasons']} for r in rows],
            'detection':[{k:r.get(k) for k in ['contrast_id','baseline_status','time_min','post_reference_time_min','post_reference_U','use_restriction']} for r in detected],
            'adapter_states':[json.loads(r['status_json']) for r in adapter['items']]}
        if label=='TAOK1':
            links=c.resolve_links([r['evidence_id'] for r in query['items']],['substrate_contribution_from'])['links']
            keys=list({r['from_key_json']:json.loads(r['from_key_json']) for r in links}.values())
            contributions=c.source_rows('kinase/substrate_contributions.csv',keys)
            examples[label]['contribution_candidate_ids']=sorted({r['candidate_id'] for r in contributions})
            examples[label]['contribution_ids']=sorted(r['contribution_id'] for r in contributions)
            examples[label]['precursor_memberships']=c.resolve_links([fid],['precursor_member_of'])['links']
        if label=='PTPRK':
            examples[label]['parent_context_links']=c.resolve_links([r['evidence_id'] for r in query['items']],['same_experiment_parent_context'])['links']
    method_examples={}
    for gene in ['AKT1','AKT2','AKT3']:
        page=c.query({'entity':gene,'evidence_type':'method_result','method_id':'PhosX_native_functions'})
        rows=[r['source_row'] for r in c.resolve([r['evidence_id'] for r in page['items']])]
        assert len(rows)==6 and all(r['status']=='insufficient_coverage' for r in rows)
        method_examples[gene]=rows
    finding_bytes=digest(baseline/'reader/findings.csv')==digest(revised/'reader/findings.csv')
    assert finding_bytes
    return {'baseline_run_id':json.loads((baseline/'provenance.json').read_text())['run_id'],
        'revision_run_id':json.loads((revised/'provenance.json').read_text())['run_id'],
        'source_accounting':accounting,'coverage':coverage,'index_rows':len(c.index),'stored_links':len(c.links),
        'catalog_sources':len(c.catalog['sources']),'pagination':{'page_sizes':[701,10000],'same_ids_order_count':True},
        'examples':examples,'method_examples':method_examples,'preserved_hashes':checks,
        'preserved_quant_csv':sum(n.startswith('quant/') for n in checks),'preserved_figures':sum(n.startswith('figures/') for n in checks),
        'findings_ids_order_bytes_preserved':finding_bytes,'new_external_searches':0,
        'scientific_calculation':'not_run','review_status':'not_recorded'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--revision',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();result=validate(a.baseline,a.revision)
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:result[k] for k in ['baseline_run_id','revision_run_id','index_rows','catalog_sources','preserved_quant_csv','preserved_figures']}))


if __name__=='__main__':main()
