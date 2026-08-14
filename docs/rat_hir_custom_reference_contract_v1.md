# Rat_hir Custom Reference Contract v1

## Purpose

`Rat_hir` is a **custom reference database label**, not a new species. It is
defined as a *Rattus norvegicus* reference FASTA supplemented with a single
*Homo sapiens* insulin receptor entry.

| Field | Rat_hir value |
|---|---|
| Order label | `rat_hir` |
| Reference directory | `data/reference/rat_hir/` |
| Order-level analysis species | `rat` |
| Order-level taxonomy ID | `10116` |
| Order-level KEGG organism | `rno` |
| Custom protein | Human INSR, normally UniProt `P06213` |

The custom label remains on the Order for provenance. Public rat annotation
sources are used for the rat background. The existing per-protein
FASTA-provenance layer routes a row with `OX=9606` to human annotation without
changing the order's rat discovery context.

## Required FASTA layout

Place exactly the mixed database intended for search in the custom reference
directory:

```text
data/reference/rat_hir/<your_rat_hir_database>.fasta
```

Do not rely on fallback to `data/reference/rat/`. A missing `rat_hir`
directory or FASTA is intentionally reported as an error, since silently
searching a plain rat FASTA would omit the human transgene sequence.

## Required human INSR header provenance

The human entry must retain an accession, gene symbol, organism, and taxonomy
identifier. For a reviewed UniProt sequence, use a header equivalent to:

```fasta
>sp|P06213|INSR_HUMAN Insulin receptor OS=Homo sapiens OX=9606 GN=INSR PE=1 SV=3
```

The mixed-FASTA preprocessing contract records `FASTA_Organism=Homo sapiens`
and `FASTA_Taxonomy_ID=9606` for the transgene row. This gives human INSR
priority for accession-aware UniProt, STRING, KEGG, and RAG enrichment while
rat proteins retain `10116`/`rno` routing.

## User workflow

1. Put the custom rat-plus-human-INSR FASTA in `data/reference/rat_hir/`.
2. Select **Rat_hir (Rat + human INSR)** in the new-order Species selector.
3. Run preprocessing from the beginning for each affected Order; cached
   outputs made before mixed-FASTA provenance support do not have per-protein
   taxon fields.
4. In the enriched TSV, confirm human INSR has `FASTA_Taxonomy_ID=9606` and
   `Annotation_KEGG_Organism=hsa`; rat background entries should show
   `10116` and `rno`.

## Interpretation boundary

`Rat_hir` is not a fourth organism in downstream biology. The platform keeps
rat as the order-level discovery context and treats human INSR as a
FASTA-defined transgene. Gene-only screens that lack accession or FASTA taxon
may still be ambiguous between rat `Insr` and human `INSR`; accession-aware
and FASTA-provenance fields should be used for transgene-specific claims.
