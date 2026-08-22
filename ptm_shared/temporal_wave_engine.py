"""Canonical Temporal Wave Contract v1.

This module is the single computational source of truth for Temporal PTM Wave
detection.  It intentionally contains no database, LLM, enrichment, or UI
dependencies so that API, RAG, and report-generation paths receive identical
wave memberships and provenance from the same condition-level input vectors.

The contract distinguishes measured temporal evidence from downstream
biological interpretation.  A returned wave is a co-moving PTM group, not a
causal signaling claim.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

from ptm_shared.substrate_temporal_dynamics import describe_member_dynamics, summarise_member_pattern_distribution


CONTRACT_VERSION = "temporal_wave_contract.v1"
ENGINE_VERSION = "1.0.0"

DEFAULT_CONFIG: Dict[str, Any] = {
    "correlation_threshold": 0.70,
    "threshold_source": "default",
    "minimum_timepoints": 3,
    "minimum_variance": 0.30,
    "minimum_amplitude": 0.80,
    "minimum_cluster_size": 2,
    "maximum_waves": 8,
    "missing_value": 0.0,
}


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


def _time_minutes(label: str) -> float:
    """Parse standard timepoint labels without imposing experiment-specific bins."""
    text = str(label or "").strip().lower()
    if not text:
        return float("inf")
    import re

    match = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*(min|m|h|hr|hour|d|day)s?$", text)
    if match:
        value = float(match.group(1))
        unit = match.group(2)
        if unit in {"h", "hr", "hour"}:
            return value * 60.0
        if unit in {"d", "day"}:
            return value * 1440.0
        return value
    try:
        return float(text)
    except ValueError:
        return float("inf")


def _config_with_provenance(config: Optional[Mapping[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Normalize config and make each threshold decision reproducible."""
    merged = dict(DEFAULT_CONFIG)
    explicit = dict(config or {})
    for key in DEFAULT_CONFIG:
        if key in explicit and explicit[key] is not None:
            merged[key] = explicit[key]

    threshold = max(0.0, min(1.0, _as_float(merged["correlation_threshold"], 0.70)))
    merged["correlation_threshold"] = threshold
    merged["minimum_timepoints"] = max(2, int(merged["minimum_timepoints"]))
    merged["minimum_cluster_size"] = max(2, int(merged["minimum_cluster_size"]))
    merged["maximum_waves"] = max(1, int(merged["maximum_waves"]))
    merged["minimum_variance"] = max(0.0, _as_float(merged["minimum_variance"], 0.30))
    merged["minimum_amplitude"] = max(0.0, _as_float(merged["minimum_amplitude"], 0.80))
    merged["missing_value"] = _as_float(merged["missing_value"], 0.0)

    serialized = json.dumps(merged, sort_keys=True, separators=(",", ":"))
    provenance = {
        "contract_version": CONTRACT_VERSION,
        "engine_version": ENGINE_VERSION,
        "correlation_threshold": threshold,
        "threshold_source": str(explicit.get("threshold_source", merged["threshold_source"])),
        "minimum_timepoints": merged["minimum_timepoints"],
        "minimum_variance": merged["minimum_variance"],
        "minimum_amplitude": merged["minimum_amplitude"],
        "minimum_cluster_size": merged["minimum_cluster_size"],
        "maximum_waves": merged["maximum_waves"],
        "distance_metric": "signed_pearson_distance=1-r",
        "linkage": "average",
        "missing_value_policy": "explicit_fill",
        "config_sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
    }
    return merged, provenance


