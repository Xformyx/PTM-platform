# PTM-Vector P1: Ensembl Release-116 Strict-Tree Context Bundle Activation

## Status and claim ceiling

This runbook activates the first reproducible local P1 source bundle created
from Ensembl Compara release 116 strict protein OrthoXML. It is a **mapping
provenance** deployment, not a kinase attribution deployment. The bundle is
external to the Git repository and must be mounted read-only beneath the worker
filesystem.

| Item | Frozen value |
| --- | --- |
| Bundle ID | `rat_human_ensembl_116_strict_tree_context_20260831` |
| Bundle manifest SHA-256 | `f80b6f9abf5568153cde2c730332dd9c55431476f8a2e6cfa3acb01cca291dfe` |
| Ensembl Compara source | `Compara.116.protein_default.allhomologies_strict.orthoxml.xml.gz` |
| Source artifact SHA-256 | `fe61861834dd757386a2c98133bdb189f77f5b00773d574a0f0c7a9a55a45543` |
| Pinned peptide references | Ensembl 116 Rattus norvegicus GRCr8 and Homo sapiens GRCh38 FASTA |
| Strict rat→human rows | 14,800 row records; zero rows failed pinned FASTA reconciliation |
| Mapping evidence ceiling | **M3 gene-only context only** for rat→human rows |
| Direct kinase attribution | **Tier E `no_call`** for every mapping class |

> The strict OrthoXML export records tree-compliant orthology pairs but does
> not contain Ensembl's `is_high_confidence` value or protein
> alignment/CIGAR. The P1 builder therefore writes those fields as unavailable
> and false. It must not be represented as M2 residue-level orthology evidence.

The bundle also includes the verified mixed Rat_hir analysis FASTA. Its human
INSR `P06213` entry is retained with `OX=9606`. A human source record is mapped
only as same-species M1 after sequence/site verification; it is never sent
through rat→human orthology and remains Tier E `no_call` pending P2.

## Mount and configure atomically

Place the bundle on a controlled, read-only worker volume. The directory must
contain `bundle.json`, `analysis/`, `ensembl_116/`, and `compara_116/` exactly
as created by the offline builder. Do not copy it into the repository, an Order
directory, a report payload, a RAG collection, or an LLM prompt.

Configure all three variables for the RAG enrichment worker **in one
deployment**. The paths below are deployment examples, not literal sandbox
paths.

```dotenv
PTM_MAPPING_SNAPSHOT_ROOT=/srv/ptm-mapping/rat_human_ensembl_116_strict_tree_context_20260831
PTM_MAPPING_SOURCE_BUNDLE_PATH=/srv/ptm-mapping/rat_human_ensembl_116_strict_tree_context_20260831/bundle.json
PTM_MAPPING_BUNDLE_SHA256=f80b6f9abf5568153cde2c730332dd9c55431476f8a2e6cfa3acb01cca291dfe
```

`PTM_MAPPING_SOURCE_BUNDLE_PATH` must remain beneath
`PTM_MAPPING_SNAPSHOT_ROOT`. At analysis time the importer resolves only local
paths and validates SHA-256 for the manifest, analysis FASTA, rat FASTA, human
FASTA and JSONL snapshot. A missing file, a hash mismatch, a path escaping the
root, or a release/taxonomy/schema mismatch produces M0
`not_evaluable_missing_or_incompatible_snapshot`; it must not trigger an API
request, gene-symbol fallback or guessed mapping.

The `PTM_MAPPING_BUNDLE_SHA256` control-plane value is intentionally the SHA-256
of `bundle.json`, not the orthology JSONL hash. It is compared to the compact
sidecar’s mapping-bundle projection and invalidates an old sidecar whenever the
configured manifest changes.

## Activation and acceptance procedure

Restart only the RAG enrichment workers after the atomic configuration update.
Then run canonical temporal sidecar creation through an eligible Order; do not
hand-edit any sidecar or reuse a legacy v1/v2 P0 ledger. The existing cache
freshness contract will rebuild a stale P1 projection.

| Verification | Required result | Interpretation |
| --- | --- | --- |
| Full persisted sidecar | `mapping_importer.mapping_bundle_status = validated` and bundle SHA-256 equals the configured manifest SHA-256 | Local bundle integrity and caller handoff succeeded |
| Full ledger, rat feature with an exactly reconciled strict-tree gene pair | `M3_gene_only_context` | Valid cross-species context, not residue/site attribution |
| Full ledger, verified human `P06213` feature | `M1_exact_sequence_site`, source taxonomy `9606` | Human transgene remained a human source entity |
| Compact temporal summary / Report packet | aggregate `mapping_class_counts` only; no accession, sequence, peptide, coordinate, Ensembl ID or source path | Full-ledger boundary held |
| Any direct kinase entry | `status = no_call`, tier `E_direct_kinase_no_call` | P1 did not create a kinase–substrate claim |
| Report prose | May state aggregate mapping readiness/context; may not name an attributed kinase from P1 | Claim ceiling held |

## Replacement and rollback

To replace a bundle, create and validate the new local directory offline,
compute its `bundle.json` SHA-256, then change the root, manifest path and
expected manifest hash together. Never mutate files in an active bundle path.
The changed hash forces a new sidecar projection.

If the bundle volume must be withdrawn, remove all three variables and restart
the worker. New sidecars must become explicit M0/no-call rather than falling
back to online mapping. Preserve already generated sidecars for audit; do not
edit mapping classes in place.

## P2 prerequisite

P2 remains blocked until a separately versioned, license-compliant curated
kinase–substrate relation snapshot is acquired. Even then, only a P0-ready M1
site plus a matching P2 curated edge may enter direct-evidence evaluation. This
release-116 strict-tree M3 context bundle cannot be used to promote any direct
kinase relation.
