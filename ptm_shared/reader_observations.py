"""Existing report observation helpers, shared without worker/LLM imports."""
from __future__ import annotations
import math
import re
from typing import Any, Iterable, Mapping
OBSERVED_PATTERN_VERSION = "observed_joint_pattern.v1"
TRAJECTORY_FACT_VERSION = "trajectory_shape_fact.v1"
DEFAULT_BASELINE_BAND_LOG2 = 0.15

def observed_time_minutes(point):
    """Parse elapsed time, never a sample-name rank. Unknown time stays unknown."""
    explicit = point.get("time_minutes")
    if explicit is not None:
        try:
            value = float(explicit)
            return value if math.isfinite(value) else None
        except (ValueError, TypeError):
            return None
    if point.get("elapsed_time") is not None and point.get("time_unit"):
        label = str(point["elapsed_time"]) + str(point["time_unit"])
    else:
        label = str(point.get("condition") or point.get("Condition") or "").strip()
    match = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*(s|sec|secs|seconds?|m|min|mins|minutes?|h|hr|hrs|hours?|d|days?)", label, re.I)
    if not match:
        return None
    unit = match[2].lower()
    scale = 1 / 60 if unit.startswith("s") else 60 if unit.startswith("h") else 1440 if unit.startswith("d") else 1
    return float(match[1]) * scale


def summarize_observed_pattern(points, *, value_key="ptm_relative_log2fc", tolerance=0.15):
    """Describe sampled levels; point-wise q values are never a pattern test."""
    rows = sorted(points, key=lambda p: (observed_time_minutes(p) if observed_time_minutes(p) is not None else math.inf, str(p.get("condition"))))
    valid = [p for p in rows if isinstance(p.get(value_key), (int, float)) and math.isfinite(p[value_key])]
    timed = [p for p in valid if observed_time_minutes(p) is not None]
    values = [p[value_key] for p in valid]
    label = "single-observation"
    if len(values) >= 2:
        if len(valid) != len(rows):
            label = "partial-observation"
        elif max(values) - min(values) <= 1e-9:
            label = "stable-near-reference" if abs(values[0]) <= 1e-9 else "constant-positive-level" if values[0] > 0 else "constant-negative-level"
        elif len(timed) != len(valid):
            label = "time-unavailable"
        elif sum(math.isclose(abs(v), max(map(abs, values)), abs_tol=1e-9) for v in values) > 1:
            label = "tied-observed-extrema"
        else:
            index = max(range(len(values)), key=lambda i: abs(values[i]))
            label = "early-maximal" if index == 0 else "late-maximal" if index == len(values) - 1 else "transient-intermediate"
    maxima = [p for p in timed if abs(p[value_key]) == max((abs(p[value_key]) for p in timed), default=0)]
    extrema = [{"condition": p.get("condition"), "time_minutes": observed_time_minutes(p),
                "value": p[value_key], "kind": "positive_observed_maximum" if p[value_key] > 0 else "negative_observed_trough" if p[value_key] < 0 else "zero_level"} for p in maxima]
    return {"contract_version": OBSERVED_PATTERN_VERSION, "label": label,
            "claim_scope": "descriptive_pattern", "pattern_q_value": None, "pattern_ci": None,
            "statistical_status": "no_pattern_level_test_supplied", "descriptive_tolerance": tolerance,
            "tolerance_source": "configurable_existing_quantitation_comparison_tolerance_not_significance",
            "observed_times_minutes": [observed_time_minutes(p) for p in timed],
            "unknown_time_conditions": [p.get("condition") for p in rows if observed_time_minutes(p) is None],
            "missing_conditions": [p.get("condition") for p in rows if p not in valid],
            "observed_extrema": extrema,
            "peak_status": "sampled_extrema_only_no_biological_peak_or_interpolation",
            "interpretation_boundary": "Observation-window description, not causal order, kinase activity, or population reproducibility."}


