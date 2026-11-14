"""Deterministic checks of structured assertions against immutable saved rows.

This is an anchor/value/restriction checker, never a biological prose reviewer.
"""
from __future__ import annotations

import json
import math
from numbers import Real

from .quantitative_fields import field_semantics

VERSION = 'astra_claim_check.v1'
MISSING = object()


def compare_value(actual, asserted, *, rounding_precision=None, tolerance=None):
    if actual is MISSING:
        return 'unverifiable', 'field_not_recorded'
    if actual is None or isinstance(actual, float) and not math.isfinite(actual):
        return ('unverifiable', 'source_null') if asserted is None else ('failed', 'null_is_not_a_value')
    if asserted is None:
        return 'unverifiable', 'asserted_value_missing'
    if isinstance(actual, Real) and not isinstance(actual, bool):
        if not isinstance(asserted, Real) or isinstance(asserted, bool) or not math.isfinite(asserted):
            return 'failed', 'numeric_type_mismatch'
        allowed = 1e-12 * max(1., abs(actual))
        if rounding_precision is not None:
            if type(rounding_precision) is not int or not 0 <= rounding_precision <= 15:
                return 'failed', 'invalid_rounding_precision'
            allowed += .5 * 10 ** -rounding_precision
        if tolerance is not None:
            if (not isinstance(tolerance, Real) or isinstance(tolerance, bool) or not math.isfinite(tolerance)
                    or tolerance < 0 or tolerance > max(1e-6, abs(actual)*1e-6)):
                return 'failed', 'tolerance_exceeds_contract'
            allowed += tolerance
        if actual * asserted < 0:
            return 'failed', 'sign_mismatch'
        return ('passed', 'within_declared_precision') if abs(actual-asserted) <= allowed else ('failed', 'value_mismatch')
    if rounding_precision is not None or tolerance is not None:
        return 'failed', 'numeric_tolerance_on_non_numeric_value'
    return ('passed', 'exact_value') if type(actual) is type(asserted) and actual == asserted else ('failed', 'value_or_type_mismatch')


def _field(row, path):
    """Explicit JSON paths only; retain the nearest declared point, never first binding."""
    value = row; context = row
    for part in path.split('.'):
        if isinstance(value, str):
            try: value = json.loads(value)
            except ValueError: return MISSING, context
        if isinstance(value, dict):
            if value.get('contrast_id'): context = value
            value = value.get(part, MISSING)
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else: return MISSING, context
    return value, context


def _descriptor(table, path, context):
    # These are existing, typed projection paths, not arbitrary JSON field names.
    semantic_table = table; column = path
    if table == 'reader_adapter/form_contrasts.csv' and path.startswith('row_json.') and path.count('.') == 1:
        semantic_table = 'quant/comparisons.csv'; column = path.split('.')[-1]
    elif table == 'reader/cards.csv' and path.startswith('card_json.source_bindings.'):
        bits = path.split('.')
        if len(bits) == 4 and bits[2].isdigit(): semantic_table = 'quant/comparisons.csv'; column = bits[-1]
    result = field_semantics(semantic_table, column, row=context)
    result['field_path'] = table+'.'+path
    return result


def _points(catalog):
    from .effect_series import resolve_series
    name = 'study/study_design.json'; path = catalog.root/name
    if not path.is_file(): return {}
    if name not in catalog._verified:
        # Old catalogs have no effect_scope hash; bind to the archived manifest.
        manifest = catalog.root/'manifest.json'
        if not manifest.is_file(): return {}
        saved = json.loads(manifest.read_text())
        entries = saved.get('files', [])
        meta = next((v for v in entries if v.get('path') == name), None) if isinstance(entries, list) else entries.get(name)
        if not meta or not meta.get('sha256'): return {}
        catalog._verify(name, meta)
    catalog._require()
    series, _ = resolve_series(json.loads(path.read_text()))
    return {p['contrast_id']: p for s in series.values() for p in s['points']}


def _scope(claim, context, points):
    cid = context.get('contrast_id') or context.get('contrast_or_window_id')
    point = points.get(cid, {})
    aliases = {'target_condition_id':'target_condition_id', 'reference_condition_id':'reference_condition_id',
               'target_time_min':'time_min', 'reference_time_min':'reference_time_min',
               'comparison_kind':'effect_kind', 'reference_strategy':'reference_strategy'}
    status = 'passed'; reasons = []
    for assertion, source in aliases.items():
        if assertion not in claim: continue
        value = point.get(source, context.get(source))
        if value is None:
            if status != 'failed': status = 'unverifiable'
            reasons.append(assertion+':not_recorded')
        elif claim[assertion] != value:
            status = 'failed'; reasons.append(assertion+':mismatch')
        # Stored row and canonical point must agree where both record the field.
        if source in point and context.get(source) is not None and point[source] != context[source]:
            status = 'failed'; reasons.append(assertion+':source_snapshot_conflict')
    return status, reasons


