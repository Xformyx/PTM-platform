"""Adversarial contracts; synthetic records do not establish real-report parity."""
import copy
import json
import pandas as pd
import pytest
from ptm_shared.localization_evidence import probability_sequence,protein_sites,by_contrast
from ptm_shared.kinase_specificity import select_membership


def test_documented_curly_grammar_does_not_copy_minimum():
    raw='AS(UniMod:21){0.99}T{0.01}AAK2'
    probs,status=probability_sequence(raw,'AS(UniMod:21)TAAK',2)
    assert status=='parsed' and probs=={2:.99,3:.01}
    assert probability_sequence(raw,'AS(UniMod:21)TAAK',3)[1]=='charge_or_sequence_mismatch'
    assert probability_sequence(raw.replace('0.99','1.2'),'AS(UniMod:21)TAAK',2)[1]=='invalid_probability'
    assert protein_sites('[P1:S4,T5];[P2:S9]')[0]=={('P1','S',4),('P1','T',5),('P2','S',9)}


def test_baseline_confidence_never_promotes_low_target_or_missing_charge():
    observations=pd.DataFrame([{'observation_id':'o0','form_id':'f','injection_id':'i0','quantification_contributor':True},
                               {'observation_id':'o1','form_id':'f','injection_id':'i1','quantification_contributor':True}])
    children=pd.DataFrame([{'observation_id':'o0','observation_site_id':'s0','site_id':'s','site_probability':.99,'assignment_status':'site_localization_supported'},
                          {'observation_id':'o1','observation_site_id':'s1','site_id':'s','site_probability':.1,'assignment_status':'site_localization_supported'}])
    ids=pd.DataFrame([{'form_id':'f','site_id':'s','site_attribution_eligible':True}])
    comp=pd.DataFrame([{'form_id':'f','contrast_id':'c','reference_joint_run_ids':'i0','target_joint_run_ids':'i1'}])
    result=by_contrast(observations,children,ids,comp).iloc[0]
    assert result.reference_pass_n==1 and result.target_pass_n==0 and not result.localized_eligible
    children.loc[1,'site_probability']=.99
    assert by_contrast(observations,children,ids,comp).iloc[0].localized_eligible
    assert not by_contrast(observations,children,ids,comp,expected_contributors={('f','i1'):2}).iloc[0].localized_eligible


def test_specificity_score_is_consumed_by_membership():
    scored=pd.DataFrame([{'form_id':'f','site_id':'s','candidate_id':k,'score':score,'percentile':score,'status':'scored'}
                         for k,score in [('high',99.9),('low',.1)]])
    selected,policy=select_membership(scored)
    assert selected.membership_selected.tolist()==[True,False]
    assert len(selected)==2  # low pair is retained, excluded from footprint only
    scored['percentile']=[.1,99.9]
    selected,_=select_membership(scored)
    assert selected.membership_selected.tolist()==[False,True]

from ptm_shared.tests.test_astra_science import config
from pathlib import Path
from ptm_shared.astra_evidence_v6 import run,prepare_evidence,calculate,discover,score_candidates,resolve_plan
from ptm_shared.astra_package import replay_package
from ptm_shared.science_reference import preflight


def add_report(config,tmp_path):
    pr=pd.read_csv(config['pr_matrix_path'],sep='\t');design=config['experimental_context']['study_design'];rows=[]
    for j,i in enumerate(design['injections']):
        for n,r in pr.loc[pr['Modified.Sequence'].str.contains('UniMod:21')].iterrows():
            raw=r['Modified.Sequence'].replace('(UniMod:21)','(UniMod:21){0.990000}')+str(r['Precursor.Charge'])
            rows.append({'Run':i['input_column'],'Run.Index':j,'Channel':'light','Precursor.Lib.Index':n,
                **{k:r[k] for k in ['Precursor.Id','Modified.Sequence','Precursor.Charge','Protein.Group','Protein.Ids']},
                'PTM.Site.Confidence':.98,'Lib.PTM.Site.Confidence':.999,'Q.Value':.001,'Site.Occupancy.Probabilities':raw})
    report=tmp_path/'main.tsv';pd.DataFrame(rows).to_csv(report,sep='\t',index=False)
    config['diann_report_path']=str(report);config['experimental_context']['science']['diann_version']='2.7.0'
    return rows


