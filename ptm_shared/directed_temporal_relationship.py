"""Evidence-aware directionality analysis for Temporal PTM results.

The module intentionally distinguishes temporal precedence from causality.
It uses only observed time-course values for D0–D2 and accepts biological
support as a separate, optional input for D3. Intervention evidence is handled
by a later optional layer and is never inferred from observational trajectories.
"""

from __future__ import annotations

import math
import random
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np


CONTRACT_VERSION = "directed_temporal_relationship.v1"

DEFAULT_CONFIG: Dict[str, Any] = {
    "onset_threshold": 0.30,
    "simultaneous_tolerance_minutes": None,
    "minimum_timepoints": 3,
    "minimum_pairs_for_lag_similarity": 3,
    "minimum_lag_aware_similarity": 0.40,
    "bootstrap_iterations": 250,
    "permutation_iterations": 250,
    "random_seed": 20260813,
    "threshold_sensitivity_values": [0.20, 0.30, 0.50],
}


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


def timepoint_to_minutes(label: Any) -> float:
    """Normalize min/hour/day labels to minutes while preserving source labels."""
    text = str(label or "").strip().lower()
    match = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*(min|m|h|hr|hour|d|day)s?$", text)
    if match:
        value = float(match.group(1))
        unit = match.group(2)
        return value * 60.0 if unit in {"h", "hr", "hour"} else value * 1440.0 if unit in {"d", "day"} else value
    try:
        return float(text)
    except ValueError:
        return float("inf")


def _safe_correlation(left: Sequence[float], right: Sequence[float]) -> Optional[float]:
    if len(left) < 3 or len(left) != len(right):
        return None
    left_array = np.asarray(left, dtype=float)
    right_array = np.asarray(right, dtype=float)
    if not np.all(np.isfinite(left_array)) or not np.all(np.isfinite(right_array)):
        return None
    if float(np.std(left_array)) == 0.0 or float(np.std(right_array)) == 0.0:
        return None
    value = float(np.corrcoef(left_array, right_array)[0, 1])
    return value if math.isfinite(value) else None


def _effective_config(config: Optional[Mapping[str, Any]], minutes: Sequence[float]) -> Dict[str, Any]:
    merged = dict(DEFAULT_CONFIG)
    merged.update({key: value for key, value in dict(config or {}).items() if value is not None})
    merged["onset_threshold"] = max(0.0, _as_float(merged["onset_threshold"], 0.30))
    merged["minimum_timepoints"] = max(3, int(merged["minimum_timepoints"]))
    merged["minimum_pairs_for_lag_similarity"] = max(3, int(merged["minimum_pairs_for_lag_similarity"]))
    merged["minimum_lag_aware_similarity"] = max(0.0, min(1.0, _as_float(merged["minimum_lag_aware_similarity"], 0.40)))
    merged["bootstrap_iterations"] = max(0, int(merged["bootstrap_iterations"]))
    merged["permutation_iterations"] = max(0, int(merged["permutation_iterations"]))
    merged["random_seed"] = int(merged["random_seed"])
    ordered_minutes = sorted(set(minutes))
    gaps = [right - left for left, right in zip(ordered_minutes, ordered_minutes[1:]) if right > left]
    inferred_tolerance = min(gaps) / 2.0 if gaps else 0.0
    merged["simultaneous_tolerance_minutes"] = max(
        0.0, _as_float(merged.get("simultaneous_tolerance_minutes"), inferred_tolerance)
    )
    thresholds = merged.get("threshold_sensitivity_values") or []
    merged["threshold_sensitivity_values"] = sorted({max(0.0, _as_float(value)) for value in thresholds} | {merged["onset_threshold"]})
    return merged


def _first_onset(minutes: Sequence[float], values: Sequence[float], threshold: float) -> Optional[float]:
    for minute, value in zip(minutes, values):
        if abs(float(value)) >= threshold:
            return float(minute)
    return None


