"""Analysis context PATCH semantics shared by order creation and duplication."""
from copy import deepcopy
import os


def current_astra_context(context):
    """Select the current engine for a NEW request, including v4 order reruns.

    Do not apply to recorded packages/replay or the generic PATCH merger. Keep
    explicit legacy purposes and every supplied design/science setting intact.
    """
    result = deepcopy(context or {})
    requested = result.get('quantitation_export_mode')
    if result.get('quantitation_export_mode') == 'astra_analysis.v4':
        result['quantitation_export_mode'] = 'astra_analysis.v5'
    if result.get('quantitation_export_mode')=='astra_analysis.v5' and os.getenv('PTM_ASTRA_EVIDENCE_V6')=='1':
        result['quantitation_export_mode']='astra_analysis.v6'
    if str(requested).startswith('astra_analysis.'):
        previous = result.get('astra_execution') or {}
        # The resolver is called more than once on create/start. Keep the first
        # request, but never let a stale contract hide a newly changed profile.
        if previous.get('effective_profile') != requested:
            previous = {}
        result['astra_execution'] = {
            'requested_profile': previous.get('requested_profile', requested),
            'effective_profile': result['quantitation_export_mode'],
            'selection_policy': 'current_astra_context.v1',
            'api_v6_flag_enabled': os.getenv('PTM_ASTRA_EVIDENCE_V6') == '1',
        }
    return result


def verify_execution_profile(context, executed_profile):
    """Check request intent before publishing, never derive it from the result.

    Recorded archives without a selection record use their recorded request.
    This does not upgrade legacy runs or consult the replay worker's flag.
    """
    record = deepcopy(context.get('astra_execution') or {})
    requested = context.get('quantitation_export_mode')
    expected = record.get('effective_profile', requested)
    if expected != requested or executed_profile != expected:
        raise ValueError(f'astra_profile_mismatch: expected={expected}, dispatch={requested}, executed={executed_profile}')
    return {**record, 'expected_profile': expected, 'dispatch_profile': requested,
            'executed_profile': executed_profile, 'status': 'matched'}


def merge_analysis_context(existing, patch):
    """Omitted keys survive; an explicit null removes a key.

    Structured values such as sample_manifest are replaced atomically when supplied.
    An empty PATCH is a no-op, not a request to forget the experimental design.
    """
    if existing is not None and not isinstance(existing, dict):
        raise ValueError("Existing analysis_context must be an object")
    if patch is not None and not isinstance(patch, dict):
        raise ValueError("analysis_context must be an object")
    result = deepcopy(existing or {})
    for key, value in (patch or {}).items():
        if value is None:
            result.pop(key, None)
        else:
            result[key] = deepcopy(value)
    policy = result.get("normalization_policy", "legacy_median.v1")
    if policy not in {"legacy_median.v1", "already_normalized.v1", "use_supplied_intensities"}:
        raise ValueError("Unsupported normalization_policy")
    if result.get('quantitation_export_mode', 'legacy_only.v1') not in {'legacy_only.v1', 'legacy_plus_report_compatible.v1', 'enrichment_free_primary.v2', 'enrichment_free_timecourse.v3', 'astra_analysis.v4','astra_analysis.v5','astra_analysis.v6'}:
        raise ValueError('Unsupported quantitation_export_mode')
    return result
