import copy
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from ptm_shared.astra_inputs import capture_order, transfer_contract, leaves
from ptm_shared.astra_plan import resolve_plan
from ptm_shared.astra_sources import SourceClient, resolve_sources
from ptm_shared.astra_temporal import measured_features, order_intervals, integrate_temporal
from ptm_shared.astra_package import run_astra_analysis, replay_package, validate_package, validate_science
from ptm_shared.kea3_evidence import parse_kea3, mapped_human_genes
from ptm_shared.motif_candidate_calibration import anchored_match, anchored_background, load_motif_library
from ptm_shared.study_design import resolve_study_design
from scripts.validate_generic_platform import make_fixture


@pytest.fixture
def configuration(tmp_path):
    fixture=tmp_path/'fixture';make_fixture(fixture)
    definition=json.loads((fixture/'fixture.json').read_text())
    context={**definition['analysis_context'],'quantitation_export_mode':'astra_analysis.v4'}
    context['study_design']=resolve_study_design(context,definition['sample_config'],taxonomy_id='9606',species='human')
    context['custom_extension']={'zero':0,'false':False,'empty':[],'null':None,'unicode':'한글 α\n'+('long question ' * 500)}
    fixtures={'OmniPath':{'raw':(fixture/'snapshot.tsv').read_text()},'iPTMnet':{'status':'timeout'},
        'KEA3':{'payload':{'Integrated--meanRank':[{'TF':'EGFR','Score':'2','FDR':'0.03','Overlapping_Genes':'GENA,GENB'}]}},'STRING':{'payload':[]}}
    snapshot=capture_order({'id':42,'project_name':'원문 연구','order_code':'synthetic','species':'human',
        'analysis_context':context,'sample_config':definition['sample_config'],'report_options':{'research_questions':['질문\n'+('αβ ' * 700)],'report_type':'co_scientist'},
        'analysis_options':{'filter':False},'rag_collections':[]})
    return {'experimental_context':context,'species_tax_id':'9606','order_code':'synthetic','run_generation':1,
        'reference_root':str(tmp_path/'reference'),'source_fixtures':fixtures,'user_input_snapshot':snapshot,
        **{field:str(fixture/name) for field,name in [('pr_matrix_path','PR.tsv'),('pg_matrix_path','PG.tsv'),('fasta_path','reference.fasta')]}}


def test_lossless_input_inventory_and_secret_exclusion(configuration):
    snapshot=configuration['user_input_snapshot'];context=configuration['experimental_context'];design=context['study_design']
    snapshot['original']['analysis_context']['private_token']='MUST_NOT_APPEAR'
    clean=capture_order({**snapshot['original'],'id':42})
    assert 'MUST_NOT_APPEAR' not in json.dumps(clean)
    fields,check,brief=transfer_contract(clean,design,context,{'collections':[]})
    assert check['unexpected_missing']==0
    assert check['raw_transferred']==len(list(leaves(clean['original'])))
    assert check['justified_exclusions']==1
    assert len({r['source_field_path'] for r in fields})==len(fields)
    extension=clean['original']['analysis_context']['custom_extension']
    assert extension['zero']==0 and extension['false'] is False and extension['empty']==[] and extension['null'] is None
    assert clean['original']['report_options']['research_questions'][0] in json.loads(json.dumps(brief)).replace('\\n','\n')


def test_plan_question_independence_and_policy_dependencies(configuration):
    ctx=configuration['experimental_context'];a=resolve_plan(ctx,{'PR':'one'},'pin-a')
    changed=copy.deepcopy(ctx);changed['biological_question']='Different EGF expectation';changed['study_design']['study']['biological_question']='EGF'
    b=resolve_plan(changed,{'PR':'one'},'pin-a')
    assert a['fingerprints']==b['fingerprints']
    c=resolve_plan(ctx,{'PR':'one'},'pin-b')
    assert c['fingerprints']['quant']==a['fingerprints']['quant'] and c['fingerprints']['discovery']!=a['fingerprints']['discovery']
    changed['normalization_policy']='legacy_median.v1'
    assert resolve_plan(changed,{'PR':'one'},'pin-a')['fingerprints']['quant']!=a['fingerprints']['quant']


