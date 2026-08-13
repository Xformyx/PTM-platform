# Directed Temporal Relationship Contract v1

## Purpose

This contract records **observational temporal directionality** between PTM sites, Temporal Waves, or PTM-to-effector relationships. It deliberately separates temporal precedence from causality so unbiased discovery time-course proteomics remains independent of any later intervention experiment.

> A positive time lag means that the target changed later than the source. It does **not** mean that the source caused the target to change.

## Directionality Output

`ptm_shared/directed_temporal_relationship.py` returns the following key fields.

| Field | Meaning |
|---|---|
| `direction` | `source_precedes_target`, `target_precedes_source`, `simultaneous`, or `unresolved` |
| `onset_lag_minutes` | Target onset minute minus source onset minute |
| `peak_lag_minutes` | Target peak minute minus source peak minute |
| `lag_aware_similarity` | Best physical time-shifted profile similarity and zero-lag comparator |
| `evidence_profile.bootstrap` | Replicate bootstrap stability and 95% peak-lag interval, if replicate values exist |
| `evidence_profile.leave_one_timepoint` | Stability after omitting each timepoint, where evaluable |
| `evidence_profile.time_permutation` | Empirical null test for time-order information |
| `evidence_profile.threshold_sensitivity` | Direction result across configured onset thresholds |
| `causality_status` | `not_tested` by default; never inferred from a trajectory |

Time labels are normalized to minutes for `min`, `h`/`hr`/`hour`, and `d`/`day` labels. Unparseable labels, fewer than three timepoints, or missing quantitative values yield `D0_unresolved` rather than an inferred direction.

## D-Tier Interpretation

| Tier | Requirement | Permitted interpretation |
|---|---|---|
| `D0_unresolved` | Insufficient, conflicting, simultaneous, or non-evaluable timing | No directionality claim |
| `D1_temporal_precedence` | Observed source/target temporal order | `temporally precedes` |
| `D2_reproducible_directionality` | D1 plus replicate bootstrap stability ≥0.70 and available time-permutation support at `p≤0.05`; leave-one-timepoint stability must not fail | `reproducibly precedes` |
| `D3_mechanistically_supported_directionality` | D2 plus a separated kinase–substrate, motif, PPI, or ChromaDB support flag | `temporally and mechanistically consistent with a candidate regulatory path` |

No D-tier is a causal tier. The Report, Data-Grounded Analysis, and external Co-Scientist writer contexts must not convert D0–D3 evidence to `causes`, `drives`, `proves`, or `directly activates` language.

## Pipeline Placement

```text
Unbiased time-course PTM data
  → Canonical Temporal Wave detection
  → DirectedTemporalRelationship evidence (D0–D3)
  → Report / Data-Grounded Analysis / Co-Scientist interpretation guardrails
  → D2/D3-only post-analysis validation recommendations
  → optional user-uploaded perturbation evidence evaluation
```

The optional final step does not alter original Wave membership, kinase scoring, TMM contribution, or discovery results.

## Post-Analysis Validation Recommendation

`ptm_shared/causal_validation.py` selects only `source_precedes_target` records with D2 or D3 evidence and `causality_status=not_tested`. It produces a bounded recommendation containing:

1. an orthogonal targeted assay;
2. an optional independently justified intervention design;
3. observed onset/peak time windows;
4. a preregistered decision rule; and
5. matched-control requirements.

The recommendation is rendered in **Post-Analysis Causal Validation Recommendations** after the general Report validation section. It is not placed in Results and does not retrospectively influence unbiased discovery.

## Optional Perturbation Evidence Upload

The Order Detail Signal Propagation Timeline provides an optional CSV/TSV upload control once signal-propagation data exist. The endpoint is:

```text
POST /api/orders/{order_id}/perturbation-evidence
```

The file must be UTF-8 CSV/TSV and contain all columns below.

| Column | Meaning |
|---|---|
| `source` | Exact discovery source key |
| `target` | Exact discovery target key |
| `control_mean` | Mean outcome in matched control |
| `perturbed_mean` | Mean outcome in the uploaded intervention condition |
| `expected_target_change` | Prespecified `up` or `down` outcome |
| `q_value` | Multiple-testing-aware significance value for the tested target |

Only rows matching an already observed `source_precedes_target` relationship are evaluated. At the configured `alpha` default of 0.05, a row receives `perturbation_supported` only when its observed delta has the prespecified direction and `q_value ≤ alpha`; otherwise it receives `perturbation_not_supported`. A result applies only to the uploaded condition.

## Files

| File | Role |
|---|---|
| `ptm_shared/directed_temporal_relationship.py` | Directionality contract and stability diagnostics |
| `ptm_shared/temporal_wave_engine.py` | Canonical Wave output plus pairwise Wave directionality records |
| `ptm_shared/causal_validation.py` | D2/D3 recommendation and upload-evidence evaluator |
| `workers/report_generation/core/temporal_analysis.py` | PTM/protein and PPI timeline integration |
| `workers/report_generation/core/nodes/writer_node.py` | Evidence-aware Report and Data-Grounded context injection |
| `workers/report_generation/core/nodes/editor_node.py` | Dedicated report appendices |
| `api-server/app/api/orders.py` | Order-scoped perturbation upload and read endpoints |
| `frontend/src/components/SignalPropagationTimeline.tsx` | Evidence-aware timeline labels and optional upload UI |
