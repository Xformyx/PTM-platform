# PTM-Vector P5 Candidate Discovery Packet Contract

## Purpose

P5 turns already measured, named PTM trajectories into **transparent discovery candidates** for Gemini and Order-scoped RAG. It does not infer a direct kinase–site edge, a kinase activity probability, a causal edge, or a perturbation outcome. P0–P3 provenance remains separate: a direct kinase claim is allowed only through its own evidence chain, never through P5 score, literature prose, motif, Wave or candidate membership.

## Candidate universe and exclusions

The input universe is `vector_plot_raw_data` restricted to named gene-site rows with a finite PTM-relative log2FC at one or more declared conditions. `unknown`/missing gene labels, synthetic gene/site identities, benchmark truth/workbook fields, locked scores, treatment-specific priors, P2 candidate identities, P3 allocated candidate mass and RAG/LLM output are excluded.

Each named gene-site candidate receives exactly one primary bucket, using deterministic precedence:

1. `multi_site_divergent` if the computed canonical multisite evidence identifies the gene-site as divergent.
2. `ptm_protein_decoupled` if its measured PTM–protein contrast is finite and reaches the declared contrast threshold.
3. `annotation_negative_discovery` if no known curated kinase anchor or motif-context annotation is attached to that observed site.
4. `canonical_context_anchor` otherwise.

The bucket describes a discovery rationale, not biological importance, novelty in all literature, or a direct kinase assignment.

## Transparent selection components

Eligible candidates must have a finite multi-condition PTM trajectory whenever the Order has more than one condition. Selection ranks a lexicographic, fully reported component vector rather than a hidden probability:

| Component | Definition | Role |
|---|---|---|
| finite-condition count | count of finite measured PTM-relative log2FC values | minimum observability and first ranking component |
| maximum absolute PTM magnitude | maximum finite `abs(PTM_Relative_Log2FC)` | observed effect scale |
| q-value coverage | count of finite q-values; best finite q-value if present | precision context, never imputed |
| maximum PTM–protein contrast | maximum finite `abs(PTM_Relative_Log2FC - Protein_Log2FC)` | layer-decoupling context |
| temporal context count | number of computed Wave/Dynamic/recurrence labels attached to the site | descriptive temporal support only |
| multisite divergence flag | computed evidence flag | within-gene regulation heterogeneity context |

No component is a kinase probability or p-value. Missing values remain `not_recorded` and cannot be synthetically supplied.

## Capacity and quota policy

The default Report candidate capacity is 20 cards. Candidate selection reserves up to 6 `canonical_context_anchor`, up to 10 `annotation_negative_discovery`, and up to 4 combined `multi_site_divergent`/`ptm_protein_decoupled` cards. Any unused quota is backfilled by remaining eligible cards in deterministic global order. The output records requested quota, selected count and backfill count per bucket.

This policy prevents high-amplitude canonical candidates from occupying all Report and RAG attention. It does not force a weak discovery candidate into the packet: a bucket with no eligible row remains empty.

## LLM-facing card boundary

Each card may expose only Report-eligible observation fields: gene/site label, condition-level PTM-relative and protein log2FC, q-value coverage/best q, observed temporal profile and peak, bucket, component vector, stated novelty rationale, pathway context and computed Wave/Dynamic/multisite descriptors. P0–P3 aggregate readiness may be included separately. Full feature ledger identity, protein accession, peptide/sequence, coordinate provenance, P2 candidate kinase identity, P3 allocation detail, raw precursor ID and benchmark truth remain excluded.

Gemini must write each discovery discussion as: **measured trajectory → data-derived discovery rationale → literature agreement/disagreement or unresolved status → system-specific biological model → discriminating next measurement**. The card must be called a data-prioritized candidate, not a confirmed novel substrate or direct kinase target.

## RAG query policy

RAG receives two dedicated bounded roles: `canonical_anchor_biology` and `discovery_candidate_biology`. It preserves query role, selected bucket and candidate anchor in retrieval telemetry. The default candidate query capacity reserves 3 slots for canonical anchors and 5 for discovery/divergent/decoupled cards, with deterministic backfill when a bucket is empty. Query text is built only from active Order context, gene/site label when available, PTM type and descriptive measured profile; it must not add a presumed kinase, pathway, treatment prior or external data.

## Acceptance criteria

P5 is accepted only if tests demonstrate: canonical crowding cannot erase an eligible annotation-negative candidate; candidate order is deterministic; all cards report their selection components; missing q-values are explicit; multi-site and decoupled buckets preserve their measured rationale; non-insulin contexts receive no insulin leakage; RAG has canonical/discovery role quotas and telemetry; and no P5 output can create a direct kinase, causal or perturbation-supported assertion.
