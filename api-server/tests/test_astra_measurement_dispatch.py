"""Round 05: synthetic upload/ORM/dispatch/worker evidence, never real-report parity."""
import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
import pandas as pd
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.api import orders
from app.core.database import Base
from app.models.order import Order
from app.models.rag_collection import RagCollection
from app.services.astra_input_capture import prepare_astra_inputs
from ptm_shared import astra_evidence_v6 as evidence
from ptm_shared.annotation_registry import digest
from ptm_shared.astra_package import replay_package
from ptm_shared.astra_sources import SourceClient
from ptm_shared.tests.test_astra_science import config
from ptm_shared.tests.test_astra_evidence_integration import add_report
from scripts.validate_astra_activation import compare_quant


def test_uploaded_measurements_reach_worker_contributions_and_replay(config, tmp_path, monkeypatch):
    ctx=config['experimental_context'];ctx['quantitation_export_mode']='astra_analysis.v6'
    rows=add_report(config,tmp_path);design=ctx['study_design']
    cross=[]
    for j,inj in enumerate(design['injections']):
        cross.append({'Run':f'raw_{j}.raw','Channel':'light',**{k:inj[k] for k in ['input_column','injection_id']}})
    chosen=rows[0]['Precursor.Id'];reference=design['conditions'][0]['condition_id']
    target_columns={i['input_column'] for i in design['injections'] if i['condition_id']!=reference}
    for row in rows:
        if row['Precursor.Id']==chosen and row['Run'] in target_columns:
            row['Site.Occupancy.Probabilities']=row['Site.Occupancy.Probabilities'].replace('0.990000','0.100000')
        row['Run']=f"raw_{row['Run.Index']}.raw"
    rows.extend([{**rows[0],'Run':'unknown.raw'}, {**rows[0],'Precursor.Charge':9},
                 {**rows[0],'Channel':'heavy'},dict(rows[1])])
    main=Path(config['diann_report_path']);pd.DataFrame(rows).to_csv(main,sep='\t',index=False)
    cross_path=tmp_path/'cross.csv';pd.DataFrame(cross).to_csv(cross_path,index=False)
    site={'Run.Index':0,'Channel':'light','Precursor.Lib.Index':rows[2]['Precursor.Lib.Index'],
          'Protein':rows[2]['Protein.Ids'],'Site':3,'Residue':'S','Modification':'UniMod:21','Occupied':True,'Probability':.99}
    site_path=tmp_path/'sites.parquet';pd.DataFrame([site,{**site,'Precursor.Lib.Index':999999},
        {**site,'Protein':rows[0]['Protein.Ids'],'Precursor.Lib.Index':rows[0]['Precursor.Lib.Index']}]).to_parquet(site_path)
    settings=SimpleNamespace(INPUT_DIR=str(tmp_path/'uploads'),OUTPUT_DIR=str(tmp_path/'outputs'),REFERENCE_DIR=config['reference_root'])
    monkeypatch.setattr(orders,'get_settings',lambda:settings)
    monkeypatch.setattr('app.config.get_settings',lambda:settings)
    app=FastAPI();app.include_router(orders.router)
    app.dependency_overrides[orders.get_current_user]=lambda:SimpleNamespace(id=0,role='admin')
    paths={'pr_matrix':config['pr_matrix_path'],'pg_matrix':config['pg_matrix_path'],'fasta_file':config['fasta_path'],
           'diann_report':main,'diann_site_report':site_path,'run_crosswalk':cross_path}
    samples=json.loads(Path(config['pr_matrix_path']).with_name('fixture.json').read_text())['sample_config']

    async def upload_and_read():
        db_engine=create_async_engine(f'sqlite+aiosqlite:///{tmp_path}/orders.sqlite')
        async with db_engine.begin() as conn:
            await conn.run_sync(lambda c:Base.metadata.create_all(c,tables=[Order.__table__,RagCollection.__table__]))
        session=async_sessionmaker(db_engine,expire_on_commit=False)
        async def database():
            async with session() as db:yield db
        app.dependency_overrides[orders.get_db]=database
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://test') as client:
            response=await client.post('/orders',data={'project_name':'Round05_synthetic','species':'human','ptm_type':'phosphorylation',
                'sample_config':json.dumps(samples),'analysis_context':json.dumps(ctx),'rag_collections':'[]','report_options':'{}'},
                files={key:(Path(path).name,Path(path).read_bytes()) for key,path in paths.items()})
            assert response.status_code==201,response.text
        async with session() as db:
            order=(await db.execute(select(Order).where(Order.id==response.json()['id']))).scalar_one()
            snapshot,pin=await prepare_astra_inputs(order,db,settings.REFERENCE_DIR)
        await db_engine.dispose()
        return order,snapshot,pin
    order,snapshot,literature=asyncio.run(upload_and_read())
    dispatch={key:getattr(order,key) for key in ['pr_matrix_path','pg_matrix_path','fasta_path','order_code']}
    dispatch.update(species_tax_id='9606',user_input_snapshot=snapshot,literature_pin=literature,source_fixtures=config['source_fixtures'])
    orders._attach_enrichment_free_profile(order,dispatch)
    for key,path in [('diann_report_path',main),('diann_site_report_path',site_path),('run_crosswalk_path',cross_path)]:
        assert digest(dispatch[key])==digest(path)
        assert snapshot['original']['input_files'][key]['status']=='provided'
    assert dispatch['experimental_context']['science']['diann_version']=='2.7.0'

    baseline=copy.deepcopy(dispatch)
    for key in ['diann_report_path','diann_site_report_path']:
        baseline.pop(key,None)
        baseline['user_input_snapshot']['original']['input_files'][key]={'filename':None,'status':'not_provided'}
    output=Path(settings.OUTPUT_DIR)/order.order_code
    before=evidence.run(order.id,baseline,output)
    before_root=output/'enrichment_free_runs'/before['run_id']
    orphan=pd.read_csv(before_root/'study/input_lineage.csv').set_index('input_id').loc['CROSSWALK']
    assert orphan.disposition=='accepted_but_unused' and 'main_report_not_provided' in orphan.reason
    assert (before_root/'inputs/CROSSWALK.csv').is_file()  # copied does not imply consumed
    dispatch['source_pin_sha256']=before['source_pin_sha256']

    # Execute the real primary worker branch; only infrastructure side effects
    # (DB progress, broker, webhook) are replaced, not scientific consumers.
    import preprocessing.tasks as worker
    import common.run_control as control
    monkeypatch.setattr(worker,'OUTPUT_DIR',settings.OUTPUT_DIR)
    for name in ['update_order_status','publish_progress','send_step_webhook']:
        monkeypatch.setattr(worker,name,lambda *a,**k:None)
    monkeypatch.setattr(control,'bind_run_generation',lambda *a:None)
    monkeypatch.setattr(control,'is_stale_generation',lambda *a:False)
    monkeypatch.setattr(control,'abort_if_superseded',lambda *a:None)
    monkeypatch.setattr('common.db_engine.get_engine',Mock(side_effect=RuntimeError('no infrastructure writes in fixture')))
    consumers={name:Mock(wraps=getattr(evidence,name)) for name in ['prepare_evidence','observations','read_site_report','observation_sites','by_contrast','score_candidates']}
    for name,spy in consumers.items():monkeypatch.setattr(evidence,name,spy)
    with (patch.object(SourceClient,'query',side_effect=AssertionError('Pinned source only')),
          patch.object(evidence,'calculate',side_effect=AssertionError('audit_only must reuse quant cache'))):
        result=worker.run_preprocessing.run(order.id,dispatch)
    assert result['status']=='completed'
    assert all(spy.call_count==1 for spy in consumers.values())
    root=output/'enrichment_free_runs'/result['run_id']
    saved=json.loads((root/'platform_run.json').read_text())
    comparisons=compare_quant(output/before['artifacts']['astra']['path'],output/saved['artifacts']['astra']['path'])
    assert len(comparisons)==22 and all(r['byte_equal'] for r in comparisons)
    obs=pd.read_csv(root/'science/measurement_observations.csv');children=pd.read_csv(root/'science/observation_sites.csv')
    loc=pd.read_csv(root/'science/localization_by_contrast.csv');contributions=pd.read_csv(root/'kinase/substrate_contributions.csv')
    assert len(obs)==len(rows) and obs.source_row_id.tolist()==list(range(1,len(rows)+1))
    assert obs.match_status.eq('conflict').sum()==2
    for reason in ['run_crosswalk_required','matrix_precursor_unmatched']:
        assert obs.restriction_reasons.fillna('').str.contains(reason).any()
    assert obs.localization_metric_value.eq(.98).all() and obs.library_localization_confidence.eq(.999).all()
    assert obs.identification_q_values.map(json.loads).map(lambda q:q['Q.Value']).eq(.001).all()
    form=obs.loc[obs.raw_precursor_id.eq(chosen),'form_id'].dropna().iloc[0]
    assert not loc.loc[loc.form_id.eq(form),'localized_eligible'].any()
    assert children.site_probability.dropna().isin([.99,.1]).all()
    assert set(children.observation_id)<=set(obs.observation_id)
    comp=pd.read_csv(root/'quant/comparisons.csv').set_index(['form_id','contrast_id'])
    indexed_obs=obs.set_index('observation_id')
    for row in loc.itertuples():
        for side in ['reference','target']:
            raw=getattr(row,side+'_observation_ids');ids=[] if pd.isna(raw) else raw.split(';')
            raw_runs=comp.loc[(row.form_id,row.contrast_id),side+'_joint_run_ids']
            runs=set() if pd.isna(raw_runs) else set(raw_runs.split(';'))
            assert set(indexed_obs.loc[ids].injection_id)<=runs
    supported=contributions.loc[contributions.track.eq('localized_A')]
    assert len(supported) and supported.localization_ids.notna().all()
    passed=set(loc.loc[loc.localized_eligible,'localization_id'])
    assert all(set(ids.split(';'))<=passed for ids in supported.localization_ids)
    sites=pd.read_csv(root/'science/site_report_observations.csv')
    assert sites.status.tolist()==['matched','restricted','restricted']
    assert sites.restriction_reasons.fillna('').str.contains('main_report_unmatched').sum()==1
    assert sites.restriction_reasons.fillna('').str.contains('main_report_ambiguous').sum()==1
    calls_before_replay={k:v.call_count for k,v in consumers.items()}
    with patch('socket.socket',side_effect=AssertionError('Offline fixture replay')):
        replay_package(root,tmp_path/'replay')
    audit={'scope':'synthetic_SQLite_API_real_worker_branch_infrastructure_mocked','run_id':result['run_id'],
           'source_pin_sha256':saved['source_pin_sha256'],'consumer_calls':calls_before_replay,
           'observations':len(obs),'match_status':obs.match_status.value_counts().to_dict(),'quant_tables':comparisons,
           'real_user_report_parity':'not_run_missing_input'}
    (tmp_path/'lineage_validation.json').write_text(json.dumps(audit,indent=2))


