"""Separate method signals from domain-checked, artifact-backed selective calls."""
from collections import defaultdict
import hashlib
import json
import re
import numpy as np
import pandas as pd
from .astra_inputs import stable_id
from .science_inference import identifiability

VERSION='evidence_resolution.v2'


def validate_policy(artifact,design,resource_hashes):
    if not artifact:return None,'uncalibrated_policy'
    payload={k:v for k,v in artifact.items() if k!='sha256'}
    actual=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    if actual!=artifact.get('sha256'):raise ValueError('calibration_artifact_checksum_invalid')
    required={'policy_id','domain','splits','rules','calibration_metrics','validation_evidence','resource_hashes'}
    if required-set(payload):raise ValueError('calibration_artifact_schema_invalid')
    splits=[set(payload['splits'].get(k,[])) for k in ('development','calibration','held_out')]
    if any(not s for s in splits) or any(splits[i]&splits[j] for i in range(3) for j in range(i+1,3)):
        raise ValueError('calibration_study_split_invalid')
    evidence=payload['validation_evidence'];metrics=payload['calibration_metrics']
    if evidence.get('status')!='evaluated' or not re.fullmatch('[a-f0-9]{64}',str(evidence.get('evaluation_artifact_sha256',''))) or not metrics.get('risk_definition') or metrics.get('truth_evaluable_n',0)<1:
        raise ValueError('calibration_evaluation_evidence_missing')
    study=design['study'];domain=payload['domain']
    taxa={str(t) for t in study.get('expected_sample_taxa',[]) } or {str(study['taxonomy_id'])}
    if not taxa<=set(domain.get('taxa',[])) or study.get('design_axis','time_course') not in domain.get('design_axes',[]) or design['replication_declaration'] not in domain.get('replication',[]):
        return payload,'out_of_calibration_domain'
    if set(payload['resource_hashes'])!=set(resource_hashes):return payload,'calibration_resource_mismatch'
    rules=payload['rules']
    for field in ('minimum_genes','minimum_measurement_groups','minimum_absolute_effect'):
        if not isinstance(rules.get(field),(int,float)) or rules[field]<0:raise ValueError('calibration_rule_invalid')
    if not isinstance(rules.get('reject_reasons'),list) or not rules.get('allowed_tracks'):raise ValueError('calibration_rule_invalid')
    return payload,'calibrated_in_domain'


