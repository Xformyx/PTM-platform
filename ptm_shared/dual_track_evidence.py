"""Relative-versus-occupancy TMM evidence classification without biology labels."""

from __future__ import annotations

import math
from collections import Counter
from typing import Any, Mapping, Sequence

import numpy as np


CONTRACT_VERSION = "tmm_dual_track_evidence.v2"


def _net_profile(score: Mapping[str, Any], conditions: Sequence[str]) -> np.ndarray:
    up = score.get("weighted_up_sums") or {}
    down = score.get("weighted_down_sums") or {}
    return np.asarray([
        float(up.get(condition) or 0.0) + float(down.get(condition) or 0.0)
        for condition in conditions
    ], dtype=float)


def _correlation(left: np.ndarray, right: np.ndarray) -> float | None:
    if left.size < 3 or float(np.std(left)) == 0.0 or float(np.std(right)) == 0.0:
        return None
    value = float(np.corrcoef(left, right)[0, 1])
    return value if math.isfinite(value) else None


def _top_sites(score: Mapping[str, Any], limit: int = 3) -> list[str]:
    records = sorted(
        (
            item for item in score.get("contribution_details") or []
            if item.get("contribution_ratio") is not None and item.get("ptm_key")
        ),
        key=lambda item: float(item.get("contribution_ratio") or 0.0),
        reverse=True,
    )[:limit]
    return [str(item["ptm_key"]) for item in records]


def classify_dual_track_kinase(
    relative_score: Mapping[str, Any] | None,
    occupancy_score: Mapping[str, Any] | None,
    conditions: Sequence[str],
    *,
    correlation_threshold: float = 0.5,
    peak_index_tolerance: int = 1,
    magnitude_log2_ratio_threshold: float = 1.0,
) -> dict[str, Any]:
    relative_score = relative_score or {}
    occupancy_score = occupancy_score or {}
    correlation_threshold = min(1.0, max(-1.0, float(correlation_threshold)))
    peak_index_tolerance = max(0, int(peak_index_tolerance))
    relative = _net_profile(relative_score, conditions)
    occupancy = _net_profile(occupancy_score, conditions)
    relative_available = bool(relative_score) and bool(np.any(np.abs(relative) > 0))
    occupancy_available = bool(occupancy_score) and bool(np.any(np.abs(occupancy) > 0))
    base = {
        "contract_version": CONTRACT_VERSION,
        "correlation_threshold": correlation_threshold,
        "peak_index_tolerance": peak_index_tolerance,
        "magnitude_log2_ratio_threshold": magnitude_log2_ratio_threshold,
        "relative_available": relative_available,
        "occupancy_available": occupancy_available,
        "interpretation_boundary": "Cross-track consistency evidence; not direct kinase-substrate or causal evidence.",
    }
    if not relative_available and not occupancy_available:
        return {**base, "classification": "dual_track_unavailable", "reportability": "insufficient"}
    if relative_available and not occupancy_available:
        return {**base, "classification": "relative_only", "reportability": "single_track_only"}
    if occupancy_available and not relative_available:
        return {**base, "classification": "occupancy_only", "reportability": "single_track_only"}

    relative_peak_index = int(np.argmax(np.abs(relative)))
    occupancy_peak_index = int(np.argmax(np.abs(occupancy)))
    relative_peak_value = float(relative[relative_peak_index])
    occupancy_peak_value = float(occupancy[occupancy_peak_index])
    peak_index_lag = occupancy_peak_index - relative_peak_index
    correlation = _correlation(relative, occupancy)
    direction_concordant = (
        relative_peak_value == 0.0
        or occupancy_peak_value == 0.0
        or (relative_peak_value > 0) == (occupancy_peak_value > 0)
    )
    relative_magnitude = abs(relative_peak_value)
    occupancy_magnitude = abs(occupancy_peak_value)
    magnitude_log2_ratio = (
        math.log2((occupancy_magnitude + 1e-12) / (relative_magnitude + 1e-12))
        if relative_magnitude > 0 or occupancy_magnitude > 0 else 0.0
    )
    relative_top = _top_sites(relative_score)
    occupancy_top = _top_sites(occupancy_score)
    overlap = sorted(set(relative_top) & set(occupancy_top))
    union = set(relative_top) | set(occupancy_top)
    top_site_jaccard = len(overlap) / len(union) if union else None
    timing_concordant = abs(peak_index_lag) <= peak_index_tolerance
    trajectory_concordant = correlation is not None and correlation >= correlation_threshold
    magnitude_concordant = abs(magnitude_log2_ratio) <= magnitude_log2_ratio_threshold

    if not direction_concordant:
        classification = "direction_discordant"
    elif trajectory_concordant and not timing_concordant:
        classification = "timing_shifted"
    elif trajectory_concordant and timing_concordant and not magnitude_concordant:
        classification = "magnitude_discordant"
    elif trajectory_concordant and timing_concordant and relative_top and occupancy_top and not overlap:
        classification = "substrate_attribution_discordant"
    elif trajectory_concordant and timing_concordant:
        classification = "dual_track_concordant"
    else:
        classification = "trajectory_discordant"

    relative_tier = str((relative_score.get("tmm_evidence") or {}).get("confidence_tier") or "unclassified")
    occupancy_tier = str((occupancy_score.get("tmm_evidence") or {}).get("confidence_tier") or "unclassified")
    both_data_anchored = "data_anchored" in relative_tier and "data_anchored" in occupancy_tier
    reportability = (
        "dual_track_supported" if classification == "dual_track_concordant" and both_data_anchored
        else "dual_track_observed_prior_limited" if classification == "dual_track_concordant"
        else "discordance_is_result"
    )
    return {
        **base,
        "classification": classification,
        "reportability": reportability,
        "trajectory_correlation": correlation,
        "trajectory_concordant": trajectory_concordant,
        "relative_peak_condition": conditions[relative_peak_index],
        "occupancy_peak_condition": conditions[occupancy_peak_index],
        "peak_index_lag": peak_index_lag,
        "peak_window_concordant": timing_concordant,
        "direction_concordant": direction_concordant,
        "relative_peak_value": relative_peak_value,
        "occupancy_peak_value": occupancy_peak_value,
        "magnitude_log2_ratio": magnitude_log2_ratio,
        "magnitude_concordant": magnitude_concordant,
        "top_contribution_overlap": overlap,
        "top_contribution_jaccard": top_site_jaccard,
        "relative_top_contributions": relative_top,
        "occupancy_top_contributions": occupancy_top,
        "relative_evidence_tier": relative_tier,
        "occupancy_evidence_tier": occupancy_tier,
        "both_tracks_data_anchored": both_data_anchored,
    }


