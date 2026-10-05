"""Analysis context PATCH semantics shared by order creation and duplication."""
from copy import deepcopy
import os


def current_astra_context(context):
    """Select the current engine for a NEW request, including v4 order reruns.

    Do not apply to recorded packages/replay or the generic PATCH merger. Keep
    explicit legacy purposes and every supplied design/science setting intact.
    """
    result = deepcopy(context or {})
    if result.get('quantitation_export_mode') == 'astra_analysis.v4':
        result['quantitation_export_mode'] = 'astra_analysis.v5'
    if result.get('quantitation_export_mode')=='astra_analysis.v5' and os.getenv('PTM_ASTRA_EVIDENCE_V6')=='1':
        result['quantitation_export_mode']='astra_analysis.v6'
    return result


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
