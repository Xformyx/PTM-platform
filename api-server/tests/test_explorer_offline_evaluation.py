"""Real frozen production fixture -> runner-only scorer. No research claim."""
import asyncio
import json
import pytest
from test_signaling_explorer import setup_explorer
from benchmarking.explorer_evaluation import evaluate
from benchmarking.blind_trial_ledger import append_trial
from benchmarking.tests.test_locked_scorer import _manifest
from ptm_shared.report_revision import file_sha256
from ptm_shared.analysis_universe import signature


def test_locked_runner_requires_frozen_engine_and_preserves_unmeasured_gates(tmp_path,monkeypatch):
    engine,_,root,client,base=setup_explorer(tmp_path,monkeypatch)
    bundle=client.get(base).json()
    directory=next(root.glob('.analysis_results/*/*/manifest.json')).parent
    binding=json.loads((directory/'engine_binding.json').read_text())
    observations=tmp_path/'observations.json'
    observations.write_text(json.dumps({'provenance':{'analysis_revision':bundle['revisions']['analysis']},
        'site_availability':[],'site_observations':[]}))
    benchmark=_manifest(tmp_path)
    ledger=tmp_path/'trials.jsonl'
    frozen=append_trial(ledger,trial_id='synthetic',phase='freeze',code_commit='synthetic',
        input_hashes={'engine':binding['engine_signature'],'effective_config':signature(binding['effective_config'])},
        variable_config={},objective={},fold_metrics=[],decision='freeze',decision_reason='synthetic software test')
    plan=tmp_path/'plan.json';plan.write_text(json.dumps({'schema_version':'explorer_evaluation_plan.v1',
        'observations_sha256':file_sha256(observations),'expected_engine_binding':binding,
        'trial_ledger':'trials.jsonl','frozen_trial_sha256':frozen['record_sha256'],
        'benchmark_manifest':benchmark.path.name,'required_metrics':['detectable_anchor_recall']}))
    before=ledger.read_bytes()
    result=evaluate(directory,observations,plan,tmp_path/'evaluation')
    assert result['gates']['G0']['evaluation_status']=='evaluated'
    assert result['gates']['G1']['evaluation_status']=='not_evaluable'
    assert result['gates']['G2']['evaluation_status']=='not_evaluated'
    assert result['promotion_eligible'] is False and ledger.read_bytes()==before
    with pytest.raises(FileExistsError):evaluate(directory,observations,plan,tmp_path/'evaluation')
    observations.write_text('{}')
    with pytest.raises(ValueError,match='changed_since_freeze'):evaluate(directory,observations,plan,tmp_path/'changed')
    asyncio.run(engine.dispose())
