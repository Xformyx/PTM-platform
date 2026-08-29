"""P3: Production temporal precedence output — evidence-tiered, non-mutating.

Provides additive temporal observations that attach to existing analysis output
WITHOUT modifying static Wave membership, TMM scores, kinase rankings, or any
locked score.

PRODUCTION SAFETY RULES
------------------------
1. NO static Wave membership change.
2. NO TMM score, coefficient, or kinase ranking change.
3. NO locked benchmark truth or known relation flows into production output.
4. Until P4 (Trametinib validation), all report phrases use "not_evaluable"
   or "observed temporal precedence with uncertainty".
5. Output is additive: a new `temporal_precedence` field on the sidecar.

PHRASE POLICY (PDF §4 P3)
--------------------------
FORBIDDEN phrases:
  - "X kinase activates Y at time T"
  - "Dynamic Co-Wave demonstrates causal temporal ordering"
  - "temporal ordering validated"

REQUIRED phrase template:
  - "Site X shows observed response timing onset ~T min (CI [L, U]) within the
    measured time window. Causal interpretation requires independent validation."
  - If not_evaluable: "Temporal event resolution requires replicate-level data."

Implementation target: PDF §2 P3.
Pre-registration: 2026-08-29.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ptm_shared.replicate_event_adapter import EventRecord, EventStatus
from ptm_shared.study_temporal_context import StudyTemporalContext, INSULIN_TEMPORAL_CONTEXT

CONTRACT_VERSION = "temporal_precedence_output.v1"

# P4 validation gate — flipped to True only after Trametinib interaction-response
# validation passes (see interaction_response_validation.py).
# Until then, all report phrases default to "not_evaluable".
_P4_VALIDATION_PASSED: bool = False


class TemporalObservationTier(str, enum.Enum):
    resolved_within_grid = "resolved_within_grid"
    left_censored = "left_censored"
    right_censored = "right_censored"
    ambiguous = "ambiguous"
    not_evaluable = "not_evaluable"


@dataclass
class TemporalPrecedenceObservation:
    """Single-site temporal precedence observation.

    Attributes
    ----------
    site_key : str
    tier : TemporalObservationTier
    report_phrase : str  — safe, pre-approved phrase (see PHRASE POLICY)
    onset_t50_min : float | None
    onset_ci95_min : tuple | None
    peak_t_min : float | None
    peak_ci95_min : tuple | None
    exit_t50_min : float | None
    exit_ci95_min : tuple | None
    replicate_bootstrap_stability : float | None
    wave_id : str | None
    p4_gate_passed : bool  — False until Trametinib validation completes
    """

    site_key: str
    tier: TemporalObservationTier
    report_phrase: str
    onset_t50_min: float | None = None
    onset_ci95_min: tuple[float, float] | None = None
    peak_t_min: float | None = None
    peak_ci95_min: tuple[float, float] | None = None
    exit_t50_min: float | None = None
    exit_ci95_min: tuple[float, float] | None = None
    replicate_bootstrap_stability: float | None = None
    wave_id: str | None = None
    p4_gate_passed: bool = False
    input_type: str = "condition_mean_gp"
    contract_version: str = CONTRACT_VERSION


def _build_report_phrase(
    record: EventRecord,
    time_unit: str = "min",
    p4_passed: bool = False,
) -> str:
    """Build a safe, policy-compliant report phrase for a site.

    Forbidden: causal language, "validates", "demonstrates temporal ordering".
    Required: "observed response timing", "within the measured time window".
    If P4 not passed: append not_evaluable_causal_claim note.
    """
    status = record.event_status

    if status == EventStatus.not_evaluable_replicate_posterior:
        return (
            "not_evaluable_replicate_posterior: "
            "Temporal event resolution requires replicate-level data. "
            "Condition-mean GP is available for exploratory analysis only."
        )

    if status == EventStatus.unresolved:
        return (
            f"Site {record.site_key}: no significant temporal response detected "
            f"within the measured time window (threshold |FC| >= {record.amplitude_threshold_fc})."
        )

    peak_str = (
        f"peak ~{record.peak_t_min:.1f} {time_unit}"
        if record.peak_t_min is not None else "peak not determined"
    )
    onset_str = ""
    if status == EventStatus.left_censored:
        onset_str = "onset before first measured timepoint (left-censored)"
    elif record.onset_t50_min is not None:
        ci = record.onset_ci95_min
        ci_str = f" (95% CI [{ci[0]:.1f}, {ci[1]:.1f}] {time_unit})" if ci else ""
        onset_str = f"onset ~{record.onset_t50_min:.1f} {time_unit}{ci_str}"

    exit_str = ""
    if status == EventStatus.right_censored:
        exit_str = "exit not resolved by last timepoint (right-censored)"
    elif record.exit_t50_min is not None:
        ci = record.exit_ci95_min
        ci_str = f" (95% CI [{ci[0]:.1f}, {ci[1]:.1f}] {time_unit})" if ci else ""
        exit_str = f"exit ~{record.exit_t50_min:.1f} {time_unit}{ci_str}"

    parts = [f"Site {record.site_key}: observed response timing"]
    if onset_str:
        parts.append(onset_str)
    if peak_str:
        parts.append(peak_str)
    if exit_str:
        parts.append(exit_str)

    phrase = "; ".join(parts) + " (within the measured time window)."

    if not p4_passed:
        phrase += (
            " Causal interpretation requires independent chemical/genetic "
            "holdout validation (P4 gate not yet passed)."
        )
    return phrase


def build_temporal_precedence_observation(
    record: EventRecord,
    wave_id: str | None = None,
    time_unit: str = "min",
    *,
    p4_passed: bool = _P4_VALIDATION_PASSED,
) -> TemporalPrecedenceObservation:
    """Convert an EventRecord to a production-safe TemporalPrecedenceObservation."""

    status_map = {
        EventStatus.resolved: TemporalObservationTier.resolved_within_grid,
        EventStatus.left_censored: TemporalObservationTier.left_censored,
        EventStatus.right_censored: TemporalObservationTier.right_censored,
        EventStatus.ambiguous: TemporalObservationTier.ambiguous,
        EventStatus.unresolved: TemporalObservationTier.not_evaluable,
        EventStatus.not_evaluable_replicate_posterior: TemporalObservationTier.not_evaluable,
    }

    return TemporalPrecedenceObservation(
        site_key=record.site_key,
        tier=status_map.get(record.event_status, TemporalObservationTier.not_evaluable),
        report_phrase=_build_report_phrase(record, time_unit=time_unit, p4_passed=p4_passed),
        onset_t50_min=record.onset_t50_min,
        onset_ci95_min=record.onset_ci95_min,
        peak_t_min=record.peak_t_min,
        peak_ci95_min=record.peak_ci95_min,
        exit_t50_min=record.exit_t50_min,
        exit_ci95_min=record.exit_ci95_min,
        replicate_bootstrap_stability=record.replicate_bootstrap_stability,
        wave_id=wave_id,
        p4_gate_passed=p4_passed,
        input_type=record.input_type,
    )


def build_temporal_precedence_output(
    event_records: Mapping[str, EventRecord],
    wave_contract: Mapping[str, Any],
    study_context: StudyTemporalContext | None = None,
    *,
    p4_passed: bool = _P4_VALIDATION_PASSED,
) -> dict[str, Any]:
    """Build production temporal precedence output for all sites.

    SAFETY: Does NOT modify wave_contract in any way.
    Returns additive output dict for attachment to sidecar.

    Returns
    -------
    dict with keys:
      observations : list[dict]  — one per site
      summary      : dict        — coverage and tier breakdown
      p4_gate      : dict        — gate status
      contract_version : str
    """
    ctx = study_context or INSULIN_TEMPORAL_CONTEXT
    time_unit = "min" if ctx.time_unit_label == "minutes" else (
        "hr" if ctx.time_unit_label == "hours" else "day"
    )

    # Build site→wave_id mapping
    site_to_wave: dict[str, str] = {}
    for wave in wave_contract.get("waves", []):
        for m in wave.get("members", []):
            site_to_wave[m] = wave["wave_id"]

    observations: list[dict[str, Any]] = []
    tier_counts: dict[str, int] = {}

    for site_key, record in sorted(event_records.items()):
        obs = build_temporal_precedence_observation(
            record,
            wave_id=site_to_wave.get(site_key),
            time_unit=time_unit,
            p4_passed=p4_passed,
        )
        tier_counts[obs.tier.value] = tier_counts.get(obs.tier.value, 0) + 1
        observations.append({
            "site_key": obs.site_key,
            "wave_id": obs.wave_id,
            "tier": obs.tier.value,
            "onset_t50_min": obs.onset_t50_min,
            "onset_ci95_min": obs.onset_ci95_min,
            "peak_t_min": obs.peak_t_min,
            "peak_ci95_min": obs.peak_ci95_min,
            "exit_t50_min": obs.exit_t50_min,
            "exit_ci95_min": obs.exit_ci95_min,
            "replicate_bootstrap_stability": obs.replicate_bootstrap_stability,
            "report_phrase": obs.report_phrase,
            "p4_gate_passed": obs.p4_gate_passed,
            "input_type": obs.input_type,
        })

    n_total = len(observations)
    n_evaluable = sum(
        1 for o in observations
        if o["tier"] != TemporalObservationTier.not_evaluable.value
    )

    return {
        "observations": observations,
        "summary": {
            "n_sites": n_total,
            "n_evaluable": n_evaluable,
            "tier_breakdown": tier_counts,
            "study_context": ctx.study_id,
        },
        "p4_gate": {
            "passed": p4_passed,
            "note": (
                "P4 gate passed: causal interpretation unlocked in report phrases."
                if p4_passed else
                "P4 gate NOT passed. All report phrases use "
                "'observed temporal precedence' language only. "
                "Trametinib interaction-response validation required for P4."
            ),
        },
        "contract_version": CONTRACT_VERSION,
        "mutation_guarantee": (
            "This output is additive. "
            "Static Wave membership, TMM scores, kinase rankings, and locked "
            "scores are not modified by temporal precedence output."
        ),
    }
