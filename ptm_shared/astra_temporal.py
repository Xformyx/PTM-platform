"""Measured-grid features, target-excluded anchors and bounded cross-layer joins."""
from collections import defaultdict
import json
import numpy as np
import pandas as pd

from .astra_inputs import stable_id
from .substrate_temporal_dynamics import compute_site_kinetic_profile, SiteKineticConfig
from .kinase_trajectory_evidence import compute_target_trajectory_evidence, AnchorDeltaIndex, scheduled_intervals

VERSION = 'observed_grid_temporal.v1'
FEATURE_COLUMNS = ['feature_id','entity_id','series_id','arm_id','reference_condition_id','track','times_minutes','values',
    'observed_mask','observed_points','observed_peak_time_min','signed_peak','maximum_absolute_effect','onset_lower_min',
    'onset_upper_min','onset_left_censored','recovery_lower_min','recovery_upper_min','right_censored','pattern',
    'legacy_pattern_candidate','threshold','threshold_sensitive','loto_pattern_stability','observed_duration_min',
    'adjacent_trapezoid_auc','adjacent_absolute_auc','auc_supported_duration_min','gap_intervals','adjacent_intervals',
    'observation_counts','parent_pattern_agreement','normalization_pattern_agreement','baseline_anchor_is_independent_observation','causality_status','estimator_version']


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',',':'))


def finite(value):
    try:return float(value) if np.isfinite(float(value)) else None
    except (TypeError,ValueError):return None


def basic_pattern(values,threshold):
    observed=[v for v in values if v is not None]
    active=[v for v in observed if abs(v)>=threshold]
    if not observed:return 'not_evaluable'
    if not active:return 'below_operational_threshold'
    if any(v>0 for v in active) and any(v<0 for v in active):return 'mixed_direction'
    if abs(observed[-1])<threshold:return 'transient_observed'
    if len(observed)>1 and all(abs(v)>=threshold for v in observed):return 'sustained_over_observed_points'
    if len(observed)>1 and all(b>=a for a,b in zip(observed,observed[1:])):return 'monotone_increase'
    if len(observed)>1 and all(b<=a for a,b in zip(observed,observed[1:])):return 'monotone_decrease'
    return 'delayed_or_variable_observed'


def measured_features(times,values,threshold=.5):
    times=list(map(float,times));values=[finite(v) for v in values]
    observed=[i for i,v in enumerate(values) if v is not None]
    active=[i for i in observed if abs(values[i])>=threshold]
    peak=max(observed,key=lambda i:abs(values[i])) if observed else None
    onset=active[0] if active else None
    previous=max((i for i in observed if onset is not None and i<onset),default=None)
    recovery=next((i for i in observed if active and i>active[0] and abs(values[i])<threshold),None)
    before_recovery=max((i for i in observed if recovery is not None and i<recovery),default=None)
    intervals=[];area=absolute=duration=0.;gaps=0
    for i in range(len(times)-1):
        dt=times[i+1]-times[i];available=values[i] is not None and values[i+1] is not None and dt>0
        row={'from_min':times[i],'to_min':times[i+1],'dt_min':dt,'status':'adjacent_observed_trapezoid' if available else 'gap_not_bridged',
             'delta':values[i+1]-values[i] if available else None,'rate_log2_per_min':(values[i+1]-values[i])/dt if available else None}
        intervals.append(row)
        if available:
            area+=(values[i]+values[i+1])*dt/2;absolute+=(abs(values[i])+abs(values[i+1]))*dt/2;duration+=dt
        else:gaps+=1
    pattern=basic_pattern(values,threshold)
    loto=[basic_pattern([None if j==i else v for j,v in enumerate(values)],threshold)==pattern for i in observed]
    # Reuse the mature pattern engine, but its gap-bridging AUC is never exported.
    positive_dt=np.diff(times);positive_dt=positive_dt[positive_dt>0]
    config=SiteKineticConfig(onset_threshold_fc=threshold,recovery_threshold_fc=threshold,
        secondary_peak_sep_minutes=float(np.median(positive_dt)) if len(positive_dt) else 0.,
        run_loto=False,run_threshold_sensitivity=False)
    legacy=compute_site_kinetic_profile([f'{t:g}min' for t in times],values,config=config).primary_pattern if times else 'not_evaluable'
    return {'times_minutes':_json(times),'values':_json(values),'observed_mask':_json([v is not None for v in values]),
        'observed_points':len(observed),'observed_peak_time_min':times[peak] if peak is not None else None,
        'signed_peak':values[peak] if peak is not None else None,'maximum_absolute_effect':abs(values[peak]) if peak is not None else None,
        'onset_lower_min':times[previous] if previous is not None else None,'onset_upper_min':times[onset] if onset is not None else None,
        'onset_left_censored':onset is not None and previous is None,'recovery_lower_min':times[before_recovery] if before_recovery is not None else None,
        'recovery_upper_min':times[recovery] if recovery is not None else None,'right_censored':bool(active and active[-1]==observed[-1]),
        'pattern':pattern,'legacy_pattern_candidate':legacy,'threshold':threshold,
        'threshold_sensitive':any(basic_pattern(values,threshold*m)!=pattern for m in [.5,2]),
        'loto_pattern_stability':float(np.mean(loto)) if loto else None,
        'observed_duration_min':times[observed[-1]]-times[observed[0]] if len(observed)>1 else 0.,
        'adjacent_trapezoid_auc':area if duration else None,'adjacent_absolute_auc':absolute if duration else None,
        'auc_supported_duration_min':duration,'gap_intervals':gaps,'adjacent_intervals':_json(intervals),
        'baseline_anchor_is_independent_observation':False,'causality_status':'not_tested','estimator_version':VERSION}


