"""Lossless projection to the existing precursor-card input contract.

No card selection, normalization, aggregation, localization inference or writer
execution lives here. Unrepresentable forms remain in the exported audit rows.
"""
import json
import math
from pathlib import Path

import pandas as pd

from .annotation_registry import digest
from .astra_inputs import stable_id
from .evidence_contracts import build_measurement_provenance
from .feature_identity import canonical_feature_identity, project_reader_display_identity
from .study_metadata import build_study_metadata_contract

VERSION = 'astra_card_input.v1'
TABLE_KEYS = {
    'reader_adapter/form_identity': ['form_id'],
    'reader_adapter/form_contrasts': ['adapter_row_id'],
    'reader_adapter/precursor_membership': ['membership_id'],
    'reader_adapter/study_metadata': ['metadata_id'],
}
MEMBER_COLUMNS = ['membership_id', 'form_id', 'source_file_sha256', 'source_row',
                  'precursor_id', 'charge', 'protein_group', 'modified_sequence',
                  'observed_injection_ids_json', 'schema_version']


def clean(value):
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if pd.isna(value):
        return None
    return value.item() if hasattr(value, 'item') else value


def encode(value):
    return json.dumps(clean(value), ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def ids(value):
    return str(value).split(';') if value is not None and not pd.isna(value) and str(value) else []


def precursor_membership(path, summary, design):
    """Exact existing quantification group key; do not rebuild or merge form IDs."""
    result = []
    if path is None:
        return pd.DataFrame(columns=MEMBER_COLUMNS)
    keys = {(r['Protein.Group'], r['Modified.Sequence']): r['form_id'] for r in summary.to_dict('records')}
    sha = digest(Path(path))
    injections = {s['input_column']: s['injection_id'] for s in design['injections']}
    required = {'Protein.Group', 'Modified.Sequence', 'Precursor.Id', 'Precursor.Charge'}
    header = pd.read_csv(path, sep='\t', nrows=0)
    if not required <= set(header):
        raise ValueError('card_adapter_missing_precursor_columns')
    offset = 0
    for chunk in pd.read_csv(path, sep='\t', usecols=lambda c: c in required or c in injections, chunksize=20000):
        for i, row in enumerate(chunk.to_dict('records'), offset + 1):
            fid = keys.get((row['Protein.Group'], row['Modified.Sequence']))
            if fid is None:
                continue
            observed = [sid for column, sid in injections.items()
                        if pd.notna(row.get(column)) and float(row[column]) > 0]
            result.append({'membership_id': stable_id('card_member', [sha, i, fid]), 'form_id': fid,
                           'source_file_sha256': sha, 'source_row': i,
                           'precursor_id': row['Precursor.Id'], 'charge': row['Precursor.Charge'],
                           'protein_group': row['Protein.Group'], 'modified_sequence': row['Modified.Sequence'],
                           'observed_injection_ids_json': encode(sorted(observed)), 'schema_version': VERSION})
        offset += len(chunk)
    return pd.DataFrame(result, columns=MEMBER_COLUMNS)


def metadata_packet(design, context, snapshot):
    original = (snapshot or {}).get('original', {})
    raw = original.get('analysis_context', {})
    # The legacy resolver sees the recorded fields, never invented dose or hardware.
    source = raw if snapshot is not None else {k: v for k, v in context.items() if not k.startswith('_')}
    resolved = dict(source)
    projection_sources = {k: 'study/user_input_snapshot.json#/original/analysis_context/' + k for k in source}
    fallbacks = {'organism': original.get('species', design.get('study', {}).get('species')),
                 'replicate_semantics': design.get('replication_declaration')}
    for key, value in fallbacks.items():
        aliases = ('organism','host_organism','species','taxonomy') if key == 'organism' else ('replicate_semantics','replicate_type','replicate_design')
        if value is not None and not any(source.get(k) is not None for k in aliases):
            resolved[key] = value
            projection_sources[key] = ('study/user_input_snapshot.json#/original/species' if key == 'organism' and 'species' in original
                                       else 'study/study_design.json#/' + ('study/species' if key == 'organism' else 'replication_declaration'))
    contract = build_study_metadata_contract(resolved)
    materials = {m['material_id']: m for m in design.get('materials', [])}
    samples = []
    for s in design.get('injections', []):
        m = materials.get(s.get('material_id'), {})
        samples.append({**s, 'sample_id': s['injection_id'], 'biological_unit': m.get('biological_unit_id'),
                        'pair_id': m.get('pair_id')})
    conflicts = list(design.get('metadata_conflicts', []))
    for key, value in source.items():
        if key in design.get('study', {}) and clean(value) != clean(design['study'][key]):
            conflicts.append({'field': key, 'raw': value, 'canonical': design['study'][key],
                              'status': 'raw_canonical_difference_preserved'})
    return {'contract': contract, 'recorded_context': source, 'contract_input_sources': projection_sources,
            'snapshot_ref': 'study/user_input_snapshot.json#/original/analysis_context',
            'snapshot_status': 'provided' if snapshot is not None else 'unavailable_context_fallback',
            'canonical_study': design.get('study', {}), 'arms': design.get('arms', []),
            'conditions': design.get('conditions', []), 'contrasts': design.get('contrasts', []),
            'replication_declaration': design.get('replication_declaration'),
            'field_provenance': design.get('field_provenance', {}), 'conflicts': conflicts,
            'sample_manifest': {'samples': samples},
            'source_paths': ['study/user_input_snapshot.json', 'study/study_design.json'],
            'adapter_scope': 'input_projection_only_no_findings_no_new_statistics'}


def project_card_inputs(tables, inputs, design, context, snapshot=None):
    summary = tables['quant/summary']
    members = precursor_membership(inputs.get('PR'), summary, design)
    member_groups = {f: g.to_dict('records') for f, g in members.groupby('form_id', sort=False)}
    sites = {f: clean(g.to_dict('records')) for f, g in tables['science/site_identity_audit'].groupby('form_id', sort=False)}
    loc = {k: clean(g.to_dict('records')) for k, g in tables['science/localization_by_contrast'].groupby(['form_id', 'contrast_id'], sort=False)}
    identities, identity_rows = {}, []
    for raw in summary.to_dict('records'):
        form = clean(raw); fid = form['form_id']; group = member_groups.get(fid, [])
        mappings = sites.get(fid, [])
        taxa = sorted({str(int(s['substrate_taxon'])) for s in mappings if s.get('substrate_taxon') is not None})
        reasons = []
        if len(group) != int(form['precursor_count']): reasons.append('precursor_membership_count_mismatch')
        if len(group) != 1: reasons.append('multiple_precursors_not_representable' if len(group) > 1 else 'precursor_membership_unavailable')
        if len(taxa) != 1 or any(s.get('substrate_taxon') is None for s in mappings):
            reasons.append('mixed_or_unknown_taxon_not_representable')
        gene = form.get('Genes')
        if not gene or len(ids(gene)) != 1: reasons.append('gene_display_ambiguous_or_unavailable')
        single = clean(group[0]) if len(group) == 1 else {}
        row = {'form_id': fid, 'gene': gene, 'position': form.get('representative_sites'),
               'protein_group': form['Protein.Group'], 'modified_sequence': form['Modified.Sequence'],
               'precursor_id': single.get('precursor_id'), 'precursor_charge': single.get('charge'),
               'fasta_taxonomy_id': taxa[0] if len(taxa) == 1 else None,
               'measurement_group_ids': sorted({s['measurement_group_id'] for s in mappings}),
               'taxa': taxa, 'mapping_ids': [s['identity_id'] for s in mappings],
               'membership_ids': [m['membership_id'] for m in group],
               'mapping_status': form['mapping_status'], 'localization_probability': None}
        identity = canonical_feature_identity(row)
        if not identity['identity_complete_for_reader_cards']: reasons.append('precursor_identity_unavailable')
        measurement = build_measurement_provenance(row, feature_id=single.get('precursor_id'),
            member_feature_ids=[m['precursor_id'] for m in group if m.get('precursor_id')],
            aggregation_rule='existing_form_quantification_projection_no_reaggregation')
        measurement['feature_entity'] = 'quantified_form'
        measurement['form_id'] = fid
        measurement['localization_evidence'] = {'status': 'see_contrast_localization_records', 'probability': None,
                                               'reason': 'no_form_wide_probability_derived'}
        row.update(measurement_provenance=measurement, identity=identity,
                   display_label=project_reader_display_identity(row, reader_measurement_unit=measurement['reader_measurement_unit']),
                   adapter_restrictions=sorted(set(reasons)))
        identities[fid] = row
        identity_rows.append({'form_id': fid, 'schema_version': VERSION, 'identity_json': encode(row),
                              'summary_json': encode(form), 'site_mappings_json': encode(mappings)})
    rows = []
    for raw in tables['quant/comparisons'].to_dict('records'):
        c = clean(raw); fid = c['form_id']; cid = c['contrast_id']
        # CSV caches read an empty reason/mask cell as NA. Canonicalize only
        # these optional table cells so fresh and cached projections replay alike.
        for key in ['exclusion_reasons','reference_joint_run_ids','target_joint_run_ids']:
            if c.get(key) == '': c[key] = None
        identity = identities[fid]; localization = loc.get((fid, cid), [])
        restrictions = list(identity['adapter_restrictions'])
        if not c['included']: restrictions.append('quant_comparison_excluded')
        # One consumer state per form/arm/reference/pairing. No gene-key pooling.
        state_id = stable_id('card_state', [fid, c['arm_id'], c['reference_condition_id'], c['pairing']])
        row = {**identity, **c, 'condition': f"{c['target_label']} vs {c['reference_label']} [{cid}]",
               'time_minutes': c['time_min'], 'reference_time_minutes': c['reference_time_min'],
               'reference_id': c['reference_condition_id'], 'unadjusted_source_field': 'quant/comparisons.U_joint',
               'localization_ids': [r['localization_id'] for r in localization],
               'localization_status': sorted({r['measurement_status'] for r in localization}),
               'source_refs': {'summary': {'table': 'quant/summary.csv', 'form_id': fid},
                               'comparison': {'table': 'quant/comparisons.csv', 'form_id': fid, 'contrast_id': cid},
                               'runlevel': {'table': 'quant/runlevel.csv', 'form_id': fid,
                                            'injection_ids': ids(c['reference_joint_run_ids']) + ids(c['target_joint_run_ids'])}},
               'adapter_restrictions': sorted(set(restrictions))}
        for axis, source in [('ptm_unadjusted', 'U_joint'), ('protein', 'P_joint'), ('ptm_protein_adjusted', 'A')]:
            row.update({f'{axis}_log2fc': c[source], f'{axis}_method': c['estimator_version'],
                        f'{axis}_estimator_id': c['estimator_version'], f'{axis}_statistical_unit': c['statistical_unit'],
                        f'{axis}_test_status': c['inference_status'], f'{axis}_p_value': None, f'{axis}_q_value': None,
                        f'{axis}_missing_reason': c['exclusion_reasons'] if c[source] is None else None,
                        f'{axis}_control_sample_ids': ids(c['reference_joint_run_ids']),
                        f'{axis}_treatment_sample_ids': ids(c['target_joint_run_ids']),
                        f'{axis}_control_n': c['reference_joint_n'], f'{axis}_treatment_n': c['target_joint_n']})
        rows.append({'adapter_row_id': stable_id('card_row', [VERSION, fid, cid]), 'form_id': fid,
                     'contrast_id': cid, 'consumer_state_id': state_id, 'card_input_eligible': not restrictions,
                     'restriction_reasons': ';'.join(sorted(set(restrictions))), 'schema_version': VERSION,
                     'row_json': encode(row)})
    # The legacy consumers have no 'excluded finite value' gate. Do not change
    # those values to null or let them enter cards: withhold that consumer state.
    blocked_states = {r['consumer_state_id'] for r in rows if not json.loads(r['row_json'])['included']
                      and any(json.loads(r['row_json'])[k] is not None for k in ['U_joint','P_joint','A'])}
    for row in rows:
        row['consumer_state_status'] = ('raw_only_excluded_finite_contrast' if row['consumer_state_id'] in blocked_states
                                        else 'see_row_eligibility')
    metadata = metadata_packet(design, context, snapshot)
    return {'reader_adapter/form_identity': pd.DataFrame(identity_rows, columns=['form_id','schema_version','identity_json','summary_json','site_mappings_json']),
            'reader_adapter/form_contrasts': pd.DataFrame(rows, columns=['adapter_row_id','form_id','contrast_id','consumer_state_id','card_input_eligible','restriction_reasons','consumer_state_status','schema_version','row_json']),
            'reader_adapter/precursor_membership': members,
            'reader_adapter/study_metadata': pd.DataFrame([{'metadata_id': 'recorded_study', 'schema_version': VERSION, 'metadata_json': encode(metadata)}])}


def consumer_states(tables):
    """Yield supported state inputs; callers decide whether to invoke card builders.

    This is not a finding-selection API. All withheld rows remain in the tables.
    """
    metadata = json.loads(tables['reader_adapter/study_metadata'].iloc[0].metadata_json)
    records = tables['reader_adapter/form_contrasts']
    for sid, group in records.groupby('consumer_state_id', sort=True):
        if not group.card_input_eligible.any() or group.consumer_state_status.eq('raw_only_excluded_finite_contrast').any():
            continue
        # Retain excluded/missing time points for an otherwise representable form.
        rows = [json.loads(r.row_json) for r in group.itertuples()]
        if any(set(r['adapter_restrictions']) - {'quant_comparison_excluded'} for r in rows):
            continue
        manifest = {**metadata['sample_manifest'], 'conditions': [
            {'condition': r['condition'], 'time_minutes': r['time_minutes'], 'reference_id': r['reference_id']} for r in rows]}
        yield {'consumer_state_id': sid, 'vector_plot_raw_data': rows, 'sample_manifest': manifest,
               'study_metadata_contract': metadata['contract'], 'replication_declaration': metadata['replication_declaration'],
               'source_adapter_row_ids': group.adapter_row_id.tolist(), 'unadjusted_source': 'U_joint'}


def validate_card_inputs(tables, design):
    missing = set(TABLE_KEYS) - set(tables)
    if missing: raise ValueError('Missing card input table: ' + ','.join(sorted(missing)))
    original = {(r['form_id'], r['contrast_id']): clean(r) for r in tables['quant/comparisons'].to_dict('records')}
    projected = tables['reader_adapter/form_contrasts']
    if len(projected) != len(original) or set(zip(projected.form_id, projected.contrast_id)) != set(original):
        raise ValueError('Card input comparison population differs')
    run = {(r.form_id, r.injection_id): r for r in tables['quant/runlevel'].itertuples()}
    members = tables['reader_adapter/precursor_membership'].groupby('form_id').size().to_dict()
    for r in projected.itertuples():
        c = original[r.form_id, r.contrast_id]; row = json.loads(r.row_json)
        if any(not equivalent(row.get(k), v) for k, v in c.items()):
            raise ValueError('Card input changed source comparison')
        for axis, source in [('ptm_unadjusted','U_joint'), ('protein','P_joint'), ('ptm_protein_adjusted','A')]:
            if not equivalent(row[axis+'_log2fc'], c[source]): raise ValueError('Card axis changed source quantity')
        for side, condition in [('reference', c['reference_condition_id']), ('target', c['target_condition_id'])]:
            for iid in ids(c[side+'_joint_run_ids']):
                observed = run.get((r.form_id, iid))
                if observed is None or not observed.joint_observed or observed.condition_id != condition:
                    raise ValueError('Card input joint-mask foreign key mismatch')
        if r.card_input_eligible and (row['adapter_restrictions'] or members.get(r.form_id) != 1):
            raise ValueError('Unsupported form promoted to precursor card')


def equivalent(a, b):
    """CSV blanks and JSON null share NA semantics; never equate NA and zero."""
    a, b = clean(a), clean(b)
    if a in (None, '') or b in (None, ''):
        return a in (None, '') and b in (None, '')
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-10)
    return a == b
