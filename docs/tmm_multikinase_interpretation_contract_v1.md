# TMM-Aware Multi-Kinase Interpretation Contract v1

## Purpose

This contract strengthens the interpretation of substrate co-waves in which several kinase modules can be active at the same time. It preserves raw kinase-module overlap while adding a separate condition-specific, contribution-weighted interpretation. Neither representation alone is a causal network.

```text
Raw overlap                     → candidate/module membership evidence
TMM-weighted activity           → condition-specific fractional attribution
Kinase-pair temporal precedence → observed profile timing evidence
Post-analysis perturbation      → optional independent validation evidence
```

## 1. Co-Wave Provenance

The heatmap response now stores all three fields below.

| Field | Meaning | Appropriate use |
|---|---|---|
| `raw_cowave_groups` | kinase profile groups calculated before TMM weighting | inspect candidate/module overlap structure |
| `tmm_weighted_cowave_groups` | groups recalculated from TMM-weighted signed kinase profiles | primary condition-specific co-activation interpretation |
| `cowave_groups` | primary group view; TMM-weighted when available, raw only as fallback | backwards-compatible default UI/report input |

Each group includes `score_provenance` equal to `raw_pre_tmm` or `tmm_weighted`. A same-time multi-kinase group is a co-activation/common-context candidate. It is not evidence that one kinase directly phosphorylates every member substrate.

## 2. TMM Evidence Profile

Each kinase score now includes `tmm_evidence`.

| Confidence tier | Condition | Interpretation boundary |
|---|---|---|
| `tmm_data_anchored` | data-driven profile with at least three exclusive substrates | direct Order-derived temporal anchor |
| `tmm_sparse_data_anchored` | data-driven profile but limited anchor support | retain contribution, interpret cautiously |
| `tmm_prior_assisted` | Gaussian/expected-peak fallback | prior-assisted rescue; not data-anchored evidence |
| `tmm_insufficient_profile` | no usable profile | no substantive TMM attribution claim |

`profile_type`, `n_exclusive`, `n_shared`, `confidence_flags`, and an explicit interpretation boundary are retained. Reports must not describe `tmm_prior_assisted` output as a measured temporal kinase profile.

## 3. Contribution-Weighted Cascade

`tmm_weighted_temporal_cascade` is generated from each kinase's signed TMM-weighted up/down sums. The default activity threshold is the existing heatmap directional threshold (`|activity| >= 0.30`); it is recorded in output rather than silently changing legacy behavior.

```text
timepoints[].active_kinases[]
  ├── kinase / canonical
  ├── tmm_weighted_activity
  ├── tmm_weighted_substrate_support
  ├── direction
  └── tmm_evidence

cascade_flow[]
  ├── persistent_kinases
  ├── new_kinases
  └── lost_kinases
```

This cascade is stored beside the legacy raw-overlap cascade under:

```text
global_kinase_modules.temporal_cascade.tmm_weighted
```

The raw cascade remains unchanged for backwards compatibility and candidate-set review. The TMM cascade should be used for condition-specific fractional activity interpretation.

## 4. Kinase-Pair Temporal Precedence

The top TMM-weighted kinase profiles are evaluated pairwise using the shared `DirectedTemporalRelationship` engine. Each record contains minute-normalized onset/peak lag, lag-aware similarity, bootstrap/permutation availability, D-tier, quality flags, and `causality_status=not_tested`.

```text
tmm_kinase_pair_directionality[]
  ├── source_type: tmm_weighted_kinase_profile
  ├── source / target
  ├── directionality_tier: D0–D3
  ├── onset_lag_minutes / peak_lag_minutes
  └── causality_status: not_tested
```

Because TMM kinase profile pairs generally lack replicate-level kinase profiles and no biological support is injected by default, they normally remain D0/D1. They must never be translated into direct kinase-to-kinase causal claims.

## 5. Report and Data-Grounded Analysis

The kinase annotation context now includes a separate TMM-weighted activity section and TMM kinase-profile precedence section. The Data-Grounded hypothesis context receives both raw temporal cascade and TMM-weighted cascade, together with an explicit rule:

> Raw co-wave membership and TMM-weighted activity are separate evidence layers. Kinase-pair timing is observational and does not establish direct causality.

This gives report generation enough context to distinguish concurrent multi-kinase activation, shared substrate ambiguity, persistence/handoff, and sparse-profile limitations.

## 6. Regression Coverage

`workers/tests/test_tmm_multikinase_integration.py` verifies:

1. Gaussian fallback is explicitly classified as `tmm_prior_assisted`.
2. TMM-weighted cascade retains fractional activity independently of raw membership.
3. TMM co-wave groups preserve provenance.
4. Kinase-profile directionality always retains `causality_status=not_tested`.

## 7. Remaining Next Steps

The current contract establishes the structural distinction required for reliable multi-kinase interpretation. Future work should add TMM residual, candidate-profile condition number, contribution entropy, and bootstrap contribution confidence intervals. These additions will quantify profile identifiability rather than only flagging sparse anchors.