@pytest.mark.parametrize('entry,expected',[
    ({'TF':'K','FDR':'.03'},(None,.03)),({'TF':'K','P-value':'.02'},(.02,None)),({'TF':'K'},(None,None)),
    ({'TF':'K','P-value':'.02','FDR':'.04'},(.02,.04))])
def test_kea_nullable_separate_statistics(entry,expected):
    row=parse_kea3({'library':[entry]})[0]
    assert (row['p_value'],row['q_value'])==expected and row['score'] is None
    assert not row['direct_site_evidence'] and row['direction'] is None


def test_kea_requires_actual_nonhuman_mapping():
    with pytest.raises(ValueError):mapped_human_genes(['Mapk1'],'10116')
    assert mapped_human_genes(['Mapk1'],'10116',{'Mapk1':{'verified':True,'human_genes':['MAPK1']}})==['MAPK1']


def test_anchored_motif_and_duplicate_balanced_background():
    pattern=r'R.R..(?P<ptm>[ST])'
    assert anchored_match(pattern,'__RARAASAAAAAAA',7)
    assert not anchored_match(pattern,'RARAASASAAAAAAA',7)  # only a neighboring S fits
    library={'patterns':{'AKT':{'pattern':pattern,'ptm_type':'Phosphorylation','evidence_role':'site_motif'}}}
    site={'gene':'G1','sequence_window':'__RARAASAAAAAAA','modified_center':7}
    first=anchored_background([site],library)
    assert anchored_background([site]*5,library)==first


def test_gap_aware_auc_event_brackets_and_no_causal_order():
    f=measured_features([1,5,15,60,180],[0,None,1,2,0])
    assert f['onset_lower_min']==1 and f['onset_upper_min']==15
    assert f['observed_peak_time_min']==60 and f['observed_points']==4
    assert f['gap_intervals']==2 and f['auc_supported_duration_min']==165
    assert f['adjacent_trapezoid_auc']==187.5  # 15–60 and 60–180 only
    assert f['recovery_lower_min']==60 and f['recovery_upper_min']==180
    assert order_intervals(f,measured_features([1,5,15,60,180],[None,None,1,1,1]))[0]=='order_unresolved'
    assert f['causality_status']=='not_tested' and not f['baseline_anchor_is_independent_observation']


@pytest.mark.parametrize('status',['timeout','rate_limited','access_unavailable','parse_failure'])
def test_provider_failure_never_negative_cache(tmp_path,status):
    c=SourceClient(tmp_path,{'P':{'status':status}})
    row=c.query('P',{'taxon':'9606'},'https://fixture.invalid')
    assert row['status']==status and not list(tmp_path.rglob('*.json'))


def test_valid_empty_provider_cache(tmp_path):
    client=SourceClient(tmp_path,{'P':{'payload':[]}})
    record=client.query('P',{'taxon':'9606'},'https://fixture.invalid');client.accept(record,[])
    again=SourceClient(tmp_path,{}).query('P',{'taxon':'9606'},'https://fixture.invalid')
    assert again['status']=='no_hit' and again['cache_hit']


