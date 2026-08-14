"""TMM-aware multi-kinase interpretation helpers.

This module supplements, rather than replaces, legacy raw module membership.
It preserves the distinction between raw candidate/module overlap and
TMM-weighted, condition-specific kinase attribution.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence

import numpy as np

from ptm_shared.directed_temporal_relationship import (
    analyze_directed_temporal_relationship,
)


CONTRACT_VERSION = "tmm_multikinase_interpretation.v1"
DEFAULT_ACTIVE_SCORE_THRESHOLD = 0.30


def _number(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return parsed if np.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


def _profile_for_kinase(entry: Mapping[str, Any], conditions: Sequence[str]) -> dict[str, float]:
    """Return the preferred TMM-weighted signed profile with safe legacy fallback."""
    up = entry.get("tmm_weighted_up_sums") or entry.get("up_sums") or {}
    down = entry.get("tmm_weighted_down_sums") or entry.get("down_sums") or {}
    return {
        condition: round(_number(up.get(condition)) + _number(down.get(condition)), 6)
        for condition in conditions
    }


def build_tmm_evidence_profile(tmm: Mapping[str, Any]) -> dict[str, Any]:
    """Classify sparse/fallback TMM profiles without treating priors as data evidence."""
    n_exclusive = int(_number(tmm.get("n_exclusive", tmm.get("tmm_n_exclusive")), 0.0))
    n_shared = int(_number(tmm.get("n_shared", tmm.get("tmm_n_shared")), 0.0))
    profile_type = str(tmm.get("profile_type") or tmm.get("tmm_profile_type") or "unavailable")
    flags: list[str] = []

    if profile_type == "data_driven" and n_exclusive >= 3:
        tier = "tmm_data_anchored"
        interpretation = "Data-derived profile built from sufficient exclusive substrates."
    elif profile_type == "data_driven":
        tier = "tmm_sparse_data_anchored"
        flags.append("exclusive_anchor_count_below_recommended_minimum")
        interpretation = "Data-derived profile is available but has sparse exclusive-substrate support."
    elif "fallback" in profile_type or "gaussian" in profile_type:
        tier = "tmm_prior_assisted"
        flags.append("expected_peak_gaussian_fallback")
        interpretation = "Expected-time Gaussian profile is a prior-assisted fallback, not direct data evidence."
    else:
        tier = "tmm_insufficient_profile"
        flags.append("tmm_profile_unavailable_or_unclassified")
        interpretation = "No interpretable TMM profile is available."

    return {
        "contract_version": CONTRACT_VERSION,
        "profile_type": profile_type,
        "n_exclusive": n_exclusive,
        "n_shared": n_shared,
        "confidence_tier": tier,
        "confidence_flags": flags,
        "interpretation_boundary": interpretation,
    }


def build_tmm_site_contribution_matrix(
    tmm_scores: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, float]]:
    """Transpose per-kinase TMM details into normalized per-site mixtures.

    ``compute_weighted_kinase_scores`` emits contribution details grouped by
    kinase. Multisite analysis needs the inverse view: each PTM site receives
    its condition-specific fractional mixture across kinase candidates.
    """
    by_site: dict[str, dict[str, float]] = defaultdict(dict)
    for kinase, score in (tmm_scores or {}).items():
        canonical = str(kinase or "").upper()
        if not canonical:
            continue
        for detail in score.get("contribution_details", []) or []:
            if not isinstance(detail, Mapping):
                continue
            site = str(detail.get("ptm_key") or "").strip()
            if site:
                by_site[site][canonical] = max(0.0, _number(detail.get("contribution_ratio")))

    normalised: dict[str, dict[str, float]] = {}
    for site, contributions in by_site.items():
        total = sum(contributions.values())
        if total <= 0:
            continue
        row = {kinase: round(value / total, 6) for kinase, value in sorted(contributions.items())}
        normalised[site] = row
        if "_" in site:
            normalised.setdefault(site.replace("_", " ", 1), row)
    return normalised


def build_kinase_cowave_groups(
    kinase_scores: Sequence[Mapping[str, Any]],
    conditions: Sequence[str],
    *,
    provenance: str,
    correlation_threshold: float = 0.70,
) -> list[dict[str, Any]]:
    """Group kinases by profile correlation and explicitly record score provenance."""
    eligible: list[tuple[str, dict[str, float]]] = []
    for entry in kinase_scores:
        if entry.get("is_sub_pattern"):
            continue
        kinase = str(entry.get("kinase") or "").strip()
        profile = _profile_for_kinase(entry, conditions)
        if kinase and any(abs(value) > DEFAULT_ACTIVE_SCORE_THRESHOLD for value in profile.values()):
            eligible.append((kinase, profile))

    if len(eligible) < 2 or len(conditions) < 3:
        return []

    matrix = np.asarray([[profile[condition] for condition in conditions] for _, profile in eligible], dtype=float)
    correlation = np.corrcoef(matrix)
    visited: set[int] = set()
    groups: list[dict[str, Any]] = []
    for left in range(len(eligible)):
        if left in visited:
            continue
        members = [left]
        visited.add(left)
        for right in range(left + 1, len(eligible)):
            if right in visited or not np.isfinite(correlation[left, right]):
                continue
            if float(correlation[left, right]) >= correlation_threshold:
                members.append(right)
                visited.add(right)
        if len(members) < 2:
            continue
        pairwise = [
            float(correlation[i, j])
            for i in members for j in members
            if i != j and np.isfinite(correlation[i, j])
        ]
        group_profiles = [eligible[index][1] for index in members]
        mean_abs_by_condition = {
            condition: float(np.mean([abs(profile[condition]) for profile in group_profiles]))
            for condition in conditions
        }
        peak = max(mean_abs_by_condition, key=mean_abs_by_condition.get)
        groups.append({
            "group_id": len(groups),
            "kinases": [eligible[index][0] for index in members],
            "size": len(members),
            "mean_correlation": round(float(np.mean(pairwise)), 3) if pairwise else 1.0,
            "dominant_peak": peak,
            "score_provenance": provenance,
            "correlation_threshold": correlation_threshold,
        })
    return groups


def build_tmm_weighted_temporal_cascade(
    kinase_scores: Sequence[Mapping[str, Any]],
    conditions: Sequence[str],
    *,
    activity_threshold: float = DEFAULT_ACTIVE_SCORE_THRESHOLD,
) -> dict[str, Any]:
    """Build a contribution-weighted cascade in parallel with raw overlap cascade.

    The activity threshold intentionally matches the existing heatmap directional
    threshold. The output is supplementary and never overwrites raw membership.
    """
    by_timepoint: dict[str, list[dict[str, Any]]] = defaultdict(list)
    profiles: dict[str, dict[str, float]] = {}
    evidence_by_kinase: dict[str, dict[str, Any]] = {}
    for entry in kinase_scores:
        if entry.get("is_sub_pattern"):
            continue
        kinase = str(entry.get("kinase") or "").strip()
        if not kinase:
            continue
        profile = _profile_for_kinase(entry, conditions)
        profiles[kinase] = profile
        evidence = dict(entry.get("tmm_evidence") or build_tmm_evidence_profile(entry))
        evidence_by_kinase[kinase] = evidence
        weighted_up_counts = entry.get("tmm_weighted_up_counts") or entry.get("up_counts") or {}
        weighted_down_counts = entry.get("tmm_weighted_down_counts") or entry.get("down_counts") or {}
        for condition in conditions:
            activity = profile[condition]
            if abs(activity) < activity_threshold:
                continue
            support = _number(weighted_up_counts.get(condition)) + _number(weighted_down_counts.get(condition))
            by_timepoint[condition].append({
                "kinase": kinase,
                "canonical": str(entry.get("canonical") or kinase).upper(),
                "tmm_weighted_activity": round(activity, 6),
                "tmm_weighted_substrate_support": round(support, 6),
                "direction": "activation" if activity > 0 else "inactivation",
                "tmm_evidence": evidence,
            })

    timepoints = []
    for condition in conditions:
        active = sorted(
            by_timepoint.get(condition, []),
            key=lambda item: (abs(item["tmm_weighted_activity"]), item["tmm_weighted_substrate_support"]),
            reverse=True,
        )
        timepoints.append({
            "timepoint": condition,
            "active_kinases": active,
            "weighted_activity_sum": round(sum(abs(item["tmm_weighted_activity"]) for item in active), 6),
            "weighted_substrate_support": round(sum(item["tmm_weighted_substrate_support"] for item in active), 6),
            "activity_threshold": activity_threshold,
            "score_provenance": "tmm_weighted",
        })

    transitions = []
    for left, right in zip(timepoints, timepoints[1:]):
        left_kinases = {item["canonical"] for item in left["active_kinases"]}
        right_kinases = {item["canonical"] for item in right["active_kinases"]}
        transitions.append({
            "from_timepoint": left["timepoint"],
            "to_timepoint": right["timepoint"],
            "persistent_kinases": sorted(left_kinases & right_kinases),
            "new_kinases": sorted(right_kinases - left_kinases),
            "lost_kinases": sorted(left_kinases - right_kinases),
            "score_provenance": "tmm_weighted",
        })

    return {
        "contract_version": CONTRACT_VERSION,
        "score_provenance": "tmm_weighted",
        "activity_threshold": activity_threshold,
        "timepoints": timepoints,
        "cascade_flow": transitions,
        "kinase_profiles": profiles,
        "tmm_evidence_by_kinase": evidence_by_kinase,
        "interpretation_boundary": "Contribution-weighted temporal activity; not a causal cascade.",
    }


def build_tmm_kinase_pair_directionality(
    weighted_cascade: Mapping[str, Any],
    conditions: Sequence[str],
    *,
    max_kinases: int = 20,
) -> list[dict[str, Any]]:
    """Evaluate observational precedence between TMM-weighted kinase profiles.

    No biological support is supplied here. Consequently, observational profiles
    can reach at most D1 without independent replicate/permutation evidence and
    can never become causal merely because they are kinase profiles.
    """
    profiles = weighted_cascade.get("kinase_profiles") or {}
    ranked = sorted(
        profiles.items(),
        key=lambda pair: max((abs(_number(value)) for value in pair[1].values()), default=0.0),
        reverse=True,
    )[:max_kinases]
    records: list[dict[str, Any]] = []
    for source_index, (source_name, source_profile) in enumerate(ranked):
        for target_name, target_profile in ranked[source_index + 1:]:
            relation = analyze_directed_temporal_relationship(
                {"key": source_name, "temporal_values": source_profile},
                {"key": target_name, "temporal_values": target_profile},
                conditions,
                biological_support={},
            )
            if relation.get("direction") in {"source_precedes_target", "target_precedes_source"}:
                records.append({
                    "source_type": "tmm_weighted_kinase_profile",
                    "source": source_name,
                    "target": target_name,
                    **relation,
                })
    return records