def test_v6_canonical_evidence_package_replay(config,tmp_path):
    config['experimental_context']['quantitation_export_mode']='astra_analysis.v6';add_report(config,tmp_path)
    result=run(1,config,tmp_path/'out');root=tmp_path/'out/enrichment_free_runs'/result['run_id']
    children=pd.read_csv(root/'science/observation_sites.csv');loc=pd.read_csv(root/'science/localization_by_contrast.csv')
    assert len(children) and children.individual_site_posterior.dropna().eq(.99).all()
    assert loc.localized_eligible.any()
    assert not (root/'science/calibrated_calls.csv').read_text().count('\n')>1
    replay_package(root,tmp_path/'replay')
    actual=pd.read_csv(root/'kinase/substrate_contributions.csv')
    assert actual.loc[actual.track.eq('localized_A'),'localization_ids'].notna().all()
    assert result['analysis_readiness']['selective_calls']['confirmed_calls']==0


def test_annotation_only_fingerprint_does_not_requantify(config):
    context=config['experimental_context'];first=resolve_plan(context,{'PR':'pr','PG':'pg','DIANN':'a'},'source')
    second=resolve_plan(context,{'PR':'pr','PG':'pg','DIANN':'b'},'source')
    assert first['fingerprints']['quant']==second['fingerprints']['quant']
    assert first['fingerprints']['identity_localization']!=second['fingerprints']['identity_localization']
    second=resolve_plan(context,{'PR':'pr','PG':'pg','DIANN':'a'},'other')
    assert first['fingerprints']['quant']==second['fingerprints']['quant']
    assert first['fingerprints']['discovery']!=second['fingerprints']['discovery']


