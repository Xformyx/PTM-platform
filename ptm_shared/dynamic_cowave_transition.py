"""Additive dynamic co-wave transition annotation for canonical PTM Waves.

This module never changes canonical Wave membership, Wave IDs, TMM
coefficients, kinase rankings, or any score.  It annotates the observed local
activity state of members already assigned to a static Wave and reports
persistence/split/merge/recruitment/exit events as non-causal evidence.
"""

from __future__ import annotations

import hashlib
import json
from itertools import combinations
from typing import Any, Mapping, Sequence

from ptm_shared.time_varying_comovement import (
    TimeVaryingCoMovementConfig,
    compute_time_varying_comovement,
)


CONTRACT_VERSION = "dynamic_co_wave_transition.v1"
DEFAULT_CONFIG: dict[str, Any] = {
    "activity_threshold_fc": 0.50,
    "minimum_observed_timepoints": 4,
    "membership_universe": "retained_canonical_wave_members_only",
    "lotto": "leave_one_timepoint_out",
    "maximum_pair_transition_examples": 500,
    "maximum_site_transition_examples": 500,
    "maximum_membership_examples": 250,
}


def _as_float_or_none(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _effective_config(config: Mapping[str, Any] | None) -> tuple[dict[str, Any], str]:
    merged = {**DEFAULT_CONFIG, **dict(config or {})}
    merged["activity_threshold_fc"] = max(0.0, float(merged["activity_threshold_fc"]))
    merged["minimum_observed_timepoints"] = max(2, int(merged["minimum_observed_timepoints"]))
    merged["maximum_pair_transition_examples"] = max(0, int(merged["maximum_pair_transition_examples"]))
    merged["maximum_site_transition_examples"] = max(0, int(merged["maximum_site_transition_examples"]))
    merged["maximum_membership_examples"] = max(0, int(merged["maximum_membership_examples"]))
    merged["membership_universe"] = "retained_canonical_wave_members_only"
    merged["lotto"] = "leave_one_timepoint_out"
    encoded = json.dumps(merged, sort_keys=True, separators=(",", ":"))
    return merged, hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def dynamic_transition_config_sha256(config: Mapping[str, Any] | None = None) -> str:
    """Return the canonical effective-configuration hash for cache freshness."""

    return _effective_config(config)[1]


def _static_membership(wave_contract: Mapping[str, Any]) -> dict[str, str]:
    return {
        str(site_key): str(wave.get("wave_id"))
        for wave in (wave_contract.get("waves") or [])
        if isinstance(wave, Mapping) and wave.get("wave_id")
        for site_key in (wave.get("members") or [])
    }


def _trajectory_by_member(
    wave_contract: Mapping[str, Any],
    timepoints: Sequence[str],
) -> dict[str, list[float | None]]:
    values: dict[str, list[float | None]] = {}
    for wave in wave_contract.get("waves") or []:
        if not isinstance(wave, Mapping):
            continue
        for member in wave.get("member_details") or []:
            if not isinstance(member, Mapping) or not member.get("key"):
                continue
            profile = dict(member.get("temporal_values") or {})
            values[str(member["key"])] = [_as_float_or_none(profile.get(label)) for label in timepoints]
    return values


def _pair_event_id(row: Mapping[str, Any]) -> str:
    left, right = sorted((str(row.get("site_a") or ""), str(row.get("site_b") or "")))
    return "|".join((left, right, str(row.get("from_window") or ""), str(row.get("to_window") or ""), str(row.get("transition_type") or "")))


def _site_event_id(row: Mapping[str, Any]) -> str:
    return "|".join((str(row.get("site_key") or ""), str(row.get("from_window") or ""), str(row.get("to_window") or ""), str(row.get("transition_type") or "")))


def _jaccard(left: set[str], right: set[str]) -> float | None:
    union = left | right
    if not union:
        return None
    return len(left & right) / len(union)


def _event_examples(rows: Sequence[Mapping[str, Any]], maximum: int, *, identity_key: str) -> list[dict[str, Any]]:
    """Return deterministic examples while calculations retain complete event sets."""

    ordered = sorted(rows, key=lambda row: str(row.get(identity_key) or ""))
    return [dict(row) for row in ordered[:maximum]]


def _per_wave_summary(
    pair_rows: Sequence[Mapping[str, Any]],
    site_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in pair_rows:
        wave_id = str(row.get("static_wave_id") or "")
        entry = grouped.setdefault(
            wave_id,
            {
                "static_wave_id": wave_id,
                "pair_transition_count": 0,
                "nonpersistence_pair_transition_count": 0,
                "site_transition_count": 0,
                "pair_transition_type_counts": {},
                "site_transition_type_counts": {},
            },
        )
        entry["pair_transition_count"] += 1
        entry["nonpersistence_pair_transition_count"] += int(row.get("transition_type") != "persistence")
        transition_type = str(row.get("transition_type") or "unknown")
        entry["pair_transition_type_counts"][transition_type] = int(
            entry["pair_transition_type_counts"].get(transition_type, 0)
        ) + 1
    for row in site_rows:
        wave_id = str(row.get("static_wave_id") or "")
        entry = grouped.setdefault(
            wave_id,
            {
                "static_wave_id": wave_id,
                "pair_transition_count": 0,
                "nonpersistence_pair_transition_count": 0,
                "site_transition_count": 0,
                "pair_transition_type_counts": {},
                "site_transition_type_counts": {},
            },
        )
        entry["site_transition_count"] += 1
        transition_type = str(row.get("transition_type") or "unknown")
        entry["site_transition_type_counts"][transition_type] = int(
            entry["site_transition_type_counts"].get(transition_type, 0)
        ) + 1
    return [grouped[wave_id] for wave_id in sorted(grouped)]


def _annotate_once(
    *,
    wave_contract: Mapping[str, Any],
    timepoints: Sequence[str],
    trajectories: Mapping[str, Sequence[float | None]],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    membership = _static_membership(wave_contract)
    qualified = {
        key: list(trajectories[key])
        for key in sorted(membership)
        if key in trajectories and sum(value is not None for value in trajectories[key]) >= int(config["minimum_observed_timepoints"])
    }
    raw = compute_time_varying_comovement(
        timepoints,
        qualified,
        config=TimeVaryingCoMovementConfig(
            activity_threshold_fc=float(config["activity_threshold_fc"]),
            min_window_observed=int(config["minimum_observed_timepoints"]),
            require_atlas_eligible=False,
        ),
    ).to_dict()
    pair_events = []
    for row in raw.get("pair_transitions") or []:
        if membership.get(row.get("site_a")) != membership.get(row.get("site_b")):
            continue
        enriched = dict(row)
        enriched["static_wave_id"] = membership[str(row.get("site_a"))]
        enriched["transition_id"] = _pair_event_id(enriched)
        pair_events.append(enriched)
    site_events = []
    for row in raw.get("site_transitions") or []:
        if row.get("site_key") not in membership:
            continue
        enriched = dict(row)
        enriched["static_wave_id"] = membership[str(row.get("site_key"))]
        enriched["transition_id"] = _site_event_id(enriched)
        site_events.append(enriched)

    state_lookup = {
        (str(row.get("site_key")), str(row.get("window_label"))): str(row.get("activity_state"))
        for row in raw.get("memberships") or []
    }
    window_labels = sorted({str(row.get("window_label")) for row in raw.get("memberships") or []})
    opportunities = 0
    active_pairs = 0
    for wave_id in sorted(set(membership.values())):
        members = sorted(key for key, assigned_wave in membership.items() if assigned_wave == wave_id and key in qualified)
        for left, right in combinations(members, 2):
            for window in window_labels:
                left_state = state_lookup.get((left, window), "inactive")
                right_state = state_lookup.get((right, window), "inactive")
                opportunities += 1
                if left_state != "inactive" and left_state == right_state:
                    active_pairs += 1
    nonpersistent = [row for row in pair_events if row.get("transition_type") != "persistence"]
    transition_waves = sorted({str(row["static_wave_id"]) for row in nonpersistent})
    return {
        "memberships": raw.get("memberships") or [],
        "pair_transitions": pair_events,
        "site_transitions": site_events,
        "excluded_sites": raw.get("excluded_sites") or {},
        "summary": {
            "static_wave_member_count": len(membership),
            "qualified_member_count": len(qualified),
            "local_window_count": len(window_labels),
            "static_pair_window_opportunities": opportunities,
            "same_sign_active_pair_windows": active_pairs,
            "local_active_pair_coverage": (active_pairs / opportunities) if opportunities else None,
            "pair_transition_count": len(pair_events),
            "site_transition_count": len(site_events),
            "nonpersistence_pair_transition_count": len(nonpersistent),
            "transition_resolution": (len(nonpersistent) / len(pair_events)) if pair_events else None,
            "transition_supported_wave_ids": transition_waves,
            "transition_supported_wave_count": len(transition_waves),
        },
    }


def analyze_dynamic_co_wave_transitions(
    wave_contract: Mapping[str, Any],
    *,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create additive local transition evidence for immutable static Waves."""

    effective, config_sha = _effective_config(config)
    timepoints = [str(label) for label in wave_contract.get("timepoints") or []]
    trajectories = _trajectory_by_member(wave_contract, timepoints)
    annotation = _annotate_once(
        wave_contract=wave_contract,
        timepoints=timepoints,
        trajectories=trajectories,
        config=effective,
    )
    full_pair_rows = list(annotation["pair_transitions"])
    full_site_rows = list(annotation["site_transitions"])
    full_memberships = list(annotation["memberships"])
    full_pair_ids = {row["transition_id"] for row in full_pair_rows}
    full_site_ids = {row["transition_id"] for row in full_site_rows}
    folds = []
    pair_scores: list[float] = []
    site_scores: list[float] = []
    for drop_index, dropped_label in enumerate(timepoints):
        retained = [label for index, label in enumerate(timepoints) if index != drop_index]
        reduced_trajectories = {
            key: [value for index, value in enumerate(values) if index != drop_index]
            for key, values in trajectories.items()
        }
        reduced = _annotate_once(
            wave_contract=wave_contract,
            timepoints=retained,
            trajectories=reduced_trajectories,
            config={**effective, "minimum_observed_timepoints": min(int(effective["minimum_observed_timepoints"]), len(retained))},
        )
        pair_ids = {row["transition_id"] for row in reduced["pair_transitions"]}
        site_ids = {row["transition_id"] for row in reduced["site_transitions"]}
        comparable_pairs = {value for value in full_pair_ids if dropped_label not in value} | {value for value in pair_ids if dropped_label not in value}
        comparable_sites = {value for value in full_site_ids if dropped_label not in value} | {value for value in site_ids if dropped_label not in value}
        pair_score = _jaccard({value for value in full_pair_ids if value in comparable_pairs}, {value for value in pair_ids if value in comparable_pairs})
        site_score = _jaccard({value for value in full_site_ids if value in comparable_sites}, {value for value in site_ids if value in comparable_sites})
        if pair_score is not None:
            pair_scores.append(pair_score)
        if site_score is not None:
            site_scores.append(site_score)
        folds.append(
            {
                "dropped_timepoint": dropped_label,
                "comparable_pair_transition_count": len(comparable_pairs),
                "comparable_site_transition_count": len(comparable_sites),
                "pair_transition_jaccard": pair_score,
                "site_transition_jaccard": site_score,
            }
        )
    annotation["contract_version"] = CONTRACT_VERSION
    annotation["provenance"] = {
        "configuration": effective,
        "config_sha256": config_sha,
        "static_wave_contract_version": wave_contract.get("contract_version"),
        "static_wave_config_sha256": (wave_contract.get("threshold_provenance") or {}).get("config_sha256"),
        "membership_mutation": "forbidden",
        "tmm_mutation": "forbidden",
        "interpretation_boundary": "Observed local co-movement membership transitions only; not kinase or causal evidence.",
    }
    annotation["transition_examples"] = {
        "pair_transitions": _event_examples(
            full_pair_rows,
            int(effective["maximum_pair_transition_examples"]),
            identity_key="transition_id",
        ),
        "site_transitions": _event_examples(
            full_site_rows,
            int(effective["maximum_site_transition_examples"]),
            identity_key="transition_id",
        ),
        "memberships": _event_examples(
            full_memberships,
            int(effective["maximum_membership_examples"]),
            identity_key="site_key",
        ),
        "truncation": {
            "pair_transition_total_count": len(full_pair_rows),
            "site_transition_total_count": len(full_site_rows),
            "membership_total_count": len(full_memberships),
            "maximum_pair_transition_examples": int(effective["maximum_pair_transition_examples"]),
            "maximum_site_transition_examples": int(effective["maximum_site_transition_examples"]),
            "maximum_membership_examples": int(effective["maximum_membership_examples"]),
            "full_event_sets_used_for_metrics": True,
        },
    }
    annotation["per_wave_summary"] = _per_wave_summary(full_pair_rows, full_site_rows)
    annotation.pop("pair_transitions", None)
    annotation.pop("site_transitions", None)
    annotation.pop("memberships", None)
    annotation["lotto"] = {
        "method": "leave_one_timepoint_out_comparable_transition_jaccard",
        "folds": folds,
        "mean_pair_transition_jaccard": (sum(pair_scores) / len(pair_scores)) if pair_scores else None,
        "mean_site_transition_jaccard": (sum(site_scores) / len(site_scores)) if site_scores else None,
        "evaluable_pair_fold_count": len(pair_scores),
        "evaluable_site_fold_count": len(site_scores),
    }
    return annotation