def evaluate(discovery,temporal,design,artifact=None,resource_hashes=()):
    # Reuse exact same gene/group omission calculation. Replace only the old
    # policy decision; retaining no_call as a legacy projection is not a gate.
    result=identifiability(discovery,temporal,design)
    calls=result['kinase_calls'];members=discovery['substrate_contributions'];edges=discovery['kinase_candidate_edges']
    policy,policy_status=validate_policy(artifact,design,resource_hashes)
    by_call={(stable_id('call',[r.candidate_id,r.contrast_id,r.track,'selective_evidence.v1.experimental'])):r
             for r in discovery['kinase_temporal_profiles'].itertuples()}
    index=defaultdict(set);cross=defaultdict(set);domains={}
    for candidate,g in edges.groupby('candidate_id'):
        domains[candidate]=';'.join(sorted(set(g.kinase_taxon.dropna().astype(str)))) or 'unknown'
    for r in members.itertuples():
        for group in str(r.measurement_group_id).split(';'):
            index[(r.contrast_id,r.track,domains.get(r.candidate_id),group)].add(r.candidate_id)
            cross[(r.contrast_id,group)].add((r.candidate_id,r.track))
    member_index={(candidate,cid,track):g for (candidate,cid,track),g in members.groupby(['candidate_id','contrast_id','track'],sort=False)}
    output=[];dependency=[]
    for row in calls.to_dict('records'):
        p=by_call[row['call_id']];candidate=p.candidate_id;track=p.track;cid=p.contrast_id
        sub=member_index.get((candidate,cid,track),members.iloc[:0])
        groups={g for m in sub.measurement_group_id for g in str(m).split(';')}
        shared={g for g in groups if len(index[(cid,track,domains.get(candidate),g)])>1}
        reasons=set(str(row['no_call_reasons']).split(';'))-{'','uncalibrated_policy','shared_substrate_indistinguishable'}
        localized=bool(len(sub) and 'measurement_status' in sub and sub.measurement_status.isin(['site_localization_supported','run_confidence_supported']).all())
        if localized:reasons.discard('unresolved_site')
        if groups and not groups-shared:reasons.add('shared_substrate_indistinguishable')
        if policy_status!='calibrated_in_domain':reasons.add(policy_status)
        finite=pd.notna(p.activity_magnitude) and np.isfinite(p.activity_magnitude)
        status='not_evaluable' if not len(sub) else 'exploratory_method_signal' if track in {'motif_A','specificity_A'} else 'descriptive_footprint'
        resolution=row['proposed_resolution'];entity_resolution='kinase_family' if resolution=='family' else resolution
        measured='site_localization_supported' if localized and sub.measurement_status.eq('site_localization_supported').all() else 'run_confidence_supported' if localized else 'quantified' if len(sub) else 'ambiguous'
        row.update(track=track,execution_status='completed',measurement_status=measured,
            inference_status=status,entity_resolution=entity_resolution,independent_validation_status='not_performed',
            shared_evidence_ids=';'.join(sub.loc[sub.measurement_group_id.map(lambda m:bool(set(str(m).split(';'))&shared)),'contribution_id']),
            discriminating_evidence_ids=';'.join(sub.loc[sub.measurement_group_id.map(lambda m:bool(set(str(m).split(';'))-shared)),'contribution_id']),
            assay_domain=domains.get(candidate,'unknown'),policy_id=policy['policy_id'] if policy else VERSION,
            calibration_status=policy_status,calibration_artifact_sha256=artifact.get('sha256') if artifact else None,
            no_call_reasons=';'.join(sorted(reasons)))
        if policy_status=='calibrated_in_domain':
            rules=policy['rules'];rejected=set(rules['reject_reasons'])&reasons
            if len(groups)<rules['minimum_measurement_groups'] or sub.substrate_gene.nunique()<rules['minimum_genes']:rejected.add('insufficient_measurements')
            if not finite or abs(p.activity_magnitude)<rules['minimum_absolute_effect']:rejected.add('effect_below_policy')
            if track not in rules['allowed_tracks'] or resolution not in {'kinase','family'}:rejected.add('unsupported_resolution_or_track')
            if rejected:row.update(inference_status='abstained',no_call_reasons=';'.join(sorted(rejected)))
            else:row.update(resolution=resolution,entity_id=candidate,inference_status='calibrated_inference',no_call_reasons='')
        row['call_id']=stable_id('call_v2',[candidate,cid,track,row['policy_id'],row['calibration_artifact_sha256']])
        output.append(row)
        for group in sorted(groups):
            dependency.append({'dependency_id':stable_id('dependency',[candidate,cid,track,group]),'candidate_id':candidate,
                'contrast_id':cid,'track':track,'measurement_group_id':group,'assay_domain':domains.get(candidate,'unknown'),
                'shared_candidate_ids':';'.join(sorted(index[(cid,track,domains.get(candidate),group)])),
                'cross_track_uses':json.dumps(sorted(cross[(cid,group)])), 'independent_vote_count':1})
    extra=['track','execution_status','measurement_status','inference_status','entity_resolution','independent_validation_status','assay_domain']
    result['kinase_calls']=pd.DataFrame(output,columns=list(calls.columns)+extra)
    result['inference_results']=result['kinase_calls'].copy()
    result['calibrated_calls']=result['kinase_calls'].loc[result['kinase_calls'].inference_status.eq('calibrated_inference')].copy()
    result['evidence_dependency_groups']=pd.DataFrame(dependency,columns=['dependency_id','candidate_id','contrast_id','track','measurement_group_id','assay_domain','shared_candidate_ids','cross_track_uses','independent_vote_count'])
    result['calibration_provenance']=pd.DataFrame([{'policy_id':policy['policy_id'] if policy else VERSION,
        'artifact_json':json.dumps(artifact or {},sort_keys=True,allow_nan=False),'domain_status':policy_status,
        'artifact_sha256':artifact.get('sha256') if artifact else None,'resource_hashes_json':json.dumps(sorted(resource_hashes)),
        'claim_scope':'artifact-backed_selective_policy_not_independent_experiment'}])
    return result
