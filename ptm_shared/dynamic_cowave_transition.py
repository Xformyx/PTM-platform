"""Additive dynamic co-wave transition annotation for canonical PTM Waves.

This module never changes canonical Wave membership, Wave IDs, TMM
coefficients, kinase rankings, or any score.  It annotates the observed local
activity state of members already assigned to a static Wave and reports
persistence/split/merge/recruitment/exit events as non-causal evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
from itertools import combinations, permutations
from typing import Any, Mapping, Sequence

import numpy as np

from ptm_shared.time_varying_comovement import (
    TimeVaryingCoMovementConfig,
    compute_time_varying_comovement,
)
from ptm_shared.temporal_optimization_config import (
    DYNAMIC_COWAVE_CONFIG,
    DYNAMIC_COWAVE_CONTRACT_VERSION,
)


CONTRACT_VERSION = DYNAMIC_COWAVE_CONTRACT_VERSION
DEFAULT_CONFIG: dict[str, Any] = {
    # Direct public calls must use the same frozen baseline as production.
    "activity_threshold_fc": float(DYNAMIC_COWAVE_CONFIG["activity_threshold_fc"]),
    "minimum_observed_timepoints": int(DYNAMIC_COWAVE_CONFIG["minimum_observed_timepoints"]),
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
    merged["pair_scope"] = "same_static_wave_only"
    merged["site_event_policy"] = "record_noninert_transitions_only"
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
            include_inert_site_observations=False,
        ),
        group_by_site={key: membership[key] for key in qualified},
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
        "pair_scope": dict(raw.get("pair_scope") or {}),
        "event_exposure": dict(raw.get("event_exposure") or {}),
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
            "within_wave_candidate_pair_count": (raw.get("pair_scope") or {}).get("candidate_pair_count"),
            "cross_wave_pair_excluded_count": (raw.get("pair_scope") or {}).get("cross_group_pair_excluded_count"),
            "site_transition_opportunity_count": (raw.get("event_exposure") or {}).get("site_transition_opportunity_count"),
            "inert_site_observation_count": (raw.get("event_exposure") or {}).get("inert_site_observation_count"),
        },
    }


# ── T_adjacency temporal statistic ────────────────────────────────────────

def _coactive_matrix(
    wave_contract: Mapping[str, Any],
    timepoints: Sequence[str],
    trajectories: Mapping[str, Sequence[float | None]],
    threshold: float,
) -> tuple[np.ndarray, list[tuple[str, str]]]:
    """Build binary co-activity matrix [n_pairs × n_timepoints].

    Returns (matrix, pairs) where matrix[p, t] = True if both sites in pair p
    are active (|FC| >= threshold) at timepoint t.  Only same-static-Wave pairs
    are included.  Missing values (None) → inactive.

    This vectorized representation enables fast T_adjacency computation without
    re-running _annotate_once for each permutation.
    """
    site_wave = _static_membership(wave_contract)
    wave_members: dict[str, list[str]] = {}
    for site, wid in site_wave.items():
        wave_members.setdefault(wid, []).append(site)

    all_pairs: list[tuple[str, str]] = []
    for wid in sorted(wave_members):
        members = sorted(wave_members[wid])
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                all_pairs.append((members[i], members[j]))

    n_tp = len(timepoints)
    n_pairs = len(all_pairs)
    matrix = np.zeros((n_pairs, n_tp), dtype=bool)

    for p_idx, (a, b) in enumerate(all_pairs):
        fc_a = list(trajectories.get(a, [None] * n_tp))
        fc_b = list(trajectories.get(b, [None] * n_tp))
        for t_idx in range(n_tp):
            fa = fc_a[t_idx]
            fb = fc_b[t_idx]
            if fa is not None and fb is not None:
                matrix[p_idx, t_idx] = abs(fa) >= threshold and abs(fb) >= threshold

    return matrix, all_pairs


def _jaccard_binary(col_a: np.ndarray, col_b: np.ndarray) -> float:
    """Jaccard similarity between two boolean arrays."""
    inter = np.sum(col_a & col_b)
    union = np.sum(col_a | col_b)
    return float(inter / union) if union > 0 else 1.0


def _t_adjacency_for_ordering(
    coactive: np.ndarray,
    ordering: Sequence[int],
) -> float | None:
    """Compute T_adjacency for a given time-index ordering.

    T_adjacency = mean J(E_t, E_{t+1}) - mean J(E_t, E_{t+k}), k > 1

    E_t = co-active pair set at timepoint ordering[t].
    Adjacent Jaccard: pairs (ordering[0],ordering[1]), (ordering[1],ordering[2]), ...
    Non-adjacent Jaccard: all pairs (ordering[w], ordering[w+k]) with k >= 2.

    Returns None if non-adjacent Jaccard cannot be computed (fewer than 3 timepoints).
    """
    idx = list(ordering)
    n = len(idx)
    if n < 3:
        return None

    adj_j: list[float] = []
    for w in range(n - 1):
        adj_j.append(_jaccard_binary(coactive[:, idx[w]], coactive[:, idx[w + 1]]))

    nonadj_j: list[float] = []
    for k in range(2, n):
        for w in range(n - k):
            nonadj_j.append(_jaccard_binary(coactive[:, idx[w]], coactive[:, idx[w + k]]))

    if not adj_j or not nonadj_j:
        return None

    return float(np.mean(adj_j) - np.mean(nonadj_j))


# T_adjacency permutation defaults (pre-registered 2026-08-28)
T_ADJACENCY_EXACT_MAX_TIMEPOINTS: int = 8
"""Use exact permutation for n_timepoints <= this value; random otherwise.

