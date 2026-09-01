# PTM-Vector P3 Many-to-Many Candidate Allocation Contract

## Purpose and claim ceiling

P3 is deterministic **candidate-set bookkeeping**, not a model of kinase
occupancy, kinase activity, kinase probability, direct regulation, causality
or perturbation response. It consumes only P2 `R3_exact_curated_candidate_set_pending_p3`
records that already passed the P0/P1/P2 provenance gates. It never changes
Static Wave membership, Dynamic Co-Wave events, TMM, temporal precedence,
strict benchmark scoring, or the underlying P2 candidate set.

The output answers only this narrow accounting question: *if one observed,
exactly evidenced feature has N equally retained direct-relation candidates,
how can its unit evidence be represented without counting it N times or
selecting a single candidate?*

## Allocation unit and deterministic conservation rule

Each full-ledger feature record `f` is eligible only if its relation evidence
class is `R3` and it contains at least one valid P2 candidate edge. Let the
canonical, deduplicated candidate set be `C(f)`. Candidate identity is the
complete P2 edge identity: source bundle ID, kinase accession/taxon,
substrate accession/taxon, residue, position, source identity scope,
substrate identity token and edge ID. An R3 record with duplicate candidate
kinase identities is invalid for P3 and remains no-call rather than being
silently deduplicated or ranked.

P3 assigns a unit feature evidence mass and divides it equally across the
preserved candidates:

```text
feature_mass(f) = 1
candidate_mass(f, c) = 1 / |C(f)|, for every c in C(f)
sum(c in C(f)) candidate_mass(f, c) = 1
```

This equal split is an explicit **symmetry convention under unresolved
candidate ambiguity**, not a posterior kinase probability or an experimental
effect size. The candidate list is canonically sorted before serialization;
input row order cannot change masses or summaries.

## Uncertainty and aggregation

P3 reports candidate multiplicity `N`, effective candidate count `N`, and
allocation entropy `ln(N)` nats for each eligible feature. An R3 feature with
one exact curated candidate has zero *candidate-set ambiguity entropy*, but
it remains direct `no_call`: source-site evidence alone does not prove that
candidate acted in the sample.

The full ledger may retain each allocated candidate edge and its fractional
mass. The compact Report/RAG/LLM projection may contain only aggregate
quantities: eligible feature count, total conserved feature mass, total
allocated mass, candidate-count histogram, mean/maximum candidate ambiguity
entropy, allocation contract version and a fixed claim boundary. It must not
contain candidate kinase names, accessions, sites, peptides, edge IDs,
relation-source labels, PMIDs, weights by named kinase or source file paths.

`mass_conservation_status = passed` is valid only when at least one R3 feature
has an actual P3 allocation and the observed allocated total matches the
eligible feature-mass total. When no feature is eligible, both totals are zero
but the status is explicitly `not_evaluable_or_no_candidate_set`, not
`passed`. Zero R3 records therefore do not diagnose a failed P2 installation.

No aggregate is a kinase ranking. In particular, a summed fractional mass by
kinase remains full-ledger-only accounting for a later, explicitly governed
P3/P4 analytical view; it must not enter compact Report/RAG/LLM packets.

## State transitions and non-promotion rules

| Input relation state | P3 status | Direct kinase status |
| --- | --- | --- |
| P2 R0/R1/R2/R4 | `not_evaluable_or_no_candidate_set` | `no_call` |
| P2 R3, nonempty unique candidate set | `fractional_candidate_set_allocation_pending_interpretation` | `no_call` |
| P2 R3 with missing/malformed/duplicate candidate identity | `invalid_candidate_set_no_allocation` | `no_call` |
| M0/M2/M3/M4 or non-P0-ready upstream feature | Not eligible because it cannot validly reach R3 | `no_call` |

P3 must not produce a primary kinase, a probability label, an activation
direction, a temporal causal edge, an intervention recommendation or a
mechanistic sentence. P4 is the earliest layer that may evaluate matched
perturbation evidence, and even P4 must retain P3 candidate ambiguity rather
than overwrite it.

## Implementation and cache contract

The implementation should be a pure local module,
`ptm_shared/kinase_candidate_allocation.py`. It must not import network
clients, external databases, benchmark truth/workbook, locked scores, known
relation registries, treatment identity, TMM priors, RAG code or LLM code.
It attaches `allocation_evidence` only to the persisted full feature ledger.

The ledger contract must be incremented and the temporal-sidecar freshness
rule must reject older compact/full sidecars. P3 may reuse the already
validated P2 manifest hash as provenance, but it has no live source or
environment fallback. Missing P2 configuration continues to yield R0 and no
P3 allocation.

## Acceptance tests

The implementation test suite must demonstrate all of the following.

1. One R3 feature with one candidate receives mass 1.0 and entropy 0.0 while
   direct kinase attribution remains `no_call`.
2. One R3 feature with N candidates receives exactly N allocations of `1/N`,
   with total mass 1.0, deterministic candidate order and no named-kinase
   compact projection.
3. Multi-feature aggregation conserves total mass exactly and remains
   invariant to feature/candidate input order.
4. R0/R1/R2/R4, missing candidates, duplicate candidate identities and
   non-R3 mapping contexts receive no allocation and no promotion.
5. P3 cannot access benchmark truth, locked scorer, known anchors/relations,
   RAG/LLM output or external network clients; Report/RAG cannot access the
   full allocation ledger.
6. Existing Wave, Dynamic Co-Wave, TMM, temporal precedence, cache and
   Report-side sidecar tests retain their behavior apart from intentional
   v5 freshness refresh.