def order_intervals(source,target):
    a,b=finite(source.get('onset_upper_min')),finite(target.get('onset_lower_min'))
    c,d=finite(target.get('onset_upper_min')),finite(source.get('onset_lower_min'))
    if a is None or c is None:return 'not_evaluable',None,None
    if b is not None and a<b:return 'source_observed_before_target',b-a,c-d if d is not None else None
    if d is not None and c<d:return 'target_observed_before_source',d-c,a-b if b is not None else None
    if a==c and b==d:return 'same_observation_interval',None,None
    return 'order_unresolved',None,None


def integrate_temporal(tables,discovery,design,context,source_context=None,impacts=None):
    threshold=float(context.get('temporal_policy',{}).get('effect_threshold_log2',.5))
    if not np.isfinite(threshold) or threshold<=0:raise ValueError('Temporal effect threshold must be positive and finite')
    conditions={c['condition_id']:c for c in design['conditions']};series={};contrast_series={}
    for c in design['contrasts']:
        target=conditions[c['target_condition_id']]
        sid=stable_id('series',[target['arm_id'],c['reference_condition_id'],c.get('pairing')])
        series.setdefault(sid,{'series_id':sid,'arm_id':target['arm_id'],'reference_condition_id':c['reference_condition_id'],
            'contrast_ids':[],'reference_strategy':'one_declared_reference; matched_time_controls_remain_separate_series',
            'pairing':c.get('pairing'),'paired_biological_units':c.get('pairing')=='paired' and design['replication_declaration']!='technical_per_condition'})['contrast_ids'].append(c['contrast_id'])
        contrast_series[c['contrast_id']]=sid
    for s in series.values():
        s['contrast_ids']=sorted(s['contrast_ids'],key=lambda cid:(conditions[next(c['target_condition_id'] for c in design['contrasts'] if c['contrast_id']==cid)]['time']['minutes'],cid))
    impacts_by_form={fid:rows for fid,rows in impacts.groupby('form_id')} if impacts is not None else {}
    features=[];protein=[];kinase=[];fixed=[];anchors=[];membership=discovery['substrate_contributions'];profiles=discovery['kinase_temporal_profiles']
    def feature(entity,sid,track,rows,column):
        duplicates=rows.loc[rows.contrast_id.duplicated(keep=False),'contrast_id'].unique()
        if len(duplicates):
            raise ValueError(f'duplicate_temporal_observations: entity={entity}, track={track}, '
                             f'contrasts={list(duplicates)}; expected one aggregated observation per contrast')
        ordered=rows.set_index('contrast_id').reindex(series[sid]['contrast_ids'])
        times=[conditions[next(c['target_condition_id'] for c in design['contrasts'] if c['contrast_id']==cid)]['time']['minutes'] for cid in series[sid]['contrast_ids']]
        # Duplicate target times are valid contrasts but do not imply a temporal ordering.
        extra={}
        if track=='A' and entity in impacts_by_form:
            impact=impacts_by_form[entity].set_index('contrast_id').reindex(series[sid]['contrast_ids'])
            primary=basic_pattern([finite(v) for v in ordered[column]],threshold)
            for key,target in [('paired_parent_A','parent_pattern_agreement'),('alternative_normalization_A','normalization_pattern_agreement')]:
                values=[finite(v) for v in impact[key]]
                extra[target]=basic_pattern(values,threshold)==primary if any(v is not None for v in values) else None
        counts=ordered[[k for k in ['reference_joint_n','target_joint_n','reference_biological_n','target_biological_n','reference_observed_n','target_observed_n','n_sites','n_genes','n_measurement_groups'] if k in ordered]].to_json(orient='records')
        return {'observation_counts':counts,**extra,'feature_id':stable_id('feature',[entity,sid,track]),'entity_id':entity,'series_id':sid,
            'arm_id':series[sid]['arm_id'],'reference_condition_id':series[sid]['reference_condition_id'],'track':track,
            **measured_features(times,ordered[column].tolist(),threshold)}
    for sid,s in series.items():
        comp=tables['comparisons'].loc[tables['comparisons'].contrast_id.isin(s['contrast_ids'])].copy()
        comp.loc[~comp.included,'A']=np.nan
        for entity,rows in comp.groupby('form_id',sort=True):
            for track in ['A','U_all','U_joint','P_joint']:features.append(feature(entity,sid,track,rows,track))
        for layer,key in [('PG','protein_contrasts'),('strict_unmodified','strict_unmodified_proteins')]:
            selected=tables[key].loc[tables[key].contrast_id.isin(s['contrast_ids'])]
            for entity,rows in selected.groupby('protein_group',sort=True):protein.append(feature(entity,sid,layer,rows,'log2_change'))
        selected=profiles.loc[profiles.contrast_id.isin(s['contrast_ids'])]
        for (candidate,track),rows in selected.groupby(['candidate_id','track'],sort=True):
            kinase.append(feature(candidate,sid,track,rows,'activity_magnitude'))
            members=membership.loc[membership.candidate_id.eq(candidate)&membership.track.eq(track)&membership.contrast_id.isin(s['contrast_ids'])]
            sets=[set(members.loc[members.contrast_id.eq(cid),'site_key']) for cid in s['contrast_ids']]
            common=set.intersection(*sets) if sets else set();previous=set()
            for cid,available in zip(s['contrast_ids'],sets):
                sub=members.loc[members.contrast_id.eq(cid)&members.site_key.isin(common)]
                score=sub.groupby('substrate_gene').value.median().mean() if len(sub) else np.nan
                fixed.append({'candidate_id':candidate,'series_id':sid,'contrast_id':cid,'track':track,
                    'fixed_common_score':score,'fixed_common_sites':len(common),'available_sites':len(available),
                    'entered_sites':len(available-previous),'departed_sites':len(previous-available),
                    'membership_turnover':len(available^previous)/len(available|previous) if available|previous else None})
                previous=available
            if track not in {'curated_A','motif_A','specificity_A'} or members.empty:continue
            # Existing target-exclusion engine receives A values and exact numeric time labels.
            times=[conditions[next(c['target_condition_id'] for c in design['contrasts'] if c['contrast_id']==cid)]['time']['minutes'] for cid in s['contrast_ids']]
            if len(set(times))!=len(times):continue
            labels=[f'{t:g}min' for t in times];time_by_cid=dict(zip(s['contrast_ids'],labels));vectors={};identities={}
            for key,rows2 in members.groupby('site_key'):
                vectors[key]={time_by_cid[r.contrast_id]:r.value for r in rows2.itertuples()}
                identities[key]={'protein_group':rows2.substrate_gene.iloc[0],'modified_sequence':rows2.measurement_group_id.iloc[0]}
            anchor_index=AnchorDeltaIndex(scheduled_intervals(labels),vectors,sorted(vectors),identities)
            for key in sorted(vectors):
                result=compute_target_trajectory_evidence(candidate=candidate,target_key=key,timeseries=vectors,
                    conditions=labels,eligible_keys=sorted(vectors),identities=identities,_anchor_index=anchor_index)
                anchors.append({'candidate_id':candidate,'series_id':sid,'track':track,'site_key':key,
                    'target_excluded':result['anchor_rebuilt_without_target'],'support_status':result['support_status'],
                    'signed_correlation':result['metrics']['signed_profile_correlation']['value'],
                    'interval_concordance':result['metrics']['direction_concordance_fraction']['value'],
                    'details':_json(result),'independent_validation':False})
    # Evidence-constrained joins only: same parent and kinase's own measured protein.
    pindex={(r['entity_id'],r['series_id'],r['track']):r for r in protein};links=[];forms=tables['summary'].set_index('form_id')
    def link(source,target,relation,record):
        order,low,high=order_intervals(source,target)
        links.append({'link_id':stable_id('link',[source['feature_id'],target['feature_id'],relation]),
            'source_evidence_id':source['feature_id'],'target_evidence_id':target['feature_id'],'series_id':source['series_id'],
            'relation_type':relation,'relation_source':record,'order_status':order,'possible_lag_lower_min':low,'possible_lag_upper_min':high,
            'source_peak_min':source['observed_peak_time_min'],'target_peak_min':target['observed_peak_time_min'],
            'peak_order':'unavailable' if source['observed_peak_time_min'] is None or target['observed_peak_time_min'] is None else 'source_first' if source['observed_peak_time_min']<target['observed_peak_time_min'] else 'same_bin' if source['observed_peak_time_min']==target['observed_peak_time_min'] else 'target_first',
            'source_points':source['observed_points'],'target_points':target['observed_points'],
            'source_onset_lower_min':source['onset_lower_min'],'source_onset_upper_min':source['onset_upper_min'],
            'target_onset_lower_min':target['onset_lower_min'],'target_onset_upper_min':target['onset_upper_min'],
            'source_signed_peak':source['signed_peak'],'target_signed_peak':target['signed_peak'],
            'sensitivity_evidence':'parent_adjustment_impact; normalization_offsets; candidate_sensitivity; temporal threshold and LOTO columns',
            'competing_explanations':'shared_baseline; normalization; parent_ratio_mathematical_coupling; phosphatase_or_accessibility_changes',
            'causality_status':'not_tested','independent_validation':False,'precise_lag':'unavailable'})
    for f in features:
        if f['track']!='A':continue
        target=pindex.get((forms.loc[f['entity_id'],'parent_pg'],f['series_id'],'PG'))
        if target:link(f,target,'same_parent_mathematical_dependence','PR_PG_identity')
    candidate_names=discovery['kinase_candidate_edges'].drop_duplicates('candidate_id').set_index('candidate_id').candidate_gene.to_dict()
    reference=context.get('_runtime_reference')
    verified_groups={}
    if reference is not None:
        from .science_reference import candidate_protein_groups
        for candidate,edges in discovery['kinase_candidate_edges'].groupby('candidate_id'):
            verified_groups[candidate]=candidate_protein_groups(edges,tables['protein_contrasts'].protein_group.unique(),reference)
    protein_names=tables['protein_contrasts'].drop_duplicates('protein_group').set_index('protein_group').gene.to_dict()
    for f in kinase:
        if f['track'] not in {'curated_A','motif_A','specificity_A'}:continue
        gene=candidate_names.get(f['entity_id'])
        for group,name in protein_names.items():
            if (group in verified_groups.get(f['entity_id'],set())) if reference is not None else gene in str(name).split(';'):
                target=pindex.get((group,f['series_id'],'PG'))
                if target:link(f,target,'kinase_protein_abundance_not_activity','exact_gene_symbol_within_species')
    # Only recorded network relations select downstream comparisons. They are
    # indirect context, never enzyme-site edges or evidence of causality.
    kinase_features={(candidate_names.get(f['entity_id']),f['series_id']):f for f in kinase if f['track']=='curated_A'}
    gene_groups=defaultdict(list)
    for group,name in protein_names.items():
        for gene in str(name).split(';'):gene_groups[gene].append(group)
    for item in source_context or []:
        if item.get('provider')!='STRING':continue
        if reference is not None:
            # Symbol-only network joins cannot establish enzyme identity in mixed
            # references; keep the raw provider context, without a timing claim.
            continue
        record=item['record'];left=record.get('preferredName_A');right=record.get('preferredName_B')
        for a,b in [(left,right),(right,left)]:
            for sid in series:
                source=kinase_features.get((a,sid))
                if source:
                    for group in gene_groups.get(b,[]):
                        target=pindex.get((group,sid,'PG'))
                        if target:link(source,target,'network_relation_context_not_direct_substrate',item['query_id'])
    return {'temporal_series':pd.DataFrame([{**s,'contrast_ids':';'.join(s['contrast_ids'])} for s in series.values()],columns=['series_id','arm_id','reference_condition_id','contrast_ids','reference_strategy','pairing','paired_biological_units']),
        'ptm_temporal_features':pd.DataFrame(features,columns=FEATURE_COLUMNS),'protein_temporal_features':pd.DataFrame(protein,columns=FEATURE_COLUMNS),
        'kinase_temporal_features':pd.DataFrame(kinase,columns=FEATURE_COLUMNS),
        'kinase_fixed_membership':pd.DataFrame(fixed,columns=['candidate_id','series_id','contrast_id','track','fixed_common_score','fixed_common_sites','available_sites','entered_sites','departed_sites','membership_turnover']),
        'target_excluded_anchors':pd.DataFrame(anchors,columns=['candidate_id','series_id','track','site_key','target_excluded','support_status','signed_correlation','interval_concordance','details','independent_validation']),
        'cross_layer_links':pd.DataFrame(links,columns=['link_id','source_evidence_id','target_evidence_id','series_id','relation_type','relation_source','order_status','possible_lag_lower_min','possible_lag_upper_min','source_peak_min','target_peak_min','peak_order','source_points','target_points','source_onset_lower_min','source_onset_upper_min','target_onset_lower_min','target_onset_upper_min','source_signed_peak','target_signed_peak','sensitivity_evidence','competing_explanations','causality_status','independent_validation','precise_lag']).drop_duplicates('link_id')}
