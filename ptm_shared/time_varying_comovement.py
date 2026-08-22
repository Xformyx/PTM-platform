"""Observed time-varying PTM co-movement transitions for Temporal Atlas.

This module records when pairs of quality-qualified site/form trajectories are
co-active in one adjacent time window and persist, split, merge, recruit, or
exit in the next.  It describes observed membership transitions only; edges
are not causal arrows and never establish kinase regulation.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from itertools import combinations
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ptm_shared.substrate_temporal_dynamics import SiteKineticProfile


CONTRACT_VERSION = "time_varying_comovement.v1"
STATE_INACTIVE = "inactive"
STATE_POSITIVE_ACTIVE = "positive_active"
STATE_NEGATIVE_ACTIVE = "negative_active"


@dataclass(frozen=True)
class TimeVaryingCoMovementConfig:
    activity_threshold_fc: float = 0.5
    min_window_observed: int = 2
    require_atlas_eligible: bool = True


@dataclass
class WindowMembership:
    site_key: str
    window_index: int
    window_label: str
    activity_state: str
    start_value: Optional[float]
    end_value: Optional[float]
    local_delta: Optional[float]


@dataclass
class PairTransition:
    site_a: str
    site_b: str
    from_window: str
    to_window: str
    transition_type: str
    prior_states: Tuple[str, str]
    next_states: Tuple[str, str]


@dataclass
class SiteTransition:
    site_key: str
    from_window: str
    to_window: str
    transition_type: str
    prior_state: str
    next_state: str
    partner_count_before: int
    partner_count_after: int


@dataclass
class TimeVaryingCoMovementResult:
    memberships: List[WindowMembership]
    pair_transitions: List[PairTransition]
    site_transitions: List[SiteTransition]
    transition_counts: Dict[str, int]
    excluded_sites: Dict[str, List[str]]
    contract_version: str = CONTRACT_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _activity_state(value: Optional[float], threshold: float) -> str:
    if value is None or abs(value) < threshold:
        return STATE_INACTIVE
    return STATE_POSITIVE_ACTIVE if value > 0 else STATE_NEGATIVE_ACTIVE


def _coactive_pair(state_a: str, state_b: str) -> bool:
    return state_a != STATE_INACTIVE and state_a == state_b


def _trajectory_values(
    values: Sequence[Optional[float]],
    expected_length: int,
) -> Optional[List[Optional[float]]]:
    if len(values) != expected_length:
        return None
    normalized: List[Optional[float]] = []
    for value in values:
        if value is None:
            normalized.append(None)
        else:
            try:
                normalized.append(float(value))
            except (TypeError, ValueError):
                return None
    return normalized


def compute_time_varying_comovement(
    timepoint_labels: Sequence[str],
    site_trajectories: Mapping[str, Sequence[Optional[float]]],
    *,
    profiles: Optional[Mapping[str, SiteKineticProfile]] = None,
    config: Optional[TimeVaryingCoMovementConfig] = None,
) -> TimeVaryingCoMovementResult:
    """Compute adjacent-window membership transitions for qualified sites.

    Each window is the observed interval from consecutive labels.  A site is
    co-active with another site only if both end-window values exceed the
    configured threshold with the same sign.  This intentionally conservative
    rule avoids treating two-point local correlation as proof of shared control.
    """
    config = config or TimeVaryingCoMovementConfig()
    labels = list(timepoint_labels)
    n_timepoints = len(labels)
    if n_timepoints < 2:
        return TimeVaryingCoMovementResult([], [], [], {}, {})

    excluded: Dict[str, List[str]] = {}
    qualified: Dict[str, List[Optional[float]]] = {}
    for site_key, trajectory in site_trajectories.items():
        values = _trajectory_values(trajectory, n_timepoints)
        reasons: List[str] = []
        if values is None:
            reasons.append("trajectory_length_or_value_mismatch")
        profile = profiles.get(site_key) if profiles is not None else None
        if config.require_atlas_eligible:
            if profile is None:
                reasons.append("profile_unavailable")
            elif not profile.atlas_eligible:
                reasons.extend(profile.atlas_eligibility_reasons or ["atlas_ineligible"])
        if values is not None and sum(value is not None for value in values) < config.min_window_observed:
            reasons.append("insufficient_observed_timepoints")
        if reasons:
            excluded[site_key] = sorted(set(reasons))
        else:
            qualified[site_key] = values  # type: ignore[assignment]

    memberships: List[WindowMembership] = []
    states_by_window: List[Dict[str, str]] = []
    window_labels: List[str] = []
    for index in range(n_timepoints - 1):
        window_label = f"{labels[index]}→{labels[index + 1]}"
        window_labels.append(window_label)
        states: Dict[str, str] = {}
        for site_key, values in qualified.items():
            start, end = values[index], values[index + 1]
            state = _activity_state(end, config.activity_threshold_fc)
            states[site_key] = state
            memberships.append(WindowMembership(
                site_key=site_key,
                window_index=index,
                window_label=window_label,
                activity_state=state,
                start_value=start,
                end_value=end,
                local_delta=(end - start) if start is not None and end is not None else None,
            ))
        states_by_window.append(states)

    pair_transitions: List[PairTransition] = []
    site_transitions: List[SiteTransition] = []
    all_sites = sorted(qualified)
    for index in range(len(states_by_window) - 1):
        before = states_by_window[index]
        after = states_by_window[index + 1]
        before_label, after_label = window_labels[index], window_labels[index + 1]
        before_partners: Dict[str, set[str]] = defaultdict(set)
        after_partners: Dict[str, set[str]] = defaultdict(set)

        for site_a, site_b in combinations(all_sites, 2):
            prior_pair = _coactive_pair(before[site_a], before[site_b])
            next_pair = _coactive_pair(after[site_a], after[site_b])
            if prior_pair:
                before_partners[site_a].add(site_b)
                before_partners[site_b].add(site_a)
            if next_pair:
                after_partners[site_a].add(site_b)
                after_partners[site_b].add(site_a)

            if prior_pair and next_pair:
                transition_type = "persistence"
            elif prior_pair and not next_pair:
                transition_type = "split"
            elif not prior_pair and next_pair:
                if before[site_a] == STATE_INACTIVE or before[site_b] == STATE_INACTIVE:
                    transition_type = "recruitment"
                else:
                    transition_type = "merge"
            else:
                continue
            pair_transitions.append(PairTransition(
                site_a=site_a,
                site_b=site_b,
                from_window=before_label,
                to_window=after_label,
                transition_type=transition_type,
                prior_states=(before[site_a], before[site_b]),
                next_states=(after[site_a], after[site_b]),
            ))

        for site_key in all_sites:
            prior_state, next_state = before[site_key], after[site_key]
            partners_before = len(before_partners[site_key])
            partners_after = len(after_partners[site_key])
            if prior_state != STATE_INACTIVE and next_state == STATE_INACTIVE:
                site_transition = "exit"
            elif prior_state == STATE_INACTIVE and next_state != STATE_INACTIVE and partners_after == 0:
                site_transition = "independent_activation"
            elif partners_before == 0 and partners_after > 0:
                site_transition = "joined_group"
            elif partners_before > 0 and partners_after == 0 and next_state != STATE_INACTIVE:
                site_transition = "split_from_group"
            elif partners_before > 0 and partners_after > 0:
                site_transition = "group_persistence"
            else:
                site_transition = "state_unchanged_or_inactive"
            site_transitions.append(SiteTransition(
                site_key=site_key,
                from_window=before_label,
                to_window=after_label,
                transition_type=site_transition,
                prior_state=prior_state,
                next_state=next_state,
                partner_count_before=partners_before,
                partner_count_after=partners_after,
            ))

    counts = Counter(item.transition_type for item in pair_transitions)
    counts.update(item.transition_type for item in site_transitions)
    return TimeVaryingCoMovementResult(
        memberships=memberships,
        pair_transitions=pair_transitions,
        site_transitions=site_transitions,
        transition_counts=dict(sorted(counts.items())),
        excluded_sites=excluded,
    )
