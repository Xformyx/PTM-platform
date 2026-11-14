"""Read-only, whole-population views of saved substrate signal evidence.

No estimator, selection, identity inference or relationship registry is run here.
Sources retain their canonical keys; projection IDs live in a separate namespace.
"""
from collections import defaultdict
import json
import math

import pandas as pd

from .astra_card_inputs import clean, encode, ids
from .astra_inputs import stable_id
from .astra_evidence_catalog import evidence_id_for
from .effect_series import resolve_series

VERSION = 'substrate_signal_flow.v1'
TRACKS = ('U_joint', 'P_joint', 'A', 'U_all', 'P_all')
TRAJECTORIES = 'signal_flow/substrate_trajectories'
MEMBERS = 'signal_flow/substrate_bundle_membership'
TABLE_KEYS = {TRAJECTORIES: ['trajectory_id'], MEMBERS: ['membership_id']}
KINASES = 'signal_flow/kinase_substrate_bundles'
KINASE_MEMBERS = 'signal_flow/kinase_substrate_membership'
TABLE_KEYS.update({KINASES: ['bundle_id'], KINASE_MEMBERS: ['membership_id']})
LINKS = 'signal_flow/temporal_evidence_links'
HYPOTHESES = 'signal_flow/downstream_hypotheses'
TABLE_KEYS.update({LINKS: ['link_id'], HYPOTHESES: ['hypothesis_id']})


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class Sources:
    """Validated in-memory view of the existing dictionary, not a new registry."""
    def __init__(self, tables, registry):
        self.tables = tables
        self.registry = registry
        self.checked = set()

    def rows(self, name):
        if name not in self.tables:
            return []
        frame = self.tables[name]
        descriptor = self.registry.get(name + '.csv', {})
        keys = descriptor.get('unique_key')
        if not keys or not set(keys) <= set(frame):
            raise ValueError('Signal source has no canonical key: ' + name)
        if name not in self.checked:
            if frame[keys].isna().any().any() or frame.duplicated(keys).any():
                raise ValueError('Duplicate or null signal source key: ' + name)
            self.checked.add(name)
        return clean(frame.to_dict('records'))

    def ref(self, name, row):
        meta = self.registry[name + '.csv']
        key = {k: row[k] for k in meta['unique_key']}
        return {'source_table': name + '.csv', 'source_key': key,
                'evidence_id': evidence_id_for(name + '.csv', key),
                'source_sha256': meta.get('sha256'),
                'source_hash_status': 'recorded' if meta.get('sha256') else 'unavailable',
                'source_schema_version': meta.get('descriptor_schema_version')}


def legacy_crosswalk(feature, members, identities):
    """Only explicit source/precursor/sequence/taxon evidence can join the two IDs."""
    required = ('source_file_sha256', 'source_row', 'precursor_id', 'modified_sequence', 'taxon')
    if any(feature.get(k) is None for k in required):
        return {'status': 'unavailable', 'form_ids': [], 'reason': 'exact_source_identity_missing'}
    matches = set()
    for row in members:
        identity = identities.get(row['form_id'], {})
        if (all(str(feature[k]) == str(row.get(k)) for k in required if k != 'taxon')
                and identity.get('taxa') == [str(feature['taxon'])]):
            matches.add(row['form_id'])
    return {'status': 'verified' if len(matches) == 1 else 'ambiguous' if matches else 'unavailable',
            'form_ids': sorted(matches), 'reason': 'exact_source_precursor_sequence_taxon_only'}


