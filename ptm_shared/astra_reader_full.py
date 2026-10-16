"""M2: complete question/module/temporal access to saved evidence.

No selection, scientific calculation, retrieval or semantic approval. Full
projections store locators; M1's catalog/resolver remains the row authority.
"""
from collections import Counter, defaultdict
import json
from pathlib import Path

import pandas as pd

from .astra_card_inputs import encode
from .astra_inputs import stable_id
from .astra_evidence_catalog import (EvidenceCatalog, evidence_id_for, CATALOG,
                                     read_source)
from .astra_reader_temporal import project_temporal, source_row, KEYS, SERIES, PROTEIN, validate_feature_scope
from .reader_authoring import build_module_evidence_index
from .annotation_registry import digest
from .generic_workflow import json_write, object_hash

VERSION = 'whole_reader_evidence.v1'
PREFIX = 'reader/full_'
TABLE_KEYS = {PREFIX+'question_links':['link_id'], PREFIX+'temporal_links':['link_id'],
              PREFIX+'temporal_subjects':['subject_id'], PREFIX+'module_membership':['bundle_id','evidence_id']}
ARTIFACTS = [name+'.csv' for name in TABLE_KEYS] + [PREFIX+'evidence_summary.json', 'reader/FULL_EVIDENCE.md']
LINK_COLUMNS = ['link_id','subject_evidence_id','source_table','source_key_json','evidence_id','role','status','reason']
QUESTION_COLUMNS = ['link_id','question_id','subject_evidence_ids_json','source_table','source_key_json','evidence_id','role','status','reason']
ROLES = ['direct_observation','parent_context','method_context','detection','opposing_observation','limitation','literature_context']


def attach_full(tables):
    """All-card question inheritance; preserve selection, original text and review."""
    cards = [json.loads(r.card_json) for r in tables['reader/cards'].itertuples()]
    observations = [c for c in cards if c['category']=='measured_feature_observation']
    packet = json.loads(tables['reader/packet'].iloc[0].packet_json)
    questions = packet['research_question_evidence_map']['questions']
    # Existing build_question_map already matches ALL observations. Do not route
    # questions anew or replace saved literature/answerability decisions.
    known = {c['card_id'] for c in observations}
    states = defaultdict(set)
    for q in questions:
        matches = set(q['evidence_ids'])
        if not matches <= known: raise ValueError('Question references unknown observation card')
        for c in observations:
            if c['card_id'] in matches: states[c['consumer_state_id']].add(q['question_id'])
        q['whole_evidence'] = {'links':PREFIX+'question_links.csv','filter':{'question_id':q['question_id']},
            'observation_evidence_ids':sorted(matches), 'unmatched_observation_count':len(known-matches),
            'scope':'existing all-observation matching plus exact saved context links; not automatic review',
            'temporal_links':PREFIX+'temporal_links.csv', 'literature_scope':'frozen existing comparisons only; new review subjects deferred'}
    changed = tables['reader/cards'].copy()
    by_card = {}
    for i,c in enumerate(cards):
        if c['category']=='quantitation_comparison': c['question_ids']=sorted(states[c['consumer_state_id']])
        changed.iloc[i, changed.columns.get_loc('card_json')] = encode(c)
        by_card[c['card_id']] = c
    tables['reader/cards'] = changed
    packet['reader_cards'] = [by_card[c['card_id']] for c in packet['reader_cards']]
    packet['whole_evidence'] = {'schema_version':VERSION,'guide':'reader/FULL_EVIDENCE.md',
        'question_links':PREFIX+'question_links.csv','temporal_links':PREFIX+'temporal_links.csv',
        'temporal_subjects':PREFIX+'temporal_subjects.csv','module_membership':PREFIX+'module_membership.csv',
        'summary':PREFIX+'evidence_summary.json','preview_scope':'reader_cards and findings only',
        'review_status':'not_recorded','literature_execution_scope':'unchanged; M3/M4 not performed'}
    rules=packet['authoring_rules']
    rules['required_evidence_anchor']=('Use a typed citation with run_id, catalog_id, evidence_id, source_table and exact source_key. '
        'Validate using ptm_shared.astra_reader_full. Unselected and withheld evidence is citable within its recorded restrictions. '
        'Legacy card/finding markers remain preview aliases; a marker alone never authorizes a new claim.')
    rules['whole_temporal_evidence']={'source_index':PREFIX+'temporal_links.csv','subjects':PREFIX+'temporal_subjects.csv',
        'required_anchor':'Use subject_evidence_id and a validated source_table + canonical key (feature/interval/cowave or composite key); summary finding_id is optional.'}
    rules['whole_evidence_reading_order']=['whole denominators and original questions','question links and unresolved roles',
        'resolve necessary original rows including unselected/withheld','summary findings','saved temporal/method/literature evidence']
    rules['reading_order']=reading_order()
    if 'evidence_access' in packet:
        packet['evidence_access']['limits']='Whole question/module/temporal access is available. Literature review execution remains the frozen original scope (M3/M4 deferred).'
    tables['reader/packet'].loc[tables['reader/packet'].index[0],'packet_json']=json.dumps(packet,ensure_ascii=False,sort_keys=True)


