"""Measurement dependence, uncalibrated selective decisions and unit uncertainty."""
from collections import defaultdict
import json
import numpy as np
import pandas as pd
from .astra_inputs import stable_id
from .contrast_quantification import ContrastEstimator

VERSION='selective_evidence.v1.experimental'
CALL_COLUMNS=['call_id','series_id','contrast_or_window_id','resolution','entity_id','proposed_resolution','proposed_entity_id',
 'direction','call_scope','calibration_status','policy_id','calibration_artifact_sha256','effective_measurement_groups',
 'effective_substrate_genes','discriminating_evidence_ids','shared_evidence_ids','temporal_evidence_ids',
 'sensitivity_evidence_ids','restriction_reasons','no_call_reasons']
ANCHOR_COLUMNS=['anchor_id','candidate_id','contrast_id','track','excluded_kind','excluded_id','excluded_contribution_ids',
 'remaining_contribution_ids','score','remaining_genes','remaining_measurement_groups','independent_validation']


def identifiability(discovery, temporal, design):
    members=discovery['substrate_contributions'];profiles=discovery['kinase_temporal_profiles'];edges=discovery['kinase_candidate_edges']
    anchors=[];calls=[];index=defaultdict(set)
    for r in members.to_dict('records'):
        if r['track']=='curated_A':
            for group in str(r['measurement_group_id']).split(';'):index[(r['contrast_id'],group)].add(r['candidate_id'])
    by_candidate={(cid,contrast,track):group for (cid,contrast,track),group in members.groupby(['candidate_id','contrast_id','track'],sort=True)}
    conditions={c['condition_id']:c for c in design['conditions']};contrasts={c['contrast_id']:c for c in design['contrasts']}
    for p in profiles.loc[profiles.track.isin(['curated_A','motif_A','specificity_A'])].to_dict('records'):
        candidate=p['candidate_id'];cid=p['contrast_id'];track=p['track'];sub=by_candidate.get((candidate,cid,track),members.iloc[:0]);reasons=['uncalibrated_policy']
        groups={g for value in sub.measurement_group_id for g in str(value).split(';')};genes=set(sub.substrate_gene)
        shared={g for g in groups if len(index[(cid,g)])>1};unique=groups-shared
        if not groups:reasons.append('insufficient_measurements')
        if groups and not unique:reasons.append('shared_substrate_indistinguishable')
        local_anchor_ids=[]
        for kind,column in [('gene','substrate_gene'),('measurement_group','measurement_group_id')]:
            for excluded in sorted({v for value in sub[column] for v in str(value).split(';')}):
                mask=sub[column].map(lambda value:excluded in str(value).split(';'));remaining=sub.loc[~mask]
                score=remaining.groupby('substrate_gene').value.median().mean() if len(remaining) else np.nan
                aid=stable_id('anchor',[candidate,cid,track,kind,excluded]);local_anchor_ids.append(aid)
                anchors.append({'anchor_id':aid,'candidate_id':candidate,'contrast_id':cid,'track':track,'excluded_kind':kind,
                    'excluded_id':excluded,'excluded_contribution_ids':';'.join(sub.loc[mask,'contribution_id']),
                    'remaining_contribution_ids':';'.join(remaining.contribution_id),'score':score,'remaining_genes':remaining.substrate_gene.nunique(),
                    'remaining_measurement_groups':len({g for value in remaining.measurement_group_id for g in str(value).split(';')}),'independent_validation':False})
                if kind=='gene' and np.isfinite(score) and np.isfinite(p['activity_magnitude']) and score*p['activity_magnitude']<0:reasons.append('gene_omission_unstable')
        c=contrasts[cid];sid=stable_id('series',[conditions[c['target_condition_id']]['arm_id'],c['reference_condition_id'],c.get('pairing')])
        fixed=temporal.get('kinase_fixed_membership',pd.DataFrame())
        if len(fixed):
            f=fixed.loc[fixed.candidate_id.eq(candidate)&fixed.series_id.eq(sid)&fixed.track.eq(track)]
            if len(f) and (f.fixed_common_sites.eq(0).any() or (f.available_sites>f.fixed_common_sites).any()):reasons.append('membership_turnover')
        e=edges.loc[edges.candidate_id.eq(candidate)]
        if not e.empty and e.localization_probability.isna().all():reasons.append('unresolved_site')
        if not e.empty and e.kinase_taxon.isna().any():reasons.append('species_mapping_ambiguous')
        family=not e.empty and e.candidate_resolution.eq('family').all()
        magnitude=p['activity_magnitude'];direction='unavailable' if not np.isfinite(magnitude) else 'mixed' if p['positive_genes'] and p['negative_genes'] else 'up' if magnitude>0 else 'down' if magnitude<0 else 'mixed'
        calls.append({'call_id':stable_id('call',[candidate,cid,track,VERSION]),'series_id':sid,'contrast_or_window_id':cid,
            'resolution':'no_call','entity_id':None,'proposed_resolution':'family' if family else 'kinase' if not e.empty and e.candidate_resolution.eq('gene_or_accession').all() else 'motif_class',
            'proposed_entity_id':candidate,'direction':direction,'call_scope':'contrast','calibration_status':'uncalibrated',
            'policy_id':VERSION,'calibration_artifact_sha256':None,'effective_measurement_groups':len(groups),'effective_substrate_genes':len(genes),
            'discriminating_evidence_ids':';'.join(sub.loc[sub.measurement_group_id.map(lambda m:bool(set(str(m).split(';'))&unique)),'contribution_id']),
            'shared_evidence_ids':';'.join(sub.loc[sub.measurement_group_id.map(lambda m:bool(set(str(m).split(';'))&shared)),'contribution_id']),
            'temporal_evidence_ids':';'.join(temporal.get('kinase_temporal_features',pd.DataFrame(columns=['entity_id','series_id','feature_id'])).loc[lambda f:f.entity_id.eq(candidate)&f.series_id.eq(sid),'feature_id']),
            'sensitivity_evidence_ids':';'.join(local_anchor_ids),'restriction_reasons':'operational_coverage_is_not_calibrated_accuracy',
            'no_call_reasons':';'.join(sorted(set(reasons)))})
    return {'kinase_calls':pd.DataFrame(calls,columns=CALL_COLUMNS),'group_excluded_anchors':pd.DataFrame(anchors,columns=ANCHOR_COLUMNS)}


