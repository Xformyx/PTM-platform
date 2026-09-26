"""Analysis context PATCH semantics shared by order creation and duplication."""
from copy import deepcopy


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
    if policy not in {"legacy_median.v1", "already_normalized.v1"}:
        raise ValueError("Unsupported normalization_policy")
    if result.get('quantitation_export_mode', 'legacy_only.v1') not in {'legacy_only.v1', 'legacy_plus_report_compatible.v1'}:
        raise ValueError('Unsupported quantitation_export_mode')
    return result
