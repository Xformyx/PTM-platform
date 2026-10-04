"""Scientific failure-mode regressions; synthetic data are not biological validation."""
import copy
import json
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
import pytest
from scripts.validate_generic_platform import make_fixture
from ptm_shared.study_design import resolve_study_design
from ptm_shared.science_reference import preflight,inventory,select_reference,PreflightError
from ptm_shared.astra_science import run,resolve_plan,calculate
from ptm_shared.astra_package import replay_package,validate_package
from ptm_shared.diann_evidence import observations,apply_observation_policy
from benchmarking.astra_science.evaluate import validate_manifest,selective_metrics


@pytest.fixture
def config(tmp_path):
    f=tmp_path/'fixture';d=make_fixture(f)
    c={**d['analysis_context'],'quantitation_export_mode':'astra_analysis.v5','science':{}}
    c['study_design']=resolve_study_design(c,d['sample_config'],taxonomy_id='9606',species='human')
    return {'experimental_context':c,'species_tax_id':'9606','species':'human','order_code':'synthetic_science',
        'reference_root':str(tmp_path/'registry'),'source_fixtures':{'OmniPath':{'raw':(f/'snapshot.tsv').read_text()},
        'iPTMnet':{'status':'timeout'},'KEA3':{'payload':{}},'STRING':{'payload':[]},'Reactome':{'payload':[]}},
        **{key:str(f/file) for key,file in [('pr_matrix_path','PR.tsv'),('pg_matrix_path','PG.tsv'),('fasta_path','reference.fasta')]}}


def switch_species(config,species,tax):
    c=copy.deepcopy(config);c['species']=species;c['species_tax_id']=tax
    c['experimental_context']['study_design']['study'].update(species=species,taxonomy_id=tax)
    return c


@pytest.mark.parametrize('species,tax',[('human','9606'),('mouse','10090'),('rat','10116')])
def test_alias_sources_pool_before_scoring_and_temporal(config,species,tax):
    from ptm_shared.astra_discovery import discover,score_candidates
    from ptm_shared.astra_temporal import integrate_temporal
    c=switch_species(config,species,tax)
    fasta=Path(c['fasta_path']);fasta.write_text(fasta.read_text().replace('9606',tax))
    ctx=c['experimental_context'];design=ctx['study_design']
    ctx['_science_reference']=preflight(c,ctx)
    inputs={short:Path(c[key]) for short,key in [('PR','pr_matrix_path'),('PG','pg_matrix_path'),('FASTA','fasta_path')]}
    tables,_,_=calculate(inputs,design,ctx)
    rows=pd.read_csv(fasta.with_name('snapshot.tsv'),sep='\t')
    rows=rows.loc[rows.enzyme.eq('EGFR')].copy();rows['enzyme']='SYNTHETIC4'
    sources={'snapshots':[{'query_id':'omnipath','sha256':'synthetic',
        'metadata':{'taxonomy_ids':[tax],'orthology_translation':False},'rows':rows.to_dict('records')}],
        'relations':[]}
    _,original,_=discover(tables,design,fasta,ctx,sources)
    original=original.loc[original.candidate_accession.eq('SYNTHETIC4')]
    expected=score_candidates(tables,original,design,science=True)
    # iPTMnet can supply only the accession; OmniPath supplies the gene label.
    sources['relations']=[{'enzyme_id':'SYNTHETIC4','accession':r.substrate,
        'site':r.residue_type+str(r.residue_offset),'query_id':'iptmnet','sources':['PhosphoSite'],'pmids':[]}
        for r in rows.itertuples()]
    _,edges,_=discover(tables,design,fasta,ctx,sources)
    edges=edges.loc[edges.candidate_accession.eq('SYNTHETIC4')].copy()
    assert set(edges.candidate_gene)=={'EGFR'}
    assert edges.candidate_id.nunique()==1 and set(edges.kinase_taxon)=={tax}
    # Defend the scoring contract even for noncanonical display labels from an
    # additional adapter (e.g. a specificity resource).
    edges.loc[edges.provider.eq('iPTMnet'),'candidate_gene']='SYNTHETIC4'
    actual=score_candidates(tables,edges,design,science=True)
    profiles=actual['kinase_temporal_profiles']
    pd.testing.assert_frame_equal(profiles,expected['kinase_temporal_profiles'])
    assert not profiles.duplicated(['candidate_id','contrast_id','track']).any()
    contributions=actual['substrate_contributions']
    assert not contributions.contribution_id.duplicated().any()
    assert len(contributions)==len(expected['substrate_contributions'])
    assert contributions.source_query_ids.str.contains('iptmnet').all()
    assert contributions.source_query_ids.str.contains('omnipath').all()
    temporal=integrate_temporal(tables,actual,design,ctx)
    assert temporal['kinase_temporal_features'].feature_id.is_unique
    # Same label with a different identity must remain a separate candidate.
    other=original.copy();other['candidate_id']='different_accession_identity';other['candidate_accession']='OTHER'
    separate=score_candidates(tables,pd.concat([original,other]),design,science=True)
    assert separate['kinase_temporal_profiles'].candidate_id.nunique()==2
    broken={**actual,'kinase_temporal_profiles':pd.concat([profiles,profiles.iloc[:1]])}
    with pytest.raises(ValueError,match='duplicate_temporal_observations: entity='):
        integrate_temporal(tables,broken,design,ctx)