def test_track_sharing_and_positive_policy_not_hardcoded(config,tmp_path):
    import hashlib
    from ptm_shared.inference_policy import evaluate
    from ptm_shared.astra_evidence_v6 import integrate_temporal
    from ptm_shared.science_reference import preflight
    config['experimental_context']['quantitation_export_mode']='astra_analysis.v6'
    context=config['experimental_context'];design=context['study_design'];reference=preflight(config,context)
    inputs={k:Path(config[f]) for k,f in [('PR','pr_matrix_path'),('PG','pg_matrix_path'),('FASTA','fasta_path')]}
    tables,_,_=calculate(inputs,design,context)
    context=prepare_evidence(tables,inputs,design,{**context,'_runtime_reference':reference,'_runtime_inputs':inputs})
    source=pd.read_csv(Path(config['fasta_path']).with_name('snapshot.tsv'),sep='\t');source=source.loc[source.enzyme.eq('EGFR')].copy();source['enzyme']='SYNTHETIC4'
    sources={'snapshots':[{'query_id':'synthetic','sha256':'synthetic','metadata':{'taxonomy_ids':['9606'],'orthology_translation':False},'rows':source.to_dict('records')}],'relations':[]}
    _,edges,_=discover(tables,design,inputs['FASTA'],context,sources)
    edges=edges.loc[edges.candidate_accession.eq('SYNTHETIC4')].copy()
    discovery=score_candidates(tables,edges,design,context);temporal=integrate_temporal(tables,discovery,design,context)
    assert evaluate(discovery,temporal,design)['calibrated_calls'].empty
    artifact={'policy_id':'synthetic_policy_not_biological_validation','domain':{'taxa':['9606'],'design_axes':['time_course'],'replication':['technical_per_condition']},
        'splits':{'development':['synthetic-dev'],'calibration':['synthetic-cal'],'held_out':['synthetic-test']},
        'rules':{'minimum_genes':3,'minimum_measurement_groups':2,'minimum_absolute_effect':.1,'allowed_tracks':['curated_A'],'reject_reasons':['shared_substrate_indistinguishable','gene_omission_unstable']},
        'calibration_metrics':{'risk_definition':'synthetic_behavior_only','truth_evaluable_n':1},'validation_evidence':{'status':'evaluated','evaluation_artifact_sha256':'a'*64},'resource_hashes':[]}
    artifact['sha256']=hashlib.sha256(json.dumps(artifact,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    called=evaluate(discovery,temporal,design,artifact)
    assert len(called['calibrated_calls'])>0
    assert called['calibrated_calls'].independent_validation_status.eq('not_performed').all()
    # Two candidates sharing the motif/specificity universe must remain shared,
    # even when curated_A is empty.
    duplicate=edges.copy();duplicate['candidate_id']='candidate_two';duplicate['edge_id']+='two'
    both=pd.concat([edges,duplicate],ignore_index=True);both['edge_type']='experimental_specificity_prediction'
    both['membership_selected']=True
    scored=score_candidates(tables,both,design,context);temporal=integrate_temporal(tables,scored,design,context)
    result=evaluate(scored,temporal,design)['inference_results']
    rows=result.loc[result.track.eq('specificity_A')&result.effective_substrate_genes.gt(0)]
    assert len(rows) and rows.no_call_reasons.str.contains('shared_substrate_indistinguishable').all()
    assert rows.discriminating_evidence_ids.eq('').all()


def test_documented_site_report_join_and_no_minimum_replication(config,tmp_path):
    from ptm_shared.diann_evidence import observations
    from ptm_shared.localization_evidence import read_site_report
    rows=add_report(config,tmp_path);pr=pd.read_csv(config['pr_matrix_path'],sep='\t')
    obs,_=observations(config['diann_report_path'],'2.7.0',pr,config['experimental_context']['study_design'])
    r=rows[0];site={'Run.Index':r['Run.Index'],'Channel':'light','Precursor.Lib.Index':r['Precursor.Lib.Index'],
        'Protein':r['Protein.Ids'],'Site':3,'Residue':'S','Modification':'UniMod:21','Occupied':True,'Probability':.97}
    path=tmp_path/'site.parquet';pd.DataFrame([site]).to_parquet(path)
    report,status=read_site_report(path,obs,'2.7.0')
    assert status['status']=='completed' and report.observation_id.iloc[0]==obs.observation_id.iloc[0]
    pd.DataFrame([site,{**site,'Probability':.1}]).to_parquet(path)
    report,_=read_site_report(path,obs,'2.7.0');assert report.status.eq('conflict').all()


def test_full_acquisition_reactome_scope_is_not_three(config,tmp_path):
    from ptm_shared.astra_sources import resolve_sources
    mapping=[{'mapped_accession':'P'+str(i),'fasta_taxonomy_id':'9606','fasta_gene':'G'+str(i)} for i in range(7)]
    fixtures={'OmniPath':{'raw':'enzyme\tsubstrate\tresidue_type\tresidue_offset\tmodification\tsources\treferences\n'},
        'iPTMnet':{'status':'timeout'},'STRING':{'payload':[]},'Reactome':{'payload':[]},'KEA3':{'payload':{}}}
    result=resolve_sources(tmp_path/'ref',mapping,{},'phosphorylation',fixtures=fixtures,acquisition_policy={'mode':'research_full'})
    queries=[q for q in result['queries'] if q['provider']=='Reactome']
    assert len(queries)==7 and all(q['status']=='no_hit' for q in queries)
    assert not any(q.get('reason')=='three_unique_accessions_per_run_operational_budget' for q in result['queries'])
    assert result['network_scopes']['9606']['status']=='not_evaluable'


def test_exact_group_sets_and_channel_crosswalk(config,tmp_path):
    from ptm_shared.diann_evidence import observations
    rows=add_report(config,tmp_path);pr=pd.read_csv(config['pr_matrix_path'],sep='\t')
    r=rows[0];pr.loc[pr['Precursor.Id'].eq(r['Precursor.Id']),'Protein.Group']='A;B'
    r['Protein.Group']='B;A';r['Channel']='light'
    other={**r,'Channel':'heavy'};path=tmp_path/'two.tsv';pd.DataFrame([r,other]).to_csv(path,sep='\t',index=False)
    design=config['experimental_context']['study_design']
    observed,_=observations(path,'2.7.0',pr,design,exact_group_sets=True)
    assert observed.match_status.eq('conflict').all()  # channel cannot double an injection
    chosen=design['injections'][:2];cross=tmp_path/'cross.csv'
    pd.DataFrame([{'Run':r['Run'],'Channel':channel,'input_column':inj['input_column'],'injection_id':inj['injection_id']}
        for channel,inj in zip(['light','heavy'],chosen)]).to_csv(cross,index=False)
    observed,_=observations(path,'2.7.0',pr,design,cross,exact_group_sets=True)
    assert observed.match_status.eq('matched').all() and observed.injection_id.nunique()==2
    assert observed.form_id.nunique()==1
    assert observed.source_fields_json.map(json.loads).map(lambda row:row['Protein.Group']).eq('B;A').all()
    r['Protein.Ids']='DIFFERENT_ISOFORM';pd.DataFrame([r]).to_csv(path,sep='\t',index=False)
    conflict,_=observations(path,'2.7.0',pr,design,cross,exact_group_sets=True)
    assert conflict.restriction_reasons.str.contains('report_matrix_accession_conflict').all()


def test_method_null_keeps_taxon_identity_separate():
    from ptm_shared.evidence_methods import zscore_baseline
    comparisons=pd.DataFrame([{'form_id':f'f{i}','contrast_id':'c','included':True,'A':float(i)} for i in range(4)])
    identities=pd.DataFrame([{'form_id':f'f{i}','substrate_taxon':'9606' if i<2 else '10090','input_accession':f'p{i}'} for i in range(4)])
    entries=[{'accession':f'p{i}','gene':'A' if i%2==0 else 'B'} for i in range(4)]
    members=pd.DataFrame([{'candidate_id':'k','contrast_id':'c','track':'curated_A','substrate_gene':g,
        'value':v,'site_key':f's{v}','contribution_id':f'e{v}'} for g,v in [('9606:A',0),('10090:A',2)]])
    actual=zscore_baseline({'comparisons':comparisons},{'substrate_contributions':members},identities,entries).iloc[0]
    assert actual.universe_count==4 and actual.statistical_unit=='substrate_gene'
    assert actual.score==pytest.approx((1-1.5)*2**.5/(1.25**.5))
    assert pd.isna(actual.biological_p_value)


def test_string_cross_batch_scope_and_taxonomy():
    from ptm_shared.source_acquisition import string_network
    class Client:
        def __init__(self):self.calls=[]
        def query(self,provider,query,endpoint,form):
            self.calls.append(query)
            payload=([{'queryItem':a,'ncbiTaxonId':'10090','stringId':'10090.'+a} for a in query['accessions']]
                if query['step']=='identifier_mapping' else [{'ncbiTaxonId':'10090','stringId_A':'10090.P0','stringId_B':'10090.P100'}])
            return {'query_id':str(len(self.calls)),'status':'hit','payload':payload}
        def accept(self,rec,rows):rec.update(status='hit' if rows else 'no_hit',parsed_rows=rows)
    client=Client();edges,ids,scope=string_network(client,[f'P{i}' for i in range(101)],'10090')
    assert len(client.calls)==3 and len(client.calls[-1]['identifiers'])==101
    assert len(edges)==1 and edges[0]['record']['stringId_B']=='10090.P100'
    assert scope['cross_batch_edges']=='requested_together' and scope['unique_resolved_ids']==101


def test_interruption_keeps_pointer_then_reuses_quant(config,tmp_path):
    config['experimental_context']['quantitation_export_mode']='astra_analysis.v6'
    root=tmp_path/'out';first=run(1,config,root);pointer=(root/'enrichment_free_current.json').read_bytes()
    # Dispatch carries the pinned references on rerun (also covered by the real
    # API integration); a new source acquisition is intentionally a new input.
    config['source_pin_sha256']=first['source_pin_sha256']
    def interrupted(stage):
        if stage=='discover_regulators':raise RuntimeError('synthetic interruption')
    with pytest.raises(RuntimeError,match='synthetic interruption'):run(1,config,root,progress=interrupted)
    assert (root/'enrichment_free_current.json').read_bytes()==pointer
    resumed=run(1,config,root)
    before=root/'enrichment_free_runs'/first['run_id'];after=root/'enrichment_free_runs'/resumed['run_id']
    assert json.loads((after/'provenance.json').read_text())['stage_reuse']['quant']['status']=='reused'
    reuse=json.loads((after/'provenance.json').read_text())['stage_reuse']
    for stage in ('identity_localization','discover_regulators','score_regulator_footprints','integrate_temporal_layers'):
        assert reuse[stage]['status']=='reused'
    for group in ('quant','kinase','science','temporal'):
        for file in (before/group).glob('*.csv'):
            assert file.read_bytes()==(after/group/file.name).read_bytes(),file.name


def test_stage_checkpoint_checksum_failure_recomputes(tmp_path):
    from ptm_shared.evidence_stage_cache import cached_stage
    original=pd.DataFrame({'id':['x','y'],'value':[None,1.25],'text':['','unknown']})
    calls=[]
    def compute():calls.append(1);return {'table':original.copy(),'unknown':float('nan')}
    first,_=cached_stage(tmp_path,'test','same',compute)
    second,status=cached_stage(tmp_path,'test','same',compute)
    assert status['status']=='reused' and len(calls)==1
    pd.testing.assert_frame_equal(first['table'],second['table'])
    next(tmp_path.glob('*/table_0.parquet')).write_bytes(b'corrupt')
    third,status=cached_stage(tmp_path,'test','same',compute)
    assert status['status']=='computed' and len(calls)==2
    pd.testing.assert_frame_equal(original,third['table'])