def trajectory_projection(tables, design, registry):
    source = Sources(tables, registry)
    scopes, lookup = resolve_series(design)
    identity_rows = source.rows('reader_adapter/form_identity')
    identities = {r['form_id']: json.loads(r['identity_json']) for r in identity_rows}
    identity_refs = {r['form_id']: source.ref('reader_adapter/form_identity', r) for r in identity_rows}
    features = {(r['entity_id'], r['series_id'], r['track']): r
                for r in source.rows('temporal/ptm_temporal_features')}
    by_form_scope = defaultdict(dict)
    for r in source.rows('quant/comparisons'):
        sid = lookup.get(r['contrast_id'])
        if sid is None:
            raise ValueError('Comparison outside executed canonical design: ' + r['contrast_id'])
        by_form_scope[r['form_id'], sid][r['contrast_id']] = r
    trajectories, members = [], []
    for (fid, sid), comparisons in sorted(by_form_scope.items()):
        for track in TRACKS:
            if not any(track in r for r in comparisons.values()):
                continue
            tid = stable_id('substrate_trajectory', [VERSION, fid, sid, track])
            points = []
            for point in scopes[sid]['points']:
                r = comparisons.get(point['contrast_id'])
                included = r is not None and r.get('included') is True
                value = r.get(track) if r else None
                eligible = included and finite(value)
                points.append({**point, 'value': value if eligible else None,
                    'calculation_trace_value': value, 'included': included, 'eligible': eligible,
                    'status': 'observed' if eligible else 'excluded' if r and not included else 'unobserved',
                    'reasons': r.get('exclusion_reasons') if r else 'comparison_missing',
                    'source_ref': source.ref('quant/comparisons', r) if r else None,
                    'reference_joint_run_ids': r.get('reference_joint_run_ids') if r else None,
                    'target_joint_run_ids': r.get('target_joint_run_ids') if r else None})
            feature = features.get((fid, sid, track))
            # Features are saved diagnostics. Never recompute them or attach a
            # shape based on finite-but-excluded calculation traces.
            feature_valid = False
            if feature is not None:
                saved_values = json.loads(feature.get('values') or '[]')
                saved_times = json.loads(feature.get('times_minutes') or '[]')
                feature_valid = saved_times == [p['time_min'] for p in points] and len(saved_values) == len(points) and all(
                    (v is None and p['value'] is None) or (finite(v) and finite(p['value']) and math.isclose(v,p['value'],abs_tol=1e-12))
                    for v,p in zip(saved_values,points))
            feature_refs = [source.ref('temporal/ptm_temporal_features', feature)] if feature_valid else []
            pattern = feature.get('pattern') if feature_valid else None
            status = 'saved_feature' if feature_valid else 'unavailable_or_excluded_feature_scope'
            bundle = stable_id('substrate_pattern_bundle', [VERSION, sid, track, pattern, status])
            trajectories.append({'trajectory_id': tid, 'form_id': fid, 'effect_series_id': sid,
                'track': track, 'unit': 'log2_ratio', 'identity_json': encode(identities.get(fid, {})),
                'identity_ref_json': encode(identity_refs.get(fid)), 'points_json': encode(points),
                'feature_refs_json': encode(feature_refs), 'feature_status': status,
                'feature_json': encode(feature if feature_valid else None), 'pattern': pattern,
                'eligible_points': sum(p['eligible'] for p in points),
                'registered_points': len(points), 'legacy_crosswalk_status': 'unavailable_without_exact_crosswalk',
                'scope_json': encode({k: v for k, v in scopes[sid].items() if k != 'points'}),
                'schema_version': VERSION})
            members.append({'membership_id': stable_id('substrate_bundle_member', [bundle, tid]),
                'bundle_id': bundle, 'trajectory_id': tid, 'effect_series_id': sid, 'track': track,
                'pattern': pattern, 'status': status, 'meaning': 'shape_group_not_common_kinase_or_pathway'})
    return {TRAJECTORIES: pd.DataFrame(trajectories, columns=[
        'trajectory_id','form_id','effect_series_id','track','unit','identity_json','identity_ref_json',
        'points_json','feature_refs_json','feature_status','feature_json','pattern','eligible_points',
        'registered_points','legacy_crosswalk_status','scope_json','schema_version']),
        MEMBERS: pd.DataFrame(members, columns=['membership_id','bundle_id','trajectory_id',
            'effect_series_id','track','pattern','status','meaning'])}