def test_current_astra_request_and_obsolete_opt_in(config):
    from ptm_shared.analysis_context import current_astra_context,merge_analysis_context
    from ptm_shared.astra_science import validate_execution
    old=copy.deepcopy(config['experimental_context']);old['quantitation_export_mode']='astra_analysis.v4'
    old['science']={'experimental_enabled':False,'diann_version':'2.7.0'}
    updated=current_astra_context(old)
    assert updated['quantitation_export_mode']=='astra_analysis.v5'
    assert old['quantitation_export_mode']=='astra_analysis.v4'
    assert updated['science']==old['science'] and updated['study_design']==old['study_design']
    validate_execution(updated,'phosphorylation','9606')
    for mode in ['legacy_only.v1','enrichment_free_primary.v2','enrichment_free_timecourse.v3']:
        context={**old,'quantitation_export_mode':mode}
        assert current_astra_context(context)==context
    assert current_astra_context({})=={}  # API still requires an explicit purpose.
    assert merge_analysis_context(old,{})==old  # PATCH/replay is not migration.


@pytest.mark.parametrize('species,tax,fasta_tax',[('mouse','10090','9606'),('human','9606','10090')])
def test_species_conflict_before_provider_or_publication(config,tmp_path,species,tax,fasta_tax):
    c=switch_species(config,species,tax);p=Path(c['fasta_path']);p.write_text(p.read_text().replace('9606',fasta_tax))
    with patch('ptm_shared.astra_package.resolve_sources',side_effect=AssertionError('provider must not run')):
        with pytest.raises(PreflightError,match='species_reference_conflict'):run(1,c,tmp_path/'out')
    assert not (tmp_path/'out/enrichment_free_current.json').exists()


def test_reference_id_no_filename_fallback_and_missing_taxon(config,tmp_path):
    folder=tmp_path/'human';folder.mkdir();(folder/'aaa_wrong.fasta').write_text('>a OX=10090\nASAA\n')
    with pytest.raises(PreflightError,match='reference_id_required'):select_reference(tmp_path,None)
    config.pop('species_tax_id')
    with pytest.raises(PreflightError,match='taxonomy_required'):preflight(config,config['experimental_context'])


