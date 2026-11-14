"""Axis-specific Report schema shared by projection, cards and claim binding.

Legacy p_value/q_value belong only to the adjusted axis. Missing statistics or
replicate counts are never borrowed from another axis or inferred from values.
"""
from __future__ import annotations

import math
import json
from typing import Any, Mapping

QUANTITATIVE_SCHEMA_VERSION = "report_quantitative_fields.v2"
AXIS_PREFIXES = {
    "unadjusted": ("ptm_unadjusted", "PTM_Unadjusted"),
    "adjusted": ("ptm_protein_adjusted", "PTM_ProteinAdjusted", "PTM_Relative", "ptm_relative"),
    "protein": ("protein", "Protein"),
    "reconstructed": ("ptm_reconstructed", "PTM_Reconstructed", "PTM_Absolute", "ptm_absolute"),
}
SUFFIXES = {"value": ("log2fc", "Log2FC"), "p": ("p_value", "P_Value"),
            "q": ("q_value", "Q_Value"), "control_n": ("control_n", "Control_N"),
            "treatment_n": ("treatment_n", "Treatment_N")}


def axis_number(row: Mapping[str, Any], axis: str, field: str = "value") -> float | None:
    lower, upper = SUFFIXES[field]
    keys = [f"{prefix}_{lower if prefix.islower() else upper}" for prefix in AXIS_PREFIXES[axis]]
    if axis == "adjusted" and field in {"p", "q"}:
        keys += [lower, upper]
    for key in keys:
        # An explicit canonical null is authoritative, including on reprojection.
        if key not in row:
            continue
        try:
            value = float(row[key])
        except (ValueError, TypeError):
            return None
        return value if math.isfinite(value) else None
    return None


def project_axis_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    fields = {f"{prefixes[0]}_{SUFFIXES[field][0]}": axis_number(row, axis, field)
              for axis, prefixes in AXIS_PREFIXES.items() for field in SUFFIXES}
    for axis, prefixes in AXIS_PREFIXES.items():
        for suffix in ("control_sample_ids", "treatment_sample_ids", "ci", "method", "missing_reason", "estimator_id", "statistical_unit", "test_status"):
            fields[f"{prefixes[0]}_{suffix}"] = _axis_metadata(row, axis, suffix)
    return fields


def _axis_metadata(row, axis, suffix):
    source_suffix = {"control_sample_ids": "Control_Sample_IDs", "treatment_sample_ids": "Treatment_Sample_IDs",
                     "ci": "CI", "method": "Method", "missing_reason": "Missing_Reason", "estimator_id": "Estimator_ID", "statistical_unit": "Statistical_Unit", "test_status": "Test_Status"}[suffix]
    for prefix in AXIS_PREFIXES[axis]:
        key = f"{prefix}_{suffix if prefix.islower() else source_suffix}"
        if key in row:
            value = row[key]
            if isinstance(value, float) and not math.isfinite(value):
                return None
            if suffix in {"control_sample_ids", "treatment_sample_ids", "ci"} and isinstance(value, str):
                try:
                    value = json.loads(value)
                except (ValueError, TypeError):
                    return None
            return value
    if axis == "protein" and suffix == "estimator_id":
        return row.get("linked_protein_estimator_id", row.get("Linked_Protein_Estimator_ID"))
    return None