def reading_order():
    return [{'step':i+1,'purpose':purpose,'paths':paths} for i,(purpose,paths) in enumerate([
        ('Whole denominators, original questions and readiness',['reader/FULL_EVIDENCE.md','reader/coverage_summary.json','reader/question_map.json','evidence/readiness.json']),
        ('Question evidence and unresolved scope',[PREFIX+'question_links.csv','reader/EVIDENCE_ACCESS.md']),
        ('Resolve necessary original rows',['reader/evidence_catalog.json','reader/cards.csv','quant/comparisons.csv']),
        ('Summary preview',['reader/findings.csv','reader/READ_ME.md']),
        ('Saved temporal, methods and literature',[PREFIX+'temporal_links.csv','reader/TEMPORAL_EVIDENCE.md','reader/PHOSX_TIME_COURSE.md','reader/LITERATURE.md'])])]


def project_full(tables, catalog):
    """Resolve source keys from the M1 registry; no duplicated numerical payload."""
    packet=json.loads(tables['reader/packet'].iloc[0].packet_json)
    cards=[json.loads(r.card_json) for r in tables['reader/cards'].itertuples()]
    observations=[c for c in cards if c['category']=='measured_feature_observation']
    sources=catalog['sources']
    def ref(name,row):
        name=name if name.endswith('.csv') else name+'.csv'
        if name not in sources: raise ValueError('Unregistered full-evidence source: '+name)
        key={k:source_row(row)[k] for k in sources[name]['unique_key']}
        return name, encode(key), evidence_id_for(name,key)
    temporal={}; subjects=[]
    def bind(subject,name,row,role):
        table,key,eid=ref(name,row)
        lid=stable_id('whole_temporal_link',[subject,table,key,role])
        temporal[lid]=dict(zip(LINK_COLUMNS,[lid,subject,table,key,eid,role,'linked',None]))
    all_subjects=[{**c,'subject_id':c['card_id']} for c in observations]
    covered={(c['form_id'],b['arm_id'],b['reference_condition_id'],b['pairing']) for c in observations for b in c['source_bindings']}
    raw_groups=defaultdict(list)
    for r in tables['reader_adapter/form_contrasts'].itertuples():
        b=json.loads(r.row_json); scope=(r.form_id,b['arm_id'],b['reference_condition_id'],b['pairing'])
        if scope not in covered: raw_groups[scope].append(b)
    # A raw subject is explicitly a form/scope, never a fabricated observation card.
    for scope,bindings in sorted(raw_groups.items(),key=lambda x:encode(x[0])):
        all_subjects.append({'subject_id':stable_id('raw_temporal_subject',scope),'form_id':scope[0],
            'feature_label':scope[0], 'source_bindings':bindings,'card_id':None})
    data=project_temporal(tables,packet,subjects=all_subjects,links_only=True)
    for item in data['findings']:
        sid=item['finding_id']; scope=item.get('scope',{})
        subjects.append({'subject_id':sid,'subject_type':'observation' if item['card_id'] else 'raw_form_scope',
            'source_table':'reader/cards.csv' if item['card_id'] else 'quant/summary.csv',
            'source_key_json':encode({'card_id':item['card_id']} if item['card_id'] else {'form_id':item['form_id']}),
            'scope_json':encode(scope),'status':item['status'],'reasons_json':encode(item['reasons'])})
    for link in data['links']:
        for role in link['roles']: bind(link['finding_id'],link['source_table'],link['source_key'],role)
    # Protein and native methods use their own canonical identities, never a
    # kinase's self-phosphosite or matching gene label. Native scores acquire no
    # descriptive footprint peak/onset semantics.
    series_rows=tables.get(SERIES,pd.DataFrame()).to_dict('records')
    by_contrast=defaultdict(list)
    for s in series_rows:
        for cid in str(s['contrast_ids']).split(';'): by_contrast[cid].append(s)
    protein_features=defaultdict(list)
    for r in tables.get(PROTEIN,pd.DataFrame()).to_dict('records'):
        protein_features[r['entity_id'],r['series_id'],r['track']].append(r)
    for name,kind in [('quant/protein_contrasts','protein'),('kinase/method_scores','method_result')]:
        for r in tables.get(name,pd.DataFrame()).to_dict('records'):
            table,key,eid=ref(name,r); matches=by_contrast[r['contrast_id']]
            reasons=[]; scope={}
            if len(matches)==1:
                s=matches[0];scope={k:s[k] for k in ['series_id','arm_id','reference_condition_id','pairing']}
                if any(k in r and r[k]!=s[k] for k in ['arm_id','reference_condition_id','pairing']): raise ValueError('Direct subject scope conflict')
                bind(eid,name,r,'native_method_observation' if kind=='method_result' else 'protein_observation')
                bind(eid,SERIES,s,'series')
                if kind=='protein':
                    fs=protein_features[r['protein_group'],s['series_id'],'PG']
                    if len(fs)==1:
                        validate_feature_scope(fs[0],s,packet['canonical_study_design'])
                        bind(eid,PROTEIN,fs[0],'protein_temporal_feature')
                    else: reasons.append('ambiguous_protein_feature' if fs else 'no_saved_protein_feature')
                else: reasons.append('native_method_has_no_new_temporal_feature; saved contrast only')
            else: reasons.append('ambiguous_series' if matches else 'no_saved_series')
            scope.update({k:r[k] for k in ['method_id','method_version'] if k in r})
            subjects.append({'subject_id':eid,'subject_type':kind,'source_table':table,'source_key_json':key,
                'scope_json':encode(scope),'status':'linked' if len(matches)==1 else 'ambiguous' if matches else 'unlinked',
                'reasons_json':encode(reasons)})
    modules=build_module_evidence_index(observations)
    membership=[{'bundle_id':b['bundle_id'],'evidence_id':cid,'source_table':'reader/cards.csv',
        'source_key_json':encode({'card_id':cid}), 'grouping':b['grouping'],'patterns_json':encode(b['patterns']),
        'review_status':b['review_status']} for b in modules['bundles'] for cid in b['member_card_ids']]
    questions={}; by_subject=defaultdict(list)
    found=set()
    for r in temporal.values(): by_subject[r['subject_evidence_id']].append(r)
    comparisons=defaultdict(list)
    for c in cards:
        if c['category']=='quantitation_comparison':comparisons[c['consumer_state_id']].append(c)
    detection=defaultdict(list); emergence=defaultdict(list); inference=defaultdict(list); method=defaultdict(list)
    for name,lookup in [('quant/detection',detection),('evidence/emergence_evidence',emergence)]:
        for r in tables.get(name,pd.DataFrame()).to_dict('records'):lookup[r['form_id'],r['contrast_id']].append(r)
    for r in tables.get('science/inference_results',pd.DataFrame()).to_dict('records'):
        inference[r.get('proposed_entity_id'),r.get('contrast_or_window_id'),r.get('track')].append(r)
    for r in tables.get('kinase/method_scores',pd.DataFrame()).to_dict('records'):
        method[r['candidate_id'],r['contrast_id']].append(r)
    native_members=defaultdict(list)
    for r in tables.get('kinase/method_membership',pd.DataFrame()).to_dict('records'):
        for form in str(r['form_ids']).split(';'):native_members[form,r['contrast_id']].append(r)
    # Frozen literature comparisons use stored card/finding identities only.
    from .astra_reader import finding_id_for_card
    # Match only aliases already present in frozen comparison rows. This neither
    # creates findings nor depends on the current summary selection.
    finding_card={finding_id_for_card(c['card_id']):c['card_id'] for c in observations}
    lit=defaultdict(list)
    for r in tables.get('reader/literature_comparisons',pd.DataFrame()).to_dict('records'):
        if r['finding_id'] in finding_card:lit[finding_card[r['finding_id']]].append(r)
    cards_by_id={c['card_id']:c for c in observations}
    def qlink(qid,subject,role,name=None,row=None,reason=None,relation_status=None):
        table,key,eid=ref(name,row) if name else (None,None,None)
        if table:found.add(role)
        lid=stable_id('whole_question_link',[qid,role,table,key,reason])
        entry=questions.setdefault(lid,dict(zip(QUESTION_COLUMNS,[lid,qid,set(),table,key,eid,role,relation_status or ('linked' if table else 'unresolved'),reason])))
        if subject is not None:entry['subject_evidence_ids_json'].add(subject)
    role_map={'parent_protein':'parent_context','parent_observation':'parent_context','form_parent_identity':'parent_context',
        'candidate_contribution':'method_context','descriptive_kinase':'method_context','available_footprint':'method_context',
        'fixed_footprint':'method_context','target_excluded':'limitation','gene_or_group_excluded':'limitation'}
    for q in packet['research_question_evidence_map']['questions']:
        qid=q['question_id']
        for cid in sorted(q['evidence_ids']):
            c=cards_by_id[cid]; found=set()
            qlink(qid,cid,'direct_observation','reader/cards',{'card_id':cid})
            for cp in comparisons[c['consumer_state_id']]:qlink(qid,cid,'direct_observation','reader/cards',{'card_id':cp['card_id']})
            for b in c['source_bindings']:
                key={'form_id':c['form_id'],'contrast_id':b['contrast_id']}
                qlink(qid,cid,'direct_observation','quant/comparisons',key)
                qlink(qid,cid,'limitation','reader/coverage',{'adapter_row_id':b['adapter_row_id']})
                for name,lookup in [('quant/detection',detection),('evidence/emergence_evidence',emergence)]:
                    for r in lookup[c['form_id'],b['contrast_id']]:qlink(qid,cid,'detection',name,r)
                for member in native_members[c['form_id'],b['contrast_id']]:
                    if member.get('selected') is not True:
                        continue  # Retained in canonical membership source, not a score contribution.
                    qlink(qid,cid,'method_context','kinase/method_membership',member)
                    for result in method[member['candidate_id'],member['contrast_id']]:
                        declared=str(result.get('membership_ids') or '').split(';')
                        if (result['method_id']==member['method_id'] and member['method_membership_id'] in declared
                                and result.get('input_universe_hash')==member.get('input_universe_hash')):
                            qlink(qid,cid,'method_context','kinase/method_scores',result)
                opposite=c.get('opposite_signed_observations',{})
                if opposite.get('status')=='both_signs_observed' and b['adapter_row_id'] in opposite.get('positive_A_rows',[])+opposite.get('negative_A_rows',[]):
                    qlink(qid,cid,'opposing_observation','quant/comparisons',key,'opposite signed levels, not independent counterexperiment')
            for t in by_subject[cid]:
                key=json.loads(t['source_key_json']); role=role_map.get(t['role'],'direct_observation')
                qlink(qid,cid,role,t['source_table'],key)
                if t['role']=='available_footprint':
                    for r in inference[key['candidate_id'],key['contrast_id'],key['track']]:qlink(qid,cid,'limitation','science/inference_results',r)
                    # Stored method membership must demonstrate exact track;
                    # a candidate ID alone is insufficient to infer equivalence.
            for r in lit[cid]:qlink(qid,cid,'literature_context','reader/literature_comparisons',r)
            for role in set(ROLES)-found:
                qlink(qid,cid,role,reason='no_existing_exact_context_link; no new review or identity inference')
        # Do not force withheld/raw-only forms through a precursor-card matcher.
        # Keep a typed, explicit unresolved question relation to their real source.
        for raw_subject in all_subjects:
            if raw_subject.get('card_id') is None:
                qlink(qid,raw_subject['form_id'],'limitation','quant/summary',{'form_id':raw_subject['form_id']},
                    'raw-only form: no compatible observation card for existing question matcher; relevance unresolved',
                    relation_status='unresolved')
        if not q['evidence_ids']:
            for role in ROLES:qlink(qid,None,role,reason=q.get('unresolved_reason') or 'no_matching_observation')
    for entry in questions.values():entry['subject_evidence_ids_json']=encode(sorted(entry['subject_evidence_ids_json']))
    outputs={PREFIX+'question_links':pd.DataFrame([questions[k] for k in sorted(questions)],columns=QUESTION_COLUMNS),
        PREFIX+'temporal_links':pd.DataFrame([temporal[k] for k in sorted(temporal)],columns=LINK_COLUMNS),
        PREFIX+'temporal_subjects':pd.DataFrame(subjects,columns=['subject_id','subject_type','source_table','source_key_json','scope_json','status','reasons_json']).sort_values('subject_id'),
        PREFIX+'module_membership':pd.DataFrame(membership,columns=['bundle_id','evidence_id','source_table','source_key_json','grouping','patterns_json','review_status']).sort_values(['bundle_id','evidence_id'])}
    full_used=defaultdict(set)
    for entry in temporal.values():full_used[entry['source_table']].add(entry['source_key_json'])
    inventory=[{'table':name+'.csv','total_rows':len(tables[name]),'linked_unique_rows':len(full_used[name+'.csv']),
        'outside_reader_rows':len(tables[name])-len(full_used[name+'.csv']),'retained':'full_source_table'}
        for name in [*KEYS,'kinase/method_scores'] if name in tables]
    summary={'schema_version':VERSION,'observation_cards':len(observations),'comparison_cards':len(cards)-len(observations),
        'module_bundles':len(modules['bundles']),'module_members':len(membership),
        'temporal_subjects':dict(Counter((r['subject_type']+':'+r['status']) for r in subjects)),
        'question_links_by_role_status':dict(Counter(r['role']+':'+r['status'] for r in questions.values())),
        'temporal_inventory':inventory,'form_subject_inventory':data['source_inventory'],
        'native_membership_scope':{'total_rows':len(tables.get('kinase/method_membership',[])),
            'selected_rows':sum(r.get('selected') is True for r in tables.get('kinase/method_membership',pd.DataFrame()).to_dict('records')),
            'count_unit':'canonical method membership rows; all selected/unselected rows remain in source',
            'unselected_question_link_policy':'not linked as contribution; use catalog source directly'},'review_status':'not_recorded','scientific_recalculation':False,
        'new_literature_queries':0,'limits':['Question routing remains the existing all-observation matcher; raw-only rows without a card are accessible but not forced into that contract.',
            'Context links do not establish independence, activity, causality or measured localization.',
            'Native method scores have direct source/series access; no gene-based attribution or new temporal feature.',
            'Existing literature links only; missing literature links do not imply counterevidence.'],
        'unmatched_observations':{q['question_id']:len(set(cards_by_id)-set(q['evidence_ids'])) for q in packet['research_question_evidence_map']['questions']}}
    return outputs,summary


