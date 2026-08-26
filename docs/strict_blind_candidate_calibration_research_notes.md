# Strict-blind kinase-candidate calibration research notes

## Purpose

These notes support a truth-free implementation of quantitative motif likelihood and kinase-family ambiguity handling. They are methodology references only and are not passed to the benchmark analysis runtime.

## Evidence retained

Bradley and Beltrao describe kinase peptide specificity as a short sequence motif while emphasizing that cellular specificity also depends on coexpression, colocalization, docking and scaffolding. Their specificity analysis compares motif enrichment against randomized or background peptides and reports that sequence specificity differs more strongly across kinase groups and families than across close subfamilies. This supports background-normalized motif likelihood and conservative family-level resolution when the sequence evidence cannot distinguish isozymes.

Source: [Evolution of protein kinase substrate recognition at the active site](https://pmc.ncbi.nlm.nih.gov/articles/PMC6611643/), PLOS Biology, 2019, DOI 10.1371/journal.pbio.3000341.

Invergo’s IV-KAPhE work frames kinase–phosphosite assignment as a **multi-label** problem because one phosphosite may be targeted by multiple kinases. The method builds sequence specificity against proteomic or phosphoproteomic background frequencies, uses relative-entropy position weighting and normalized likelihood scores, and evaluates macro-averaged kinase metrics. The paper also warns that dense multi-kinase predictions may reflect unmodelled biochemical constraints or genuine redundancy and that closely related kinase isozymes are difficult to separate. This supports retaining multiple candidates, recording family ambiguity, and avoiding forced gene-level attribution from a broad motif alone.

Source: [Accurate, high-coverage assignment of in vivo protein kinases to phosphosites from in vitro phosphoproteomic specificity data](https://pmc.ncbi.nlm.nih.gov/articles/PMC9132282/), PLOS Computational Biology, 2022, DOI 10.1371/journal.pcbi.1010110.

The benchmarKIN study reports that inferred kinase activities depend materially on the kinase–substrate library and that target-count coverage affects which kinases can be evaluated. It compares algorithms and libraries with perturbation and independent multi-omics benchmarks, and explicitly tests predicted kinase–substrate interactions as a way to improve coverage. This supports keeping motif-predicted edges as a separate evidence class, correcting module-size effects, and requiring later perturbation validation rather than treating additional predicted edges as truth.

Source: [Comprehensive evaluation of phosphoproteomic-based kinase activity inference](https://www.nature.com/articles/s41467-025-59779-y), Nature Communications, 2025, DOI 10.1038/s41467-025-59779-y.

## Implementation boundary

The strict-blind upgrade may use only observed sequence windows, neutral FASTA provenance, temporal replicate values and generic motif definitions during selection. It must not use treatment identity, workbook anchors, expected insulin branches, biological question, RAG, reports or LLM context. Quantitative motif likelihood is therefore interpreted as sequence-support calibration, not direct kinase–substrate evidence.