def test_custom_taxonomy_mapping_and_decoys(config,tmp_path):
    p=Path(config['fasta_path']);p.write_text(p.read_text().replace(' OX=9606','')+'\n>DECOY_bad OX=10090\nASAA\n')
    without=preflight(config,config['experimental_context']);assert without['species_resolution_status']=='partial_unknown_taxonomy'
    mapping={'source':'synthetic_registered_mapping','release':'fixture.v1','accessions':{f'SYNTHETIC{i}':{'taxon':'9606','gene':f'G{i}'} for i in range(5)}}
    path=tmp_path/'mapping.json';path.write_text(json.dumps(mapping));config['taxonomy_mapping_path']=str(path)
    ref=preflight(config,config['experimental_context']);assert ref['reference_taxon_inventory']==['9606']
    assert ref['species_resolution_status']=='verified_inventory' and ref['taxonomy_mapping_resource_sha256']
    assert ref['entries'][-1]['entry_kind']=='decoy'


def test_explicit_mixed_taxa_no_host_inference(config):
    p=Path(config['fasta_path']);p.write_text(p.read_text()+'\n>sp|MOUSE|shared GN=GENA OX=10090\nMASAAKQQASTTKPEPTIDEAAKPEPTIDEVVK\n')
    config['experimental_context']['science']['reference']={'species_scope':'mixed_species','expected_sample_taxa':['9606','10090']}
    ref=preflight(config,config['experimental_context']);assert ref['host_taxon'] is None
    assert ref['reference_taxon_inventory']==['10090','9606']


def test_exact_diann_observations_charge_run_library_conflicts(config,tmp_path):
    pr=pd.read_csv(config['pr_matrix_path'],sep='\t');design=config['experimental_context']['study_design'];r=pr.iloc[2]
    first=design['injections'][0];second=design['injections'][1]
    rows=[]
    for run,conf in [(first['input_column'],.9),(second['input_column'],.2),('/different/'+first['input_column'],.99)]:
        rows.append({'Run':run,**{k:r[k] for k in ['Precursor.Id','Modified.Sequence','Precursor.Charge','Protein.Group','Protein.Ids']},'PTM.Site.Confidence':conf,'Lib.PTM.Site.Confidence':.999,'Q.Value':.001})
    rows.append({**rows[0],'Precursor.Charge':3})
    report=tmp_path/'report.tsv';pd.DataFrame(rows).to_csv(report,sep='\t',index=False)
    obs,status=observations(report,'2.7.0',pr,design)
    assert obs.localization_metric_value.tolist()==[.9,.2,.99,.9]
    assert obs.match_status.tolist()==['matched','matched','restricted','restricted']
    assert 'run_crosswalk_required' in obs.iloc[2].restriction_reasons
    assert 'matrix_precursor_unmatched' in obs.iloc[3].restriction_reasons
    filtered=apply_observation_policy(pr,obs,design,{'mode':'validated_observations','normalization_scope':'recompute_once_after_filter','minimum_run_confidence':.75,'maximum_precursor_q':.01})
    assert filtered.at[2,first['input_column']]==pr.at[2,first['input_column']]
    assert pd.isna(filtered.at[2,second['input_column']])
    pd.DataFrame([rows[0],{**rows[0],'PTM.Site.Confidence':.1}]).to_csv(report,sep='\t',index=False)
    obs,_=observations(report,'2.7.0',pr,design);assert obs.match_status.eq('conflict').all()
    with pytest.raises(ValueError,match='unsupported_diann_version'):observations(report,None,pr,design)
    library=[{k:v for k,v in rows[0].items() if k!='PTM.Site.Confidence'}]
    pd.DataFrame(library).to_csv(report,sep='\t',index=False)
    obs,_=observations(report,'2.7.0',pr,design);assert obs.localization_metric_value.isna().all()