@pytest.mark.parametrize('version,invalid_header,reason',[(None,False,'unsupported_diann_version'),('2.7.0',True,'unsupported_diann_schema')])
def test_unverified_report_semantics_preserve_quant_and_do_not_match(config,tmp_path,version,invalid_header,reason):
    from ptm_shared.science_reference import preflight
    add_report(config,tmp_path)
    config['experimental_context']['science']['diann_version']=version
    if invalid_header:Path(config['diann_report_path']).write_text('unrelated\tvalue\nrow\t1\n')
    context=config['experimental_context'];design=context['study_design']
    inputs={key:Path(config[field]) for key,field in [('PR','pr_matrix_path'),('PG','pg_matrix_path'),('FASTA','fasta_path'),('DIANN','diann_report_path')]}
    tables,_,_=evidence.calculate(inputs,design,context)
    original=tables['comparisons'].copy(deep=True)
    parsed=evidence.prepare_evidence(tables,inputs,design,{**context,'_runtime_reference':preflight(config,context)})['_canonical_evidence']
    assert parsed['measurement_status']['status']=='unsupported_schema'
    assert reason in parsed['measurement_status']['reason'] and parsed['measurement_status']['raw_input_preserved']
    assert parsed['measurement_observations'].empty and parsed['observation_sites'].empty
    assert not parsed['localization_by_contrast'].localized_eligible.any()
    pd.testing.assert_frame_equal(tables['comparisons'],original,check_exact=True)