def axis_evidence(row: Mapping[str, Any], axis: str, sample_manifest: Mapping[str, Any] | None = None) -> dict:
    """Retain axis-specific uncertainty and explicit design units; never infer pairing."""
    evidence = {field: axis_number(row, axis, field) for field in SUFFIXES}
    evidence.update({suffix: _axis_metadata(row, axis, suffix) for suffix in (
        "control_sample_ids", "treatment_sample_ids", "ci", "method", "missing_reason", "estimator_id", "statistical_unit", "test_status",
    )})
    sample_rows = (sample_manifest or {}).get("samples") or []
    samples = {}
    conflicts = set()
    for sample in sample_rows:
        if not isinstance(sample, Mapping) or not sample.get("sample_id"):
            continue
        sid = str(sample["sample_id"])
        if sid in samples and samples[sid] != sample:
            conflicts.add(sid)
        samples[sid] = sample
    for sid in conflicts:
        samples.pop(sid, None)
    evidence["sample_manifest_conflicts"] = sorted(conflicts)
    for group in ("control", "treatment"):
        ids = evidence[f"{group}_sample_ids"]
        ids = sorted(set(map(str, ids))) if isinstance(ids, list) else None
        evidence[f"{group}_sample_ids"] = ids
        units = {str(samples[s]["biological_unit"]) for s in ids or [] if s in samples and samples[s].get("biological_unit")}
        all_resolved = bool(ids) and all(s in samples and samples[s].get("biological_unit") for s in ids)
        evidence[f"{group}_biological_n"] = len(units) if all_resolved else None
    evidence["available"] = evidence["value"] is not None
    evidence["value_status"] = "observed" if evidence["available"] else "unavailable"
    if not evidence.get("test_status"):
        evidence["test_status"] = ("computed" if evidence["p"] is not None or evidence["q"] is not None
                                   else "not_computed" if "no_protein_test_computed" in str(evidence.get("method"))
                                   else "statistical_support_unavailable")
    evidence["ci_status"] = "recorded" if evidence["ci"] is not None else "not_available"
    evidence["missing_reason"] = evidence["missing_reason"] or (None if evidence["available"] else "axis_not_available")
    return evidence


def axis_support(row: Mapping[str, Any]) -> dict[str, Any]:
    return {f"{('protein_adjusted' if axis == 'adjusted' else axis)}_{SUFFIXES[field][0]}":
            axis_number(row, axis, field)
            for axis in ("unadjusted", "adjusted", "protein")
            for field in ("p", "q", "control_n", "treatment_n")}


# The package writer, saved-row bundle and structured claim checker share these
# descriptors. They describe recorded quantities; they never infer missing facts.
FIELD_SEMANTICS_VERSION = 'astra_field_semantics.v1'
METHOD_DISCRIMINATORS = ('method_id', 'method_version', 'score_name')
METHOD_METADATA = ('direction_semantics', 'null_model', 'multiple_testing_family', 'statistical_unit')
LOG_EFFECTS = {
    'A': 'Target minus actual reference of same-injection PTM/parent log ratios; U_joint minus P_joint, not absolute occupancy.',
    'U_joint': 'PTM contrast on the exact joint PTM/parent mask used for A.',
    'P_joint': 'Parent protein contrast on the exact joint PTM/parent mask used for A.',
    'U_all': 'PTM contrast on its own observed mask, which may differ from the A mask.',
    'P_all': 'Parent protein contrast on its own observed mask, which may differ from the A mask.',
    'log2_change': 'Recorded target minus actual reference log abundance contrast.',
    'strict_parent_A': 'PTM adjustment using the recorded strict peptide parent estimator and mask.',
    'PG_parent_A': 'PTM adjustment using the recorded protein-group parent estimator and mask.',
    'decomposition_residual': 'Numerical residual of A minus (U_joint minus P_joint).',
    'post_reference_U': 'Target-arm PTM change from the recorded first valid target observation, not matched treatment effect.',
    'raw_candidate_A': 'Target-arm joint PTM/parent change from the recorded post-reference; inspect eligibility.',
    'eligible_A': 'Eligible target-arm post-reference change; null when the cross-time relationship or parent is unavailable.',
}
FK_FIELDS = {'contrast_id': 'study/study_design.json#contrasts.contrast_id',
    'target_condition_id': 'study/study_design.json#conditions.condition_id',
    'reference_condition_id': 'study/study_design.json#conditions.condition_id',
    'condition_id': 'study/study_design.json#conditions.condition_id',
    'form_id': 'quant/summary.csv#form_id', 'injection_id': 'study/study_design.json#injections.injection_id',
    'material_id': 'study/study_design.json#materials.material_id'}


