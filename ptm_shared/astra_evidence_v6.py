"""v6 evidence integration. v4/v5 archives retain their original engine adapters."""
import copy
import json
from pathlib import Path
import numpy as np
import pandas as pd
from . import astra_science as legacy
from .annotation_registry import digest
from .astra_inputs import stable_id
from .diann_evidence import observations, COLUMNS
from .localization_evidence import read_site_report, observation_sites, by_contrast, VERSION as LOCAL_VERSION
from .kinase_specificity import score_sites, select_membership
from .inference_policy import evaluate
from .astra_card_inputs import project_card_inputs, validate_card_inputs, TABLE_KEYS as CARD_INPUT_KEYS

PROFILE='astra_analysis.v6'
VERSION='astra_analysis_package.v6.experimental'
CODE_FILES=legacy.CODE_FILES+['astra_evidence_v6.py','localization_evidence.py','inference_policy.py','source_acquisition.py','evidence_temporal.py','evidence_methods.py','official_specificity.py','official_method_tracks.py','phosx_activity_adapter.py','evidence_stage_cache.py','astra_card_inputs.py','study_metadata.py']
INPUT_FIELDS={**legacy.INPUT_FIELDS,'CALIBRATION':'calibration_policy_path'}
CODE_FILES += ['evidence_contracts.py','annotation_species.py']
from .astra_reader import build_reader_tables, validate_reader, write_reader, TABLE_KEYS as READER_KEYS
CODE_FILES += ['astra_reader.py','measured_feature_cards.py','reader_observations.py','research_questions.py','reader_authoring.py','quantitative_fields.py','de_novo_representation.py']
KEYS={**legacy.KEYS,'site_report_observations':['site_report_row_id'],
      'localization_by_contrast':['localization_id'],'inference_results':['call_id'],
      'calibrated_calls':['call_id'],'evidence_dependency_groups':['dependency_id'],'calibration_provenance':['policy_id']}
normalized_reference=legacy.normalized_reference
validate_execution=legacy.validate_execution
ADDITIONAL_KEYS={'temporal/interval_contrasts':['interval_id'],'temporal/group_excluded_cowave':['cowave_id'],'kinase/method_scores':['method_result_id'],
                'kinase/method_membership':['method_membership_id'],'kinase/method_executions':['execution_id'],**CARD_INPUT_KEYS,**READER_KEYS}


def integrate_temporal(tables,discovery,design,context,source_context=None,impacts=None):
    from .evidence_temporal import adjacent_contrasts,excluded_cowave
    result=legacy.integrate_temporal(tables,discovery,design,context,source_context,impacts)
    result['interval_contrasts']=adjacent_contrasts(tables,result,design)
    result['group_excluded_cowave']=excluded_cowave(discovery,result,design)
    return result


def resolve_plan(context,hashes=None,source_pin=None,taxa=None):
    from .astra_plan import resolve_plan as base
    hashes=hashes or {};science=context.get('science',{});policy=science.get('observation_policy',{'mode':'audit_only'})
    quant_keys={'PR','PG','FASTA','SEARCH_FASTA','TAXONOMY'}
    if policy.get('mode')=='validated_observations':quant_keys|={'DIANN','CROSSWALK'}
    plan=base(context,{k:v for k,v in hashes.items() if k in quant_keys},None,taxa)
    codes={n:digest(Path(__file__).with_name(n)) for n in CODE_FILES}
    quant=stable_id('quant_v6',[plan['fingerprints']['quant'],policy,science.get('reference'),codes['science_reference.py'],
                              [codes['diann_evidence.py'],science.get('diann_version')] if policy.get('mode')=='validated_observations' else None])
    identity=stable_id('identity_v6',[quant,{k:hashes.get(k) for k in ('DIANN','DIANN_SITE','CROSSWALK')},science.get('diann_version'),science.get('localization_policy'),codes['localization_evidence.py'],codes['diann_evidence.py']])
    discovery=stable_id('discovery_v6',[identity,source_pin,hashes.get('SPECIFICITY',hashes.get('SPECIFICITY_RESTRICTED')),science.get('specificity_membership'),science.get('official_methods'),codes['kinase_specificity.py'],
        {k:codes[k] for k in ('official_specificity.py','official_method_tracks.py','phosx_activity_adapter.py','evidence_methods.py')},plan['code_dependencies']['discovery']])
    temporal=stable_id('temporal_v6',[discovery,plan['fingerprints']['temporal'],context.get('temporal_policy'),codes['evidence_temporal.py']])
    inference=stable_id('inference_v6',[temporal,hashes.get('CALIBRATION'),codes['inference_policy.py']])
    plan.update(profile=PROFILE,schema_version='astra_evidence_plan.v2',experimental=True,
        fingerprints={'quant':quant,'identity_localization':identity,'discovery':discovery,'temporal':temporal,'inference':inference},
        scientific_readiness={'software':'experimental','resource_parity':'see_method_registry','performance':'not_demonstrated','independent_experiment':'pending_data'},
        input_fingerprints=hashes,acquisition_policy=context.get('acquisition_policy',{'mode':'research_full'}))
    plan['code_dependencies']['evidence']=codes
    return plan


