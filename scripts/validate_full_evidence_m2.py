"""Generate/audit a reader-only M2 revision; scientific computation is forbidden."""
import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

import pandas as pd
from ptm_shared.annotation_registry import digest
from ptm_shared.astra_evidence_catalog import EvidenceCatalog
from ptm_shared.astra_reader_revision import revise_temporal, read_tables
from ptm_shared.astra_reader_full import attach_full, project_full, validate_citations, PREFIX
from ptm_shared.generic_workflow import json_write


def audit(source,root):
    original=json.loads((source/'manifest.json').read_text())['files']
    preserve=[n for n in original if n.startswith(('quant/','science/','kinase/','temporal/','figures/','references/','reader_adapter/'))]
    preserve += [n for n in original if n.startswith('reader/literature') or n in ['reader/findings.csv','reader/coverage.csv','reader/selection_audit.json']]
    checks={n:{'before':digest(source/n),'after':digest(root/n)} for n in sorted(set(preserve))}
    assert all(v['before']==v['after'] for v in checks.values())
    old=pd.read_csv(source/'reader/cards.csv');new=pd.read_csv(root/'reader/cards.csv')
    assert old.drop(columns='card_json').equals(new.drop(columns='card_json'))
    changed=0
    for a,b in zip(old.card_json,new.card_json):
        a=json.loads(a);b=json.loads(b)
        changed+=a.get('question_ids')!=b.get('question_ids')
        a.pop('question_ids',None);b.pop('question_ids',None);assert a==b
    before=json.loads((source/'reader/authoring_packet.json').read_text());after=json.loads((root/'reader/authoring_packet.json').read_text())
    for k in ['original_questions','literature','literature_comparison_status','coverage_inventory','temporal_evidence','module_evidence_index','observation_selection_audit']:
        assert before.get(k)==after.get(k),k
    new_manifest=json.loads((root/'manifest.json').read_text())['files']
    changed_files=[n for n in original if digest(source/n)!=digest(root/n)]
    allowed={'reader/packet.csv','reader/cards.csv','reader/evidence_index.csv','reader/evidence_links.csv',
        'reader/evidence_catalog.json','reader/EVIDENCE_ACCESS.md','reader/authoring_packet.json','reader/question_map.json','reader/READ_ME.md',
        'reproducibility/data_dictionary.json','reproducibility/parent_reader_provenance.json',
        'reproducibility/temporal_reader_revision.json','reproducibility/temporal_reader_stage.json',
        'study/analysis_plan.json','provenance.json','START_HERE_ASTRA.md','evidence_report.html'}
    allowed.update('reproducibility/code/ptm_shared/'+n for n in ['astra_reader_full.py','astra_evidence_catalog.py',
        'astra_package.py','astra_reader.py','astra_reader_revision.py','astra_reader_temporal.py'])
    assert set(changed_files)<=allowed, sorted(set(changed_files)-allowed)
    c=EvidenceCatalog(root);run=json.loads((root/'provenance.json').read_text())['run_id']
    examples={};citations=[]
    for form in ['form_97aa4b58cee5c391','form_6618452f34b3cbbc','form_92f581e44d9b44cf','form_eeaed22a5119b2f5','form_9951a8944f668c17']:
        items=c.query({'form_id':form,'evidence_type':'raw_ptm'},page_size=10000)['items']
        examples[form]=[]
        for item in items:
            row=c.resolve([item['evidence_id']])[0]['source_row'];raw=json.loads(row['row_json'])
            examples[form].append({k:raw.get(k) for k in ['form_id','contrast_id','time_min','reference_condition_id','U_joint','P_joint','A','included','exclusion_reasons']})
        item=items[0];citations.append({'run_id':run,'catalog_id':c.catalog['catalog_id'],'evidence_id':item['evidence_id'],
            'source_table':item['source_table'],'source_key':json.loads(item['source_key_json'])})
    validate_citations(c,citations)
    return {'run_id':run,'preserved_files':checks,'quant_csv_count':sum(n.startswith('quant/') and n.endswith('.csv') for n in checks),
        'card_count':len(new),'only_card_question_relationships_changed':changed,'all_card_values_ID_NA_scope_unchanged':True,
        'old_question_text_literature_selection_temporal_preserved':True,'examples':examples,'validated_citations':citations,
        'changed_existing_files':changed_files,'added_files':sorted(set(new_manifest)-set(original)),
        'all_other_manifest_files_byte_identical':True,'whole_scope':json.loads((root/'reader/full_evidence_summary.json').read_text())}


