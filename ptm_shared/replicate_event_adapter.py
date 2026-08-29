"""P1: Replicate-aware event record adapter.

Extracts per-site event records (onset / peak / exit times with CIs) from
time-course trajectories.

CONTEXT REGISTRATION RULE (Fix-1, 2026-08-29 audit)
-----------------------------------------------------
study_context MUST be provided explicitly.
Passing study_context=None returns EventStatus.not_evaluable_context_not_registered.
Functions NEVER silently default to INSULIN_TEMPORAL_CONTEXT because that would
make the temporal analysis insulin-specific without the caller's knowledge.

The only place INSULIN_TEMPORAL_CONTEXT is used is:
  - unit tests that explicitly call study_context=INSULIN_TEMPORAL_CONTEXT
  - insulin-specific benchmark runner code

REPLICATE VS CONDITION-MEAN CONFIDENCE (Fix-3, 2026-08-29 audit)
-----------------------------------------------------------------
replicate_bootstrap_stability : float | None
  Set ONLY when input_type="replicate_level_bootstrap" (actual per-replicate
  intensity series). True biological replicate stability — NOT a p-value.

exploratory_model_uncertainty : float | None
  Set when input_type="condition_mean_gp_parametric_bootstrap".
  Fraction of diagonal-approximation GP posterior samples with consistent
  event_status. This is GP model uncertainty, NOT replicate stability.
  Label explicitly as exploratory; never conflate with replicate_bootstrap_stability.

DESIGN CONTRACT
---------------
- condition-mean-only input → onset/peak/exit CIs from parametric GP draws.
  replicate_bootstrap_stability=None (not evaluable).
  exploratory_model_uncertainty = GP parametric fraction.
- replicate-level input → full replicate_bootstrap_stability using actual replicates.
  exploratory_model_uncertainty=None (not applicable).
- Event records NEVER modify static Wave membership, TMM scores, or any locked score.
- Claim boundary: express as "observed response timing", not "activation/causality".

EVENT STATUS RULES
------------------
unresolved                       max |posterior_mean| < amplitude_threshold
left_censored                    raw FC[0] >= amplitude_threshold * onset_fraction
right_censored                   raw FC[-1] >= amplitude_threshold * exit_fraction
ambiguous                        threshold crossed but CI overlaps threshold
resolved                         onset + peak + exit all within grid
not_evaluable_replicate_posterior replicate data absent; condition-mean available
not_evaluable_context_not_registered study_context not provided; no analysis run

CLAIM LIMITS (PDF §2 Table)
---------------------------
onset_t50_min     → "observed response timing", NOT "activation/causality"
peak_t_min        → do NOT claim peak outside the measured time grid
exit_t50_min      → right_censored means unknown, NOT "no exit"
replicate_bootstrap_stability → NOT a biological effect size or p-value
exploratory_model_uncertainty → GP model internal consistency ONLY

Implementation target: PDF §2 P1.
Pre-registration: 2026-08-29.
Audit remediation: 2026-08-29 (context registration rule, replicate/GP separation).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np

from ptm_shared.probabilistic_cowave import (
    ACTIVITY_THRESHOLD_FC,
    estimate_trajectory_posterior,
)
from ptm_shared.study_temporal_context import StudyTemporalContext

CONTRACT_VERSION = "replicate_event_adapter.v2"

_NOT_REGISTERED_MSG = (
    "study_context=None is not allowed. "
    "Pass an explicit StudyTemporalContext. "
    "To use the insulin context in a test, pass study_context=INSULIN_TEMPORAL_CONTEXT "
    "from ptm_shared.study_temporal_context explicitly."
)


class EventStatus(str, enum.Enum):
    resolved = "resolved"
    left_censored = "left_censored"
    right_censored = "right_censored"
    ambiguous = "ambiguous"
    unresolved = "unresolved"
    not_evaluable_replicate_posterior = "not_evaluable_replicate_posterior"
    not_evaluable_context_not_registered = "not_evaluable_context_not_registered"


@dataclass
class EventRecord:
    """Per-site temporal event record.

    All time values are in **minutes** (canonical internal unit).

    Claim limits:
      - onset/peak/exit times are observed response timing, NOT causal activation.
      - peak outside the measured time window cannot be claimed.
      - right_censored exit means the response did not resolve before the last
        timepoint; it does NOT mean there is no exit.
      - replicate_bootstrap_stability is structural replicate consistency, NOT
        effect size or p-value.
      - exploratory_model_uncertainty is GP model internal consistency ONLY;
        do NOT conflate with replicate_bootstrap_stability.
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

    # True replicate bootstrap stability (replicate-level input only).
    # None when input is condition-mean.
    replicate_bootstrap_stability: float | None = None

    # GP parametric bootstrap consistency (condition-mean input only).
    # NOT a replicate stability estimate — GP model uncertainty only.
    # None when input is replicate-level.
    exploratory_model_uncertainty: float | None = None

    # Provenance
    input_type: str = "unknown"
    n_replicates_used: int | None = None
    bootstrap_evaluable_draw_fraction: float | None = None
    amplitude_threshold_fc: float = ACTIVITY_THRESHOLD_FC
    contract_version: str = CONTRACT_VERSION

    # Interpretation notes
    censoring_note: str | None = None
    claim_limit: str = (
        "onset_t50 = observed response timing; "
        "not activation/causality. "
        "peak outside grid cannot be claimed. "
        "right_censored exit ≠ no exit. "
        "exploratory_model_uncertainty ≠ replicate_bootstrap_stability."
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
        If None or NaN, falls back to GP posterior |mean_traj[0]|.
    raw_last_abs_fc : override for right-censoring check (raw |FC| at t=-1).
        If None or NaN, falls back to GP posterior |mean_traj[-1]|.

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
    # GP smoothing can lift posterior mean at t=0 above onset threshold even
    # when raw FC[0]=0 (due to nearby high FC values). Censoring is a
    # data-observation statement, not a model statement.
    def _is_valid_float(v: float | None) -> bool:
        return v is not None and v == v  # NaN check

    if _is_valid_float(raw_first_abs_fc):
        first_val = float(raw_first_abs_fc)  # type: ignore[arg-type]
        if first_val >= onset_thresh:
            onset_t = None
            status_onset = EventStatus.left_censored
        else:
            gp_crossing = _find_crossing_time(times_min, signed, onset_thresh, direction="up")
            onset_t = gp_crossing if gp_crossing is not None else float(times_min[0])
            status_onset = EventStatus.resolved
    else:
        first_signed = abs(float(signed[0]))
        if first_signed >= onset_thresh:
            onset_t = None
            status_onset = EventStatus.left_censored
        else:
            onset_t = _find_crossing_time(times_min, signed, onset_thresh, direction="up")
            status_onset = EventStatus.resolved if onset_t is not None else EventStatus.ambiguous

    if _is_valid_float(raw_last_abs_fc):
        last_val = float(raw_last_abs_fc)  # type: ignore[arg-type]
    else:
        last_val = abs(float(signed[-1]))

    if last_val >= exit_thresh:
        exit_t = None
        status_exit = EventStatus.right_censored
    else:
        exit_t = _find_crossing_time(
            times_min, signed, exit_thresh, direction="down", after_idx=peak_idx
        )
        status_exit = EventStatus.resolved if exit_t is not None else EventStatus.ambiguous

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


def _gp_parametric_uncertainty(
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
    This is GP model internal consistency — NOT replicate stability.
    Only valid for condition-mean GP posteriors.
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


def _not_registered_record(site_key: str) -> EventRecord:
    """Return a not_evaluable_context_not_registered record."""
    return EventRecord(
        site_key=site_key,
        event_status=EventStatus.not_evaluable_context_not_registered,
        input_type="not_evaluable_context_not_registered",
        claim_limit=_NOT_REGISTERED_MSG,
    )


# ── Public API ─────────────────────────────────────────────────────────────

def extract_event_record(
    site_key: str,
    timepoint_labels: Sequence[str],
    fc_values: Sequence[float | None],
    *,
    study_context: StudyTemporalContext,
    amplitude_threshold: float | None = None,
    n_bootstrap: int = _N_PARAMETRIC_BOOTSTRAP,
    seed: int = _PARAMETRIC_BOOTSTRAP_SEED,
) -> EventRecord:
    """Extract event record for a single site from condition-mean FC trajectory.

    Uses GP posterior (condition-mean) with parametric bootstrap for CI.
    For true replicate-level uncertainty, use extract_event_record_from_replicates().

    study_context is REQUIRED. No insulin default.

    Parameters
    ----------
    site_key : str
    timepoint_labels : ordered sequence of timepoint labels
    fc_values : log2FC values aligned to timepoint_labels (None = missing)
    study_context : StudyTemporalContext — MUST be explicit, no default.
    amplitude_threshold : override activity threshold
    """
    thresh = amplitude_threshold if amplitude_threshold is not None else ACTIVITY_THRESHOLD_FC
    gp_ls = study_context.gp_length_scale_min_minutes

    posterior = estimate_trajectory_posterior(
        timepoint_labels,
        fc_values,
        length_scale_min=gp_ls,
    )
    from ptm_shared.probabilistic_cowave import _timepoints_to_minutes
    times_min = _timepoints_to_minutes(list(timepoint_labels))
    mean_arr = np.array(posterior["posterior_mean"])
    std_arr = np.array(posterior["posterior_std"])

    raw_fcs = [v if v is not None else float("nan") for v in fc_values]

    def _abs_if_valid(x: float) -> float | None:
        return None if x != x else abs(x)  # NaN check

    raw_first = _abs_if_valid(raw_fcs[0]) if raw_fcs else None
    raw_last = _abs_if_valid(raw_fcs[-1]) if raw_fcs else None

    ref_ev = _event_times_from_trajectory(
        times_min, mean_arr, thresh,
        raw_first_abs_fc=raw_first,
        raw_last_abs_fc=raw_last,
    )

    # Parametric CI bootstrap
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

    model_uncertainty = _gp_parametric_uncertainty(
        times_min, mean_arr, std_arr, thresh,
        n_samples=n_bootstrap, seed=seed + 1
    )

    status = ref_ev["status"]
    censoring_note: str | None = None
    if status == EventStatus.left_censored:
        censoring_note = study_context.censoring_left_note
    elif status == EventStatus.right_censored:
        censoring_note = study_context.censoring_right_note

    return EventRecord(
        site_key=site_key,
        event_status=status,
        onset_t50_min=round(ref_ev["onset_t"], 3) if ref_ev["onset_t"] is not None else None,
        onset_ci95_min=_ci_from_samples(bootstrap_onset),
        peak_t_min=round(ref_ev["peak_t"], 3) if ref_ev["peak_t"] is not None else None,
        peak_ci95_min=_ci_from_samples(bootstrap_peak),
        peak_fc=round(ref_ev["peak_fc"], 4) if ref_ev["peak_fc"] is not None else None,
        exit_t50_min=round(ref_ev["exit_t"], 3) if ref_ev["exit_t"] is not None else None,
        exit_ci95_min=_ci_from_samples(bootstrap_exit),
        replicate_bootstrap_stability=None,            # not applicable for condition-mean
        exploratory_model_uncertainty=model_uncertainty,
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
    study_context: StudyTemporalContext,
    amplitude_threshold: float | None = None,
    n_bootstrap: int = 200,
    seed: int = _PARAMETRIC_BOOTSTRAP_SEED,
) -> EventRecord:
    """Extract event record from per-replicate FC matrix.

    study_context is REQUIRED. No insulin default.

    Parameters
    ----------
    replicate_fc_matrix : shape [n_replicates, n_timepoints]. NaN for missing.
    study_context : StudyTemporalContext — MUST be explicit, no default.
    """
    gp_ls = study_context.gp_length_scale_min_minutes
    thresh = amplitude_threshold if amplitude_threshold is not None else ACTIVITY_THRESHOLD_FC

    from ptm_shared.probabilistic_cowave import _timepoints_to_minutes
    times_min = _timepoints_to_minutes(list(timepoint_labels))
    n_rep = replicate_fc_matrix.shape[0]

    finite_by_timepoint = np.any(np.isfinite(replicate_fc_matrix), axis=0)
    if not bool(np.all(finite_by_timepoint)):
        return EventRecord(
            site_key=site_key,
            event_status=EventStatus.not_evaluable_replicate_posterior,
            input_type="replicate_level_bootstrap",
            n_replicates_used=n_rep,
            amplitude_threshold_fc=thresh,
            bootstrap_evaluable_draw_fraction=0.0,
            censoring_note="replicate_matrix_contains_unobserved_timepoint",
        )
    cond_mean = [
        float(np.mean(column[np.isfinite(column)]))
        for column in replicate_fc_matrix.T
    ]
    posterior = estimate_trajectory_posterior(
        timepoint_labels, cond_mean, length_scale_min=gp_ls
    )
    mean_arr = np.array(posterior["posterior_mean"])

    ref_ev = _event_times_from_trajectory(times_min, mean_arr, thresh)

    rng = np.random.default_rng(seed)
    bootstrap_onset: list[float | None] = []
    bootstrap_peak: list[float | None] = []
    bootstrap_exit: list[float | None] = []
    status_counts: dict[str, int] = {}
    evaluable_draws = 0

    for _ in range(n_bootstrap):
        idx = rng.integers(0, n_rep, size=n_rep)
        sample_matrix = replicate_fc_matrix[idx, :]
        if not bool(np.all(np.any(np.isfinite(sample_matrix), axis=0))):
            continue
        sample_mean = [
            float(np.mean(column[np.isfinite(column)]))
            for column in sample_matrix.T
        ]
        b_posterior = estimate_trajectory_posterior(
            timepoint_labels, sample_mean, length_scale_min=gp_ls
        )
        b_mean = np.array(b_posterior["posterior_mean"])
        ev = _event_times_from_trajectory(times_min, b_mean, thresh)
        bootstrap_onset.append(ev["onset_t"])
        bootstrap_peak.append(ev["peak_t"])
        bootstrap_exit.append(ev["exit_t"])
        status_counts[ev["status"].value] = status_counts.get(ev["status"].value, 0) + 1
        evaluable_draws += 1

    stability = (
        round(status_counts.get(ref_ev["status"].value, 0) / evaluable_draws, 4)
        if evaluable_draws else None
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
        exploratory_model_uncertainty=None,  # not applicable for replicate-level
        input_type="replicate_level_bootstrap",
        n_replicates_used=n_rep,
        bootstrap_evaluable_draw_fraction=round(evaluable_draws / max(n_bootstrap, 1), 4),
        amplitude_threshold_fc=thresh,
    )


def build_event_records_for_wave_contract(
    wave_contract: Mapping[str, Any],
    *,
    study_context: StudyTemporalContext,
    amplitude_threshold: float | None = None,
) -> dict[str, EventRecord]:
    """Build EventRecord for every site in a wave_contract.

    study_context is REQUIRED. No insulin default.
    Returns {site_key: EventRecord}. Never mutates the wave_contract.
    """
    timepoints: list[str] = wave_contract.get("timepoints", [])
    records: dict[str, EventRecord] = {}

    for wave in wave_contract.get("waves", []):
        for detail in wave.get("member_details", []):
            key = detail["key"]
            tv: dict[str, float | None] = detail.get("temporal_values", {})
            fc_values = [tv.get(tp) for tp in timepoints]
            records[key] = extract_event_record(
                key, timepoints, fc_values,
                study_context=study_context,
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
