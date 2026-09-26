from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from app.api.orders import _updated_analysis_context


def order(tmp_path):
    pr, pg = tmp_path / 'pr.tsv', tmp_path / 'pg.tsv'
    for path in [pr,pg]:
        path.write_text('Protein.Group\tc\tt\nP1\t1\t2\n')
    manifest = {'pairing':'unpaired','samples':[
        {'sample_id':'c','condition':'Control','biological_unit':'control_material'},
        {'sample_id':'t','condition':'5min','biological_unit':'treated_material'}]}
    return SimpleNamespace(sample_config={'samples':[{'file_name':'c','group':'Control'},
        {'file_name':'t','condition':'5min','group':'Treatment'}]}, pr_matrix_path=str(pr), pg_matrix_path=str(pg),
        analysis_context={'sample_manifest':manifest, 'normalization_policy':'already_normalized.v1',
                          'custom_future':{'keep':True}}, ptm_type='phosphorylation')


def test_create_copy_and_rerun_keep_manifest_and_policy(tmp_path):
    source = order(tmp_path)
    assert _updated_analysis_context(source, {}) == source.analysis_context
    copy = _updated_analysis_context(source, {'treatment':'Insulin'})
    assert copy['sample_manifest'] == source.analysis_context['sample_manifest']
    assert copy['normalization_policy'] == 'already_normalized.v1'
    source.analysis_context = copy
    rerun = _updated_analysis_context(source, {'biological_question':'Late response'})
    assert rerun['sample_manifest'] == copy['sample_manifest']
    assert rerun['custom_future'] == {'keep':True}


def test_explicit_clear_and_incomplete_design(tmp_path):
    source = order(tmp_path)
    assert 'sample_manifest' not in _updated_analysis_context(source, {'sample_manifest':None})
    bad = {'samples':[{'sample_id':'c','condition':'Control','biological_unit':'x'}]}
    with pytest.raises(HTTPException) as exc:
        _updated_analysis_context(source, {'sample_manifest':bad})
    assert exc.value.status_code == 422