def write_full(directory,tables,*,source_root=None):
    """Called by the production writer and the same offline revision/replay path."""
    from .astra_package import write_tables
    directory=Path(directory);root=Path(source_root or directory)
    catalog=json.loads((directory/CATALOG).read_text())
    outputs,summary=project_full(tables,catalog)
    # Check all exact endpoints against registered source keys in one pass per source.
    needed=defaultdict(set)
    for f in outputs.values():
        for r in f.to_dict('records'):
            if r.get('source_table'):needed[r['source_table']].add(r['source_key_json'])
    for name,keys in needed.items():
        meta=catalog['sources'][name];columns=meta['unique_key']
        known={encode({k:source_row(r)[k] for k in columns}) for r in read_source(root,name,meta,columns=columns).to_dict('records')}
        if not keys<=known:raise ValueError('Full evidence source FK mismatch: '+name)
    for name,frame in outputs.items():
        if frame.duplicated(TABLE_KEYS[name]).any():raise ValueError('Duplicate full reader key: '+name)
    entries=write_tables(outputs,directory)
    for name,meta in entries.items():
        meta.update(unique_key=TABLE_KEYS[name[:-4]],row_grain=TABLE_KEYS[name[:-4]],units='source locators; quantities and restrictions remain in original rows')
        catalog['sources'][name]={**meta,'sha256':digest(directory/name),'descriptor_schema_version':VERSION,
            'availability':'available' if meta['rows'] else 'available_empty','role':'whole_reader_projection','indexed':False,
            'access':'registered_source_and_canonical_key','independent_observation_count':None}
    if source_root is None:
        path=directory/'reproducibility/data_dictionary.json';dictionary=json.loads(path.read_text());dictionary.update(entries);json_write(path,dictionary)
    catalog['catalog_id']=object_hash({k:v for k,v in catalog.items() if k!='catalog_id'});json_write(directory/CATALOG,catalog)
    json_write(directory/(PREFIX+'evidence_summary.json'),summary)
    (directory/'reader/FULL_EVIDENCE.md').write_text(GUIDE,encoding='utf-8')
    guide=directory/'reader/EVIDENCE_ACCESS.md'
    guide.write_text(guide.read_text()+'\nM2 full question/module/temporal access: [instructions and typed citations](FULL_EVIDENCE.md). Only new literature review remains deferred to M3/M4.\n',encoding='utf-8')
    return ARTIFACTS


