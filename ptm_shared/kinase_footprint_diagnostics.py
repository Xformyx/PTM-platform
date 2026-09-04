"""Claim-safe diagnostics for kinase substrate-footprint displays.

This module does not rank kinases and does not assign kinase-to-site edges.  It
only reports how much of an already computed, contribution-weighted footprint
depends on its site support.  The diagnostics are deliberately generic: no
kinase, substrate, species, treatment or pathway identity is special-cased.
"""

from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
from typing import Any, Mapping, Sequence

import numpy as np

from ptm_shared.de_novo_representation import (
    heatmap_denovo_value,
    heatmap_denovo_weight,
    is_de_novo_representation,
)


CONTRACT_VERSION = "kinase_footprint_diagnostics.v1"


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if np.isfinite(parsed) else default


def detection_aware_footprint_value(
    row: Mapping[str, Any] | None,
    conventional_value: Any,
) -> tuple[float | None, bool]:
    """Return the footprint input value without converting pseudo-log2FC to signal.

    Conventional values are preserved as observations.  A declared de novo row
    is instead represented by the frozen capped LOD-relative value multiplied
    by the established heatmap confidence weight.  The numerical magnitude of
    ``conventional_value`` never determines the representation class.
    """

    try:
        parsed_conventional = float(conventional_value)
    except (TypeError, ValueError):
        parsed_conventional = None
    if parsed_conventional is not None and not np.isfinite(parsed_conventional):
        parsed_conventional = None
    is_denovo = is_de_novo_representation(row)
    if not is_denovo:
        return parsed_conventional, False
    source = row or {}
    lod_relative = _finite(source.get("lod_relative_log2", source.get("LOD_Relative_Log2")), default=0.0)
    confidence = str(source.get("denovo_confidence", source.get("DeNovo_Confidence", "")) or "").strip().lower()
    return heatmap_denovo_value(lod_relative) * heatmap_denovo_weight(confidence), True


def _profile_peak(profile: Mapping[str, float], conditions: Sequence[str]) -> tuple[str | None, float, str]:
    if not conditions:
        return None, 0.0, "near_zero_footprint"
    peak_condition = max(conditions, key=lambda condition: abs(_finite(profile.get(condition))))
    peak_value = _finite(profile.get(peak_condition))
    if peak_value > 0:
        direction = "positive_substrate_footprint"
    elif peak_value < 0:
        direction = "negative_substrate_footprint"
    else:
        direction = "near_zero_footprint"
    return peak_condition, peak_value, direction


