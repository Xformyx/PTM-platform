# PTM-Vector Known-versus-Novel Substrate Competitiveness Audit

## External method anchors

### KSEA

KSEA App states that kinase–substrate annotation is sourced from curated PhosphoSitePlus and optional predicted NetworKIN. Its default uses PhosphoSitePlus alone, and it aggregates available kinase–substrate annotations to estimate kinase activity. This makes the output inherently dependent on available prior edges rather than a complete feature-level discovery ledger.

Source: Wiredja DD, Koyutürk M, Chance MR. *The KSEA App: a web-based tool for kinase activity inference from quantitative phosphoproteomics*. Bioinformatics (2017). https://pmc.ncbi.nlm.nih.gov/articles/PMC5860163/

### KSTAR

KSTAR converts observed phosphosites into kinase activity scores using pruned global kinase–substrate prediction graphs. Its paper notes sparse direct kinase–substrate annotation and reports that most phosphoproteome sites can be unlabelled. It expands coverage with predicted networks, then uses enrichment over multiple pruned graphs to control overlap and study-bias effects. This is a kinase-activity inference strategy, not a feature-level temporal new-substrate prioritization framework.

Source: Crowl S et al. *KSTAR: An algorithm to predict patient-specific kinase activities from phosphoproteomic data*. Nature Communications (2022). https://www.nature.com/articles/s41467-022-32017-5

### CLUE

CLUE selects an informative clustering partition for time-series phosphoproteomics by using curated kinase–substrate annotations, then identifies kinases enriched within clusters. Its method paper explicitly shows that performance depends on annotation completeness; the no-annotation scenario loses the knowledge input that guides clustering evaluation.

Source: Yang P et al. *Knowledge-Based Analysis for Detecting Key Signaling Events from Time-Series Phosphoproteomics Data*. PLOS Computational Biology (2015). https://doi.org/10.1371/journal.pcbi.1004403

## Interpretation boundary

These comparisons describe documented method design, not a head-to-head performance claim. PTM-Vector should claim a distinct evidence architecture only where its production code demonstrably retains measured annotation-negative features, temporal evidence and explicit no-call provenance independently of kinase-prior attribution.

## Current production-code audit

### Information already delivered to Gemini

`biological_synthesis_packet.v1` is built from the active Order's `vector_plot_raw_data`, experiment metadata, network pathway enrichment output and temporal evidence packet. It provides the cell model, organism, treatment, time grid and stated biological question; total row/gene/site landscape counts; up to 20 measured gene-site trajectory cards ranked by absolute PTM log2FC; up to eight pathway-enrichment anchors; and temporal-context availability. Each card includes condition-level PTM-relative and protein log2FC, q-value in the machine packet, peak condition and a data-derived coarse profile label.

The packet is placed ahead of full-vector data in Results, Discussion, Conclusion, Abstract and question/answer section supplements. `build_data_anchored_rag_queries` then creates retrieval plans for study context, measured pathway anchors, up to six candidate genes and the time-course programme. Retrieval preserves query role and anchor, and writer telemetry preserves the selected literature references.

This path is data-inclusive: a named, quantified substrate can enter the candidate cards and candidate-biology RAG query whether or not it has a known kinase–site annotation. P0–P3 direct-edge status is intentionally isolated from this discovery route.

### Existing novelty path and its limit

The legacy kinase annotation node separately labels a phosphosite as a `novel_candidate` when it has no known kinase anchor within its cluster. It also reports known, motif-only and novel counts per cluster. However, the same node embeds these discoveries within a legacy temporal kinase-cascade text block, which is a lower-quality route for a discovery narrative: it does not create a ranked novel-candidate card, does not preserve q-value/trajectory/replicate/Wave evidence together and can be crowded out by kinase-cascade prose.

The new biological synthesis packet solves priority and quantitative traceability but does not yet carry a first-class `known`, `motif-context`, `annotation-negative` or `novelty rationale` field. Its candidate ranking is currently maximum absolute PTM log2FC only. Candidate RAG retrieves only the first six cards and guarantees representation of a query role, not every individual candidate. Consequently, a high-amplitude canonical substrate can crowd a less-known but reproducible dynamic, multi-site divergent or PTM–protein-decoupled candidate out of both the short candidate list and the literature comparison.

### Narrow production-safe improvement proposal

Add a candidate-discovery companion packet, not a direct kinase allocator. It should partition already observed named gene-site trajectories into: (1) canonical/context anchors, (2) annotation-negative discovery candidates and (3) discordant or multi-site-divergent candidates. Each card should preserve only Report-eligible fields: measured PTM/protein trajectory, q-value coverage, profile/peak, Wave/Dynamic membership where computed, pathway context, novelty rationale and a direct-edge status of `not established` when appropriate.

Ranking should use a declared deterministic discovery score with its components reported separately rather than a hidden biological probability. A first implementation can require finite multi-condition trajectory evidence, then combine effect magnitude, q-value coverage, PTM–protein divergence, reproducible Wave/Dynamic context and within-gene site divergence. It must not use benchmark truth, treatment-specific priors, P2 candidate identities or P3 allocated edge mass.

RAG should reserve separate, bounded query slots for canonical anchors and discovery candidates. Candidate queries should include the active cell model, treatment, PTM type and the measured gene/site context when present, and writer input should request literature agreement, disagreement, plausibility and a discriminating follow-up measurement for each selected discovery candidate. Figure and Report text should label these as data-prioritized candidates, not new direct kinase substrates.

## Competitive positioning

PTM-Vector's defensible distinction is not that it estimates kinase activity better than KSEA or KSTAR under every condition. Its distinction is that it retains the experimentally measured feature universe when kinase–site annotation is sparse, separates direct-attribution no-call from biological discovery, and can use time-resolved PTM/protein trajectories, static and Dynamic Co-Wave evidence, multi-site divergence and Order-scoped literature to prioritize new biological hypotheses.

KSEA is useful as a known-substrate enrichment baseline. KSTAR expands coverage with predicted kinase networks and controls some network/study-bias properties. CLUE offers a knowledge-guided choice of temporal clustering partition. PTM-Vector can complement all three by retaining annotation-negative features as first-class discovery objects rather than treating them solely as absent evidence for a kinase score. This is a design comparison, not a quantitative superiority claim; prospective evaluation requires held-out biological validation, which remains outside the current P4-deferred scope.
