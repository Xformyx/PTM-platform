"""C03 bounded real temporal/projection functions on one form, no method/provider run."""
from copy import deepcopy
import json
from unittest.mock import patch
import numpy as np
import pandas as pd
import pytest
from test_generic_study import generic_fixture
from test_control_comparison import resolved
from ptm_shared.contrast_quantification import quantify_contrasts
from ptm_shared.effect_series import resolve_series
from ptm_shared.astra_evidence_v6 import integrate_temporal

TIMES=[1,5,15,30,60,180]


def fixture(gap=False):
    pr,pg,fasta,_,ctx,old=generic_fixture()
    pr=pr.drop(columns=[s['sample_id'] for s in old]);pg=pg.drop(columns=[s['sample_id'] for s in old])
    samples=[]
    for n,t in enumerate(TIMES):
        for role in ['Control','Treatment']:
            for rep in [1,2,3]:
                sid=f'{role}_{t}_{rep}'
                samples.append({'sample_id':sid,'condition':f'{role} {t}min','group':role,'replicate':rep,'control_family':'vehicle'})
                pr[sid]=10.*2**(n+(role=='Treatment'));pg[sid]=np.nan if gap and t==15 and role=='Control' else 2.
    ctx.update(quantitation_export_mode='astra_analysis.v6',replication_declaration='independent_biological_units',control_comparison={'strategy':'time_matched'})
    ctx=resolved(ctx,samples);design=ctx['study_design']
    tables=quantify_contrasts(pr,pg,fasta,design)
    discovery={
        'kinase_candidate_edges':pd.DataFrame(columns=['candidate_id','candidate_gene']),
        'substrate_contributions':pd.DataFrame(columns=['candidate_id','track','contrast_id','substrate_gene','site_key','form_ids']),
        'kinase_temporal_profiles':pd.DataFrame(columns=['candidate_id','track','contrast_id','activity_magnitude'])}
    temporal=integrate_temporal(tables,discovery,design,ctx)
    return pr,pg,ctx,tables,temporal,discovery


def test_six_real_effect_points_and_two_different_interval_meanings():
    _,_,ctx,tables,temporal,_=fixture();design=ctx['study_design']
    scopes,lookup=resolve_series(design);assert len(scopes)==1
    s=next(iter(scopes.values()));assert s['reference_condition_id'] is None
    assert len(s['reference_condition_ids'])==6 and [p['time_min'] for p in s['points']]==TIMES
    assert temporal['temporal_series'].iloc[0].reference_condition_id is None
    f=temporal['ptm_temporal_features'].query("track=='A'").iloc[0]
    assert f.observed_points==6 and json.loads(f.times_minutes)==TIMES
    assert f.adjacent_trapezoid_auc==pytest.approx(179)
    np.testing.assert_allclose(temporal['effect_interval_contrasts'].A,0,atol=1e-12,rtol=0)
    np.testing.assert_allclose(temporal['interval_contrasts'].A,1,atol=1e-12,rtol=0)
    assert len(temporal['effect_interval_contrasts'])==5
    assert all(len(r.split(';'))==3 for r in temporal['effect_interval_contrasts'].from_reference_run_ids)
    assert len(tables['runlevel'])==36 and tables['runlevel'].injection_id.nunique()==36
    assert tables['comparisons'].biological_p_value.isna().all()
    copied=deepcopy(design);copied['contrasts'].reverse();copied['conditions'].reverse()
    assert resolve_series(copied)==(scopes,lookup)


