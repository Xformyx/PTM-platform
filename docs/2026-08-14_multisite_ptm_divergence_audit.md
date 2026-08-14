# Multisite PTM Divergence: Current-Code Audit and Scientific Interpretation

**Scope.** This assessment traces the current PTM-platform implementation from
divergence-pair generation through receptor inference, temporal report writing, and
frontend rendering. It distinguishes measured observations from mechanism-level
interpretation and recommends changes that preserve the value of site-resolved
time-course phosphoproteomics.

## Executive conclusion

Multisite PTM divergence is one of PTM-platform's most valuable data products. Two
sites on one protein may encode different temporal programs, kinase preferences,
domains, binding interactions, or functional states. The current platform already
computes and exposes this information in several high-value paths. In particular, it
uses same-protein site timing to enrich receptor ranking and to provide site-specific
motif, kinase, pathway, domain, and co-wave context to the report LLM.

The central limitation is that the platform currently has **two related but not
identical divergence implementations**: an API-side `TemporalDivergencePair` path and
a report-side recomputation. Both classify patterns from peak time and signed log2FC,
then attach mechanism-like labels. This makes divergence a strong exploratory signal,
but not yet a unified, statistically calibrated site-regulation evidence layer.

## What the current code computes

### Entry condition and site-pair construction

Both implementations group PTMs by gene/protein and consider all site pairs where at
least one site is `regulated` or `de_novo`. A protein therefore needs at least two
measured sites and the experiment needs at least three ordered timepoints.

For every site, the code retains the full log2FC vector, absolute-maximum peak,
peak condition, peak index, activity class, and de novo status. The pair is ordered by
peak index and receives one of three operational labels.

| Current pattern label | Current rule | Safe observational meaning |
|---|---|---|
| `multisite_coordination` | both sites have the same absolute-maximum peak index | same-peak site coordination candidate |
| `sequential_regulation` | different peak indices with the same peak sign | temporally separated same-direction site response |
| `signal_attenuation` | different peak indices with opposite peak signs | temporally separated opposite-direction site response |

The report path additionally records real-time lag when labels can be parsed to
minutes, a MAD-normalized effect size, a high/medium/low confidence tier, a warning
for three or fewer timepoints, cluster co-membership, motif-family overlap, and
known kinase-substrate overlap.

## Where divergence is used today

### 1. Receptor inference and ranking

The API-side `compute_divergence_pairs()` is called inside the receptor inference
endpoint. It produces two effects.

First, de novo sites in a divergence pair can receive an activity-weight increase
from 0.3 to 0.5–0.7. Second, receptor candidates receive a `temporal_cascade_score`
from divergence patterns. The score contributes 15% of the combined receptor
confidence score. It is increased by motif matches, sequential pairs, opposite-sign
pairs, shared pathways, and same-peak multisite coordination. Low-tier pairs are
excluded and non-significant report-style pairs would be discounted when present.

The result is persisted in `order.receptor_inference_data` as `divergence_pairs` and
returned by the vector-data API. The frontend uses this for the divergence view.

### 2. Report and LLM context

`temporal_comovement_node.py` recomputes divergence from the significant PTM matrix
for report writing. It builds a dedicated **Multi-site Temporal Divergence Analysis**
section and provides up to 15 pairs to the LLM.

For each pair, it cross-references:

| Context layer | Current source |
|---|---|
| temporal profile and peak lag | significant PTM matrix |
| co-wave membership | canonical temporal cluster mapping |
| predicted kinase candidates | cluster shared kinase annotation |
| motif and flanking sequence | enriched PTM data |
| known kinase-substrate and upstream regulation | RAG enrichment |
| shared and site-specific pathways | RAG / Reactome context |
| domain localization | unified enrichment |
| PTM–non-PTM neighborhood | cluster linkage context |

This is a major strength: divergence is not shown as an isolated two-site chart. It
is presented as an intra-protein observation connected to Wave membership, kinase
candidates, domain biology, and literature context.

### 3. Frontend visualization

`OrderDetail.tsx` independently derives and displays the three divergence classes.
This gives users a site-level view that is complementary to protein-level pathways
and kinase modules.

## What divergence does *not* currently drive

Divergence does not directly enter canonical Wave clustering, TMM contribution
deconvolution, or TMM-weighted kinase activity. It indirectly affects receptor
ranking but does not ask whether site A and site B have **different TMM kinase
contribution distributions**. This is the most promising missing link.

The current `DirectedTemporalRelationship` engine is also not applied directly to
site A versus site B. Consequently, the divergence layer records peak order but not
the same bootstrap confidence interval, time-order permutation, or D0–D3 evidence
tier now available to other temporal relationships.

## Scientific significance

Multisite phosphorylation can implement graded responses, thresholds, timing delays,
signal integration, and functional switches on one protein; the order and kinetics of
individual sites are biologically consequential rather than redundant.[1] [2]
Large-scale time-resolved phosphoproteomics has likewise shown that individual sites
within signaling networks can exhibit distinct temporal dynamics following a common
stimulus.[3]

