"""All-row correction, technical repeatability, emergence and evidence coverage."""
import json
import numpy as np
import pandas as pd
from .astra_inputs import stable_id
from .contrast_quantification import ContrastEstimator

VERSION='astra_evidence.v1'


def censoring_bounds(tables,design,model=None):
    """Conditional bounds from supplied, documented per-feature/run detection limits.

    No limit is fitted from the observed minimum. A declared external model is
    checked structurally, not asserted biologically validated by this function.
    """
    model=model or {};est=ContrastEstimator(design);rows=[]
    records=model.get('limits',[])
    lookup={}
    valid=all(model.get(k) for k in ['model_version','source','validation_evidence','assumption'])
    if records and not valid:raise ValueError('LOD limits require model, source, validation evidence and explicit assumption')
    for record in records:
        key=(record['form_id'],record['injection_id']);value=float(record['upper_detection_limit'])
        if key in lookup or not np.isfinite(value) or value<=0:raise ValueError('Invalid duplicate/nonpositive LOD limit')
        lookup[key]=value
    forms=tables['summary'].set_index('form_id')
    run={fid:g.set_index('injection_id').reindex([s['injection_id'] for s in est.samples]) for fid,g in tables['runlevel'].groupby('form_id')}
    for contrast in design['contrasts']:
        ref=est.indices[contrast['reference_condition_id']];target=est.indices[contrast['target_condition_id']]
        for fid,g in run.items():
            if g.iloc[ref].U_observed.fillna(False).any():continue
            bound=np.nan;status='unavailable_no_validated_detection_limit_model';mask=[]
            if valid and records and forms.loc[fid,'primary_adjustment_eligible']:
                values=g.adjusted_log2_ratio.to_numpy(float).copy();complete=True
                for i in ref:
                    limit=lookup.get((fid,est.samples[i]['injection_id']))
                    if pd.notna(g.iloc[i].parent_log2) and limit is not None:
                        values[i]=np.log2(limit)-g.iloc[i].parent_log2;mask.append(est.samples[i]['injection_id'])
                    elif pd.notna(g.iloc[i].parent_log2):complete=False
                if complete:
                    bound=est.contrast(values,contrast)['value'][0]
                    status='conditional_lower_bound' if np.isfinite(bound) else 'unavailable_insufficient_joint_parent_target'
                else:status='unavailable_missing_feature_run_limits'
            rows.append({'bound_id':stable_id('bound',[fid,contrast['contrast_id']]),'form_id':fid,'contrast_id':contrast['contrast_id'],
                'conditional_A_lower_bound':bound,'status':status,'reference_limit_run_ids':';'.join(mask),
                'model_version':model.get('model_version'),'LOD_source':model.get('source'),'assumption':model.get('assumption'),
                'validation_evidence':model.get('validation_evidence'),'baseline_FC_created':False,
                'interpretation':'conditional_bound_not_point_estimate; supplied_model_validity_remains_an_assumption'})
    return pd.DataFrame(rows,columns=['bound_id','form_id','contrast_id','conditional_A_lower_bound','status','reference_limit_run_ids','model_version','LOD_source','assumption','validation_evidence','baseline_FC_created','interpretation'])


