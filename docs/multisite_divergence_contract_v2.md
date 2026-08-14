# Canonical Multisite PTM Divergence Contract v2

**Status:** Implemented in the shared `ptm_shared.multisite_divergence` package.

## Purpose

This contract identifies **observed time-resolved differences among PTM sites on
the same protein**. It deliberately separates measured site patterns from
kinase assignment and causal interpretation.

> A multisite divergence pair is a site-specific temporal observation. It does
> not prove one kinase, processive phosphorylation, activation/inhibition,
> feedback, a signaling cascade, or causality.

## Canonical patterns

| Canonical pattern | Legacy label | Meaning |
|---|---|---|
| `same_peak_coordination` | `multisite_coordination` | Two sites reach their maximal absolute response at the same measured timepoint. |
| `temporally_separated_same_direction` | `sequential_regulation` | Two sites peak at different timepoints with the same observed sign. |
| `temporally_separated_opposite_direction` | `signal_attenuation` | Two sites peak at different timepoints with opposite observed signs. |

The legacy labels remain in `legacy_pattern` for backwards-compatible API
consumers only. New report, frontend, and AI wording must use the canonical
observation-first labels.

## Required evidence fields

Each `TemporalDivergencePair` records the following layers independently.

| Layer | Field(s) | Interpretation boundary |
|---|---|---|
| Observed trajectory | `peak_condA/B`, `fcA/B`, `temporal_lag`, `pattern` | Measured pattern only. |
| Directionality | `directionality`, `directionality_tier` | Temporal precedence is observational and `causality_status=not_tested`. |
| Effect / resolution | `effect_size`, `confidence_tier`, `resolution_warning` | Guards against weak amplitude or sparse time axes. |
| Statistical order support | `fdr_q_value` | BH-adjusted time-order permutation evidence. |
| TMM attribution | `tmm_contribution_divergence` | Condition-specific kinase-mixture comparison, not true occupancy. |
| Eligibility | `evidence_eligible_for_ai`, `evidence_eligible_for_receptor`, `evidence_gate_reasons` | Controls downstream consumption. |

## TMM contribution divergence

For a same-protein site pair, each per-site kinase contribution vector is
normalized and compared using total-variation distance.

| Distance | Classification |
|---:|---|
| `≤ 0.25` | `concordant_kinase_mixture` |
| `0.25–0.50` | `partially_divergent_kinase_mixture` |
| `≥ 0.50` | `divergent_kinase_mixture` |

This supports a hypothesis such as “the two sites have distinct
condition-specific candidate kinase mixtures.” It does **not** identify a
true direct kinase–substrate relationship.

## Evidence gates

### Data-Grounded Analysis / report discussion

A pair is `evidence_eligible_for_ai` only when all of the following hold:

1. Confidence tier is not `Low`.
2. The time axis is not flagged as low resolution.
3. Directionality is not `D0_unresolved`.
4. Time-order permutation survives BH correction (`FDR ≤ 0.05`).

### Receptor inference

`evidence_eligible_for_receptor` additionally requires D2/D3 directionality
and either shared pathway context or a shared curated kinase–substrate
candidate. Receptor scoring uses only contextual agreement and optional TMM
mixture divergence. It does not reward inferred feedback loops or cascade
depth from observational site patterns.

## Consumers

| Consumer | Use |
|---|---|
| Vector-data API | Produces canonical pairs for the order-level frontend panel and persists them with receptor inference. |
| Frontend multisite panel | Uses canonical API records when available; legacy client calculation is a cache-compatible fallback with observation-first language. |
| Report temporal co-movement node | Delegates pair generation to the shared contract and retains a legacy-compatible rendering shape. |
| Data-Grounded Analysis | Recomputes only AI-eligible pairs before hypothesis generation because this stage precedes report temporal co-movement in the graph. |
| Receptor inference | Uses only receptor-eligible pairs; default divergence contribution is zero when evidence is insufficient. |

## Validation wording

Use: **“observed site-specific temporal pattern,” “temporally precedes,”
“condition-specific candidate kinase mixture,”** and **“warrants post-analysis
validation.”**

Do not use: **“causes,” “feedback loop,” “signal attenuation mechanism,”
“directly activates,” “single kinase confirmation,”** or **“proves.”**

Only separately uploaded and evaluated intervention data may support a later
`perturbation_supported` status.