@pytest.mark.parametrize('species,tax',[('human','9606'),('mouse','10090')])
def test_species_package_replay_no_confirmed_calls(config,tmp_path,species,tax):
    c=switch_species(config,species,tax);f=Path(c['fasta_path']);f.write_text(f.read_text().replace('9606',tax))
    result=run(1,c,tmp_path/'out');root=tmp_path/'out/enrichment_free_runs'/result['run_id']
    comp=pd.read_csv(root/'quant/comparisons.csv');finite=comp.loc[comp.included]
    assert np.allclose(finite.A,finite.U_joint-finite.P_joint)
    assert np.allclose(np.abs(finite.A),1);assert comp.biological_p_value.isna().all()
    calls=pd.read_csv(root/'science/kinase_calls.csv');assert calls.resolution.eq('no_call').all()
    assert calls.no_call_reasons.str.contains('uncalibrated_policy').all()
    edges=pd.read_csv(root/'kinase/kinase_candidate_edges.csv');assert edges.kinase_taxon.isna().all() # fixture enzyme identifiers lack accession evidence
    assert set(edges.substrate_taxon.astype(str))=={tax}
    with patch('socket.socket',side_effect=AssertionError('offline replay attempted network')):
        replay_package(root,tmp_path/'replay')
    replay=json.loads((tmp_path/'replay/replay_result.json').read_text());assert replay['passed']
    assert len(replay['tables'])==57
    # A repository-imported replay hides omitted portable modules. A fresh process
    # outside the checkout must load only the package's pinned code.
    import os,subprocess,sys
    standalone=tmp_path/'standalone'
    subprocess.run([sys.executable,str((root/'replay.py').resolve()),'--output',str(standalone)],
        cwd=tmp_path,env={**os.environ,'PYTHONPATH':''},check=True,capture_output=True,text=True)
    assert json.loads((standalone/'replay_result.json').read_text())['passed']


@pytest.mark.parametrize('target',['phosphoproteomics','proteomics'])
def test_cross_sectional_and_protein_only(config,tmp_path,target):
    ctx=config['experimental_context'];ctx['design_axis']='cross_sectional';ctx['analysis_target']=target
    ptm='proteomics' if target=='proteomics' else 'phosphorylation'
    design=ctx['study_design'];design['study'].update(design_axis='cross_sectional',analysis_target=target,ptm_type=ptm)
    for c in design['conditions']:c['time']=None
    if target=='proteomics':config.pop('pr_matrix_path')
    result=run(1,config,tmp_path/'out');root=tmp_path/'out/enrichment_free_runs'/result['run_id']
    assert result['analysis_readiness']['temporal']['status']=='not_applicable'
    protein=pd.read_csv(root/'quant/protein_contrasts.csv');assert len(protein)==20 and protein.time_min.isna().all()
    if target=='proteomics':
        assert pd.read_csv(root/'quant/comparisons.csv').empty
        assert result['analysis_readiness']['kinase']['status']=='not_applicable'
    replay_package(root,tmp_path/'replay')


def test_pg_absent_errors_instead_of_fake_adjustment(config):
    config.pop('pg_matrix_path')
    with pytest.raises(PreflightError,match='parent_input_required'):preflight(config,config['experimental_context'])


def test_plan_inputs_and_questions(config):
    ctx=config['experimental_context'];a=resolve_plan(ctx,{'FASTA':'one'})
    changed=copy.deepcopy(ctx);changed['biological_question']='EGF expected'
    assert a['fingerprints']==resolve_plan(changed,{'FASTA':'one'})['fingerprints']
    assert a['fingerprints']!=resolve_plan(ctx,{'FASTA':'two'})['fingerprints']


def test_benchmark_leakage_and_unknown_truth():
    record={'dataset_id':'a','study_id':'study','cohort_id':'cohort','raw_sha256':'a'*64,'taxon':'9606','split':'development','truth_scope':'kinase','license':'synthetic','independent_unit_definition':'sample','source_overlap':[]}
    with pytest.raises(ValueError,match='leakage'):validate_manifest([record,{**record,'dataset_id':'b','split':'locked_test','raw_sha256':'b'*64}])
    result=selective_metrics([{'evaluation_resolution':'kinase','resolution':'kinase','correct':None},{'evaluation_resolution':'kinase','resolution':'kinase','correct':True}])[0]
    assert result['selective_risk']==0 and result['truth_evaluable_fraction']==.5