def calculate(inputs,design,context,registration=None):
    # Annotation-only evidence never filters or renormalizes supplied intensities.
    if context.get('science',{}).get('observation_policy',{}).get('mode','audit_only')=='audit_only':
        return legacy.calculate({k:v for k,v in inputs.items() if k not in {'DIANN','DIANN_SITE','CROSSWALK'}},design,context,registration)
    return legacy.calculate(inputs,design,context,registration)


def prepare_evidence(tables,inputs,design,context):
    from .study_design import stable_id as form_key
    pr=pd.read_csv(inputs['PR'],sep='\t') if 'PR' in inputs else pd.DataFrame()
    science=context.get('science',{});reference=context['_runtime_reference']
    try:obs,status=observations(inputs.get('DIANN'),science.get('diann_version'),pr,design,inputs.get('CROSSWALK'),exact_group_sets=True)
    except ValueError as e:
        if science.get('observation_policy',{}).get('mode')=='validated_observations':raise
        obs=pd.DataFrame(columns=COLUMNS);status={'status':'unsupported_schema','reason':str(e),'raw_input_preserved':True}
    if not inputs.get('DIANN'):status={'status':'missing_input','reason':'main_report_not_provided','matrix_quantification_available':True}
    if len(obs):obs.loc[~obs.form_id.isin(tables['summary'].form_id),'form_id']=None
    ids=legacy.site_identity(tables['summary'],reference)
    site_report,site_status=read_site_report(inputs.get('DIANN_SITE'),obs,science.get('diann_version'))
    children=observation_sites(obs,ids,tables['summary'],reference,site_report)
    expected={}
    if len(pr):
        pr=pr.copy();pr['_form_id']=[form_key('form',str(pg)+'|'+str(ms)) for pg,ms in zip(pr['Protein.Group'],pr['Modified.Sequence'])]
        pr=pr.loc[pr._form_id.isin(tables['summary'].form_id)]
        for injection in design['injections']:
            positive=pd.to_numeric(pr[injection['input_column']],errors='coerce').gt(0)
            expected.update({(fid,injection['injection_id']):int(n) for fid,n in pr.loc[positive].groupby('_form_id').size().items()})
    localized=by_contrast(obs,children,ids,tables['comparisons'],science.get('localization_policy'),expected)
    try:scores,resource=score_sites(ids,reference['entries'],inputs.get('_LOCAL_SPECIFICITY',inputs.get('SPECIFICITY')),official=True)
    except (ValueError,KeyError,OSError) as error:
        from .kinase_specificity import COLUMNS as SCORE_COLUMNS
        scores=pd.DataFrame(columns=SCORE_COLUMNS)
        resource={'status':'resource_unavailable','reason':'invalid_or_missing_specificity_resource','error_type':type(error).__name__,
                  'quantification_preserved':True,'official_parity_status':'not_run'}
    if 'SPECIFICITY_RESTRICTED' in inputs:
        resource.update(raw_resource_packaged=False,replay_scope='requires_identical_external_resource',
                        local_scoring_performed='_LOCAL_SPECIFICITY' in inputs)
    if 'membership_selected' in scores:
        selection={'policy_id':'PhosX-0.23.1.binarise_pssm_scores','source':'official_function','parameters':{k:resource.get(k) for k in ('n_top_kinases','min_quantile')}}
    else:scores,selection=select_membership(scores,science.get('specificity_membership'))
    canonical={'measurement_observations':obs,'site_report_observations':site_report,'site_identity_audit':ids,
        'observation_sites':children,'localization_by_contrast':localized,'specificity_scores':scores,
        'measurement_status':status,'site_report_status':site_status,'resource':resource,'selection_policy':selection}
    return {**context,'_canonical_evidence':canonical}


