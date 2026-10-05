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
        if len(refs)!=1:continue
        reference=next(iter(refs));targets={c['target_condition_id'] for c in original}
        ordered=sorted(targets|{reference},key=lambda c:conditions[c]['time']['minutes'])
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
