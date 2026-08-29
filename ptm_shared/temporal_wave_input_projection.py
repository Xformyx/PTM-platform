"""Shared, truth-free input projection for canonical Temporal Wave fitting.

The canonical Wave engine requires a rectangular finite matrix.  Missing
measurements are therefore never converted to a biological zero.  Until a
separately validated pairwise-missing distance engine exists, only sites with
one finite observation at every declared timepoint are eligible for Wave
fitting.  The complete site observation table remains available downstream;
this module controls only the Wave-fitting universe.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Sequence


CONTRACT_VERSION = "temporal_wave_input_projection.v1"
MISSING_VALUE_POLICY = "complete_case_no_imputation"


def _finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def project_temporal_wave_input(
    site_time_series: Mapping[str, Mapping[str, Any]],
    timepoints: Sequence[str],
) -> tuple[dict[str, dict[str, float]], dict[str, Any]]:
    """Project sparse site trajectories to a common Wave-fitting universe.

    A site is eligible only when every declared timepoint has a finite observed
    value.  No missing value is imputed, including zero imputation.  This pure
    function is shared by production and strict benchmark analysis paths.
    """

    ordered_timepoints = list(dict.fromkeys(str(value) for value in timepoints))
    projected: dict[str, dict[str, float]] = {}
    excluded_counts = {
        "invalid_time_series": 0,
        "no_observed_values": 0,
        "incomplete_time_grid": 0,
    }
    missing_timepoint_counts: dict[str, int] = {}

    for raw_key, raw_values in sorted(site_time_series.items()):
        key = str(raw_key or "").strip().upper()
        if not key or not isinstance(raw_values, Mapping):
            excluded_counts["invalid_time_series"] += 1
            continue
        parsed = {
            timepoint: value
            for timepoint in ordered_timepoints
            if (value := _finite_float(raw_values.get(timepoint))) is not None
        }
        if not parsed:
            excluded_counts["no_observed_values"] += 1
            continue
        missing_count = len(ordered_timepoints) - len(parsed)
        if missing_count:
            excluded_counts["incomplete_time_grid"] += 1
            missing_timepoint_counts[str(missing_count)] = (
                missing_timepoint_counts.get(str(missing_count), 0) + 1
            )
            continue
        projected[key] = {timepoint: parsed[timepoint] for timepoint in ordered_timepoints}

    site_key_sha256 = hashlib.sha256(
        json.dumps(sorted(projected), separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    provenance = {
        "contract_version": CONTRACT_VERSION,
        "missing_value_policy": MISSING_VALUE_POLICY,
        "imputation_applied": False,
        "required_observed_timepoints": len(ordered_timepoints),
        "timepoints": ordered_timepoints,
        "total_input_sites": len(site_time_series),
        "eligible_site_count": len(projected),
        "excluded_site_count": sum(excluded_counts.values()),
        "excluded_reason_counts": excluded_counts,
        "missing_timepoint_count_distribution": missing_timepoint_counts,
        "eligible_site_keys_sha256": site_key_sha256,
        "claim_boundary": (
            "Projection defines the Wave-fitting input universe only. "
            "Missing measurements are not biological zeroes and are never imputed."
        ),
    }
    return projected, provenance
