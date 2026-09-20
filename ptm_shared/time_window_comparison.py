"""Constrained two-window allocation comparison, never a primary activity call.

Only observed, independently anchored profiles are used. Identifiability is
checked before adding a smoothness penalty; regularization cannot create data
support. Ratios describe fitted magnitude shares, not regulator switching proof.
"""
from collections import defaultdict
import numpy as np
from scipy.optimize import nnls
from .kinase_trajectory_evidence import elapsed_minutes
from .analysis_universe import signature
from .tmm_identifiability import ambiguity_aware_attribution

MODEL="time_window_nnls.v1"


def compare_time_windows(manifest,inputs,scores,*,penalty=1.0):
    if penalty<0: raise ValueError("negative_temporal_penalty")
    conditions=sorted(manifest['conditions'],key=lambda c:(elapsed_minutes(c) if elapsed_minutes(c) is not None else float('inf'),c))
    candidates=defaultdict(set)
    for module in manifest['candidate_modules']:
        for member in module['members']:candidates[member['key']].add(module['canonical'])
    rows=[]
    for fid in sorted(inputs['features']):
        names=sorted(candidates[fid]); observed=inputs['ptm_timeseries'].get(fid,{})
        record={'feature_id':fid,'candidates':names,'evaluation_status':'not_evaluable','reason':None,
            'allocations':[],'resolution':'insufficient_information','observed':observed}
        profiles=[scores.get('relative',{}).get(k,{}) for k in names]
        if not names:record['reason']='no_candidate_mapping'
        elif len(conditions)<6 or any(elapsed_minutes(c) is None for c in conditions):record['reason']='insufficient_declared_time_grid'
        elif any(p.get('profile_type')!='data_driven' or p.get('kinase_profile_provenance',{}).get('support_unit')!='measurement_group.v1'
                 or p.get('kinase_profile_provenance',{}).get('independent_group_count',0)<3 for p in profiles):
            record['reason']='independent_observed_anchors_required'
        else:
            half=len(conditions)//2;windows=[conditions[:half],conditions[half:]]
            blocks=[];targets=[];used=[]
            for window, labels in enumerate(windows):
                valid=[c for c in labels if c in observed and all(p.get('profile_values',{}).get(c) is not None for p in profiles)]
                values=np.asarray([[p['profile_values'][c] for p in profiles] for c in valid]).reshape(len(valid),len(names))
                block=np.zeros((len(valid),2*len(names)));block[:,window*len(names):(window+1)*len(names)]=values
                blocks.append(block);targets.extend(abs(observed[c]) for c in valid);used.extend((c,window) for c in valid)
            x=np.vstack(blocks);target=np.asarray(targets)
            if any(len(block)<=len(names) for block in blocks):record['reason']='insufficient_observations_per_window'
            elif np.linalg.matrix_rank(x)<x.shape[1] or np.linalg.cond(x)>1e6:
                record.update(reason='rank_deficient_or_ill_conditioned_profiles',resolution='ambiguous_group')
            elif np.linalg.norm(target)<=1e-12:record['reason']='no_directional_signal'
            else:
                guard=ambiguity_aware_attribution(fid,target,x,[f"{k}@window{w}" for w in range(2) for k in names],n_bootstrap=0)
                if not guard.attribution_supported or any(len(g.members)>1 for g in guard.groups):
                    record.update(reason=guard.unsupported_reason or 'unresolved_window_group',resolution='ambiguous_group')
                    rows.append(record)
                    continue
                smooth=np.sqrt(penalty)*np.column_stack([np.eye(len(names)),-np.eye(len(names))])
                coefficients,_=nnls(np.vstack([x,smooth]),np.concatenate([target,np.zeros(len(names))]))
                fit=x@coefficients
                if np.any(fit<=1e-12):record['reason']='unsupported_zero_fit'
                else:
                    weights=[]
                    for i,(condition,window) in enumerate(used):
                        shares=x[i,window*len(names):(window+1)*len(names)]*coefficients[window*len(names):(window+1)*len(names)]/fit[i]
                        if abs(float(sum(shares))-1)>1e-8:raise ValueError('window_mass_conservation_failed')
                        weights.append({'condition':condition,'window':window,'shares':dict(zip(names,map(float,shares))),
                            'weighted_observations':{k:float(observed[condition]*r) for k,r in zip(names,shares)}})
                    record.update(evaluation_status='evaluated',reason=None,resolution='conditional_individual_model',
                        allocations=weights,used_conditions=[c for c,_ in used],windows=windows,
                        residual_sum_squares=float(np.sum((target-fit)**2)),coefficients=coefficients.tolist(),
                        biological_uncertainty=None)
        rows.append(record)
    return {'model_id':MODEL,'status':'completed','records':rows,'measurement_revision':manifest['measurement_revision'],
        'candidate_graph_hash':signature(manifest['candidate_modules']),'target_transform':'magnitude',
        'original_sign_preserved':True,'window_policy':'two_contiguous_halves_of_declared_grid',
        'smoothness_penalty':penalty,'rank_check':'unpenalized_observed_design','independent_validation':False,
        'default_model_promoted':False,'interpretation':'conditional_time_varying_allocation_not_kinase_switching_evidence'}
