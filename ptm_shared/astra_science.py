"""Experimental v5 adapter around the existing immutable Astra package engine."""
import copy
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from .annotation_registry import digest
from .astra_inputs import stable_id
from .astra_plan import effective_context
from .study_design import require_resolved
from .science_reference import preflight, inventory
from .diann_evidence import observations, apply_observation_policy
from .kinase_specificity import score_sites
from .science_inference import identifiability, unit_intervals

PROFILE='astra_analysis.v5'
VERSION='astra_analysis_package.v5.experimental'
CODE_FILES=['astra_science.py','science_reference.py','species_registry.py','diann_evidence.py','kinase_specificity.py','science_inference.py','perturbation_validation.py','kinase_family_registry.json','study_design.v4.schema.json']
INPUT_FIELDS={'DIANN':'diann_report_path','DIANN_SITE':'diann_site_report_path','CROSSWALK':'run_crosswalk_path',
              'SEARCH_FASTA':'search_fasta_path','TRANSGENE':'transgene_manifest_path','TAXONOMY':'taxonomy_mapping_path',
              'SPECIFICITY':'specificity_manifest_path','VALIDATION':'perturbation_manifest_path'}
KEYS={'reference_inventory':['accession'],'measurement_observations':['observation_id'],'site_identity_audit':['identity_id'],
      'observation_sites':['observation_site_id'],'specificity_scores':['specificity_id'],
      'kinase_calls':['call_id'],'group_excluded_anchors':['anchor_id'],'replicate_uncertainty':['uncertainty_id'],
      'perturbation_validation':['validation_id']}


def validate_execution(context,ptm_type,taxonomy_id,options=None,pr_columns=None,pg_columns=None):
    # v5 is the current Astra execution path. Scientific readiness is reported
    # per evidence layer; an obsolete UI opt-in is not an execution prerequisite.
    design=require_resolved(context.get('study_design') or {},pr_columns,pg_columns)
    if taxonomy_id is None or str(taxonomy_id)!=str(design['study'].get('taxonomy_id')):raise ValueError('species_contract_conflict')
    from .contrast_quantification import PTM_CODES
    if ptm_type not in {*PTM_CODES,'proteomics'} or design['study']['ptm_type']!=ptm_type:raise ValueError('analysis_target_conflict')
    if effective_context(context)['normalization_policy'] not in {'already_normalized.v1','legacy_median.v1'}:raise ValueError('unsupported_normalization')


def resolve_plan(context,hashes=None,source_pin=None,taxa=None):
    from .astra_plan import resolve_plan as base_plan
    quant_hashes={k:v for k,v in (hashes or {}).items() if k in {'PR','PG','FASTA','DIANN','CROSSWALK','SEARCH_FASTA','TAXONOMY'}}
    plan=base_plan(context,quant_hashes,source_pin,taxa);science=context.get('science',{})
    code={name:digest(Path(__file__).with_name(name)) for name in CODE_FILES}
    quant=stable_id('quant_v5',[plan['fingerprints']['quant'],science.get('diann_version'),science.get('observation_policy'),science.get('reference'),{k:code[k] for k in ('science_reference.py','diann_evidence.py','astra_science.py')}])
    discovery=stable_id('discovery_v5',[quant,source_pin,hashes,code])
    plan.update(profile=PROFILE,schema_version='astra_science_plan.v1',experimental=True,
        capabilities={'target':context['study_design']['study'].get('analysis_target'),'axis':context['study_design']['study'].get('design_axis')},
        scientific_readiness={'software':'experimental','resource_parity':'not_verified','performance':'not_demonstrated','independent_experiment':'pending_data'},
        fingerprints={'quant':quant,'discovery':discovery,'temporal':stable_id('temporal_v5',[discovery,science.get('selective_policy'),science.get('uncertainty'),plan['fingerprints']['temporal']])})
    plan['code_dependencies']['science']=code
    return plan


