# Rat Direct Evidence and Human Ortholog Conserved-site Evidence Assessment

## External evidence collected

### iPTMnet coverage

iPTMnet v6.2 statistics (updated 2024-01-31) report 477,619 sites and 18,445 enzyme-substrate-site relations for human, versus 38,932 sites and 946 enzyme-substrate-site relations for rat. Thus the rat dataset contains approximately 12.26-fold fewer total sites and 19.49-fold fewer enzyme-substrate-site relations than the human dataset. iPTMnet nevertheless explicitly supports rat as a selectable organism, so a zero returned direct hit must be interpreted as no returned curated rat exact-site record rather than as lack of rat support.

* Source: https://research.bioinformatics.udel.edu/iptmnet/stat
* Resource page: https://research.bioinformatics.udel.edu/iptmnet/
* Resource paper: https://pmc.ncbi.nlm.nih.gov/articles/PMC5753337/

### BioGRID direct organism semantics

BioGRID REST accepts NCBI taxonomy identifiers through its `taxId` parameter and limits gene-name lookup to genes from the selected organism. The documentation distinguishes direct organism filtering from optional `interSpeciesExcluded`, which controls interactions whose two partners originate in different species. BioGRID is an interaction database, not an exact PTM-site resource; therefore a BioGRID zero is an absence of returned direct interaction records for the queried rat gene under the selected query/filter state, not evidence about the PTM residue.

* REST documentation: https://wiki.thebiogrid.org/doku.php/biogridrest
* About/curation scope: https://wiki.thebiogrid.org/doku.php/aboutus

### Conserved-site validation capability

Ensembl REST provides rat-to-human orthology lookups by stable ID or symbol, can restrict to orthologues and a target species, and can return aligned protein sequences. The same service exposes protein sequence retrieval. These endpoints permit residue-level mapping from a rat reference sequence position to a human ortholog position, but symbol matching alone is insufficient for a conserved-site assertion.

* Homology by stable ID: https://rest.ensembl.org/documentation/info/homology_species_gene_id
* Homology by symbol: https://rest.ensembl.org/documentation/info/homology_symbol
* Sequence by ID: https://rest.ensembl.org/documentation/info/sequence_id

## Current PTM-platform code findings

* `workers/rag_enrichment/core/enrichment_pipeline.py` derives the external annotation organism from `FASTA_Taxonomy_ID` first. Rat uses taxon 10116; the human INSR transgene uses taxon 9606 and remains a human query.
* The iPTMnet client sends the raw gene, site string, and selected organism directly. No human ortholog fallback exists.
* The BioGRID client sends the raw gene and taxon ID; rat queries use 10116. No human interaction fallback exists.
* Both client functions presently catch request exceptions and return an empty-shaped payload. Downstream code can therefore conflate a request failure with an empty direct result unless an explicit source error provenance field is added.

## Required safety gates for any fallback

1. Retain the direct rat query result verbatim and evaluate it first.
2. Permit human fallback only when no direct rat exact-site hit is returned and a unique Ensembl rat-human one-to-one ortholog is identified.
3. Map the actual rat FASTA residue through an aligned protein sequence and require the human aligned residue to match the PTM amino-acid class.
4. Query iPTMnet using the mapped human protein/gene and mapped human position; do not infer a human site from symbol equality alone.
5. Persist `direct_rat`, `inferred_cross_species`, and `unavailable_or_unaligned` as mutually exclusive provenance states. Cross-species evidence may support prioritization but must not be treated as direct rat observation or causal evidence.
6. Keep BioGRID interaction evidence in a separate `cross_species_interaction_context` field. It must never be represented as a site-level PTM validation.

## Proposed enrichment contract

### Direct rat evidence remains authoritative

For every rat PTM, the worker must run the current direct rat iPTMnet and BioGRID queries first. A returned direct rat iPTMnet exact-site hit is final for the site-validation layer; the worker must not query human merely to replace or augment a successful direct rat record. A returned direct rat BioGRID interaction list remains direct interaction context, not a PTM-site assertion.

### Human conserved-site fallback is narrow and additive

The fallback may run only if the direct rat iPTMnet query completes successfully with zero exact-site hits. It should use the FASTA-native rat accession when available, resolve a unique Ensembl rat-to-human one-to-one ortholog, obtain an aligned protein representation, map the observed rat residue to a human aligned position, and require the same residue letter at both positions. Only then may the worker query human iPTMnet with the mapped human gene/accession and residue position.

The fallback must never run for a human PTM such as the Rat_hir human INSR transgene, which is already a direct human query. It must also be skipped when the ortholog is one-to-many/many-to-many, when the observed residue maps to a gap or a different amino acid, when the protein is unresolved, or when the alignment source is unavailable.

### Suggested packet schema

```json
{
  "iptmnet_evidence": {
    "provenance": "direct_rat | inferred_cross_species | unavailable_or_unaligned | source_error",
    "direct_rat": {"query_status": "hit | empty | error", "sites_found": 0},
    "human_conserved_site": {
      "eligible": false,
      "orthology_type": "ortholog_one2one",
      "human_gene": null,
      "rat_site": "S522",
      "human_site": null,
      "residue_conserved": false,
      "alignment_source": "Ensembl Compara",
      "human_iptmnet": null
    }
  },
  "biogrid_interaction_context": {
    "direct_rat": {"query_status": "hit | empty | error", "interaction_count": 0},
    "cross_species_interaction_context": null
  }
}
```

### BioGRID handling

BioGRID should continue to query the rat taxon (10116) directly. Since BioGRID provides protein/genetic interaction context rather than residue-level PTM validation, an empty rat result cannot be repaired by a human iPTMnet hit. If a rat-to-human conserved-site mapping has independently passed the iPTMnet gates, a separate optional human BioGRID query could later provide `cross_species_interaction_context`; it must be labeled as human ortholog interaction context and must not enter the direct rat interaction count or the site-validation score.

### Routing and wording requirements

`inferred_cross_species` must neither set `direct_site_curated=true` nor make a causal claim. It can be reported as: "No direct rat curated record was returned; the aligned human ortholog carries curated evidence at the conserved residue." The evidence-gap router may retain the direct-rat gap while reducing the priority of redundant broad literature retrieval; high-priority synthesis must retain the provenance label.

### Operational requirements

The implementation should cache ortholog alignment results by source protein/accession, residue, target species, and Ensembl release/response provenance. It should impose bounded timeout and retry behavior, preserve a distinguishable `source_error` state, and never allow an Ensembl timeout to block or invalidate the existing direct rat enrichment result. The fallback should follow the selection-mode contract: selected discovery/regulation trajectories may receive it, whereas the broad `All PTMs` and `Minor` annotation modes do not automatically fan out to cross-species queries.
