"""Versioned question semantics; legacy bindings are never inferred from prose."""
from copy import deepcopy
import json
from unittest.mock import patch
import pytest
from ptm_shared.astra_inputs import capture_order
from ptm_shared import astra_reader as reader
from ptm_shared.research_questions import build_question_map
from ptm_shared.tests.test_astra_reader import small, projected


def card(gene='Mapk1', taxon='10116', cid='rat', accession='P1'):
    return {'card_id':cid, 'feature_identity':{'gene':gene, 'fasta_taxonomy_id':taxon,
            'protein_group':accession, 'feature_id':'feature-'+cid, 'reader_feature_id':'reader-'+cid},
            'evidence_ids':[cid], 'category':'measured_feature_observation',
            'trajectory':[{'time_minutes':30,'axes':{k:{'available':True} for k in ['unadjusted','protein','adjusted']}}]}


def test_new_design_role_empty_questions_and_explicit_id_legacy_compatibility():
    text='Astral DIA/DIA-NN 실험 설계\nMAPK1의 측정 목적'
    snapshot=capture_order({'id':1,'analysis_context':{'biological_question':text},'report_options':{'research_questions':[]}})
    raw, questions=reader._questions(snapshot,{'recorded_context':{}})
    assert not questions and raw['biological_question']==text and raw['biological_question_role']=='study_design_context'
    old=deepcopy(snapshot);old.pop('context_contract');old['schema_version']='astra_research_input.v1'
    old_raw, old_questions=reader._questions(old,{'recorded_context':{}})
    assert old_questions==[{'text':text,'question_id':'BQ-001','origin':'analysis_context.biological_question'}]
    assert 'biological_question_role' not in old_raw
    snapshot['original']['report_options']['research_questions']=[{'text':'MAPK1 time?', 'question_id':'RQ-saved'}]
    assert reader._questions(snapshot,{'recorded_context':{}})[1][0]['question_id']=='RQ-saved'
    # BQ presence/text does not opt a legacy execution into a new contract.
    assert old_questions==reader._questions(old,{'recorded_context':{}})[1]


@pytest.mark.parametrize('extra',['',' with Astral DIA/DIA-NN FASTA acquisition'])
def test_measured_gene_case_and_technical_terms_do_not_block(extra):
    questions=build_question_map(['MAPK1 temporal response'+extra], [card(),card('Akt1',cid='other')], entity_contract='measured_identity.v1')['questions']
    q=questions[0]
    assert q['evidence_ids']==['rat'] and q['entities']==['Mapk1']
    if extra:
        assert {'DIA','NN','FASTA'} <= {r['term'] for r in q['entity_resolution']['unresolved_terms']}
        assert not any(r['hard_filter'] for r in q['entity_resolution']['unresolved_terms'])
    assert q['entity_resolution']['resolved'][0]['candidates'][0]['taxon']=='10116'


def test_verified_accession_alias_and_ambiguous_taxon_family():
    inventory=[{'accession':'P1','raw_identifier':'sp|P1|MAPK1_RAT','gene':'Mapk1','taxon':'10116'}]
    q=build_question_map(['P1 temporal response'], [card()], entity_contract='measured_identity.v1',reference_inventory=inventory)['questions'][0]
    assert q['evidence_ids']==['rat'] and q['entities']==['Mapk1']
    bad=build_question_map(['P1 temporal response'], [card()], entity_contract='measured_identity.v1',reference_inventory=[{**inventory[0],'taxon':'9606'}])['questions'][0]
    assert not bad['entities'] and bad['answerability']=='relevance_unresolved'
    q=build_question_map(['mapk1 temporal response'], [card(),card('MAPK1','9606','human','P2')],entity_contract='measured_identity.v1')['questions'][0]
    assert q['evidence_ids']==['human','rat'] and q['entity_resolution']['resolved'][0]['status']=='ambiguous_taxon_or_identity'
    scoped=build_question_map([{'text':'mapk1 temporal response','taxon_id':'10116'}], [card(),card('MAPK1','9606','human','P2')],entity_contract='measured_identity.v1')['questions'][0]
    assert scoped['evidence_ids']==['rat']
    family=build_question_map(['AKT time response'],[card('Akt1')],entity_contract='measured_identity.v1')['questions'][0]
    assert not family['entities'] and family['answerability']=='relevance_unresolved'


def test_new_reader_whole_question_links_independent_of_selection(small):
    tables, inputs, design=small
    tables['quant/summary']['Genes']='Mapk1'
    from ptm_shared.astra_card_inputs import project_card_inputs
    tables.update(project_card_inputs(tables,inputs,design,{}))
    snapshot=capture_order({'id':1,'analysis_context':{'biological_question':'DIA-NN design'},
        'report_options':{'research_questions':['MAPK1 temporal response with DIA-NN FASTA']}})
    choose=reader.select_finding_cards; populations=[]
    for n in [0,5,15,50]:
        def selection(cards,**kw):
            selected,audit=choose(cards,maximum=max(1,n))
            return selected[:n],audit
        with patch.object(reader,'select_finding_cards',side_effect=selection):
            result=reader.build_reader_tables(tables,design,snapshot)
        packet=json.loads(result['reader/packet'].iloc[0].packet_json)
        q=packet['research_question_evidence_map']['questions']
        assert [x['question_id'] for x in q]==['RQ-001'] and q[0]['evidence_ids']
        populations.append(q[0]['evidence_ids'])
        assert packet['coverage_inventory']['withheld_rows']>0
        assert packet['original_questions']['biological_question']=='DIA-NN design'
        assert reader.validate_reader({**tables,**result})['values_times_NA_masks_ids']=='passed'
    assert all(p==populations[0] for p in populations)
