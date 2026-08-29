"""P1: Replicate-aware event record adapter.

Extracts per-site event records (onset / peak / exit times with CIs) from
time-course trajectories.

DESIGN CONTRACT
---------------
- condition-mean-only input → event records with input_type="condition_mean_gp"
  and replicate_bootstrap_stability=None (flagged not_evaluable_replicate_posterior).
- replicate-level input → full bootstrap_stability using actual replicates.
- Event records NEVER modify static Wave membership, TMM scores, or any locked score.
- Claim boundary: express as "observed response timing", not "activation/causality".

EVENT STATUS RULES
------------------
unresolved    max |posterior_mean| < amplitude_threshold            → no activation
left_censored |mean[0]| >= amplitude_threshold * onset_fraction     → onset before grid
right_censored after peak, |mean[-1]| >= amplitude_threshold * exit_fraction → exit after grid
ambiguous     threshold crossed but CI overlaps threshold in both directions
resolved      onset + peak + exit all within grid with CI within grid

CLAIM LIMITS (PDF §2 Table)
---------------------------
onset_t50_min     → "observed response timing", NOT "activation/causality"
peak_t_min        → do NOT claim peak outside the measured time grid
exit_t50_min      → right_censored means unknown, NOT "no exit"
replicate_bootstrap_stability → NOT a biological effect size or p-value

Implementation target: PDF §2 P1.
Pre-registration: 2026-08-29.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np

from ptm_shared.probabilistic_cowave import (
    ACTIVITY_THRESHOLD_FC,
    GP_LENGTH_SCALE_MIN,
    estimate_trajectory_posterior,
)
from ptm_shared.study_temporal_context import (
    INSULIN_TEMPORAL_CONTEXT,
    StudyTemporalContext,
)

CONTRACT_VERSION = "replicate_event_adapter.v1"


class EventStatus(str, enum.Enum):
    resolved = "resolved"
    left_censored = "left_censored"
    right_censored = "right_censored"
    ambiguous = "ambiguous"
    unresolved = "unresolved"
    not_evaluable_replicate_posterior = "not_evaluable_replicate_posterior"


@dataclass
class EventRecord:
    """Per-site temporal event record.

    All time values are in **minutes** (canonical internal unit).

    Claim limits:
      - onset/peak/exit times are observed response timing, NOT causal activation.
      - peak outside the measured time window cannot be claimed.
      - right_censored exit means the response did not resolve before the last
        timepoint; it does NOT mean there is no exit.
      - replicate_bootstrap_stability is structural consistency, NOT effect size.
    """

    site_key: str
    event_status: EventStatus

    # Timing estimates (None when not computable for this status)
    onset_t50_min: float | None = None
    onset_ci95_min: tuple[float, float] | None = None

    peak_t_min: float | None = None
    peak_ci95_min: tuple[float, float] | None = None
    peak_fc: float | None = None

    exit_t50_min: float | None = None
    exit_ci95_min: tuple[float, float] | None = None

    # Fraction [0, 1] of bootstrap resamples where event_status is consistent.
    # None when input is condition-mean only (not_evaluable_replicate_posterior).
    replicate_bootstrap_stability: float | None = None

    # Provenance
    input_type: str = "condition_mean_gp"
    n_replicates_used: int | None = None
    amplitude_threshold_fc: float = ACTIVITY_THRESHOLD_FC
    contract_version: str = CONTRACT_VERSION

    # Interpretation notes
    censoring_note: str | None = None
    claim_limit: str = (
        "onset_t50 = observed response timing; "
        "not activation/causality. "
        "peak outside grid cannot be claimed. "
        "right_censored exit ≠ no exit."
    )


# ── Event extraction from GP posterior ────────────────────────────────────

_N_PARAMETRIC_BOOTSTRAP = 500
_PARAMETRIC_BOOTSTRAP_SEED = 20260829


def _find_crossing_time(
    times: np.ndarray,
    values: np.ndarray,
    threshold: float,
    *,
    direction: str = "up",
    after_idx: int = 0,
) -> float | None:
    """Return interpolated time of first threshold crossing (up or down).

    direction='up': first crossing from below to above threshold.
    direction='down': first crossing from above to below threshold.
    after_idx: only search from this index onward.
    Returns None if no crossing found.
    """
    for i in range(after_idx, len(values) - 1):
        v0, v1 = values[i], values[i + 1]
        if direction == "up" and v0 < threshold <= v1:
            frac = (threshold - v0) / (v1 - v0)
            return float(times[i] + frac * (times[i + 1] - times[i]))
        if direction == "down" and v0 >= threshold > v1:
            frac = (v0 - threshold) / (v0 - v1)
            return float(times[i] + frac * (times[i + 1] - times[i]))
    return None


def _event_times_from_trajectory(
    times_min: np.ndarray,
    mean_traj: np.ndarray,
    amplitude_threshold: float,
    *,
    onset_fraction: float = 0.5,
    exit_fraction: float = 0.5,
    raw_first_abs_fc: float | None = None,
    raw_last_abs_fc: float | None = None,
) -> dict[str, Any]:
    """Extract onset / peak / exit from a single trajectory array.

    Censoring detection uses raw FC boundary values (not GP posterior) because
    left/right censoring is a data-observation statement: was the response already
    active before the first measurement, or still active after the last?
    GP smoothing lifts the posterior mean at boundary timepoints due to nearby
    high values, which would incorrectly trigger left_censored when FC[0] = 0.

    Parameters
    ----------
    raw_first_abs_fc : override for left-censoring check (raw |FC| at t=0).
        If None, falls back to |mean_traj[0]|.
    raw_last_abs_fc : override for right-censoring check (raw |FC| at t=-1).
        If None, falls back to |mean_traj[-1]|.

    Returns dict with: direction, onset_t, peak_t, peak_fc, exit_t, status.
    """
    abs_mean = np.abs(mean_traj)
    peak_idx = int(np.argmax(abs_mean))
    peak_fc = float(mean_traj[peak_idx])
    peak_t = float(times_min[peak_idx])
    max_abs = float(abs_mean[peak_idx])

    if max_abs < amplitude_threshold:
        return {
            "status": EventStatus.unresolved,
            "onset_t": None,
            "peak_t": peak_t,
            "peak_fc": peak_fc,
            "exit_t": None,
            "direction": "none",
        }

    direction = "positive" if peak_fc > 0 else "negative"
    signed = mean_traj if direction == "positive" else -mean_traj
    onset_thresh = amplitude_threshold * onset_fraction
    exit_thresh = amplitude_threshold * exit_fraction

    # Left/onset determination: use raw FC[0] when available.
    # GP smoothing can lift posterior mean at the first timepoint above the
    # onset threshold even when raw FC[0] = 0 (due to nearby high FC values).
    # We distinguish three cases:
    #   raw_first >= onset_thresh  → left_censored (response active before grid)
    #   raw_first < onset_thresh   → NOT left_censored; onset IS within the grid.
    #                                Set onset_t = times_min[0] as lower bound since
    #                                GP crossing before t[0] is an artefact.
    #   raw_first is None/unknown  → fall back to GP posterior (conservative)
    if raw_first_abs_fc is not None and not (raw_first_abs_fc != raw_first_abs_fc):
        first_val = float(raw_first_abs_fc)
        if first_val >= onset_thresh:
            onset_t = None
            status_onset = EventStatus.left_censored
        else:
            # Onset is within grid: use t[0] as lower bound,
            # then refine with GP posterior (may be at t[0] if smooth value >= thresh)
            gp_crossing = _find_crossing_time(times_min, signed, onset_thresh, direction="up")
            onset_t = gp_crossing if gp_crossing is not None else float(times_min[0])
            status_onset = EventStatus.resolved
    else:
        # raw_first unknown (NaN or None) — fall back to GP posterior
        first_signed = abs(float(signed[0]))
        if first_signed >= onset_thresh:
            onset_t = None
            status_onset = EventStatus.left_censored
        else:
            onset_t = _find_crossing_time(times_min, signed, onset_thresh, direction="up")
            status_onset = EventStatus.resolved if onset_t is not None else EventStatus.ambiguous

    # Right censoring: use raw FC[-1] if provided
    last_signed = (
        raw_last_abs_fc
        if raw_last_abs_fc is not None
        else abs(float(signed[-1]))
    )
    if last_signed >= exit_thresh:
        exit_t = None
        status_exit = EventStatus.right_censored
    else:
        exit_t = _find_crossing_time(
            times_min, signed, exit_thresh, direction="down", after_idx=peak_idx
        )
        status_exit = EventStatus.resolved if exit_t is not None else EventStatus.ambiguous

    # Combine status
    if status_onset == EventStatus.left_censored:
        final_status = EventStatus.left_censored
    elif status_exit == EventStatus.right_censored:
        final_status = EventStatus.right_censored
    elif status_onset == EventStatus.resolved and status_exit == EventStatus.resolved:
        final_status = EventStatus.resolved
    else:
        final_status = EventStatus.ambiguous

    return {
        "status": final_status,
        "onset_t": onset_t,
        "peak_t": peak_t,
        "peak_fc": peak_fc,
        "exit_t": exit_t,
        "direction": direction,
    }


def _parametric_bootstrap_stability(
    times_min: np.ndarray,
    posterior_mean: np.ndarray,
    posterior_std: np.ndarray,
    amplitude_threshold: float,
    *,
    n_samples: int = _N_PARAMETRIC_BOOTSTRAP,
    seed: int = _PARAMETRIC_BOOTSTRAP_SEED,
) -> float:
    """Fraction of GP posterior samples with consistent event_status.

    Uses diagonal approximation (independent per-timepoint noise).
    This is a structural consistency estimate — NOT a p-value or effect size.
    Only valid for condition-mean GP posteriors; true replicate bootstrap
    requires actual per-replicate intensity values.
    """
    rng = np.random.default_rng(seed)
    reference = _event_times_from_trajectory(
        times_min, posterior_mean, amplitude_threshold
    )
    ref_status = reference["status"]
    consistent = 0
    for _ in range(n_samples):
        sample_traj = rng.normal(posterior_mean, posterior_std)
        sample_ev = _event_times_from_trajectory(
            times_min, sample_traj, amplitude_threshold
        )
        if sample_ev["status"] == ref_status:
            consistent += 1
    return round(consistent / n_samples, 4)


def _ci_from_samples(values: list[float | None]) -> tuple[float, float] | None:
    """95% CI from a list of values (ignoring None)."""
    valid = [v for v in values if v is not None]
    if len(valid) < 10:
        return None
    arr = np.array(valid)
    return (round(float(np.percentile(arr, 2.5)), 3),
            round(float(np.percentile(arr, 97.5)), 3))


def extract_event_record(
    site_key: str,
    timepoint_labels: Sequence[str],
    fc_values: Sequence[float | None],
    *,
    study_context: StudyTemporalContext | None = None,
    amplitude_threshold: float | None = None,
    n_bootstrap: int = _N_PARAMETRIC_BOOTSTRAP,
    seed: int = _PARAMETRIC_BOOTSTRAP_SEED,
) -> EventRecord:
    """Extract event record for a single site from condition-mean FC trajectory.

    Uses GP posterior (condition-mean) with parametric bootstrap for CI.
    For true replicate-level uncertainty, pass per-replicate data to
    extract_event_record_from_replicates() instead.

    Parameters
    ----------
    site_key : str
    timepoint_labels : ordered sequence of timepoint labels
    fc_values : log2FC values aligned to timepoint_labels (None = missing)
    study_context : StudyTemporalContext (uses insulin default if None)
    amplitude_threshold : override activity threshold (default from context or GP default)
    """
    ctx = study_context or INSULIN_TEMPORAL_CONTEXT
    thresh = amplitude_threshold if amplitude_threshold is not None else ctx.gp_length_scale_min_minutes

    # Use GP_LENGTH_SCALE_MIN from context; fall back to global default
    gp_ls = ctx.gp_length_scale_min_minutes
    thresh = amplitude_threshold if amplitude_threshold is not None else ACTIVITY_THRESHOLD_FC

    posterior = estimate_trajectory_posterior(
        timepoint_labels,
        fc_values,
        length_scale_min=gp_ls,
    )
    from ptm_shared.probabilistic_cowave import _timepoints_to_minutes
    times_min = _timepoints_to_minutes(list(timepoint_labels))
    mean_arr = np.array(posterior["posterior_mean"])
    std_arr = np.array(posterior["posterior_std"])

    # Raw FC boundary values for censoring detection (bypass GP smoothing effect)
    raw_fcs = [v if v is not None else float("nan") for v in fc_values]
    raw_first = abs(raw_fcs[0]) if not (len(raw_fcs) > 0 and raw_fcs[0] != raw_fcs[0]) else None
    raw_last = abs(raw_fcs[-1]) if not (len(raw_fcs) > 0 and raw_fcs[-1] != raw_fcs[-1]) else None

    # Point estimate event times
    ref_ev = _event_times_from_trajectory(
        times_min, mean_arr, thresh,
        raw_first_abs_fc=raw_first,
        raw_last_abs_fc=raw_last,
    )

    # Parametric bootstrap CI
    bootstrap_onset: list[float | None] = []
    bootstrap_peak: list[float | None] = []
    bootstrap_exit: list[float | None] = []
    rng = np.random.default_rng(seed)
    for _ in range(n_bootstrap):
        sample = rng.normal(mean_arr, std_arr)
        ev = _event_times_from_trajectory(
            times_min, sample, thresh,
            raw_first_abs_fc=raw_first,
            raw_last_abs_fc=raw_last,
        )
        bootstrap_onset.append(ev["onset_t"])
        bootstrap_peak.append(ev["peak_t"])
        bootstrap_exit.append(ev["exit_t"])

    onset_ci = _ci_from_samples(bootstrap_onset)
    peak_ci = _ci_from_samples(bootstrap_peak)
    exit_ci = _ci_from_samples(bootstrap_exit)

    stability = _parametric_bootstrap_stability(
        times_min, mean_arr, std_arr, thresh,
        n_samples=n_bootstrap, seed=seed + 1
    )

    status = ref_ev["status"]
    censoring_note: str | None = None
    if status == EventStatus.left_censored:
        censoring_note = ctx.censoring_left_note
    elif status == EventStatus.right_censored:
        censoring_note = ctx.censoring_right_note

    return EventRecord(
        site_key=site_key,
        event_status=status,
        onset_t50_min=round(ref_ev["onset_t"], 3) if ref_ev["onset_t"] is not None else None,
        onset_ci95_min=onset_ci,
        peak_t_min=round(ref_ev["peak_t"], 3) if ref_ev["peak_t"] is not None else None,
        peak_ci95_min=peak_ci,
        peak_fc=round(ref_ev["peak_fc"], 4) if ref_ev["peak_fc"] is not None else None,
        exit_t50_min=round(ref_ev["exit_t"], 3) if ref_ev["exit_t"] is not None else None,
        exit_ci95_min=exit_ci,
        replicate_bootstrap_stability=stability,
        input_type="condition_mean_gp_parametric_bootstrap",
        n_replicates_used=None,
        amplitude_threshold_fc=thresh,
        censoring_note=censoring_note,
    )


def extract_event_record_from_replicates(
    site_key: str,
    timepoint_labels: Sequence[str],
    replicate_fc_matrix: np.ndarray,
    *,
    study_context: StudyTemporalContext | None = None,
    amplitude_threshold: float | None = None,
    n_bootstrap: int = 200,
    seed: int = _PARAMETRIC_BOOTSTRAP_SEED,
) -> EventRecord:
    """Extract event record from per-replicate FC matrix.

    Parameters
    ----------
    replicate_fc_matrix : shape [n_replicates, n_timepoints]. NaN for missing.
    """
    ctx = study_context or INSULIN_TEMPORAL_CONTEXT
    gp_ls = ctx.gp_length_scale_min_minutes
    thresh = amplitude_threshold if amplitude_threshold is not None else ACTIVITY_THRESHOLD_FC

    from ptm_shared.probabilistic_cowave import _timepoints_to_minutes
    times_min = _timepoints_to_minutes(list(timepoint_labels))
    n_rep = replicate_fc_matrix.shape[0]

    # Condition-mean GP for point estimates
    cond_mean = np.nanmean(replicate_fc_matrix, axis=0).tolist()
    posterior = estimate_trajectory_posterior(
        timepoint_labels, cond_mean, length_scale_min=gp_ls
    )
    mean_arr = np.array(posterior["posterior_mean"])

    ref_ev = _event_times_from_trajectory(times_min, mean_arr, thresh)

    # True replicate bootstrap: resample replicates
    rng = np.random.default_rng(seed)
    bootstrap_onset: list[float | None] = []
    bootstrap_peak: list[float | None] = []
    bootstrap_exit: list[float | None] = []
    status_counts: dict[str, int] = {}

    for _ in range(n_bootstrap):
        idx = rng.integers(0, n_rep, size=n_rep)
        sample_matrix = replicate_fc_matrix[idx, :]
        sample_mean = np.nanmean(sample_matrix, axis=0).tolist()
        b_posterior = estimate_trajectory_posterior(
            timepoint_labels, sample_mean, length_scale_min=gp_ls
        )
        b_mean = np.array(b_posterior["posterior_mean"])
        ev = _event_times_from_trajectory(times_min, b_mean, thresh)
        bootstrap_onset.append(ev["onset_t"])
        bootstrap_peak.append(ev["peak_t"])
        bootstrap_exit.append(ev["exit_t"])
        status_counts[ev["status"].value] = status_counts.get(ev["status"].value, 0) + 1

    stability = round(
        status_counts.get(ref_ev["status"].value, 0) / n_bootstrap, 4
    )

    return EventRecord(
        site_key=site_key,
        event_status=ref_ev["status"],
        onset_t50_min=round(ref_ev["onset_t"], 3) if ref_ev["onset_t"] is not None else None,
        onset_ci95_min=_ci_from_samples(bootstrap_onset),
        peak_t_min=round(ref_ev["peak_t"], 3) if ref_ev["peak_t"] is not None else None,
        peak_ci95_min=_ci_from_samples(bootstrap_peak),
        peak_fc=round(ref_ev["peak_fc"], 4) if ref_ev["peak_fc"] is not None else None,
        exit_t50_min=round(ref_ev["exit_t"], 3) if ref_ev["exit_t"] is not None else None,
        exit_ci95_min=_ci_from_samples(bootstrap_exit),
        replicate_bootstrap_stability=stability,
        input_type="replicate_level_bootstrap",
        n_replicates_used=n_rep,
        amplitude_threshold_fc=thresh,
    )


def build_event_records_for_wave_contract(
    wave_contract: Mapping[str, Any],
    *,
    study_context: StudyTemporalContext | None = None,
    amplitude_threshold: float | None = None,
) -> dict[str, EventRecord]:
    """Build EventRecord for every site in a wave_contract.

    Returns {site_key: EventRecord}.  Never mutates the wave_contract.
    """
    ctx = study_context or INSULIN_TEMPORAL_CONTEXT
    timepoints: list[str] = wave_contract.get("timepoints", [])
    records: dict[str, EventRecord] = {}

    for wave in wave_contract.get("waves", []):
        for detail in wave.get("member_details", []):
            key = detail["key"]
            tv: dict[str, float | None] = detail.get("temporal_values", {})
            fc_values = [tv.get(tp) for tp in timepoints]
            records[key] = extract_event_record(
                key, timepoints, fc_values,
                study_context=ctx,
                amplitude_threshold=amplitude_threshold,
            )
    return records


def not_evaluable_record(site_key: str, reason: str = "condition_mean_only") -> EventRecord:
    """Return a not_evaluable stub record when replicate data is unavailable."""
    return EventRecord(
        site_key=site_key,
        event_status=EventStatus.not_evaluable_replicate_posterior,
        input_type="not_evaluable_replicate_posterior",
        claim_limit=(
            "Replicate-level posterior is not evaluable. "
            "Condition-mean GP estimates are available via extract_event_record(). "
            f"Reason: {reason}"
        ),
    )
