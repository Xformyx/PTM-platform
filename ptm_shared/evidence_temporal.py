"""Adjacent contrasts and group-excluded co-wave on recorded A observations."""
import json
import numpy as np
import pandas as pd
from .astra_inputs import stable_id
from .contrast_quantification import ContrastEstimator
from .kinase_trajectory_evidence import compute_target_trajectory_evidence

INTERVAL_COLUMNS=['interval_id','form_id','series_id','arm_id','reference_condition_id','target_condition_id',
    'from_min','to_min','duration_min','U_joint','P_joint','A','U_all','P_all','reference_run_ids','target_run_ids',
    'reference_joint_n','target_joint_n','statistical_unit','status','estimator_version']
COWAVE_COLUMNS=['cowave_id','candidate_id','series_id','track','site_key','excluded_kind','excluded_ids','remaining_site_keys',
    'signed_correlation','interval_concordance','support_status','details','independent_validation','quantification_track']


def adjacent_contrasts(tables,temporal,design):
    rows=[]
    if design['study'].get('design_axis')=='cross_sectional':return pd.DataFrame(columns=INTERVAL_COLUMNS)
    est=ContrastEstimator(design);summary=tables['summary'];run=tables['runlevel'];conditions=est.conditions
    contrasts={c['contrast_id']:c for c in design['contrasts']}
    def array(column):return run.pivot(index='form_id',columns='injection_id',values=column).reindex(index=summary.form_id,columns=[s['injection_id'] for s in est.samples]).to_numpy(float)
    u,p=array('ptm_log2'),array('parent_log2');joint=np.isfinite(u)&np.isfinite(p)
    uj,pj=np.where(joint,u,np.nan),np.where(joint,p,np.nan)
    for series in temporal['temporal_series'].to_dict('records'):
        original=[contrasts[c] for c in str(series['contrast_ids']).split(';') if c in contrasts]
        if not original:continue
        refs={c['reference_condition_id'] for c in original}
        matched=all(c.get('reference_strategy')=='time_matched' for c in original)
        if len(refs)!=1 and not matched:continue
        if len({c['pairing'] for c in original})!=1:continue
        targets={c['target_condition_id'] for c in original}
        nodes=targets if matched else targets|refs
        ordered=sorted(nodes,key=lambda c:(conditions[c]['time']['minutes'],c))
        times=[conditions[c]['time']['minutes'] for c in ordered]
        if len(set(times))!=len(times):continue # arbitrary/control contrasts are not a serial path
        for a,b in zip(ordered,ordered[1:]):
            contrast={'reference_condition_id':a,'target_condition_id':b,'pairing':original[0]['pairing']}
            values={key:est.contrast(v,contrast) for key,v in [('U_joint',uj),('P_joint',pj),('U_all',u),('P_all',p)]}
            for idx,form in enumerate(summary.itertuples()):
                valid=form.primary_adjustment_eligible and np.isfinite(values['U_joint']['value'][idx]) and np.isfinite(values['P_joint']['value'][idx])
                rows.append({'interval_id':stable_id('interval',[series['series_id'],form.form_id,a,b]),'form_id':form.form_id,
                    'series_id':series['series_id'],'arm_id':series['arm_id'],'reference_condition_id':a,'target_condition_id':b,
                    'from_min':conditions[a]['time']['minutes'],'to_min':conditions[b]['time']['minutes'],
                    'duration_min':conditions[b]['time']['minutes']-conditions[a]['time']['minutes'],
                    **{k:v['value'][idx] for k,v in values.items()},
                    'A':values['U_joint']['value'][idx]-values['P_joint']['value'][idx] if valid else np.nan,
                    'reference_run_ids':est.run_ids(joint[idx],a),'target_run_ids':est.run_ids(joint[idx],b),
                    'reference_joint_n':values['U_joint']['reference_n'][idx],'target_joint_n':values['U_joint']['target_n'][idx],
                    'statistical_unit':values['U_joint']['statistical_unit'],'status':'quantifiable_change' if valid else 'parent_or_joint_observations_unavailable',
                    'estimator_version':'adjacent_same_injection_unit_balanced.v1'})
    return pd.DataFrame(rows,columns=INTERVAL_COLUMNS)


def excluded_cowave(discovery,temporal,design):
    rows=[];members=discovery['substrate_contributions'];contrast={c['contrast_id']:c for c in design['contrasts']};conditions={c['condition_id']:c for c in design['conditions']}
    if design['study'].get('design_axis')=='cross_sectional':return pd.DataFrame(columns=COWAVE_COLUMNS)
    for s in temporal['temporal_series'].to_dict('records'):
        cids=str(s['contrast_ids']).split(';');labels={c:f"{conditions[contrast[c]['target_condition_id']]['time']['minutes']:g}min" for c in cids}
        if len(set(labels.values()))!=len(labels):continue
        selected=members.loc[members.contrast_id.isin(cids)&members.track.isin(['curated_A','motif_A','specificity_A'])]
        for (candidate,track),group in selected.groupby(['candidate_id','track'],sort=True):
            vectors={key:{labels[r.contrast_id]:r.value for r in g.itertuples()} for key,g in group.groupby('site_key')}
            metadata={key:g.iloc[0] for key,g in group.groupby('site_key')}
            identities={key:{'protein_group':r.substrate_gene,'modified_sequence':r.measurement_group_id} for key,r in metadata.items()}
            for key,r in metadata.items():
                for kind,column in [('gene','substrate_gene'),('measurement_group','measurement_group_id')]:
                    exclude=set(str(r[column]).split(';'))
                    remaining=[k for k,other in metadata.items() if not exclude&set(str(other[column]).split(';'))]
                    # The existing target-excluded engine receives explicit A and
                    # a filtered anchor universe; no fit includes the target gene/group.
                    result=compute_target_trajectory_evidence(candidate=candidate,target_key=key,timeseries=vectors,
                        conditions=list(labels.values()),eligible_keys=remaining,identities=identities)
                    rows.append({'cowave_id':stable_id('cowave',[candidate,s['series_id'],track,key,kind]),'candidate_id':candidate,
                        'series_id':s['series_id'],'track':track,'site_key':key,'excluded_kind':kind,'excluded_ids':';'.join(sorted(exclude)),
                        'remaining_site_keys':';'.join(sorted(remaining)),
                        'signed_correlation':result['metrics']['signed_profile_correlation']['value'],
                        'interval_concordance':result['metrics']['direction_concordance_fraction']['value'],
                        'support_status':result['support_status'],'details':json.dumps(result,sort_keys=True,allow_nan=False),
                        'independent_validation':False,'quantification_track':'parent_adjusted_A'})
    return pd.DataFrame(rows,columns=COWAVE_COLUMNS)


