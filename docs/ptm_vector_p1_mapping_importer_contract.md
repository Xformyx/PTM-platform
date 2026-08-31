# PTM-Vector P1 Species/Site Mapping Importer Contract

## Scope and evidence ceiling

This document specifies the production implementation for P1. The importer
converts an already acquired **local mapping source bundle** into feature-level
mapping provenance. It does not query any remote endpoint at order runtime;
does not read benchmark truth, locked scores, treatment identity, RAG prose or
LLM output; and does not import a kinase--substrate relation database. P1
therefore cannot produce a direct kinase call. It may only replace the P0
statement “mapping ledger absent” with a checked M0--M4 mapping status.

> An M1 record establishes a sequence/site mapping prerequisite, not a kinase
> relation. An M2 or M3 record is contextual only. A curated relation snapshot
> is separately governed by P2.

## Module and entry points

The implementation adds `ptm_shared/species_site_mapping.py` with the frozen
contract version `ptm_species_site_mapping.v1`. Its public interfaces are
deliberately file-local and deterministic.

| Function | Input | Output | Constraint |
|---|---|---|---|
| `load_mapping_source_bundle()` | bundle manifest path | validated manifest or M0 diagnostic | local files only; verifies every SHA-256 before parsing |
| `load_orthology_snapshot()` | validated local snapshot path | immutable, typed orthology rows | accepts only declared source/target taxa and release |
| `map_feature_records()` | P0 feature ledger plus validated bundle | feature-ID keyed M0--M4 results | no network client/import; no kinase relation input |
| `attach_mapping_context()` | P0 ledger plus mapping results | enriched full ledger and fresh compact summary | cannot alter direct-kinase tier from `E_direct_kinase_no_call` |
| `compact_mapping_summary()` | full mapping context | aggregate-only class/status counts | excludes feature identifiers, accessions, sequences and coordinates |

`build_production_temporal_ptm_protein_analysis()` will receive an optional
local mapping-bundle reference. When omitted, it emits an explicit M0
diagnostic rather than attempting an online lookup or a fallback mapping. The
normal RAG caller must pass **feature provenance rows reconstructed from the
same enriched records**, including per-protein FASTA taxonomy provenance, into
the full-sidecar builder. This is required so the P0 feature identity record,
not a gene-level aggregate, remains the mapping unit.

## Local source-bundle manifest

The source bundle is a JSON document placed outside git, benchmark folders and
the Report/RAG payload. Every file is resolved beneath a configured trusted
mapping snapshot root after canonical-path containment checks. The physical
analysis FASTA and reference FASTAs must never be copied into an order packet.

```json
{
  "contract_version": "ptm_species_site_mapping_source_bundle.v1",
  "bundle_id": "rat_human_ensembl_116_20260831",
  "created_at": "2026-08-31T00:00:00Z",
  "analysis_reference": {
    "relative_path": "analysis/uniprotkb_proteome_Rat_add_human_INSR.fasta",
    "sha256": "61b5d367511111d46377c78cfcfc1a09bacb0c1632c9960282520de732823c83",
    "order_species_taxonomy_id": 10116,
    "mixed_taxa_allowed": [10116, 9606]
  },
  "reference_fastas": {
    "rattus_norvegicus": {
      "relative_path": "ensembl_116/Rattus_norvegicus.GRCr8.pep.all.fa.gz",
      "sha256": "860aef1226c1ac924cac38fb18327e2c8275a8b78c23e2ec20e60f573cffb228",
      "provider": "Ensembl",
      "release": "116",
      "assembly": "GRCr8",
      "taxonomy_id": 10116
    },
    "homo_sapiens": {
      "relative_path": "ensembl_116/Homo_sapiens.GRCh38.pep.all.fa.gz",
      "sha256": "9b43da92651b35814597af6a8b18f500b768679a49fa4678224f384917ce7668",
      "provider": "Ensembl",
      "release": "116",
      "assembly": "GRCh38",
      "taxonomy_id": 9606
    }
  },
  "orthology_snapshot": {
    "relative_path": "compara_116/rat_to_human_orthology.jsonl.gz",
    "sha256": "REQUIRED_ACQUIRED_VALUE",
    "provider": "Ensembl Compara",
    "release": "116",
    "source_taxonomy_id": 10116,
    "target_taxonomy_id": 9606,
    "retrieval_query_contract": "orthologues; protein sequence; aligned/CIGAR retained"
  }
}
```

The example’s analysis FASTA hash is the locally verified mixed Rat_hir
reference. It records an explicit human `P06213` INSR insertion. The
orthology file is intentionally represented as `REQUIRED_ACQUIRED_VALUE`: no
cross-species mapping may be activated until a release-116 row snapshot with
that file’s real hash and all required alignment fields has been acquired.