def build_dual_track_evidence(
    relative_scores: Mapping[str, Mapping[str, Any]],
    occupancy_scores: Mapping[str, Mapping[str, Any]],
    conditions: Sequence[str],
    *,
    correlation_threshold: float = 0.5,
    peak_index_tolerance: int = 1,
    magnitude_log2_ratio_threshold: float = 1.0,
) -> dict[str, Any]:
    kinases = sorted(set(relative_scores) | set(occupancy_scores))
    by_kinase = {
        kinase: classify_dual_track_kinase(
            relative_scores.get(kinase),
            occupancy_scores.get(kinase),
            conditions,
            correlation_threshold=correlation_threshold,
            peak_index_tolerance=peak_index_tolerance,
            magnitude_log2_ratio_threshold=magnitude_log2_ratio_threshold,
        )
        for kinase in kinases
    }
    counts = Counter(item["classification"] for item in by_kinase.values())
    reportability = Counter(item["reportability"] for item in by_kinase.values())
    return {
        "contract_version": CONTRACT_VERSION,
        "parameters": {
            "correlation_threshold": correlation_threshold,
            "peak_index_tolerance": peak_index_tolerance,
            "magnitude_log2_ratio_threshold": magnitude_log2_ratio_threshold,
        },
        "by_kinase": by_kinase,
        "summary": {
            "kinase_count": len(by_kinase),
            "classification_counts": dict(sorted(counts.items())),
            "reportability_counts": dict(sorted(reportability.items())),
        },
    }
