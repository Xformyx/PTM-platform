# Enrichment-free temporal proteomics + RAG/LLM research notes

## Integrated time-resolved phosphoproteome and proteome

Xiao et al. profiled time-resolved phosphoproteomes and proteomes during myogenesis. They reported an early phosphoproteome response before clear proteome-level changes, used temporal phosphorylation to infer kinase activities and context-relevant substrates, and connected signaling to later protein-level transcriptional programs. Inhibitor phosphoproteomics and proteomics were subsequently used to distinguish kinase-specific effects and validate a predicted substrate.

Source: [Time-resolved phosphoproteome and proteome analysis reveals kinase signaling on master transcription factors during myogenesis](https://pmc.ncbi.nlm.nih.gov/articles/PMC9198430/), iScience, 2022, DOI 10.1016/j.isci.2022.104489.

## LLMs in the scientific method

Zhang et al. review the use of LLMs across the scientific cycle, including literature synthesis, hypothesis generation, experimental design and agent workflows. They emphasize that useful scientific integration requires clear evaluation metrics and alignment with human scientific goals, and that prompts alone are insufficient for complex multi-step or non-language computations. This supports keeping deterministic PTM calculations outside the LLM and using the LLM to organize evidence, compare hypotheses and propose tests.

Source: [Exploring the role of large language models in the scientific method: from hypothesis to discovery](https://www.nature.com/articles/s44387-025-00019-5), npj Artificial Intelligence, 2025.

## Biomedical retrieval-augmented reasoning

Feng et al. combine document/entity knowledge graphs with progressive retrieval-augmented reasoning and require evidence-source provenance for graph relationships. Their evaluation reports improvements in retrieval and answer generation over compared approaches. The relevant design lesson is not the exact reported performance but the separation of retrieval, evidence normalization, cross-document reasoning and source traceability.

Source: [A retrieval-augmented knowledge mining method with deep thinking LLMs for biomedical research and clinical support](https://pmc.ncbi.nlm.nih.gov/articles/PMC12448786/), GigaScience, 2025, DOI 10.1093/gigascience/giaf109.

## Signaling-pathway inference benchmark limits

Garrido-Rodriguez et al. compare literature-curated, computational and peptide-array kinase–substrate networks on EGF phosphoproteomics. Expanded networks strongly increase phosphosite coverage, but performance gains are modest and many predicted interactions are absent from current ground truth. They separate coverage from accuracy and use inhibitor-derived targets to choose network thresholds. This supports a distinct canonical recovery layer, data-anchored kinase layer, discovery layer and later perturbation validation.

Source: [Benchmarking EGF signaling pathway inference using phosphoproteomics and kinase-substrate interactions](https://www.nature.com/articles/s41467-026-69332-0), Nature Communications, 2026, DOI 10.1038/s41467-026-69332-0.

## Boundary for PTM-platform

RAG and LLM outputs must not enter the primary strict-blind score or tune Wave/TMM parameters. They should receive only archived truth-free quantitative evidence and retrieve from the user-selected ChromaDB collection. Every generated mechanism hypothesis must preserve separate observation, computational attribution, retrieved literature and proposed validation fields.