def _reference(inputs,context):
    study=context['study_design']['study']
    config={'species':study['species'],'species_tax_id':study['taxonomy_id'],'fasta_path':str(inputs['FASTA']),
            'pg_matrix_path':str(inputs.get('PG','')),'pr_matrix_path':str(inputs.get('PR','')),
            **{field:str(inputs[k]) for k,field in INPUT_FIELDS.items() if k in inputs}}
    return preflight(config,context)


def normalized_reference(inputs,context):
    reference=_reference(inputs,context)
    # Parser adapter: accession identity and explicit registered OX/GN, no guessing.
    target=Path(inputs['FASTA']).with_name('analysis_reference.fasta')
    lines=[]
    for e in reference['entries']:
        if e['entry_kind']!='biological':continue
        suffix=(' OX='+e['taxon'] if e['taxon'] else '')+(' GN='+e['gene'] if e['gene'] else '')
        lines.extend([('>sp|' if e['reviewed'] else '>tr|')+e['accession']+'|registered'+suffix,e['sequence']])
    data=('\n'.join(lines)+'\n').encode()
    if target.exists() and target.read_bytes()!=data:raise ValueError('derived_reference_changed')
    if not target.exists():target.write_bytes(data)
    return target,reference


def calculate(inputs,design,context,registration=None):
    from .generic_workflow import calculate as generic_calculate
    columns=[i['input_column'] for i in design['injections']]
    pr=pd.read_csv(inputs['PR'],sep='\t') if 'PR' in inputs else pd.DataFrame(columns=['Protein.Group','Protein.Ids','Genes','Stripped.Sequence','Modified.Sequence','Precursor.Id','Precursor.Charge','Proteotypic']+columns)
    pr[columns]=pr[columns].astype(float)
    pg=pd.read_csv(inputs['PG'],sep='\t');science=context.get('science',{})
    obs,_=observations(inputs.get('DIANN'),science.get('diann_version'),pr,design,inputs.get('CROSSWALK'))
    pr=apply_observation_policy(pr,obs,design,science.get('observation_policy',{}))
    fasta,reference=normalized_reference(inputs,context)
    excluded={e['accession'] for e in reference['entries'] if e['entry_kind']!='biological'}
    for frame in (pr,pg):
        # Exclude groups containing designated decoy/contaminant/spike-in entries.
        frame.drop(frame.index[frame['Protein.Group'].fillna('').map(lambda g:bool(set(str(g).split(';'))&excluded))],inplace=True)
    return generic_calculate({**inputs,'FASTA':fasta},design,context,None,raw_pr=pr,raw_pg=pg)


