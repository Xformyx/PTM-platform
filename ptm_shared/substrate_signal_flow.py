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
            feature_valid = feature is not None and all(p['included'] for p in points if p['source_ref'])
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
