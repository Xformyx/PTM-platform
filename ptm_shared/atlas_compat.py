"""Compatibility helpers for Temporal Atlas order artifacts.

Atlas must remain readable for orders created before form-aware trajectories
were introduced.  These helpers normalize only structural legacy variants and
replace non-finite numeric values before a FastAPI JSON response is emitted.
They never manufacture kinetic observations.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any


def atlas_records(payload: Any) -> list[dict[str, Any]]:
    """Return mapping records from current or common legacy enriched payloads."""
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, Mapping)]
    if isinstance(payload, Mapping):
        for key in ("ptms", "enriched_ptms", "data", "records", "items"):
            nested = payload.get(key)
            if isinstance(nested, list):
                return [dict(item) for item in nested if isinstance(item, Mapping)]
    return []


def atlas_form_trajectories(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Normalize current and legacy form trajectories to mapping records only."""
    raw_forms = record.get("site_form_trajectories")
    if isinstance(raw_forms, Mapping):
        raw_forms = raw_forms.get("forms") or raw_forms.get("site_forms") or []
    if not isinstance(raw_forms, list):
        raw_forms = []

    forms: list[dict[str, Any]] = []
    for raw_form in raw_forms:
        if not isinstance(raw_form, Mapping):
            continue
        form = dict(raw_form)
        trajectory = form.get("trajectory")
        if not isinstance(trajectory, Mapping):
            trajectory = form.get("trajectory_data")
        if not isinstance(trajectory, Mapping):
            continue
        timepoints = trajectory.get("timepoints")
        if not isinstance(timepoints, list):
            continue
        form["trajectory"] = {
            **dict(trajectory),
            "timepoints": [dict(point) for point in timepoints if isinstance(point, Mapping)],
        }
        forms.append(form)

    if forms:
        return forms

    trajectory = record.get("trajectory")
    if isinstance(trajectory, Mapping) and isinstance(trajectory.get("timepoints"), list):
        return [{
            **dict(record),
            "trajectory": {
                **dict(trajectory),
                "timepoints": [dict(point) for point in trajectory["timepoints"] if isinstance(point, Mapping)],
            },
        }]
    return []


def json_safe(value: Any) -> Any:
    """Recursively convert response payloads to strict JSON-compatible values."""
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if hasattr(value, "item"):
        try:
            return json_safe(value.item())
        except (TypeError, ValueError):
            pass
    return value
