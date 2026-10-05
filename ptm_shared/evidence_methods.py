"""Method contracts and a measured-universe z-score baseline, separate from calls."""
import math
import json
import numpy as np
import pandas as pd
from .astra_inputs import stable_id

METHOD_COLUMNS=['method_result_id','method_id','method_version','candidate_id','contrast_id','score_name','score',
 'direction_semantics','method_p','method_q','null_model','multiple_testing_family','eligible_site_count','universe_count',
 'input_universe_hash','membership_ids','status','statistical_unit','biological_p_value']


def zscore_baseline(tables,discovery,identities,entries):
    """Repository z-score, NOT an execution of official KSEA.

    One value per measured group, then gene. Null is exchangeability of assayed
    substrate genes; it is not a test across biological samples. Explicitly
    observed, eligible A values define the universe, never the whole genome.
    """
    rows=[];comp=tables['comparisons']
    entry_index={e['accession']:e for e in entries};gene_by_form={}
    for form,group in identities.groupby('form_id'):
        identities_for_form={(str(r.substrate_taxon),entry_index.get(r.input_accession,{}).get('gene')) for r in group.itertuples()}
        if len(identities_for_form)==1:
            taxon,gene=next(iter(identities_for_form))
            if taxon not in {'None','nan',''} and gene:gene_by_form[form]=taxon+':'+gene
    members=discovery['substrate_contributions'];members=members.loc[members.track.eq('curated_A')]
    for cid,comparisons in comp.groupby('contrast_id',sort=True):
        usable=comparisons.loc[comparisons.included&comparisons.A.notna()].copy()
        usable['gene']=usable.form_id.map(gene_by_form)
        universe=usable.dropna(subset=['gene']).groupby('gene').A.median()
        universe_hash=stable_id('universe',[(str(g),float(v)) for g,v in universe.items()])
        sd=float(universe.std(ddof=0)) if len(universe) else float('nan');mean=float(universe.mean())
        for candidate,sub in members.loc[members.contrast_id.eq(cid)].groupby('candidate_id',sort=True):
            # Identical validated taxon/gene identity in null and candidate sets.
            # An unresolved gene cannot enter only one side of the comparison.
            sub=sub.loc[sub.substrate_gene.isin(universe.index)]
            values=sub.groupby('substrate_gene').value.median();m=len(values)
            good=m>=2 and len(universe)>=3 and np.isfinite(sd) and sd>0
            z=(float(values.mean())-mean)*math.sqrt(m)/sd if good else None
            rows.append({'method_result_id':stable_id('method_result',['repository_zscore.v1',candidate,cid]),
                'method_id':'repository_measured_gene_zscore','method_version':'1','candidate_id':candidate,'contrast_id':cid,
                'score_name':'z_score','score':z,'direction_semantics':'relative_to_measured_gene_universe_not_direct_activity',
                'method_p':math.erfc(abs(z)/math.sqrt(2)) if good else None,'method_q':None,
                'null_model':'normal_approximation_exchangeable_observed_substrate_genes_not_biological_replicates',
                'multiple_testing_family':cid+':all_evaluable_curated_candidates','eligible_site_count':sub.site_key.nunique(),
                'universe_count':len(universe),'input_universe_hash':universe_hash,'membership_ids':';'.join(sorted(sub.contribution_id)),
                'status':'computed_exploratory' if good else 'insufficient_coverage_or_variance','statistical_unit':'substrate_gene','biological_p_value':None})
    out=pd.DataFrame(rows,columns=METHOD_COLUMNS)
    for cid,frame in out.loc[out.method_p.notna()].groupby('contrast_id'):
        ordered=frame.sort_values('method_p');p=ordered.method_p.to_numpy(float);n=len(p)
        out.loc[ordered.index,'method_q']=np.minimum(1,np.minimum.accumulate((p*n/np.arange(1,n+1))[::-1])[::-1])
    return out


def registry(scientific,readiness):
    methods=[{'method_id':'repository_measured_gene_zscore','implementation':'ptm_shared.evidence_methods.zscore_baseline',
        'version':'1','status':'executed','scope':'measured_gene_universe_A_curated_membership','official_implementation':False},
        {'method_id':'PhosX','version':'0.23.1','commit':'b556f59c39f099b5f3fcb574a8a70856c3fdc82c',
         'status':'resource_unavailable','reason':'separately_pinned_matrix_background_and_local_use_permission_required',
         'code_license':'Apache-2.0','data_license':'requires_resource_specific_review','upstream_activation_evidence':'separate_not_executed'},
        {'method_id':'Kinase_Library','commit':'6b81cf8f9736c4f88e4dc07dbd0f99fe9e67b32a','status':'license_unresolved',
         'reason':'CC-BY-NC-SA-3.0_scope_not_approved_for_platform_runtime','official_implementation':True},
        {'method_id':'KSEA_official','status':'not_requested','reason':'repository_zscore_is_separate_not_official_KSEA_execution'},
        {'method_id':'PTM-SEA','status':'resource_unavailable','reason':'pinned_ssGSEA2_R_environment_and_licensed_PTMsigDB_site_signatures_required'},
        {'method_id':'KSTAR','status':'resource_unavailable','reason':'pinned_human_network_background_and_validated_mapping_required'},
        {'method_id':'PhosR','status':'not_evaluable','reason':'no_automatic_imputation_or_biological_test_on_technical_only_data; external_comparator_contract_required'},
        {'method_id':'MSstatsPTM','status':'not_evaluable','reason':'official_model_environment_and_suitable_biological_design_required; A_is_not_MSstatsPTM'},
        {'method_id':'RoKAI','status':'deferred','reason':'optional_network_propagation_not_primary_site_evidence'},
        {'method_id':'PHOTON','status':'deferred','reason':'optional_network_context_not_direct_kinase_site_evidence'},
        {'method_id':'probabilistic_cowave_GP','status':'not_evaluable','reason':'legacy_insulin_15min_prior_and_implicit_noise_are_not_a_generic_validated_uncertainty_model'},
        {'method_id':'group_excluded_cowave','status':'executed','implementation':'kinase_trajectory_evidence.compute_target_trajectory_evidence',
         'scope':'observational_A_gene_and_measurement_group_exclusion_not_independent_validation'}]
    executions=scientific.get('kinase/method_executions',pd.DataFrame())
    if len(executions):
        for method in methods:
            if method['method_id']=='PhosX':
                method.update(status='executed' if executions.status.eq('executed').all() else 'partial',
                    reason=None,execution_ids=executions.execution_id.tolist(),official_implementation=True,
                    result_table='kinase/method_scores.csv',membership_table='kinase/method_membership.csv')
    return {'schema_version':'method_registry.v2','methods':methods,
        'calibration':'not_implied_by_method_specific_pq','actual_sufficient_input_required':True}
