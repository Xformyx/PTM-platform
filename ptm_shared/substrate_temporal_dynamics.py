"""Canonical Substrate-level Temporal Dynamics Contract v1.

Single source of truth for site/form-level kinetic feature extraction and
hierarchical temporal pattern taxonomy.  All downstream consumers
(API scoring, co-wave composition, report nodes, UI adapter) must derive
pattern labels from this module.  Frontend ``classifyTrend()`` is a
display-only adapter—not the primary classification.

Scope
-----
Protein-normalized Track 2 PTM trajectory (ordered timepoint labels +
corresponding values) → ``SiteKineticProfile`` containing kinetic features
and a hierarchical pattern label with stability metadata.

Out of scope
-----------
Kinase attribution, causality claims, cross-condition divergence (that is
computed by callers comparing two ``SiteKineticProfile`` instances as per
P2 of the deepening plan), protein-level aggregation.

Implementation target
---------------------
Substrate-level Temporal Dynamics Deepening Plan v1 §4 (P1).
Declaration: docs/external_review_request_2026-08-22.md Appendix.
Pre-registration status: Platform engineering module — not a primary
  methodological contribution.  Pattern taxonomy and gate thresholds are
  frozen at ``CONTRACT_VERSION``; changes require a new version constant.

Interpretation limits
---------------------
Pattern labels describe observed trajectory *shape*.  They do not assert
biological mechanism, upstream kinase identity, or downstream effect.
Prohibited claim: "site X shows [pattern] because kinase Y is active."
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from ptm_shared.directed_temporal_relationship import timepoint_to_minutes


CONTRACT_VERSION = "substrate_temporal_dynamics.v1"

# ── Taxonomy labels ──────────────────────────────────────────────────────────
# Frozen with CONTRACT_VERSION.  Do not reorder; consumers may branch on these.
PATTERN_FLAT = "flat_or_low_evidence"
PATTERN_MONOTONE_RISE = "monotonic_rise"
PATTERN_MONOTONE_DECLINE = "monotonic_decline"
PATTERN_EARLY_PULSE = "early_single_pulse"
PATTERN_DELAYED_PULSE = "delayed_single_pulse"
PATTERN_TRANSIENT_SUPPRESSION = "transient_suppression"
PATTERN_DELAYED_SUPPRESSION = "delayed_suppression"
PATTERN_SUSTAINED_ACTIVATION = "sustained_activation"
PATTERN_SUSTAINED_SUPPRESSION = "sustained_suppression"
PATTERN_BIPHASIC = "biphasic_switch"
PATTERN_REBOUND = "rebound"
PATTERN_OVERSHOOT = "overshoot_recovery"
PATTERN_MULTI_PEAK = "multi_peak_candidate"
PATTERN_OSCILLATORY = "oscillatory_supported"
PATTERN_UNRESOLVED = "heterogeneous_or_unresolved"

TAXONOMY_LABELS: Tuple[str, ...] = (
    PATTERN_FLAT,
    PATTERN_MONOTONE_RISE,
    PATTERN_MONOTONE_DECLINE,
    PATTERN_EARLY_PULSE,
    PATTERN_DELAYED_PULSE,
    PATTERN_TRANSIENT_SUPPRESSION,
    PATTERN_DELAYED_SUPPRESSION,
    PATTERN_SUSTAINED_ACTIVATION,
    PATTERN_SUSTAINED_SUPPRESSION,
    PATTERN_BIPHASIC,
    PATTERN_REBOUND,
    PATTERN_OVERSHOOT,
    PATTERN_MULTI_PEAK,
    PATTERN_OSCILLATORY,
    PATTERN_UNRESOLVED,
)

# ── Frozen gate thresholds (v1) ──────────────────────────────────────────────
# Any per-experiment override must be passed explicitly via SiteKineticConfig.
# Changing defaults here invalidates all previously classified sites.
_MIN_AMPLITUDE: float = 0.5       # |FC| to pass quality gate
_MIN_OBSERVED: int = 3            # non-missing timepoints required
_ONSET_THRESHOLD: float = 0.5    # |FC| to declare onset / "above threshold"
_RECOVERY_THRESHOLD: float = 0.5 # |FC| below which signal is considered baseline
_PROMINENCE_RATIO: float = 0.50  # extremum must reach ≥ 50% of amplitude to count
_SECONDARY_SEP_MINUTES: float = 5.0  # minimum separation between distinct peaks (min)
_SUSTAINED_RATIO: float = 0.50   # active_duration / total_span to call "sustained"
_MONOTONE_RATIO: float = 0.80    # fraction of steps in dominant direction
_EARLY_PEAK_RATIO: float = 0.40  # peak in first X% of time span → "early"
_OSC_MIN_OBSERVED: int = 6       # oscillatory_supported: minimum observed timepoints
_OSC_MIN_EXTREMA: int = 4        # oscillatory_supported: ≥2 cycles = ≥4 extrema
_OSC_INTERVAL_CV_MAX: float = 0.30  # max CV of inter-peak intervals
_MISSINGNESS_WARNING_RATIO: float = 0.34  # > 1/3 missing → flag

# ── Configuration ─────────────────────────────────────────────────────────────

@dataclass
class SiteKineticConfig:
    """Dataset-specific overrides for gate thresholds.

    All defaults are copied from the module-level frozen constants.
    Pass an instance to ``compute_site_kinetic_profile`` when a study uses
    a dataset-specific noise floor that differs from the v1 defaults.
    Override source must be documented in the calling experiment script.
    """
    onset_threshold_fc: float = _ONSET_THRESHOLD
    recovery_threshold_fc: float = _RECOVERY_THRESHOLD
    min_amplitude_fc: float = _MIN_AMPLITUDE
    min_observed_timepoints: int = _MIN_OBSERVED
    secondary_peak_sep_minutes: float = _SECONDARY_SEP_MINUTES
    sustained_duration_ratio: float = _SUSTAINED_RATIO
    monotone_ratio: float = _MONOTONE_RATIO
    early_peak_ratio: float = _EARLY_PEAK_RATIO
    run_loto: bool = True
    run_threshold_sensitivity: bool = True
    threshold_sensitivity_multipliers: Tuple[float, ...] = (0.5, 2.0)

    @classmethod
    def default(cls) -> "SiteKineticConfig":
        return cls()


# ── Output contract ───────────────────────────────────────────────────────────

@dataclass
class SiteKineticProfile:
    """Per-site kinetic features and taxonomy label.

    This is the output contract.  Consumers must not add biological
    causality beyond what the field comments permit.
    """
    # ── Signal / quality ──────────────────────────────────────────────────
    amplitude: Optional[float]         # max |value| over observed timepoints
    dynamic_range: Optional[float]     # max(obs) − min(obs)
    observed_timepoints_count: int
    missing_timepoints_count: int
    qvalue_coverage: Optional[float]   # fraction of observed with q_value < 0.05

    # ── Onset / peak ──────────────────────────────────────────────────────
    onset_minutes: Optional[float]     # earliest obs timepoint with |v| > threshold
    peak_minutes: Optional[float]      # timepoint of max |v|
    peak_sign: Optional[int]           # +1 or -1
    peak_prominence: Optional[float]   # peak |v| minus local baseline average
    secondary_peak_minutes: Optional[float]
    secondary_peak_sign: Optional[int]

    # ── Duration ──────────────────────────────────────────────────────────
    active_duration_minutes: Optional[float]      # onset to last above threshold
    time_above_threshold_minutes: Optional[float] # sum of intervals above threshold
    auc_signed: Optional[float]        # trapezoid ∫ FC·dt (signed)
    auc_absolute: Optional[float]      # trapezoid ∫ |FC|·dt

    # ── Rise / recovery ───────────────────────────────────────────────────
    rise_slope: Optional[float]        # |FC| per minute from onset to peak
    decay_slope: Optional[float]       # |FC| per minute from peak to recovery/end
    recovery_minutes: Optional[float]  # minutes from peak to first return to baseline
    return_to_baseline: Optional[bool]

    # ── Shape ──────────────────────────────────────────────────────────────
    sign_switch_count: int             # sign changes among above-threshold values
    local_extrema_count: int           # local maxima + minima above prominence
    peak_separation_minutes: Optional[float]
    monotonicity_score: Optional[float]  # fraction of consecutive steps in dominant dir

    # ── Pattern taxonomy ──────────────────────────────────────────────────
    primary_pattern: str               # one of TAXONOMY_LABELS
    pattern_modifiers: List[str]       # auxiliary flags
    quality_gate_passed: bool

    # ── Uncertainty ────────────────────────────────────────────────────────
    loto_pattern_stability: Optional[float]  # fraction of LOTO rounds matching primary
    threshold_sensitivity_flag: bool   # True if pattern changes when threshold varies
    missingness_warning: bool

    # ── P0 input audit ────────────────────────────────────────────────────
    # 구현 대상: Substrate-level Temporal Dynamics Deepening Plan v1 §3 (P0)
    # 이 필드들은 X축 데이터 품질 경고이며 패턴 판정에 영향을 주지 않는다.
    time_ordering_warning: bool   # True if parsed minutes are not non-decreasing
    duplicate_timepoint_warning: bool  # True if two labels parse to the same minute

    # ── Provenance ────────────────────────────────────────────────────────
    onset_threshold_fc_used: float
    observed_minutes: List[float]
    contract_version: str = CONTRACT_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _parse_trajectory(
    labels: Sequence[Any],
    values: Sequence[Optional[float]],
) -> Tuple[List[float], List[float], List[float], int]:
    """Return (all_minutes, obs_minutes, obs_values, missing_count).

    Missing values are represented as None or NaN.  Timepoints whose minute
    parse returns infinity (unparseable label) are treated as missing.
    """
    all_minutes: List[float] = []
    obs_minutes: List[float] = []
    obs_values: List[float] = []
    missing = 0
    for label, v in zip(labels, values):
        t = timepoint_to_minutes(label)
        all_minutes.append(t)
        if v is None or (isinstance(v, float) and not math.isfinite(v)) or not math.isfinite(t):
            missing += 1
        else:
            obs_minutes.append(t)
            obs_values.append(float(v))
    return all_minutes, obs_minutes, obs_values, missing


def _trapezoid(minutes: List[float], values: List[float], absolute: bool = False) -> Optional[float]:
    if len(minutes) < 2:
        return None
    total = 0.0
    for i in range(1, len(minutes)):
        dt = minutes[i] - minutes[i - 1]
        v_left = abs(values[i - 1]) if absolute else values[i - 1]
        v_right = abs(values[i]) if absolute else values[i]
        total += 0.5 * (v_left + v_right) * dt
    return total


def _monotonicity_score(values: List[float]) -> Optional[float]:
    """Fraction of consecutive steps in the dominant direction (rise or fall)."""
    if len(values) < 2:
        return None
    diffs = [values[i + 1] - values[i] for i in range(len(values) - 1)]
    n_pos = sum(1 for d in diffs if d > 0)
    n_neg = sum(1 for d in diffs if d < 0)
    n_total = len(diffs)
    if n_total == 0:
        return None
    dominant = max(n_pos, n_neg)
    return dominant / n_total


def _find_primary_peak(obs_values: List[float]) -> Optional[int]:
    """Index of maximum |value| in the observed trajectory."""
    if not obs_values:
        return None
    return int(np.argmax(np.abs(obs_values)))


def _find_local_extrema(
    obs_values: List[float],
    amplitude: float,
    prominence_ratio: float,
) -> List[Tuple[int, str]]:
    """Return (index, 'max'|'min') pairs for interior local extrema above prominence.

    Endpoints are intentionally excluded.  A trajectory peak at index 0 or
    at the last index indicates "still rising/declining" rather than a
    resolved local extremum, and is handled separately in the monotone path.
    """
    if len(obs_values) < 3:
        return []
    threshold = amplitude * prominence_ratio
    extrema: List[Tuple[int, str]] = []
    for i in range(1, len(obs_values) - 1):
        left, mid, right = obs_values[i - 1], obs_values[i], obs_values[i + 1]
        if mid > left and mid > right and mid >= threshold:
            extrema.append((i, "max"))
        elif mid < left and mid < right and (-mid) >= threshold:
            extrema.append((i, "min"))
    return extrema


def _sign_switches(obs_values: List[float], threshold: float) -> int:
    """Count sign changes among values with |v| > threshold."""
    significant = [v for v in obs_values if abs(v) > threshold]
    if len(significant) < 2:
        return 0
    return sum(
        1 for i in range(1, len(significant))
        if math.copysign(1, significant[i]) != math.copysign(1, significant[i - 1])
    )


def _first_above(obs_minutes: List[float], obs_values: List[float], threshold: float) -> Optional[float]:
    """First observed minute where |value| > threshold."""
    for t, v in zip(obs_minutes, obs_values):
        if abs(v) > threshold:
            return t
    return None


def _last_above(obs_minutes: List[float], obs_values: List[float], threshold: float) -> Optional[float]:
    last = None
    for t, v in zip(obs_minutes, obs_values):
        if abs(v) > threshold:
            last = t
    return last


def _time_above_threshold(
    obs_minutes: List[float], obs_values: List[float], threshold: float
) -> Optional[float]:
    """Sum of interval lengths where both endpoints are above threshold."""
    if len(obs_minutes) < 2:
        return None
    total = 0.0
    for i in range(1, len(obs_minutes)):
        if abs(obs_values[i - 1]) > threshold and abs(obs_values[i]) > threshold:
            total += obs_minutes[i] - obs_minutes[i - 1]
    return total if total > 0.0 else 0.0


def _extract_features(
    obs_minutes: List[float],
    obs_values: List[float],
    config: SiteKineticConfig,
) -> Dict[str, Any]:
    """Compute raw kinetic features. Returns a flat dict consumed by _classify_taxonomy."""
    if not obs_values:
        return {"observed_count": 0, "amplitude": None}

    amplitude = float(np.max(np.abs(obs_values)))
    dynamic_range = float(np.max(obs_values) - np.min(obs_values))
    total_span = obs_minutes[-1] - obs_minutes[0] if len(obs_minutes) >= 2 else 0.0

    pk_idx = _find_primary_peak(obs_values)
    peak_minutes = obs_minutes[pk_idx] if pk_idx is not None else None
    peak_sign = int(math.copysign(1, obs_values[pk_idx])) if pk_idx is not None else None

    # Prominence: peak |v| minus the mean |v| at adjacent observed points
    if pk_idx is not None:
        neighbors = []
        if pk_idx > 0:
            neighbors.append(abs(obs_values[pk_idx - 1]))
        if pk_idx < len(obs_values) - 1:
            neighbors.append(abs(obs_values[pk_idx + 1]))
        baseline_avg = float(np.mean(neighbors)) if neighbors else 0.0
        peak_prominence: Optional[float] = abs(obs_values[pk_idx]) - baseline_avg
    else:
        peak_prominence = None

    onset = _first_above(obs_minutes, obs_values, config.onset_threshold_fc)
    last_active = _last_above(obs_minutes, obs_values, config.onset_threshold_fc)
    active_duration = (last_active - onset) if (onset is not None and last_active is not None) else None
    time_above = _time_above_threshold(obs_minutes, obs_values, config.onset_threshold_fc)
    auc_signed = _trapezoid(obs_minutes, obs_values, absolute=False)
    auc_absolute = _trapezoid(obs_minutes, obs_values, absolute=True)

    # Rise/decay slopes
    rise_slope: Optional[float] = None
    if onset is not None and peak_minutes is not None and peak_minutes > onset and pk_idx is not None:
        onset_idx = next((i for i, t in enumerate(obs_minutes) if t >= onset), None)
        if onset_idx is not None and onset_idx != pk_idx:
            dt = peak_minutes - obs_minutes[onset_idx]
            dv = abs(obs_values[pk_idx]) - abs(obs_values[onset_idx])
            rise_slope = dv / dt if dt > 0 else None

    decay_slope: Optional[float] = None
    recovery_minutes: Optional[float] = None
    return_to_baseline: Optional[bool] = None
    if pk_idx is not None and pk_idx < len(obs_minutes) - 1:
        post_peak_m = obs_minutes[pk_idx + 1:]
        post_peak_v = obs_values[pk_idx + 1:]
        if post_peak_m:
            end_m = post_peak_m[-1]
            end_v = abs(post_peak_v[-1])
            dt = end_m - obs_minutes[pk_idx]
            dv = abs(obs_values[pk_idx]) - end_v
            decay_slope = dv / dt if dt > 0 else None
            # Recovery: first timepoint after peak where |v| <= recovery threshold
            for t, v in zip(post_peak_m, post_peak_v):
                if abs(v) <= config.recovery_threshold_fc:
                    recovery_minutes = t - obs_minutes[pk_idx]
                    return_to_baseline = True
                    break
            if return_to_baseline is None:
                return_to_baseline = False

    sign_sw = _sign_switches(obs_values, config.onset_threshold_fc)
    monotone = _monotonicity_score(obs_values)
    local_extrema = _find_local_extrema(obs_values, amplitude, _PROMINENCE_RATIO)

    # Secondary peak: first extremum with sufficient separation from primary
    sec_idx: Optional[int] = None
    sec_sign: Optional[int] = None
    sep_minutes: Optional[float] = None
    if pk_idx is not None:
        for ei, etype in local_extrema:
            if ei == pk_idx:
                continue
            if abs(obs_minutes[ei] - obs_minutes[pk_idx]) >= config.secondary_peak_sep_minutes:
                sec_idx = ei
                sec_sign = int(math.copysign(1, obs_values[ei]))
                sep_minutes = abs(obs_minutes[ei] - obs_minutes[pk_idx])
                break

    # Oscillatory interval CV (among all local extrema of same sign)
    osc_interval_cv: Optional[float] = None
    same_sign_extrema = [
        obs_minutes[ei] for ei, etype in local_extrema
        if etype == ("max" if (peak_sign or 1) > 0 else "min")
    ]
    if len(same_sign_extrema) >= 2:
        intervals = [same_sign_extrema[i + 1] - same_sign_extrema[i] for i in range(len(same_sign_extrema) - 1)]
        mean_interval = float(np.mean(intervals))
        if mean_interval > 0:
            osc_interval_cv = float(np.std(intervals) / mean_interval)

    sustained_ratio = (active_duration / total_span) if (active_duration is not None and total_span > 0) else 0.0

    return {
        "observed_count": len(obs_values),
        "amplitude": amplitude,
        "dynamic_range": dynamic_range,
        "total_span": total_span,
        "pk_idx": pk_idx,
        "peak_minutes": peak_minutes,
        "peak_sign": peak_sign,
        "peak_prominence": peak_prominence,
        "sec_idx": sec_idx,
        "sec_sign": sec_sign,
        "sep_minutes": sep_minutes,
        "onset": onset,
        "last_active": last_active,
        "active_duration": active_duration,
        "time_above": time_above,
        "auc_signed": auc_signed,
        "auc_absolute": auc_absolute,
        "rise_slope": rise_slope,
        "decay_slope": decay_slope,
        "recovery_minutes": recovery_minutes,
        "return_to_baseline": return_to_baseline,
        "sign_sw": sign_sw,
        "monotone": monotone,
        "local_extrema": local_extrema,
        "sustained_ratio": sustained_ratio,
        "osc_interval_cv": osc_interval_cv,
    }


def _classify_taxonomy(
    obs_minutes: List[float],
    obs_values: List[float],
    f: Dict[str, Any],
    config: SiteKineticConfig,
) -> Tuple[str, List[str]]:
    """Hierarchical taxonomy from pre-computed features.

    Called from both the main path and LOTO loops; must be a pure function of
    (obs_minutes, obs_values, f, config).  No I/O.

    Precedence (top wins):
    0. Quality gate → flat
    1. Multi-peak / oscillatory (≥2 interior extrema + prominent secondary)
    2. Sign-switch + prominent opposite phase → biphasic / unresolved
    3. Monotone RISE  (peak at last observed point, score ≥ threshold)
    4. Monotone DECLINE (peak at first point, no return to baseline, score ≥ threshold)
    5. Sustained (active_duration / total_span ≥ threshold)
    6. Single pulse / suppression (default, discriminated by early vs delayed peak)
    """
    amp = f.get("amplitude")
    n_obs = f.get("observed_count", 0)

    # Level 0 — quality gate
    if amp is None or amp < config.min_amplitude_fc or n_obs < config.min_observed_timepoints:
        return PATTERN_FLAT, []

    modifiers: List[str] = []
    return_to_baseline = f.get("return_to_baseline")
    if return_to_baseline:
        modifiers.append("return_to_baseline")

    pk_idx = f["pk_idx"]
    peak_sign = f["peak_sign"]
    sign_sw = f["sign_sw"]
    monotone = f["monotone"]
    local_extrema: List[Tuple[int, str]] = f["local_extrema"]
    n_extrema = len(local_extrema)
    sec_idx = f["sec_idx"]
    sustained_ratio = f["sustained_ratio"]
    total_span = f["total_span"]
    peak_min = f["peak_minutes"]
    osc_cv = f["osc_interval_cv"]
    obs_span = len(obs_values)

    # Level 1 — multi-peak / oscillatory
    if n_extrema >= 2 and sec_idx is not None:
        is_oscillatory = (
            n_obs >= _OSC_MIN_OBSERVED
            and n_extrema >= _OSC_MIN_EXTREMA
            and osc_cv is not None
            and osc_cv <= _OSC_INTERVAL_CV_MAX
        )
        if is_oscillatory:
            return PATTERN_OSCILLATORY, modifiers
        return PATTERN_MULTI_PEAK, modifiers

    # Level 2 — sign-switch / biphasic
    if sign_sw >= 1 and peak_sign is not None:
        opp_sign = -peak_sign
        opp_candidates = [
            (abs(v), i) for i, v in enumerate(obs_values)
            if math.copysign(1.0, v) == float(opp_sign)
            and abs(v) >= amp * _PROMINENCE_RATIO
        ]
        if opp_candidates:
            modifiers.append("rebound_present")
            return PATTERN_BIPHASIC, modifiers
        return PATTERN_UNRESOLVED, ["sign_switch_without_prominent_secondary"]

    # Level 3 — monotone RISE: peak is at the last observed index (still climbing)
    if (monotone is not None and monotone >= config.monotone_ratio
            and pk_idx is not None and pk_idx == obs_span - 1):
        return PATTERN_MONOTONE_RISE, modifiers

    # Level 4 — monotone DECLINE: peak at first index AND signal does not return to baseline
    if (monotone is not None and monotone >= config.monotone_ratio
            and pk_idx is not None and pk_idx == 0
            and not return_to_baseline):
        return PATTERN_MONOTONE_DECLINE, modifiers

    # Level 5 — sustained
    if sustained_ratio >= config.sustained_duration_ratio:
        if peak_sign is not None and peak_sign > 0:
            return PATTERN_SUSTAINED_ACTIVATION, modifiers
        return PATTERN_SUSTAINED_SUPPRESSION, modifiers

    # Level 6 — single pulse / suppression
    early_cutoff = (
        obs_minutes[0] + total_span * config.early_peak_ratio
        if (obs_minutes and total_span > 0) else None
    )
    if peak_sign is not None and peak_sign > 0:
        if early_cutoff is not None and peak_min is not None and peak_min <= early_cutoff:
            return PATTERN_EARLY_PULSE, modifiers
        return PATTERN_DELAYED_PULSE, modifiers
    else:
        if early_cutoff is not None and peak_min is not None and peak_min <= early_cutoff:
            return PATTERN_TRANSIENT_SUPPRESSION, modifiers
        return PATTERN_DELAYED_SUPPRESSION, modifiers


def _run_loto(
    labels: Sequence[Any],
    values: Sequence[Optional[float]],
    q_values: Optional[Sequence[Optional[float]]],
    primary_pattern: str,
    config: SiteKineticConfig,
) -> Optional[float]:
    """Leave-one-timepoint-out stability: fraction of rounds matching primary_pattern."""
    n = len(labels)
    if n < config.min_observed_timepoints + 1:
        return None
    matches = 0
    for skip_i in range(n):
        loto_labels = [labels[i] for i in range(n) if i != skip_i]
        loto_values = [values[i] for i in range(n) if i != skip_i]
        loto_q = (
            [q_values[i] for i in range(n) if i != skip_i]
            if q_values is not None else None
        )
        _, obs_m, obs_v, _ = _parse_trajectory(loto_labels, loto_values)
        f = _extract_features(obs_m, obs_v, config)
        pattern, _ = _classify_taxonomy(obs_m, obs_v, f, config)
        if pattern == primary_pattern:
            matches += 1
    return matches / n


def _check_threshold_sensitivity(
    obs_minutes: List[float],
    obs_values: List[float],
    primary_pattern: str,
    config: SiteKineticConfig,
) -> bool:
    """True if primary_pattern changes at any threshold multiplier in config."""
    for mult in config.threshold_sensitivity_multipliers:
        alt_config = SiteKineticConfig(
            onset_threshold_fc=config.onset_threshold_fc * mult,
            recovery_threshold_fc=config.recovery_threshold_fc * mult,
            min_amplitude_fc=config.min_amplitude_fc,
            min_observed_timepoints=config.min_observed_timepoints,
            secondary_peak_sep_minutes=config.secondary_peak_sep_minutes,
            sustained_duration_ratio=config.sustained_duration_ratio,
            monotone_ratio=config.monotone_ratio,
            early_peak_ratio=config.early_peak_ratio,
            run_loto=False,
            run_threshold_sensitivity=False,
        )
        f = _extract_features(obs_minutes, obs_values, alt_config)
        pattern, _ = _classify_taxonomy(obs_minutes, obs_values, f, alt_config)
        if pattern != primary_pattern:
            return True
    return False


# ── Public API ────────────────────────────────────────────────────────────────

def compute_site_kinetic_profile(
    timepoint_labels: Sequence[Any],
    values: Sequence[Optional[float]],
    *,
    q_values: Optional[Sequence[Optional[float]]] = None,
    config: Optional[SiteKineticConfig] = None,
) -> SiteKineticProfile:
    """Compute kinetic features and taxonomy label for one PTM site/form.

    Parameters
    ----------
    timepoint_labels : sequence of str
        Ordered timepoint labels (e.g. ``["5min", "15min", "30min", "60min"]``).
        Parsing follows the canonical ``timepoint_to_minutes`` parser.
    values : sequence of float or None
        Protein-normalized log2 fold-change (Track 2) values.  ``None`` indicates
        a missing measurement; NaN is treated the same way.
    q_values : optional sequence of float or None
        Per-timepoint significance values.  Used only to compute
        ``qvalue_coverage``; does not affect taxonomy.
    config : SiteKineticConfig or None
        Dataset-specific threshold overrides.  Defaults to ``SiteKineticConfig.default()``.

    Returns
    -------
    SiteKineticProfile
        See dataclass definition for field semantics.
    """
    if config is None:
        config = SiteKineticConfig.default()

    all_minutes_raw, obs_minutes, obs_values, missing_count = _parse_trajectory(timepoint_labels, values)
    n_all = len(timepoint_labels)
    n_obs = len(obs_minutes)
    missingness_warning = (missing_count / n_all) > _MISSINGNESS_WARNING_RATIO if n_all > 0 else False

    # ── P0 X-axis audit ──────────────────────────────────────────────────────
    # Only finite (parseable) minutes are checked; unparseable labels already
    # become missing_count and are excluded from pattern classification.
    finite_minutes = [m for m in all_minutes_raw if math.isfinite(m)]
    time_ordering_warning = any(
        finite_minutes[i] > finite_minutes[i + 1]
        for i in range(len(finite_minutes) - 1)
    )
    _minute_counts: Dict[float, int] = {}
    for m in finite_minutes:
        _minute_counts[m] = _minute_counts.get(m, 0) + 1
    duplicate_timepoint_warning = any(c > 1 for c in _minute_counts.values())

    # Q-value coverage
    qvalue_coverage: Optional[float] = None
    if q_values is not None and n_obs > 0:
        paired_q = [
            qv for lbl, v, qv in zip(timepoint_labels, values, q_values)
            if v is not None and (not isinstance(v, float) or math.isfinite(v))
            and qv is not None
        ]
        if paired_q:
            qvalue_coverage = sum(1 for q in paired_q if q < 0.05) / len(paired_q)

    f = _extract_features(obs_minutes, obs_values, config)
    primary_pattern, modifiers = _classify_taxonomy(obs_minutes, obs_values, f, config)
    quality_gate_passed = primary_pattern != PATTERN_FLAT

    # LOTO stability
    loto_stability: Optional[float] = None
    if config.run_loto and quality_gate_passed:
        loto_stability = _run_loto(timepoint_labels, values, q_values, primary_pattern, config)

    # Threshold sensitivity
    threshold_sensitivity_flag = False
    if config.run_threshold_sensitivity and quality_gate_passed and obs_minutes:
        threshold_sensitivity_flag = _check_threshold_sensitivity(
            obs_minutes, obs_values, primary_pattern, config
        )

    return SiteKineticProfile(
        amplitude=f.get("amplitude"),
        dynamic_range=f.get("dynamic_range"),
        observed_timepoints_count=n_obs,
        missing_timepoints_count=missing_count,
        qvalue_coverage=qvalue_coverage,
        onset_minutes=f.get("onset"),
        peak_minutes=f.get("peak_minutes"),
        peak_sign=f.get("peak_sign"),
        peak_prominence=f.get("peak_prominence"),
        secondary_peak_minutes=(
            obs_minutes[f["sec_idx"]] if f.get("sec_idx") is not None else None
        ),
        secondary_peak_sign=f.get("sec_sign"),
        active_duration_minutes=f.get("active_duration"),
        time_above_threshold_minutes=f.get("time_above"),
        auc_signed=f.get("auc_signed"),
        auc_absolute=f.get("auc_absolute"),
        rise_slope=f.get("rise_slope"),
        decay_slope=f.get("decay_slope"),
        recovery_minutes=f.get("recovery_minutes"),
        return_to_baseline=f.get("return_to_baseline"),
        sign_switch_count=f.get("sign_sw", 0),
        local_extrema_count=len(f.get("local_extrema", [])),
        peak_separation_minutes=f.get("sep_minutes"),
        monotonicity_score=f.get("monotone"),
        primary_pattern=primary_pattern,
        pattern_modifiers=modifiers,
        quality_gate_passed=quality_gate_passed,
        loto_pattern_stability=loto_stability,
        threshold_sensitivity_flag=threshold_sensitivity_flag,
        missingness_warning=missingness_warning,
        time_ordering_warning=time_ordering_warning,
        duplicate_timepoint_warning=duplicate_timepoint_warning,
        onset_threshold_fc_used=config.onset_threshold_fc,
        observed_minutes=list(obs_minutes),
        contract_version=CONTRACT_VERSION,
    )


def describe_member_dynamics(
    timepoint_labels: Sequence[Any],
    values: Sequence[Optional[float]],
    *,
    q_values: Optional[Sequence[Optional[float]]] = None,
    config: Optional[SiteKineticConfig] = None,
) -> Dict[str, Any]:
    """Compact site-dynamics summary for embedding in wave member records.

    Returns a flat dict with the most wave-relevant fields; avoids copying
    the full SiteKineticProfile into high-cardinality wave output.
    """
    profile = compute_site_kinetic_profile(
        timepoint_labels, values, q_values=q_values, config=config
    )
    return {
        "primary_pattern": profile.primary_pattern,
        "pattern_modifiers": profile.pattern_modifiers,
        "quality_gate_passed": profile.quality_gate_passed,
        "amplitude": profile.amplitude,
        "onset_minutes": profile.onset_minutes,
        "peak_minutes": profile.peak_minutes,
        "peak_sign": profile.peak_sign,
        "active_duration_minutes": profile.active_duration_minutes,
        "auc_signed": profile.auc_signed,
        "return_to_baseline": profile.return_to_baseline,
        "sign_switch_count": profile.sign_switch_count,
        "loto_pattern_stability": profile.loto_pattern_stability,
        "threshold_sensitivity_flag": profile.threshold_sensitivity_flag,
        "missingness_warning": profile.missingness_warning,
        "site_kinetic_contract": CONTRACT_VERSION,
    }


def compute_kinase_substrate_phenotypes(
    site_profiles: Mapping[str, "SiteKineticProfile"],
    kinase_substrates: Mapping[str, Sequence[str]],
) -> Dict[str, Dict[str, Any]]:
    """Compute substrate temporal pattern distribution per kinase (P3).

    For each kinase, collects the primary_pattern labels of its assigned
    substrates and returns a compact phenotype record.  Sites without a
    corresponding kinetic profile are skipped.

    Implementation target: Substrate-level Temporal Dynamics Deepening Plan v1 §6 (P3).
    Pre-registration status: Platform engineering module.
    Interpretation limits: pattern distribution is a structural description
    of the kinase's substrate population shape; it does not assert biological
    mechanism or confirm kinase attribution accuracy.

    Parameters
    ----------
    site_profiles : mapping of site_key → SiteKineticProfile
    kinase_substrates : mapping of kinase_name → [site_key, ...]

    Returns
    -------
    dict keyed by kinase_name with sub-keys:
      ``n_substrates``      — assigned sites with a kinetic profile
      ``n_quality_passed``  — sites passing quality gate
      ``pattern_counts``    — {label: count} for quality-passed sites
      ``dominant_pattern``  — most common label (None if none pass gate)
      ``pattern_diversity`` — number of distinct labels
      ``flat_fraction``     — fraction of substrates failing quality gate
    """
    from collections import Counter

    results: Dict[str, Dict[str, Any]] = {}

    for kinase, site_keys in kinase_substrates.items():
        matched = [
            site_profiles[key] for key in site_keys if key in site_profiles
        ]
        n_matched = len(matched)
        if n_matched == 0:
            results[kinase] = {
                "n_substrates": 0,
                "n_quality_passed": 0,
                "pattern_counts": {},
                "dominant_pattern": None,
                "pattern_diversity": 0,
                "flat_fraction": None,
            }
            continue

        passed = [p for p in matched if p.quality_gate_passed]
        n_passed = len(passed)
        counts: Counter[str] = Counter(p.primary_pattern for p in passed)
        dominant = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] if counts else None

        results[kinase] = {
            "n_substrates": n_matched,
            "n_quality_passed": n_passed,
            "pattern_counts": dict(counts),
            "dominant_pattern": dominant,
            "pattern_diversity": len(counts),
            "flat_fraction": (n_matched - n_passed) / n_matched,
        }

    return results


def summarise_member_pattern_distribution(
    member_dynamics: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Aggregate member-level pattern labels into a wave-level composition.

    Parameters
    ----------
    member_dynamics : sequence of dicts as returned by ``describe_member_dynamics``

    Returns
    -------
    dict with keys:
      ``pattern_counts``   — ``{label: count}`` for all observed labels
      ``dominant_pattern`` — most common label (ties broken alphabetically)
      ``pattern_diversity``— number of distinct labels observed
      ``loto_mean``        — mean LOTO stability (None if none available)
      ``threshold_sensitive_fraction`` — fraction with threshold_sensitivity_flag=True
      ``missingness_warning_fraction`` — fraction with missingness_warning=True
    """
    from collections import Counter

    if not member_dynamics:
        return {
            "pattern_counts": {},
            "dominant_pattern": None,
            "pattern_diversity": 0,
            "loto_mean": None,
            "threshold_sensitive_fraction": None,
            "missingness_warning_fraction": None,
        }

    counts: Counter[str] = Counter()
    loto_vals: List[float] = []
    thresh_flags: List[bool] = []
    miss_flags: List[bool] = []

    for d in member_dynamics:
        counts[d.get("primary_pattern", PATTERN_UNRESOLVED)] += 1
        loto = d.get("loto_pattern_stability")
        if loto is not None:
            loto_vals.append(float(loto))
        tf = d.get("threshold_sensitivity_flag")
        if tf is not None:
            thresh_flags.append(bool(tf))
        mw = d.get("missingness_warning")
        if mw is not None:
            miss_flags.append(bool(mw))

    dominant = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    return {
        "pattern_counts": dict(counts),
        "dominant_pattern": dominant,
        "pattern_diversity": len(counts),
        "loto_mean": float(np.mean(loto_vals)) if loto_vals else None,
        "threshold_sensitive_fraction": (
            sum(thresh_flags) / len(thresh_flags) if thresh_flags else None
        ),
        "missingness_warning_fraction": (
            sum(miss_flags) / len(miss_flags) if miss_flags else None
        ),
    }
