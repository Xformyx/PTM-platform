"""Dataset-scoped four-arm evidence; never a project-wide validation flag."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from .annotation_registry import digest
from .astra_inputs import stable_id

VERSION='four_arm_unit_bootstrap.v1.experimental'
ARMS=('vehicle','stimulus','inhibitor','stimulus_plus_inhibitor')
COLUMNS=['validation_id','discovery_run_id','validation_dataset_id','validation_cohort_id','independence_from_discovery',
 'target_id','time','scale','effect_estimate','uncertainty_type','interval_low','interval_high','biological_units',
 'result_status','claim_scope','raw_evidence_hashes','method_version','panel_selection','multiple_testing_policy']
COLUMNS+=['assay_type','site_mapping_evidence','intervention_identity','dose_and_timing','biological_unit_definition','panel_selection_timestamp','independence_provenance']


def import_validation(path):
    if not path:return pd.DataFrame(columns=COLUMNS),{'status':'pending_data','independent_experiment_available':False}
    meta=json.loads(Path(path).read_text())
    required=['dataset_id','cohort_id','discovery_run_id','independence_from_discovery','scale','pairing','panel_selection','observations','assay_type','site_mapping_evidence','intervention_identity','dose_and_timing','biological_unit_definition']
    if any(k not in meta for k in required):raise ValueError('validation_manifest_incomplete')
    if meta['scale'] not in {'A','U','log2_abundance'}:raise ValueError('validation_scale_unsupported')
    if meta.get('baseline_strategy')!='shared_scale_no_arm_specific_baseline':raise ValueError('validation_baseline_estimand_conflict')
    if meta['pairing'] not in {'paired','unpaired'}:raise ValueError('validation_pairing_required')
    data=pd.DataFrame(meta['observations']);required_cols={'target_id','time','arm','biological_unit_id','value'}
    if not required_cols<=set(data):raise ValueError('validation_observation_schema')
    if set(data.arm)-set(ARMS):raise ValueError('validation_unknown_arm')
    if 'scale' in data and not data.scale.eq(meta['scale']).all():raise ValueError('validation_row_scale_conflict')
    if 'baseline_strategy' in data and not data.baseline_strategy.eq(meta['baseline_strategy']).all():raise ValueError('validation_row_baseline_conflict')
    data['value']=pd.to_numeric(data.value,errors='raise')
    if np.isinf(data.value).any():raise ValueError('validation_infinite_measurement')
    if data.biological_unit_id.isna().any():raise ValueError('validation_biological_unit_missing')
    if 'batch' in data and data.batch.nunique()>1:raise ValueError('validation_batch_model_not_implemented')
    if meta['pairing']=='paired' and ('pair_id' not in data or data.pair_id.isna().any()):raise ValueError('validation_pair_id_required')
    if meta['pairing']=='unpaired' and data.groupby('biological_unit_id').arm.nunique().gt(1).any():raise ValueError('shared_units_require_explicit_pairing')
    rows=[];sha=digest(path);rng=np.random.default_rng(1729)
    for (target,time),group in data.groupby(['target_id','time'],dropna=False,sort=True):
        if set(group.arm)!=set(ARMS):raise ValueError('validation_requires_four_arms_at_same_time')
        unit='pair_id' if meta['pairing']=='paired' else 'biological_unit_id'
        if meta['pairing']=='paired' and group.groupby(['pair_id','arm']).biological_unit_id.nunique().gt(1).any():raise ValueError('pair_arm_unit_ambiguous')
        values=group.groupby(['arm',unit]).value.mean();means=values.groupby('arm').mean()
        effect=(means['stimulus_plus_inhibitor']-means['inhibitor'])-(means['stimulus']-means['vehicle'])
        arrays={a:values.loc[a].dropna() for a in ARMS};n=min(map(len,arrays.values()));boots=[]
        if meta['pairing']=='paired':
            common=set.intersection(*(set(a.index) for a in arrays.values()));n=len(common)
            contrasts=np.asarray([arrays[ARMS[3]][k]-arrays[ARMS[2]][k]-arrays[ARMS[1]][k]+arrays[ARMS[0]][k] for k in sorted(common)])
            effect=float(contrasts.mean()) if n else np.nan
            if n>=3:boots=[rng.choice(contrasts,n,replace=True).mean() for _ in range(1000)]
        elif n>=3:
            for _ in range(1000):
                m={a:rng.choice(v.to_numpy(),len(v),replace=True).mean() for a,v in arrays.items()}
                boots.append(m[ARMS[3]]-m[ARMS[2]]-m[ARMS[1]]+m[ARMS[0]])
        ci=np.quantile(boots,[.025,.975]) if boots else [None,None]
        independent=meta['independence_from_discovery']=='confirmed_independent_cohort' and not meta.get('synthetic',False)
        rows.append({'validation_id':stable_id('validation',[sha,target,time,VERSION]),'discovery_run_id':meta['discovery_run_id'],
            'validation_dataset_id':meta['dataset_id'],'validation_cohort_id':meta['cohort_id'],'independence_from_discovery':meta['independence_from_discovery'],
            'target_id':target,'time':time,'scale':meta['scale'],'effect_estimate':effect,
            'uncertainty_type':'biological_unit_percentile_CI' if boots else 'unavailable_insufficient_units',
            'interval_low':ci[0],'interval_high':ci[1],'biological_units':n,'result_status':'independent_assay_evidence' if independent else 'exploratory_not_independent_validation',
            'claim_scope':'intervention_response_not_direct_kinase_site_causality','raw_evidence_hashes':sha,'method_version':VERSION,
            'panel_selection':json.dumps(meta['panel_selection'],sort_keys=True),'multiple_testing_policy':'no_hypothesis_tests_pointwise_CI_not_simultaneous',
            **{k:json.dumps(meta[k],ensure_ascii=False) if isinstance(meta[k],(dict,list)) else meta[k] for k in ['assay_type','site_mapping_evidence','intervention_identity','dose_and_timing','biological_unit_definition']},
            'panel_selection_timestamp':meta.get('panel_selection_timestamp'),'independence_provenance':'provided_manifest_declaration_not_external_verification'})
    return pd.DataFrame(rows,columns=COLUMNS),{'status':'actual_input_imported','independent_experiment_available':any(r['result_status']=='independent_assay_evidence' for r in rows),'manifest_sha256':sha,'synthetic':meta.get('synthetic',False)}
