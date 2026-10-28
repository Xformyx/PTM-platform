"""Reconcile verified DIA-NN aliases for live drafts, never recorded replay."""
from copy import deepcopy


def _value(value):
    value = value.get('value') if isinstance(value, dict) else value
    return str(value).strip() if value not in (None, '', 'unknown') else None


def reconcile_diann_version(context):
    result = deepcopy(context)
    for key in ['science', 'processing', 'acquisition_metadata', 'metadata_provenance']:
        if result.get(key) is not None and not isinstance(result[key], dict):
            raise ValueError(key + ' must be an object')
    science = result.get('science') or {}
    processing = result.get('processing')
    if processing is None and 'processing' not in result:
        processing = deepcopy((result.get('study_design') or {}).get('study', {}).get('processing', {}))
    processing = processing or {}
    legacy = result.get('acquisition_metadata') or {}
    sv = _value(science.get('diann_version'))
    pv = _value(processing.get('software_version'))
    lv = _value(legacy.get('diann_version'))
    software = _value(processing.get('software') or processing.get('software_name'))
    row = processing.get('software_version') or {}
    source = row.get('source', '') if isinstance(row, dict) else ''
    if not software and isinstance(row, dict): software = _value(row.get('software'))
    identified = software.lower().replace('-', '') == 'diann' if software else 'diann_version' in source
    other = bool(software) and not identified
    values = {'science.diann_version': sv, 'acquisition_metadata.diann_version': lv}
    if pv and not other and (identified or pv in {sv, lv}): values['processing.software_version'] = pv
    previous = (result.get('metadata_provenance') or {}).get('diann_version') or {}
    old = previous.get('resolved_value')
    # A later edit of one linked alias updates the still-unchanged mirrors.
    changed = {v for k, v in values.items() if v != old and (v is not None or k in previous.get('linked_fields', []))}
    present = {v for v in values.values() if v is not None}
    issues = []
    if old and len(changed) == 1:
        chosen = next(iter(changed))
    elif len(present) > 1:
        issues.append({'code': 'diann_version_conflict', 'path': 'science.diann_version',
                       'message': 'DIA-NN versions differ. Correct this version in the original data information.',
                       'severity': 'error', 'values': values})
        return result, issues
    else: chosen = next(iter(present), None)
    if pv and not identified and not other and pv not in {sv, lv}:
        issues.append({'code': 'processing_software_unidentified', 'path': 'processing.software_version',
                       'message': 'The recorded software version is not identified as DIA-NN; identify the software in data information.',
                       'severity': 'warning' if not chosen else 'error'})
        return result, issues
    if chosen is not None or old:
        result['science'] = {**science, 'diann_version': chosen}
        linked = ['science.diann_version']
        if not other:
            result['processing'] = {**processing, 'software': 'DIA-NN', 'software_version': {
                **(row if isinstance(row, dict) else {}), 'value': chosen,
                'status': 'provided' if chosen else 'unknown', 'software': 'DIA-NN',
                'source': source or 'analysis_context.science.diann_version'}}
            linked.append('processing.software_version')
        if 'diann_version' in legacy:
            result['acquisition_metadata'] = {**legacy, 'diann_version': chosen}
            linked.append('acquisition_metadata.diann_version')
        result['metadata_provenance'] = {**result.get('metadata_provenance', {}),
            'diann_version': {'resolved_value': chosen, 'linked_fields': linked,
                             'source_fields': previous.get('source_fields') or [key for key,value in values.items() if value is not None]}}
    return result, issues