def discover(tables,design,fasta_path,context,sources):
    from .astra_discovery import discover as base_discover
    # Original reference inventory was checked before source queries by the orchestrator.
    ctx={**context,'_science_reference':context['_runtime_reference']}
    mapped,edges,motif=base_discover(tables,design,fasta_path,ctx,sources)
    canonical=context.get('_canonical_evidence')
    if canonical is None:
        ids=site_identity(tables['summary'],context['_runtime_reference'])
        scores,resource=score_sites(ids,context['_runtime_reference']['entries'],context.get('_runtime_inputs',{}).get('SPECIFICITY'))
    else:
        ids=canonical['site_identity_audit'];scores=canonical['specificity_scores'];resource=canonical['resource']
    extra=[];forms=tables['summary'].set_index('form_id');identity=ids.set_index(['form_id','site_id'])
    for score in scores.loc[scores.status.eq('scored')].to_dict('records'):
        site=identity.loc[(score['form_id'],score['site_id'])];form=forms.loc[score['form_id']]
        row={column:None for column in edges.columns}
        row.update(edge_id=stable_id('edge',[score['specificity_id']]),candidate_id=score['candidate_id'],candidate_gene=score['kinase_accession'],
            candidate_accession=score['kinase_accession'],candidate_resolution='gene_or_accession',form_id=score['form_id'],site_id=score['site_id'],
            measurement_group_id=score['measurement_group_id'],substrate_gene=str(form.representative_gene),input_fasta_gene=str(form.representative_gene),
            substrate_gene_source='FASTA_or_registered_mapping',protein_group=form['Protein.Group'],input_accession=site.input_accession,
            input_position=site.input_position,representative_accession=form.representative_accession,representative_position=form.representative_sites,
            substrate_taxon=score['substrate_taxon'],kinase_taxon=score['kinase_taxon'],source_taxon=score['reference_assay_taxon'],
            reference_assay_taxon=score['reference_assay_taxon'],host_taxon=context['_runtime_reference']['host_taxon'],sequence_window=score['sequence_window'],
            edge_type='experimental_specificity_prediction',directness='sequence_specificity_not_current_cell_relation',provider='local_specificity_resource',
            original_resource=score['resource_id'],evidence_record_ids=score['specificity_id'],PMIDs='',DOIs=resource.get('publication_doi',''),reference_ids=score['resource_id'],
            orthology_method='not_curated_orthology_prediction',site_mapping_status=site.mapping_status,localization_status='unknown',
            primary_quant_eligibility=bool(form.primary_adjustment_eligible),source_query_id=stable_id('resource',[score['matrix_sha256'],score['background_sha256']]),
            ambiguity_group=score['measurement_group_id'],duplicate_evidence_group=score['specificity_id'],
            restriction_reasons='official_parity_not_verified;uncalibrated_policy;unresolved_localization',
            footprint_eligible=bool(site.site_attribution_eligible and form.primary_adjustment_eligible),enzyme_taxonomy_source='specificity_manifest',source_caution='')
        extra.append(row)
    if extra:edges=pd.concat([edges,pd.DataFrame(extra,columns=edges.columns)],ignore_index=True)
    return mapped,edges,motif


def integrate_temporal(tables,discovery,design,context,source_context=None,impacts=None):
    from .astra_temporal import integrate_temporal as base_temporal
    if design['study'].get('design_axis')!='cross_sectional':return base_temporal(tables,discovery,design,context,source_context,impacts)
    # Empty schema uses the same constructor with no temporal comparisons. No fake time.
    empty=copy.deepcopy(design);empty['contrasts']=[]
    result=base_temporal(tables,discovery,empty,context,source_context,impacts)
    conditions={c['condition_id']:c for c in design['conditions']};groups={}
    for contrast in design['contrasts']:
        arm=conditions[contrast['target_condition_id']]['arm_id'];ref=contrast['reference_condition_id'];pair=contrast.get('pairing')
        sid=stable_id('series',[arm,ref,pair])
        groups.setdefault(sid,{'series_id':sid,'arm_id':arm,'reference_condition_id':ref,'contrast_ids':[],
            'reference_strategy':'cross_sectional_contrast_set_no_time_order','pairing':pair,'paired_biological_units':pair=='paired'})['contrast_ids'].append(contrast['contrast_id'])
    result['temporal_series']=pd.DataFrame([{**r,'contrast_ids':';'.join(r['contrast_ids'])} for r in groups.values()],columns=result['temporal_series'].columns)
    return result


