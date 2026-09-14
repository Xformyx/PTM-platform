"""Signed adjacent-interval substrate diagnostics for kinase candidates.

구현 대상: docs/collaboration/integrated_implementation_w0_2026-09-14.md
사전등록: 2026-09-14. 기존 TMM 점수 산출과 분리한 보조 관측 계약.
해석 한계: 구간 Δ·상관은 촉매속도·직접 효소관계·성능 향상이 아니다.
주장 금지: 이 값으로 kinase 귀속 정확도나 하류 개선을 논하지 않는다.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import numpy as np

from ptm_shared.directed_temporal_relationship import timepoint_to_minutes


CONTRACT_VERSION = "kinase_trajectory_evidence.v1"
ROLE = "additive_observational_evidence"
MIN_COMMON_POINTS = 3
"""Level correlation 계산 조건.

docs/collaboration/integrated_implementation_w0_2026-09-14.md 에서
2026-09-14 선언. 최소 공통 시점은 계산 조건이며 생물학적 충분 기준이 아니다.
"""
MIN_COMMON_INTERVALS = 3
"""Interval-rate correlation 계산 조건.

같은 W0 문서에서 2026-09-14 선언. 2구간 ±1을 강한 근거로 발표하지 않는다.
"""
DELTA_TOLERANCE = 0.0
"""방향 판정에서 실제 0과 부호를 구분하는 기술적 허용.

W0에서 2026-09-14 선언. 기존 표시 ±0.15 밴드를 재사용하지 않는다.
"""
MIN_ANCHOR_GROUPS_FOR_MEDIAN = 1
"""Anchor median을 내보낼 최소 group 수.

