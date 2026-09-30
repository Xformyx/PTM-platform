import copy
import json
import numpy as np
import pandas as pd
import pytest

from ptm_shared.study_design import resolve_study_design, require_resolved, DesignError
from ptm_shared.contrast_quantification import quantify_contrasts, ContrastEstimator
from test_report_compatible_quantification import fixture


def generic_fixture(arms=('AB','CuAB'), times=(60,)):
    pr,pg,fasta,_=fixture()
    columns=['b1','b2','b3']+[f'{arm}_{t}_{r}' for arm in arms for t in times for r in range(1,4)]
    source=pr.iloc[0].to_dict()
    base={k:v for k,v in source.items() if k not in ['b1','b2','b3','t1','t2','t3']}
    pr=pd.DataFrame([{**base,**{c:(10 if c.startswith('b') else 20 if c.startswith('AB_') else 80) for c in columns}}])
    pg=pd.DataFrame([{'Protein.Group':'ISO','Genes':'GENE',**{c:2. for c in columns}}])
    rows=[{'sample_id':c,'condition':'0min' if c.startswith('b') else f"{c.split('_')[0]} {c.split('_')[1]}min",
           'group':'Control' if c.startswith('b') else 'Treatment','replicate':i%3+1} for i,c in enumerate(columns)]
    context={'treatment':'compound study','replication_declaration':'technical_per_condition','pairing_policy':'unpaired',
             'quantitation_export_mode':'enrichment_free_timecourse.v3','normalization_policy':'already_normalized.v1',
             'enrichment_status':'enrichment_free','annotation_mode':'quantification_only'}
    design=resolve_study_design(context,rows,taxonomy_id=9606,species='human')
    require_resolved(design)
    return pr,pg,fasta,design,context,rows


def test_import21_rep_unknown_units_conflicts_and_order():
    rows=[{'sample_id':f'f{t}_{r}','condition':f'{t}min_{r}','replicate':r,'group':'Control' if t==0 else 'Treatment'}
          for t in [0,1,5,15,30,60,180] for r in [1,2,3]]
    context={'time_points':'0,1,5,15,30,60,180min','replication_declaration':'technical_per_condition'}
    d=resolve_study_design(context,rows);require_resolved(d)
    assert len(d['materials'])==7 and len(d['injections'])==21
    assert sorted(c['time']['minutes'] for c in d['conditions'])==[0,1,5,15,30,60,180]
    unknown=resolve_study_design({'time_points':context['time_points']},rows)
    assert not unknown['materials'] and all(i['material_id'] is None for i in unknown['injections'])
    confirmed=resolve_study_design({**context,'study_design':unknown},rows)
    assert len(confirmed['materials'])==7
    c=next(c for c in d['conditions'] if c['time']['minutes']==5);c['time']={'value':15,'unit':'min'}
    bad=resolve_study_design({**context,'study_design':d},rows)
    assert any(i['code']=='time_conflict' for i in bad['issues'])
    with pytest.raises(DesignError):require_resolved(bad)
    rows=[{'sample_id':str(i),'condition':label,'group':'Control' if i==0 else 'Treatment'} for i,label in enumerate(['0min','0.5h','1d','1510.5min'])]
    d=resolve_study_design({},rows);d2=resolve_study_design({},rows[::-1])
    assert {c['label']:c['time']['minutes'] for c in d['conditions']}=={'0min':0,'0.5h':30,'1d':1440,'1510.5min':1510.5}
    assert sorted(d['injections'],key=lambda r:r['input_column'])==sorted(d2['injections'],key=lambda r:r['input_column'])


def test_multiarm_shared_baseline_masks_and_no_pseudoreplication():
    pr,pg,fasta,d,*_=generic_fixture()
    pg.loc[0,'b3']=np.nan
    a=quantify_contrasts(pr,pg,fasta,d)
    c=a['comparisons'].set_index('target_label')
    assert c.loc['AB 60min','A']==pytest.approx(1)
    assert c.loc['CuAB 60min','A']==pytest.approx(3)
    assert np.allclose(c.A,c.U_joint-c.P_joint)
    assert c.reference_joint_n.eq(2).all()
    assert c.reference_biological_n.eq(1).all() and c.target_biological_n.eq(1).all()
    assert c.biological_p_value.isna().all()
    assert len(a['runlevel'])==9  # shared baseline exists once, not once per contrast
    assert len(a['protein_contrasts'])==2