def discover(tables,design,fasta_path,context,sources):
    # Unscoped legacy context probabilities cannot certify a run/contrast in v6.
    mapped,edges,motif=legacy.discover(tables,design,fasta_path,{**context,'localization_evidence':[]},sources)
    canonical=context['_canonical_evidence'];spec=canonical['specificity_scores'].set_index('specificity_id')
    edges=edges.copy();edges['specificity_id']=None;edges['specificity_percentile']=np.nan
    edges['membership_policy_id']=None;edges['membership_selected']=None
    mask=edges.edge_type.eq('experimental_specificity_prediction')
    for index,row in edges.loc[mask].iterrows():
        score=spec.loc[row.evidence_record_ids];selected=bool(score.membership_selected)
        edges.at[index,'specificity_id']=score.name;edges.at[index,'specificity_percentile']=score.percentile
        edges.at[index,'membership_policy_id']=score.selection_policy_id;edges.at[index,'membership_selected']=selected
        edges.at[index,'footprint_eligible']=bool(row.footprint_eligible and selected)
        if not selected:edges.at[index,'restriction_reasons']=str(row.restriction_reasons)+';'+score.selection_reason
        # A proven enzyme taxon/accession identifies the same candidate across
        # curated/specificity tracks. Never infer enzyme taxon from substrate.
        if pd.notna(row.kinase_taxon):edges.at[index,'candidate_id']=stable_id('candidate',[str(row.kinase_taxon),row.candidate_accession])
    edges['localization_status']='contrast_scoped_see_localization_by_contrast'
    edges['localization_probability']=np.nan
    return mapped,edges,motif


def score_candidates(tables,edges,design,context):
    from .astra_discovery import score_candidates as score
    result=score(tables,edges,design,science=True,localization=context['_canonical_evidence']['localization_by_contrast'])
    # Evidence IDs survive the same serialization as the numerical contribution.
    edge_index=edges.set_index('edge_id').to_dict('index')
    localized=context['_canonical_evidence']['localization_by_contrast']
    loc_index={(r.form_id,r.site_id,r.contrast_id):r.localization_id for r in localized.itertuples()}
    loc_state={(r.form_id,r.site_id,r.contrast_id):r for r in localized.itertuples()}
    rows=result['substrate_contributions'];spec_ids=[];loc_ids=[];loc_status=[]
    for r in rows.itertuples():
        items=[edge_index[e] for e in str(r.edge_ids).split(';')]
        spec_ids.append(';'.join(sorted({i['specificity_id'] for i in items if pd.notna(i['specificity_id'])})))
        loc_ids.append(';'.join(sorted({loc_index[(i['form_id'],i['site_id'],r.contrast_id)] for i in items if (i['form_id'],i['site_id'],r.contrast_id) in loc_index})))
        states=[loc_state.get((i['form_id'],i['site_id'],r.contrast_id)) for i in items]
        loc_status.append('unresolved' if not states or not all(s is not None and s.localized_eligible for s in states) else
            'site_localization_supported' if all(s.measurement_status=='site_localization_supported' for s in states) else 'run_confidence_supported')
    rows['specificity_ids']=spec_ids;rows['localization_ids']=loc_ids;rows['measurement_status']=loc_status
    return result


