# PTM-Vector P1 Rat–Human Mapping Source Manifest

## Purpose and non-promotion boundary

P1 creates a **versioned mapping-provenance layer**, not a direct kinase
assignment service. It must read a local, versioned mapping snapshot that is
recorded with each order. The online resources below are approved candidates
for generating that snapshot, but the normal analysis path must never make a
live API request or silently update a source release.

## Required source bundle for an order

| Asset | Required provenance | Minimum required fields | Intended mapping use |
|---|---|---|---|
| Analysis FASTA | local path, SHA-256, build date, all source accessions | source accession, full protein sequence, explicit human INSR insertion record if present | peptide/site coordinate verification |
| Rat reference proteome | provider, proteome ID, release date/version, download URL, SHA-256 | reviewed/unreviewed status, accession, sequence | rat source-coordinate reference |
| Human reference proteome | provider, proteome ID, release date/version, download URL, SHA-256 | accession, isoform/canonical indication, sequence | target-coordinate reference |
| Orthology snapshot | provider, release/database name, query parameters, retrieval timestamp, SHA-256 | source/target Ensembl gene and protein IDs, homology type, confidence, aligned protein/CIGAR data | M2 aligned ortholog site transfer |
| Mapping output | generator version, source bundle hashes, row count, SHA-256 | source/target accession, residue/position, mapping class, validation flags | immutable order-level mapping ledger |

The analysis FASTA is authoritative for the experiment. A current release of a
reference proteome cannot be substituted for it, because a mixed species
database may include a human protein such as INSR in addition to rat entries.

## Verified local analysis reference and selected frozen sequence sources

The following local source has been verified but must remain outside the git
repository and order packets. It is a candidate **analysis FASTA manifest**
entry, not a mapping result and not a substitute for an orthology snapshot.

| Role | Frozen identity | Verification result |
|---|---|---|
| Actual analysis FASTA | `uniprotkb_proteome_Rat_add_human_INSR.fasta`; SHA-256 `61b5d367511111d46377c78cfcfc1a09bacb0c1632c9960282520de732823c83` | 54,495 entries; explicit `sp|P06213|INSR_HUMAN`, `OX=9606`, `GN=INSR`, sequence version `SV=4` present |
| Rat mapping reference | Ensembl release 116, `Rattus_norvegicus.GRCr8.pep.all.fa.gz`; artifact SHA-256 `860aef1226c1ac924cac38fb18327e2c8275a8b78c23e2ec20e60f573cffb228`; decompressed stream SHA-256 `3d213d197c0d3416fa89a93c05cd3c56ce0f2729ba682b7ccdae8e8fe02c3aeb` | 51,575 Ensembl peptide entries downloaded from the release-116 archive |
| Human mapping reference | Ensembl release 116, `Homo_sapiens.GRCh38.pep.all.fa.gz`; artifact SHA-256 `9b43da92651b35814597af6a8b18f500b768679a49fa4678224f384917ce7668`; decompressed stream SHA-256 `3f1ef9848ae79d3810ef5c7bff3482d7fb0554618adf7f3655828e918f50a7c5` | 382,428 Ensembl peptide entries downloaded from the release-116 archive |

Release-116 FASTA URLs are
`https://ftp.ensembl.org/pub/release-116/fasta/rattus_norvegicus/pep/Rattus_norvegicus.GRCr8.pep.all.fa.gz`
and
`https://ftp.ensembl.org/pub/release-116/fasta/homo_sapiens/pep/Homo_sapiens.GRCh38.pep.all.fa.gz`.
The official `CHECKSUMS` registry supplied FTP checksums for these files; P1
will validate the recorded SHA-256 values from the acquired local artifacts.

No pinned rat–human Compara/orthology row snapshot is present yet. Therefore
the importer must report `M0_not_evaluable_missing_or_incompatible_snapshot`
for cross-species mapping until the aligned, one-to-one orthology bundle is
generated and frozen. The verified human INSR source entry remains human
source evidence; it must never be relabelled as a rat orthology merely because
the order-level analysis species is rat.

## Candidate public sources

| Source | Candidate record/API | Snapshot rule | License/reuse note |
|---|---|---|---|
| Ensembl Compara | `GET /homology/symbol/:species/:symbol` with `type=orthologues`, `target_species`, `sequence=protein`, and `aligned=1` where available | pin Ensembl release/archive, query parameters, response hash and retrieval date | Ensembl legal page documents release-specific terms; verify the archived release before redistribution |
| UniProt rat proteome | `UP000002494` | pin exact downloaded FASTA/release and checksum | UniProt copyrightable database content is CC BY 4.0 |
| UniProt human proteome | `UP000005640` | pin exact downloaded FASTA/release and checksum | UniProt copyrightable database content is CC BY 4.0 |
| Human INSR | `P06213` | record accession, sequence version and checksum; verify that the analysis FASTA contains the same inserted sequence | UniProtKB reviewed human INSR entry; do not infer a rat ortholog when the measured accession is human INSR |

## Mapping classes emitted by P1

| Class | Necessary conditions | Direct kinase tier effect |
|---|---|---|
| M1 `exact_sequence_site` | analysis FASTA source peptide/site and target peptide/site both match exactly; residue identity and coordinate are verified | mapping prerequisite only; curated edge still required |
| M2 `aligned_one_to_one_ortholog_site` | pinned one-to-one orthology plus sequence alignment maps the residue with matching amino-acid identity | transferred context only; cannot create a direct curated human edge |
| M3 `gene_only_context` | gene-level orthology but sequence/site prerequisites fail or are absent | contextual annotation only; no direct attribution |
| M4 `unmapped_or_ambiguous` | no unique eligible M1–M3 record, multiple equally eligible records, or provenance is incomplete | direct-kinase no-call |

## Acceptance gates before importer activation

1. The actual analysis FASTA and the custom human INSR insertion must have
   SHA-256 values recorded.
2. The mapping snapshot must provide row-level source and target identifiers,
   release hashes, mapping class and the validation flags needed above.
3. An M1 result must be independently recomputable from the pinned source and
   target sequences. An M2 result must carry an aligned-residue record and a
   one-to-one orthology assertion.
4. Missing, stale or incompatible manifests must yield `M0_not_evaluable`,
   never a gene-symbol fallback promoted to M1/M2.
5. P1 mapping output remains full-sidecar-only. RAG/Report receives only
   aggregate mapping-class/no-call counts.

## External sources

1. [Ensembl REST — homology by symbol](https://rest.ensembl.org/documentation/info/homology_symbol). The API documents `type`, `target_species`, `sequence`, `aligned` and CIGAR parameters for orthology retrieval.
2. [Ensembl legal information](https://www.ensembl.org/info/about/legal/index.html). The current page identifies Ensembl release 116 (June 2026); the production snapshot must additionally record the chosen archived release and its terms.
3. [UniProt license and disclaimer](https://www.uniprot.org/help/license). UniProt states that copyrightable database content is CC BY 4.0.
4. [UniProt rat reference proteome UP000002494](https://www.uniprot.org/proteomes/UP000002494).
5. [UniProt human reference proteome UP000005640](https://www.uniprot.org/proteomes/UP000005640).
6. [UniProtKB human INSR P06213](https://www.uniprot.org/uniprotkb/P06213/entry).