def _classify_pattern(profiles: np.ndarray) -> str:
    """Classify observed trajectories without asserting upstream causality."""
    mean_profile = np.mean(profiles, axis=0)
    if mean_profile.size == 0:
        return "insufficient_data"

    max_value = float(np.max(np.abs(mean_profile)))
    if max_value == 0:
        return "flat"

    positive = int(np.sum(mean_profile > 0.5))
    negative = int(np.sum(mean_profile < -0.5))
    above_half = int(np.sum(np.abs(mean_profile) > max_value * 0.5))
    spike_ratio = above_half / len(mean_profile)
    sustained_ratio = int(np.sum(np.abs(mean_profile) > 1.0)) / len(mean_profile)
    signs = np.sign(mean_profile[np.abs(mean_profile) > 0.5])
    sign_changes = int(np.sum(signs[1:] * signs[:-1] < 0)) if len(signs) > 1 else 0
    peak_indices = np.argmax(np.abs(profiles), axis=1)
    peak_spread = int(np.max(peak_indices) - np.min(peak_indices)) if len(peak_indices) else 0

    if sign_changes:
        return "biphasic_switch"
    if peak_spread >= 3 and len(profiles) >= 3:
        return "sequential_wave"
    if spike_ratio <= 0.4 and max_value > 3:
        return "transient_burst" if positive > negative else "transient_suppression"
    if sustained_ratio >= 0.6:
        return "sustained_activation" if positive > negative else "sustained_inhibition"
    if positive > negative:
        return "co_activated"
    if negative > positive:
        return "co_inhibited"
    return "mixed_response"


def _evidence_tier(coherence: float, direction_consistency: float, member_count: int) -> str:
    """Assign an evidence tier from measured structure only, not biology or literature."""
    if member_count >= 4 and coherence >= 0.85 and direction_consistency >= 0.80:
        return "high_structural_evidence"
    if member_count >= 2 and coherence >= 0.70 and direction_consistency >= 0.65:
        return "moderate_structural_evidence"
    return "exploratory_structural_evidence"