def test_missing_endpoint_is_not_bridged_and_point_pairing_is_retained():
    _,_,ctx,_,temporal,_=fixture(gap=True)
    f=temporal['ptm_temporal_features'].query("track=='A'").iloc[0]
    assert json.loads(f.observed_mask)==[True,True,False,True,True,True]
    intervals=temporal['effect_interval_contrasts']
    assert len(intervals)==5 and intervals.loc[intervals.from_min.eq(15)|intervals.to_min.eq(15),'A'].isna().all()
    assert not ((intervals.from_min==5)&(intervals.to_min==30)).any()
    d=deepcopy(ctx['study_design']);d['contrasts'][0]['pairing']='unknown'
    s=next(iter(resolve_series(d)[0].values()))
    assert s['pairing']=='mixed' and 'mixed_pairing' in s['inference_status']
    assert {p['pairing'] for p in s['points']}=={'unknown','unpaired'}


def test_scopes_never_mix_families_arms_baselines_or_invalid_references():
    _,_,ctx,_,_,_=fixture();d=deepcopy(ctx['study_design'])
    c=d['contrasts'][0];reference=next(x for x in d['conditions'] if x['condition_id']==c['reference_condition_id'])
    reference['control_family']='different_vehicle'
    with pytest.raises(ValueError,match='Invalid time-matched'):resolve_series(d)
    c['control_family']='different_vehicle'
    assert len(resolve_series(d)[0])==2
    target=next(x for x in d['conditions'] if x['condition_id']==d['contrasts'][1]['target_condition_id'])
    target['arm_id']='another_arm'
    assert len(resolve_series(d)[0])==3
    c.update(reference_strategy='shared_reference',effect_kind='reference_change')
    scopes,_=resolve_series(d)
    assert len(scopes)==3 and len([s for s in scopes.values() if s['reference_strategy']=='shared_reference'])==1


def test_method_order_figures_and_protein_summary_share_effect_scopes():
    from ptm_shared.astra_package import order_method_scores
    from ptm_shared.astra_figures import curve_series,heatmap_grid
    from ptm_shared.generic_workflow import temporal_layers
    _,_,ctx,tables,_,_=fixture();d=ctx['study_design']
    rows=[{'method_result_id':str(i),'method_id':'fixture_only','contrast_id':c['contrast_id'],'candidate_id':'kinase','score':i,'p_value':.5} for i,c in enumerate(d['contrasts'])]
    frame=pd.DataFrame(rows).sample(frac=1,random_state=5)
    ordered,audit=order_method_scores(frame,design=d,comparisons=tables['comparisons'])
    times=tables['comparisons'].set_index('contrast_id').time_min
    assert ordered.contrast_id.map(times).tolist()==TIMES and audit['effect_series_time_monotonic']
    pd.testing.assert_frame_equal(ordered.sort_values('method_result_id').reset_index(drop=True),frame.sort_values('method_result_id').reset_index(drop=True))
    selected,points=curve_series(tables['protein_contrasts'],'protein_group','log2_change',d)
    assert len(selected)==1 and points.time_min.tolist()==TIMES
    assert 'Time-matched controls' in selected.iloc[0].display_label
    assert points.reference_condition_id.nunique()==6
    _,meta=heatmap_grid(tables['comparisons'],'form_id','contrast_id','A',d)
    assert meta.time_min.tolist()==TIMES
    layers,_=temporal_layers(tables,d,ctx)
    assert layers['temporal_protein_summary'].query("layer=='PG'").measured_contrasts.tolist()==[6]


def reader_fixture(tmp_path):
    from ptm_shared.astra_card_inputs import project_card_inputs,validate_card_inputs
    from ptm_shared.astra_reader import build_reader_tables
    pr,_,ctx,quant,temporal,_=fixture();d=ctx['study_design']
    pr_path=tmp_path/'PR.tsv';pr.to_csv(pr_path,sep='\t',index=False)
    tables={**{'quant/'+k:v for k,v in quant.items() if isinstance(v,pd.DataFrame)},**{'temporal/'+k:v for k,v in temporal.items()}}
    # Explicit fixture identity/localization metadata; no identity/LLM/provider run.
    fid=quant['summary'].iloc[0].form_id
    tables['science/site_identity_audit']=pd.DataFrame([{'form_id':fid,'identity_id':'fixture_identity','site_id':'fixture_site','measurement_group_id':'fixture_group','substrate_taxon':9606,'mapping_status':'unique'}])
    tables['science/localization_by_contrast']=pd.DataFrame([{'form_id':fid,'contrast_id':c['contrast_id'],'localization_id':'loc_'+c['contrast_id'],'measurement_status':'missing_input'} for c in d['contrasts']])
    tables.update(project_card_inputs(tables,{'PR':pr_path},d,ctx));validate_card_inputs(tables,d)
    tables.update(build_reader_tables(tables,d,{'original':{'analysis_context':ctx}}))
    return tables,d


