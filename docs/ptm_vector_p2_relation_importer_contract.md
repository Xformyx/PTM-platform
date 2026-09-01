# PTM-Vector P2: Curated Kinase–Substrate Relation Evidence Importer Contract

## Scope

P2 consumes a separately acquired, license-recorded, immutable **local**
kinase–substrate relation bundle. It does not query a source API at Order
runtime, create a kinase activity score, infer causality, alter Wave/Dynamic
Co-Wave/TMM calculations, use benchmark truth/locked scores, or send
feature-level identity or candidate kinase names to RAG, Report, or an LLM.

P2 supplies curated **relation provenance**. P3 will separately decide whether
and how several compatible kinase candidates can be retained or attributed.
Consequently, an exact P2 edge does not yet create a single direct kinase call.

## Bundle manifest

`ptm_kinase_relation_source_bundle.v1` is the only accepted manifest contract.
All paths are relative to an operator-mounted trusted root, all referenced
files are SHA-256 checked before use, and the root path cannot be escaped.

| Required manifest field | Requirement |
| --- | --- |
| `bundle_id` | Immutable, human-readable identifier; never derived from an Order |
| `source_name`, `source_url` | Exact upstream source identity and retrieval endpoint/page |
| `license_spdx_or_text`, `license_evidence_url` | Formal reuse basis; a license is not inferred from public availability |
| `release_or_retrieval_date` | Upstream release tag/date or a bounded retrieval timestamp |
| `transform_description` | Versioned disclosure of filtering/normalization performed offline |
| `relation_snapshot` | Relative JSONL(.gz) path, SHA-256 and schema version |
| `cross_reference_snapshot` | Required, separately hashed source-versioned mapping that records how a P1 M1 target accession/taxon is authorized to become a relation-source accession/identity scope |

The operator must retain the original license record and source artifact outside
the repository. Raw source dumps and derived JSONL do not enter git, an Order
folder, report bundle, RAG collection or LLM input.

## Canonical relation-row schema

Each normalized JSONL row must contain these fields. Input parsing may preserve
additional source-specific fields under `source_provenance`, but they never
relax exact matching.

| Field | Rule |
| --- | --- |
| `edge_id` | Stable source or transformation identifier |
| `relation_type` | `kinase_substrate_phosphorylation` only in P2 v1 |
| `kinase_accession`, `kinase_taxonomy_id` | A single source-versioned canonical kinase protein identity and NCBI taxonomy ID |
| `substrate_accession`, `substrate_taxonomy_id` | A single source-versioned canonical substrate protein identity and NCBI taxonomy ID |
| `residue`, `position` | Single `S`, `T`, or `Y` plus positive one-based coordinate in the declared substrate sequence/isoform |
| `substrate_isoform_or_sequence_id` | Required source-versioned identity token; it must disclose whether it is isoform/sequence-exact or source-release accession/site scope |
| `source_identity_scope` | Required. `isoform_or_sequence_exact` is strongest; iPTMnet release 6.2 may use only `accession_site_exact_iPTMnet_release_6_2`, never a hidden isoform claim |
| `evidence_reference_ids` | At least one source evidence/publication identifier |
| `source_provenance` | Source dataset release row/key and relation-specific evidence metadata |

Malformed, duplicate, ambiguous or conflicting rows are rejected or marked
non-joinable at bundle-validation time. A gene symbol, motif, kinase-family
label, text-mined assertion, or upstream pathway edge cannot substitute for
this row schema.

## Feature-to-relation join policy

P2 must require all of the following:

1. **P0 readiness:** a single feature accession, exactly one reported PTM
   position, non-multiphosphorylated precursor and class-I-or-higher recorded
   localization.
2. **P1 M1:** `M1_exact_sequence_site` only. M0/M2/M3/M4 are unconditionally
   non-joinable. M2 aligned ortholog context and M3 gene context are never
   converted to direct evidence by a P2 relation row.