def _restrictions(claim, descriptor, context):
    status = 'passed'; reasons = []
    if descriptor['status'] == 'unknown':
        status = 'unverifiable'; reasons.append('unknown_field_semantics')
    elif claim.get('unit') != descriptor['unit']:
        status = 'failed'; reasons.append('unit_mismatch_or_missing')
    allowed = {descriptor['restriction_class']}
    if descriptor['restriction_class'] == 'status': allowed.add('declared_status')
    level = claim.get('claim_level')
    if level not in allowed:
        status = ('unverifiable' if not level or descriptor['status']=='unknown' else 'failed')
        reasons.append('claim_level_not_supported_by_field')
    if level in {'confirmed_kinase_call','kinase_inactivity','causal_activation','absolute_occupancy',
                 'independent_validation','whole_paper_review','high_localization_confidence'}:
        status = 'failed'; reasons.append('scientific_promotion_not_supported_by_mechanical_check')
    if context.get('inference_use_allowed') is False and level != 'declared_status':
        status = 'failed'; reasons.append('source_inference_use_disallowed')
    return status, reasons


def check_claims(catalog, claims):
    from .astra_reader_full import validate_citations
    from .astra_evidence_catalog import digest
    if not isinstance(claims, list): raise ValueError('claims must be a list')
    catalog._require()
    if 'provenance.json' not in catalog._verified:
        catalog._verify('provenance.json', {'sha256':digest(catalog.root/'provenance.json')})
    run_id = json.loads((catalog.root/'provenance.json').read_text())['run_id']
    points = _points(catalog); output = []
    for claim in claims:
        if not isinstance(claim, dict): raise ValueError('each claim must be an object')
        result = {'claim':claim, 'claim_id':claim.get('claim_id'), 'anchor_status':'invalid',
            'numeric_status':'unverifiable', 'scope_status':'unverifiable', 'restriction_status':'unverifiable',
            'literature_anchor_status':'not_requested', 'semantic_review_status':'not_performed',
            'verification_reason':[]}
        try:
            if claim.get('run_id') != run_id or claim.get('catalog_id') != catalog.catalog['catalog_id']:
                raise ValueError('Claim run/catalog mismatch')
            refs = claim.get('evidence_refs')
            if not isinstance(refs, list) or not refs: raise ValueError('Claim requires evidence_refs')
            checked = validate_citations(catalog, refs); result['anchor_status'] = 'validated'
            literature = claim.get('literature_refs') or []
            if literature:
                result['literature_anchor_status'] = 'invalid'
                validate_citations(catalog, literature)
                result['literature_anchor_status'] = 'validated_fragment_anchor_only'
            if len(checked) > 1:
                checked = [r for r in checked if r['citation']['evidence_id'] == claim.get('value_evidence_id')]
            if len(checked) != 1:
                result['verification_reason'].append('multiple_anchors_require_unique_value_evidence_id')
            else:
                selected = checked[0]; row = selected['source_row'][0]
                path = claim.get('field_path')
                if not isinstance(path, str) or not path: raise ValueError('Claim requires field_path')
                value, context = _field(row, path)
                descriptor = _descriptor(selected['citation']['source_table'], path, context)
                result['definition'] = descriptor
                result['source_value_recorded'] = value is not MISSING
                result['source_value'] = value if value is not MISSING else None
                result['actual_scope'] = points.get(context.get('contrast_id') or context.get('contrast_or_window_id'), {})
                result['numeric_status'], reason = compare_value(value, claim.get('asserted_value'),
                    rounding_precision=claim.get('rounding_precision'), tolerance=claim.get('tolerance'))
                result['verification_reason'].append(reason)
                result['scope_status'], reasons = _scope(claim, context, points)
                result['verification_reason'].extend(reasons)
                result['restriction_status'], reasons = _restrictions(claim, descriptor, context)
                result['verification_reason'].extend(reasons)
        except (ValueError, KeyError, TypeError) as exc:
            result['anchor_status'] = 'invalid'; result['verification_reason'].append(str(exc))
        states = [result[k] for k in ('numeric_status','scope_status','restriction_status')]
        result['verification_status'] = ('rejected' if result['anchor_status']=='invalid' or 'failed' in states
            else 'unverifiable' if 'unverifiable' in states else 'mechanically_validated_not_semantically_reviewed')
        output.append(result)
    catalog._require()
    return {'schema_version':VERSION, 'run_id':run_id, 'catalog_id':catalog.catalog['catalog_id'], 'claims':output,
            'semantic_review_status':'not_performed', 'scope':'structured saved-row assertions only; no natural-language scientific approval'}