def test_real_orchestrator_offline_replay_and_interruption(configuration,tmp_path):
    out=tmp_path/'output'
    result=run_astra_analysis(42,configuration,out)
    directory=out/'enrichment_free_runs'/result['run_id']
    assert result['counts']['primary_comparisons']==24
    assert result['counts']['candidate_entities']>=2
    assert result['analysis_readiness']['completion_status']=='completed_with_limitations'
    snapshot=json.loads((directory/'study/user_input_snapshot.json').read_text())
    assert snapshot==configuration['user_input_snapshot']
    assert json.loads((directory/'study/input_transfer_validation.json').read_text())['unexpected_missing']==0
    edges=pd.read_csv(directory/'kinase/kinase_candidate_edges.csv')
    assert 'sequence_motif_candidate' in set(edges.edge_type)
    assert edges.loc[edges.edge_type.str.startswith('curated'),'localization_probability'].isna().all()
    profiles=pd.read_csv(directory/'kinase/kinase_temporal_profiles.csv')
    assert profiles.loc[profiles.track.eq('localized_A'),'activity_magnitude'].isna().all()
    assert profiles.loc[profiles.track.eq('curated_A'),'activity_magnitude'].notna().any()
    contrasts=pd.read_csv(directory/'quant/comparisons.csv');assert contrasts.biological_p_value.isna().all()
    assert np.allclose(contrasts.loc[contrasts.included,'A'],contrasts.loc[contrasts.included,'U_joint']-contrasts.loc[contrasts.included,'P_joint'])
    with patch('urllib.request.urlopen',side_effect=AssertionError('offline replay attempted a network call')):
        replay_package(directory,tmp_path/'replayed')
    assert json.loads((tmp_path/'replayed/replay_result.json').read_text())['passed']
    original=(out/'enrichment_free_current.json').read_bytes()
    changed=copy.deepcopy(configuration);changed['experimental_context']['biological_question']='EGF question only'
    changed['source_pin_sha256']=result['source_pin_sha256']
    rerun=run_astra_analysis(42,changed,out)
    assert rerun['provenance']['stage_reuse']['quant']['status']=='reused'
    assert rerun['source_pin_sha256']==result['source_pin_sha256']
    after=out/'enrichment_free_runs'/rerun['run_id']
    for name in ['quant/comparisons.csv','kinase/substrate_contributions.csv','kinase/kinase_temporal_profiles.csv']:
        pd.testing.assert_frame_equal(pd.read_csv(directory/name),pd.read_csv(after/name),check_dtype=False,atol=1e-10,rtol=1e-10)
    original=(out/'enrichment_free_current.json').read_bytes()
    with pytest.raises(RuntimeError):run_astra_analysis(42,configuration,out,checkpoint=lambda:(_ for _ in ()).throw(RuntimeError('superseded')))
    assert (out/'enrichment_free_current.json').read_bytes()==original
    with patch('ptm_shared.astra_package.figure_packet',side_effect=OSError('injected write interruption')):
        with pytest.raises(OSError):run_astra_analysis(42,configuration,out)
    assert (out/'enrichment_free_current.json').read_bytes()==original
    table=directory/'quant/comparisons.csv';table.write_text(table.read_text()+'CORRUPTION')
    with pytest.raises(ValueError,match='hash'):validate_package(directory)


def test_lod_requires_documented_external_model_and_never_imputes_point_fc(configuration):
    from ptm_shared.astra_evidence import censoring_bounds
    from ptm_shared.generic_workflow import calculate
    cfg=configuration;ctx=cfg['experimental_context'];design=ctx['study_design']
    tables,*_=calculate({k:Path(cfg[f]) for k,f in [('PR','pr_matrix_path'),('PG','pg_matrix_path'),('FASTA','fasta_path')]},design,{**ctx,'annotation_mode':'quantification_only'},None)
    before=tables['comparisons'].copy(deep=True)
    missing=censoring_bounds(tables,design)
    assert len(missing) and missing.conditional_A_lower_bound.isna().all()
    records=[]
    for r in tables['runlevel'].itertuples():
        if not r.U_observed:records.append({'form_id':r.form_id,'injection_id':r.injection_id,'upper_detection_limit':1})
    with pytest.raises(ValueError,match='require'):censoring_bounds(tables,design,{'limits':records})
    bounds=censoring_bounds(tables,design,{'model_version':'fixture.v1','source':'synthetic known upper limit',
        'validation_evidence':'fixture assumption only','assumption':'undetected intensity <=1','limits':records})
    assert bounds.conditional_A_lower_bound.notna().any() and not bounds.baseline_FC_created.any()
    pd.testing.assert_frame_equal(before,tables['comparisons'])