def test_nonzero_same_time_reference_and_unit_weighting():
    *_,d,ctx,rows=generic_fixture(arms=('AB',))
    for c in d['conditions']:c['time']={'value':60,'unit':'min','minutes':60,'original':'60min'}
    require_resolved(d)
    # Two units per condition: one with two injections, the other with one.
    for c in d['conditions']:
        samples=sorted([i for i in d['injections'] if i['condition_id']==c['condition_id']],key=lambda i:i['input_column'])
        old=samples[0]['material_id'];new=old+'_second'
        d['materials'].append({'material_id':new,'biological_unit_id':new,'pair_id':None})
        samples[-1]['material_id']=new
    est=ContrastEstimator(d)
    values=np.array([[0 if s['input_column'].startswith('b') else 10 if s['input_column'].endswith('_3') else 0 for s in est.samples]])
    result=est.contrast(values,d['contrasts'][0])
    assert result['value'][0]==5 # (mean(0,0) + 10)/2, not 10/3
    assert result['target_biological_n'][0]==2


def test_arm_emergence_and_zero_eligible_preserve_schema():
    pr,pg,fasta,d,*_=generic_fixture(times=(60,180))
    pr[['b1','b2','b3']]=np.nan
    pr[[c for c in pr if c.startswith('CuAB_60')]]=np.nan
    a=quantify_contrasts(pr,pg,fasta,d)
    assert a['comparisons'].A.isna().all()
    detection=a['detection'].set_index('target_label')
    assert detection.loc['AB 180min','post_reference_time_min']==60
    assert detection.loc['CuAB 180min','post_reference_time_min']==180
    assert not detection.baseline_FC_created.any()
    assert a['strict_parent_paired'].empty and 'form_id' in a['strict_parent_paired']
    empty=quantify_contrasts(pr.iloc[:0],pg,fasta,d)
    assert empty['comparisons'].empty and 'contrast_id' in empty['comparisons']


def test_context_unicode_and_legacy_insulin_not_reassigned():
    *_,ctx,rows=generic_fixture()
    ctx.update(cell_type='세포 α',treatment='EGF',biological_question='AKT인가?',special_conditions='12시간',time_points='0,60min',
               acquisition_metadata={'insulin_concentration':'100 nM','injection_amount':'10 µL'},api_token='DO_NOT_EXPORT')
    d=resolve_study_design(ctx,rows)
    assert d['study']['original_context']['cell_type']=='세포 α'
    assert any(i['code']=='legacy_insulin_dose_conflict' for i in d['issues'])
    assert 'DO_NOT_EXPORT' not in json.dumps(d)
    assert d['study']['acquisition']['injection_description']['value']=='10 µL'
    assert all(t.get('dose') is None for a in d['arms'] for t in a.get('treatments',[]))


def test_llm_token_settings_remain_in_the_serialized_research_record():
    from ptm_shared.generic_workflow import json_bytes
    saved = json.loads(json_bytes({'report_options': {'report_config': {'llm_tokens': {'abstract': 1024}}}, 'private_token': 'DO_NOT_EXPORT'}))
    assert saved['report_options']['report_config']['llm_tokens']['abstract'] == 1024
    assert 'private_token' not in saved


def write_inputs(tmp_path,pr,pg,fasta):
    root=tmp_path/'raw';root.mkdir()
    pr.to_csv(root/'PR.tsv',sep='\t',index=False);pg.to_csv(root/'PG.tsv',sep='\t',index=False)
    (root/'reference.fasta').write_text(''.join(f">{'sp' if row['reviewed'] else 'tr'}|{accession}|{accession} GN={row['gene']} OX=9606\n{row['sequence']}\n" for accession,row in fasta.items()))
    return {'pr_matrix_path':str(root/'PR.tsv'),'pg_matrix_path':str(root/'PG.tsv'),'fasta_path':str(root/'reference.fasta')}