def selection_sweep(root):
    """Saved all-card inputs, real existing selection function, frozen literature."""
    from ptm_shared.measured_feature_cards import select_finding_cards
    from ptm_shared.astra_reader import finding_id_for_card
    tables=read_tables(root);cards=[json.loads(r.card_json) for r in tables['reader/cards'].itertuples()]
    obs=[c for c in cards if c['category']=='measured_feature_observation']
    catalog=EvidenceCatalog(root).catalog;reference=None;results=[]
    for maximum in [5,15,50,0]:
        selected,_=select_finding_cards(obs,maximum=maximum or 15)
        if maximum==0:selected=[]
        selected_ids={c['card_id'] for c in selected}
        variant=dict(tables);variant['reader/cards']=tables['reader/cards'].copy()
        variant['reader/cards']['selected']=variant['reader/cards'].card_id.isin(selected_ids)
        variant['reader/findings']=pd.DataFrame([{'finding_id':finding_id_for_card(c['card_id']),'card_id':c['card_id'],'form_id':c['form_id']} for c in selected],columns=['finding_id','card_id','form_id'])
        variant['reader/packet']=tables['reader/packet'].copy()
        packet=json.loads(variant['reader/packet'].iloc[0].packet_json)
        states={c['consumer_state_id'] for c in selected}
        packet['reader_cards']=[c for c in cards if c['card_id'] in selected_ids or
            (c['category']=='quantitation_comparison' and c['consumer_state_id'] in states)]
        for q in packet['research_question_evidence_map']['questions']:
            q['finding_ids']=[finding_id_for_card(c['card_id']) for c in selected if c['card_id'] in q['evidence_ids']]
        variant['reader/packet'].iloc[0,variant['reader/packet'].columns.get_loc('packet_json')]=json.dumps(packet)
        attach_full(variant)
        projected,summary=project_full(variant,catalog)
        signatures={name: __import__('hashlib').sha256(frame.to_csv(index=False).encode()).hexdigest() for name,frame in projected.items()}
        if reference is None:reference=signatures
        assert signatures==reference
        results.append({'maximum':maximum,'selected':len(selected),'full_projection_sha256':signatures,'identical':True})
        print('selection_sweep',maximum,flush=True)
    return results


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--package',type=Path)
    p.add_argument('--selection-sweep',action='store_true');a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    started=time.monotonic()
    with patch('ptm_shared.astra_package.compute_science',side_effect=AssertionError('Scientific recalculation forbidden')), \
         patch('ptm_shared.astra_literature.collect',side_effect=AssertionError('Literature retrieval forbidden')):
        if a.package:root=a.package
        else:
            result=revise_temporal(a.source,a.output/'revision',whole_only=True)
            json_write(a.output/'REVISION_RESULT.json',result)
            root=a.output/'revision/enrichment_free_runs'/result['run_id']
        report=audit(a.source,root);print('preservation_audit_passed',flush=True)
        if a.selection_sweep:report['selection_sweep']=selection_sweep(root)
    replay=a.output/'reader-replay'
    subprocess.run([sys.executable,'scripts/replay_astra_reader.py','--package',str(root),'--output',str(replay)],check=True,
                   stdout=(a.output/'reader-replay.log').open('w'),stderr=subprocess.STDOUT)
    report['reader_replay']=json.loads((replay/'READER_REPLAY_VALIDATION.json').read_text())
    report.update(package_path=str(root),elapsed_seconds=time.monotonic()-started,scientific_recalculation=False,new_external_searches=0)
    json_write(a.output/'FULL_EVIDENCE_M2_VALIDATION.json',report)
    json_write(a.output/'citations.json',report['validated_citations'])
    print(json.dumps({'passed':True,'run_id':report['run_id'],'elapsed_seconds':report['elapsed_seconds']}))


if __name__=='__main__':main()