def _member_detail(
    site_key: str,
    values: np.ndarray,
    timepoints: Sequence[str],
    metadata: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    meta = dict(metadata.get(site_key, {}))
    peak_idx = int(np.argmax(np.abs(values)))
    float_values: List[Optional[float]] = [float(v) for v in values]
    q_per_tp: Optional[List[Optional[float]]] = None
    if "q_values_per_tp" in meta:
        q_per_tp = meta["q_values_per_tp"]
    site_dynamics = describe_member_dynamics(list(timepoints), float_values, q_values=q_per_tp)
    return {
        "key": site_key,
        "gene": meta.get("gene", site_key.split("(")[0].split(" ")[0]),
        "site": meta.get("site", ""),
        "temporal_values": {tp: round(float(values[index]), 6) for index, tp in enumerate(timepoints)},
        "max_fc": round(float(np.max(np.abs(values))), 6),
        "peak_tp": timepoints[peak_idx],
        "peak_index": peak_idx,
        "activity_class": meta.get("activity_class", "minor"),
        "q_value": meta.get("q_value"),
        "control_pseudocount_used": bool(meta.get("control_pseudocount_used", False)),
        "candidate_kinases": list(meta.get("candidate_kinases", [])),
        "site_dynamics": site_dynamics,
    }


def _build_wave(
    wave_index: int,
    row_indices: Sequence[int],
    matrix: np.ndarray,
    site_keys: Sequence[str],
    timepoints: Sequence[str],
    corr: np.ndarray,
    metadata: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    profiles = matrix[list(row_indices)]
    details = [_member_detail(site_keys[index], matrix[index], timepoints, metadata) for index in row_indices]
    mean_profile = np.mean(profiles, axis=0)
    peak_index = int(np.argmax(np.abs(mean_profile)))
    pairwise = [
        corr[row_indices[left_position], right_index]
        for left_position in range(len(row_indices))
        for right_index in row_indices[left_position + 1 :]
    ]
    coherence = float(np.mean(pairwise)) if pairwise else 1.0
    peak_indices = np.argmax(np.abs(profiles), axis=1)
    peak_dispersion = float(np.std(peak_indices)) if len(peak_indices) else 0.0
    dominant_sign = 1 if mean_profile[peak_index] >= 0 else -1
    member_peak_signs = np.sign(profiles[np.arange(len(profiles)), peak_indices])
    direction_consistency = float(np.mean(member_peak_signs == dominant_sign)) if len(member_peak_signs) else 0.0
    amplitudes = np.max(np.abs(profiles), axis=1)
    activity_counts: Dict[str, int] = {"de_novo": 0, "regulated": 0, "minor": 0}
    for detail in details:
        activity = detail["activity_class"]
        activity_counts[activity] = activity_counts.get(activity, 0) + 1
    dominant_activity = "de_novo" if activity_counts.get("de_novo", 0) else (
        "regulated" if activity_counts.get("regulated", 0) else "minor"
    )
    evidence = {
        "temporal_coherence": round(coherence, 6),
        "direction_consistency": round(direction_consistency, 6),
        "peak_dispersion_timepoints": round(peak_dispersion, 6),
        "median_member_amplitude": round(float(np.median(amplitudes)), 6),
        "member_count": len(details),
        "replicate_stability": None,
        "dataset_reproducibility": None,
        "lag_evidence": None,
        "kinase_enrichment": None,
        "pathway_enrichment": None,
        "prior_agreement": None,
        "prior_conflict": None,
        "evidence_tier": _evidence_tier(coherence, direction_consistency, len(details)),
        "interpretation_boundary": "Structural co-movement evidence only; not causal evidence.",
    }
    wave_id = f"TW-{wave_index:02d}"
    member_dynamics_list = [d.get("site_dynamics") for d in details if d.get("site_dynamics")]
    member_pattern_summary = summarise_member_pattern_distribution(member_dynamics_list)
    return {
        "wave_id": wave_id,
        "cluster_id": wave_index,
        "members": [detail["key"] for detail in details],
        "member_count": len(details),
        "member_details": details,
        "pattern": _classify_pattern(profiles),
        "member_pattern_summary": member_pattern_summary,
        "peak_timepoint": timepoints[peak_index],
        "peak_index": peak_index,
        "mean_profile": {tp: round(float(mean_profile[index]), 6) for index, tp in enumerate(timepoints)},
        "correlation_mean": round(coherence, 6),
        "activity_class_counts": activity_counts,
        "dominant_activity_class": dominant_activity,
        "evidence_profile": evidence,
    }


def analyze_temporal_waves(
    site_time_series: Mapping[str, Mapping[str, Any]],
    timepoints: Sequence[str],
    *,
    metadata: Optional[Mapping[str, Mapping[str, Any]]] = None,
    config: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Return a reproducible canonical Temporal Wave Contract.

    `site_time_series` must be a condition-level, protein-normalized PTM
    measurement mapping: ``{site_key: {timepoint: log2fc}}``. Missing values
    are recorded and filled only according to the explicit contract policy.
    """
    effective_config, provenance = _config_with_provenance(config)
    metadata = metadata or {}
    ordered_timepoints = sorted({str(tp) for tp in timepoints}, key=lambda tp: (_time_minutes(tp), tp))
    result: Dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "engine_version": ENGINE_VERSION,
        "timepoints": ordered_timepoints,
        "threshold_provenance": provenance,
        "waves": [],
        "directed_relationships": [],
        "unassigned_sites": [],
        "excluded_sites": [],
        "summary": {},
        "quality_warnings": [],
    }
    if len(ordered_timepoints) < effective_config["minimum_timepoints"]:
        result["quality_warnings"].append("insufficient_timepoints")
        result["summary"] = {"total_input_sites": len(site_time_series), "eligible_sites": 0, "num_waves": 0}
        return result

    site_keys: List[str] = []
    rows: List[List[float]] = []
    missing_counts: Dict[str, int] = {}
    for site_key in sorted(site_time_series):
        values = site_time_series[site_key]
        if not isinstance(values, Mapping):
            result["excluded_sites"].append({"key": site_key, "reason": "invalid_time_series"})
            continue
        missing = sum(1 for tp in ordered_timepoints if values.get(tp) is None)
        vector = [_as_float(values.get(tp), effective_config["missing_value"]) for tp in ordered_timepoints]
        variance = float(np.var(vector))
        amplitude = float(np.max(np.abs(vector))) if vector else 0.0
        if variance < effective_config["minimum_variance"] and amplitude < effective_config["minimum_amplitude"]:
            result["excluded_sites"].append({
                "key": site_key,
                "reason": "below_variance_and_amplitude_threshold",
                "variance": round(variance, 6),
                "amplitude": round(amplitude, 6),
            })
            continue
        site_keys.append(site_key)
        rows.append(vector)
        missing_counts[site_key] = missing

    if len(rows) < 2:
        result["quality_warnings"].append("fewer_than_two_eligible_sites")
        result["summary"] = {
            "total_input_sites": len(site_time_series),
            "eligible_sites": len(rows),
            "num_waves": 0,
        }
        return result

    matrix = np.asarray(rows, dtype=float)
    standardized = matrix - matrix.mean(axis=1, keepdims=True)
    standard_deviation = matrix.std(axis=1, keepdims=True)
    standard_deviation[standard_deviation == 0] = 1.0
    standardized = standardized / standard_deviation
    correlation = np.clip((standardized @ standardized.T) / matrix.shape[1], -1.0, 1.0)
    np.fill_diagonal(correlation, 1.0)
    distance = np.maximum((1.0 - correlation + (1.0 - correlation).T) / 2.0, 0.0)
    np.fill_diagonal(distance, 0.0)
    linkage_matrix = linkage(squareform(distance, checks=False), method="average")
    labels = fcluster(linkage_matrix, t=1.0 - effective_config["correlation_threshold"], criterion="distance")

    groups: Dict[int, List[int]] = defaultdict(list)
    for index, label in enumerate(labels):
        groups[int(label)].append(index)
    wave_rows: List[Tuple[List[int], Dict[str, Any]]] = []
    unassigned: List[Dict[str, Any]] = []
    for indices in groups.values():
        if len(indices) < effective_config["minimum_cluster_size"]:
            unassigned.extend(_member_detail(site_keys[index], matrix[index], ordered_timepoints, metadata) for index in indices)
            continue
        wave_rows.append((indices, _build_wave(0, indices, matrix, site_keys, ordered_timepoints, correlation, metadata)))
    wave_rows.sort(key=lambda item: (-item[1]["member_count"], item[1]["members"]))
    retained = wave_rows[: effective_config["maximum_waves"]]
    for indices, _ in wave_rows[effective_config["maximum_waves"] :]:
        unassigned.extend(_member_detail(site_keys[index], matrix[index], ordered_timepoints, metadata) for index in indices)
    waves = [_build_wave(index + 1, indices, matrix, site_keys, ordered_timepoints, correlation, metadata) for index, (indices, _) in enumerate(retained)]
    # P1: Wave membership remains structural, while between-wave temporal order
    # is represented as a separate, explicitly non-causal evidence contract.
    try:
        from ptm_shared.directed_temporal_relationship import analyze_directed_temporal_relationship

        relationships = []
        for source_index, source_wave in enumerate(waves):
            for target_wave in waves[source_index + 1 :]:
                relation = analyze_directed_temporal_relationship(
                    {"key": source_wave["wave_id"], "temporal_values": source_wave["mean_profile"]},
                    {"key": target_wave["wave_id"], "temporal_values": target_wave["mean_profile"]},
                    ordered_timepoints,
                )
                relation["source"]["wave_id"] = source_wave["wave_id"]
                relation["target"]["wave_id"] = target_wave["wave_id"]
                relationships.append(relation)
        result["directed_relationships"] = relationships
        for wave in waves:
            related = [
                relation for relation in relationships
                if relation["source"].get("wave_id") == wave["wave_id"]
                or relation["target"].get("wave_id") == wave["wave_id"]
            ]
            wave["evidence_profile"]["directionality_relations"] = [
                {
                    "counterpart_wave_id": (
                        relation["target"]["wave_id"]
                        if relation["source"].get("wave_id") == wave["wave_id"]
                        else relation["source"]["wave_id"]
                    ),
                    "direction": relation["direction"],
                    "directionality_tier": relation["directionality_tier"],
                    "onset_lag_minutes": relation.get("onset_lag_minutes"),
                    "peak_lag_minutes": relation.get("peak_lag_minutes"),
                }
                for relation in related
            ]
    except Exception as directionality_error:
        result["quality_warnings"].append("directionality_engine_unavailable")
        result["directionality_warning"] = str(directionality_error)
    result["waves"] = waves
    result["unassigned_sites"] = unassigned
    result["summary"] = {
        "total_input_sites": len(site_time_series),
        "eligible_sites": len(site_keys),
        "excluded_sites": len(result["excluded_sites"]),
        "unassigned_sites": len(unassigned),
        "num_waves": len(waves),
        "wave_sizes": [wave["member_count"] for wave in waves],
        "missing_values_filled": sum(missing_counts.values()),
        "analysis_scope": "condition_level_protein_normalized_ptm_log2fc",
    }
    if result["summary"]["missing_values_filled"]:
        result["quality_warnings"].append("missing_values_filled_by_contract_policy")
    return result


def build_input_from_vector_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    condition_key: str = "condition",
    value_key: str = "ptm_relative_log2fc",
) -> Tuple[Dict[str, Dict[str, float]], List[str], Dict[str, Dict[str, Any]]]:
    """Build canonical input from API vector-plot rows without dataset-specific fields."""
    grouped: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    metadata: Dict[str, Dict[str, Any]] = {}
    timepoints: set[str] = set()
    for row in rows:
        condition = str(row.get(condition_key) or "").strip()
        gene = str(row.get("gene") or row.get("Gene.Name") or "").strip()
        site = str(row.get("position") or row.get("site") or row.get("PTM_Position") or "").strip()
        if not condition or not gene:
            continue
        site_key = f"{gene} {site}".strip()
        grouped[site_key][condition].append(_as_float(row.get(value_key)))
        timepoints.add(condition)
        meta = metadata.setdefault(site_key, {"gene": gene, "site": site})
        meta["activity_class"] = row.get("activity_class", meta.get("activity_class", "minor"))
        meta["q_value"] = row.get("q_value", meta.get("q_value"))
        meta["control_pseudocount_used"] = bool(row.get("control_pseudocount_used", meta.get("control_pseudocount_used", False)))
        candidates = row.get("candidate_kinases") or row.get("kinases") or []
        if isinstance(candidates, str):
            candidates = [part.strip() for part in candidates.replace("|", ";").split(";") if part.strip()]
        if isinstance(candidates, list):
            meta["candidate_kinases"] = sorted(set(meta.get("candidate_kinases", [])) | set(map(str, candidates)))
    series = {
        site_key: {condition: float(np.mean(values)) for condition, values in condition_values.items()}
        for site_key, condition_values in grouped.items()
    }
    return series, sorted(timepoints, key=lambda tp: (_time_minutes(tp), tp)), metadata


def validate_temporal_wave_contract(result: Mapping[str, Any]) -> List[str]:
    """Return contract validation errors; an empty list means a valid v1 result."""
    errors: List[str] = []
    if result.get("contract_version") != CONTRACT_VERSION:
        errors.append("invalid_contract_version")
    if not isinstance(result.get("threshold_provenance"), Mapping):
        errors.append("missing_threshold_provenance")
    if not isinstance(result.get("waves"), list):
        errors.append("waves_must_be_list")
        return errors
    wave_ids: set[str] = set()
    for wave in result["waves"]:
        wave_id = wave.get("wave_id")
        if not wave_id or wave_id in wave_ids:
            errors.append("missing_or_duplicate_wave_id")
        wave_ids.add(wave_id)
        if not isinstance(wave.get("evidence_profile"), Mapping):
            errors.append(f"missing_evidence_profile:{wave_id}")
        if not wave.get("members"):
            errors.append(f"empty_wave:{wave_id}")
    return errors