def augment(scientific,inputs,design,context,readiness):
    from .contrast_quantification import ContrastEstimator
    from .science_inference import unit_intervals
    from .perturbation_validation import import_validation
    canonical=context['_canonical_evidence'];reference=context['_runtime_reference']
    tables={k:canonical[k] for k in ('measurement_observations','site_report_observations','site_identity_audit','observation_sites','localization_by_contrast','specificity_scores')}
    discovery={k.split('/')[-1]:v for k,v in scientific.items() if k.startswith('kinase/')}
    temporal={k.split('/')[-1]:v for k,v in scientific.items() if k.startswith('temporal/')}
    from .evidence_methods import zscore_baseline
    scientific['kinase/method_scores']=zscore_baseline({k.split('/')[-1]:v for k,v in scientific.items() if k.startswith('quant/')},discovery,canonical['site_identity_audit'],reference['entries'])
    artifact=json.loads(inputs['CALIBRATION'].read_text()) if 'CALIBRATION' in inputs else None
    resource_hashes=[canonical['resource'][k] for k in ('matrix_sha256','background_sha256') if canonical['resource'].get(k)]
    resource_hashes += [digest(inputs[k]) for k in ('FASTA','TAXONOMY','SEARCH_FASTA') if k in inputs]
    if context.get('_source_pin_sha256'):resource_hashes.append(context['_source_pin_sha256'])
    from .generic_workflow import object_hash
    resource_hashes.append(object_hash({'localization_version':LOCAL_VERSION,'policy':context.get('science',{}).get('localization_policy')}))
    decisions=evaluate(discovery,temporal,design,artifact,resource_hashes)
    run=scientific['quant/runlevel'];summary=scientific['quant/summary'];est=ContrastEstimator(design)
    arrays={k:run.pivot(index='form_id',columns='injection_id',values=c).reindex(index=summary.form_id,columns=[s['injection_id'] for s in est.samples]).to_numpy(float) for k,c in [('U','ptm_log2'),('P','parent_log2'),('A','adjusted_log2_ratio')]}
    uncertainty=unit_intervals({'arrays':arrays,'summary':summary,'estimator':est},design,context.get('science',{}).get('uncertainty'))
    validation,validation_status=import_validation(inputs.get('VALIDATION'))
    tables.update(reference_inventory=pd.DataFrame([{k:v for k,v in e.items() if k not in {'sequence','header','mapping_candidates'}} for e in reference['entries']]),
        replicate_uncertainty=uncertainty,perturbation_validation=validation,**decisions)
    for name,table in tables.items():table['schema_version']=VERSION;scientific['science/'+name]=table
    from .official_method_tracks import execute_tracks
    native,membership,executions=execute_tracks(scientific,inputs,context,canonical['resource'])
    scientific['kinase/method_scores']=pd.concat([scientific['kinase/method_scores'],native],ignore_index=True)
    scientific['kinase/method_membership']=membership
    scientific['kinase/method_executions']=executions
    calls=decisions['kinase_calls'];loc=canonical['localization_by_contrast']
    readiness.update(schema_version=VERSION,experimental=True,completion_status='completed_with_limitations',
        native_method_runtime=context.get('_method_runtime',[]),
        measurement_evidence=canonical['measurement_status'],supporting_inputs={'diann_site_report':canonical['site_report_status']},
        specificity={**canonical['resource'],'membership_policy':canonical['selection_policy']},
        selective_calls={'status':'see_inference_results','confirmed_calls':len(decisions['calibrated_calls']),
                         'inference_status_counts':calls.inference_status.value_counts().to_dict(),'independent_validation':'not_performed'},
        strict_attribution={'status':'contrast_localized_subset_available' if loc.localized_eligible.any() else 'not_evaluable',
                            'eligible_form_site_contrasts':int(loc.localized_eligible.sum()),'gate_version':LOCAL_VERSION},
        reference={k:v for k,v in reference.items() if k not in {'entries','reference_path'}},
        independent_validation=validation_status,scientific_improvement='not_demonstrated_independent_benchmark_pending')
    if design['study'].get('design_axis')=='cross_sectional':readiness['temporal']={'status':'not_applicable','reason':'cross_sectional_design'}
    if design['study'].get('analysis_target')=='proteomics':
        for key in ('parent_adjustment','kinase','strict_attribution','measurement_evidence'):readiness[key]={'status':'not_applicable','reason':'protein_only_analysis'}
    scientific.update(project_card_inputs(scientific,inputs,design,context,context.get('_reader_input_snapshot')))
    projected=scientific['reader_adapter/form_contrasts']
    readiness['card_input_adapter']={'schema_version':'astra_card_input.v1','status':'projected',
        'rows':len(projected),'eligible_rows':int(projected.card_input_eligible.sum()),
        'consumer_execution':'shared_report_cards_and_selector'}
    scientific.update(build_reader_tables(scientific,design,context.get('_reader_input_snapshot')))
    readiness['reader']={'status':'generated','version':'astra_reader.v1',
        'selected_findings':len(scientific['reader/findings']),'literature_comparison':'not_performed'}
    return scientific