W0에서 2026-09-14 선언. 1이면 값은 정의되지만 단일 기질 의존으로 기록한다.
"""


def elapsed_minutes(label: Any) -> float | None:
    """Parse scheduled elapsed time. Unknown labels stay unknown."""
    value = timepoint_to_minutes(label)
    return float(value) if math.isfinite(value) else None


def observed_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def measurement_group_id(key: str, identity: Mapping[str, Any] | None) -> str:
    """Exclude the same modified peptide / confirmed same-site group together.

    Unclear identity is not pooled. Feature count is not biological n.
    """
    ident = dict(identity or {})
    sequence = str(ident.get("modified_sequence") or ident.get("Modified.Sequence") or "").strip()
    parent = str(
        ident.get("protein_group")
        or ident.get("protein")
        or ident.get("gene")
        or ""
    ).strip()
    site = str(ident.get("confirmed_site") or ident.get("position") or ident.get("site") or "").strip()
    confirmed_same_site = bool(ident.get("same_site_confirmed") or ident.get("confirmed_same_site"))
    if sequence and parent:
        return f"{parent}|seq:{sequence}"
    if confirmed_same_site and parent and site:
        return f"{parent}|site:{site}"
    return f"ungrouped:{key}"


def scheduled_intervals(conditions: Sequence[str]) -> list[dict[str, Any]]:
    """Adjacent pairs on the scheduled grid. Missing middles are not bridged."""
    intervals: list[dict[str, Any]] = []
    for index in range(len(conditions) - 1):
        start, end = str(conditions[index]), str(conditions[index + 1])
        t0, t1 = elapsed_minutes(start), elapsed_minutes(end)
        if t0 is None or t1 is None:
            intervals.append({
                "interval_id": f"{start}->{end}",
                "from": start,
                "to": end,
                "dt_minutes": None,
                "status": "not_evaluable",
                "reason": "unknown_elapsed_time",
            })
            continue
        if t1 <= t0:
            intervals.append({
                "interval_id": f"{start}->{end}",
                "from": start,
                "to": end,
                "dt_minutes": None,
                "status": "not_evaluable",
                "reason": "nonpositive_or_duplicate_time",
            })
            continue
        intervals.append({
            "interval_id": f"{start}->{end}",
            "from": start,
            "to": end,
            "dt_minutes": t1 - t0,
            "status": "scheduled",
            "reason": None,
        })
    return intervals


def interval_delta(series: Mapping[str, Any], start: str, end: str) -> float | None:
    left = observed_float(series.get(start) if isinstance(series, Mapping) else None)
    right = observed_float(series.get(end) if isinstance(series, Mapping) else None)
    if left is None or right is None:
        return None
    return right - left


def direction_of(delta: float | None, *, tolerance: float = DELTA_TOLERANCE) -> str:
    if delta is None:
        return "not_evaluable"
    if abs(delta) <= tolerance:
        return "flat"
    return "increase" if delta > 0 else "decrease"


def _pearson(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) < MIN_COMMON_POINTS or len(left) != len(right):
        return None
    left_array = np.asarray(left, dtype=float)
    right_array = np.asarray(right, dtype=float)
    if not np.all(np.isfinite(left_array)) or not np.all(np.isfinite(right_array)):
        return None
    if float(np.std(left_array)) == 0.0 or float(np.std(right_array)) == 0.0:
        return None
    value = float(np.corrcoef(left_array, right_array)[0, 1])
    return value if math.isfinite(value) else None


def _series_track(key: str, representation: Mapping[str, Any] | None) -> str:
    payload = (representation or {}).get(key) or {}
    if isinstance(payload, Mapping):
        return str(payload.get("track") or payload.get("quantification_track") or "unadjusted")
    return "unadjusted"


def _eligible_keys(
    keys: Sequence[str],
    timeseries: Mapping[str, Mapping[str, Any]],
    *,
    denovo_keys: set[str] | None,
    representation: Mapping[str, Any] | None,
    required_track: str,
) -> list[str]:
    denovo = {str(item) for item in (denovo_keys or set())}
    eligible = []
    for key in keys:
        if str(key) in denovo:
            continue
        if _series_track(str(key), representation) != required_track:
            continue
        if str(key) not in timeseries:
            continue
        eligible.append(str(key))
    return eligible


def _anchor_deltas(
    interval: Mapping[str, Any],
    timeseries: Mapping[str, Mapping[str, Any]],
    eligible_keys: Sequence[str],
    identities: Mapping[str, Mapping[str, Any]] | None,
    exclude_groups: set[str],
) -> dict[str, Any]:
    if interval.get("status") != "scheduled":
        return {"status": "not_evaluable", "reason": interval.get("reason"), "deltas": {}, "n_anchor_groups": 0}
    start, end = interval["from"], interval["to"]
    by_group: dict[str, list[float]] = {}
    for key in eligible_keys:
        group = measurement_group_id(key, (identities or {}).get(key))
        if group in exclude_groups:
            continue
        delta = interval_delta(timeseries.get(key) or {}, start, end)
        if delta is None:
            continue
        by_group.setdefault(group, []).append(delta)
    # One observation per group: median of that group's own deltas if several
    # charge/site-confirmed members remain after exclusion.
    group_deltas = {group: float(np.median(values)) for group, values in by_group.items()}
    if len(group_deltas) < MIN_ANCHOR_GROUPS_FOR_MEDIAN:
        return {
            "status": "not_evaluable",
            "reason": "no_eligible_anchor_after_group_exclusion",
            "deltas": group_deltas,
            "n_anchor_groups": 0,
        }
    return {
        "status": "computed",
        "reason": None,
        "deltas": group_deltas,
        "n_anchor_groups": len(group_deltas),
        "anchor_median": float(np.median(list(group_deltas.values()))),
        "membership_changed": False,
    }


def _fixed_common_groups(
    intervals: Sequence[Mapping[str, Any]],
    timeseries: Mapping[str, Mapping[str, Any]],
    eligible_keys: Sequence[str],
    identities: Mapping[str, Mapping[str, Any]] | None,
    exclude_groups: set[str],
) -> set[str]:
    common: set[str] | None = None
    for interval in intervals:
        if interval.get("status") != "scheduled":
            continue
        present = set()
        for key in eligible_keys:
            group = measurement_group_id(key, (identities or {}).get(key))
            if group in exclude_groups:
                continue
            if interval_delta(timeseries.get(key) or {}, interval["from"], interval["to"]) is None:
                continue
            present.add(group)
        if common is None:
            common = present
        else:
            common &= present
    return common or set()


def _level_reference(
    conditions: Sequence[str],
    timeseries: Mapping[str, Mapping[str, Any]],
    eligible_keys: Sequence[str],
    identities: Mapping[str, Mapping[str, Any]] | None,
    exclude_groups: set[str],
    target_observed: Sequence[str],
) -> dict[str, float | None]:
    """Median of a fixed anchor-group set on times shared with the target."""
    groups_by_time: dict[str, dict[str, float]] = {str(condition): {} for condition in target_observed}
    for key in eligible_keys:
        group = measurement_group_id(key, (identities or {}).get(key))
        if group in exclude_groups:
            continue
        series = timeseries.get(key) or {}
        for condition in target_observed:
            value = observed_float(series.get(condition))
            if value is None:
                continue
            groups_by_time[str(condition)][group] = value
    common_groups: set[str] | None = None
    for condition in target_observed:
        present = set(groups_by_time[str(condition)])
        common_groups = present if common_groups is None else common_groups & present
    common_groups = common_groups or set()
    reference: dict[str, float | None] = {}
    for condition in target_observed:
        values = [groups_by_time[str(condition)][group] for group in common_groups]
        reference[str(condition)] = float(np.median(values)) if values else None
    return reference


def compute_target_trajectory_evidence(
    *,
    candidate: str,
    target_key: str,
    timeseries: Mapping[str, Mapping[str, Any]],
    conditions: Sequence[str],
    eligible_keys: Sequence[str],
    identities: Mapping[str, Mapping[str, Any]] | None = None,
    iterative_shared_keys: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Compare one target to anchors that exclude its measurement group."""
    target_series = timeseries.get(target_key) or {}
    target_group = measurement_group_id(target_key, (identities or {}).get(target_key))
    exclude = {target_group}
    intervals = scheduled_intervals(conditions)
    used_in_iterative = target_key in {str(item) for item in (iterative_shared_keys or [])}
    target_observed = [str(condition) for condition in conditions if observed_float(target_series.get(condition)) is not None]
    reference_levels = _level_reference(
        conditions, timeseries, eligible_keys, identities, exclude, target_observed,
    )
    common_level_times = [
        condition for condition in target_observed
        if reference_levels.get(condition) is not None
    ]
    signed_profile_correlation = _pearson(
        [float(observed_float(target_series.get(condition))) for condition in common_level_times],
        [float(reference_levels[condition]) for condition in common_level_times],
    )
    interval_records = []
    same = opposite = both_flat = one_flat = not_evaluable = 0
    target_rates: list[float] = []
    anchor_rates: list[float] = []
    common_groups = _fixed_common_groups(intervals, timeseries, eligible_keys, identities, exclude)
    for interval in intervals:
        target_delta = interval_delta(target_series, interval["from"], interval["to"]) if interval["status"] == "scheduled" else None
        anchors = _anchor_deltas(interval, timeseries, eligible_keys, identities, exclude)
        fixed_deltas = [anchors["deltas"][group] for group in common_groups if group in anchors.get("deltas", {})] if anchors.get("status") == "computed" else []
        anchor_median = anchors.get("anchor_median") if anchors.get("status") == "computed" else None
        if interval["status"] != "scheduled":
            comparison = "not_evaluable"
            not_evaluable += 1
        elif target_delta is None or anchor_median is None:
            comparison = "not_evaluable"
            not_evaluable += 1
        else:
            target_dir = direction_of(target_delta)
            anchor_dir = direction_of(float(anchor_median))
            if target_dir == "flat" and anchor_dir == "flat":
                comparison = "both_flat"
                both_flat += 1
            elif "flat" in {target_dir, anchor_dir}:
                comparison = "one_flat"
                one_flat += 1
            elif target_dir == anchor_dir:
                comparison = "same_direction"
                same += 1
            else:
                comparison = "opposite_direction"
                opposite += 1
            dt = interval.get("dt_minutes")
            if dt and dt > 0:
                target_rates.append(target_delta / dt)
                anchor_rates.append(float(anchor_median) / dt)
        interval_records.append({
            **interval,
            "target_delta": target_delta,
            "anchor_median_delta": anchor_median,
            "n_anchor_groups": anchors.get("n_anchor_groups", 0),
            "fixed_common_anchor_groups": len(fixed_deltas),
            "comparison": comparison,
            "anchor_status": anchors.get("status"),
            "anchor_reason": anchors.get("reason"),
        })
    directional = same + opposite
    concordance = (same / directional) if directional else None
    rate_correlation = _pearson(target_rates, anchor_rates) if len(target_rates) >= MIN_COMMON_INTERVALS else None
    loto = []
    for omitted in conditions:
        remaining = [interval for interval in interval_records if omitted not in {interval["from"], interval["to"]}]
        remain_same = sum(1 for interval in remaining if interval["comparison"] == "same_direction")
        remain_opp = sum(1 for interval in remaining if interval["comparison"] == "opposite_direction")
        remain_den = remain_same + remain_opp
        loto.append({
            "omitted_condition": omitted,
            "bridged": False,
            "remaining_scheduled_intervals": len(remaining),
            "direction_concordance_fraction": (remain_same / remain_den) if remain_den else None,
            "denominator": remain_den,
        })
    other_groups = sorted({
        measurement_group_id(key, (identities or {}).get(key))
        for key in eligible_keys
        if measurement_group_id(key, (identities or {}).get(key)) not in exclude
    })
    omission_sensitivity = []
    for group in other_groups:
        dropped_same = dropped_opp = 0
        for interval in intervals:
            target_delta = interval_delta(target_series, interval["from"], interval["to"]) if interval["status"] == "scheduled" else None
            anchors = _anchor_deltas(interval, timeseries, eligible_keys, identities, exclude | {group})
            if target_delta is None or anchors.get("status") != "computed":
                continue
            target_dir = direction_of(target_delta)
            anchor_dir = direction_of(float(anchors["anchor_median"]))
            if target_dir in {"increase", "decrease"} and anchor_dir in {"increase", "decrease"}:
                if target_dir == anchor_dir:
                    dropped_same += 1
                else:
                    dropped_opp += 1
        dropped_den = dropped_same + dropped_opp
        omission_sensitivity.append({
            "omitted_anchor_group": group,
            "direction_concordance_fraction": (dropped_same / dropped_den) if dropped_den else None,
            "denominator": dropped_den,
        })
    support_status = "computed" if directional or signed_profile_correlation is not None else "not_evaluable"
    if not eligible_keys or all(
        measurement_group_id(key, (identities or {}).get(key)) in exclude for key in eligible_keys
    ):
        support_status = "not_evaluable"
    return {
        "contract_version": CONTRACT_VERSION,
        "role": ROLE,
        "candidate": candidate,
        "target_key": target_key,
        "measurement_group": target_group,
        "support_status": support_status,
        "used_in_iterative_profile": used_in_iterative,
        "anchor_rebuilt_without_target": True,
        "metrics": {
            "signed_profile_correlation": {
                "value": signed_profile_correlation,
                "n_common_points": len(common_level_times),
                "unit": "pearson_r",
                "status": "computed" if signed_profile_correlation is not None else "not_evaluable",
            },
            "interval_direction_support": interval_records,
            "direction_concordance_fraction": {
                "value": concordance,
                "numerator": same,
                "denominator": directional,
                "both_flat": both_flat,
                "one_flat": one_flat,
                "not_evaluable": not_evaluable,
                "scheduled_intervals": len(intervals),
                "unit": "fraction",
                "status": "computed" if concordance is not None else "not_evaluable",
            },
            "interval_rate_correlation": {
                "value": rate_correlation,
                "n_common_intervals": len(target_rates),
                "unit": "pearson_r_log2_contrast_per_min",
                "status": "computed" if rate_correlation is not None else "not_evaluable",
            },
            "timepoint_omission_robustness": loto,
            "anchor_omission_sensitivity": omission_sensitivity or [{
                "status": "not_evaluable",
                "reason": "no_alternate_anchor_group",
            }],
        },
        "estimator": CONTRACT_VERSION,
        "delta_tolerance": DELTA_TOLERANCE,
    }