def test_card_reader_full_scope_and_saved_csv_replay(tmp_path):
    from ptm_shared.astra_card_inputs import consumer_states
    from ptm_shared.astra_reader_temporal import project_temporal
    from ptm_shared.astra_package import write_tables
    from ptm_shared.astra_reader_revision import read_tables
    from ptm_shared import astra_reader_full as full
    from ptm_shared.generic_workflow import json_write
    tables,d=reader_fixture(tmp_path)
    states=list(consumer_states(tables));assert len(states)==1
    assert len({p['reference_id'] for p in states[0]['vector_plot_raw_data']})==6
    packet=json.loads(tables['reader/packet'].iloc[0].packet_json)
    cards=[c for c in packet['reader_cards'] if c['category']=='measured_feature_observation']
    assert len(cards)==1 and len(cards[0]['trajectory'])==6
    data=project_temporal(tables,packet)
    assert data['findings'] and all(f['status']=='linked' for f in data['findings'])
    assert all(len(f['ordered_contrast_ids'])==6 for f in data['findings'])
    assert any(l['source_table']=='temporal/effect_series_points.csv' for l in data['links'])
    output=tmp_path/'saved';output.mkdir()
    descriptor=write_tables(tables,output,design=d)
    (output/'reproducibility').mkdir()
    json_write(output/'reproducibility/data_dictionary.json',descriptor)
    loaded=read_tables(output)
    # Saved-row replay has no scientific engine, methods or external retrieval.
    with patch('ptm_shared.astra_package.compute_science',side_effect=AssertionError('science forbidden')):
        assert project_temporal(loaded,packet)==data
    catalog={'sources':{k:{**v,'unique_key':v['unique_key'] or full.KEYS.get(k[:-4])} for k,v in descriptor.items()}}
    whole,summary=full.project_full(tables,catalog)
    assert len(whole[full.PREFIX+'temporal_subjects'])>0
    assert 'matched_effect_change' in set(whole[full.PREFIX+'temporal_links'].role)
    altered={k:v.copy(deep=True) for k,v in tables.items()}
    altered['reader/findings']=altered['reader/findings'].iloc[:0]
    other,_=full.project_full(altered,catalog)
    for key in ['temporal_subjects','temporal_links','question_links']:
        pd.testing.assert_frame_equal(whole[full.PREFIX+key],other[full.PREFIX+key])
    bad={k:v.copy(deep=True) for k,v in tables.items()}
    bad['temporal/effect_series_points'].loc[0,'reference_condition_id']='invented'
    with pytest.raises(ValueError,match='Effect point binding conflict'):project_temporal(bad,packet)


