"""Successful scientific rows may be reused; reader input must stay current."""
import json
from pathlib import Path
import pandas as pd
from ptm_shared.tests.test_astra_science import config


def test_augmentation_reuse_rebuilds_reader_and_invalidates_policy(config,tmp_path,monkeypatch):
    from ptm_shared.astra_evidence_v6 import run
    from ptm_shared import official_method_tracks
    original=official_method_tracks.execute_tracks;calls=[]
    def tracked(*args,**kwargs):
        calls.append(1);return original(*args,**kwargs)
    monkeypatch.setattr(official_method_tracks,'execute_tracks',tracked)
    context=config['experimental_context'];context['quantitation_export_mode']='astra_analysis.v6'
    first=run(1,config,tmp_path/'out');assert len(calls)==1
    config['source_pin_sha256']=first['provenance']['source_pin_sha256']
    context['biological_question']='A changed question must reach the current reader.'
    second=run(1,config,tmp_path/'out');assert len(calls)==1
    root=tmp_path/'out/enrichment_free_runs'/second['run_id']
    prov=json.loads((root/'provenance.json').read_text())
    assert prov['stage_reuse']['augment_evidence']['status']=='reused'
    assert prov['stage_reuse']['quantitative_evidence']['status']=='reused'
    packet=json.loads((root/'reader/authoring_packet.json').read_text())
    assert packet['original_questions']['biological_question']==context['biological_question']
    first_root=tmp_path/'out/enrichment_free_runs'/first['run_id']
    for name in ['kinase/method_scores.csv','science/inference_results.csv','quant/comparisons.csv']:
        assert (root/name).read_bytes()==(first_root/name).read_bytes()
    context['science']['uncertainty']={'enabled':False,'seed':991}
    third=run(1,config,tmp_path/'out');assert len(calls)==2
    assert third['provenance']['stage_reuse']['augment_evidence']['status']=='computed'


def test_incomplete_native_stage_is_retried(config,tmp_path,monkeypatch):
    from ptm_shared.astra_evidence_v6 import run
    from ptm_shared import official_method_tracks
    original=official_method_tracks.execute_tracks;calls=[]
    def failed(scientific,inputs,context,resource):
        native,members,executions=original(scientific,inputs,context,resource);calls.append(1)
        row={k:None for k in official_method_tracks.EXEC_COLUMNS}
        row.update(execution_id='test_failed',method_id='PhosX_native_functions',
                   contrast_id=context['study_design']['contrasts'][0]['contrast_id'],status='failed',reason='synthetic_process_failure')
        return native,members,pd.DataFrame([row])
    monkeypatch.setattr(official_method_tracks,'execute_tracks',failed)
    config['experimental_context']['quantitation_export_mode']='astra_analysis.v6'
    for _ in range(2):
        result=run(1,config,tmp_path/'out')
        assert result['provenance']['stage_reuse']['augment_evidence']['status']=='not_cached'
    assert len(calls)==2