def test_refresh_reuses_a_valid_success(tmp_path):
    client=SourceClient(tmp_path,{'P':{'payload':[]}})
    client.accept(client.query('P',{},'https://fixture.invalid'),[])
    refresh=SourceClient(tmp_path,{'P':{'payload':[{'new':True}]}},refresh=True)
    reused=refresh.query('P',{},'https://fixture.invalid')
    assert reused['cache_hit'] is True and reused['payload']==[]


def test_missing_table_and_foreign_keys_fail_even_with_rebuilt_hash(configuration,tmp_path):
    from ptm_shared.astra_package import compute_science
    from ptm_shared.astra_sources import resolve_sources
    from ptm_shared.astra_discovery import mapped_sites
    from ptm_shared.generic_workflow import calculate
    ctx=configuration['experimental_context'];design=ctx['study_design']
    inputs={k:Path(configuration[f]) for k,f in [('PR','pr_matrix_path'),('PG','pg_matrix_path'),('FASTA','fasta_path')]}
    quant=calculate(inputs,design,{**ctx,'annotation_mode':'quantification_only'},None)
    mapped,_,fasta=mapped_sites(quant[0],design,inputs['FASTA'],ctx,[])
    sources=resolve_sources(configuration['reference_root'],mapped.to_dict('records'),fasta,'phosphorylation',fixtures=configuration['source_fixtures'])
    tables,*_=compute_science(inputs,design,ctx,sources,quant=quant)
    validate_science(tables,design)
    tables['temporal/cross_layer_links'].loc[0,'target_evidence_id']='missing_feature'
    with pytest.raises(ValueError,match='Foreign key'):validate_science(tables,design)


def test_empty_nonphosphorylation_retains_protein_layer(configuration,tmp_path):
    cfg=copy.deepcopy(configuration);ctx=cfg['experimental_context'];ctx['study_design']['study']['ptm_type']='ubiquitylation'
    result=run_astra_analysis(42,cfg,tmp_path/'nonphospho')
    assert result['analysis_readiness']['kinase']['status']=='not_applicable'
    assert result['counts']['candidate_entities']==0 and result['counts']['protein_groups']>0


def test_order_research_allowlist_detects_schema_drift():
    # Every newly added Order column must receive an explicit research/exclusion decision.
    import ast
    from ptm_shared.astra_inputs import RESEARCH_FIELDS,FILE_FIELDS
    source=ast.parse((Path(__file__).parents[2]/'api-server/app/models/order.py').read_text())
    cls=next(n for n in source.body if isinstance(n,ast.ClassDef) and n.name=='Order')
    fields={n.target.id for n in cls.body if isinstance(n,ast.AnnAssign)}
    operational={'id','user_id','run_by_user_id','status','priority','current_stage','progress_pct','stage_detail','result_files','error_message',
        'cross_talk_data','signal_propagation_data','kinase_analysis_data','receptor_inference_data','ip_overlay_data','kinase_activity_heatmap',
        'substrate_go_localization','watchdog_alerted_at','watchdog_restart_count','started_at','completed_at','created_at','updated_at','logs','reports'}
    assert fields==set(RESEARCH_FIELDS)|set(FILE_FIELDS)|operational