def kinase_projection(tables, design, registry, trajectories):
    """Expose saved scores side by side; never reweight or rank substrates."""
    source = Sources(tables, registry)
    scopes, lookup = resolve_series(design)
    trajectories = trajectories.to_dict('records')
    trajectory_ids = {(r['form_id'], r['effect_series_id'], r['track']): r['trajectory_id'] for r in trajectories}
    edges = {r['edge_id']: r for r in source.rows('kinase/kinase_candidate_edges')}
    names = ['kinase/substrate_contributions', 'kinase/kinase_temporal_profiles',
             'temporal/kinase_fixed_membership', 'temporal/target_excluded_anchors',
             'kinase/candidate_sensitivity', 'science/inference_results',
             'kinase/method_scores', 'kinase/method_membership']
    rows = {name: source.rows(name) for name in names}
    groups = defaultdict(lambda: defaultdict(list))
    method_scopes = defaultdict(set)
    for r in rows['kinase/method_scores']:
        method_scopes[r.get('candidate_id'), r.get('contrast_id'), r.get('method_id')].add(
            'method:' + encode([r.get('method_id'), r.get('method_version'), r.get('score_name')]))
    for name in names:
        for r in rows[name]:
            candidate = r.get('candidate_id') or r.get('proposed_entity_id')
            sid = lookup.get(r.get('contrast_id') or r.get('contrast_or_window_id')) or r.get('series_id')
            if not candidate or sid not in scopes:
                continue  # source availability below records unbound rows
            track = r.get('track')
            if name.startswith('kinase/method_'):
                tracks = (['method:' + encode([r.get('method_id'),r.get('method_version'),r.get('score_name')])]
                          if name == 'kinase/method_scores' else
                          sorted(method_scopes[candidate,r.get('contrast_id'),r.get('method_id')]) or
                          ['method:' + encode([r.get('method_id'),None,None])])
            else:
                tracks = [track or 'unrecorded']
            for scope_track in tracks:
                groups[candidate, sid, scope_track][name].append(r)
    # Priors without an evaluated footprint remain accessible, not a score=0.
    form_scopes = defaultdict(set)
    for r in trajectories:
        if r['track'] == 'A': form_scopes[r['form_id']].add(r['effect_series_id'])
    candidate_scopes = {(k[0], k[1]) for k in groups}
    by_candidate = defaultdict(list)
    for edge in edges.values():
        by_candidate[edge['candidate_id']].append(edge)
        for sid in form_scopes[edge['form_id']]:
            if (edge['candidate_id'], sid) not in candidate_scopes:
                groups[edge['candidate_id'], sid, 'uncomputed']
    bundles, members = [], []
    for (candidate, sid, track), sources in sorted(groups.items()):
        bid = stable_id('kinase_substrate_bundle', [VERSION, candidate, sid, track])
        form_ids, site_ids, genes, measurement_groups = set(), set(), set(), set()
        evidence_edges = set()
        supports = []
        for name in ('kinase/substrate_contributions', 'kinase/method_membership'):
            for row in sources.get(name, []):
                linked_edges = ids(row.get('edge_ids'))
                if any(e not in edges or edges[e]['candidate_id'] != candidate for e in linked_edges):
                    raise ValueError('Contribution edge FK mismatch')
                forms = ids(row.get('form_ids'))
                if any(edges[e]['form_id'] not in forms for e in linked_edges):
                    raise ValueError('Contribution form/edge FK mismatch')
                evidence_edges.update(linked_edges)
                form_ids.update(forms); site_ids.update(ids(row.get('site_ids')))
                genes.update(ids(row.get('substrate_gene')))
                if row.get('measurement_group_id'): measurement_groups.add(row['measurement_group_id'])
                membership_id = stable_id('kinase_bundle_member', [bid, source.ref(name, row)['source_key']])
                supports.append(row)
                members.append({'membership_id': membership_id, 'bundle_id': bid, 'candidate_id': candidate,
                    'effect_series_id': sid, 'contrast_id': row.get('contrast_id'), 'track': track,
                    'form_ids_json': encode(forms), 'trajectory_ids_json': encode([trajectory_ids[f,sid,'A'] for f in forms if (f,sid,'A') in trajectory_ids]),
                    'edge_refs_json': encode([source.ref('kinase/kinase_candidate_edges', edges[e]) for e in linked_edges]),
                    'source_ref_json': encode(source.ref(name,row)), 'saved_values_json': encode(row),
                    'meaning': 'saved_method_dependency_not_independent_validation'})
        available_forms = {r['form_id'] for r in trajectories if r['effect_series_id'] == sid}
        prior_edges = [e for e in by_candidate[candidate] if e['form_id'] in available_forms]
        evidence_edges.update(e['edge_id'] for e in prior_edges)
        prior_forms = {e['form_id'] for e in prior_edges}
        points = []
        for i, point in enumerate(scopes[sid]['points']):
            cid = point['contrast_id']
            at_point = [r for r in supports if r.get('contrast_id') == cid]
            points.append({**point,
                'contributing_form_count': len({f for r in at_point for f in ids(r.get('form_ids'))}),
                'contributing_site_count': len({s for r in at_point for s in ids(r.get('site_ids'))}),
                'contributing_gene_count': len({g for r in at_point for g in ids(r.get('substrate_gene'))}),
                'contributing_measurement_group_count': len({r['measurement_group_id'] for r in at_point if r.get('measurement_group_id')}),
                'membership_event_meaning': 'initial_membership_not_emergence' if i == 0 else 'saved_membership_turnover',
                'saved_results': {name: [{'values': r, 'source_ref': source.ref(name,r)} for r in group if r.get('contrast_id') == cid]
                                  for name, group in sources.items() if name not in ('kinase/substrate_contributions','kinase/method_membership')}})
        diagnostic = {name: [{'values': r, 'source_ref': source.ref(name,r)} for r in group]
                      for name, group in sources.items() if name in ('temporal/target_excluded_anchors','science/inference_results')}
        bundles.append({'bundle_id': bid, 'candidate_id': candidate, 'effect_series_id': sid, 'track': track,
            'association_form_count': len(prior_forms | form_ids), 'contributing_form_count': len(form_ids),
            'site_count': len(site_ids), 'gene_count': len(genes), 'measurement_group_count': len(measurement_groups),
            'independent_validation_count': None, 'family_label': None,
            'edge_refs_json': encode([source.ref('kinase/kinase_candidate_edges',edges[e]) for e in sorted(evidence_edges)]),
            'edges_json': encode([edges[e] for e in sorted(evidence_edges)]),
            'points_json': encode(points), 'diagnostics_json': encode(diagnostic),
            'fixed_membership_status': 'recorded' if sources.get('temporal/kinase_fixed_membership') else 'unavailable',
            'source_availability_json': encode({name: 'available' if name in tables else 'unavailable' for name in names}),
            'support_signature_json': encode(sorted({encode([r.get('contrast_id'),r.get('measurement_group_id'),
                sorted(ids(r.get('form_ids'))),sorted(ids(r.get('site_ids')))]) for r in supports})),
            'interpretation': 'exploratory_substrate_association_not_calibrated_activity', 'schema_version': VERSION})
    indistinguishable = defaultdict(list)
    for b in bundles:
        if json.loads(b['support_signature_json']):
            indistinguishable[b['effect_series_id'],b['track'],b['support_signature_json']].append(b['candidate_id'])
    for b in bundles:
        candidates = indistinguishable[b['effect_series_id'],b['track'],b['support_signature_json']]
        b['indistinguishable_candidates_json'] = encode(sorted(set(candidates)) if len(set(candidates)) > 1 else [])
        b['identifiability_status'] = 'identical_saved_support_not_family' if len(set(candidates)) > 1 else 'not_established_by_this_projection'
    return {KINASES: pd.DataFrame(bundles, columns=['bundle_id','candidate_id','effect_series_id','track',
        'association_form_count','contributing_form_count','site_count','gene_count','measurement_group_count',
        'independent_validation_count','family_label','edge_refs_json','edges_json','points_json','diagnostics_json',
        'fixed_membership_status','source_availability_json','support_signature_json','interpretation','schema_version',
        'indistinguishable_candidates_json','identifiability_status']),
        KINASE_MEMBERS: pd.DataFrame(members, columns=['membership_id','bundle_id','candidate_id','effect_series_id',
            'contrast_id','track','form_ids_json','trajectory_ids_json','edge_refs_json','source_ref_json','saved_values_json','meaning'])}


