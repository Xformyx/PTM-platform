"""Frozen truth-free temporal configuration selected by nested validation.

Selection used only replicate holdout stability, Wave structure, TMM holdout
reconstruction, and parsimony.  No locked benchmark truth was available to the
selector.  The ordinary production defaults remain unchanged; strict benchmark
runs opt in explicitly while the configuration undergoes server confirmation.
"""

from __future__ import annotations

import hashlib
import json


CONTRACT_VERSION = "truth_free_temporal_optimized.v2"
SELECTION_RECORD_SHA256 = "2a6c7c728b2b931cb00f275e39be721a4ed904f95c566077219c3f5c254201e1"
SELECTION_LAST_RECORD_SHA256 = "f535cb2e319de574395b7e108216832ba5154d1c4a0bf4f415321f6db59f1b7a"

SITE_AGGREGATION = "median"

WAVE_CONFIG = {
    "correlation_threshold": 0.70,
    "minimum_variance": 0.30,
    "minimum_amplitude": 0.40,
    "minimum_cluster_size": 2,
    "maximum_waves": 8,
    "compute_directionality": True,
    "bootstrap_repeats": 25,
    "soft_membership_threshold": 0.60,
    "threshold_source": CONTRACT_VERSION,
}

TMM_CONFIG = {
    "profile_min_exclusive": 5,
    "gaussian_sigma_log": 0.80,
    "target_transform": "magnitude",
    "activity_metric": "shrunken_mean",
    "shrinkage_prior_support": 10.0,
    "candidate_prior_strength": 5.0,
    "candidate_hierarchy_mode": "family_guard",
    "iterative_profile_rounds": 0,
    "iterative_min_top1_probability": 0.80,
    "iterative_min_shared_support": 3,
    "iterative_profile_blend": 0.50,
    "dual_track_correlation_threshold": 0.50,
    "dual_track_peak_index_tolerance": 2,
    "dual_track_magnitude_log2_ratio_threshold": 1.0,
    "uncertainty_bootstrap_repeats": 50,
    "uncertainty_loto_enabled": True,
    "uncertainty_seed": 20260826,
}