EFFECT_INTERVAL_COLUMNS=['interval_id','form_id','series_id','from_contrast_id','to_contrast_id','from_min','to_min',
    'from_target_condition_id','from_reference_condition_id','to_target_condition_id','to_reference_condition_id',
    'from_target_run_ids','from_reference_run_ids','to_target_run_ids','to_reference_run_ids',
    'from_target_joint_n','from_reference_joint_n','to_target_joint_n','to_reference_joint_n',
    'from_pairing','to_pairing','from_statistical_unit','to_statistical_unit',
    *[prefix+'_'+side+'_'+count for prefix in ['from','to'] for side in ['target','reference'] for count in ['aggregation_n','biological_n']],
    'U_joint','P_joint','A','status','effect_kind','inference_status','estimator_version']


def effect_intervals(tables,design):
    """Descriptive endpoint effect differences, reusing real unit/mask estimation.

    No cross-time pair is inferred. Each endpoint uses its actual contrast and
    same-injection joint mask; missing scheduled endpoints are never bypassed.
    This supplies no variance, biological p/q, or interaction test.
    """
    from .effect_series import resolve_series
    scopes,_=resolve_series(design);rows=[]
    if design['study'].get('design_axis')=='cross_sectional':return pd.DataFrame(columns=EFFECT_INTERVAL_COLUMNS)
    est=ContrastEstimator(design);summary=tables['summary'];run=tables['runlevel']
    contrasts={c['contrast_id']:c for c in design['contrasts']}
    def array(column):return run.pivot(index='form_id',columns='injection_id',values=column).reindex(index=summary.form_id,columns=[s['injection_id'] for s in est.samples]).to_numpy(float)
    u,p=array('ptm_log2'),array('parent_log2');joint=np.isfinite(u)&np.isfinite(p)
    uj,pj=np.where(joint,u,np.nan),np.where(joint,p,np.nan)
    for scope in scopes.values():
        if scope['reference_strategy']!='time_matched':continue
        points=scope['points'];times=[p['time_min'] for p in points]
        if None in times or len(set(times))!=len(times):continue
        endpoints={p['contrast_id']:{k:est.contrast(v,contrasts[p['contrast_id']]) for k,v in [('U_joint',uj),('P_joint',pj)]} for p in points}
        for a,b in zip(points,points[1:]):
            av,bv=endpoints[a['contrast_id']],endpoints[b['contrast_id']]
            for idx,form in enumerate(summary.itertuples()):
                delta={k:bv[k]['value'][idx]-av[k]['value'][idx] for k in ['U_joint','P_joint']}
                valid=form.primary_adjustment_eligible and all(np.isfinite(v) for v in delta.values())
                record={'interval_id':stable_id('effect_interval',[scope['series_id'],form.form_id,a['contrast_id'],b['contrast_id']]),
                    'form_id':form.form_id,'series_id':scope['series_id'],'from_min':a['time_min'],'to_min':b['time_min'],
                    **delta,'A':delta['U_joint']-delta['P_joint'] if valid else np.nan,
                    'status':'descriptive_effect_difference' if valid else 'endpoint_parent_or_joint_observations_unavailable',
                    'effect_kind':'matched_treatment_effect_change','inference_status':'descriptive_only_no_interaction_test',
                    'estimator_version':'endpoint_joint_unit_balanced_difference.v1'}
                for prefix,point,values in [('from',a,av),('to',b,bv)]:
                    record[prefix+'_contrast_id']=point['contrast_id'];record[prefix+'_pairing']=point['pairing']
                    record[prefix+'_statistical_unit']=values['U_joint']['statistical_unit']
                    for side in ['target','reference']:
                        cid=point[side+'_condition_id'];record[prefix+'_'+side+'_condition_id']=cid
                        record[prefix+'_'+side+'_run_ids']=est.run_ids(joint[idx],cid)
                        record[prefix+'_'+side+'_joint_n']=values['U_joint'][side+'_n'][idx]
                        for count in ['aggregation_n','biological_n']:
                            record[prefix+'_'+side+'_'+count]=values['U_joint'][side+'_'+count][idx]
                rows.append(record)
    return pd.DataFrame(rows,columns=EFFECT_INTERVAL_COLUMNS)
