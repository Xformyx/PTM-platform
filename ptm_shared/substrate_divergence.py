"""Condition-aware Substrate Divergence Contract v1 (P2).

Compares ``SiteKineticProfile`` instances for the same PTM site observed under
different experimental conditions.  Quantifies divergence in onset, peak,
amplitude, duration, AUC, and pattern taxonomy.

Scope
-----
Two ``SiteKineticProfile`` objects from the same site in condition A vs
condition B → ``SiteConditionDivergence`` (feature-vector differences +
composite divergence score).

Multiple sites → ``summarise_population_divergence`` (population-level summary
including pattern-transition matrix and aggregate statistics).

Out of scope
-----------
Kinase attribution, causal claims, cross-protein comparisons, statistical
significance (callers must apply their own correction).  The divergence score
is a structural feature, not a significance test.

Implementation target
---------------------
Substrate-level Temporal Dynamics Deepening Plan v1 §5 (P2).
Pre-registration status: Platform engineering module — not a primary
  methodological contribution.  Score formula and feature weights frozen
  at CONTRACT_VERSION.

Interpretation limits
---------------------
``divergence_score`` describes feature distance, not biological mechanism.
A high score means the site behaves differently in the two conditions; it
does not identify which kinase caused the difference.
Prohibited claim: "site X diverged because kinase Y was differentially active."
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ptm_shared.substrate_temporal_dynamics import (
    CONTRACT_VERSION as P1_CONTRACT_VERSION,
    PATTERN_FLAT,
    SiteKineticConfig,
    SiteKineticProfile,
    compute_site_kinetic_profile,
)


CONTRACT_VERSION = "substrate_divergence.v1"

# ── Frozen divergence score weights (v1) ─────────────────────────────────────
# Changing these weights invalidates previously computed divergence_score values.
_WEIGHT_SIGN_REVERSAL: float = 3.0       # peak sign differs → most significant
_WEIGHT_PATTERN_CHANGE: float = 1.5     # pattern label changes (excluding flat/flat)
_WEIGHT_AMPLITUDE_MAX: float = 2.0      # max contribution from amplitude log2 ratio
_AMPLITUDE_LOG2_CAP: float = 2.0        # cap |log2 ratio| at 2 FC before scaling
_WEIGHT_PEAK_SHIFT_MAX: float = 2.0     # max contribution from relative peak shift


# ── Output contracts ──────────────────────────────────────────────────────────

@dataclass
class SiteConditionDivergence:
    """Feature-vector divergence between conditions A and B for one PTM site.

    All "delta" fields are computed as (B − A).  None indicates one or both
    profiles lacked the feature (e.g., no onset because below threshold).
    """
    # ── Timing ────────────────────────────────────────────────────────────
    onset_delta_minutes: Optional[float]       # B.onset − A.onset
    peak_shift_minutes: Optional[float]        # B.peak  − A.peak
    recovery_delta_minutes: Optional[float]    # B.recovery − A.recovery
    active_duration_delta_minutes: Optional[float]  # B − A

    # ── Amplitude ─────────────────────────────────────────────────────────
    amplitude_delta: Optional[float]           # B.amplitude − A.amplitude
    amplitude_ratio: Optional[float]           # B.amplitude / A.amplitude
    amplitude_log2_ratio: Optional[float]      # log2(B/A); None if A ≤ 0

    # ── AUC ───────────────────────────────────────────────────────────────
    auc_signed_delta: Optional[float]          # B.auc_signed − A.auc_signed
    auc_magnitude_ratio: Optional[float]       # B.auc_absolute / A.auc_absolute

    # ── Pattern ───────────────────────────────────────────────────────────
    pattern_a: str
    pattern_b: str
    pattern_conserved: bool                    # same primary_pattern in A and B
    sign_reversal: bool                        # peak_sign differs between A and B

    # ── Composite divergence ──────────────────────────────────────────────
    divergence_score: float
    """Composite structural distance (0 = identical features, higher = more divergent).

    Components (frozen weights):
      sign_reversal         × 3.0   (if peak signs differ)
      pattern_change        × 1.5   (if pattern label changes, excluding flat→flat)
      |amplitude_log2_ratio|× 1.0 per log2FC, capped at 2 log2FC  (max 2.0)
      |peak_shift| / span   × 2.0   (relative timing shift, max 2.0)
    Total unbounded but typically 0–8.5 for real data.
    """

    # ── Quality ───────────────────────────────────────────────────────────
    both_quality_gate_passed: bool
    only_a_passes_gate: bool
    only_b_passes_gate: bool
    neither_passes_gate: bool

    # ── Reference span used for peak_shift normalization ──────────────────
    reference_span_minutes: Optional[float]

    # ── Provenance ────────────────────────────────────────────────────────
    p1_contract_version: str = P1_CONTRACT_VERSION
    contract_version: str = CONTRACT_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PopulationDivergenceSummary:
    """Population-level summary of condition divergence across multiple sites."""
    n_sites: int
    n_both_pass: int
    n_only_a_pass: int
    n_only_b_pass: int
    n_neither_pass: int

    n_conserved: int              # same pattern in both (quality-passed sites)
    n_diverged: int               # different pattern (quality-passed sites)
    n_sign_reversal: int

    conservation_rate: Optional[float]  # n_conserved / n_both_pass
    sign_reversal_rate: Optional[float] # n_sign_reversal / n_both_pass

    mean_divergence_score: Optional[float]
    mean_amplitude_log2_ratio: Optional[float]
    mean_peak_shift_minutes: Optional[float]

    pattern_transition_counts: Dict[str, int]  # "A→B": count
    top_transitions: List[Tuple[str, str, int]]  # [(from, to, count), ...]

    contract_version: str = CONTRACT_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_div(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    if b == 0.0:
        return None
    return a / b


def _safe_log2_ratio(b: Optional[float], a: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    if a <= 0.0 or b <= 0.0:
        return None
    return math.log2(b / a)


def _compute_divergence_score(
    sign_reversal: bool,
    pattern_conserved: bool,
    pattern_a: str,
    pattern_b: str,
    amplitude_log2_ratio: Optional[float],
    peak_shift_minutes: Optional[float],
    reference_span: Optional[float],
) -> float:
    """Compute the composite divergence score from feature differences."""
    score = 0.0

    if sign_reversal:
        score += _WEIGHT_SIGN_REVERSAL

    if not pattern_conserved and not (pattern_a == PATTERN_FLAT and pattern_b == PATTERN_FLAT):
        score += _WEIGHT_PATTERN_CHANGE

    if amplitude_log2_ratio is not None:
        capped = min(abs(amplitude_log2_ratio), _AMPLITUDE_LOG2_CAP)
        score += (capped / _AMPLITUDE_LOG2_CAP) * _WEIGHT_AMPLITUDE_MAX

    if peak_shift_minutes is not None and reference_span and reference_span > 0:
        relative_shift = min(abs(peak_shift_minutes) / reference_span, 1.0)
        score += relative_shift * _WEIGHT_PEAK_SHIFT_MAX

    return round(score, 6)


# ── Public API ────────────────────────────────────────────────────────────────

def compare_site_profiles(
    profile_a: SiteKineticProfile,
    profile_b: SiteKineticProfile,
    *,
    reference_span_minutes: Optional[float] = None,
) -> SiteConditionDivergence:
    """Compute condition divergence between two pre-computed SiteKineticProfile instances.

    Parameters
    ----------
    profile_a, profile_b : SiteKineticProfile
        Profiles from conditions A and B for the same site.  Must be computed
        from the same timepoint labels if peak_shift normalization is desired.
    reference_span_minutes : float or None
        The full measurement time span used to normalize timing differences
        into a relative shift.  If None, inferred as the larger of the two
        profiles' observed time spans (last_minute − first_minute).

    Returns
    -------
    SiteConditionDivergence
    """
    a, b = profile_a, profile_b

    # Gate status
    gate_a = a.quality_gate_passed
    gate_b = b.quality_gate_passed

    # Timing deltas
    onset_delta = (
        (b.onset_minutes - a.onset_minutes)
        if (b.onset_minutes is not None and a.onset_minutes is not None)
        else None
    )
    peak_shift = (
        (b.peak_minutes - a.peak_minutes)
        if (b.peak_minutes is not None and a.peak_minutes is not None)
        else None
    )
    recovery_delta = (
        (b.recovery_minutes - a.recovery_minutes)
        if (b.recovery_minutes is not None and a.recovery_minutes is not None)
        else None
    )
    dur_delta = (
        (b.active_duration_minutes - a.active_duration_minutes)
        if (b.active_duration_minutes is not None and a.active_duration_minutes is not None)
        else None
    )

    # Amplitude
    amp_delta = (
        (b.amplitude - a.amplitude)
        if (b.amplitude is not None and a.amplitude is not None)
        else None
    )
    amp_ratio = _safe_div(b.amplitude, a.amplitude)
    amp_log2 = _safe_log2_ratio(b.amplitude, a.amplitude)

    # AUC
    auc_delta = (
        (b.auc_signed - a.auc_signed)
        if (b.auc_signed is not None and a.auc_signed is not None)
        else None
    )
    auc_mag_ratio = _safe_div(b.auc_absolute, a.auc_absolute)

    # Pattern
    pattern_conserved = a.primary_pattern == b.primary_pattern
    sign_reversal = (
        a.peak_sign is not None
        and b.peak_sign is not None
        and a.peak_sign != b.peak_sign
    )

    # Reference span for normalization
    if reference_span_minutes is None:
        span_a = (
            a.observed_minutes[-1] - a.observed_minutes[0]
            if len(a.observed_minutes) >= 2 else 0.0
        )
        span_b = (
            b.observed_minutes[-1] - b.observed_minutes[0]
            if len(b.observed_minutes) >= 2 else 0.0
        )
        reference_span_minutes = max(span_a, span_b) if (span_a > 0 or span_b > 0) else None

    divergence_score = _compute_divergence_score(
        sign_reversal=sign_reversal,
        pattern_conserved=pattern_conserved,
        pattern_a=a.primary_pattern,
        pattern_b=b.primary_pattern,
        amplitude_log2_ratio=amp_log2,
        peak_shift_minutes=peak_shift,
        reference_span=reference_span_minutes,
    )

    return SiteConditionDivergence(
        onset_delta_minutes=onset_delta,
        peak_shift_minutes=peak_shift,
        recovery_delta_minutes=recovery_delta,
        active_duration_delta_minutes=dur_delta,
        amplitude_delta=amp_delta,
        amplitude_ratio=amp_ratio,
        amplitude_log2_ratio=amp_log2,
        auc_signed_delta=auc_delta,
        auc_magnitude_ratio=auc_mag_ratio,
        pattern_a=a.primary_pattern,
        pattern_b=b.primary_pattern,
        pattern_conserved=pattern_conserved,
        sign_reversal=sign_reversal,
        divergence_score=divergence_score,
        both_quality_gate_passed=gate_a and gate_b,
        only_a_passes_gate=gate_a and not gate_b,
        only_b_passes_gate=not gate_a and gate_b,
        neither_passes_gate=not gate_a and not gate_b,
        reference_span_minutes=reference_span_minutes,
    )


def compare_site_trajectories(
    timepoint_labels: Sequence[Any],
    values_a: Sequence[Optional[float]],
    values_b: Sequence[Optional[float]],
    *,
    q_values_a: Optional[Sequence[Optional[float]]] = None,
    q_values_b: Optional[Sequence[Optional[float]]] = None,
    config: Optional[SiteKineticConfig] = None,
) -> Tuple[SiteConditionDivergence, SiteKineticProfile, SiteKineticProfile]:
    """Compute divergence directly from raw trajectories.

    Convenience wrapper: computes two SiteKineticProfile instances then calls
    compare_site_profiles.  The same timepoint_labels are used for both; pass
    different label lists via profiles if the conditions have different timepoints.

    Returns
    -------
    (divergence, profile_a, profile_b)
    """
    profile_a = compute_site_kinetic_profile(
        timepoint_labels, values_a, q_values=q_values_a, config=config
    )
    profile_b = compute_site_kinetic_profile(
        timepoint_labels, values_b, q_values=q_values_b, config=config
    )
    divergence = compare_site_profiles(profile_a, profile_b)
    return divergence, profile_a, profile_b


def summarise_population_divergence(
    divergences: Sequence[SiteConditionDivergence],
) -> PopulationDivergenceSummary:
    """Aggregate per-site divergence records into a population-level summary.

    Parameters
    ----------
    divergences : sequence of SiteConditionDivergence
        One record per site.  Empty input returns a zero summary.

    Returns
    -------
    PopulationDivergenceSummary
    """
    if not divergences:
        return PopulationDivergenceSummary(
            n_sites=0, n_both_pass=0, n_only_a_pass=0, n_only_b_pass=0,
            n_neither_pass=0, n_conserved=0, n_diverged=0, n_sign_reversal=0,
            conservation_rate=None, sign_reversal_rate=None,
            mean_divergence_score=None, mean_amplitude_log2_ratio=None,
            mean_peak_shift_minutes=None, pattern_transition_counts={},
            top_transitions=[],
        )

    n = len(divergences)
    n_both = sum(1 for d in divergences if d.both_quality_gate_passed)
    n_only_a = sum(1 for d in divergences if d.only_a_passes_gate)
    n_only_b = sum(1 for d in divergences if d.only_b_passes_gate)
    n_neither = sum(1 for d in divergences if d.neither_passes_gate)

    # Restrict pattern/sign metrics to sites where both pass gate
    both_pass = [d for d in divergences if d.both_quality_gate_passed]
    n_conserved = sum(1 for d in both_pass if d.pattern_conserved)
    n_diverged = len(both_pass) - n_conserved
    n_sign_rev = sum(1 for d in both_pass if d.sign_reversal)

    conservation_rate = n_conserved / n_both if n_both > 0 else None
    sign_rev_rate = n_sign_rev / n_both if n_both > 0 else None

    # Aggregate numerics
    scores = [d.divergence_score for d in divergences]
    mean_score = sum(scores) / len(scores) if scores else None

    log2_ratios = [d.amplitude_log2_ratio for d in divergences if d.amplitude_log2_ratio is not None]
    mean_log2 = sum(log2_ratios) / len(log2_ratios) if log2_ratios else None

    peak_shifts = [d.peak_shift_minutes for d in both_pass if d.peak_shift_minutes is not None]
    mean_shift = sum(peak_shifts) / len(peak_shifts) if peak_shifts else None

    # Transition matrix
    transitions: Counter[Tuple[str, str]] = Counter()
    for d in both_pass:
        transitions[(d.pattern_a, d.pattern_b)] += 1

    transition_counts = {f"{a}\u2192{b}": count for (a, b), count in transitions.items()}
    top = sorted(transitions.items(), key=lambda kv: -kv[1])[:10]
    top_transitions = [(a, b, count) for (a, b), count in top]

    return PopulationDivergenceSummary(
        n_sites=n,
        n_both_pass=n_both,
        n_only_a_pass=n_only_a,
        n_only_b_pass=n_only_b,
        n_neither_pass=n_neither,
        n_conserved=n_conserved,
        n_diverged=n_diverged,
        n_sign_reversal=n_sign_rev,
        conservation_rate=conservation_rate,
        sign_reversal_rate=sign_rev_rate,
        mean_divergence_score=round(mean_score, 6) if mean_score is not None else None,
        mean_amplitude_log2_ratio=round(mean_log2, 6) if mean_log2 is not None else None,
        mean_peak_shift_minutes=round(mean_shift, 6) if mean_shift is not None else None,
        pattern_transition_counts=transition_counts,
        top_transitions=top_transitions,
    )