def quantitative_evidence(tables,alternative,design,normalization,alternative_norm,discovery):
    est=ContrastEstimator(design);run=tables['runlevel'];forms=tables['summary'];ids=forms.form_id.tolist()
    form_index=forms.set_index('form_id');id_index={fid:i for i,fid in enumerate(ids)}
    matrices={key:run.pivot(index='form_id',columns='injection_id',values=key).reindex(index=ids,columns=[s['injection_id'] for s in est.samples]).to_numpy(float)
              for key in ['adjusted_log2_ratio','ptm_log2','parent_log2']}
    loo=[]
    for contrast in design['contrasts']:
        selected=list(est.indices[contrast['reference_condition_id']])+list(est.indices[contrast['target_condition_id']])
        for omitted in selected:
            values=matrices['adjusted_log2_ratio'].copy();values[:,omitted]=np.nan
            scores=est.contrast(values,contrast)['value']
            for fid,score in zip(ids,scores):
                loo.append({'form_id':fid,'contrast_id':contrast['contrast_id'],'omitted_injection_id':est.samples[omitted]['injection_id'],
                            'A':score,'statistic_type':'technical_injection_omission_not_biological_inference'})
    loo=pd.DataFrame(loo,columns=['form_id','contrast_id','omitted_injection_id','A','statistic_type'])
    ranges=loo.groupby(['form_id','contrast_id']).A.agg(['min','max']) if len(loo) else pd.DataFrame(columns=['min','max'])
    alternate=alternative['comparisons'].set_index(['form_id','contrast_id']).A.to_dict()
    paired=tables['strict_parent_paired'].set_index(['form_id','contrast_id']).strict_parent_A.to_dict()
    complete=tables['strict_parent_complete'].set_index(['form_id','contrast_id']).strict_parent_A.to_dict()
    impacts=[]
    for r in tables['comparisons'].to_dict('records'):
        key=(r['form_id'],r['contrast_id']);a,u,p=r['A'],r['U_joint'],r['P_joint'];alt=alternate.get(key,np.nan);strict=paired.get(key,np.nan)
        category='parent_unavailable'
        if r['included']:
            category='direction_reversed' if a*u<0 and min(abs(a),abs(u))>=.25 else 'parent_explains_unadjusted_change' if abs(u)>=.5 and abs(a)<.5 else 'parent_masks_adjusted_change' if abs(a)>=.5 and abs(u)<.5 else 'largely_concordant'
            if np.isfinite(r['U_all']) and abs(r['U_all']-u)>=.25:category='joint_mask_sensitive'
        low,high=(ranges.loc[key,'min'],ranges.loc[key,'max']) if key in ranges.index else (np.nan,np.nan)
        unstable=(np.isfinite(alt) and abs(alt-a)>=.5) or (np.isfinite(strict) and abs(strict-a)>=.5)
        impacts.append({**r,'impact_id':stable_id('impact',key),'paired_parent_A':strict,'complete_parent_A':complete.get(key,np.nan),
            'alternative_normalization_A':alt,'normalization_delta':alt-a,'alternative_parent_delta':strict-a,
            'classification':category,'parent_or_normalization_sensitive':bool(unstable),'technical_LOO_min':low,'technical_LOO_max':high,
            'technical_unstable':bool(np.isfinite(low) and np.isfinite(high) and high-low>=.5),
            'observation_tier':'repeated_observation' if min(r['reference_joint_n'],r['target_joint_n'])>=2 else 'single_observation' if r['included'] else 'not_evaluable',
            'classification_policy':'effect_0.5_direction_reversal_both_0.25; not_kinase_activity'})
    offsets=[]
    factors=normalization['factors'];other=alternative_norm['factors']
    for r in tables['comparisons'].to_dict('records'):
        # Calculate the factor contrast on the form's actual joint mask and weights.
        i=id_index[r['form_id']]
        vector=np.array([np.log2(other['PR'][s['input_column']]/factors['PR'][s['input_column']])-np.log2(other['PG'][s['input_column']]/factors['PG'][s['input_column']]) for s in est.samples])
        vector[~np.isfinite(matrices['adjusted_log2_ratio'][i])]=np.nan
        c=next(c for c in design['contrasts'] if c['contrast_id']==r['contrast_id'])
        offsets.append({'form_id':r['form_id'],'contrast_id':r['contrast_id'],'expected_A_offset':est.contrast(vector,c)['value'][0],
                        'observed_A_offset':alternate.get((r['form_id'],r['contrast_id']),np.nan)-r['A'],
                        'same_factor_PR_PG_cancels':True,'normalization_scope':'whole_study_once'})
    emergence=[];conditions={c['condition_id']:c for c in design['conditions']};candidateedges=discovery['kinase_candidate_edges']
    detection=tables['detection']
    observations={(fid,cid):g for (fid,cid),g in run.groupby(['form_id','condition_id'],sort=True)}
    # Preserve every declared comparison. Shared baseline observations are stored once in runlevel,
    # and referenced here; different post-references never overwrite each other.
    scopes=detection.to_dict('records')
    referenced={(r['form_id'],r['condition_id']) for r in scopes}
    scopes += [{'form_id':fid,'condition_id':cid} for fid,cid in sorted(observations) if (fid,cid) not in referenced]
    contrast_by_id={c['contrast_id']:c for c in design['contrasts']}
    for d in scopes:
        fid,cid=d['form_id'],d['condition_id'];group=observations[(fid,cid)]
        positive=group.loc[group.U_observed,'ptm_intensity'];parent=group.loc[group.P_observed,'parent_intensity'];form=form_index.loc[fid]
        contrast_id=d.get('contrast_id');reference_id=d.get('reference_condition_id')
        pairing=contrast_by_id.get(contrast_id,{}).get('pairing')
        series_id=stable_id('series',[conditions[cid]['arm_id'],reference_id,pairing]) if contrast_id else None
        candidates=candidateedges.loc[candidateedges.form_id.eq(fid)]
        emergence.append({'emergence_id':stable_id('emergence',[fid,cid,contrast_id]),'contrast_id':contrast_id,'reference_condition_id':reference_id,'series_id':series_id,'form_id':fid,'condition_id':cid,'arm_id':conditions[cid]['arm_id'],
            'time_min':conditions[cid]['time']['minutes'],'detected_n':len(positive),'scheduled_n':len(group),'parent_n':len(parent),
            'detected_injection_ids':';'.join(group.loc[group.U_observed,'injection_id']),'parent_injection_ids':';'.join(group.loc[group.P_observed,'injection_id']),
            'positive_intensity_min':positive.min() if len(positive) else np.nan,'positive_intensity_median':positive.median() if len(positive) else np.nan,
            'positive_intensity_max':positive.max() if len(positive) else np.nan,'repeatability_tier':'repeated_detection' if len(positive)>=2 else 'single_detection' if len(positive) else 'not_detected',
            'repeatability_policy':'at_least_two_technical_observations.v1','candidate_ids':';'.join(sorted(set(candidates.candidate_id))),
            'candidate_edge_ids':';'.join(sorted(set(candidates.edge_id))),'parent_eligible':bool(form.primary_adjustment_eligible),
            'baseline_score_contributor':False if d is not None and d.get('baseline_status')=='undetected' else None,
            'post_reference_condition_id':d.get('post_reference_condition_id') if d is not None else None,
            'post_reference_A':d.get('eligible_A') if d is not None else np.nan,'post_reference_caveat':'conditioned_on_first_repeated_detection; not_baseline_fold_change',
            'LOD_bound_status':'unavailable_no_validated_detection_limit_model','population_detection_p_value':None})
    ledger=[];byform={fid:g for fid,g in candidateedges.groupby('form_id')}
    provider_failed=any(s.get('status') not in {'hit','no_hit'} for s in discovery.get('source_queries',[]))
    impactindex={(r['form_id'],r['contrast_id']):r for r in impacts}
    for r in tables['comparisons'].to_dict('records'):
        f=form_index.loc[r['form_id']];e=byform.get(r['form_id'],candidateedges.iloc[:0]);reasons=set(';'.join(e.restriction_reasons).split(';'))-{''}
        if not f.primary_mapping_eligible:reasons.add('mapping_failure')
        if not f.primary_adjustment_eligible:reasons.add('missing_or_ineligible_parent')
        if not r['included']:reasons.add('no_baseline_or_target_quantification')
        if provider_failed:reasons.add('provider_failure_or_incomplete_queries')
        if e.empty:reasons.add('no_database_edge_or_usable_motif')
        if not e.edge_type.str.startswith('curated').any():reasons.add('no_database_edge')
        if not e.edge_type.eq('sequence_motif_candidate').any():reasons.add('no_usable_sequence_motif')
        if impactindex[(r['form_id'],r['contrast_id'])]['technical_unstable']:reasons.add('unstable_technical_estimate')
        ledger.append({'evidence_id':stable_id('evidence',[r['form_id'],r['contrast_id']]),'form_id':r['form_id'],'contrast_id':r['contrast_id'],
            'parent_quantification_eligible':bool(f.primary_adjustment_eligible),'site_attribution_eligible':bool(f.primary_mapping_eligible and f.n_modifications==1 and f.localization_probability_available),
            'candidate_count':e.candidate_id.nunique(),'candidate_ids':';'.join(sorted(set(e.candidate_id))),
            'edge_ids':';'.join(sorted(set(e.edge_id))),'A_available':bool(r['included']),'reason_codes':';'.join(sorted(reasons)),
            'independent_biological_pq':'unavailable_method_not_implemented'})
    qc=[]
    for (fid,cid,mid),g in run.groupby(['form_id','condition_id','material_id'],sort=True,dropna=False):
        for key in ['ptm_log2','parent_log2','adjusted_log2_ratio']:
            vals=g[key].dropna()
            qc.append({'form_id':fid,'condition_id':cid,'material_id':mid,'track':key,'observed_n':len(vals),'scheduled_n':len(g),
                'log2_SD':vals.std(ddof=1) if len(vals)>=2 else np.nan,'statistical_scope':'within_material_technical_dispersion; not_population_CI' if pd.notna(mid) else 'unconfirmed_material_measurement_dispersion; not_population_CI'})
    return {'parent_adjustment_impact':pd.DataFrame(impacts,columns=list(tables['comparisons'])+['impact_id','paired_parent_A','complete_parent_A','alternative_normalization_A','normalization_delta','alternative_parent_delta','classification','parent_or_normalization_sensitive','technical_LOO_min','technical_LOO_max','technical_unstable','observation_tier','classification_policy']),
        'technical_injection_omissions':loo,'normalization_offsets':pd.DataFrame(offsets,columns=['form_id','contrast_id','expected_A_offset','observed_A_offset','same_factor_PR_PG_cancels','normalization_scope']),
        'emergence_evidence':pd.DataFrame(emergence,columns=['emergence_id','contrast_id','reference_condition_id','series_id','form_id','condition_id','arm_id','time_min','detected_n','scheduled_n','parent_n','detected_injection_ids','parent_injection_ids','positive_intensity_min','positive_intensity_median','positive_intensity_max','repeatability_tier','repeatability_policy','candidate_ids','candidate_edge_ids','parent_eligible','baseline_score_contributor','post_reference_condition_id','post_reference_A','post_reference_caveat','LOD_bound_status','population_detection_p_value']),
        'feature_evidence_ledger':pd.DataFrame(ledger,columns=['evidence_id','form_id','contrast_id','parent_quantification_eligible','site_attribution_eligible','candidate_count','candidate_ids','edge_ids','A_available','reason_codes','independent_biological_pq']),
        'technical_dispersion':pd.DataFrame(qc,columns=['form_id','condition_id','material_id','track','observed_n','scheduled_n','log2_SD','statistical_scope'])}