## Orthology snapshot row schema

Each JSONL record must include the fields below. The importer rejects the
entire bundle as M0 if required columns are absent, source/target taxa or
release disagree with the manifest, or aligned strings/CIGAR cannot describe a
valid same-length alignment.

| Field | Type | Requirement |
|---|---|---|
| `source_ensembl_gene_id`, `target_ensembl_gene_id` | string | non-empty stable IDs |
| `source_ensembl_protein_id`, `target_ensembl_protein_id` | string | non-empty stable translation IDs |
| `homology_type` | enum | must be `ortholog_one2one` for M2 |
| `is_high_confidence` | boolean | must be `true` for M2 |
| `source_taxonomy_id`, `target_taxonomy_id` | integer | must match manifest |
| `source_sequence`, `target_sequence` | string | ungapped protein strings, checksum-verifiable against pinned FASTAs |
| `source_aligned`, `target_aligned` | string | same length, gaps permitted only as `-` |
| `cigar_line` | string | parses to aligned lengths and ungapped sequence lengths |
| `source_gene_symbol`, `target_gene_symbol` | string/null | context-only; never a site mapping fallback |
| `source_uniprot_accessions`, `target_uniprot_accessions` | array | optional cross-reference context, never required to manufacture a match |

## Deterministic per-feature mapping record

The mapping output is stored only under each `feature_record.mapping_evidence`.
It preserves enough detail to reproduce the class, but it is not emitted to
compact Report/RAG payloads.

```json
{
  "mapping_importer_contract_version": "ptm_species_site_mapping.v1",
  "mapping_bundle_id": "rat_human_ensembl_116_20260831",
  "mapping_bundle_sha256": "manifest-content-sha256",
  "mapping_class": "M2_aligned_one_to_one_ortholog_site",
  "mapping_status": "mapped_context_only_no_direct_edge_promotion",
  "source": {
    "analysis_accession": "source accession from the P0 feature record",
    "fasta_taxonomy_id": 10116,
    "residue": "Y",
    "position": 185,
    "sequence_verified": true,
    "peptide_window_verified": true
  },
  "target": {
    "taxonomy_id": 9606,
    "ensembl_protein_id": "target translation ID",
    "residue": "Y",
    "position": 187,
    "sequence_verified": true
  },
  "orthology": {
    "homology_type": "ortholog_one2one",
    "high_confidence": true,
    "aligned_residue_verified": true
  },
  "promotion_guard": "mapping_evidence_alone_cannot_create_or_rank_a_direct_kinase_edge"
}
```

## M0--M4 state machine and conflict resolution

The order below is a **validation order**, not a rule that upgrades a weaker
record into a direct relation. The first failed source-bundle gate applies M0
globally. A valid bundle then evaluates each feature independently.

| State | Entry condition | Required verification | Resulting direct-kinase status |
|---|---|---|---|
| M0 `not_evaluable_missing_or_incompatible_snapshot` | missing bundle, missing file, SHA-256 mismatch, invalid release/taxon/schema, or a stale bundle contract | none; emit machine-readable diagnostic | Tier E no-call; F3 remains not evaluable |
| M1 `exact_sequence_site` | unique source analysis entry and unique target peptide/site candidate with exact peptide-window match | source/target coordinates in range; residues and peptide sequence windows match pinned FASTAs | Tier E no-call pending P2 curated edge and P0 readiness gates |
| M2 `aligned_one_to_one_ortholog_site` | no M1; unique valid `ortholog_one2one`, high-confidence alignment maps the source coordinate to one target coordinate | both ungapped sequence checks, CIGAR/aligned-column consistency and identical source/target residue at mapped column | Tier E no-call; context-only mapping |
| M3 `gene_only_context` | no M1/M2; explicit valid orthology has unique gene-level target but lacks site-verified mapping | source/target stable gene identifiers and valid bundle provenance | Tier E no-call; context-only mapping |
| M4 `unmapped_or_ambiguous` | valid bundle, but absent candidate, unresolved source accession/position, multiple highest-precedence distinct targets, or residue conflict | record candidate count and failure code; do not choose arbitrarily | Tier E no-call; F3 flagged |

For the deliberately mixed Rat_hir reference, an analysis FASTA entry carrying
`OX=9606` is assessed as a human source entry. In particular, `P06213` is first
eligible for a same-species M1 sequence/site check; it is **not** sent through
the rat-to-human orthology transfer path. A shared gene symbol is never enough
to select a target protein, residue or mapping class.

