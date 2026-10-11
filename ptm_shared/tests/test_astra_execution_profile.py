"""Request intent is independent of the engine/result; archives stay pinned."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from ptm_shared.analysis_context import current_astra_context, verify_execution_profile


@pytest.mark.parametrize('flag', [None, '0', '1'])
@pytest.mark.parametrize('mode', ['astra_analysis.v4', 'astra_analysis.v5', 'astra_analysis.v6', 'legacy_only.v1'])
def test_selection_and_idempotent_request_audit(monkeypatch, flag, mode):
    if flag is None: monkeypatch.delenv('PTM_ASTRA_EVIDENCE_V6', raising=False)
    else: monkeypatch.setenv('PTM_ASTRA_EVIDENCE_V6', flag)
    original = {'quantitation_export_mode': mode, 'study_design': {'keep': True}}
    saved = deepcopy(original)
    actual = current_astra_context(original)
    expected = ('astra_analysis.v6' if flag == '1' else 'astra_analysis.v5') if mode in {'astra_analysis.v4', 'astra_analysis.v5'} else mode
    assert actual['quantitation_export_mode'] == expected
    assert current_astra_context(actual) == actual
    assert original == saved
    if mode.startswith('astra_'):
        assert actual['astra_execution']['requested_profile'] == mode
        assert verify_execution_profile(actual, expected)['status'] == 'matched'


def test_wrong_engine_fails_before_input_or_pointer_access(tmp_path, monkeypatch):
    from ptm_shared.astra_package import run_astra_analysis
    monkeypatch.setenv('PTM_ASTRA_EVIDENCE_V6', '1')
    context = current_astra_context({'quantitation_export_mode': 'astra_analysis.v5'})
    pointer = tmp_path / 'enrichment_free_current.json'
    pointer.write_text('previous-success')
    wrong = SimpleNamespace(PROFILE='astra_analysis.v5', VERSION='injected-wrong-engine')
    with pytest.raises(ValueError, match='astra_profile_mismatch'):
        run_astra_analysis(1, {'experimental_context': context}, tmp_path, engine=wrong)
    assert pointer.read_text() == 'previous-success'
    assert list(tmp_path.iterdir()) == [pointer]
    context['quantitation_export_mode'] = 'astra_analysis.v5'
    with pytest.raises(ValueError, match='astra_profile_mismatch'):
        verify_execution_profile(context, 'astra_analysis.v5')


def test_archive_legacy_profile_is_not_upgraded_by_replay_flag(monkeypatch):
    monkeypatch.setenv('PTM_ASTRA_EVIDENCE_V6', '1')
    for mode in ('astra_analysis.v4', 'astra_analysis.v5'):
        context = {'quantitation_export_mode': mode}
        assert verify_execution_profile(context, mode)['executed_profile'] == mode