def augment(scientific,inputs,design,context,readiness):
    from .contrast_quantification import ContrastEstimator
    from .perturbation_validation import import_validation
    reference=_reference(inputs,context);entries={r['accession']:r for r in reference['entries']}
    summary=scientific['quant/summary'];pr=pd.read_csv(inputs['PR'],sep='\t') if 'PR' in inputs else pd.DataFrame()
    obs,obs_status=observations(inputs.get('DIANN'),context.get('science',{}).get('diann_version'),pr,design,inputs.get('CROSSWALK'))
    if len(obs):obs.loc[~obs.form_id.isin(summary.form_id),'form_id']=None
    ids=site_identity(summary,reference)
    children=[]
    by_form={fid:g.to_dict('records') for fid,g in ids.groupby('form_id')}
    for o in obs.to_dict('records'):
        for s in by_form.get(o['form_id'],[]):
            children.append({'observation_site_id':stable_id('observation_site',[o['observation_id'],s['site_id']]),
                'observation_id':o['observation_id'],'identity_id':s['identity_id'],'form_id':s['form_id'],'site_id':s['site_id'],
                'individual_site_posterior':None,'status':'sequence_mapping_only_min_confidence_not_site_posterior'})
    spec,resource=score_sites(ids,reference['entries'],inputs.get('SPECIFICITY'))
    if inputs.get('SPECIFICITY_RESTRICTED'):
        requested=json.loads(Path(inputs['SPECIFICITY_RESTRICTED']).read_text())
        resource={'status':'license_unresolved' if requested.get('redistribution_status') in {None,'unknown','unresolved'} else 'redistribution_not_permitted',
            'scoring_status':'not_run_resource_not_packaged','matrix_sha256':requested.get('matrix_sha256'),
            'background_sha256':requested.get('background_sha256'),'official_parity_status':'official_parity_not_verified',
            'local_adapter_available':'kinase_specificity.score_sites; local execution is separate from portable package permission'}
    discovery={k.split('/')[-1]:v for k,v in scientific.items() if k.startswith('kinase/')}
    temporal={k.split('/')[-1]:v for k,v in scientific.items() if k.startswith('temporal/')}
    decisions=identifiability(discovery,temporal,design)
    run=scientific['quant/runlevel'];est=ContrastEstimator(design)
    arrays={k:run.pivot(index='form_id',columns='injection_id',values=column).reindex(index=summary.form_id,columns=[s['injection_id'] for s in est.samples]).to_numpy(float) for k,column in [('U','ptm_log2'),('P','parent_log2'),('A','adjusted_log2_ratio')]}
    uncertainty=unit_intervals({'arrays':arrays,'summary':summary,'estimator':est},design,context.get('science',{}).get('uncertainty'))
    validation,validation_status=import_validation(inputs.get('VALIDATION'))
    scientific.update({'science/reference_inventory':pd.DataFrame([{k:v for k,v in e.items() if k not in {'sequence','header','mapping_candidates'}} for e in reference['entries']]),
        'science/measurement_observations':obs,'science/site_identity_audit':ids,
        'science/observation_sites':pd.DataFrame(children,columns=['observation_site_id','observation_id','identity_id','form_id','site_id','individual_site_posterior','status']),
        'science/specificity_scores':spec,'science/replicate_uncertainty':uncertainty,'science/perturbation_validation':validation,
        **{'science/'+k:v for k,v in decisions.items()}})
    for name,table in scientific.items():
        if name.startswith('science/') and 'schema_version' not in table:table['schema_version']=VERSION
    readiness.update(schema_version=VERSION,experimental=True,completion_status='completed_with_limitations',
        measurement_evidence=obs_status,reference={k:v for k,v in reference.items() if k not in {'entries','reference_path'}},
        supporting_inputs={'diann_site_report':'raw_provenance_only_parser_not_implemented' if 'DIANN_SITE' in inputs else 'not_provided','transgene_manifest':'raw_provenance_only_construct_validation_pending' if 'TRANSGENE' in inputs else 'not_provided'},
        specificity=resource,selective_calls={'status':'uncalibrated_policy','confirmed_calls':0},independent_validation=validation_status,
        scientific_improvement='not_demonstrated_independent_benchmark_pending')
    if design['study'].get('design_axis')=='cross_sectional':readiness['temporal']={'status':'not_applicable','reason':'cross_sectional_design'}
    if design['study'].get('analysis_target')=='proteomics':
        for key in ('parent_adjustment','kinase','strict_attribution','measurement_evidence'):readiness[key]={'status':'not_applicable','reason':'protein_only_analysis'}
        readiness['quantification']={'status':'protein_abundance_available'}
    return scientific


