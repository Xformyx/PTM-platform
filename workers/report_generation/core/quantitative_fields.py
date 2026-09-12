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
        for suffix in ("control_sample_ids", "treatment_sample_ids", "ci", "method", "missing_reason", "estimator_id"):
            fields[f"{prefixes[0]}_{suffix}"] = _axis_metadata(row, axis, suffix)
    return fields


def _axis_metadata(row, axis, suffix):
    source_suffix = {"control_sample_ids": "Control_Sample_IDs", "treatment_sample_ids": "Treatment_Sample_IDs",
                     "ci": "CI", "method": "Method", "missing_reason": "Missing_Reason", "estimator_id": "Estimator_ID"}[suffix]
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
        "control_sample_ids", "treatment_sample_ids", "ci", "method", "missing_reason", "estimator_id",
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
    evidence["ci_status"] = "recorded" if evidence["ci"] is not None else "not_available"
    evidence["missing_reason"] = evidence["missing_reason"] or (None if evidence["available"] else "axis_not_available")
    return evidence


def axis_support(row: Mapping[str, Any]) -> dict[str, Any]:
    return {f"{('protein_adjusted' if axis == 'adjusted' else axis)}_{SUFFIXES[field][0]}":
            axis_number(row, axis, field)
            for axis in ("unadjusted", "adjusted", "protein")
            for field in ("p", "q", "control_n", "treatment_n")}