def field_semantics(table, column, *, row=None, dtype=None):
    """A row discriminator refines a contract; missing metadata stays unknown."""
    row = row or {}; table = table.removesuffix('.csv')
    out = {'schema_version': FIELD_SEMANTICS_VERSION, 'field_path': table+'.csv.'+column,
        'meaning': 'Unknown: no registered semantic contract for this field.', 'status': 'unknown',
        'unknown_reason': 'unregistered_or_legacy_field', 'unit': 'unknown', 'scale': 'unknown',
        'allowed_values': None, 'range': None, 'nullable': True,
        'null_contract': 'Missing is unavailable/unknown, never zero; inspect recorded status/reason.',
        'null_status_binding': [], 'statistical_unit': 'unknown', 'foreign_key': FK_FIELDS.get(column),
        'restriction_class': 'unclassified'}
    def known(meaning, unit, scale='identity', statistical_unit='not_applicable', restriction_class='recorded_metadata', **extra):
        out.update(meaning=meaning, unit=unit, scale=scale, statistical_unit=statistical_unit,
                   restriction_class=restriction_class, status='known', unknown_reason=None, **extra)
    if table=='quant/detection' and column in {'post_reference_U','raw_candidate_A','eligible_A'} and row.get('detection_version')!='target_arm_post_reference.v2':
        out.update(unknown_reason='legacy_detection_semantics_not_versioned',restriction_class='relative_effect',
                   meaning='Stored legacy detection track; preserved without recalculation. Cross-time eligibility has not been upgraded.')
    elif column in LOG_EFFECTS and table.startswith(('quant/', 'temporal/', 'evidence/')):
        known(LOG_EFFECTS[column], 'log2_ratio', 'log2', 'recorded_material_unit_or_pair', 'relative_effect')
    elif column in {'ptm_intensity', 'parent_intensity'}:
        known('Positive supplied matrix intensity; upstream normalization is not inferred.', 'supplied_intensity_unit',
              statistical_unit='injection', restriction_class='raw_abundance', range={'min_exclusive':0})
    elif column in {'ptm_log2','parent_log2','adjusted_log2_ratio'}:
        known('Recorded per-injection log abundance or PTM/parent log ratio.', 'log2_intensity' if column!='adjusted_log2_ratio' else 'log2_ratio',
              'log2','injection','relative_abundance')
    elif column in {'biological_p_value','biological_q_value'}:
        known('Biological-unit test probability/FDR only when actually computed; Astra primary tests remain unavailable.',
              'probability','probability','biological_unit_or_declared_pair','biological_statistic',range={'min':0,'max':1})
    elif column in {'method_p','method_q'}:
        known('Recorded method-native p/FDR; not biological replicate inference or calibration.',
              'probability','probability',row.get('statistical_unit') or 'unknown','method_statistic',range={'min':0,'max':1})
        out.update(null_model=row.get('null_model') or 'unknown',multiple_testing_family=row.get('multiple_testing_family') or 'unknown')
    elif column in {'score','native_score'} and table=='kinase/method_scores':
        if tuple(row.get(k) for k in METHOD_DISCRIMINATORS)==('PhosX_native_functions','0.23.1','Activity Score'):
            known('Native PhosX Activity Score: signed site-rank enrichment, not causal activation.',
                  'native_activity_score','native',row.get('statistical_unit') or 'unknown','native_activity')
        elif tuple(row.get(k) for k in METHOD_DISCRIMINATORS)==('repository_measured_gene_zscore','1','z_score'):
            known('Repository measured-gene universe standardized enrichment; not official KSEA or direct kinase activity.',
                  'standardized_score','z_score',row.get('statistical_unit') or 'unknown','descriptive_footprint')
        else:
            out.update(unknown_reason='method_discriminator_requires_recorded_contract',restriction_class='method_score')
        out.update(direction_semantics=row.get('direction_semantics') or 'unknown',
                   null_model=row.get('null_model') or 'unknown',multiple_testing_family=row.get('multiple_testing_family') or 'unknown')
    elif column=='localization_probability':
        known('Supplied localization confidence only; null means not measured/unknown and is not high confidence.',
              'probability','probability','localization_evidence','localization',range={'min':0,'max':1})
    elif column=='activity_magnitude' and table=='kinase/kinase_temporal_profiles':
        known('Descriptive gene-balanced substrate footprint on the recorded track; not native activity or a confirmed kinase call.',
              'log2_ratio','log2','substrate_gene','descriptive_footprint')
    elif column=='rate_log2_per_min' and table.startswith('temporal/'):
        known('Recorded adjacent observed effect change divided by elapsed canonical minutes; gaps remain unavailable.',
              'log2_ratio_per_minute','log2_per_time','recorded_material_unit_or_pair','relative_effect_rate')
    elif column in {'time_min','reference_time_min','first_repeated_time_min','post_reference_time_min','from_min','to_min','dt_min',
                    'observed_peak_time_min','onset_lower_min','onset_upper_min','recovery_lower_min','recovery_upper_min',
                    'observed_duration_min','auc_supported_duration_min','possible_lag_lower_min','possible_lag_upper_min',
                    'source_peak_min','target_peak_min','source_onset_lower_min','source_onset_upper_min','target_onset_lower_min','target_onset_upper_min'}:
        known('Recorded canonical numeric time in minutes; unknown is null, never time zero.', 'minute','linear',restriction_class='time')
    elif column.endswith('_biological_n'):
        known('Recorded biological units with usable values; never the injection count.', 'count','integer','biological_unit','biological_count',range={'min':0})
    elif column in {'reference_joint_n','target_joint_n','reference_observed_n','target_observed_n','detected_n','reference_detected_n','scheduled_n','parent_observed_n','joint_observed_n'}:
        known('Recorded finite injection observations (scheduled_n counts registered injections); not independent biological n.',
              'count','integer','injection','injection_count',range={'min':0})
    elif column in {'eligible_site_count','universe_count'}:
        known('Recorded method input membership count; unit follows the method row.', 'count','integer',row.get('statistical_unit') or 'unknown','method_coverage',range={'min':0})
    elif column.endswith('_id') or column in {'input_column','source_key_json'}:
        known('Recorded identity or canonical source locator, not a quantity.', 'identifier',restriction_class='identity')
    elif str(dtype)=='bool' or column in {'joint_observed','U_observed','P_observed','included','inference_use_allowed','primary_adjustment_eligible','primary_mapping_eligible'}:
        known('Recorded boolean observation/eligibility mask; false is distinct from unknown.', 'boolean',allowed_values=[False,True],restriction_class='mask')
    elif column.endswith(('_status','_reason','_reasons')) or column in {'status','resolution','pairing','reference_strategy','effect_kind'}:
        known('Recorded status/declaration; no additional scientific approval is implied.', 'category',restriction_class='status')
    elif table.startswith('reader/literature') and column=='source_json.document':
        known('Stored retrieved text fragment; not whole-paper review, independent validation or semantic approval.',
              'text',restriction_class='literature_fragment')
    return out


