"""TMM-aware multi-kinase interpretation helpers.

This module supplements, rather than replaces, legacy raw module membership.
It preserves the distinction between raw candidate/module overlap and
TMM-weighted, condition-specific kinase attribution.
"""

from __future__ import annotations

from collections import defaultdict
import re
from typing import Any, Mapping, Sequence

import numpy as np

from ptm_shared.directed_temporal_relationship import (
    analyze_directed_temporal_relationship,
)


CONTRACT_VERSION = "tmm_multikinase_interpretation.v1"
DEFAULT_ACTIVE_SCORE_THRESHOLD = 0.30
ACTIVITY_WEIGHTED_SUM = "weighted_sum"
ACTIVITY_WEIGHTED_MEAN = "weighted_mean"
ACTIVITY_SHRUNKEN_MEAN = "shrunken_mean"
ACTIVITY_METRICS = {
    ACTIVITY_WEIGHTED_SUM,
    ACTIVITY_WEIGHTED_MEAN,
    ACTIVITY_SHRUNKEN_MEAN,
}
_PTM_KEY_PATTERN = re.compile(r"^(?P<gene>.+?)[ _](?P<site>[STY]\d+(?:[/;][STY]\d+)*)$", re.I)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return parsed if np.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


def canonical_ptm_key(value: Any) -> str:
    """Return the one calculation key used by Wave, TMM, and source data.

    Legacy payloads sometimes used ``GENE S123`` as a display alias for
    ``GENE_S123``.  Display labels must never become additional biological
    records, so both forms resolve to one uppercase canonical key.
    """
    raw = str(value or "").strip().upper()
    if not raw:
        return ""
    match = _PTM_KEY_PATTERN.fullmatch(raw)
    if match:
        gene = match.group("gene").strip().replace(" ", "_")
        site = match.group("site").replace(";", "/")
        return f"{gene}_{site}"
    return raw.replace(" ", "_", 1)


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
    elif profile_type == "iterative_data_assisted":
        tier = "tmm_iterative_data_assisted"
        flags.append("shared_site_iterative_profile_not_direct_anchor")
        interpretation = "Profile was refined from identifiable high-share shared sites and remains data-assisted, not direct substrate evidence."
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
            site = canonical_ptm_key(detail.get("ptm_key"))
            if site:
                by_site[site][canonical] = max(0.0, _number(detail.get("contribution_ratio")))

    normalised: dict[str, dict[str, float]] = {}
    for site, contributions in by_site.items():
        total = sum(contributions.values())
        if total <= 0:
            continue
        row = {kinase: round(value / total, 6) for kinase, value in sorted(contributions.items())}
        normalised[site] = row
    return normalised


