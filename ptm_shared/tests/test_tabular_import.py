import json
import pytest
from ptm_shared.tabular_import import read_quantitative_tsv
from ptm_shared.de_novo_representation import heatmap_denovo_value


def test_malformed_records_remain_accounted_without_moving_source_locators(tmp_path):
    source=tmp_path/'raw.tsv';source.write_text('id\tx\nA\t0\nmalformed\t2\textra\nB\t\n')
    frame=read_quantitative_tsv(source,tmp_path/'out')
    assert frame['id'].tolist()==['A','B']
    assert frame.iloc[0]['x']==0
    assert frame.attrs['source_row_locators']==[{'start_line':2,'end_line':2},{'start_line':4,'end_line':4}]
    audit=frame.attrs['import_accounting']
    assert audit['source_rows']==3 and audit['parsed_rows']==2 and audit['quarantined_rows']==1
    ledger=json.loads((tmp_path/'out'/audit['quarantine_artifact']).read_text())
    assert ledger['raw_fields']==['malformed','2','extra']
    assert source.read_text().count('extra')==1


def test_unrecoverable_parse_is_not_success_and_missing_lod_is_not_zero(tmp_path):
    source=tmp_path/'raw.tsv';source.write_text('id\tx\nA\t0\n"unclosed\t2')
    with pytest.raises(ValueError,match='parse_failure'):read_quantitative_tsv(source,tmp_path/'out')
    audit=json.loads(next((tmp_path/'out').glob('import_*.json')).read_text())
    assert audit['execution_status']=='failed' and audit['source_rows'] is None
    for value in (None,'NA',float('nan'),float('inf')):assert heatmap_denovo_value(value) is None
    assert heatmap_denovo_value(0)==0


def test_duplicate_header_is_quarantined_without_overwriting_measurement_columns(tmp_path):
    source=tmp_path/'raw.tsv';original='id\tx\tx\nA\t1\t2\n';source.write_text(original)
    with pytest.raises(ValueError,match='ambiguous_source_header'):
        read_quantitative_tsv(source,tmp_path/'out')
    audit=json.loads(next((tmp_path/'out').glob('import_*.json')).read_text())
    assert audit['execution_status']=='failed'
    assert source.read_text()==original