def compute_kinase_trajectory_evidence(
    *,
    candidate: str,
    target_keys: Sequence[str],
    timeseries: Mapping[str, Mapping[str, Any]],
    conditions: Sequence[str],
    identities: Mapping[str, Mapping[str, Any]] | None = None,
    denovo_keys: set[str] | Sequence[str] | Mapping[str, Any] | None = None,
    representation: Mapping[str, Any] | None = None,
    iterative_shared_keys: Sequence[str] | None = None,
    required_track: str = "unadjusted",
) -> dict[str, Any]:
    """Kinase-level summary. Does not alter NNLS ratios or weighted sums."""
    if isinstance(denovo_keys, Mapping):
        denovo_set = {str(key) for key, flag in denovo_keys.items() if flag}
    else:
        denovo_set = {str(key) for key in (denovo_keys or [])}
    eligible = _eligible_keys(
        list(target_keys),
        timeseries,
        denovo_keys=denovo_set,
        representation=representation,
        required_track=required_track,
    )
    targets = []
    for key in eligible:
        targets.append(compute_target_trajectory_evidence(
            candidate=candidate,
            target_key=key,
            timeseries=timeseries,
            conditions=conditions,
            eligible_keys=eligible,
            identities=identities,
            iterative_shared_keys=iterative_shared_keys,
        ))
    evaluable = [row for row in targets if row.get("support_status") == "computed"]
    correlations = [
        row["metrics"]["signed_profile_correlation"]["value"]
        for row in evaluable
        if row["metrics"]["signed_profile_correlation"]["value"] is not None
    ]
    concordances = [
        row["metrics"]["direction_concordance_fraction"]["value"]
        for row in evaluable
        if row["metrics"]["direction_concordance_fraction"]["value"] is not None
    ]
    return {
        "contract_version": CONTRACT_VERSION,
        "role": ROLE,
        "candidate": candidate,
        "n_targets_considered": len(target_keys),
        "n_targets_eligible": len(eligible),
        "n_targets_excluded_denovo_or_track": len(target_keys) - len(eligible),
        "n_targets_evaluable": len(evaluable),
        "support_status": "computed" if evaluable else "not_evaluable",
        "unavailable_reason": None if evaluable else "no_evaluable_signed_interval_comparison",
        "median_signed_profile_correlation": float(np.median(correlations)) if correlations else None,
        "median_direction_concordance_fraction": float(np.median(concordances)) if concordances else None,
        "targets": targets,
        "estimator": CONTRACT_VERSION,
        "does_not_modify": ["nnls_ratio", "weighted_up_sums", "weighted_down_sums", "ranking"],
    }


