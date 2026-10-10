"""Round 04: immutable pins, explicit refresh, partial publication protection."""
import copy
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ptm_shared.astra_sources import (SourceClient,resolve_sources,pin_sources,read_source_pin,
    source_execution_record,requested_acquisition_policy,SourceRefreshIncomplete)
from ptm_shared.astra_evidence_v6 import run,resolve_plan
from ptm_shared.astra_package import replay_package, partial_refresh_preserves_existing_package
from ptm_shared.tests.test_astra_science import config


def complete_fixtures():
    return {'OmniPath':{'raw':'enzyme\tsubstrate\tresidue_type\tresidue_offset\tmodification\tsources\treferences\n'},
            'iPTMnet':{'raw':'<html>iPTMnet Report for P0 Not found.</html>'},'STRING':{'payload':[]},
            'Reactome':{'payload':[]},'KEA3':{'payload':{}},'PubMed':{'payload':{'result':{'uids':[]}}}}


def test_bounded_reuse_full_refresh_and_unknown_policy(tmp_path):
    mapping=[{'mapped_accession':f'P{i}','fasta_taxonomy_id':'9606','fasta_gene':f'G{i}'} for i in range(7)]
    fixtures=complete_fixtures()
    old=resolve_sources(tmp_path,mapping,{},'phosphorylation',fixtures=fixtures)
    sha=old['pin_sha256'];original=(tmp_path/'source_pins'/(sha+'.json')).read_bytes()
    context={'quantitation_export_mode':'astra_analysis.v6','refresh_references':False}
    with patch.object(SourceClient,'query',side_effect=AssertionError('Reuse must not query')):
        reused=resolve_sources(tmp_path,mapping,{},'phosphorylation',pin_sha=sha,acquisition_policy={'mode':'research_full'})
    record=source_execution_record(context,sha,reused)
    assert record['pin_reused'] and record['effective_pin_policy']=='legacy_bounded'
    assert record['message']=='기존 제한된 근거 재사용, 이번 전체 수집 미실행'
    fresh=resolve_sources(tmp_path,mapping,{},'phosphorylation',pin_sha=sha,refresh=True,fixtures=fixtures,acquisition_policy={'mode':'research_full'})
    assert fresh['pin_sha256']!=sha and fresh['acquisition_policy']['mode']=='research_full'
    queries=[q for q in fresh['queries'] if q['provider']=='Reactome']
    assert len(queries)==7 and all(q['status']=='no_hit' for q in queries)
    assert sum(q['cache_hit'] for q in queries)==3
    assert (tmp_path/'source_pins'/(sha+'.json')).read_bytes()==original
    context['refresh_references']=True;record=source_execution_record(context,sha,fresh)
    assert not record['pin_reused'] and record['acquisition_executed'] and record['status']=='completed'
    assert record['previous_pin_sha256']==sha and record['used_pin_sha256']==fresh['pin_sha256']
    unknown=pin_sources(tmp_path,{'queries':[]})
    assert source_execution_record({'quantitation_export_mode':'astra_analysis.v6'},unknown['pin_sha256'],unknown)['effective_pin_policy']=='unknown'
    assert 'acquisition_policy' not in read_source_pin(tmp_path,unknown['pin_sha256'])


def test_refresh_intent_cannot_change_quant_fingerprint(config):
    ctx=config['experimental_context'];ctx['quantitation_export_mode']='astra_analysis.v6'
    old=resolve_plan(ctx,{'PR':'same','PG':'same','FASTA':'same'},'old')
    changed={**ctx,'refresh_references':True,'acquisition_policy':{'mode':'research_full'}}
    new=resolve_plan(changed,{'PR':'same','PG':'same','FASTA':'same'},'new')
    assert old['fingerprints']['quant']==new['fingerprints']['quant']
    assert old['fingerprints']['identity_localization']==new['fingerprints']['identity_localization']
    assert old['fingerprints']['discovery']!=new['fingerprints']['discovery']
    assert requested_acquisition_policy({'refresh_references':True})['mode']=='research_full'


