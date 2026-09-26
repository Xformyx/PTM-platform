"""Run-specific normalization provenance independent of current order settings."""
import json
import math
from pathlib import Path

VERSION = "normalization_provenance.v1"


def normalize_supplied_matrices(pr, pg, columns, policy):
    """Execute an explicit policy once; record both layers for portable replay."""
    import numpy as np
    import pandas as pd
    result, factors = [], []
    for source in (pr, pg):
        frame = source.copy()
        values = frame[columns].apply(pd.to_numeric, errors='coerce')
        values = values.where(np.isfinite(values) & values.gt(0))
        layer_factors = {c:1.0 for c in columns}
        if policy == 'legacy_median.v1':
            medians = values.median().fillna(1.0)
            target = float(np.median(medians))
            layer_factors = (target / medians).to_dict()
        elif policy != 'already_normalized.v1':
            raise ValueError('Unsupported normalization_policy')
        frame[columns] = values.mul(pd.Series(layer_factors))
        result.append(frame); factors.append(layer_factors)
    return *result, normalization_provenance(policy, *factors)


def normalization_provenance(policy, pr_factors=None, pg_factors=None):
    if policy not in {"legacy_median.v1", "already_normalized.v1"}:
        raise ValueError("Unsupported normalization_policy")
    applied = policy == "legacy_median.v1"
    factors = {"PR": dict(pr_factors or {}), "PG": dict(pg_factors or {})}
    values = [float(v) for layer in factors.values() for v in layer.values()]
    if any(not math.isfinite(v) or v <= 0 for v in values):
        raise ValueError("Normalization factors must be positive and finite")
    method = "separate_samplewise_median_scaling" if applied else "none"
    return {"schema_version": VERSION, "normalization_policy": policy,
            "method": method, "normalization_method": method,
            "sample_scaling_status": "performed" if applied else "not_performed",
            "batch_variation_corrected": False, "batch_correction_status": "not_performed",
            "injection_order_drift_correction_status": "not_performed",
            "upstream_quantity_scale_status": "unknown_not_recorded",
            "ratio_track_interpretation": "protein_abundance_adjusted_relative_ptm_ratio_contrast",
            "factors": factors, "factor_range": [min(values), max(values)] if values else None,
            "samples_scaled": len(set(factors["PR"]) | set(factors["PG"])) if applied else 0}


def recorded_normalization(output_dir, suffix):
    """Read the artifact belonging to this result, never infer from edited settings."""
    path = Path(output_dir) / f"normalization_provenance{suffix}.json"
    try:
        record = json.loads(path.read_text())
    except (OSError, ValueError):
        return unknown_normalization()
    if not isinstance(record, dict) or record.get("schema_version") != VERSION:
        return unknown_normalization()
    return record


def unknown_normalization():
    return {"method": "unknown_not_recorded", "normalization_method": "unknown_not_recorded",
            "sample_scaling_status": "unknown_not_recorded", "normalization_policy": None,
            "upstream_quantity_scale_status": "unknown_not_recorded",
            "batch_variation_corrected": False, "batch_correction_status": "not_performed",
            "injection_order_drift_correction_status": "not_performed",
            "ratio_track_interpretation": "protein_abundance_adjusted_relative_ptm_ratio_contrast"}