def test_specificity_is_separate_and_matrix_semantics(tmp_path):
    from ptm_shared.kinase_specificity import score_sites
    from ptm_shared.annotation_registry import digest
    matrices={'K_HUMAN':{'kinase_taxon':'9606','weights':{'-1':{'A':1.},'0':{'S':2.},'1':{'A':3.}}}}
    (tmp_path/'matrix.json').write_text(json.dumps(matrices));(tmp_path/'background.json').write_text(json.dumps({'K_HUMAN':[0,3,6,9]}))
    meta={'resource_id':'synthetic_not_atlas','resource_version':'test.v1','publication_doi':None,'source_url':'synthetic',
        'license_identifier':'test_fixture','redistribution_status':'permitted','assay_taxon':'9606','supported_center_residues':['S'],
        'window_offsets':[-1,0,1],'alphabet':'AS','matrix_scale':'log2_additive','pseudocount_policy':'none','terminal_policy':'reject','priming_modification_policy':'reject',
        'matrix_sha256':digest(tmp_path/'matrix.json'),'background_sha256':digest(tmp_path/'background.json'),
        'matrix_file':'matrix.json','background_file':'background.json'}
    manifest=tmp_path/'resource.json';manifest.write_text(json.dumps(meta))
    site={'site_id':'s1','form_id':'f1','measurement_group_id':'m1','substrate_taxon':'10116','input_accession':'RAT','input_position':2}
    frame,status=score_sites(pd.DataFrame([site,{**site,'site_id':'s2','input_position':1}]),[{'accession':'RAT','sequence':'ASA'}],manifest)
    assert frame.iloc[0].score==6 and frame.iloc[0].percentile==75
    assert frame.iloc[0].kinase_taxon=='9606' and frame.iloc[0].substrate_taxon=='10116'
    assert frame.iloc[1].status=='not_evaluable'
    assert status['official_parity_status']=='official_parity_not_verified'
    assert frame.edge_type.eq('experimental_specificity_prediction').all()
    primed,_=score_sites(pd.DataFrame([{**site,'form_modification_count':2}]),[{'accession':'RAT','sequence':'ASA'}],manifest)
    assert primed.score.isna().all() and primed.restriction_reasons.eq('priming_or_multisite_context_unsupported').all()


def test_pair_unit_resampling_covariance_and_technical_pseudoreplication(config):
    from ptm_shared.contrast_quantification import ContrastEstimator
    from ptm_shared.science_inference import unit_intervals
    design=copy.deepcopy(config['experimental_context']['study_design']);design['replication_declaration']='independent_biological_units'
    # Three declared donors across conditions. Each donor's PTM-parent ratio differs,
    # but the paired contrast is exactly 1. Identical PTM/parent fluctuations cancel.
    design['materials']=[]
    for i,s in enumerate(design['injections']):
        donor=i%3;mid=s['injection_id'];s['material_id']=mid
        design['materials'].append({'material_id':mid,'biological_unit_id':f'donor{donor}','pair_id':f'pair{donor}'})
    for c in design['contrasts']:c['pairing']='paired'
    est=ContrastEstimator(design);ref=design['contrasts'][0]['reference_condition_id']
    values=np.array([[int(s['material_id'][-1],16) if False else 1+(s['condition_id']!=ref) for s in est.samples]],float)
    result=unit_intervals({'arrays':{'A':values},'summary':pd.DataFrame({'form_id':['f']}),'estimator':est},design,{'enabled':True,'resamples':100})
    assert result.interval_low.eq(1).all() and result.interval_high.eq(1).all()
    design['replication_declaration']='technical_per_condition'
    result=unit_intervals({'arrays':{'A':values},'summary':pd.DataFrame({'form_id':['f']}),'estimator':est},design,{'enabled':True,'resamples':100})
    assert result.interval_low.isna().all()