def attach_trajectory_evidence(
    results: dict[str, dict],
    *,
    kinase_modules: Sequence[Mapping[str, Any]],
    ptm_timeseries: Mapping[str, Mapping[str, Any]],
    conditions: Sequence[str],
    identities: Mapping[str, Mapping[str, Any]] | None = None,
    denovo_keys: Any = None,
    representation: Mapping[str, Any] | None = None,
) -> dict[str, dict]:
    """Write ``trajectory_evidence`` only. Weighted sums stay untouched."""
    members_by_kinase = {}
    iterative_keys: dict[str, list[str]] = {}
    for module in kinase_modules or []:
        canonical = str(module.get("canonical") or module.get("kinase") or "").upper()
        keys = [str(member.get("key")) for member in module.get("members") or [] if member.get("key")]
        members_by_kinase[canonical] = keys
    for canonical, payload in results.items():
        provenance = payload.get("iterative_profile_provenance") or {}
        if isinstance(provenance, Mapping):
            iterative_keys[canonical] = list(provenance.get("iterative_shared_keys") or [])
        payload["trajectory_evidence"] = compute_kinase_trajectory_evidence(
            candidate=canonical,
            target_keys=members_by_kinase.get(canonical, []),
            timeseries=ptm_timeseries,
            conditions=conditions,
            identities=identities,
            denovo_keys=denovo_keys,
            representation=representation,
            iterative_shared_keys=iterative_keys.get(canonical),
        )
    return results