def test_tiny_matched_package_publication_uses_actual_effect_scope(tmp_path):
    """One synthetic form, fixture sources only; no native PhosX/RAG/LLM."""
    from test_generic_study import write_inputs
    from ptm_shared.astra_evidence_v6 import run
    from ptm_shared.astra_package import validate_package
    from ptm_shared.astra_reader_revision import read_tables
    from ptm_shared.astra_inputs import capture_order
    pr,pg,ctx,_,_,_=fixture()
    fasta=generic_fixture()[2]
    config=write_inputs(tmp_path,pr,pg,fasta)
    config.update(experimental_context=ctx,species='human',species_tax_id='9606',order_code='synthetic_matched',
        reference_root=str(tmp_path/'registry'),source_fixtures={
            'OmniPath':{'raw':'enzyme\tsubstrate\tresidue_type\tresidue_offset\n'},'iPTMnet':{'status':'timeout'},
            'KEA3':{'payload':{}},'STRING':{'payload':[]},'Reactome':{'payload':[]}},
        user_input_snapshot=capture_order({'order_code':'synthetic_matched','analysis_context':ctx}))
    with patch('requests.sessions.Session.request',side_effect=AssertionError('network forbidden')), \
         patch('ptm_shared.phosx_activity_adapter.execute',side_effect=AssertionError('native PhosX forbidden')):
        result=run(1,config,tmp_path/'output')
    root=tmp_path/'output/enrichment_free_runs'/result['run_id']
    validate_package(root)
    saved=read_tables(root)
    assert len(saved['temporal/temporal_series'])==1
    assert len(saved['temporal/effect_series_points'])==6
    assert len(saved['temporal/effect_interval_contrasts'])==5
    policy=json.loads((root/'study/control_comparison.json').read_text())
    assert policy['label']=='시간대별 Control 기준'
    assert '시간대별 Control 기준' in (root/'reader/READ_ME.md').read_text()
    assert '시간대별 Control 기준' in (root/'figures/figure_legends.json').read_text()
    assert saved['quant/comparisons'].biological_p_value.isna().all()
    assert saved['quant/comparisons'].biological_q_value.isna().all()


def test_saved_native_method_views_follow_effect_time_without_running_method():
    from ptm_shared.astra_reader import phosx_time_views
    _,_,ctx,quant,temporal,_=fixture()
    comparisons=quant['comparisons'];cids=comparisons.contrast_id.tolist()
    methods=pd.DataFrame([{'method_id':'PhosX_native_functions','contrast_id':cid,'candidate_id':'fixture_assay','status':'insufficient_coverage','score':None,'method_p':None,'method_q':None} for cid in reversed(cids)])
    tables={'quant/comparisons':comparisons,'temporal/effect_series_points':temporal['effect_series_points'],
        'kinase/method_executions':pd.DataFrame([{'method_id':'PhosX_native_functions','contrast_id':cid,'status':'fixture_saved_only'} for cid in reversed(cids)]),
        'science/site_identity_audit':pd.DataFrame(columns=['site_attribution_eligible','form_id','site_id']),
        'science/specificity_scores':pd.DataFrame(columns=['form_id','site_id','status','measurement_group_id','membership_selected']),
        'kinase/method_membership':pd.DataFrame(columns=['contrast_id','selected','measurement_group_id']),
        'kinase/method_scores':methods,
        'kinase/kinase_candidate_edges':pd.DataFrame([{'edge_type':'experimental_specificity_prediction','candidate_id':'fixture_assay','candidate_accession':'fixture_accession'}])}
    timeline,assays=phosx_time_views(tables)
    assert timeline.time_min.tolist()==assays.time_min.tolist()==TIMES
    assert assays.reference_condition_id.nunique()==6 and assays.method_p.isna().all()
    pd.testing.assert_frame_equal(tables['kinase/method_scores'],methods)
    # Reference hash ordering is immaterial, even when IDs are relabelled.
    from ptm_shared.astra_package import order_method_scores
    d=deepcopy(ctx['study_design']);refs=[p['reference_condition_id'] for p in next(iter(resolve_series(d)[0].values()))['points']]
    replacements=dict(zip(refs,reversed(refs)))
    for c in d['conditions']:c['condition_id']=replacements.get(c['condition_id'],c['condition_id'])
    for c in d['contrasts']:c['reference_condition_id']=replacements[c['reference_condition_id']]
    for i in d['injections']:i['condition_id']=replacements.get(i['condition_id'],i['condition_id'])
    ordered,audit=order_method_scores(methods,design=d)
    assert ordered.contrast_id.tolist()==timeline.contrast_id.tolist()
