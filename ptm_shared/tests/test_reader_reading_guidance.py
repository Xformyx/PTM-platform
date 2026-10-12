"""A stored reader revision and fresh replay use one serialization contract."""
import json
from unittest.mock import patch
from ptm_shared.tests.test_astra_literature import reader, small, selection, Retriever, Model


def test_guidance_keeps_literature_status_questions_and_exact_packet_bytes(reader):
    from ptm_shared import astra_literature as lit
    from ptm_shared.astra_reader import attach_reading_guidance
    tables,design,snapshot=reader
    with patch('ptm_shared.finding_literature.time.sleep'):
        pin=lit.collect(tables,snapshot,selection(),retriever=Retriever(),llm=Model())
    lit.apply(tables,pin,snapshot,selection())
    before=tables['reader/packet'].iloc[0].packet_json
    prior=json.loads(before)
    attach_reading_guidance(tables)
    after=tables['reader/packet'].iloc[0].packet_json
    assert after==before
    packet=json.loads(after)
    assert packet['literature']==prior['literature']
    assert packet['original_questions']==prior['original_questions']
    assert packet['authoring_rules']['reading_order'][0]['paths'][0]=='study/STUDY_BRIEF.md'
    assert 'references/source_pin.json' in packet['authoring_rules']['reading_order'][-1]['paths']


def test_completed_literature_overrides_historical_display_only(reader,tmp_path):
    from ptm_shared import astra_literature as lit
    from ptm_shared.astra_reader import write_reader
    tables,design,snapshot=reader
    original_cards=tables['reader/cards'].copy(deep=True)
    with patch('ptm_shared.finding_literature.time.sleep'):
        pin=lit.collect(tables,snapshot,selection(),retriever=Retriever(),llm=Model())
    lit.apply(tables,pin,snapshot,selection())
    (tmp_path/'reader').mkdir()
    write_reader(tmp_path,tables)
    text=(tmp_path/'reader/READ_ME.md').read_text()
    assert 'Literature comparison and independent validation were not performed by this reader stage.' not in text
    assert 'Literature search/comparison status:' in text
    assert 'Independent validation not performed.' in text
    assert tables['reader/cards'].equals(original_cards)
    packet=json.loads(tables['reader/packet'].iloc[0].packet_json)
    assert packet['authoring_rules']['literature_execution_authority']['path']=='reader/literature_search.csv'
    assert packet['literature_comparison_status']!='not_performed'