def table_field_semantics(table, frame):
    """Complete descriptors, including explicit unknowns, without changing CSVs."""
    statuses = [c for c in frame if c.endswith(('_status','_reason','_reasons')) or c in {'status','included','inference_use_allowed'}]
    fields = {}
    row_contract = ({'detection_version':'target_arm_post_reference.v2'} if 'detection_version' in frame and
                    frame.detection_version.eq('target_arm_post_reference.v2').all() else {})
    for column in frame:
        fields[column] = {**field_semantics(table,column,dtype=frame[column].dtype,row=row_contract),
                          'observed_null_count':int(frame[column].isna().sum()),
                          'dtype':str(frame[column].dtype),'null_status_binding':statuses}
    variants = []
    if table.removesuffix('.csv')=='kinase/method_scores':
        cols = [k for k in (*METHOD_DISCRIMINATORS,*METHOD_METADATA) if k in frame]
        if cols:
            for row in frame[cols].drop_duplicates().to_dict('records'):
                row = {k:None if isinstance(v,float) and not math.isfinite(v) else v for k,v in row.items()}
                variants.append({'discriminator':{k:row.get(k) for k in METHOD_DISCRIMINATORS},
                    'recorded_metadata':{k:row.get(k) for k in METHOD_METADATA},
                    'fields':{k:field_semantics(table,k,row=row) for k in ('score','native_score','method_p','method_q') if k in frame}})
    return {'field_semantics_version':FIELD_SEMANTICS_VERSION,'field_semantics':fields,'method_semantics':variants}


FIELD_GUIDE = '''# 필드별 의미와 통계 단위

`reproducibility/data_dictionary.json`의 field_semantics가 column 계약입니다.
method_scores는 method_id/method_version/score_name과 recorded_metadata를 함께 읽으세요.
실제 null 개수는 observed_null_count이며 nullable 허용 여부와 다릅니다.
unknown descriptor는 0이나 승인된 값이 아닙니다. source row의 status/reason을 유지하세요.
U_joint/P_joint/A와 U_all/P_all은 mask가 다릅니다. A는 절대 occupancy가 아닙니다.
Native Activity Score, footprint, method p/q, biological p/q와 calibration은 서로 바꾸지 마세요.
미측정 localization이나 no-call을 높은 confidence/비활성으로 해석하지 마세요.
정의 추가는 계산·검색·의미 검토를 수행하지 않습니다.
'''
