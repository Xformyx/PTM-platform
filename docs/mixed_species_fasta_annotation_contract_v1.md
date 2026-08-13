# Mixed-Species FASTA Annotation Contract v1

## Purpose

An order can use a background-species FASTA that intentionally contains one or more
transgenes from another species. A common case is a **rat** proteome reference that
contains a human **INSR** entry. Such proteins must be retained as measured entities;
the order-level species must not silently turn them into `Unknown`, drop them, or use
the background species for their per-protein external annotation.

This contract is generic. It does not hard-code INSR, human, or rat names.

## Required FASTA header fields

Every intentionally added transgene entry must retain a stable accession, gene symbol,
organism, and taxonomy identifier. A reviewed UniProt-style header is recommended.

```text
>sp|P06213|INSR_HUMAN Insulin receptor OS=Homo sapiens OX=9606 GN=INSR PE=1 SV=3
```

The preprocessing contract extracts the following fields from the FASTA itself:

| FASTA field | Output field | Purpose |
|---|---|---|
| accession (`P06213`) | `Protein.Group` / accession lookup | sequence, UniProt, and site-level identity |
| `GN=INSR` | `Gene.Name` | readable gene context |
| `OS=Homo sapiens` | `FASTA_Organism` | per-protein organism provenance |
| `OX=9606` | `FASTA_Taxonomy_ID` | species-aware STRING, KEGG, and RAG routing |

Rows without `OX=` are retained, but their downstream external annotation falls back
to the order-level species. They are not dropped; their provenance is `Unknown`.

## Output provenance fields

Unified enrichment appends the following columns without changing the original
quantification or discovery measurements:

```text
FASTA_Organism
FASTA_Taxonomy_ID
FASTA_Mixed_Species_Group
Annotation_Species_Taxonomy_ID
Annotation_KEGG_Organism
Annotation_Organism
```

For a human INSR transgene in a rat order, the expected values are:

```text
FASTA_Organism = Homo sapiens
FASTA_Taxonomy_ID = 9606
Annotation_Species_Taxonomy_ID = 9606
Annotation_KEGG_Organism = hsa
```

The surrounding rat proteins retain `10116` and `rno`.

## Routing behavior

1. **Protein retention and motif analysis:** accession-based local FASTA lookup. No
   species filter is applied.
2. **UniProt annotation:** accession-based lookup. No order-wide organism filter is
   required for a valid accession.
3. **STRING and KEGG annotation:** grouped by `FASTA_Taxonomy_ID`; equal gene symbols
   from distinct species are queried separately.
4. **RAG enrichment:** a PTM carrying `FASTA_Taxonomy_ID=9606` uses human external
   gene-level annotation context while the order remains a rat discovery analysis.

## Operational procedure

1. Put the mixed FASTA in the selected rat reference location.
2. Confirm the transgene header contains accession, `GN=`, `OS=`, and `OX=` fields.
3. Create or rerun the Order with species set to **rat**.
4. Rerun preprocessing after this feature is deployed; cached prior enrichment files
   will not have the new provenance columns.
5. In the enriched TSV, verify the transgene row has the expected `FASTA_*` and
   `Annotation_*` values before interpreting external annotations.

## Scope and limitations

The order's discovery data remain a single experiment. Per-protein organism provenance
only controls external annotation routing; it does not transform rat observations into
human observations, infer cross-species causal links, or overwrite the original
quantification.

Gene-only global annotation endpoints that do not receive a protein accession can still
be ambiguous when host and transgene share a gene symbol. Prefer the enriched TSV,
accession-aware UniProt annotation, and RAG fields for transgene-specific interpretation.
