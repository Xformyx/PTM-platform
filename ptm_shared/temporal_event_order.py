"""Additive observed event-time evidence for canonical temporal Wave members.

Design boundary
---------------
This module transforms ordered, protein-normalized PTM trajectories into
observed half-amplitude crossing times.  It does not alter Wave membership,
TMM coefficients, kinase ranks, or Dynamic Co-Wave v2 transitions.  It also
does not infer kinase identity, direct regulation, propagation, or causality.

Replicate boundary
------------------
The current shared Wave contract carries condition-level vectors.  Accordingly
this module makes censoring explicit but labels time-order uncertainty as not
evaluable until raw biological replicate values are supplied by a later input
contract.  A condition mean must never be presented as a replicate-derived CI.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Sequence

import numpy as np

from ptm_shared.directed_temporal_relationship import timepoint_to_minutes


CONTRACT_VERSION = "temporal_event_order.v1"

DEFAULT_CONFIG: dict[str, Any] = {
    "minimum_observed_timepoints": 4,
    "minimum_amplitude_fc": 0.40,
    "half_amplitude_fraction": 0.50,
    "reference_level": 0.0,
    "input_level": "condition_mean_only",
    "bootstrap_repeats": 200,
    "bootstrap_seed": 20260828,
    "minimum_replicates_per_timepoint": 2,
    "minimum_resolved_bootstrap_fraction": 0.80,
}


def _finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _effective_config(config: Mapping[str, Any] | None) -> tuple[dict[str, Any], str]:
    effective = dict(DEFAULT_CONFIG)
    for key in DEFAULT_CONFIG:
        if config and config.get(key) is not None:
            effective[key] = config[key]
    effective["minimum_observed_timepoints"] = max(2, int(effective["minimum_observed_timepoints"]))
    effective["minimum_amplitude_fc"] = max(0.0, float(effective["minimum_amplitude_fc"]))
    effective["half_amplitude_fraction"] = min(1.0, max(0.0, float(effective["half_amplitude_fraction"])))
    effective["reference_level"] = float(effective["reference_level"])
    effective["input_level"] = str(effective["input_level"])
    effective["bootstrap_repeats"] = max(0, int(effective["bootstrap_repeats"]))
    effective["bootstrap_seed"] = int(effective["bootstrap_seed"])
    effective["minimum_replicates_per_timepoint"] = max(2, int(effective["minimum_replicates_per_timepoint"]))
    effective["minimum_resolved_bootstrap_fraction"] = min(
        1.0, max(0.0, float(effective["minimum_resolved_bootstrap_fraction"]))
    )
    serialized = json.dumps(effective, sort_keys=True, separators=(",", ":"))
    return effective, hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _time_axis_status(timepoints: Sequence[str]) -> tuple[list[float], list[str]]:
    minutes = [timepoint_to_minutes(value) for value in timepoints]
    flags: list[str] = []
    if any(not math.isfinite(value) for value in minutes):
        flags.append("unparseable_timepoint")
    if any(minutes[index] >= minutes[index + 1] for index in range(len(minutes) - 1)):
        flags.append("non_strictly_increasing_time_axis")
    return minutes, flags


def _empty_site_event(site_key: str, *, status: str, quality_flags: Sequence[str]) -> dict[str, Any]:
    return {
        "site_key": site_key,
        "event_status": status,
        "direction": None,
        "amplitude_fc": None,
        "t50_minutes": None,
        "t50_interval": None,
        "peak_minutes": None,
        "peak_time_status": "not_evaluable",
        "observed_timepoint_count": 0,
        "missing_timepoint_count": 0,
        "quality_flags": list(quality_flags),
        "replicate_uncertainty_status": "not_evaluable_condition_mean_only",
        "interpretation_boundary": "No temporal relation, kinase attribution, or causal conclusion is implied.",
    }


def extract_observed_event_time(
    site_key: str,
    timepoints: Sequence[str],
    values: Sequence[Any],
    *,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return an observed signed half-amplitude crossing with explicit censoring.

    Values are assumed to be protein-normalized log2 fold changes relative to a
    stated zero reference.  The routine does not extrapolate before the first
    observed point or after the final observed point.  If the first observed
    value has already crossed the half-amplitude target, event time is marked
    left-censored rather than invented at time zero.
    """

    effective, config_hash = _effective_config(config)
    labels = [str(value) for value in timepoints]
    if len(labels) != len(values):
        result = _empty_site_event(site_key, status="invalid_input_length", quality_flags=["time_value_length_mismatch"])
        result["config_sha256"] = config_hash
        return result
    minutes, axis_flags = _time_axis_status(labels)
    if axis_flags:
        result = _empty_site_event(site_key, status="invalid_time_axis", quality_flags=axis_flags)
        result["config_sha256"] = config_hash
        return result

    observations: list[tuple[float, float]] = []
    for minute, raw_value in zip(minutes, values):
        parsed_value = _finite_float(raw_value)
        if parsed_value is not None:
            observations.append((minute, parsed_value))
    missing_count = len(labels) - len(observations)
    if len(observations) < effective["minimum_observed_timepoints"]:
        result = _empty_site_event(
            site_key,
            status="insufficient_observed_timepoints",
            quality_flags=["insufficient_observed_timepoints"],
        )
        result["observed_timepoint_count"] = len(observations)
        result["missing_timepoint_count"] = missing_count
        result["config_sha256"] = config_hash
        return result

    reference = effective["reference_level"]
    peak_index = max(range(len(observations)), key=lambda index: abs(observations[index][1] - reference))
    peak_minutes, peak_value = observations[peak_index]
    signed_amplitude = peak_value - reference
    amplitude = abs(signed_amplitude)
    if amplitude < effective["minimum_amplitude_fc"]:
        result = _empty_site_event(site_key, status="below_amplitude_gate", quality_flags=["below_amplitude_gate"])
        result["amplitude_fc"] = amplitude
        result["peak_minutes"] = peak_minutes
        result["peak_time_status"] = "right_censored" if peak_index == len(observations) - 1 else "observed"
        result["observed_timepoint_count"] = len(observations)
        result["missing_timepoint_count"] = missing_count
        result["config_sha256"] = config_hash
        return result

    direction = "up" if signed_amplitude > 0 else "down"
    oriented = [(minute, (value - reference) * (1 if direction == "up" else -1)) for minute, value in observations]
    target = amplitude * effective["half_amplitude_fraction"]
    first_minute, first_oriented = oriented[0]
    event_status = "resolved_interpolated"
    t50_minutes: float | None = None
    t50_interval: dict[str, float] | None = None
    quality_flags: list[str] = []
    if first_oriented >= target:
        event_status = "left_censored_before_first_observed"
        t50_interval = {"upper_bound_minutes": first_minute}
        quality_flags.append("first_observation_already_half_amplitude")
    else:
        for index in range(1, len(oriented)):
            left_minute, left_value = oriented[index - 1]
            right_minute, right_value = oriented[index]
            if left_value < target <= right_value:
                if right_value == target:
                    t50_minutes = right_minute
                    event_status = "resolved_at_observed_timepoint"
                else:
                    fraction = (target - left_value) / (right_value - left_value)
                    t50_minutes = left_minute + fraction * (right_minute - left_minute)
                t50_interval = {"left_minutes": left_minute, "right_minutes": right_minute}
                break
        if t50_minutes is None:
            event_status = "unresolved_nonmonotone_or_missing_crossing"
            quality_flags.append("half_amplitude_crossing_not_observed")

    return {
        "site_key": site_key,
        "event_status": event_status,
        "direction": direction,
        "amplitude_fc": round(amplitude, 6),
        "t50_minutes": None if t50_minutes is None else round(t50_minutes, 6),
        "t50_interval": t50_interval,
        "peak_minutes": peak_minutes,
        "peak_time_status": "right_censored" if peak_index == len(observations) - 1 else "observed",
        "observed_timepoint_count": len(observations),
        "missing_timepoint_count": missing_count,
        "quality_flags": quality_flags,
        "replicate_uncertainty_status": "not_evaluable_condition_mean_only",
        "config_sha256": config_hash,
        "interpretation_boundary": (
            "Observed condition-mean timing with explicit censoring only; it is not a replicate CI, "
            "kinase attribution, direct regulation, propagation, or causal evidence."
        ),
    }