def _peak_time(minutes: Sequence[float], values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    return float(minutes[int(np.argmax(np.abs(np.asarray(values, dtype=float))))])


def _lag_aware_similarity(
    minutes: Sequence[float], source_values: Sequence[float], target_values: Sequence[float], minimum_pairs: int
) -> Dict[str, Any]:
    """Find the physical time lag with strongest profile similarity.

    Positive lag means the target profile is aligned at later minutes than the
    source. This is evidence for temporal order only, never a causal assertion.
    """
    if len(minutes) < minimum_pairs:
        return {"best_lag_minutes": None, "best_similarity": None, "zero_lag_similarity": None, "paired_points": 0}
    ordered_minutes = sorted(set(float(value) for value in minutes))
    gaps = [right - left for left, right in zip(ordered_minutes, ordered_minutes[1:]) if right > left]
    tolerance = min(gaps) / 2.0 if gaps else 0.0
    candidates = sorted({right - left for left in minutes for right in minutes})
    observed: List[Tuple[float, float, int]] = []
    for lag in candidates:
        source_pairs: List[float] = []
        target_pairs: List[float] = []
        for source_index, source_time in enumerate(minutes):
            expected_target_time = source_time + lag
            target_indices = [
                target_index for target_index, actual_time in enumerate(minutes)
                if abs(actual_time - expected_target_time) <= tolerance + 1e-9
            ]
            if not target_indices:
                continue
            target_index = min(target_indices, key=lambda index: abs(minutes[index] - expected_target_time))
            source_pairs.append(float(source_values[source_index]))
            target_pairs.append(float(target_values[target_index]))
        similarity = _safe_correlation(source_pairs, target_pairs)
        if similarity is not None:
            observed.append((float(lag), similarity, len(source_pairs)))
    zero_lag = next((similarity for lag, similarity, _ in observed if abs(lag) <= 1e-9), None)
    if not observed:
        return {"best_lag_minutes": None, "best_similarity": None, "zero_lag_similarity": None, "paired_points": 0}
    best_lag, best_similarity, pairs = max(observed, key=lambda item: (abs(item[1]), item[2], -abs(item[0])))
    return {
        "best_lag_minutes": round(best_lag, 6),
        "best_similarity": round(best_similarity, 6),
        "zero_lag_similarity": round(zero_lag, 6) if zero_lag is not None else None,
        "paired_points": pairs,
    }


def _direction_from_lags(
    onset_lag: Optional[float], peak_lag: Optional[float], best_lag: Optional[float], config: Mapping[str, Any]
) -> Tuple[str, float, List[str]]:
    flags: List[str] = []
    if onset_lag is None or peak_lag is None:
        return "unresolved", 0.0, ["missing_onset_or_peak"]
    tolerance = float(config["simultaneous_tolerance_minutes"])
    signs = [
        1 if onset_lag > tolerance else -1 if onset_lag < -tolerance else 0,
        1 if peak_lag > tolerance else -1 if peak_lag < -tolerance else 0,
        0 if best_lag is None or abs(best_lag) <= tolerance else 1 if best_lag > 0 else -1,
    ]
    positive = sum(sign == 1 for sign in signs)
    negative = sum(sign == -1 for sign in signs)
    if positive >= 2 and negative == 0:
        return "source_precedes_target", positive / 3.0, flags
    if negative >= 2 and positive == 0:
        return "target_precedes_source", negative / 3.0, flags
    if signs[0] == 0 and signs[1] == 0:
        return "simultaneous", 1.0, flags
    return "unresolved", max(positive, negative) / 3.0, ["onset_peak_lag_disagreement"]


def _core(source_values: Sequence[float], target_values: Sequence[float], minutes: Sequence[float], config: Mapping[str, Any]) -> Dict[str, Any]:
    source_onset = _first_onset(minutes, source_values, float(config["onset_threshold"]))
    target_onset = _first_onset(minutes, target_values, float(config["onset_threshold"]))
    source_peak = _peak_time(minutes, source_values)
    target_peak = _peak_time(minutes, target_values)
    onset_lag = target_onset - source_onset if source_onset is not None and target_onset is not None else None
    peak_lag = target_peak - source_peak if source_peak is not None and target_peak is not None else None
    similarity = _lag_aware_similarity(minutes, source_values, target_values, int(config["minimum_pairs_for_lag_similarity"]))
    direction, score, flags = _direction_from_lags(onset_lag, peak_lag, similarity["best_lag_minutes"], config)
    if similarity["best_similarity"] is None or abs(float(similarity["best_similarity"])) < float(config["minimum_lag_aware_similarity"]):
        flags.append("weak_lag_aware_similarity")
    return {
        "direction": direction,
        "temporal_order_score": round(score, 6),
        "source_onset_minutes": source_onset,
        "target_onset_minutes": target_onset,
        "onset_lag_minutes": round(onset_lag, 6) if onset_lag is not None else None,
        "source_peak_minutes": source_peak,
        "target_peak_minutes": target_peak,
        "peak_lag_minutes": round(peak_lag, 6) if peak_lag is not None else None,
        "lag_aware_similarity": similarity,
        "quality_flags": flags,
    }


def _bootstrap(
    source_replicates: Optional[Mapping[str, Sequence[Any]]],
    target_replicates: Optional[Mapping[str, Sequence[Any]]],
    timepoints: Sequence[str],
    minutes: Sequence[float],
    config: Mapping[str, Any],
) -> Dict[str, Any]:
    if not isinstance(source_replicates, Mapping) or not isinstance(target_replicates, Mapping):
        return {"available": False, "reason": "replicate_level_values_unavailable", "stability": None, "peak_lag_ci_minutes": None}
    if any(not source_replicates.get(tp) or not target_replicates.get(tp) for tp in timepoints):
        return {"available": False, "reason": "incomplete_replicate_coverage", "stability": None, "peak_lag_ci_minutes": None}
    iterations = int(config["bootstrap_iterations"])
    if iterations <= 0:
        return {"available": False, "reason": "bootstrap_disabled", "stability": None, "peak_lag_ci_minutes": None}
    generator = random.Random(int(config["random_seed"]))
    directions: List[str] = []
    peak_lags: List[float] = []
    for _ in range(iterations):
        source = [float(np.mean([_as_float(generator.choice(list(source_replicates[tp]))) for _ in range(len(source_replicates[tp]))])) for tp in timepoints]
        target = [float(np.mean([_as_float(generator.choice(list(target_replicates[tp]))) for _ in range(len(target_replicates[tp]))])) for tp in timepoints]
        relation = _core(source, target, minutes, config)
        directions.append(relation["direction"])
        if relation["peak_lag_minutes"] is not None:
            peak_lags.append(float(relation["peak_lag_minutes"]))
    modal = max(set(directions), key=directions.count) if directions else "unresolved"
    ci = [float(np.percentile(peak_lags, 2.5)), float(np.percentile(peak_lags, 97.5))] if len(peak_lags) >= 2 else None
    return {
        "available": True,
        "iterations": iterations,
        "modal_direction": modal,
        "stability": round(directions.count(modal) / len(directions), 6) if directions else None,
        "peak_lag_ci_minutes": [round(value, 6) for value in ci] if ci else None,
    }


def _leave_one_out(source: Sequence[float], target: Sequence[float], minutes: Sequence[float], config: Mapping[str, Any], reference: str) -> Dict[str, Any]:
    if len(minutes) < 4:
        return {"available": False, "reason": "fewer_than_four_timepoints", "stability": None}
    directions = []
    for omitted in range(len(minutes)):
        keep = [index for index in range(len(minutes)) if index != omitted]
        directions.append(_core([source[index] for index in keep], [target[index] for index in keep], [minutes[index] for index in keep], config)["direction"])
    return {"available": True, "directions": directions, "stability": round(sum(direction == reference for direction in directions) / len(directions), 6)}


def _permutation(source: Sequence[float], target: Sequence[float], minutes: Sequence[float], config: Mapping[str, Any], observed_score: float) -> Dict[str, Any]:
    iterations = int(config["permutation_iterations"])
    if len(minutes) < 4 or iterations <= 0:
        return {"available": False, "reason": "insufficient_timepoints_or_permutation_disabled", "p_value": None}
    generator = random.Random(int(config["random_seed"]) + 1)
    null_scores = []
    for _ in range(iterations):
        shuffled = list(target)
        generator.shuffle(shuffled)
        null_scores.append(float(_core(source, shuffled, minutes, config)["temporal_order_score"]))
    return {
        "available": True,
        "iterations": iterations,
        "seed": int(config["random_seed"]) + 1,
        "null_score_mean": round(float(np.mean(null_scores)), 6),
        "p_value": round((1 + sum(score >= observed_score for score in null_scores)) / (1 + len(null_scores)), 6),
    }


def _tier(core: Mapping[str, Any], bootstrap: Mapping[str, Any], leave_one_out: Mapping[str, Any], permutation: Mapping[str, Any], biological_support: Mapping[str, Any]) -> Tuple[str, List[str]]:
    flags = list(core.get("quality_flags") or [])
    if core.get("direction") in {"unresolved", "simultaneous"}:
        return "D0_unresolved", flags
    tier = "D1_temporal_precedence"
    bootstrap_stability = bootstrap.get("stability")
    leave_one_out_stability = leave_one_out.get("stability")
    p_value = permutation.get("p_value")
    reproducible = (
        bootstrap.get("available") is True
        and bootstrap_stability is not None
        and float(bootstrap_stability) >= 0.70
        and permutation.get("available") is True
        and p_value is not None
        and float(p_value) <= 0.05
        and (leave_one_out_stability is None or float(leave_one_out_stability) >= 0.70)
    )
    if reproducible:
        tier = "D2_reproducible_directionality"
    else:
        if bootstrap.get("available") is not True:
            flags.append("replicate_bootstrap_not_available")
        elif bootstrap_stability is None or float(bootstrap_stability) < 0.70:
            flags.append("replicate_directionality_stability_below_threshold")
        if permutation.get("available") is not True or p_value is None:
            flags.append("time_order_permutation_not_available")
        elif float(p_value) > 0.05:
            flags.append("time_order_not_distinguishable_from_permutation_null")
        if leave_one_out_stability is not None and float(leave_one_out_stability) < 0.70:
            flags.append("leave_one_timepoint_stability_below_threshold")
    supported = any(bool(biological_support.get(key)) for key in ("kinase_substrate_consistent", "motif_consistent", "ppi_consistent", "chromadb_consistent"))
    if tier == "D2_reproducible_directionality" and supported:
        tier = "D3_mechanistically_supported_directionality"
    return tier, sorted(set(flags))


def analyze_directed_temporal_relationship(
    source: Mapping[str, Any],
    target: Mapping[str, Any],
    timepoints: Sequence[str],
    *,
    config: Optional[Mapping[str, Any]] = None,
    biological_support: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Return a DirectedTemporalRelationship with no causal conclusion.

    ``source`` and ``target`` use ``{key, temporal_values, replicates?}``.
    Replicates are optional. Their absence is explicitly recorded, never
    silently replaced with artificial stability estimates.
    """
    ordered = sorted({str(tp) for tp in timepoints}, key=lambda tp: (timepoint_to_minutes(tp), tp))
    minutes = [timepoint_to_minutes(tp) for tp in ordered]
    support = dict(biological_support or {})
    result: Dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "source": {"key": str(source.get("key") or "unknown")},
        "target": {"key": str(target.get("key") or "unknown")},
        "timepoints": ordered,
        "timepoint_minutes": minutes,
        "causality_status": "not_tested",
        "biological_support": support,
        "interpretation_boundary": "Temporal precedence evidence only; no causal intervention was evaluated.",
    }
    effective = _effective_config(config, minutes) if all(math.isfinite(value) for value in minutes) else None
    source_mapping = source.get("temporal_values") if isinstance(source.get("temporal_values"), Mapping) else source
    target_mapping = target.get("temporal_values") if isinstance(target.get("temporal_values"), Mapping) else target
    source_values = [_as_float(source_mapping.get(tp), float("nan")) for tp in ordered]
    target_values = [_as_float(target_mapping.get(tp), float("nan")) for tp in ordered]
    if effective is None or len(ordered) < int(effective["minimum_timepoints"]) or not all(math.isfinite(value) for value in source_values + target_values):
        result.update({"direction": "unresolved", "directionality_tier": "D0_unresolved", "quality_flags": ["insufficient_or_unparseable_timepoints_or_values"], "evidence_profile": {"replicate_stability": None, "leave_one_timepoint_stability": None, "time_permutation_p_value": None}})
        return result
    core = _core(source_values, target_values, minutes, effective)
    bootstrap = _bootstrap(source.get("replicates"), target.get("replicates"), ordered, minutes, effective)
    leave_one_out = _leave_one_out(source_values, target_values, minutes, effective, str(core["direction"]))
    permutation = _permutation(source_values, target_values, minutes, effective, float(core["temporal_order_score"]))
    sensitivity = []
    for threshold in effective["threshold_sensitivity_values"]:
        threshold_config = dict(effective)
        threshold_config["onset_threshold"] = threshold
        alternative = _core(source_values, target_values, minutes, threshold_config)
        sensitivity.append({"onset_threshold": threshold, "direction": alternative["direction"], "onset_lag_minutes": alternative["onset_lag_minutes"], "peak_lag_minutes": alternative["peak_lag_minutes"]})
    tier, flags = _tier(core, bootstrap, leave_one_out, permutation, support)
    result.update(core)
    result.update({
        "directionality_tier": tier,
        "quality_flags": flags,
        "evidence_profile": {
            "replicate_stability": bootstrap.get("stability"),
            "bootstrap": bootstrap,
            "leave_one_timepoint_stability": leave_one_out.get("stability"),
            "leave_one_timepoint": leave_one_out,
            "time_permutation_p_value": permutation.get("p_value"),
            "time_permutation": permutation,
            "threshold_sensitivity": sensitivity,
            "time_resolution_minutes": [right - left for left, right in zip(sorted(set(minutes)), sorted(set(minutes))[1:]) if right > left],
        },
        "config_provenance": {
            "onset_threshold": effective["onset_threshold"],
            "simultaneous_tolerance_minutes": effective["simultaneous_tolerance_minutes"],
            "bootstrap_iterations": effective["bootstrap_iterations"],
            "permutation_iterations": effective["permutation_iterations"],
            "random_seed": effective["random_seed"],
        },
    })
    return result


def validate_directed_temporal_relationship(result: Mapping[str, Any]) -> List[str]:
    """Validate minimal contract invariants without requiring perturbation data."""
    errors: List[str] = []
    if result.get("contract_version") != CONTRACT_VERSION:
        errors.append("invalid_contract_version")
    if result.get("causality_status") != "not_tested" and not result.get("perturbation_evidence"):
        errors.append("causality_status_requires_perturbation_evidence")
    if result.get("directionality_tier") not in {
        "D0_unresolved", "D1_temporal_precedence", "D2_reproducible_directionality", "D3_mechanistically_supported_directionality"
    }:
        errors.append("invalid_directionality_tier")
    return errors