def observed_order(left, right):
    """A bracket comparison, not an onset estimator or a causal test."""
    if not left or not right:
        return 'not_evaluable', 'saved_feature_unavailable'
    if left.get('onset_left_censored') or right.get('onset_left_censored'):
        return 'unresolved', 'left_censored_onset'
    bounds = [left.get('onset_lower_min'),left.get('onset_upper_min'),right.get('onset_lower_min'),right.get('onset_upper_min')]
    if not all(finite(v) for v in bounds):
        return 'not_evaluable', 'onset_bracket_missing'
    if bounds[1] < bounds[2]: return 'observed_before', 'separated_saved_onset_brackets'
    if bounds[3] < bounds[0]: return 'observed_after', 'separated_saved_onset_brackets'
    return 'unresolved', 'overlapping_or_same_sampled_bin'


def evidence_map(projections):
    """Typed existing dependencies/priors plus bounded, reviewable hypotheses.

    No benchmark registry, inferred kinase direction, lag model, or new score.
    Adjacent observed brackets within an existing candidate support set provide
    timeline navigation; absence of a link is not absence of a biological relation.
    """
    trajectories = projections[TRAJECTORIES].to_dict('records')
    by_id = {r['trajectory_id']: r for r in trajectories}
    by_form = {(r['form_id'],r['effect_series_id']): r for r in trajectories if r['track']=='A'}
    links, hypotheses = {}, []
    def link(kind, start, end, sid, refs, *, status='linked', reason=None, biological=False):
        lid = stable_id('signal_evidence_link',[VERSION,kind,start,end,sid,refs])
        links[lid] = {'link_id':lid,'edge_type':kind,'from_id':start,'to_id':end,'effect_series_id':sid,
            'source_refs_json':encode(refs),'status':status,'reason':reason,
            'direction_meaning':'recorded_prior_not_current_experiment_causality' if biological else 'membership_or_observed_dependency_not_regulation',
            'causality_status':'not_established'}
        return lid
    for m in projections[MEMBERS].to_dict('records'):
        r=by_id[m['trajectory_id']]
        link('bundle_member',m['bundle_id'],m['trajectory_id'],m['effect_series_id'],
             [p['source_ref'] for p in json.loads(r['points_json']) if p['source_ref']])
    members=defaultdict(list)
    for m in projections[KINASE_MEMBERS].to_dict('records'):
        members[m['bundle_id']].append(m)
        for tid in json.loads(m['trajectory_ids_json']):
            link('method_contribution',tid,m['bundle_id'],m['effect_series_id'],[json.loads(m['source_ref_json'])])
    for b in projections[KINASES].to_dict('records'):
        sid=b['effect_series_id']; refs=json.loads(b['edge_refs_json']); edges=json.loads(b['edges_json'])
        related={}
        prior_ids=[]; prior_checks=[]
        for edge,ref in zip(edges,refs):
            t=by_form.get((edge['form_id'],sid))
            if not t: continue
            related[t['trajectory_id']]=t
            link('candidate_association',t['trajectory_id'],b['bundle_id'],sid,[ref])
            exact=(edge.get('edge_type')=='curated_exact_site_native'
                and edge.get('site_mapping_status') in ('unique','single_gene_consistent_coordinates','single_gene_isoform_coordinates')
                and edge.get('directness')=='site_relation_recorded'
                and edge.get('candidate_accession') and edge.get('input_accession')
                and edge.get('substrate_taxon') is not None and edge.get('kinase_taxon') is not None
                and edge.get('evidence_record_ids'))
            if exact:
                prior_ids.append(link('curated_enzyme_substrate_prior',b['bundle_id'],t['trajectory_id'],sid,[ref],
                    reason='exact_recorded_site_prior; localization_and_experimental_context_limits_remain', biological=True))
                for upstream in by_form.values():
                    identity=json.loads(upstream['identity_json'])
                    taxa=identity.get('taxa',[])
                    taxon=str(int(edge['kinase_taxon'])) if finite(edge['kinase_taxon']) else str(edge['kinase_taxon'])
                    if (upstream['effect_series_id']!=sid or upstream['trajectory_id']==t['trajectory_id']
                            or identity.get('protein_group')!=edge['candidate_accession'] or taxa!=[taxon]):
                        continue
                    order,reason=observed_order(json.loads(upstream['feature_json']),json.loads(t['feature_json']))
                    prior_checks.append({'upstream_observation_id':upstream['trajectory_id'],
                        'target_observation_id':t['trajectory_id'],'prior_source_ref':ref,
                        'observation_source_refs':json.loads(upstream['feature_refs_json'])+json.loads(t['feature_refs_json']),
                        'consistency':'consistent' if order=='observed_before' else 'inconsistent' if order=='observed_after' else 'not_evaluable',
                        'reason':reason,'meaning':'measured_form_response_order_not_kinase_activation_order',
                        'prior_falsified':False})
        ordered=sorted(related.values(),key=lambda r:(
            (json.loads(r['feature_json']) or {}).get('onset_upper_min') is None,
            (json.loads(r['feature_json']) or {}).get('onset_upper_min') or 0,r['trajectory_id']))
        order_links=[]
        for left,right in zip(ordered,ordered[1:]):
            status,reason=observed_order(json.loads(left['feature_json']),json.loads(right['feature_json']))
            order_links.append(link('observed_before',left['trajectory_id'],right['trajectory_id'],sid,
                json.loads(left['feature_refs_json'])+json.loads(right['feature_refs_json']),status=status,reason=reason))
            li=json.loads(left['identity_json']);ri=json.loads(right['identity_json'])
            if li.get('protein_group') and li.get('protein_group')==ri.get('protein_group'):
                link('same_parent_mathematical_dependence',left['trajectory_id'],right['trajectory_id'],sid,
                    [json.loads(left['identity_ref_json']),json.loads(right['identity_ref_json'])],reason='shared_parent_adjustment_not_independent_validation')
        hid=stable_id('signal_hypothesis',[VERSION,b['bundle_id']])
        hypotheses.append({'hypothesis_id':hid,'bundle_id':b['bundle_id'],'effect_series_id':sid,
            'kind':'substrate_temporal_association_hypothesis','status':'review_required',
            'trajectory_ids_json':encode(sorted(related)), 'prior_link_ids_json':encode(prior_ids),
            'order_link_ids_json':encode(order_links),'prior_status':'recorded_exact_site_prior' if prior_ids else 'missing_exact_prior',
            'prior_observation_checks_json':encode(prior_checks),
            'temporal_consistency':'not_evaluable_kinase_activity_onset_not_observed',
            'counterevidence_json':encode({'indistinguishable_candidates':json.loads(b['indistinguishable_candidates_json']),
                'saved_diagnostics':json.loads(b['diagnostics_json']), 'points':json.loads(b['points_json'])}),
            'alternatives_json':encode(['phosphatase/accessibility/localization/turnover','shared_control_and_normalization',
                'parent_protein_adjustment','changing_membership','shared_substrate_not_independent_cascade']),
            'required_validation_json':encode(['candidate_specific_perturbation','direct_assay','denser_time_sampling_where_brackets_overlap']),
            'causality_status':'not_established','semantic_review_status':'not_performed'})
    return {LINKS:pd.DataFrame(list(links.values()),columns=['link_id','edge_type','from_id','to_id','effect_series_id',
            'source_refs_json','status','reason','direction_meaning','causality_status']),
        HYPOTHESES:pd.DataFrame(hypotheses,columns=['hypothesis_id','bundle_id','effect_series_id','kind','status',
            'trajectory_ids_json','prior_link_ids_json','order_link_ids_json','prior_status','temporal_consistency',
            'prior_observation_checks_json','counterevidence_json','alternatives_json','required_validation_json','causality_status','semantic_review_status'])}


def project_signal_flow(tables, design, registry):
    result=trajectory_projection(tables,design,registry)
    result.update(kinase_projection(tables,design,registry,result[TRAJECTORIES]))
    result.update(evidence_map(result))
    return result