For PTM-platform, the strongest academic contribution is not merely identifying that a
protein has more than one regulated site. It is the ability to formulate the following
testable observation:

> **Within the same protein, site-specific PTM trajectories separate into distinct
> temporal programs and candidate upstream kinase contexts; this may indicate
> functionally differentiated regulatory states under the measured condition.**

This makes divergence valuable for proteins such as receptors, adapters, scaffold
proteins, transcription factors, and kinases, where different domains/sites often
govern localization, binding, stability, activation, or feedback.

## Interpretation boundary

The current labels should remain explicitly exploratory.

| Current tempting wording | Why it is too strong | Preferred wording |
|---|---|---|
| “one kinase performs processive multisite phosphorylation” | same peak does not identify the kinase or prove processivity | “same-peak coordination is consistent with co-regulation or a shared signaling complex” |
| “activation site followed by inhibitory site” | positive/negative log2FC is not a functional activating/inhibitory annotation | “opposite-direction site response” |
| “negative feedback loop” | opposite site signs and lag do not prove a feedback edge | “feedback-compatible site pattern” |
| “two independent kinases” | differing peak times alone do not identify two kinases | “temporally separated site regulation with distinct kinase-context candidates” |
| “same cluster confirms same kinase” | correlation and shared Wave are not direct kinase evidence | “same Wave supports coordinated temporal regulation” |

The report-side permutation p-value currently permutes pooled values between the two
sites. It measures a broad profile difference, but it is **not a temporal-order
permutation test** and should not be described as proof that the observed lag is
significant. The current time-resolution warning is useful but should be extended to
all mechanism-facing claims.

## Priority upgrade roadmap

### D0 — One shared divergence contract

Move the divergence computation to `ptm_shared`, then make API, report worker, and
frontend consume one versioned result. Persist a stable pair identifier, source
timepoint list, minutes axis, input PTM IDs, configuration hash, and algorithm
version. This eliminates the current API/report/frontend drift.

### D1 — Observation-first pattern names and site-pair directionality

Rename the three classes to `same_peak_coordination`,
`temporally_separated_same_direction`, and
`temporally_separated_opposite_direction`. Then pass each pair through
`DirectedTemporalRelationship` to obtain onset/peak lag, lag-aware similarity,
bootstrap interval, leave-one-timepoint-out stability, time-order permutation, and
D0–D3 directionality tier.

### D2 — Divergence–TMM integration

For each site in a pair, retain the TMM contribution vector across candidate kinases.
Compute a site-pair kinase-attribution distance and mark:

```text
same temporal program + similar TMM attribution
same temporal program + divergent TMM attribution
different temporal program + shared TMM attribution
different temporal program + divergent TMM attribution
```

This is a distinct PTM-platform contribution. It distinguishes two sites that peak at
the same time but may be explained by different kinase mixtures, from two sites that
peak at different times despite shared kinase contribution.

### D3 — Statistical and functional calibration

Use replicate-aware pair profiles where available, perform a time-order null rather
than pooled-value permutation for lag claims, correct across tested site pairs, and
separate signal magnitude from functional annotation. Functional “activation” or
“inhibition” labels should only be added when a site-specific curated annotation or
validated literature record exists.

### D4 — Evidence-aware receptor use

Do not let exploratory divergence patterns strongly increase receptor confidence by
default. Receptor ranking should consume only pairs that meet a documented evidence
threshold: adequate time resolution, non-low effect tier, directionality support,
and relevant kinase/receptor context. Keep the original divergence result visible even
when it does not qualify for receptor scoring.

## Recommended report structure

Report the findings in three layers:

1. **Observation:** measured site-specific trajectories, peak times, amplitudes, and
   Wave membership.
2. **Interpretation:** TMM kinase-attribution concordance/divergence, motifs, domains,
   curated kinase-substrate records, pathway and literature context.
3. **Validation proposal:** only after analysis, recommend targeted site assays,
   domain/function tests, or perturbation experiments for high-priority pairs.

This preserves the discovery value of multisite divergence without presenting an
observational pattern as a confirmed molecular mechanism.

## Code locations audited

| Purpose | Current location |
|---|---|
| API divergence computation and receptor weighting | `api-server/app/api/orders.py` |
| Shared API divergence object and AI summary | `api-server/app/core/biological_relationship.py` |
| Report divergence recomputation and LLM context | `workers/report_generation/core/nodes/temporal_comovement_node.py` |
| User-facing divergence visualization | `frontend/src/pages/OrderDetail.tsx` |

## References

[1] [Salazar C, Höfer T. Multisite protein phosphorylation—from molecular
mechanisms to kinetic models. *FEBS Journal*. 2009.](https://doi.org/10.1111/j.1742-4658.2009.07027.x)

[2] [Ventura AC, et al. Multisite phosphorylation provides an effective and
flexible mechanism for switch-like protein degradation. *PNAS*. 2010.](https://pmc.ncbi.nlm.nih.gov/articles/PMC3001445/)

[3] [Olsen JV, et al. Global, in vivo, and site-specific phosphorylation
dynamics in signaling networks. *Cell*. 2006.](https://pubmed.ncbi.nlm.nih.gov/17081983/)