def validate_citations(catalog,citations):
    """Validate typed report anchors, not the scientific meaning of prose."""
    catalog._require()
    run_id=json.loads((catalog.root/'provenance.json').read_text())['run_id']
    checked=[]
    for citation in citations:
        if citation.get('run_id')!=run_id:raise ValueError('Citation run mismatch')
        if citation.get('catalog_id')!=catalog.catalog['catalog_id']:raise ValueError('Citation catalog mismatch')
        table=citation.get('source_table');key=citation.get('source_key')
        if not isinstance(key,dict):raise ValueError('Citation requires canonical source key')
        rows=catalog.source_rows(table,[key])
        if citation.get('evidence_id')!=evidence_id_for(table,key):raise ValueError('Citation evidence ID/key mismatch')
        checked.append({'citation':citation,'source_row':rows,'status':'source_anchor_validated','semantic_review':'not_performed'})
    return checked


GUIDE='''# 전체 근거의 질문·시간·작성 경로 (M2)

[전체 분모](coverage_summary.json) → [원문 질문과 답변 범위](question_map.json) →
[질문별 연결·미연결 역할](full_question_links.csv) → [catalog와 원본 조회](EVIDENCE_ACCESS.md) →
[요약 findings](findings.csv) → [전체 시간 연결](full_temporal_links.csv) / [방법](../kinase/method_scores.csv) / [기존 문헌](LITERATURE.md).

[범위와 제한](full_evidence_summary.json), [전체 subject 상태](full_temporal_subjects.csv),
[전체 observation 모듈](full_module_membership.csv), [작성 packet](authoring_packet.json).
요약의 개수와 무관하게 원본을 조회하고 인용할 수 있습니다. 원본 scope, NA, no-call, 보류 및 localization 미측정 제한을 유지하세요.
모듈은 기존 axis pattern별 기술적 묶음이며 kinase family나 인과 경로가 아닙니다.
시간은 저장된 feature/interval/cowave의 키로 해석하세요. Native 방법 점수에는 footprint peak 규칙을 적용하지 않습니다.
문헌 연결은 기존 결과만 포함합니다. 미연결은 반대 근거가 아니며 새 검색·승인은 수행하지 않았습니다.

source_table/source_key_json으로 M1 `source` 또는 `resolve`를 실행합니다. 전체 질문 연결에서 subject_evidence_ids_json은 해당 관계를 지지하는 원래 observation 카드 ID 목록이며, raw-only의 미연결 질문 행은 실제 form evidence ID를 사용합니다. 또한, temporal subject의 raw_form_scope는 카드가 아닌 원 form+scope입니다.
인용은 run_id, catalog_id, evidence_id, source_table, source_key를 함께 보관하고 아래 명령으로 검사하세요.
```sh
PYTHONPATH=PACKAGE/reproducibility/code python -m ptm_shared.astra_reader_full --package PACKAGE --citations citations.json
```
`run_id`는 provenance.json, `catalog_id`는 evidence_catalog.json에서 가져옵니다. 키/ID는 조회 결과에서 복사합니다.
이 검사는 출처 무결성 검사입니다. 접근 가능하거나 anchor가 유효하다는 사실은 실제 검토·과학적 의미 승인과 다릅니다.
'''


def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--package',required=True);p.add_argument('--citations',required=True)
    a=p.parse_args();print(encode(validate_citations(EvidenceCatalog(a.package),json.loads(Path(a.citations).read_text()))))


if __name__=='__main__':main()