def test_perturbation_interaction_scoped_and_synthetic_not_validation(tmp_path):
    from ptm_shared.perturbation_validation import import_validation
    rows=[{'target_id':'site1','time':5,'arm':arm,'biological_unit_id':f'{arm}_{i}','pair_id':f'p{i}','value':value+i*.2}
          for i in range(3) for arm,value in [('vehicle',0),('stimulus',2),('inhibitor',-.5),('stimulus_plus_inhibitor',.5)]]
    meta={k:'provided_fixture' for k in ['dataset_id','cohort_id','discovery_run_id','assay_type','site_mapping_evidence','intervention_identity','dose_and_timing','biological_unit_definition']}
    meta.update(independence_from_discovery='confirmed_independent_cohort',scale='A',pairing='paired',panel_selection='synthetic_predeclared',observations=rows,synthetic=True,baseline_strategy='shared_scale_no_arm_specific_baseline')
    path=tmp_path/'validation.json';path.write_text(json.dumps(meta))
    result,status=import_validation(path)
    assert np.isclose(result.effect_estimate.iloc[0],-1)
    assert np.isclose(result.interval_low.iloc[0],-1) and np.isclose(result.interval_high.iloc[0],-1)
    assert not status['independent_experiment_available']
    original=result.validation_id.iloc[0];meta['cohort_id']='new_cohort';path.write_text(json.dumps(meta))
    assert import_validation(path)[0].validation_id.iloc[0]!=original


def test_parquet_and_tsv_equivalent_observation_joins(config,tmp_path):
    pr=pd.read_csv(config['pr_matrix_path'],sep='\t');r=pr.iloc[2];design=config['experimental_context']['study_design']
    frame=pd.DataFrame([{'Run':design['injections'][0]['input_column'],**{k:r[k] for k in ['Precursor.Id','Modified.Sequence','Precursor.Charge','Protein.Group','Protein.Ids']},'PTM.Site.Confidence':1.2}])
    tsv=tmp_path/'report.tsv';parquet=tmp_path/'report.parquet';frame.to_csv(tsv,sep='\t',index=False);frame.to_parquet(parquet)
    a,_=observations(tsv,'2.7.0',pr,design);b,_=observations(parquet,'2.7.0',pr,design)
    assert a.iloc[0].restriction_reasons==b.iloc[0].restriction_reasons=='invalid_run_confidence'
    assert a.iloc[0].injection_id==b.iloc[0].injection_id


def test_enzyme_taxon_protein_link_is_not_substrate_taxon():
    from ptm_shared.science_reference import candidate_protein_groups
    entries=[{'accession':'H','taxon':'9606','gene':'KIN'},{'accession':'M','taxon':'10090','gene':'KIN'}]
    edges=pd.DataFrame({'kinase_taxon':['10090'],'candidate_accession':[None],'candidate_gene':['KIN']})
    assert candidate_protein_groups(edges,['H','M','H;M'],{'entries':entries})=={'M'}
    edges['kinase_taxon']=None
    assert candidate_protein_groups(edges,['H','M'],{'entries':entries})==set()


def test_two_sites_same_window_keep_identity_and_mapping_dependence(config):
    from ptm_shared.astra_science import site_identity
    ref=preflight(config,config['experimental_context']);entry=ref['entries'][0]
    form={'form_id':'f','Stripped.Sequence':'ASAAK','n_modifications':1,'primary_adjustment_eligible':True,
        'mapping_json':json.dumps([{'accession':entry['accession'],'sites':['S3'],'gene':'GENA'},
            {'accession':entry['accession'],'sites':['S10'],'gene':'GENA'}])}
    table=site_identity(pd.DataFrame([form]),ref)
    assert table.site_id.nunique()==2 and table.measurement_group_id.nunique()==1
    assert not table.site_attribution_eligible.any()


