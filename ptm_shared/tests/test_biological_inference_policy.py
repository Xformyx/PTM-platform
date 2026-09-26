import pytest
from ptm_shared.sample_manifest import compare_sample_units, unit_test_inputs, validate_sample_manifest
from ptm_shared.analysis_context import merge_analysis_context
from ptm_shared.preprocessing_dependencies import quantification_dependency_digest


def test_missing_design_preserves_repeatability_without_biological_p():
    result = compare_sample_units({'c1': 100, 'c2': 101, 'c3': 99}, {'t1': 1000, 't2': 1001, 't3': 999})
    assert result['p_value'] is None
    assert result['status'].startswith('biological_design_unavailable')
    assert result['observation_repeatability']['control']['cv'] == .01


def test_explicit_biological_replication_can_support_inference():
    manifest = {'samples': [{'sample_id': s, 'biological_unit': s} for s in ['c1','c2','t1','t2']]}
    result = compare_sample_units({'c1': 100, 'c2': 101}, {'t1': 1000, 't2': 1002}, manifest)
    assert result['p_value'] is not None


@pytest.mark.parametrize('bad', [None, '', ' ', [], {}])
def test_malformed_unit_fails_closed(bad):
    manifest = {'samples': [{'sample_id': 'c', 'condition': 'Control', 'biological_unit': bad}]}
    with pytest.raises(ValueError):
        validate_sample_manifest(manifest)
    assert unit_test_inputs({'c': 1}, {'c': 2}, manifest)['status'] == 'invalid_biological_design'


def test_context_patch_preserves_structured_design_and_explicit_clear():
    original = {'sample_manifest': {'samples': [{'sample_id':'c', 'biological_unit':'b'}]},
                'normalization_policy': 'already_normalized.v1', 'future_extension': {'keep': True}}
    patch = merge_analysis_context(original, {'treatment': 'insulin'})
    assert patch['sample_manifest'] == original['sample_manifest']
    assert patch['normalization_policy'] == 'already_normalized.v1'
    patch['future_extension']['keep'] = False
    assert original['future_extension']['keep'] is True
    assert 'sample_manifest' not in merge_analysis_context(original, {'sample_manifest': None})


def test_shared_engine_change_invalidates_cache(tmp_path):
    core, shared = tmp_path / 'core', tmp_path / 'shared'
    core.mkdir(); shared.mkdir()
    (core / 'engine.py').write_text('a = 1')
    helper = shared / 'inference.py'
    helper.write_text('policy = 1')
    before = quantification_dependency_digest(core, shared)
    helper.write_text('policy = 2')
    assert quantification_dependency_digest(core, shared) != before