def test_bundle_replay_context_and_failure_publication(tmp_path,monkeypatch):
    from ptm_shared.generic_workflow import run_generic_analysis,replay_bundle
    from ptm_shared.enrichment_free_workflow import recorded_run
    pr,pg,fasta,d,ctx,rows=generic_fixture()
    ctx.update(study_design=d,biological_question='ERK인가? <script>alert(1)</script>')
    config={**write_inputs(tmp_path,pr,pg,fasta),'experimental_context':ctx,'order_code':'GENERIC_FIXTURE','run_generation':1}
    out=tmp_path/'results';result=run_generic_analysis(1,config,out)
    directory=out/'enrichment_free_runs'/result['run_id']
    assert result['analysis_readiness']['kinase']['status']=='not_run'
    assert result['counts']['primary_comparisons']==2
    replay=replay_bundle(directory,tmp_path/'replay')
    assert all(r['numeric_missing_text_keys_equal'] for r in replay)
    import ptm_shared.generic_workflow as workflow
    monkeypatch.setattr(workflow,'validate_tables',lambda *args:(_ for _ in ()).throw(OSError('interrupted write')))
    with pytest.raises(OSError):run_generic_analysis(1,config,out)
    assert recorded_run(out)['run_id']==result['run_id']


def test_species_registry_edges_localization_and_question_invariance(tmp_path):
    from ptm_shared.annotation_registry import digest,require_compatible,public_registry,RegistryError
    from ptm_shared.generic_kinase import map_edges,score_contrasts
    pr,pg,fasta,d,ctx,_=generic_fixture()
    annotation=pd.DataFrame([{'enzyme':'AKT1','substrate':'CAN','residue_type':'S','residue_offset':2,
                             'modification':'phosphorylation','sources':'PhosphoSite','references':'PhosphoSite:123'}])
    source=tmp_path/'snapshot.tsv';annotation.to_csv(source,sep='\t',index=False);sha=digest(source)
    root=tmp_path/'registry';reg=root/sha;reg.mkdir(parents=True);(reg/'snapshot.tsv').write_bytes(source.read_bytes())
    metadata={'database_sha256':sha,'taxonomy_ids':['9606'],'ptm_types':['phosphorylation'],'id_system':'UniProt',
              'orthology_translation':False,'database':'synthetic fixture','version':'fixture.v1'}
    (reg/'annotation_metadata.json').write_text(json.dumps(metadata))
    registered=require_compatible(root,sha,9606,'phosphorylation')
    with pytest.raises(RegistryError):require_compatible(root,sha,10090,'phosphorylation')
    a=quantify_contrasts(pr,pg,fasta,d)
    _,edges=map_edges(a,annotation,registered,ctx,{'CAN':'9606','ISO':'9606'})
    score=score_contrasts(a,edges,ctx,registered)
    assert set(score['kinase_profiles'].entity)=={'AKT1','AKT_family'}
    assert not edges.strict_eligible.any()
    ctx['biological_question']='expect a completely different pathway'
    changed=score_contrasts(a,edges,ctx,registered)
    pd.testing.assert_frame_equal(score['kinase_profiles'],changed['kinase_profiles'])
    pd.testing.assert_frame_equal(score['kinase_membership'],changed['kinase_membership'])
    ctx['localization_evidence']=[{'protein_group':'ISO','modified_sequence':'AS(UniMod:21)K','accession':'CAN',
        'residue_type':'S','residue_offset':2,'probability':.99,'source':'synthetic localization fixture'}]
    _,localized=map_edges(a,annotation,registered,ctx,{'CAN':'9606','ISO':'9606'})
    assert localized.strict_eligible.all()
    (reg/'snapshot.tsv').write_text('corrupt')
    assert public_registry(root)['snapshots'][0]['status']=='checksum_invalid'