def summarize_tmm_uncertainty(
    tmm_scores: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Summarize unique-site adaptive uncertainty without republishing withheld ratios."""
    by_site: dict[str, Mapping[str, Any]] = {}
    resolutions: dict[str, str] = {}
    for score in (tmm_scores or {}).values():
        for detail in score.get("contribution_details", []) or []:
            if not isinstance(detail, Mapping):
                continue
            site = canonical_ptm_key(detail.get("ptm_key"))
            if not site:
                continue
            resolutions.setdefault(site, str(detail.get("resolution") or "unannotated"))
            uncertainty = detail.get("uncertainty")
            if isinstance(uncertainty, Mapping) and uncertainty.get("evaluated"):
                by_site.setdefault(site, uncertainty)

    bootstrap = [
        float(item["bootstrap_top1_stability"])
        for item in by_site.values()
        if item.get("bootstrap_top1_stability") is not None
        and np.isfinite(float(item["bootstrap_top1_stability"]))
    ]
    loto = [
        float(item["loto_top_group_stability"])
        for item in by_site.values()
        if item.get("loto_top_group_stability") is not None
        and np.isfinite(float(item["loto_top_group_stability"]))
    ]

    def _summary(values: Sequence[float]) -> dict[str, Any]:
        array = np.asarray(values, dtype=float)
        if array.size == 0:
            return {"count": 0, "median": None, "q25": None, "q75": None, "fraction_ge_0_8": None}
        return {
            "count": int(array.size),
            "median": round(float(np.median(array)), 6),
            "q25": round(float(np.quantile(array, 0.25)), 6),
            "q75": round(float(np.quantile(array, 0.75)), 6),
            "fraction_ge_0_8": round(float(np.mean(array >= 0.8)), 6),
        }

    return {
        "contract_version": "adaptive_tmm_uncertainty.v1",
        "unique_contribution_sites": len(resolutions),
        "evaluated_unique_sites": len(by_site),
        "resolved_unique_sites": sum(1 for value in resolutions.values() if value == "resolved"),
        "bootstrap_top1_stability": _summary(bootstrap),
        "loto_top_group_stability": _summary(loto),
        "interpretation_boundary": "Uncertainty is computed only for supported required singleton groups; ambiguity-group and guard-withheld per-kinase ratios remain withheld.",
    }


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
    activity_metric: str = ACTIVITY_WEIGHTED_SUM,
    shrinkage_prior_support: float = 5.0,
) -> dict[str, Any]:
    """Build a contribution-weighted cascade in parallel with raw overlap cascade.

    The activity threshold intentionally matches the existing heatmap directional
    threshold. The output is supplementary and never overwrites raw membership.
    """
    if activity_metric not in ACTIVITY_METRICS:
        raise ValueError(f"unsupported activity_metric: {activity_metric}")
    shrinkage_prior_support = max(0.0, float(shrinkage_prior_support))
    by_timepoint: dict[str, list[dict[str, Any]]] = defaultdict(list)
    selected_profiles: dict[str, dict[str, float]] = {}
    raw_sum_profiles: dict[str, dict[str, float]] = {}
    effect_size_profiles: dict[str, dict[str, float]] = {}
    shrunken_profiles: dict[str, dict[str, float]] = {}
    evidence_by_kinase: dict[str, dict[str, Any]] = {}
    for entry in kinase_scores:
        if entry.get("is_sub_pattern"):
            continue
        kinase = str(entry.get("kinase") or "").strip()
        if not kinase:
            continue
        profile = _profile_for_kinase(entry, conditions)
        raw_sum_profiles[kinase] = {}
        effect_size_profiles[kinase] = {}
        shrunken_profiles[kinase] = {}
        selected_profiles[kinase] = {}
        evidence = dict(entry.get("tmm_evidence") or build_tmm_evidence_profile(entry))
        evidence_by_kinase[kinase] = evidence
        weighted_up_counts = entry.get("tmm_weighted_up_counts") or entry.get("up_counts") or {}
        weighted_down_counts = entry.get("tmm_weighted_down_counts") or entry.get("down_counts") or {}
        for condition in conditions:
            raw_weighted_sum = profile[condition]
            evidence_mass = _number(weighted_up_counts.get(condition)) + _number(weighted_down_counts.get(condition))
            activity_effect_size = raw_weighted_sum / evidence_mass if evidence_mass > 0 else 0.0
            shrinkage_factor = (
                evidence_mass / (evidence_mass + shrinkage_prior_support)
                if evidence_mass > 0 and shrinkage_prior_support > 0
                else (1.0 if evidence_mass > 0 else 0.0)
            )
            shrunken_activity = activity_effect_size * shrinkage_factor
            activity_by_metric = {
                ACTIVITY_WEIGHTED_SUM: raw_weighted_sum,
                ACTIVITY_WEIGHTED_MEAN: activity_effect_size,
                ACTIVITY_SHRUNKEN_MEAN: shrunken_activity,
            }
            selected_activity = activity_by_metric[activity_metric]
            raw_sum_profiles[kinase][condition] = round(raw_weighted_sum, 6)
            effect_size_profiles[kinase][condition] = round(activity_effect_size, 6)
            shrunken_profiles[kinase][condition] = round(shrunken_activity, 6)
            selected_profiles[kinase][condition] = round(selected_activity, 6)
            if abs(selected_activity) < activity_threshold:
                continue
            by_timepoint[condition].append({
                "kinase": kinase,
                "canonical": str(entry.get("canonical") or kinase).upper(),
                "tmm_weighted_activity": round(raw_weighted_sum, 6),
                "raw_weighted_sum": round(raw_weighted_sum, 6),
                "activity_effect_size": round(activity_effect_size, 6),
                "evidence_mass": round(evidence_mass, 6),
                "tmm_weighted_substrate_support": round(evidence_mass, 6),
                "shrinkage_factor": round(shrinkage_factor, 6),
                "shrunken_activity": round(shrunken_activity, 6),
                "selected_activity": round(selected_activity, 6),
                "selected_activity_metric": activity_metric,
                "direction": "activation" if selected_activity > 0 else "inactivation",
                "tmm_evidence": evidence,
            })

    timepoints = []
    for condition in conditions:
        active = sorted(
            by_timepoint.get(condition, []),
            key=lambda item: (abs(item["selected_activity"]), item["evidence_mass"]),
            reverse=True,
        )
        timepoints.append({
            "timepoint": condition,
            "active_kinases": active,
            "weighted_activity_sum": round(sum(abs(item["tmm_weighted_activity"]) for item in active), 6),
            "selected_activity_abs_sum": round(sum(abs(item["selected_activity"]) for item in active), 6),
            "weighted_substrate_support": round(sum(item["evidence_mass"] for item in active), 6),
            "activity_threshold": activity_threshold,
            "activity_metric": activity_metric,
            "score_provenance": f"tmm_{activity_metric}",
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
        "score_provenance": f"tmm_{activity_metric}",
        "activity_threshold": activity_threshold,
        "activity_metric": activity_metric,
        "shrinkage_prior_support": shrinkage_prior_support,
        "timepoints": timepoints,
        "cascade_flow": transitions,
        "kinase_profiles": selected_profiles,
        "kinase_profiles_raw_sum": raw_sum_profiles,
        "kinase_profiles_effect_size": effect_size_profiles,
        "kinase_profiles_shrunken": shrunken_profiles,
        "tmm_evidence_by_kinase": evidence_by_kinase,
        "interpretation_boundary": (
            "Contribution-weighted temporal activity with effect size separated from evidence mass; "
            "not a causal cascade."
        ),
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


def build_evidence_gated_tmm_directionality(
    weighted_cascade: Mapping[str, Any],
    conditions: Sequence[str],
    *,
    max_kinases: int = 20,
) -> dict[str, Any]:
    """Separate evidence-eligible edges from observational prior-limited candidates.

    The underlying temporal relationship is unchanged.  This gate only controls
    publication scope: both endpoints must be data-anchored and the relationship
    must reach D2 or D3 before it enters the main edge list.
    """
    candidates = build_tmm_kinase_pair_directionality(
        weighted_cascade,
        conditions,
        max_kinases=max_kinases,
    )
    evidence = weighted_cascade.get("tmm_evidence_by_kinase") or {}
    main_edges: list[dict[str, Any]] = []
    annotated_candidates: list[dict[str, Any]] = []
    for record in candidates:
        source = str(record.get("source") or "")
        target = str(record.get("target") or "")
        source_tier = str((evidence.get(source) or {}).get("confidence_tier") or "unclassified")
        target_tier = str((evidence.get(target) or {}).get("confidence_tier") or "unclassified")
        directionality_tier = str(record.get("directionality_tier") or "D0_unresolved")
        reasons: list[str] = []
        if source_tier != "tmm_data_anchored":
            reasons.append("source_profile_not_data_anchored")
        if target_tier != "tmm_data_anchored":
            reasons.append("target_profile_not_data_anchored")
        if directionality_tier not in {
            "D2_reproducible_directionality",
            "D3_mechanistically_supported_directionality",
        }:
            reasons.append("directionality_below_D2")
        annotated = {
            **record,
            "source_tmm_evidence_tier": source_tier,
            "target_tmm_evidence_tier": target_tier,
            "evidence_eligible_for_main_edge": not reasons,
            "evidence_gate_reasons": reasons,
            "publication_scope": "main_edge" if not reasons else "exploratory_candidate",
            "interpretation_boundary": "Temporal precedence is observational; no causal intervention was evaluated.",
        }
        annotated_candidates.append(annotated)
        if not reasons:
            main_edges.append(annotated)
    return {
        "contract_version": "evidence_gated_tmm_directionality.v1",
        "main_edges": main_edges,
        "candidate_edges": annotated_candidates,
        "summary": {
            "main_edge_count": len(main_edges),
            "candidate_edge_count": len(annotated_candidates),
            "prior_limited_candidate_count": sum(
                1 for row in annotated_candidates
                if "source_profile_not_data_anchored" in row["evidence_gate_reasons"]
                or "target_profile_not_data_anchored" in row["evidence_gate_reasons"]
            ),
            "below_D2_candidate_count": sum(
                1 for row in annotated_candidates
                if "directionality_below_D2" in row["evidence_gate_reasons"]
            ),
        },
        "selection_boundary": "Evidence gating is not a tuning objective and never promotes D1 or prior-assisted profiles to main edges.",
    }