def joint_axis_pattern(axes, *, tolerance=0.15):
    """Classify already calculated U/P/A; this does not calculate an adjusted value."""
    u, p, a = [axes[key].get("value") for key in ("unadjusted", "protein", "adjusted")]
    if u is None or p is None or a is None:
        return "incomplete_axes_observation"
    near = lambda value: abs(value) <= tolerance
    if near(u) and p < -tolerance and a > tolerance:
        return "ptm_maintained_protein_decreased_adjusted_increased"
    if near(u - p) and near(a) and not near(u):
        return "ptm_protein_co_movement"
    if u > tolerance and near(p) and a > tolerance:
        return "ptm_increased_with_stable_protein"
    if near(u) and near(p) and near(a):
        return "near_reference_all_axes"
    return "joint_axis_change"


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def build_trajectory_shape_fact(
    points: Iterable[Mapping[str, Any]],
    *,
    axis: str = "ptm_protein_adjusted_log2fc",
    baseline_band_log2: float = DEFAULT_BASELINE_BAND_LOG2,
) -> dict[str, Any]:
    ordered: list[dict[str, Any]] = []
    for point in points:
        value = _finite(point.get(axis))
        if value is None or bool(point.get("detection_context_only")):
            continue
        ordered.append({"condition": str(point.get("condition") or "recorded condition"), "value": value})

    if len(ordered) < 2:
        return {
            "contract_version": TRAJECTORY_FACT_VERSION,
            "axis": axis,
            "classification": "insufficient_numeric_points",
            "baseline_band_log2": baseline_band_log2,
            "reader_summary": "The recorded trajectory did not contain enough conventional numeric points for a shape classification.",
            "monotonic_claim_allowed": False,
            "baseline_return_claim_allowed": False,
            "points": ordered,
        }

    values = [item["value"] for item in ordered]
    deltas = [right - left for left, right in zip(values, values[1:])]
    direction_steps = [
        1 if delta > baseline_band_log2 else -1 if delta < -baseline_band_log2 else 0
        for delta in deltas
    ]
    has_up = any(step > 0 for step in direction_steps)
    has_down = any(step < 0 for step in direction_steps)
    if has_up and has_down:
        classification = "non_monotonic"
    elif has_up:
        classification = "monotonic_increase"
    elif has_down:
        classification = "monotonic_decrease"
    else:
        classification = "approximately_stable_within_descriptive_band"

    excursions = [abs(value) > baseline_band_log2 for value in values]
    baseline_return_indices = [
        index for index, value in enumerate(values)
        if index > 0 and abs(value) <= baseline_band_log2 and any(excursions[:index])
    ]
    baseline_return_claim_allowed = bool(baseline_return_indices)
    extrema = {
        "maximum": {"condition": ordered[max(range(len(values)), key=values.__getitem__)]["condition"], "value": max(values)},
        "minimum": {"condition": ordered[min(range(len(values)), key=values.__getitem__)]["condition"], "value": min(values)},
    }
    axis_label = {
        "ptm_protein_adjusted_log2fc": "protein-adjusted PTM contrast",
        "ptm_unadjusted_log2fc": "unadjusted PTM contrast",
        "protein_log2fc": "linked protein contrast",
    }.get(axis, axis.replace("_", " "))
    point_text = "; ".join(f"{item['condition']} {item['value']:+.3f}" for item in ordered)
    if classification == "non_monotonic":
        interpretation = "showed a non-monotonic trajectory across the sampled conditions"
    elif classification == "monotonic_increase":
        interpretation = "increased monotonically within the pre-specified descriptive tolerance"
    elif classification == "monotonic_decrease":
        interpretation = "decreased monotonically within the pre-specified descriptive tolerance"
    else:
        interpretation = "remained within the pre-specified descriptive tolerance"
    return {
        "contract_version": TRAJECTORY_FACT_VERSION,
        "axis": axis,
        "classification": classification,
        "baseline_band_log2": baseline_band_log2,
        "reader_summary": f"The {axis_label} {interpretation}: {point_text}.",
        "monotonic_claim_allowed": classification in {"monotonic_increase", "monotonic_decrease"},
        "baseline_return_claim_allowed": baseline_return_claim_allowed,
        "baseline_return_conditions": [ordered[index]["condition"] for index in baseline_return_indices],
        "extrema": extrema,
        "points": ordered,
    }