6 timepoints → 720 orderings (always exact).
7 timepoints → 5,040 orderings (exact, fast).
8 timepoints → 40,320 orderings (exact, seconds).
Pre-registered 2026-08-28.
"""


def compute_temporal_adjacency_statistic(
    wave_contract: Mapping[str, Any],
    timepoints: Sequence[str],
    trajectories: Mapping[str, Sequence[float | None]],
    config: Mapping[str, Any],
    *,
    random_n: int = 10000,
    seed: int = 20260828,
) -> dict[str, Any]:
    """Compute T_adjacency and its null distribution.

    T_adjacency = mean J(adjacent windows) − mean J(non-adjacent windows).

    A positive T_adjacency means that sites which are co-active at one timepoint
    tend to remain co-active at the *next* timepoint more than at distant timepoints —
    i.e., the local structure is temporally coherent.

    Null distribution: all n! orderings of timepoints (exact for n ≤ 8) or
    random subsample for larger n.  Plus-one correction applied.

    Implementation target: Image "2.1 시간 순서의 정보성" T_adjacency recommendation.
    Pre-registration: 2026-08-28.
    Interpretation limits:
      Significant p (< 0.05) supports that the observed temporal ordering is more
      structured than random, NOT that Dynamic Co-Wave captures causal kinase ordering.
      This test is a prerequisite for claiming biologically meaningful temporal structure.
    Claim boundary: Do NOT claim "Dynamic Co-Wave captures biologically meaningful
      temporal ordering" unless p_t_adjacency < 0.05 on the actual dataset.
      Current finding (2026-08-28): p_time_index_permutation = 0.570858 with
      transition_resolution metric — temporal ordering was NOT statistically significant.
      T_adjacency is proposed as a better statistic for this question.
    """
    threshold = float(config.get("activity_threshold_fc", 0.40))
    coactive, pairs = _coactive_matrix(wave_contract, timepoints, trajectories, threshold)
    n_tp = len(timepoints)

    if n_tp < 3:
        return {
            "status": "skipped_too_few_timepoints",
            "t_adjacency_observed": None,
            "method": "exact" if n_tp <= T_ADJACENCY_EXACT_MAX_TIMEPOINTS else "random",
        }

    identity_ordering = list(range(n_tp))
    observed = _t_adjacency_for_ordering(coactive, identity_ordering)
    if observed is None:
        return {"status": "skipped_not_computable", "t_adjacency_observed": None}

    use_exact = n_tp <= T_ADJACENCY_EXACT_MAX_TIMEPOINTS
    method = "exact_all_permutations" if use_exact else f"random_{random_n}_permutations"

    null_values: list[float] = []
    if use_exact:
        all_perms = list(permutations(range(n_tp)))
        for perm in all_perms:
            v = _t_adjacency_for_ordering(coactive, list(perm))
            if v is not None:
                null_values.append(v)
    else:
        rng = np.random.default_rng(seed)
        for _ in range(random_n):
            perm = rng.permutation(n_tp).tolist()
            v = _t_adjacency_for_ordering(coactive, perm)
            if v is not None:
                null_values.append(v)

    if not null_values:
        return {"status": "skipped_empty_null", "t_adjacency_observed": observed}

    null_arr = np.array(null_values)
    n_exceed = int(np.sum(null_arr >= observed))
    p_empirical = (n_exceed + 1) / (len(null_arr) + 1)
    null_rank = int(np.sum(null_arr < observed))
    supports_ordered_adjacency = bool(p_empirical < 0.05)

    return {
        "status": "computed",
        "method": method,
        "t_adjacency_observed": round(observed, 6),
        "null_mean": round(float(np.mean(null_arr)), 6),
        "null_std": round(float(np.std(null_arr)), 6),
        "null_5th_pct": round(float(np.percentile(null_arr, 5)), 6),
        "null_95th_pct": round(float(np.percentile(null_arr, 95)), 6),
        "n_permutations_evaluated": len(null_values),
        "n_exceedances": n_exceed,
        "p_empirical_one_sided": round(p_empirical, 6),
        "null_rank_of_observed": null_rank,
        "verdict": "supports_ordered_adjacency" if supports_ordered_adjacency else "not_significant",
        "supports_global_temporal_order": supports_ordered_adjacency,
        "interpretation": (
            "Observed ordering has higher adjacent than distant co-activity coherence under the exact null; "
            "this is structural ordering evidence only, not causal or kinase-direction evidence."
            if supports_ordered_adjacency
            else "Observed ordering is not significantly more adjacency-coherent than the exact ordering null. "
            "Do not claim that Dynamic Co-Wave validates global chronological structure from this result."
        ),
        "claim_boundary": (
            "T_adjacency tests global adjacency coherence only. It does not establish causal propagation, "
            "direct kinase-substrate regulation, or correctness of any specific event order."
        ),
    }


def _permuted_wave_contract(
    wave_contract: Mapping[str, Any],
    permuted_membership: Mapping[str, str],
) -> dict[str, Any]:
    """Rebuild a wave_contract with shuffled Wave-membership assignments.

    Trajectories (temporal_values) are preserved exactly; only which Wave a
    site belongs to is changed.  This is the null model for the permutation test:
    if Wave membership is random, the observed transition_resolution should fall
    in the null distribution.
    """
    # Collect all member_details keyed by site
    all_details: dict[str, dict] = {}
    for wave in wave_contract.get("waves") or []:
        for md in wave.get("member_details") or []:
            if md.get("key"):
                all_details[str(md["key"])] = dict(md)

    # Rebuild waves with permuted membership
    new_wave_ids = sorted(set(permuted_membership.values()))
    new_waves = []
    for wid in new_wave_ids:
        members_in = [k for k, v in permuted_membership.items() if v == wid]
        new_waves.append({
            "wave_id": wid,
            "members": members_in,
            "member_details": [all_details[k] for k in members_in if k in all_details],
        })
    return {**dict(wave_contract), "waves": new_waves}


def _wave_membership_permutation_test(
    wave_contract: Mapping[str, Any],
    timepoints: Sequence[str],
    trajectories: Mapping[str, Sequence[float | None]],
    config: Mapping[str, Any],
    n_permutations: int,
    seed: int,
) -> dict[str, Any]:
    """Estimate null distribution of transition_resolution by shuffling Wave labels.

    Implementation target: Roadmap §3 time-label permutation + bootstrap.
    Pre-registration: 2026-08-28.  Permutation count and seed fixed before
      inhibitor data was seen.
    Interpretation limits: tests whether transition_resolution is above chance
      given the observed trajectory shapes; does not validate causal mechanisms.
    Claim boundary: a significant p-value supports annotation informativeness,
      not kinase attribution accuracy.
    """
    membership = _static_membership(wave_contract)
    if len(membership) < 4:
        return {
            "status": "skipped_too_few_members",
            "n_permutations": 0,
            "method": "wave_membership_label_permutation",
        }

    observed_result = _annotate_once(
        wave_contract=wave_contract,
        timepoints=list(timepoints),
        trajectories=trajectories,
        config=config,
    )
    observed_resolution = observed_result["summary"].get("transition_resolution")

    all_keys = list(membership.keys())
    all_wave_ids = list(membership.values())
    rng = np.random.default_rng(seed)

    null_resolutions: list[float] = []
    for _ in range(n_permutations):
        shuffled_ids = rng.permutation(all_wave_ids).tolist()
        perm_membership = dict(zip(all_keys, shuffled_ids))
        perm_contract = _permuted_wave_contract(wave_contract, perm_membership)
        perm_result = _annotate_once(
            wave_contract=perm_contract,
            timepoints=list(timepoints),
            trajectories=trajectories,
            config=config,
        )
        r = perm_result["summary"].get("transition_resolution")
        if r is not None:
            null_resolutions.append(r)

    if not null_resolutions:
        return {
            "status": "skipped_no_evaluable_permutations",
            "n_permutations": n_permutations,
            "method": "wave_membership_label_permutation",
        }

    null_arr = np.array(null_resolutions)
    obs = observed_resolution if observed_resolution is not None else 0.0
    # Plus-one correction (Phipson & Smyth 2010): prevents p=0 when no
    # exceedances are observed.  With n_permutations=500 the minimum
    # representable p is 1/501 ≈ 0.001996.
    # pre-registered 2026-08-28.
    n_exceed = int(np.sum(null_arr >= obs))
    p_empirical = (n_exceed + 1) / (len(null_arr) + 1)

    return {
        "status": "computed",
        "method": "wave_membership_label_permutation",
        "n_permutations": n_permutations,
        "seed": seed,
        "observed_transition_resolution": observed_resolution,
        "null_mean": round(float(np.mean(null_arr)), 6),
        "null_std": round(float(np.std(null_arr)), 6),
        "null_5th_pct": round(float(np.percentile(null_arr, 5)), 6),
        "null_95th_pct": round(float(np.percentile(null_arr, 95)), 6),
        "n_exceedances": n_exceed,
        "p_empirical_one_sided": round(p_empirical, 6),
        # Legacy field kept for backward compat; equals p_empirical_one_sided
        "p_value_resolution_ge_observed": round(p_empirical, 6),
        "interpretation": (
            "p_empirical_one_sided: one-sided empirical p-value with plus-one correction "
            "(Phipson & Smyth 2010). "
            "Tests whether transition_resolution exceeds random Wave membership. "
            "Does not test temporal ordering — see time_index_permutation_test for that. "
            "Does not imply kinase-level mechanism."
        ),
    }


def _time_index_permutation_test(
    wave_contract: Mapping[str, Any],
    timepoints: Sequence[str],
    trajectories: Mapping[str, Sequence[float | None]],
    config: Mapping[str, Any],
    n_permutations: int,
    seed: int,
) -> dict[str, Any]:
    """Estimate null distribution by shuffling time-index order (same shuffle all sites).

    Unlike Wave-membership permutation, this null preserves:
    - Which sites belong to which Wave (group structure unchanged)
    - The per-site distribution of FC values
    - Cross-site contemporaneous correlation structure (all sites get the same shuffle)

    It disrupts:
    - Temporal adjacency ordering between consecutive windows

    Question answered: "Is the observed temporal ordering more informative than
    random temporal ordering?" — distinct from the Wave-membership question.

    Implementation target: Roadmap §3 time-index permutation.
    Pre-registration: 2026-08-28.  n_permutations, seed, and the use of uniform
      cross-site shuffling are frozen before inhibitor data is seen.
    Interpretation limits: tests temporal ordering informativeness, not kinase
      attribution accuracy.
    Claim boundary: significant p-value supports non-random temporal structure;
      does not imply causal mechanism.
    """
    if len(timepoints) < 3:
        return {
            "status": "skipped_too_few_timepoints",
            "n_permutations": 0,
            "method": "time_index_permutation",
        }

    observed_result = _annotate_once(
        wave_contract=wave_contract,
        timepoints=list(timepoints),
        trajectories=trajectories,
        config=config,
    )
    observed_resolution = observed_result["summary"].get("transition_resolution")

    rng = np.random.default_rng(seed)
    null_resolutions: list[float] = []
    tp_list = list(timepoints)

    for _ in range(n_permutations):
        # Same permutation of time indices applied to all sites
        idx = rng.permutation(len(tp_list)).tolist()
        shuffled_tps = [tp_list[i] for i in idx]
        shuffled_trajectories = {
            key: [list(values)[i] for i in idx]
            for key, values in trajectories.items()
        }
        perm_result = _annotate_once(
            wave_contract=wave_contract,
            timepoints=shuffled_tps,
            trajectories=shuffled_trajectories,
            config={
                **config,
                "minimum_observed_timepoints": min(
                    int(config["minimum_observed_timepoints"]), len(tp_list)
                ),
            },
        )
        r = perm_result["summary"].get("transition_resolution")
        if r is not None:
            null_resolutions.append(r)

    if not null_resolutions:
        return {
            "status": "skipped_no_evaluable_permutations",
            "n_permutations": n_permutations,
            "method": "time_index_permutation",
        }

    null_arr = np.array(null_resolutions)
    obs = observed_resolution if observed_resolution is not None else 0.0
    n_exceed = int(np.sum(null_arr >= obs))
    p_empirical = (n_exceed + 1) / (len(null_arr) + 1)

    return {
        "status": "computed",
        "method": "time_index_permutation",
        "n_permutations": n_permutations,
        "seed": seed,
        "observed_transition_resolution": observed_resolution,
        "null_mean": round(float(np.mean(null_arr)), 6),
        "null_std": round(float(np.std(null_arr)), 6),
        "null_5th_pct": round(float(np.percentile(null_arr, 5)), 6),
        "null_95th_pct": round(float(np.percentile(null_arr, 95)), 6),
        "n_exceedances": n_exceed,
        "p_empirical_one_sided": round(p_empirical, 6),
        "interpretation": (
            "p_empirical_one_sided: one-sided empirical p-value with plus-one correction. "
            "Tests whether the observed temporal ordering produces higher transition_resolution "
            "than random time-index shuffles (same shuffle applied to all sites simultaneously). "
            "Distinct from Wave-membership permutation — answers a different null hypothesis. "
            "Does not imply kinase-level mechanism."
        ),
    }


# ── Permutation test defaults (pre-registered 2026-08-28) ─────────────────
# n_permutations=500: balance between runtime and null-distribution resolution.
#   With plus-one correction, minimum representable p-value = 1/(500+1) ≈ 0.001996.
#   Increasing to 2000 is valid exploratory analysis; do not change threshold
#   after observing inhibitor results.
PERMUTATION_N_DEFAULT: int = 500
PERMUTATION_SEED_DEFAULT: int = 20260828


def analyze_dynamic_co_wave_transitions(
    wave_contract: Mapping[str, Any],
    *,
    config: Mapping[str, Any] | None = None,
    permutation_test: bool = False,
    permutation_n: int = PERMUTATION_N_DEFAULT,
    permutation_seed: int = PERMUTATION_SEED_DEFAULT,
    time_index_permutation_test: bool = False,
    time_index_permutation_n: int = PERMUTATION_N_DEFAULT,
    time_index_permutation_seed: int = PERMUTATION_SEED_DEFAULT,
    t_adjacency_test: bool = False,
    t_adjacency_random_n: int = 10000,
    t_adjacency_seed: int = PERMUTATION_SEED_DEFAULT,
) -> dict[str, Any]:
    """Create additive local transition evidence for immutable static Waves.

    permutation_test=True — Wave-membership label permutation null (Roadmap §3).
      Tests: "Is transition_resolution above random group assignment?"
    time_index_permutation_test=True — time-index permutation null (Roadmap §3).
      Tests: "Is the observed temporal ordering more informative than random?"
      Note: p=0.570858 was observed (2026-08-28) — transition_resolution was NOT
      significant for temporal ordering with this test.
    t_adjacency_test=True — T_adjacency statistic with exact permutation (n≤8 tp).
      Tests: "Are co-active pairs more stable between adjacent than distant timepoints?"
      Recommended primary temporal statistic (Image §2.1, 2026-08-28).
    All tests are disabled by default for production latency; enable for analysis runs.
    """

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
        "pair_scope": annotation.get("pair_scope"),
        "event_exposure": annotation.get("event_exposure"),
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
    if permutation_test:
        annotation["permutation_test"] = _wave_membership_permutation_test(
            wave_contract=wave_contract,
            timepoints=timepoints,
            trajectories=trajectories,
            config=effective,
            n_permutations=permutation_n,
            seed=permutation_seed,
        )
    else:
        annotation["permutation_test"] = {"status": "not_requested"}

    if time_index_permutation_test:
        annotation["time_index_permutation_test"] = _time_index_permutation_test(
            wave_contract=wave_contract,
            timepoints=timepoints,
            trajectories=trajectories,
            config=effective,
            n_permutations=time_index_permutation_n,
            seed=time_index_permutation_seed,
        )
    else:
        annotation["time_index_permutation_test"] = {"status": "not_requested"}

    if t_adjacency_test:
        annotation["t_adjacency_test"] = compute_temporal_adjacency_statistic(
            wave_contract=wave_contract,
            timepoints=timepoints,
            trajectories=trajectories,
            config=effective,
            random_n=t_adjacency_random_n,
            seed=t_adjacency_seed,
        )
    else:
        annotation["t_adjacency_test"] = {"status": "not_requested"}

    return annotation