def test_membership_turnover_fixed_profile_and_target_exclusion(configuration,tmp_path):
    from ptm_shared.generic_workflow import calculate
    from ptm_shared.astra_discovery import discover,score_candidates,mapped_sites
    from ptm_shared.astra_sources import resolve_sources
    from ptm_shared.astra_temporal import integrate_temporal
    cfg=configuration;ctx=cfg['experimental_context'];design=ctx['study_design'];pr=pd.read_csv(cfg['pr_matrix_path'],sep='\t')
    selected=pr.Genes.eq('GENA')&pr['Modified.Sequence'].str.contains('UniMod:21',regex=False)
    row=pr.index[selected][0]
    for column in pr:
        if column.startswith('AB_60_'):pr.loc[row,column]=25.
        if column.startswith('AB_180_'):pr.loc[row,column]=np.nan
    pr.to_csv(cfg['pr_matrix_path'],sep='\t',index=False)
    inputs={k:Path(cfg[f]) for k,f in [('PR','pr_matrix_path'),('PG','pg_matrix_path'),('FASTA','fasta_path')]}
    tables,*_=calculate(inputs,design,{**ctx,'annotation_mode':'quantification_only'},None)
    mapped,_,fasta=mapped_sites(tables,design,inputs['FASTA'],ctx,[])
    sources=resolve_sources(cfg['reference_root'],mapped.to_dict('records'),fasta,'phosphorylation',fixtures=cfg['source_fixtures'])
    _,edges,_=discover(tables,design,inputs['FASTA'],ctx,sources)
    discovery=score_candidates(tables,edges,design);temporal=integrate_temporal(tables,discovery,design,ctx)
    p=discovery['kinase_temporal_profiles'];a=p.loc[p.candidate_gene.eq('EGFR')&p.track.eq('curated_A')]
    arm=next(c['arm_id'] for c in design['conditions'] if c['label']=='AB 60min');a=a.loc[a.arm_id.eq(arm)].sort_values('time_min')
    assert a.activity_magnitude.iloc[0]<a.activity_magnitude.iloc[1]
    fixed=temporal['kinase_fixed_membership'];fixed=fixed.loc[fixed.candidate_id.eq(a.candidate_id.iloc[0])&fixed.track.eq('curated_A')&fixed.contrast_id.isin(a.contrast_id)]
    assert np.allclose(fixed.fixed_common_score,1.) and fixed.departed_sites.sum()==1
    anchors=temporal['target_excluded_anchors'];assert anchors.target_excluded.all() and not anchors.independent_validation.any()
    assert not temporal['temporal_series'].paired_biological_units.any()
    # Two curated candidates have exactly the same substrate sets and cannot be resolved by these footprints.
    same=p.loc[p.candidate_gene.isin(['EGFR','SRC'])&p.track.eq('curated_A')]
    assert same.groupby('contrast_id').identifiability_group.nunique().eq(1).all()
    assert edges.localization_probability.isna().all()


def test_missing_alias_gene_uses_unambiguous_form_gene(configuration):
    from ptm_shared.generic_workflow import calculate
    from ptm_shared.astra_discovery import discover
    cfg=configuration;ctx=cfg['experimental_context'];design=ctx['study_design']
    fasta=Path(cfg['fasta_path']);sequence=fasta.read_text().splitlines()[1]
    with fasta.open('a') as handle:handle.write('>sp|ALIAS0|ALIAS_WITHOUT_GN OX=9606\n'+sequence+'\n')
    pr=pd.read_csv(cfg['pr_matrix_path'],sep='\t');pr.loc[pr.Genes.eq('GENA'),'Protein.Ids']='SYNTHETIC0;ALIAS0'
    pr.to_csv(cfg['pr_matrix_path'],sep='\t',index=False)
    inputs={k:Path(cfg[f]) for k,f in [('PR','pr_matrix_path'),('PG','pg_matrix_path'),('FASTA','fasta_path')]}
    tables,*_=calculate(inputs,design,{**ctx,'annotation_mode':'quantification_only'},None)
    _,edges,_=discover(tables,design,inputs['FASTA'],ctx,{'snapshots':[],'associations':[]})
    alias=edges.loc[edges.input_accession.eq('ALIAS0')]
    assert len(alias)>0
    assert alias.substrate_gene.eq('GENA').all()
    assert alias.substrate_gene_source.eq('unambiguous_form_representative_gene').all()
    assert 'ALIAS0' not in set(edges.substrate_gene)
