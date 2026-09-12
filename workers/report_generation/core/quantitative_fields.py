"""Axis-specific Report schema shared by projection, cards and claim binding.

Legacy p_value/q_value belong only to the adjusted axis. Missing statistics or
replicate counts are never borrowed from another axis or inferred from values.
"""
from __future__ import annotations

import math
from typing import Any, Mapping

QUANTITATIVE_SCHEMA_VERSION = "report_quantitative_fields.v1"
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
    return {f"{prefixes[0]}_{SUFFIXES[field][0]}": axis_number(row, axis, field)
            for axis, prefixes in AXIS_PREFIXES.items() for field in SUFFIXES}


def axis_support(row: Mapping[str, Any]) -> dict[str, Any]:
    return {f"{('protein_adjusted' if axis == 'adjusted' else axis)}_{SUFFIXES[field][0]}":
            axis_number(row, axis, field)
            for axis in ("unadjusted", "adjusted", "protein")
            for field in ("p", "q", "control_n", "treatment_n")}