def validate_tables(tables,design):
    # Archived v6 bundles without this additive adapter remain valid.
    if any(name.startswith('reader_adapter/') for name in tables):validate_card_inputs(tables,design)
    if any(name.startswith('reader/') for name in tables):validate_reader(tables)
    forms=set(tables['quant/summary'].form_id);contrasts={c['contrast_id'] for c in design['contrasts']}
    universes={'form_id':forms,'contrast_id':contrasts,'contrast_or_window_id':contrasts,
        'observation_id':set(tables['science/measurement_observations'].observation_id),
        'site_id':set(tables['science/site_identity_audit'].site_id),'identity_id':set(tables['science/site_identity_audit'].identity_id),
        'proposed_entity_id':set(tables['kinase/kinase_candidate_edges'].candidate_id)}
    for name,frame in tables.items():
        if not name.startswith('science/'):continue
        for key,allowed in universes.items():
            if key in frame and not set(frame[key].dropna())<=allowed:raise ValueError('Evidence foreign key mismatch:'+name+'/'+key)
    children=tables['science/observation_sites'];posterior=children.loc[children.individual_site_posterior.notna()]
    if not posterior.individual_site_posterior.between(0,1).all() or not posterior.parser_version.eq(LOCAL_VERSION).all() or not posterior.probability_scope.eq('site_localization_probability').all() or not posterior.assignment_status.eq('site_localization_supported').all():raise ValueError('Site posterior lacks validated parser scope')
    calls=tables['science/kinase_calls'];confirmed=calls.loc[calls.resolution.ne('no_call')]
    from .inference_policy import validate_policy
    policies={}
    for row in tables['science/calibration_provenance'].itertuples():
        artifact=json.loads(row.artifact_json)
        policy,status=validate_policy(artifact,design,json.loads(row.resource_hashes_json))
        policies[row.policy_id]=(artifact,policy,status)
    if len(confirmed) and (not confirmed.inference_status.eq('calibrated_inference').all() or not confirmed.calibration_status.eq('calibrated_in_domain').all() or confirmed.calibration_artifact_sha256.isna().any() or confirmed.entity_id.isna().any()):raise ValueError('Call lacks domain-matched calibration evidence')
    for row in confirmed.itertuples():
        artifact,policy,status=policies.get(row.policy_id,(None,None,None))
        if status!='calibrated_in_domain' or artifact['sha256']!=row.calibration_artifact_sha256:raise ValueError('Confirmed call artifact mismatch')
        if row.effective_measurement_groups<policy['rules']['minimum_measurement_groups'] or row.effective_substrate_genes<policy['rules']['minimum_genes'] or row.track not in policy['rules']['allowed_tracks']:raise ValueError('Confirmed call policy coverage mismatch')
    anchors=set(tables['science/group_excluded_anchors'].anchor_id)
    for ids in calls.sensitivity_evidence_ids.dropna():
        if not set(str(ids).split(';'))-{''}<=anchors:raise ValueError('Call anchor foreign key mismatch')
    for col,universe in [('specificity_ids',set(tables['science/specificity_scores'].specificity_id)),('localization_ids',set(tables['science/localization_by_contrast'].localization_id))]:
        for value in tables['kinase/substrate_contributions'][col].dropna():
            if not set(str(value).split(';'))-{''}<=universe:raise ValueError('Contribution evidence foreign key mismatch:'+col)


def run(order_id,config,output_dir,checkpoint=lambda:None,progress=lambda message:None):
    from .astra_package import run_astra_analysis
    from . import astra_evidence_v6
    context=config['experimental_context']
    if not config.get('fasta_path'):
        from .science_reference import bind_registered_reference
        fasta,context,mapping=bind_registered_reference(config['reference_root'],context)
        config={**config,'fasta_path':fasta,'experimental_context':context,'taxonomy_mapping_path':config.get('taxonomy_mapping_path') or mapping}
    validate_execution(context,context['study_design']['study']['ptm_type'],config.get('species_tax_id'))
    reference=legacy.preflight(config,context)
    return run_astra_analysis(order_id,{**config,'fasta_path':reference['reference_path']},output_dir,checkpoint,progress,engine=astra_evidence_v6)


def source_universe(tables,mapped,inputs,context):
    reference=legacy._reference(inputs,context)
    observed={a for group in tables['protein_contrasts'].protein_group for a in str(group).split(';')}
    entries={e['accession']:e for e in reference['entries'] if e['entry_kind']=='biological'}
    rows=mapped.to_dict('records');present={r['mapped_accession'] for r in rows}
    for accession in sorted(observed-present):
        e=entries.get(accession)
        if not e:continue
        rows.append({'mapped_accession':accession,'fasta_taxonomy_id':e['taxon'],'fasta_gene':e['gene'] or '',
                     'source_scope':'protein_context'})
    return rows