def test_multiple_accessions_one_group_and_paired_parent_masks():
    pr,pg,fasta,d,*_=generic_fixture(arms=('AB',))
    pr['Protein.Group']='ISO;CAN';pg['Protein.Group']='ISO;CAN'
    # Strict peptides are never the backbone of a modified sequence.
    extras=[]
    for seq in ['PEP','AAA']:
        row=pr.iloc[0].to_dict();row.update({'Precursor.Id':seq,'Stripped.Sequence':seq,'Modified.Sequence':seq})
        row.update({c:4. if c.startswith('AB') else 2. for c in [i['input_column'] for i in d['injections']]})
        extras.append(row)
    extras[0]['b3']=np.nan
    pr=pd.concat([pr,pd.DataFrame(extras)],ignore_index=True)
    a=quantify_contrasts(pr,pg,fasta,d)
    assert a['summary'].primary_adjustment_eligible.all()
    paired=a['strict_parent_paired'].iloc[0]
    assert paired.strict_parent_A==pytest.approx(0.) and paired.peptide_n==2
    audit=a['strict_parent_peptide_masks'].set_index('sequence')
    assert audit.loc['PEP','reference_joint_n']==2
    assert len(audit.loc['PEP','reference_run_ids'].split(';'))==2
    assert not audit.loc['PEP','complete_mask_included']
    assert a['strict_parent_complete'].iloc[0].status=='insufficient_sequences'


def test_whole_study_normalization_and_full_protein_panel(tmp_path):
    from ptm_shared.generic_workflow import calculate
    pr,pg,fasta,d,ctx,_=generic_fixture()
    config=write_inputs(tmp_path,pr,pg,fasta)
    inputs={name:config[key] for name,key in [('PR','pr_matrix_path'),('PG','pg_matrix_path'),('FASTA','fasta_path')]}
    ctx['normalization_policy']='legacy_median.v1'
    d['validation_panel']={'genes':['GENE'],'selection_timing':'retrospective_exploratory'}
    d['temporal_windows']={'chosen_window':{'minimum_minutes':50,'maximum_minutes':90}}
    tables,norm,ready=calculate(inputs,d,ctx)
    assert norm['scope']=='whole_study' and norm['applications']==1
    assert norm['factors']['PR']['b1']==2
    assert norm['factors']['PR']['AB_60_1']==1
    assert norm['factors']['PR']['CuAB_60_1']==.25
    assert np.allclose(tables['comparisons'].A,0)
    assert len(tables['protein_contrasts'])==2
    assert tables['validation_panel'].declared_windows.eq('chosen_window').all()
    assert 'GENE' in set(tables['validation_panel'].gene)
    assert ready['temporal']['arm_contexts']


@pytest.mark.parametrize('ptm_type,modified',[('acetylation','(UniMod:1)ASK'),('ubiquitylation','ASK(UniMod:121)')])
def test_other_ptms_quantification_only_and_annotation_boundary(ptm_type,modified):
    from ptm_shared.study_execution import validate_execution
    pr,pg,fasta,d,ctx,_=generic_fixture()
    pr['Modified.Sequence']=modified;d['study']['ptm_type']=ptm_type;ctx['study_design']=d
    assert validate_execution(ctx,ptm_type,9606) is None
    a=quantify_contrasts(pr,pg,fasta,d,ptm_type)
    assert len(a['comparisons'])==2 and a['comparisons'].included.all()
    ctx['annotation_mode']='required'
    with pytest.raises(ValueError,match='phosphorylation only'):validate_execution(ctx,ptm_type,9606)


def test_declared_pair_mask_identity_and_pair_ids_required():
    pr,pg,fasta,d,ctx,rows=generic_fixture(arms=('AB',))
    for material in d['materials']:material['pair_id']='declared_donor_pair'
    d['contrasts'][0]['pairing']='paired'
    require_resolved(d)
    pg.loc[0,'b3']=np.nan
    a=quantify_contrasts(pr,pg,fasta,d)
    row=a['comparisons'].iloc[0]
    assert row.A==pytest.approx(row.U_joint-row.P_joint)
    assert row.statistical_unit=='declared_pair'
    d['materials'][0]['pair_id']=None
    with pytest.raises(DesignError,match='pair_mapping_required'):require_resolved(d)