def candidate_context_and_omissions(tables,discovery,technical_omissions):
    """Kinase abundance/self-sites never substitute for a substrate footprint."""
    edges=discovery['kinase_candidate_edges'];members=discovery['substrate_contributions']
    proteins=tables['protein_contrasts'];forms=tables['summary'];context=[];self_sites=[];omissions=[]
    groups_by_gene={}
    for group,gene in proteins[['protein_group','gene']].drop_duplicates().itertuples(index=False):
        for symbol in str(gene).split(';'):groups_by_gene.setdefault(symbol,set()).add(group)
    for candidate,g in edges.groupby('candidate_id',sort=True):
        gene=g.candidate_gene.iloc[0];groups=groups_by_gene.get(gene,set())
        for contrast in tables['comparisons'].contrast_id.unique():
            abundance=proteins.loc[proteins.protein_group.isin(groups)&proteins.contrast_id.eq(contrast)]
            if abundance.empty:context.append({'candidate_id':candidate,'contrast_id':contrast,'protein_group':None,'log2_abundance':None,'status':'unavailable_kinase_protein_not_observed_or_family_unresolved'})
            for r in abundance.itertuples():context.append({'candidate_id':candidate,'contrast_id':contrast,'protein_group':r.protein_group,'log2_abundance':r.log2_change,'status':'protein_abundance_not_activity'})
        own_forms=forms.loc[forms['Protein.Group'].isin(groups)]
        for r in tables['comparisons'].loc[tables['comparisons'].form_id.isin(own_forms.form_id)].itertuples():
            self_sites.append({'candidate_id':candidate,'form_id':r.form_id,'contrast_id':r.contrast_id,'A':r.A,'U_all':r.U_all,
                'site_function_status':'regulatory_function_not_annotated','interpretation':'observed_kinase_PTM_not_activity_proof'})
    loo_index={(cid,omitted):rows.set_index('form_id').A.to_dict() for (cid,omitted),rows in technical_omissions.groupby(['contrast_id','omitted_injection_id'])}
    for (candidate,cid,track),rows in members.loc[members.track.isin(['curated_A','motif_A'])].groupby(['candidate_id','contrast_id','track'],sort=True):
        for (contrast,omitted),values in loo_index.items():
            if contrast!=cid:continue
            gene_values={}
            for r in rows.itertuples():
                observed=[values.get(fid,np.nan) for fid in r.form_ids.split(';')];observed=[v for v in observed if np.isfinite(v)]
                if observed:gene_values.setdefault(r.substrate_gene,[]).append(float(np.median(observed)))
            score=float(np.mean([np.median(v) for v in gene_values.values()])) if gene_values else np.nan
            omissions.append({'candidate_id':candidate,'contrast_id':cid,'track':track,'omitted_injection_id':omitted,'score':score,
                'remaining_genes':len(gene_values),'statistical_scope':'technical_measurement_sensitivity_not_biological_inference'})
    return {'kinase_protein_context':pd.DataFrame(context,columns=['candidate_id','contrast_id','protein_group','log2_abundance','status']),
        'kinase_self_site_context':pd.DataFrame(self_sites,columns=['candidate_id','form_id','contrast_id','A','U_all','site_function_status','interpretation']),
        'kinase_technical_omissions':pd.DataFrame(omissions,columns=['candidate_id','contrast_id','track','omitted_injection_id','score','remaining_genes','statistical_scope'])}