def write_artifacts(directory,scientific,context,inputs,sources,readiness):
    from .generic_workflow import json_write
    from .evidence_methods import registry
    if 'reader/packet' in scientific:write_reader(directory,scientific)
    capabilities={'schema_version':'input_capabilities.v2','input_scope':'DIA-NN_quantification_matrices_not_instrument_spectra',
        'matrix_quantification_available':'PR' in inputs or 'PG' in inputs,'measured_localization_available':bool(scientific['science/observation_sites'].site_probability.notna().any()),
        'run_confidence_available':bool(scientific['science/measurement_observations'].localization_metric_value.notna().any()),
        'site_report_status':readiness['supporting_inputs']['diann_site_report'],
        'search_analysis_reference_status':readiness['reference'].get('search_reference_status','see_reference_provenance'),
        'instrument_raw_search_performed':False,'missing_input_does_not_disable_matrix_quantification':True}
    json_write(directory/'study/input_capabilities.json',capabilities)
    consumers={'PR':('contrast_quantification.prepare_forms','quant/runlevel.csv'),
        'PG':('contrast_quantification.protein_contrasts','quant/protein_contrasts.csv'),
        'FASTA':('science_reference.preflight','science/site_identity_audit.csv'),
        'DIANN':('diann_evidence.observations → localization_evidence.observation_sites','science/measurement_observations.csv'),
        'DIANN_SITE':('localization_evidence.read_site_report','science/site_report_observations.csv'),
        'CROSSWALK':('diann_evidence.observations','science/measurement_observations.csv'),
        'SPECIFICITY':('kinase_specificity.score_sites → membership gate → astra_discovery.score_candidates','science/specificity_scores.csv'),
        'CALIBRATION':('inference_policy.evaluate','science/calibration_provenance.csv'),
        'SEARCH_FASTA':('science_reference.preflight','science/reference_inventory.csv'),
        'TAXONOMY':('science_reference.inventory','science/reference_inventory.csv'),
        'VALIDATION':('perturbation_validation.import_validation','science/perturbation_validation.csv'),
        'TRANSGENE':('raw provenance only; construct-specific mapping not implemented','inputs/')}
    rows=[]
    field_map={'PR':'pr_matrix_path','PG':'pg_matrix_path','FASTA':'fasta_path',**INPUT_FIELDS}
    for key,(function,table) in consumers.items():
        path=inputs.get(key,inputs.get('SPECIFICITY_RESTRICTED') if key=='SPECIFICITY' else None)
        status='not_provided' if path is None else 'accepted_but_unused' if key=='TRANSGENE' else 'consumed'
        reason=None
        if key=='CROSSWALK' and path and not inputs.get('DIANN'):
            status='accepted_but_unused';reason='main_report_not_provided; observations_returns_before_reading_crosswalk'
        if key=='DIANN' and path and readiness['measurement_evidence']['status']=='unsupported_schema':status='accepted_unsupported_schema'
        if key=='DIANN_SITE' and path and readiness['supporting_inputs']['diann_site_report']['status'] in {'unsupported_schema','ambiguous_semantics'}:status='accepted_unsupported_schema'
        if key=='SPECIFICITY' and path and readiness['specificity']['status'] in {'resource_unavailable','license_unresolved','not_run_resource_not_packaged'}:status='accepted_but_unavailable'
        rows.append({'input_id':key,'source_filename':Path(path).name if path else None,'sha256':digest(path) if path else None,
            'order_field':field_map[key],'runtime_input_key':key,'consumer':function,'export_location':table,'disposition':status,'reason':reason,
            'parser_version':LOCAL_VERSION if key in {'DIANN','DIANN_SITE','CROSSWALK'} else VERSION,
            'schema':'detected_and_declared_version_required','lineage_scope':'source_bytes_to_same_run_scientific_tables'})
    pd.DataFrame(rows).to_csv(directory/'study/input_lineage.csv',index=False)
    json_write(directory/'methods/method_registry.json',registry(scientific,readiness))
    json_write(directory/'methods/native_execution_runtime.json',readiness.get('native_method_runtime',[]))
    json_write(directory/'science/resource_registry.json',{'specificity':readiness['specificity'],'source_pin_sha256':sources['pin_sha256'],
        'sources':[{'query_id':q['query_id'],'provider':q['provider'],'status':q['status'],'response_sha256':q.get('response_sha256'),'license_scope':q.get('license_scope'),'reason':q.get('reason')} for q in sources['queries']]})
    json_write(directory/'science/official_parity_results.json',{'status':'resource_specific_parity_not_verified_in_this_run',
        'meaning':'official_function_invocation_and_external_adapter_tests_are_separate_from_this_experiment'})
    json_write(directory/'reproducibility/table_migration.json',{'canonical_profiles':'kinase/kinase_temporal_profiles.csv',
        'deprecated':{'quant/kinase_profiles.csv':{'superseded_by':'kinase/kinase_temporal_profiles.csv','reason':'legacy_v3_projection_not_all_v6_tracks'}},
        'inference_results':'science/inference_results.csv','calibrated_calls':'science/calibrated_calls.csv',
        'old_archives_unchanged':True})
    counts=scientific['science/inference_results'].no_call_reasons.fillna('').str.split(';').explode().value_counts().to_dict()
    json_write(directory/'evidence/analysis_limitations.json',{'no_call_reason_counts':{k:int(v) for k,v in counts.items() if k},
        'independent_biological_pq':'not_computed','benchmark_improvement':'not_demonstrated',
        'literature_comparison':'selected_documents_and_metadata_not_automatically_compared',
        'GP':'not_executed_legacy_noise_and_timescale_contract_not_validated_for_this_design',
        'source_completeness':sources.get('status'),'conditional_replay':'_LOCAL_SPECIFICITY' in inputs})
    json_write(directory/'methods/adapter_parameters.json',{'specificity':readiness['specificity'].get('membership_policy'),
        'localization':context.get('science',{}).get('localization_policy',{'policy_id':'all_joint_contributors_localized.v1','threshold':.75}),
        'normalization':context.get('normalization_policy'),'interval_contrasts':'adjacent_conditions_within_declared_shared_reference_series; overlapping_exploratory_with_primary_contrasts'})


