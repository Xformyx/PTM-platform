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


def test_generic_draft_save_and_execution_validation_share_resolver(tmp_path):
    source=order(tmp_path);source.species='human';source.analysis_options={'mode':'full'};source.rag_collections=None
    context={'quantitation_export_mode':'enrichment_free_timecourse.v3','sample_manifest':None,
        'annotation_mode':'quantification_only','normalization_policy':'already_normalized.v1','enrichment_status':'enrichment_free',
        'cell_type':'세포 α','treatment':'EGF','biological_question':'response?','special_conditions':'unknown',
        'replication_declaration':'technical_per_condition'}
    draft=_updated_analysis_context(source,context)
    assert draft['study_design']['status']=='draft'
    source.analysis_context=draft
    with pytest.raises(HTTPException) as exc:_updated_analysis_context(source,{},for_execution=True)
    assert exc.value.status_code==422 and exc.value.detail['issues']
    source.analysis_context=_updated_analysis_context(source,{'time_points':'0,5min'})
    resolved=_updated_analysis_context(source,{},for_execution=True)
    assert resolved['study_design']['status']=='resolved'
    assert resolved['study_design']['study']['original_context']['cell_type']=='세포 α'
    assert len(resolved['study_design']['injections'])==2
    rerun=_updated_analysis_context(source,{'biological_question':'different expected pathway'})
    for key in ['injections','materials','conditions','contrasts','arms']:
        assert rerun['study_design'][key]==resolved['study_design'][key]


def test_standard_other_ptm_not_subject_to_generic_constraints(tmp_path):
    source=order(tmp_path);source.ptm_type='acetylation'
    assert _updated_analysis_context(source,{'treatment':'hypoxia'})['treatment']=='hypoxia'