ADDITIVE_V2_CONTRACT_VERSION = "enrichment_free_temporal_mechanism.v2"
ADDITIVE_V2_SELECTION_LEDGER_SHA256 = "818b7ef4e9ea27b61791ad85f919ab3b1812284edf80c267c078a637cd2ee114"
ADDITIVE_V2_SELECTION_LAST_RECORD_SHA256 = "8464787a5bd1d43feecaf072de74fe283956f294812be431f68f72c7f7b092b0"
CROSS_LAYER_CONFIG = {
    "minimum_absolute_change": 0.30,
    "minimum_lag_aware_similarity": 0.40,
    "minimum_loto_stability": 0.60,
    "maximum_candidates_per_wave": 200,
    "bootstrap_iterations": 0,
    "permutation_iterations": 0,
    "random_seed": 20260827,
}
# ── Temporal ordering evidence record (2026-08-28) ─────────────────────────
# Finding: p_time_index_permutation = 0.570858 (transition_resolution metric,
#   commit 8fc58701, Insulin_Signaling_Dynamic_V1).
# Interpretation: current transition_resolution CANNOT distinguish the observed
#   temporal ordering from random orderings at any conventional alpha level.
# Consequence:
#   FORBIDDEN claim: "Dynamic Co-Wave captures biologically meaningful temporal ordering."
#   PERMITTED claim: "Dynamic Co-Wave provides a reproducible annotation of local
#     membership reconfiguration within static temporal modules."
# Resolution path: T_adjacency statistic (mean J_adjacent - mean J_non-adjacent).
#   Exact permutation over all 720 orderings for 6 timepoints.
#   A significant T_adjacency p-value is required before claiming temporal structure.
# Reference: Image §2.1 "시간 순서의 정보성은 아직 증명되지 않았음", 2026-08-28.
TEMPORAL_ORDERING_P_VALUE_RECORD: dict[str, object] = {
    "records": [
        {
            "metric": "p_time_index_permutation_of_transition_resolution",
            "value": 0.570858,
            "dataset": "Insulin_Signaling_Dynamic_V1",
            "commit": "8fc58701f6457230dd1203087075e0df1b41c987",
            "date": "2026-08-28",
            "verdict": "not_significant",
        },
        {
            "metric": "T_adjacency_exact_permutation_720",
            "value": 0.284327,
            "n_exceedances": 204,
            "n_permutations": 720,
            "t_adjacency_observed": 0.031171,
            "null_mean": 0.0,
            "null_std": 0.047861,
            "dataset": "Insulin_Signaling_Dynamic_V1",
            "commit": "f02084e",
            "date": "2026-08-29",
            "verdict": "not_significant",
            "note": (
                "T_adjacency is a more direct measure than transition_resolution "
                "but still fails to demonstrate temporal ordering informativeness. "
                "Changing statistics to find significance (score chasing) is forbidden."
            ),
        },
    ],
    "verdict_summary": "temporal_ordering_not_statistically_significant_in_any_test_to_date",
    "forbidden_claim": "Dynamic Co-Wave captures biologically meaningful temporal ordering.",
    "permitted_claim": (
        "Dynamic Co-Wave provides a reproducible annotation of local membership "
        "reconfiguration within static temporal modules."
    ),
    "resolution_path": (
        "Not further global permutation statistics. "
        "Next: pre-specified kinase/site relation onset/peak/exit difference with CI "
        "from raw replicate trajectory; Trametinib interaction response as primary "
        "external outcome; mirdametinib as fixed-pipeline chemical holdout."
    ),
    "log1p_coordinate_validation": {
        "status": "not_demonstrated",
        "date": "2026-08-29",
        "reason": (
            "Coordinate–length-scale unit mismatch (length_scale_min=15 in minute units, "
            "log1p values span 0.69–5.20). T_adjacency p=0.284327 not significant. "
            "log1p default reverted to 'minutes'; GP_LOG1P_LENGTH_SCALE_MIN added as "
            "EXPERIMENTAL constant for future validated use."
        ),
    },
}