def test_treatment_dose_conflict_persists_until_confirmation():
    *_,d,ctx,rows=generic_fixture(arms=('AB',))
    d['study']['original_context']['treatment']='insulin'
    d['arms'][-1]['treatments']=[{'name':'insulin','dose':100,'unit':'nM'}]
    ctx.update(treatment='EGF',study_design=d)
    for _ in range(2):
        ctx['study_design']=resolve_study_design(ctx,rows)
        assert any(i['code']=='treatment_context_conflict' for i in ctx['study_design']['issues'])
    ctx['treatment_conflict_resolution']='reviewed_structured_arms'
    assert not any(i['code']=='treatment_context_conflict' for i in resolve_study_design(ctx,rows)['issues'])


def test_atomic_registry_recovery_and_immutable_retry(tmp_path):
    import subprocess,sys,os
    from pathlib import Path
    from ptm_shared.annotation_registry import digest,inspect_snapshot
    source=tmp_path/'audit';source.mkdir();snapshot=source/'snapshot.tsv'
    pd.DataFrame(columns=['enzyme','substrate','residue_type','residue_offset','modification','sources','references']).to_csv(snapshot,sep='\t',index=False)
    sha=digest(snapshot);metadata={'database_sha256':sha,'taxonomy_ids':['10090'],'ptm_types':['phosphorylation'],'id_system':'UniProt','database':'empty synthetic','version':'fixture'}
    (source/'annotation_metadata.json').write_text(json.dumps(metadata))
    root=tmp_path/'reference';target=root/'frozen_annotations'/sha;target.mkdir(parents=True)
    (target/'snapshot.tsv').write_text('interrupted registration')
    repo=Path(__file__).resolve().parents[2]
    cmd=[sys.executable,'scripts/register_frozen_annotation.py','--snapshot',str(snapshot),'--audit-dir',str(source),'--sha256',sha,'--reference-root',str(root)]
    env={**os.environ,'PYTHONPATH':str(repo)}
    failed=subprocess.run(cmd,cwd=repo,env=env,capture_output=True)
    assert failed.returncode!=0
    subprocess.run(cmd+['--recover-incomplete'],cwd=repo,env=env,check=True,capture_output=True)
    assert inspect_snapshot(root/'frozen_annotations',sha,10090,'phosphorylation')['status']=='ready'
    before=(target/'annotation_metadata.json').read_bytes()
    subprocess.run(cmd,cwd=repo,env=env,check=True,capture_output=True)
    assert (target/'annotation_metadata.json').read_bytes()==before
    assert len(list((root/'frozen_annotations').glob('.incomplete-*')))==1


def test_mouse_zero_annotation_has_schema_and_no_insulin_defaults(tmp_path):
    from ptm_shared.generic_workflow import calculate,build_report
    pr,pg,fasta,d,ctx,_=generic_fixture();d['study'].update(taxonomy_id='10090',species='mouse',treatment='hypoxia')
    cfg=write_inputs(tmp_path,pr,pg,fasta)
    snapshot=tmp_path/'empty.tsv';pd.DataFrame(columns=['enzyme','substrate','residue_type','residue_offset','modification','sources','references']).to_csv(snapshot,sep='\t',index=False)
    inputs={name:cfg[key] for name,key in [('PR','pr_matrix_path'),('PG','pg_matrix_path'),('FASTA','fasta_path')]};inputs['snapshot']=snapshot
    registration={'sha256':'synthetic','metadata':{'taxonomy_ids':['10090'],'orthology_translation':False}}
    tables,norm,ready=calculate(inputs,d,ctx,registration)
    assert tables['kinase_profiles'].empty and 'contrast_id' in tables['kinase_profiles']
    assert ready['kinase']['status']=='no_observed_curated_edges'
    assert tables['validation_panel'].empty and len(tables['protein_contrasts'])==2
    report=build_report(d,{'order_code':'fixture','run_id':'fixture','provenance_id':'fixture'},tables,ready)
    assert 'AKT_family' not in report and 'HIRc' not in report and 'FOSL1' not in report