def test_restricted_specificity_not_redistributed_and_quantification_continues(config,tmp_path):
    target=tmp_path/'out';target.mkdir();pointer=target/'enrichment_free_current.json';pointer.write_text('{"old":true}')
    manifest=tmp_path/'license.json';manifest.write_text(json.dumps({'redistribution_status':'unresolved'}))
    config['specificity_manifest_path']=str(manifest)
    result=run(1,config,target)
    assert result['analysis_readiness']['specificity']['status']=='license_unresolved'
    root=target/'enrichment_free_runs'/result['run_id']
    assert pd.read_csv(root/'science/specificity_scores.csv').empty
    assert not pd.read_csv(root/'quant/comparisons.csv').empty
    assert not (root/'inputs/matrix.json').exists()
    replay_package(root,tmp_path/'replay')


def test_registered_mapping_does_not_promote_unreviewed_accessions(config):
    from ptm_shared.astra_science import normalized_reference
    path=Path(config['fasta_path']);path.write_text(path.read_text().replace('>sp|','>tr|'))
    inputs={'FASTA':path,'PG':Path(config['pg_matrix_path']),'PR':Path(config['pr_matrix_path'])}
    normalized,reference=normalized_reference(inputs,config['experimental_context'])
    assert all(not entry['reviewed'] for entry in reference['entries'])
    assert '>sp|' not in normalized.read_text()


def test_explicit_reference_selects_manifest_not_alphabetic_file(tmp_path):
    from ptm_shared.annotation_registry import digest
    root=tmp_path/'sequence_references/human-release';root.mkdir(parents=True)
    (root/'a_mouse.fasta').write_text('>M OX=10090\nASA\n')
    human=root/'z_human.fasta';human.write_text('>H OX=9606\nASA\n')
    (root/'manifest.json').write_text(json.dumps({'reference_id':'human-release','version':'test.v1','file':human.name,'sha256':digest(human)}))
    selected,_=select_reference(tmp_path,'human-release');assert selected==str(human)
    human.write_text('changed')
    with pytest.raises(PreflightError,match='checksum'):select_reference(tmp_path,'human-release')


def test_registry_mapping_survives_worker_capture_and_offline_replay(config,tmp_path):
    import re
    from ptm_shared.annotation_registry import digest
    from ptm_shared.science_reference import bind_registered_reference
    original=Path(config['fasta_path'])
    entries=inventory(original)
    root=Path(config['reference_root'])/'sequence_references/custom-human';root.mkdir(parents=True)
    fasta=root/'custom.fasta'
    fasta.write_text(re.sub(r' (?:OX|GN)=[^\s]+','',original.read_text()))
    manifest=root/'manifest.json'
    manifest.write_text(json.dumps({'reference_id':'custom-human','version':'synthetic.v1','file':fasta.name,
        'sha256':digest(fasta),'taxonomy_mapping':{'source':'synthetic','release':'test.v1',
            'accessions':{e['accession']:{'taxon':e['taxon'],'gene':e['gene']} for e in entries}}}))
    config['experimental_context']['science']['reference']={'reference_id':'custom-human'}
    path,context,mapping=bind_registered_reference(config['reference_root'],config['experimental_context'])
    assert context['science']['reference']['registry_manifest_sha256']==digest(manifest)
    assert 'accessions' not in json.dumps(context['science']['reference'])
    config.update(fasta_path=path,experimental_context=context,taxonomy_mapping_path=mapping)
    result=run(1,config,tmp_path/'out')
    package=tmp_path/'out/enrichment_free_runs'/result['run_id']
    audit=pd.read_csv(package/'science/reference_inventory.csv')
    assert audit.taxon.astype(str).eq('9606').all()
    assert audit.taxonomy_source.eq('registered_mapping').all()
    manifest.unlink();fasta.unlink()
    replay_package(package,tmp_path/'replay')


def test_shared_species_peptide_is_one_measurement_not_two_sites_of_evidence(config):
    from ptm_shared.astra_science import site_identity
    ref=preflight(config,config['experimental_context']);entry=ref['entries'][0]
    ref['entries'].append({**entry,'accession':'MOUSE','taxon':'10090'})
    table=site_identity(pd.DataFrame([{'form_id':'shared','Stripped.Sequence':'ASAAK','n_modifications':1,
        'primary_adjustment_eligible':True,'mapping_json':json.dumps([
            {'accession':entry['accession'],'sites':['S3']},{'accession':'MOUSE','sites':['S3']}])}]),ref)
    assert table.species_ambiguous.all() and table.measurement_group_id.nunique()==1
    assert not table.site_attribution_eligible.any()