# ── Next-step roadmap (2026-08-29) ─────────────────────────────────────────
# Source: "Latest Temporal-Order Remediation Revalidation" PDF, 2026-08-29.
#
# The correct path forward is NOT to find another global permutation statistic.
# It IS:
#   1. Raw replicate trajectory model: y_irt = f_i(t) + b_ir + ε_irt
#      (per-replicate intensity, not condition-level FC)
#   2. Pre-specified kinase/site relations: define onset/peak/exit differences
#      and confidence intervals BEFORE seeing kinase scores.
#   3. Primary external outcome: Trametinib interaction response.
#   4. Fixed-pipeline chemical holdout: mirdametinib.
#   5. T_adjacency (and any other global order statistic) stays as a
#      descriptive structure test — NOT used for kinase/causality claims.
#
# Prerequisites before implementing:
#   a. Replicate-level intensity data available in production pipeline
#   b. Pre-specified kinase–site pair list frozen in docs before data analysis
#   c. Trametinib/mirdametinib outcome labels isolated from temporal analysis
TEMPORAL_ORDERING_NEXT_STEPS: dict[str, object] = {
    "date": "2026-08-29",
    "source": "Latest_Temporal-Order_Remediation_Revalidation.pdf",
    "scope": "general (applies to all time-course studies, not insulin-only)",
    "immediate_action": "none — do NOT change global permutation statistics further",
    "next_implementation_steps": [
        "P1: replicate_aware_event_record — model y_irt = f_i(t) + b_ir + epsilon_irt "
        "from per-replicate intensity; return event_status=not_evaluable when condition-mean only",
        "P1: event_record_schema — onset_t50 + CI, peak_t + CI, exit_t50 + CI, "
        "event_status (resolved/left_censored/right_censored/ambiguous/unresolved), "
        "replicate_bootstrap_stability",
        "P2: known_relation_registry — study-specific (source, target, allowed_lag, "
        "expected_direction, evidence_tier); runner-only; start with insulin anchors",
        "P2: within_wave_synchrony_test (A) — P(|t_onset_i - t_onset_j| <= tau); "
        "null=membership permutation; tau from StudyTemporalContext",
        "P2: directed_precedence_concordance_test (B) — P(t_source + delta < t_target); "
        "null=hierarchical replicate bootstrap + relation-level temporal permutation",
        "P3: production temporal precedence output as evidence-tiered observation "
        "(static Wave/TMM/score non-mutation)",
        "P4: study-specific primary interaction-response validation "
        "(insulin: Trametinib ΔMEK; other studies: equivalent chemical/genetic holdout)",
        "P5: study-specific chemical holdout Q2 reproducibility",
        "t_adjacency_role: descriptive structure test only, NOT causal claim basis",
    ],
    "generalisation_notes": {
        "gp_length_scale": (
            "15 min (insulin) is NOT a universal default. "
            "Use StudyTemporalContext.gp_length_scale_min_minutes derived from "
            "compute_gp_length_scale_from_grid() and biological review per study. "
            "Cell cycle: ~12 hr. Hypoxia: ~6 hr. EGF: ~6 min."
        ),
        "synchrony_tau": (
            "5 min (insulin) is NOT universal. Set tau = nominal_grid_interval for each study. "
            "StudyTemporalContext.synchrony_tau_minutes holds this value."
        ),
        "chemical_holdout": (
            "Trametinib/mirdametinib are insulin+MEK specific. "
            "Every study must define its own chemical/genetic holdout in "
            "StudyTemporalContext.chemical_holdout_description before primary analysis."
        ),
        "known_relation_registry": (
            "Insulin anchors are insulin-specific. Other studies need their own registry "
            "in (source, target, allowed_lag_min, expected_direction, evidence_tier) format. "
            "Registry must be runner-only; never flow into production temporal output."
        ),
        "time_grid": (
            "Current 1-5-15-30-60-180 min grid: 0-5 min onset is left-censored or unresolved. "
            "Recommended dense early grid: 0, 0.25-0.5, 1, 2, 5, 10, 15, 30, 60, 180 min. "
            "For other studies, equivalent early-phase density is required."
        ),
    },
    "gating_prerequisites": [
        "replicate-level intensity available in production preprocessing output",
        "StudyTemporalContext pre-registered with gp_length_scale and tau for each study",
        "known-relation registry isolated from temporal analysis code path",
        "chemical/genetic holdout labels isolated from temporal analysis code path",
    ],
}


