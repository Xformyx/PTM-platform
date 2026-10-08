"""Report consumers must preserve identity, masks, questions and raw exclusions."""
import json
from pathlib import Path
from unittest.mock import patch
import pandas as pd
import pytest

from ptm_shared.tests.test_astra_card_inputs import small, config, test_adapter_called_by_v6_and_portable_replay as _portable
from ptm_shared.astra_card_inputs import project_card_inputs
from ptm_shared import astra_reader as reader


def projected(small):
    tables,inputs,design=small
    return {**tables,**project_card_inputs(tables,inputs,design,{})},design


def test_existing_consumers_all_values_missing_grids_identity_and_scope(small):
    tables,design=projected(small)
    snapshot={'original':{'analysis_context':{'biological_question':'  PTM protein adjustment at 30 min\n한글 원문  '},
                         'report_options':{'research_questions':['When is the observed peak?', 'Does it cause kinase activation?']}}}
    with patch.object(reader,'build_feature_observation_cards',wraps=reader.build_feature_observation_cards) as observe, \
         patch.object(reader,'build_quantitation_comparison_cards',wraps=reader.build_quantitation_comparison_cards) as compare, \
         patch.object(reader,'select_finding_cards',wraps=reader.select_finding_cards) as select, \
         patch.object(reader,'build_authoring_packet',wraps=reader.build_authoring_packet) as author:
        result=reader.build_reader_tables(tables,design,snapshot)
    assert observe.call_count==6 and compare.call_count==6 and select.call_count==author.call_count==1
    assert reader.validate_reader({**tables,**result})['values_times_NA_masks_ids']=='passed'
    packet=json.loads(result['reader/packet'].iloc[0].packet_json)
    assert packet['original_questions']['biological_question']==snapshot['original']['analysis_context']['biological_question']
    q=packet['research_question_evidence_map']['questions'][0]
    assert q['original_text']==packet['original_questions']['biological_question']
    assert q['finding_ids'] and q['answer_status']=='partially_answerable'
    coverage=packet['coverage_inventory']
    assert coverage['total_form_contrasts']==36 and coverage['card_grid_rows']==18 and coverage['card_numeric_rows']==12
    assert coverage['card_missing_timepoints']==6 and coverage['fully_withheld_forms']==3
    assert len(result['reader/findings'])==6  # different taxa and reference scopes retained
    assert set(result['reader/findings'].form_id)=={'single','multisite','mouse'}
    assert all('not_performed'==c['literature_comparison_status'] for c in packet['reader_cards'])
    for c in packet['reader_cards']:
        if not c.get('trajectory'):continue
        assert [p['time_minutes'] for p in c['trajectory']]==[30,60,120]
        assert c['trajectory'][1]['axes']['adjusted']['value'] is None
        assert c['trajectory'][0]['axes']['adjusted']['treatment_biological_n']==1
        assert c['source_bindings'][0]['U_all']==3 and c['source_bindings'][0]['U_joint']==2
        assert len({b['reference_condition_id'] for b in c['source_bindings']})==1
    # Source ordering and question expectations cannot alter finding selection.
    shuffled={k:v.sample(frac=1,random_state=42).reset_index(drop=True) for k,v in tables.items()}
    again=reader.build_reader_tables(shuffled,design,snapshot)
    assert result['reader/findings'].finding_id.tolist()==again['reader/findings'].finding_id.tolist()
    changed=reader.build_reader_tables(tables,design,{'original':{'analysis_context':{'biological_question':'EGF AKT insulin'}}})
    assert result['reader/findings'].finding_id.tolist()==changed['reader/findings'].finding_id.tolist()


def test_no_call_empty_questions_and_withheld_rows_are_not_invented(small):
    tables,design=projected(small)
    tables['science/inference_results']=pd.DataFrame([{'inference_status':'abstained'}])
    result=reader.build_reader_tables(tables,design,{'original':{'report_options':{'research_questions':[]}}})
    packet=json.loads(result['reader/packet'].iloc[0].packet_json)
    assert packet['inference_status_counts']=={'abstained':1} and len(result['reader/findings'])>0
    assert packet['original_questions']['research_questions']==[]
    withheld=result['reader/coverage'].query("card_status == 'withheld'")
    assert set(withheld.form_id)=={'collapsed','mixed','parent_missing'}
    assert withheld.reason.str.contains('multiple_precursors_not_representable').any()
    assert withheld.reason.str.contains('mixed_or_unknown_taxon_not_representable').any()
    # No fallback to U_all and no fabricated identity when nothing is card-compatible.
    tables['reader_adapter/form_contrasts']['card_input_eligible']=False
    empty=reader.build_reader_tables(tables,design)
    assert empty['reader/findings'].empty and empty['reader/cards'].empty
    reader.validate_reader({**tables,**empty})


def test_tampered_value_or_reference_rejected(small):
    tables,design=projected(small);result=reader.build_reader_tables(tables,design)
    c=json.loads(result['reader/cards'].iloc[0].card_json)
    c['trajectory'][0]['axes']['adjusted']['control_sample_ids']=['invented_injection']
    result['reader/cards'].loc[0,'card_json']=json.dumps(c)
    with pytest.raises(ValueError,match='joint mask'):reader.validate_reader({**tables,**result})


def test_shared_functions_are_same_callable():
    from scripts.validate_astra_card_inputs import card_builders
    old_observe,old_compare=card_builders()
    from ptm_shared.measured_feature_cards import build_feature_observation_cards,build_quantitation_comparison_cards
    from report_generation.core.reader_authoring import serialize_authoring_packet
    assert old_observe is build_feature_observation_cards and old_compare is build_quantitation_comparison_cards
    assert serialize_authoring_packet is reader.build_authoring_packet


def test_real_v6_package_invocation_and_offline_reader_replay(config,tmp_path):
    from ptm_shared import astra_evidence_v6 as engine
    with patch.object(engine,'build_reader_tables',wraps=engine.build_reader_tables) as spy:
        _portable(config,tmp_path)
    assert spy.call_count==1
    replay=json.loads((tmp_path/'offline/replay_result.json').read_text())
    assert len(replay['reader_artifacts'])==8 and all(r['byte_equal'] for r in replay['reader_artifacts'])
    root=next((tmp_path/'out/enrichment_free_runs').iterdir())
    assert '[reader/READ_ME.md](reader/READ_ME.md)' in (root/'START_HERE_ASTRA.md').read_text()
    reader_text=(root/'reader/READ_ME.md').read_text()
    assert '| --- |' in reader_text and '\n\n| --- |' not in reader_text
    import re
    for link in re.findall(r'\]\(([^)]+)\)',reader_text):assert (root/'reader'/link).is_file(),link