def test_package_reuse_refresh_failure_and_archive_replay(config,tmp_path):
    ctx=config['experimental_context'];ctx['quantitation_export_mode']='astra_analysis.v6'
    ctx['acquisition_policy']={'mode':'legacy_bounded'}
    config['source_fixtures']=complete_fixtures()
    # Small real orchestrator runs; successful fixture responses carry no fabricated edges.
    output=tmp_path/'out';first=run(1,config,output)
    old_sha=first['source_pin_sha256'];old_bytes=(Path(config['reference_root'])/'source_pins'/(old_sha+'.json')).read_bytes()
    config['source_pin_sha256']=old_sha;ctx['acquisition_policy']={'mode':'research_full'}
    with (patch.object(SourceClient,'query',side_effect=AssertionError('Pinned rerun must not query')),
          patch('ptm_shared.astra_evidence_v6.calculate',side_effect=AssertionError('Valid quant cache must be reused'))):
        reused=run(1,config,output)
    assert reused['source_execution']['effective_pin_policy']=='legacy_bounded'
    assert reused['provenance']['stage_reuse']['quant']['status']=='reused'
    ctx['refresh_references']=True
    with patch('ptm_shared.astra_evidence_v6.calculate',side_effect=AssertionError('Refresh must not requantify')):
        fresh=run(1,config,output)
    assert fresh['source_pin_sha256']!=old_sha
    assert fresh['source_execution']['status']=='completed'
    assert fresh['provenance']['stage_reuse']['quant']['status']=='reused'
    assert fresh['provenance']['stage_reuse']['discover_regulators']['status']=='computed'
    assert (Path(config['reference_root'])/'source_pins'/(old_sha+'.json')).read_bytes()==old_bytes
    root=output/'enrichment_free_runs'/fresh['run_id']
    for relative in ['study/analysis_plan.json','provenance.json','evidence/readiness.json','platform_run.json']:
        assert json.loads((root/relative).read_text())['source_execution']==fresh['source_execution']
    with (patch('socket.socket',side_effect=AssertionError('Replay network')),
          patch('ptm_shared.astra_package.resolve_sources',side_effect=AssertionError('Replay resolver'))):
        replay_package(root,tmp_path/'replay')
    replay=json.loads((tmp_path/'replay/replay_result.json').read_text())
    assert replay['source_execution']['execution_mode']=='archive_replay'
    assert replay['source_execution']['pin_reused'] and not replay['source_execution']['acquisition_executed']
    assert replay['source_execution']['used_pin_sha256']==fresh['source_pin_sha256']
    pointer=(output/'enrichment_free_current.json').read_bytes()
    partial=copy.deepcopy(read_source_pin(config['reference_root'],old_sha))
    partial.pop('pin_sha256');partial['queries'].append({'query_id':'failed','provider':'Reactome','status':'timeout','reason':'fixture_timeout'})
    partial=pin_sources(config['reference_root'],partial)
    with patch('ptm_shared.astra_package.resolve_sources',return_value=partial):
        with pytest.raises(SourceRefreshIncomplete):run(1,config,output)
    assert (output/'enrichment_free_current.json').read_bytes()==pointer
    failed=[p for p in (output/'enrichment_free_runs').iterdir() if not (p/'manifest.json').exists()]
    assert len(failed)==1
    record=json.loads((failed[0]/'references/source_execution.json').read_text())
    assert record['status']=='partial' and any(q['status']=='timeout' for q in record['incomplete_queries'])
    stages=json.loads((failed[0]/'stage_checkpoint.json').read_text())['stages']
    assert next(r for r in stages if r['stage']=='resolve_annotation')['status']=='failed'


def test_partial_refresh_without_a_completed_package_does_not_block():
    assert partial_refresh_preserves_existing_package(True, 'partial', True)
    assert not partial_refresh_preserves_existing_package(True, 'partial', False)
    assert not partial_refresh_preserves_existing_package(False, 'partial', True)
    assert not partial_refresh_preserves_existing_package(True, 'completed', False)