def unit_intervals(analysis,design,policy=None):
    """Cluster bootstrap of joint log ratios, shared draws across all contrasts.

    Cluster strata are the set of conditions in which a declared unit/pair appears.
    This preserves longitudinal units and a shared baseline without assuming that
    destructive timepoint materials belong to the same donor. No p-values.
    """
    policy=policy or {};repeats=int(policy.get('resamples',500));seed=int(policy.get('seed',1729));minimum=int(policy.get('minimum_units',3))
    if repeats<100 or minimum<3:raise ValueError('uncertainty_policy_requires_100_resamples_and_3_units')
    est=analysis['estimator'];arrays=analysis['arrays'];joint=np.isfinite(arrays['A']);rows=[]
    pairings={c.get('pairing') for c in design['contrasts']};paired=pairings=={'paired'}
    enabled=bool(policy.get('enabled',False));reason=None
    if not enabled:reason='not_requested'
    elif design['replication_declaration'] in {'technical_per_condition','unknown'}:reason='insufficient_independent_units'
    elif len(pairings)>1 or 'unknown' in pairings:reason='unsupported_pairing_design'
    maps={};strata=defaultdict(list)
    for cid in est.indices:
        values,pairs,unit=est.condition_values(np.where(joint,arrays['A'],np.nan),cid)
        if paired:
            by_pair=defaultdict(list)
            for key,value in values.items():
                if pairs.get(key):by_pair[pairs[key]].append(value)
            # Match the estimator: one mean per declared pair, not last-row wins.
            from .contrast_quantification import _finite_mean
            maps[cid]={key:_finite_mean(np.stack(v,axis=1),1) for key,v in by_pair.items()}
        else:maps[cid]=values
        if unit!='biological_unit':reason='biological_units_unresolved'
    cluster_conditions=defaultdict(list)
    for cid,values in maps.items():
        for key in values:cluster_conditions[key].append(cid)
    for key,conditions in cluster_conditions.items():strata[tuple(sorted(conditions))].append(key)
    rng=np.random.default_rng(seed);draws=[]
    if reason is None:
        for _ in range(repeats):
            draws.append([k for _,keys in sorted(strata.items()) for k in rng.choice(sorted(keys),len(keys),replace=True)])
    for c in design['contrasts']:
        a,b=maps[c['reference_condition_id']],maps[c['target_condition_id']]
        for i,fid in enumerate(analysis['summary'].form_id):
            valid_a={k:v[i] for k,v in a.items() if np.isfinite(v[i])};valid_b={k:v[i] for k,v in b.items() if np.isfinite(v[i])}
            n=min(len(valid_a),len(valid_b)) if not paired else len(set(valid_a)&set(valid_b));why=reason or ('insufficient_units' if n<minimum else None)
            if 'primary_adjustment_eligible' in analysis['summary'] and not analysis['summary'].iloc[i].primary_adjustment_eligible:
                why='parent_or_mapping_ineligible'
            samples=[]
            if why is None:
                for draw in draws:
                    if paired:values=[valid_b[k]-valid_a[k] for k in draw if k in valid_a and k in valid_b];value=np.mean(values) if values else np.nan
                    else:
                        ra=[valid_a[k] for k in draw if k in valid_a];tb=[valid_b[k] for k in draw if k in valid_b]
                        value=np.mean(tb)-np.mean(ra) if ra and tb else np.nan
                    samples.append(value)
            finite=np.asarray([v for v in samples if np.isfinite(v)])
            if why is None and len(finite)<.95*repeats:why='bootstrap_missingness_unstable'
            interval=np.quantile(finite,[.025,.975]) if why is None else [None,None]
            rows.append({'uncertainty_id':stable_id('uncertainty',[fid,c['contrast_id']]),'form_id':fid,'contrast_id':c['contrast_id'],
                'reference_biological_n':len(valid_a),'target_biological_n':len(valid_b),'effective_units':n,
                'interval_low':interval[0],'interval_high':interval[1],'uncertainty_type':'biological_cluster_percentile_CI' if why is None else 'unavailable',
                'status':why or 'computed_experimental','resamples':repeats if samples else 0,'seed':seed,
                'statistical_unit':'declared_pair' if paired else 'declared_biological_unit','method':'joint_ratio_cluster_bootstrap.v1',
                'assumptions':'independent_clusters; observed_units_represent_missing_units; covariance_and_shared_reference_preserved'})
    return pd.DataFrame(rows,columns=['uncertainty_id','form_id','contrast_id','reference_biological_n','target_biological_n','effective_units',
        'interval_low','interval_high','uncertainty_type','status','resamples','seed','statistical_unit','method','assumptions'])