If duplicate candidates resolve to the same target protein/residue after
verification, they collapse deterministically by target identifier and content
hash. If equally eligible candidates resolve to different targets, they yield
M4. M1 outranks M2, which outranks M3, only for reporting the most specific
provenance class; none of the three changes a kinase attribution tier.

## Verification algorithms

M1 parsing accepts exactly one `S|T|Y` plus positive integer from the feature’s
reported PTM position. It verifies the indicated residue in the source analysis
FASTA and in a single target sequence, then verifies that the normalized
unmodified feature peptide (or a declared fixed flank window) occurs at those
coordinates. A multi-position precursor, an ambiguous accession group, or
missing/low localization remains a P0 direct-call blocker even if M1 mapping
can be recorded.

M2 resolves the source site into the pinned orthology record only after the
source sequence is verified against the analysis reference and the relevant
pinned species FASTA. It walks aligned columns or a parsed CIGAR from the
source coordinate to exactly one target coordinate. Gaps, a residue mismatch,
paralogous or non-high-confidence relationships, and mismatched FASTA content
cannot receive M2. Such cases may receive M3 only when the validated snapshot
contains a unique explicit gene-level relationship; otherwise they are M4.

The normal module will import only standard-library file/hash/compression/JSON
facilities and local BioPython parsing if needed. It must not import or call
`requests`, `httpx`, `urllib`, a database relation registry, RAG or LLM code.

## Sidecar, cache and downstream boundary

The P0 feature-ledger contract will move to
`ptm_kinase_feature_provenance.v3` when P1 is wired. Its cache identity must
include `ptm_species_site_mapping.v1`, mapping-bundle content SHA-256 and the
bundle status. A legacy v1/v2 ledger without a mapping bundle is stale for P1
and must be rebuilt as M0; it must not be retroactively assigned M1--M4.

The full sidecar holds the detailed mapping records. Its only released
projection is:

```json
{
  "mapping_importer_contract_version": "ptm_species_site_mapping.v1",
  "mapping_bundle_status": "validated|not_evaluable",
  "mapping_class_counts": {"M0": 0, "M1": 0, "M2": 0, "M3": 0, "M4": 0},
  "direct_kinase_attribution_status": "no_call_without_p2_curated_edge_and_p0_readiness",
  "excluded_fields": ["feature_id", "accession", "sequence", "peptide", "coordinate", "orthology_ids"]
}
```

The compact summary must contain no protein/gene name, source or target
accession, Ensembl ID, peptide, raw site coordinate, source file path, raw
quantitative value, benchmark truth, locked score, known relation, RAG prose or
LLM output. Report text may describe aggregate mapping readiness only.

## Acceptance tests

| Test | Fixture | Required assertion |
|---|---|---|
| exact M1 | synthetic human source and target peptide/site with matching residue/window | one M1 record; Tier E no-call unchanged |
| aligned M2 | synthetic rat/human one-to-one alignment with a mapped same-residue column | one M2 context record; no direct edge field appears |
| human INSR preservation | `P06213`, `OX=9606` source fixture within rat order context | source remains human; no rat orthology lookup/classification |
| M3 context | unique gene relationship but missing/incompatible site alignment | M3 emitted; no promotion |
| M4 ambiguity | two equally valid distinct target candidates or residue disagreement | M4 emitted; no arbitrary selection |
| M0 absence/mismatch | missing bundle, malformed row, SHA mismatch, release mismatch | M0 diagnostic; no crash and no fallback |
| P0 gates remain active | M1 fixture with multi-site, ambiguous accession, or low/missing localization | mapping record can be present, direct status remains Tier E |
| compact isolation | full M1/M2 records with IDs/sequences/coordinates | compact summary and Report packet contain aggregate counts only |
| no live lookup | monkeypatch network primitives and inspect import surface | mapping resolves from local fixture; no HTTP call/import |
| cache/legacy | v2 sidecar and a changed mapping bundle hash | legacy cache refreshes to explicit M0; changed bundle invalidates previous P1 projection |
| regression | P0 ledger, temporal sidecar, dynamic/Report packet suite | Wave/TMM/strict runner behavior unchanged; benchmark truth remains isolated |

## Sources and release decisions

The P1 source/reuse rationale and the release-116 FASTA hashes are maintained
in [`ptm_vector_p1_mapping_source_manifest.md`](ptm_vector_p1_mapping_source_manifest.md).
Ensembl’s orthology API documentation confirms the availability of target
species, protein sequence, alignment and CIGAR output for snapshot generation,
but the runtime uses only the resulting frozen local rows. [1]

## References

[1] [Ensembl REST: homology by symbol](https://rest.ensembl.org/documentation/info/homology_symbol).
