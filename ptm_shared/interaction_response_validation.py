"""P4/P5: Interaction-response validation framework.

P4: Trametinib primary interaction-response validation.
  ΔMEK = [IM − M] − [I − V]
  where I=insulin, M=MEK inhibitor (Trametinib), V=vehicle, IM=insulin+MEK.

P5: Mirdametinib chemical holdout (Q2 reproducibility).
  Frozen pipeline; compound-specific effects explicitly noted.

STATUS: PENDING DATA.
  This module defines the framework and computational contract.
  Actual validation requires Trametinib and mirdametinib cohort data
  (site × timepoint × replicate FC matrices).

WHEN DATA IS AVAILABLE
----------------------
1. Freeze the entire analysis pipeline (Waves, TMM, event records) on the
   Trametinib cohort WITHOUT inspecting drug-response outcome.
2. Compute ΔMEK interaction contrast and check if event-order features
   enriched pre-treatment sites that show MEK-interaction response.
3. Only after P4 passes, set _P4_VALIDATION_PASSED = True in
   temporal_precedence_output.py to unlock causal language in reports.
4. Apply the frozen pipeline to mirdametinib (P5) without modification.

ISOLATION RULE
--------------
Drug-cohort outcome labels (ΔMEK, inhibitor response direction) must NEVER
flow into temporal analysis code, Wave clustering, or TMM scoring.
This module uses a pending_data guard to enforce this at import time.

Implementation target: PDF §4 P4/P5.
Pre-registration framework: 2026-08-29.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np

CONTRACT_VERSION = "interaction_response_validation.v1"


class P4Status(str, enum.Enum):
    pending_data = "pending_data"
    pipeline_frozen = "pipeline_frozen"
    contrast_computed = "contrast_computed"
    validation_passed = "validation_passed"
    validation_failed = "validation_failed"


class P5Status(str, enum.Enum):
    pending_p4 = "pending_p4"
    pending_data = "pending_data"
    holdout_computed = "holdout_computed"
    reproducible = "reproducible"
    compound_specific = "compound_specific"


@dataclass
class InteractionContrastInput:
    """Input container for ΔMEK contrast calculation.

    All matrices are site × timepoint × replicate (NaN for missing).
    Units: log2FC relative to 0-min baseline.

    Attributes
    ----------
    insulin_only : array[n_sites, n_tp, n_rep]  — I condition
    mek_inhibitor : array[n_sites, n_tp, n_rep]  — M condition
    insulin_plus_mek : array[n_sites, n_tp, n_rep]  — IM condition
    vehicle : array[n_sites, n_tp, n_rep]  — V condition
    site_keys : list[str]  — site identifiers aligned to axis 0
    timepoint_labels : list[str]
    drug_name : str  — "Trametinib" (P4) or "mirdametinib" (P5)
    cohort : str  — "primary" (P4) or "holdout_Q2" (P5)
    """

    insulin_only: np.ndarray
    mek_inhibitor: np.ndarray
    insulin_plus_mek: np.ndarray
    vehicle: np.ndarray
    site_keys: list[str]
    timepoint_labels: list[str]
    drug_name: str = "Trametinib"
    cohort: str = "primary"


@dataclass
class InteractionContrastResult:
    """Result of ΔMEK contrast calculation per site × timepoint.

    ΔMEK[i, t] = mean(IM[i,t,:]) - mean(M[i,t,:]) - (mean(I[i,t,:]) - mean(V[i,t,:]))
    """

    site_keys: list[str]
    timepoint_labels: list[str]
    delta_mek: np.ndarray     # shape [n_sites, n_timepoints]
    delta_mek_std: np.ndarray # per-site, per-timepoint std (from replicate variance)
    drug_name: str
    cohort: str
    contract_version: str = CONTRACT_VERSION


@dataclass
class P4ValidationResult:
    """P4 Trametinib validation output.

    Attributes
    ----------
    status : P4Status
    enrichment_score : float | None  — fraction of top-ranked event-order sites
        that show MEK-interaction response above the null expectation.
    direction_preserved : bool | None  — Q1: does event-order direction agree?
    n_sites_evaluated : int
    n_sites_enriched : int
    threshold_fc_used : float  — frozen before seeing drug response
    note : str
    """

    status: P4Status
    enrichment_score: float | None = None
    direction_preserved: bool | None = None
    n_sites_evaluated: int = 0
    n_sites_enriched: int = 0
    threshold_fc_used: float = 0.40
    note: str = ""
    contract_version: str = CONTRACT_VERSION


@dataclass
class P5HoldoutResult:
    """P5 Mirdametinib holdout (Q2) output."""

    status: P5Status
    q2_direction_concordance: float | None = None
    q2_ranking_preserved: bool | None = None
    compound_specific_note: str = (
        "mirdametinib effect may be compound-specific. "
        "Q2 concordance does NOT validate the general kinase model."
    )
    contract_version: str = CONTRACT_VERSION


# ── ΔMEK computation ──────────────────────────────────────────────────────

def compute_delta_mek(inp: InteractionContrastInput) -> InteractionContrastResult:
    """Compute ΔMEK = [IM − M] − [I − V] per site × timepoint.

    Requires data. Returns pending result if arrays are empty.
    """
    if inp.insulin_only.size == 0:
        raise ValueError(
            "InteractionContrastInput arrays are empty. "
            "P4 computation requires actual Trametinib cohort data. "
            "Status: PENDING_DATA."
        )

    def _mean_rep(arr: np.ndarray) -> np.ndarray:
        return np.nanmean(arr, axis=2)

    im = _mean_rep(inp.insulin_plus_mek)
    m = _mean_rep(inp.mek_inhibitor)
    i = _mean_rep(inp.insulin_only)
    v = _mean_rep(inp.vehicle)

    delta = (im - m) - (i - v)

    # Propagate replicate std
    def _std_rep(arr: np.ndarray) -> np.ndarray:
        return np.nanstd(arr, axis=2, ddof=1)

    delta_var = (
        _std_rep(inp.insulin_plus_mek) ** 2
        + _std_rep(inp.mek_inhibitor) ** 2
        + _std_rep(inp.insulin_only) ** 2
        + _std_rep(inp.vehicle) ** 2
    )
    delta_std = np.sqrt(delta_var)

    return InteractionContrastResult(
        site_keys=inp.site_keys,
        timepoint_labels=inp.timepoint_labels,
        delta_mek=delta,
        delta_mek_std=delta_std,
        drug_name=inp.drug_name,
        cohort=inp.cohort,
    )


def check_event_order_enrichment(
    contrast: InteractionContrastResult,
    event_order_ranks: Mapping[str, float],
    *,
    top_n: int = 50,
    enrichment_threshold_fc: float = 0.40,
) -> dict[str, Any]:
    """Check if top-ranked event-order sites are enriched in ΔMEK response.

    Parameters
    ----------
    contrast : InteractionContrastResult
    event_order_ranks : {site_key: rank_score} — lower rank = higher priority.
        Must be frozen BEFORE computing contrast (pipeline freeze rule).
    top_n : number of top sites to evaluate
    enrichment_threshold_fc : minimum |ΔMEK| to count as "responsive"

    Returns enrichment_score = n_responsive_in_top_n / top_n.
    """
    sorted_sites = sorted(event_order_ranks, key=lambda s: event_order_ranks[s])
    top_sites = set(sorted_sites[:top_n])

    # Max |ΔMEK| per site across timepoints
    site_max_delta = {
        site: float(np.nanmax(np.abs(contrast.delta_mek[i, :])))
        for i, site in enumerate(contrast.site_keys)
        if site in top_sites
    }

    n_evaluated = len(site_max_delta)
    n_enriched = sum(1 for v in site_max_delta.values() if v >= enrichment_threshold_fc)
    enrichment_score = round(n_enriched / n_evaluated, 4) if n_evaluated > 0 else 0.0

    return {
        "enrichment_score": enrichment_score,
        "n_top_sites": top_n,
        "n_evaluated_in_top": n_evaluated,
        "n_enriched": n_enriched,
        "enrichment_threshold_fc": enrichment_threshold_fc,
    }


# ── P4 stub (pending data) ────────────────────────────────────────────────

def run_p4_trametinib_validation(
    trametinib_data: InteractionContrastInput | None,
    event_order_ranks: Mapping[str, float],
    *,
    threshold_fc: float = 0.40,
) -> P4ValidationResult:
    """Run P4 validation if Trametinib data is available; else return stub.

    PIPELINE FREEZE RULE: event_order_ranks MUST be computed from the
    pre-treatment temporal analysis before this function is called.
    This function must NEVER inform upstream temporal analysis.
    """
    if trametinib_data is None:
        return P4ValidationResult(
            status=P4Status.pending_data,
            note=(
                "P4 validation requires Trametinib cohort data "
                "(site × timepoint × replicate log2FC matrices for "
                "I, M, IM, V conditions). Freeze the analysis pipeline "
                "before acquiring data."
            ),
        )

    try:
        contrast = compute_delta_mek(trametinib_data)
        enrichment = check_event_order_enrichment(
            contrast, event_order_ranks, enrichment_threshold_fc=threshold_fc
        )
        return P4ValidationResult(
            status=P4Status.contrast_computed,
            enrichment_score=enrichment["enrichment_score"],
            n_sites_evaluated=enrichment["n_evaluated_in_top"],
            n_sites_enriched=enrichment["n_enriched"],
            threshold_fc_used=threshold_fc,
            note=(
                f"ΔMEK computed for {len(contrast.site_keys)} sites. "
                f"Enrichment score: {enrichment['enrichment_score']}. "
                "Manual review required before marking as validation_passed."
            ),
        )
    except ValueError as e:
        return P4ValidationResult(
            status=P4Status.pending_data,
            note=str(e),
        )


# ── P5 stub (pending P4 + mirdametinib data) ─────────────────────────────

def run_p5_mirdametinib_holdout(
    mirdametinib_data: InteractionContrastInput | None,
    p4_result: P4ValidationResult,
    event_order_ranks: Mapping[str, float],
    *,
    threshold_fc: float = 0.40,
) -> P5HoldoutResult:
    """Run P5 holdout if P4 passed and mirdametinib data is available.

    Mirdametinib effect may be compound-specific — do NOT claim
    Q2 concordance validates the general kinase model.
    """
    if p4_result.status not in (P4Status.validation_passed, P4Status.contrast_computed):
        return P5HoldoutResult(
            status=P5Status.pending_p4,
            compound_specific_note=(
                "P5 requires P4 (Trametinib) to complete first. "
                "Apply frozen pipeline without modification to mirdametinib cohort."
            ),
        )

    if mirdametinib_data is None:
        return P5HoldoutResult(
            status=P5Status.pending_data,
            compound_specific_note=(
                "P5 requires mirdametinib cohort data. "
                "Use the FROZEN pipeline from P4 without any modification."
            ),
        )

    try:
        contrast = compute_delta_mek(mirdametinib_data)
        enrichment = check_event_order_enrichment(
            contrast, event_order_ranks, enrichment_threshold_fc=threshold_fc
        )
        concordance = enrichment["enrichment_score"]
        return P5HoldoutResult(
            status=P5Status.holdout_computed,
            q2_direction_concordance=concordance,
            q2_ranking_preserved=concordance > 0.5,
            compound_specific_note=(
                f"Mirdametinib Q2 enrichment score: {concordance:.4f}. "
                "Any observed effect may be compound-specific to mirdametinib. "
                "Do NOT use Q2 result to make general kinase model claims."
            ),
        )
    except ValueError as e:
        return P5HoldoutResult(
            status=P5Status.pending_data,
            compound_specific_note=str(e),
        )


# ── Validation status report ──────────────────────────────────────────────

def validation_status_report(
    p4: P4ValidationResult,
    p5: P5HoldoutResult,
) -> dict[str, Any]:
    """Generate a human-readable validation status report."""
    return {
        "p4_trametinib": {
            "status": p4.status.value,
            "enrichment_score": p4.enrichment_score,
            "note": p4.note,
        },
        "p5_mirdametinib": {
            "status": p5.status.value,
            "q2_direction_concordance": p5.q2_direction_concordance,
            "compound_specific_note": p5.compound_specific_note,
        },
        "causal_language_unlocked": (
            p4.status == P4Status.validation_passed
        ),
        "recommendation": (
            "Causal interpretation of event-order output is NOT YET validated. "
            "Report phrases must use 'observed temporal precedence' language only."
            if p4.status != P4Status.validation_passed else
            "P4 validation passed. Causal language may be used for Trametinib-validated "
            "relations only. P5 holdout provides Q2 reproducibility check."
        ),
        "contract_version": CONTRACT_VERSION,
    }