def report_addendum(scientific,readiness):
    lines=['\n## Evidence integration v6 (experimental)',
        'Read study/input_capabilities.json and study/input_lineage.csv first. Inputs are DIA-NN matrices, not raw/mzML spectra. No spectrum re-search was performed.',
        'science/inference_results.csv preserves method signals even when calibrated_calls.csv is empty. No-call is neither inactive nor a failed quantitative analysis.',
        'science/localization_by_contrast.csv is the canonical per-comparison gate. A baseline confidence does not certify other conditions. Site probability and minimum occupied-site confidence remain distinct.',
        'kinase/method_scores.csv separates the repository z-score baseline from optional official PhosX native results. Method p/q are not population biological p/q. Check method_id and execution status; the repository baseline is not official KSEA.',
        'temporal/interval_contrasts.csv recalculates adjacent comparisons on their own joint masks. These exploratory intervals overlap primary comparisons; they are not independent tests.',
        'temporal/group_excluded_cowave.csv uses parent-adjusted A and excludes the target gene or measurement group. These are same-data diagnostics, not validation.',
        'All method execution/resource limitations are recorded in methods/method_registry.json and evidence/analysis_limitations.json. Expectations from publications did not enter numeric scoring. Literature concordance has not been adjudicated.']
    comparisons=scientific['quant/comparisons'];available=comparisons.loc[comparisons.included&comparisons.A.notna()].copy()
    selected=available.assign(absA=available.A.abs()).sort_values(['absA','form_id','contrast_id'],ascending=[False,True,True]).head(3)
    lines.append('Descriptive examples, selected by descending absolute A (no pathway selection; not evidence of a specific kinase):')
    for r in selected.itertuples():lines.append(f'- quant/comparisons.csv: form_id={r.form_id}; contrast_id={r.contrast_id}; U_joint={r.U_joint:.6g}, P_joint={r.P_joint:.6g}, A={r.A:.6g}. Inspect joint masks, strict-parent and normalization sensitivity before interpretation.')
    if readiness['specificity'].get('raw_resource_packaged') is False:
        lines.append('Full numerical replay is conditional: the original permitted local specificity resource with the recorded hash must be supplied via --specificity-manifest. Raw restricted matrices are excluded from this archive.')
    return '\n'.join(lines)+'\n'