DYNAMIC_COWAVE_CONTRACT_VERSION = "dynamic_co_wave_transition.v2"
DYNAMIC_COWAVE_SELECTION_LEDGER_SHA256 = "02ab551eb3c345250fa1e76758599e18026fa6b8c72889d95b7c533ebede882e"
DYNAMIC_COWAVE_SELECTION_RECORD_SHA256 = "2d12157f12eed4a3322a9a0253257352003e84044534d53dec03336770b1a08e"
DYNAMIC_COWAVE_LEDGER_TAIL_RECORD_SHA256 = "baf6849198616b6771358cc3e6936c2ac83b7c2c5f558741600345322aefdf51"
DYNAMIC_COWAVE_CONFIG = {
    "activity_threshold_fc": 0.40,
    "minimum_observed_timepoints": 4,
    "membership_universe": "retained_canonical_wave_members_only",
    "pair_scope": "same_static_wave_only",
    "site_event_policy": "record_noninert_transitions_only",
    "lotto": "leave_one_timepoint_out",
    "maximum_pair_transition_examples": 500,
    "maximum_site_transition_examples": 500,
    "maximum_membership_examples": 250,
}
_ADDITIVE_V2_CONFIG = {
    "contract_version": ADDITIVE_V2_CONTRACT_VERSION,
    "cross_layer": CROSS_LAYER_CONFIG,
    "dynamic_cowave": DYNAMIC_COWAVE_CONFIG,
}
ADDITIVE_V2_CONFIG_SHA256 = hashlib.sha256(
    json.dumps(_ADDITIVE_V2_CONFIG, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()

_CANONICAL_CONFIG = {
    "contract_version": CONTRACT_VERSION,
    "site_aggregation": SITE_AGGREGATION,
    "wave": WAVE_CONFIG,
    "tmm": TMM_CONFIG,
}
CONFIG_SHA256 = hashlib.sha256(
    json.dumps(_CANONICAL_CONFIG, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()


def provenance() -> dict[str, object]:
    return {
        "contract_version": CONTRACT_VERSION,
        "config_sha256": CONFIG_SHA256,
        "selection_record_sha256": SELECTION_RECORD_SHA256,
        "selection_last_record_sha256": SELECTION_LAST_RECORD_SHA256,
        "selection_objective": "truth_free_nested_replicate_stability_and_reconstruction",
        "truth_used_for_selection": False,
        "replicate_outer_folds": 3,
        "selection_trial_count": 7,
        "iterative_profile_decision": "rejected_rounds_zero_retained",
        "site_aggregation": SITE_AGGREGATION,
        "wave": dict(WAVE_CONFIG),
        "tmm": dict(TMM_CONFIG),
        "additive_v2": {
            "contract_version": ADDITIVE_V2_CONTRACT_VERSION,
            "config_sha256": ADDITIVE_V2_CONFIG_SHA256,
            "selection_ledger_sha256": ADDITIVE_V2_SELECTION_LEDGER_SHA256,
            "selection_last_record_sha256": ADDITIVE_V2_SELECTION_LAST_RECORD_SHA256,
            "selection_trial_count": 9,
            "truth_used_for_selection": False,
            "cross_layer": dict(CROSS_LAYER_CONFIG),
            "dynamic_cowave": {
                "contract_version": DYNAMIC_COWAVE_CONTRACT_VERSION,
                "configuration": dict(DYNAMIC_COWAVE_CONFIG),
                "selection_ledger_sha256": DYNAMIC_COWAVE_SELECTION_LEDGER_SHA256,
                "selection_record_sha256": DYNAMIC_COWAVE_SELECTION_RECORD_SHA256,
                "ledger_tail_record_sha256": DYNAMIC_COWAVE_LEDGER_TAIL_RECORD_SHA256,
                "selection_trial_count": 3,
                "truth_used_for_selection": False,
                "selection_objective": "0.45_pair_loto_jaccard + 0.25_site_loto_jaccard + 0.20_active_pair_coverage + 0.10_transition_resolution",
            },
            "protein_replicate_stability_status": "unavailable_condition_level_only",
        },
    }


# ── Dynamic Co-Wave v2 Acceptance Ledger (frozen 2026-08-28) ──────────────
# Records baseline metric values observed on the Insulin_Signaling_Dynamic_V1
# dataset with commit 8fc58701f6457230dd1203087075e0df1b41c987.
#
# WHY A SEPARATE LEDGER (not reusing v1 thresholds):
#   v1 mixed inert site_observations into the event set; v2 records them as
#   exposure only.  Jaccard denominator/numerator therefore differ, so v1 site
#   LOTO (0.722222) must not be used as a v2 pass/fail criterion.  Re-baseline
#   on v2's non-inert event universe (site LOTO = 0.716677).
#
# Pre-registration: 2026-08-28.  These values must not be revised after the
#   inhibitor study is started.  They define "not worse than insulin-only v2".
#
# Source: strict truth-free benchmark re-run report
#   "최신_strict_truth_free_benchmark_재실행_비교_보고서.pdf", §3, 2026-08-28.
DYNAMIC_COWAVE_V2_BASELINE: dict[str, object] = {
    # ── pair-level metrics (event universe identical to v1) ────────────────
    "pair_loto_jaccard": 0.710171,
    "pair_transition_count": 105538,
    "active_pair_coverage": 0.300183,
    "transition_resolution": 0.751938,
    "transition_supported_wave_count": 8,

    # ── site-level metrics (v2 non-inert event universe ONLY) ─────────────
    "site_loto_jaccard_v2_noninert": 0.716677,
    "noninert_site_transition_count": 2695,
    "inert_site_observation_count": 641,

    # ── acceptance thresholds for regression detection ─────────────────────
    # Any metric falling below its threshold → flag as regression.
    # Thresholds are set at 97% of baseline (1σ buffer against sampling noise).
    "min_pair_loto_jaccard": 0.689,        # 97% of 0.710171
    "min_site_loto_jaccard_v2_noninert": 0.695,   # 97% of 0.716677
    "min_active_pair_coverage": 0.291,     # 97% of 0.300183
    "min_transition_resolution": 0.729,    # 97% of 0.751938
    "min_transition_supported_wave_count": 8,

    # ── meta ───────────────────────────────────────────────────────────────
    "dataset": "Insulin_Signaling_Dynamic_V1",
    "commit": "8fc58701f6457230dd1203087075e0df1b41c987",
    "frozen_date": "2026-08-28",
    "v1_site_loto_jaccard_for_reference_only": 0.722222,
    "note": (
        "v1 site LOTO 0.722222 is listed for reference only. "
        "Do NOT use v1 site LOTO as v2 acceptance criterion: v1 included inert "
        "state_unchanged_or_inactive events in its Jaccard denominator while v2 "
        "records them as exposure.  The event universe differs."
    ),
}


def check_dynamic_cowave_v2_regression(
    result: Mapping[str, object],
) -> dict[str, object]:
    """Check a Dynamic Co-Wave v2 result against the frozen v2 acceptance ledger.

    Implementation target: P1-B acceptance criterion re-definition (2026-08-28).
    Pre-registration: thresholds from DYNAMIC_COWAVE_V2_BASELINE are frozen.
    Interpretation limits: detects metric regression vs. insulin-only baseline;
      does not validate against any new dataset.
    Claim boundary: passing all thresholds means noninferiority, not improvement.

    Returns
    -------
    dict with keys:
      passed       bool   — True if all thresholds met
      failures     list   — threshold names that failed
      warnings     list   — non-threshold observations
      values       dict   — measured values vs. baseline
    """
    B = DYNAMIC_COWAVE_V2_BASELINE
    summary = result.get("summary") or {}
    loto = result.get("lotto") or result.get("loto") or {}
    failures: list[str] = []
    warnings: list[str] = []
    values: dict[str, object] = {}

    def _check(name: str, measured: float | None, threshold: float, baseline: float) -> None:
        values[name] = {"measured": measured, "baseline": baseline, "threshold": threshold}
        if measured is None:
            warnings.append(f"{name}: not computed (None)")
        elif measured < threshold:
            failures.append(
                f"{name}: {measured:.6f} < threshold {threshold:.6f} "
                f"(baseline {baseline:.6f})"
            )

    _check(
        "pair_loto_jaccard",
        loto.get("mean_pair_transition_jaccard"),
        float(B["min_pair_loto_jaccard"]),
        float(B["pair_loto_jaccard"]),
    )
    _check(
        "site_loto_jaccard_v2_noninert",
        loto.get("mean_site_transition_jaccard"),
        float(B["min_site_loto_jaccard_v2_noninert"]),
        float(B["site_loto_jaccard_v2_noninert"]),
    )
    _check(
        "active_pair_coverage",
        summary.get("local_active_pair_coverage"),
        float(B["min_active_pair_coverage"]),
        float(B["active_pair_coverage"]),
    )
    _check(
        "transition_resolution",
        summary.get("transition_resolution"),
        float(B["min_transition_resolution"]),
        float(B["transition_resolution"]),
    )
    wave_count = summary.get("transition_supported_wave_count")
    min_w = int(B["min_transition_supported_wave_count"])
    values["transition_supported_wave_count"] = {
        "measured": wave_count, "baseline": B["transition_supported_wave_count"], "threshold": min_w,
    }
    if wave_count is not None and wave_count < min_w:
        failures.append(
            f"transition_supported_wave_count: {wave_count} < threshold {min_w}"
        )

    return {
        "passed": len(failures) == 0,
        "failures": failures,
        "warnings": warnings,
        "values": values,
        "ledger_frozen_date": B["frozen_date"],
        "ledger_commit": B["commit"],
    }


if __name__ == "__main__":
    print(json.dumps(provenance(), ensure_ascii=False, indent=2))