3. **Target relation identity:** P1 must expose an unambiguous M1 target
   accession/taxon. A separately validated `cross_reference_snapshot` must
   then authorize its relation-source accession and identity-scope token. P1’s
   Ensembl protein ID, a gene symbol, or an analysis FASTA accession alone is
   not silently equated to a relation-source accession/isoform. For iPTMnet
   release 6.2, the cross-reference is built only from the source-versioned
   `protein.txt` accession/organism table and grants the explicitly limited
   `accession_site_exact_iPTMnet_release_6_2` scope. It never authorizes a
   rat→human accession join.
4. **Exact P2 edge:** substrate accession, target taxonomy, residue, position
   and target isoform/sequence ID all match the local P2 row.

When one or more exact rows match, P2 records the **unranked full-ledger
candidate set** and status `relation_supported_candidate_set_pending_p3`.
`direct_kinase_attribution.status` remains `no_call`; it cannot be upgraded by
P2 alone. P3, if implemented, must preserve the complete compatible set and
state its allocation assumptions.

## Result classes

| Relation class | Meaning | Direct single-kinase claim |
| --- | --- | --- |
| `R0_not_evaluable` | Missing/incompatible manifest, hash, license declaration or snapshot schema | No-call |
| `R1_ineligible_feature_or_mapping` | P0 readiness fails, P1 is not M1, or source/versioned target relation accession is absent | No-call |
| `R2_no_exact_curated_edge` | P0/P1 eligibility passes but no exact frozen P2 row matches | No-call |
| `R3_exact_curated_candidate_set_pending_p3` | One or more exact curated rows match and full candidate set is retained | No-call; candidate-set provenance only |
| `R4_conflicting_or_ambiguous_curated_edge` | Multiple incompatible source identity/isoform records or conflicting row metadata | No-call |

## Sidecar, cache and release boundary

Full relation candidate rows, accessions, residues, coordinates, isoform IDs,
source row IDs, publication IDs and license details remain only in the full
persisted feature ledger. The compact projection may emit only the P2 importer
contract version, manifest SHA-256, validated/not-evaluable status, `R0`–`R4`
aggregate counts and fixed claim boundary. It excludes all identity, candidate
and raw-quantification fields.

The ledger contract and temporal-sidecar freshness logic must include the P2
importer contract plus configured relation-manifest SHA-256. A manifest change
must make old compact projections stale. An unset deployment configuration is
an explicit R0/no-call state, not a live fallback.

## Acceptance tests

The production test suite must demonstrate exact R3 candidate-set capture with
a fully P0-ready human M1 synthetic feature and a fully matching frozen local
row. It must also demonstrate that each of M0–M4, low/missing localization,
multi-phosphorylation, accession ambiguity, missing target relation accession,
source hash mismatch, missing license declaration, nonexact residue/position,
isoform mismatch, conflicting rows and unset bundle remains no-call.

Additional tests must prove that compact Report/RAG payloads do not expose
candidate kinase names, accessions, sequences, coordinates, relation IDs,
references or license text; that runtime modules contain no HTTP client; and
that benchmark truth, locked scorer, known relation registry, RAG and LLM data
cannot enter P2.

## Source selection record

The current source review is maintained in
`docs/ptm_vector_p2_relation_source_audit.md`. No reviewed external source is
automatically embedded today. iPTMnet’s published BY-NC-SA terms, the formal
PhosphoSitePlus license statement, and the currently unverified PhosphoSIGNOR
redistribution terms require an operator-selected, documented license path
before a real P2 snapshot is acquired.[1] [2] [3]

## References

1. [iPTMnet — License & disclaimer](https://research.bioinformatics.udel.edu/iptmnet/license)
2. [PhosphoSitePlus — overview and data-sharing information](https://www.phosphosite.org/staticAboutPhosphosite)
3. [PhosphoSIGNOR — Download Data](https://signor.uniroma2.it/PhosphoSIGNOR/downloads/)