def run(order_id,config,output_dir,checkpoint=lambda:None,progress=lambda message:None):
    from . import astra_package
    from . import astra_science
    context=config['experimental_context']
    if not config.get('fasta_path'):
        from .science_reference import bind_registered_reference
        fasta,context,mapping=bind_registered_reference(config['reference_root'],context)
        config={**config,'fasta_path':fasta,'experimental_context':context,
                'taxonomy_mapping_path':config.get('taxonomy_mapping_path') or mapping}
    validate_execution(context,context['study_design']['study']['ptm_type'],config.get('species_tax_id'))
    reference=preflight(config,context)  # must precede any directory publication or external request
    config={**config,'fasta_path':reference['reference_path']}
    return astra_package.run_astra_analysis(order_id,config,output_dir,checkpoint,progress,engine=astra_science)


def validate_tables(tables,design):
    forms=set(tables['quant/summary'].form_id);contrasts={c['contrast_id'] for c in design['contrasts']}
    observations=set(tables['science/measurement_observations'].observation_id)
    sites=set(tables['science/site_identity_audit'].site_id);identities=set(tables['science/site_identity_audit'].identity_id)
    anchors=set(tables['science/group_excluded_anchors'].anchor_id)
    candidates=set(tables['kinase/kinase_candidate_edges'].candidate_id)
    for name,df in tables.items():
        if not name.startswith('science/'):continue
        for col,universe in [('form_id',forms),('contrast_id',contrasts),('contrast_or_window_id',contrasts),('observation_id',observations),('site_id',sites),('identity_id',identities),('proposed_entity_id',candidates)]:
            if col in df and not set(df[col].dropna())<=universe:raise ValueError('Science foreign key mismatch:'+name+'/'+col)
    calls=tables['science/kinase_calls']
    if not calls.resolution.eq('no_call').all() or calls.entity_id.notna().any():raise ValueError('Uncalibrated policy emitted a confirmed call')
    children=tables['science/observation_sites']
    if children.individual_site_posterior.notna().any():raise ValueError('Run minimum was promoted to individual site posterior')
    for ids in calls.sensitivity_evidence_ids.dropna():
        if not set(str(ids).split(';'))-{''}<=anchors:raise ValueError('Call anchor foreign key mismatch')


def site_identity(summary,reference):
    entries={r["accession"]:r for r in reference["entries"]}
    identity=[]
    for f in summary.to_dict('records'):
        mappings=json.loads(f['mapping_json']);taxa={entries[r['accession']]['taxon'] for r in mappings}
        for m in mappings:
            e=entries[m['accession']]
            for site in m['sites']:
                sid=stable_id('site_identity',[e['taxon'] or '',m['accession'],e['sequence_sha256'],site[0],int(site[1:]),reference['reference_sha256']])
                identity.append({'identity_id':stable_id('mapping',[f['form_id'],sid]),'form_id':f['form_id'],'site_id':sid,
                    'measurement_group_id':stable_id('measurement',[str(f['Stripped.Sequence'])]),'input_accession':m['accession'],
                    'input_position':int(site[1:]),'substrate_taxon':e['taxon'],'sequence_sha256':e['sequence_sha256'],
                    'reference_sha256':reference['reference_sha256'],'species_ambiguous':len(taxa)>1 or None in taxa,
                    'mapping_status':'unique' if len(mappings)==1 else 'multiple_mappings','residue':site[0],
                    'parent_quant_eligible':f['primary_adjustment_eligible'],'site_attribution_eligible':len(mappings)==1 and f['n_modifications']==1})
                identity[-1]['form_modification_count']=f['n_modifications']
    ids=pd.DataFrame(identity,columns=['identity_id','form_id','site_id','measurement_group_id','input_accession','input_position','substrate_taxon','sequence_sha256','reference_sha256','species_ambiguous','mapping_status','residue','parent_quant_eligible','site_attribution_eligible','form_modification_count'])
    return ids
