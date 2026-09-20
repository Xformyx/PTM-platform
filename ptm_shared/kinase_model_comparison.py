"""Versioned transparent footprint baselines, never production model promotion.

KSEA z formula: casecpb/KSEA app.R. ULM/MLM t statistics: decoupler
run_ulm/mt.mlm definitions. This NumPy/SciPy implementation is not a claim of
package byte parity. Group aggregation and eligibility are explicit here.
"""
from collections import defaultdict
import numpy as np
from scipy.stats import norm, t
from .analysis_universe import signature
from .kinase_trajectory_evidence import measurement_group_id
from .temporal_feature_input import finite

MODELS = {"ksea_z.v1", "ulm_t.v1", "mlm_t.v1", "partial_linear.v1"}


def run_footprint_comparisons(manifest, inputs, requested):
    requested = sorted(set(requested))
    if set(requested)-MODELS: raise ValueError("unsupported_comparison_model")
    identities = inputs["features"]
    groups = defaultdict(list)
    for fid, identity in identities.items():
        group = (identity.get("fasta_taxonomy_id"), identity.get("isoform"), measurement_group_id(fid, identity))
        groups[signature(group)].append(fid)
    feature_group = {f:g for g, members in groups.items() for f in members}
    kinases = sorted(m["canonical"] for m in manifest["candidate_modules"])
    edges = {m["canonical"]:{feature_group[x["key"]] for x in m["members"] if x["key"] in feature_group} for m in manifest["candidate_modules"]}
    candidate_hash = signature(manifest["candidate_modules"])
    results = []
    for model in requested:
        if model == "partial_linear.v1":
            results.append(partial_linear_models(manifest, inputs)); continue
        records = []
        for condition in manifest["conditions"]:
            values = {g:np.median(v) for g,members in groups.items()
                      if (v:=[finite(inputs["ptm_timeseries"].get(f,{}).get(condition)) for f in members
                              if finite(inputs["ptm_timeseries"].get(f,{}).get(condition)) is not None])}
            keys = sorted(values)
            y = np.asarray([values[g] for g in keys], dtype=float)
            design = np.asarray([[float(g in edges[k]) for k in kinases] for g in keys], dtype=float).reshape(len(keys),len(kinases))
            for j, kinase in enumerate(kinases):
                mask = design[:,j]>0
                count = int(mask.sum())
                score = pvalue = None
                reason = None
                if count < 2 or len(y)<3:
                    reason = "insufficient_independent_measurement_groups"
                elif model == "ksea_z.v1":
                    sd = float(np.std(y,ddof=1))
                    if sd<=1e-12: reason="flat_background"
                    else:
                        score=float((np.mean(y[mask])-np.mean(y))*np.sqrt(count)/sd)
                        pvalue=float(2*norm.sf(abs(score)))
                else:
                    x = np.column_stack([np.ones(len(y)), design if model=="mlm_t.v1" else design[:,j]])
                    if np.linalg.matrix_rank(x)<x.shape[1] or len(y)<=x.shape[1]:
                        reason="rank_deficient_or_insufficient_degrees_of_freedom"
                    else:
                        beta=np.linalg.lstsq(x,y,rcond=None)[0]
                        residual=y-x@beta; dof=len(y)-x.shape[1]
                        covariance=np.linalg.inv(x.T@x)*float(residual@residual/dof)
                        column=j+1 if model=="mlm_t.v1" else 1
                        se=float(np.sqrt(max(0,covariance[column,column])))
                        if se<=1e-12: reason="residual_variance_not_estimable"
                        else:
                            score=float(beta[column]/se); pvalue=float(2*t.sf(abs(score),dof))
                records.append(dict(kinase=kinase,condition=condition,score=score,p_value=pvalue,q_value=None,
                    evaluation_status="evaluated" if score is not None else "not_evaluable",reason=reason,
                    substrate_groups=count,background_groups=len(y),unit="standardized_footprint_not_probability"))
        # One predefined family covers all tested kinase x condition records.
        tested=sorted([(r['p_value'],i) for i,r in enumerate(records) if r['p_value'] is not None])
        running=1.0
        for rank in range(len(tested),0,-1):
            p,i=tested[rank-1];running=min(running,p*len(tested)/rank);records[i]['q_value']=running
        results.append({"model_id":model,"model_version":model,"status":"completed",
            "evaluation_status":"evaluated" if tested else "not_evaluable", "records":records,
            "measurement_revision":manifest['measurement_revision'],"candidate_graph_hash":candidate_hash,
            "track":"relative","input_unit":"protein_adjusted_log2_contrast", "input_transform":"identity",
            "statistical_unit":"measurement_group", "aggregation":"median_within_measurement_group",
            "group_crosswalk":dict(groups),"missing_policy":"observed_only_per_condition",
            "multiple_testing_family":"all_evaluated_kinases_x_conditions_within_model",
            "biological_n":None,"biological_n_reason":"substrate_count_is_not_biological_replicates",
            "independent_validation":False,"default_model_promoted":False,
            "false_positive_rate":None,"false_positive_rate_reason":"independent_truth_not_bound"})
    return {"schema_version":"kinase_model_comparison.v1", "models":results,
            "primary_result_changed":False,"requested_models":requested}


def partial_linear_models(manifest, inputs):
    """Low-dimensional comparison using real times, no synthesized observations.

    The residual interval is a model-conditional prediction interval, not a
    biological replicate interval. It does not supply observations to Wave.
    """
    from .kinase_trajectory_evidence import elapsed_minutes
    records=[]
    for fid in sorted(inputs['features']):
        pairs=[(c,elapsed_minutes(c),finite(v)) for c,v in inputs['ptm_timeseries'].get(fid,{}).items()]
        pairs=sorted((c,x,y) for c,x,y in pairs if x is not None and y is not None)
        x=np.asarray([p[1] for p in pairs]); y=np.asarray([p[2] for p in pairs])
        record={'feature_id':fid,'used_conditions':[p[0] for p in pairs],
                'missing_conditions':[c for c in manifest['conditions'] if c not in {p[0] for p in pairs}],
                'evaluation_status':'not_evaluable','reason':'insufficient_distinct_observed_times',
                'slope_per_minute':None,'predicted_values':None,'biological_interval':None}
        if len(set(x))>=3:
            centered=x-x.mean();denom=float(centered@centered)
            slope=float(centered@(y-y.mean())/denom);fit=y.mean()+slope*centered
            record.update(evaluation_status='evaluated',reason=None,slope_per_minute=slope,
                          predicted_values={p[0]:float(v) for p,v in zip(pairs,fit)},
                          residual_sum_squares=float(np.sum((y-fit)**2)))
        records.append(record)
    return {'model_id':'partial_linear.v1','status':'completed','records':records,
            'interpretation':'linear_trend_comparison_not_peak_or_causal_order', 'prior':'linear_time_trend_with_intercept',
            'input_unit':'protein_adjusted_log2_contrast','observation_imputation':False,
            'default_model_promoted':False,'independent_validation':False}