def _stable_site_seed(site_key: str, seed: int) -> int:
    digest = hashlib.sha256(str(site_key).encode("utf-8")).digest()
    return (seed + int.from_bytes(digest[:8], byteorder="big", signed=False)) % (2**63 - 1)


def bootstrap_event_time_uncertainty(
    site_key: str,
    timepoints: Sequence[str],
    replicate_values: Mapping[str, Sequence[Any]] | None,
    *,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Estimate a site event-time CI from raw within-timepoint replicate values.

    Replicates are resampled independently inside each observed timepoint.  This
    is a bootstrap uncertainty annotation for an individual event descriptor;
    it neither creates paired longitudinal replicates nor tests directed order
    between two biological entities.
    """

    effective, _ = _effective_config(config)
    if not replicate_values:
        return {
            "replicate_uncertainty_status": "not_evaluable_condition_mean_only",
            "t50_bootstrap_ci95": None,
            "resolved_bootstrap_fraction": None,
            "bootstrap_repeats": 0,
            "interpretation_boundary": "Condition means alone cannot yield a replicate-derived event-time CI.",
        }
    per_timepoint: list[list[float]] = []
    for label in timepoints:
        values: list[float] = []
        for raw_value in list(replicate_values.get(str(label)) or []):
            parsed = _finite_float(raw_value)
            if parsed is not None:
                values.append(parsed)
        if len(values) < effective["minimum_replicates_per_timepoint"]:
            return {
                "replicate_uncertainty_status": "not_evaluable_incomplete_replicate_coverage",
                "t50_bootstrap_ci95": None,
                "resolved_bootstrap_fraction": None,
                "bootstrap_repeats": 0,
                "interpretation_boundary": "Every reported timepoint needs the configured minimum replicate coverage for a bootstrap event-time CI.",
            }
        per_timepoint.append(values)
    if effective["bootstrap_repeats"] <= 0:
        return {
            "replicate_uncertainty_status": "not_computed_bootstrap_disabled",
            "t50_bootstrap_ci95": None,
            "resolved_bootstrap_fraction": None,
            "bootstrap_repeats": 0,
            "interpretation_boundary": "Replicate values were supplied but bootstrap computation was disabled by configuration.",
        }

    rng = np.random.default_rng(_stable_site_seed(site_key, effective["bootstrap_seed"]))
    resolved_times: list[float] = []
    base_config = {**effective, "input_level": "replicate_bootstrap_mean"}
    for _ in range(effective["bootstrap_repeats"]):
        sampled_means = [
            float(np.mean(rng.choice(values, size=len(values), replace=True)))
            for values in per_timepoint
        ]
        event = extract_observed_event_time(site_key, timepoints, sampled_means, config=base_config)
        if event.get("t50_minutes") is not None:
            resolved_times.append(float(event["t50_minutes"]))
    fraction = len(resolved_times) / effective["bootstrap_repeats"]
    if fraction < effective["minimum_resolved_bootstrap_fraction"]:
        return {
            "replicate_uncertainty_status": "not_evaluable_bootstrap_censoring_or_instability",
            "t50_bootstrap_ci95": None,
            "resolved_bootstrap_fraction": round(fraction, 6),
            "bootstrap_repeats": effective["bootstrap_repeats"],
            "interpretation_boundary": "Too many bootstrap trajectories were censored or unresolved; no event-time CI is reported.",
        }
    return {
        "replicate_uncertainty_status": "bootstrap_ci95_available",
        "t50_bootstrap_ci95": {
            "lower_minutes": round(float(np.percentile(resolved_times, 2.5)), 6),
            "upper_minutes": round(float(np.percentile(resolved_times, 97.5)), 6),
        },
        "resolved_bootstrap_fraction": round(fraction, 6),
        "bootstrap_repeats": effective["bootstrap_repeats"],
        "interpretation_boundary": "Within-timepoint replicate bootstrap CI for an observed site event only; it is not a source-target order test or causal evidence.",
    }


def _wave_summary(wave: Mapping[str, Any], events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    resolved = [float(row["t50_minutes"]) for row in events if row.get("t50_minutes") is not None]
    left_censored = sum(row.get("event_status") == "left_censored_before_first_observed" for row in events)
    right_censored = sum(row.get("peak_time_status") == "right_censored" for row in events)
    ci_available = sum(row.get("replicate_uncertainty_status") == "bootstrap_ci95_available" for row in events)
    return {
        "wave_id": str(wave.get("wave_id") or wave.get("cluster_id") or "unknown_wave"),
        "member_count": len(events),
        "resolved_event_count": len(resolved),
        "event_estimability_fraction": round(len(resolved) / len(events), 6) if events else 0.0,
        "median_t50_minutes": round(sorted(resolved)[len(resolved) // 2], 6) if resolved else None,
        "left_censored_event_count": left_censored,
        "right_censored_peak_count": right_censored,
        "replicate_ci95_available_event_count": ci_available,
        "replicate_uncertainty_status": (
            "bootstrap_ci95_partially_available" if ci_available else "not_evaluable_condition_mean_only"
        ),
        "interpretation_boundary": "Observed Wave member event times; no Wave-to-Wave direction or causal relation is inferred.",
    }


def build_temporal_event_order_evidence(
    wave_contract: Mapping[str, Any],
    *,
    config: Mapping[str, Any] | None = None,
    replicate_time_series: Mapping[str, Mapping[str, Sequence[Any]]] | None = None,
) -> dict[str, Any]:
    """Build a sidecar-safe event-time contract from immutable Wave members."""

    effective, config_hash = _effective_config(config)
    timepoints = [str(value) for value in (wave_contract.get("timepoints") or [])]
    _, axis_flags = _time_axis_status(timepoints)
    if len(timepoints) < 2 or axis_flags:
        return {
            "contract_version": CONTRACT_VERSION,
            "status": "not_evaluable_invalid_time_axis",
            "timepoints": timepoints,
            "site_events": [],
            "per_wave_summary": [],
            "summary": {
                "site_event_count": 0,
                "temporal_order_validation_status": "not_evaluable_invalid_time_axis",
            },
            "provenance": {"config": effective, "config_sha256": config_hash, "membership_mutation": "forbidden"},
            "quality_flags": axis_flags or ["fewer_than_two_timepoints"],
            "interpretation_boundary": "No temporal ordering result is available from an invalid time axis.",
        }

    site_events: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for wave in wave_contract.get("waves") or []:
        wave_events: list[dict[str, Any]] = []
        for detail in wave.get("member_details") or []:
            site_key = str(detail.get("key") or "unknown_site")
            values = [dict(detail.get("temporal_values") or {}).get(label) for label in timepoints]
            event = extract_observed_event_time(site_key, timepoints, values, config=effective)
            event.update(
                bootstrap_event_time_uncertainty(
                    site_key,
                    timepoints,
                    (replicate_time_series or {}).get(site_key),
                    config=effective,
                )
            )
            event["static_wave_id"] = str(wave.get("wave_id") or wave.get("cluster_id") or "unknown_wave")
            wave_events.append(event)
            site_events.append(event)
        summaries.append(_wave_summary(wave, wave_events))

    resolved_count = sum(row.get("t50_minutes") is not None for row in site_events)
    ci_available_count = sum(row.get("replicate_uncertainty_status") == "bootstrap_ci95_available" for row in site_events)
    return {
        "contract_version": CONTRACT_VERSION,
        "status": "computed_condition_mean_only",
        "timepoints": timepoints,
        "site_events": site_events,
        "per_wave_summary": summaries,
        "summary": {
            "site_event_count": len(site_events),
            "resolved_event_count": resolved_count,
            "event_estimability_fraction": round(resolved_count / len(site_events), 6) if site_events else 0.0,
            "replicate_uncertainty_status": (
                "bootstrap_ci95_partially_available" if ci_available_count else "not_evaluable_condition_mean_only"
            ),
            "replicate_ci95_available_event_count": ci_available_count,
            "temporal_order_validation_status": "not_evaluable_replicate_missing",
            "current_transition_resolution_status": "not_supported_as_time_order_statistic",
        },
        "provenance": {
            "config": effective,
            "config_sha256": config_hash,
            "membership_source": "immutable_temporal_wave_contract",
            "membership_mutation": "forbidden",
            "tmm_mutation": "forbidden",
            "benchmark_truth_used": False,
            "rag_used": False,
            "llm_used": False,
            "input_level": "replicate_values_ephemeral" if replicate_time_series else effective["input_level"],
            "raw_replicate_values_persisted": False,
        },
        "interpretation_boundary": (
            "A timing record is an observed condition-mean event descriptor. It does not establish a precise "
            "event order, kinase activation, direct regulation, propagation, or causality without replicate-aware "
            "uncertainty and a separately specified relation test."
        ),
    }