def test_raw_diann_version_invalid_numeric_and_fractional_charge(config,tmp_path):
    pr=pd.read_csv(config['pr_matrix_path'],sep='\t');r=pr.iloc[2];design=config['experimental_context']['study_design']
    record={'Run':design['injections'][0]['input_column'],**{k:r[k] for k in ['Precursor.Id','Modified.Sequence','Precursor.Charge','Protein.Group','Protein.Ids']},'PTM.Site.Confidence':'invalid'}
    path=tmp_path/'bad.tsv';pd.DataFrame([record,{**record,'PTM.Site.Confidence':float('inf'),'Precursor.Charge':2.5}]).to_csv(path,sep='\t',index=False)
    obs,_=observations(path,'2.7.0',pr,design)
    assert obs.restriction_reasons.str.contains('invalid_run_confidence').all()
    assert 'invalid_charge' in obs.iloc[1].restriction_reasons
    assert json.loads(obs.iloc[0].source_fields_json)['PTM.Site.Confidence']=='invalid'
    first=resolve_plan(config['experimental_context'],{'DIANN':'same'})
    config['experimental_context']['science']['diann_version']='2.7.0'
    assert first['fingerprints']['quant']!=resolve_plan(config['experimental_context'],{'DIANN':'same'})['fingerprints']['quant']


def test_specificity_stage_reaches_package_and_replay_as_exploratory(config,tmp_path):
    from ptm_shared.annotation_registry import digest
    directory=tmp_path/'specificity';directory.mkdir()
    alphabet='ACDEFGHIKLMNPQRSTVWY'
    matrix={'SYNTHETIC_KINASE':{'kinase_taxon':'9606','weights':{
        '-1':dict.fromkeys(alphabet,0),'0':{'S':2.,'T':1.},'1':dict.fromkeys(alphabet,0)}}}
    (directory/'matrix.json').write_text(json.dumps(matrix));(directory/'background.json').write_text(json.dumps({'SYNTHETIC_KINASE':[0,1,2,3]}))
    meta={'resource_id':'synthetic_not_atlas','resource_version':'test.v1','publication_doi':None,'source_url':'synthetic',
        'license_identifier':'test_fixture','redistribution_status':'permitted','assay_taxon':'9606',
        'supported_center_residues':['S','T'],'window_offsets':[-1,0,1],'alphabet':alphabet,
        'matrix_scale':'log2_additive','pseudocount_policy':'none','terminal_policy':'reject','priming_modification_policy':'reject',
        'matrix_sha256':digest(directory/'matrix.json'),'background_sha256':digest(directory/'background.json'),
        'matrix_file':'matrix.json','background_file':'background.json'}
    resource=directory/'resource.json';resource.write_text(json.dumps(meta));config['specificity_manifest_path']=str(resource)
    result=run(1,config,tmp_path/'out');root=tmp_path/'out/enrichment_free_runs'/result['run_id']
    edges=pd.read_csv(root/'kinase/kinase_candidate_edges.csv');specific=edges.loc[edges.edge_type.eq('experimental_specificity_prediction')]
    assert len(specific)>0 and specific.kinase_taxon.eq(9606).all()
    profiles=pd.read_csv(root/'kinase/kinase_temporal_profiles.csv');track=profiles.loc[profiles.track.eq('specificity_A')&profiles.candidate_id.isin(specific.candidate_id)]
    assert track.activity_magnitude.notna().any() and track.priority_tier.eq('exploratory').all()
    assert {p['track'] for p in result['primary_profiles']} >= {'specificity_A'}
    replay_package(root,tmp_path/'replay')