def build_exact_footprint_equivalence(
    kinase_to_site_keys: Mapping[str, Sequence[str]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Identify only *exact* substrate-set equivalence classes.

    Near overlaps are intentionally not merged.  They must remain separate
    candidates because no data-independent Jaccard threshold can establish a
    biological family or isoform relationship.
    """

    grouped: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for kinase, keys in kinase_to_site_keys.items():
        canonical = str(kinase or "").strip()
        fingerprint = tuple(sorted({str(key or "").strip().upper() for key in keys if str(key or "").strip()}))
        if canonical and fingerprint:
            grouped[fingerprint].append(canonical)

    groups: list[dict[str, Any]] = []
    by_kinase: dict[str, dict[str, Any]] = {}
    for fingerprint, kinases in sorted(grouped.items(), key=lambda item: (item[0], item[1])):
        if len(kinases) < 2:
            continue
        ordered_kinases = sorted(kinases, key=str.upper)
        digest = sha256("|".join(fingerprint).encode("utf-8")).hexdigest()[:12]
        group = {
            "contract_version": CONTRACT_VERSION,
            "equivalence_group_id": f"exact-set-{digest}",
            "equivalence": "exact_substrate_set",
            "kinases": ordered_kinases,
            "site_count": len(fingerprint),
            "fingerprint_sha256_12": digest,
            "interpretation_boundary": (
                "These candidates share an identical observed substrate footprint; "
                "this analysis does not resolve isoform-specific activity or direct attribution."
            ),
        }
        groups.append(group)
        for kinase in ordered_kinases:
            by_kinase[kinase] = {
                "equivalence_group_id": group["equivalence_group_id"],
                "equivalence": group["equivalence"],
                "member_count": len(ordered_kinases),
                "site_count": len(fingerprint),
                "members": ordered_kinases,
                "interpretation_boundary": group["interpretation_boundary"],
            }
    return groups, by_kinase


def summarize_weighted_footprint(
    site_profiles: Mapping[str, Mapping[str, Any]],
    conditions: Sequence[str],
    *,
    shrinkage_prior_support: float,
    max_leave_one_out: int = 3,
    exclusive_site_keys: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Summarize support and leave-one-substrate-out sensitivity.

    ``site_profiles`` must contain the same thresholded, contribution-weighted
    site values that were used to construct the displayed aggregate.  This
    function neither changes the aggregate score nor applies a new biological
    threshold.  Support shrinkage is descriptive and reuses the configured TMM
    evidence-mass prior rather than introducing a new tuning constant.
    """

    ordered_conditions = [str(condition) for condition in conditions]
    profiles: dict[str, dict[str, float]] = {}
    for raw_key, raw_profile in site_profiles.items():
        key = str(raw_key or "").strip().upper()
        if not key or not isinstance(raw_profile, Mapping):
            continue
        profile = {condition: _finite(raw_profile.get(condition)) for condition in ordered_conditions}
        if any(value != 0.0 for value in profile.values()):
            profiles[key] = profile

    if not profiles:
        return {
            "contract_version": CONTRACT_VERSION,
            "status": "not_evaluable_no_weighted_site_profiles",
            "interpretation_boundary": "No thresholded contribution-weighted site profile was available for robustness diagnostics.",
        }

    aggregate = {
        condition: float(sum(profile[condition] for profile in profiles.values()))
        for condition in ordered_conditions
    }
    site_masses = {
        key: float(sum(abs(value) for value in profile.values()))
        for key, profile in profiles.items()
    }
    total_mass = float(sum(site_masses.values()))
    weights = {
        key: (mass / total_mass if total_mass > 0 else 0.0)
        for key, mass in site_masses.items()
    }
    effective_support = (
        1.0 / sum(weight ** 2 for weight in weights.values() if weight > 0)
        if any(weight > 0 for weight in weights.values())
        else 0.0
    )
    prior = max(0.0, _finite(shrinkage_prior_support))
    support_shrinkage = (
        effective_support / (effective_support + prior)
        if effective_support > 0 and prior > 0
        else (1.0 if effective_support > 0 else 0.0)
    )
    peak_condition, peak_score, direction = _profile_peak(aggregate, ordered_conditions)

    ranked_sites = sorted(site_masses, key=lambda key: (-site_masses[key], key))
    leave_one_out: list[dict[str, Any]] = []
    for key in ranked_sites[: max(0, int(max_leave_one_out))]:
        reduced = {
            condition: aggregate[condition] - profiles[key][condition]
            for condition in ordered_conditions
        }
        reduced_peak_condition, reduced_peak_score, reduced_direction = _profile_peak(reduced, ordered_conditions)
        max_score_delta = max(
            (abs(aggregate[condition] - reduced[condition]) for condition in ordered_conditions),
            default=0.0,
        )
        leave_one_out.append({
            "site_key": key,
            "leverage_fraction": round(weights[key], 6),
            "peak_condition": reduced_peak_condition,
            "peak_score": round(reduced_peak_score, 6),
            "direction": reduced_direction,
            "peak_condition_preserved": reduced_peak_condition == peak_condition,
            "direction_preserved": reduced_direction == direction,
            "max_score_delta": round(max_score_delta, 6),
        })

    result = {
        "contract_version": CONTRACT_VERSION,
        "status": "computed",
        "weighted_site_count": len(profiles),
        "effective_substrate_number": round(effective_support, 6),
        "support_shrinkage_factor": round(support_shrinkage, 6),
        "dominant_substrate_fraction": round(weights[ranked_sites[0]], 6) if ranked_sites else 0.0,
        "full_peak_condition": peak_condition,
        "full_peak_score": round(peak_score, 6),
        "footprint_direction": direction,
        "leave_one_substrate_out": leave_one_out,
        "interpretation_boundary": (
            "Leave-one-substrate-out values are robustness diagnostics for the displayed "
            "contribution-weighted footprint. They do not establish direct kinase attribution, "
            "causal regulation, or a kinase-specific biological effect."
        ),
    }
    if exclusive_site_keys is not None:
        exclusive_set = {str(key or "").strip().upper() for key in exclusive_site_keys if str(key or "").strip()}
        exclusive_profiles = {key: profile for key, profile in profiles.items() if key in exclusive_set}
        if exclusive_profiles:
            unique_summary = summarize_weighted_footprint(
                exclusive_profiles,
                ordered_conditions,
                shrinkage_prior_support=prior,
                max_leave_one_out=0,
            )
            result["unique_only_footprint"] = {
                "status": unique_summary["status"],
                "weighted_site_count": unique_summary.get("weighted_site_count", 0),
                "effective_substrate_number": unique_summary.get("effective_substrate_number", 0.0),
                "peak_condition": unique_summary.get("full_peak_condition"),
                "peak_score": unique_summary.get("full_peak_score"),
                "direction": unique_summary.get("footprint_direction"),
            }
        else:
            result["unique_only_footprint"] = {
                "status": "not_evaluable_no_exclusive_weighted_site_profiles",
                "weighted_site_count": 0,
                "interpretation_boundary": "No exclusive thresholded contribution-weighted site profile was available.",
            }
    return result
