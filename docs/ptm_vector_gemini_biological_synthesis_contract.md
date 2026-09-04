# PTM-Vector Gemini Biological Synthesis Contract

**Status:** implementation contract

**Scope:** production Report generation only; benchmark runner, locked scorer, and P4 perturbation validation are excluded.

**Language policy:** final scientific Report is written in English; operator and implementation records may be Korean.

## 1. Purpose

The production Report must answer the biological question that the user supplied for the actual Order. It must not inherit the truth-free benchmark's intentionally information-sparse setting. The Gemini writer therefore receives four explicitly separated evidence layers: measured Order data, computed temporal/pathway summaries, declared experimental context, and source-traceable literature retrieved from the selected RAG collections.

The objective is not a limitation-only document. The objective is a defensible, data-grounded biological model that identifies the most informative insulin-responsive PTM programmes, explains how they relate to the declared cell model and treatment, compares them with literature, states competing interpretations where necessary, and proposes discriminating follow-up experiments. Direct enzyme–site attribution and causal edge claims remain separately gated.

## 2. Evidence layers and allowed synthesis

| Layer | Input | What Gemini may state | What Gemini may not state |
|---|---|---|---|
| **O1 measured observations** | site/protein quantitative trajectories, q-values, PTM–protein contrasts, replicated detection, figures | the measured pattern, magnitude, timing label, and PTM–protein decoupling | values or sites absent from the packet |
| **O2 computed analyses** | pathway enrichment, Wave/Dynamic annotations, TMM candidate context, cross-layer observational lag | observed coordination, pathway membership, early/intermediate/late programme, motif-compatible candidate context | temporal adjacency as causal regulation or a direct kinase edge |
| **O3 declared study context** | cell type, organism, treatment, engineered receptor/transgene, time grid, biological question | why the measured programme matters in the stated biological system | an unstated treatment, cell model, or disease context |
| **O4 source-traceable literature** | section-specific RAG excerpts and provided PubMed references | agreement, contrast, and a literature-informed biological hypothesis with citations | a literature edge as if measured in the current Order |
| **O5 hypothesis** | deterministic synthesis of O1–O4 | the best-supported model, alternatives, and concrete validation priority | a hypothesis as a confirmed direct mechanism |

The direct kinase provenance summary (P0–P3) is a short **scope note**, not the Report's narrative centre. In an R3=0 Order, it limits only the language for direct kinase–site or perturbation claims; it does not prohibit biological interpretation of measured pathways, trajectories, candidate programmes, or literature comparison.

## 3. Required synthesis packet

Before section writing, the Report pipeline must build a deterministic `biological_synthesis_packet.v1` with no benchmark truth, locked score, inhibitor outcome, or LLM-generated claim as input. It must contain the following aggregate and data-backed cards.

| Card | Required content | Intended Report role |
|---|---|---|
| Study frame | actual cell model, organism, treatment, time grid, biological question, special engineered context | establishes why the data are biologically relevant |
| Quantitative landscape | measured site/protein counts, regulated/de novo counts, condition-level distribution | Results opening and abstract methods/findings |
| Temporal programmes | Wave/co-wave summary, reproducibility, early/intermediate/late profile labels, transition counts | describes reorganisation without declaring shared kinase control |
| Pathway anchors | Figure 1 pathway name, direct NES/FDR/term, supporting measured site count | connects enrichment to measured observations |
| Candidate observation cards | selected PTM/protein trajectories with actual values, site/protein relation, timing and pathway membership | provides named biological anchors for Results and Discussion |
| Literature comparison queries | data-derived system, pathway, and candidate-gene queries; retrieved excerpts with source identifiers | supplies citation-ready contextual interpretation |
| Hypothesis cards | observation → literature-consistent interpretation → alternative explanation → discriminating measurement | creates an actionable biological model |
| Evidence scope note | P0–P3 compact aggregate and direct-attribution status | limits direct kinase/site wording once, without dominating prose |

Candidate selection must be deterministic, traceable to supplied quantitative records, and diverse across the most supported pathway/time-programme anchors. It must not select a candidate because a benchmark workbook, known insulin relation, curated direct kinase relation, or RAG prose says it is important.

## 4. Data-anchored RAG retrieval

The current generic query pattern, `section + cell type + treatment + question + phosphorylation + signaling`, is insufficient. It produces broad background references and can over-weight canonical cascade prose. The replacement retrieval plan must create a compact, labelled query set per Report section:

| Query role | Template | Used in |
|---|---|---|
| System context | `{cell model} {treatment} phosphoproteomics {biological question}` | Introduction, Discussion |
| Pathway comparison | `{treatment} {pathway anchor} phosphorylation temporal` | Results, Discussion |
| Candidate biology | `{candidate gene} phosphorylation {treatment or pathway anchor}` | Results, Discussion |
| Temporal programme | `{treatment} phosphoproteomics early late signaling response` | Discussion, Conclusion |

Each retrieved excerpt must retain its query role, query text, collection, title, score, and source type. The writer may use references only as **literature context**: “consistent with”, “contrasts with”, “extends”, “raises the possibility”, or “motivates testing”. A retrieval labelled as a direct kinase cascade may not be generated when the current Order lacks directed temporal evidence or direct attribution.

## 5. Section-specific writing contract

### Results

Results starts with the quantitative landscape and then explains the strongest observed programmes. It uses pathway anchors, temporal profile labels, PTM–protein contrasts, and figures. It may call a pathway *enriched*, *modulated*, *activated*, or *inhibited* only when the supplied enrichment term permits that word. It may describe a phosphosite as higher/lower abundance; it must not call a kinase active solely because a substrate score or generic network diagram exists.

### Discussion

Discussion performs the intellectual synthesis. Every major biological paragraph should follow the pattern: **observed quantitative programme → pathway/candidate context → cited literature comparison → model or alternative → discriminating experiment**. This permits substantial biological interpretation without converting it into a direct enzyme–site claim.

### Abstract and Conclusion

These sections summarise the strongest observed programmes and the study-specific biological model. They should name the actual treatment and cell model and cite the principal evidence boundary once. They must not collapse a conceptual literature map into a verified receptor-to-substrate cascade.

### Evidence scope note

P0–P3 aggregates are emitted in one compact paragraph/table in Results or Limitations. They must not appear as raw `DATA-*` labels, candidate identities, accession, peptide, site, PMID, or full-ledger records.

## 6. Figure semantics

Figures can strengthen interpretation only if their captions and writer context use the same ontology as the evidence packet.

| Current unsafe figure language | Required replacement |
|---|---|
| activated/inhibited PTM | higher/lower measured PTM abundance unless an explicit functional-site sign is supplied |
| signaling cascade / signal transduction flow | literature-context pathway map or compartmentalized biological context diagram |
| gray arrows show canonical signal flow | dashed connectors indicate literature/pathway context only; they do not establish an Order-specific direction, direct regulation, or causality |
| kinase–substrate interaction evidence | network/pathway annotation; direct kinase–site attribution is reported only from P2 R3 and remains no-call in the current Order |

### Deterministic final rendering

The final renderer must expose the following compact records even when an LLM omits them. First, the P0–P3 readiness note is inserted once after Results using only the existing aggregate evidence record; it never serializes full-ledger identities, candidate edges, accession, peptide, sequence, source PMID, or raw provenance values. Second, the selected P5 cards are rendered as a compact discovery table. A conventional card may show its observed profile, peak, measured magnitude, and available q-value context. A de novo card must show only detection pattern, confidence and the frozen confidence-weighted capped LOD-relative selection effect; it must never show a conventional or control-pseudocount log2FC.

Figure 4 and all supplementary pathway/cascade diagrams are context-only by default. They use the title **Contextual Signaling Map** or **Compartmentalized Signaling Context Diagram** and dashed non-directional connectors. A directed figure edge can be enabled only if the compact direct-attribution status explicitly equals `perturbation_supported_direct_kinase_attribution`; legacy annotation, motif compatibility, pathway membership, RAG prose, receptor context and TMM candidate scores cannot enable it.

The writer receives section-local literature subsets. Before final assembly, local `[N]` citations are converted to identity-based `PMID`, `DOI`, or normalized-title markers. The final renderer resolves those markers in first-appearance order and generates the bibliography from the same resolved records. A bare local numeric citation whose identity cannot be recovered is removed rather than being matched to an unrelated bibliography entry.

A Chroma collection or internal paper-bundle label without paper-level author, year, PMID or DOI metadata is retrieval provenance, not a bibliography entry. It must be excluded from the final reference list rather than being displayed as a journal or paper citation. The final postprocessor also renumbers research-question headings after batch assembly and collapses repeated Markdown table separator rows.

### Co-Wave and protein-abundance interpretation safeguards

The canonical Wave-fitting universe is `complete_case_no_imputation`. A missing site-timepoint remains missing, is excluded from the rectangular Wave-fitting input, and is never converted to a biological zero. The compact Report packet must display the eligible and excluded input counts with this policy so that the reader can distinguish reduced coverage from an observed inactive state.

Dynamic Co-Wave transition totals are exposure-dependent descriptive counts. The Report must place them beside same-Wave candidate-pair scope, non-evaluable window exposure, LOTO stability, and the persisted global adjacency-order test status. A transition count, local co-membership, or sampled-timepoint order cannot be used as a measure of biological effect size, proof of chronological ordering, common kinase control, direct regulation, or causality.

For a PTM–protein comparison, onset and peak values are **observed sampled-timepoint differences**. They are not continuous-time estimates and do not establish a biological lag, upstream/downstream relation, transcriptional programme, or a PTM-to-protein mechanism. Condition-level protein abundance is a parallel observation, not a stoichiometry or occupancy measurement. Accordingly, Report prose uses “protein-abundance-adjusted PTM change” or “PTM-specific regulation adjusted for protein abundance,” and may not claim phosphosite occupancy, complex stoichiometry, or phosphorylation stoichiometry.

Pathway anchors must carry deterministic q-value wording. Only `q < 0.05` anchors are rendered as FDR-supported/statistically significant enrichment. An available `q >= 0.05` is a top-ranked descriptive pathway trend, and an unavailable q-value is annotation/context only; neither may be called significant or enriched. Free-form legacy Co-Wave, non-PTM, TF and pathway helper prose is not injected into Results, Research Question Answers, Discussion, Abstract, or Conclusion; the audited temporal and biological synthesis packets are the sole Report route for these interpretations.

### Representation and membership safeguards

Every Report consumer that accepts a vector row must use the shared provenance-based de novo detector. A declared `Conventional_Log2FC_NA`, control-pseudocount flag, or de novo activity class takes precedence over the numerical field itself; a pseudo-Log2FC is never supplied to the full-vector prompt, compressed vector ranking, per-condition conventional statistics, figure context, heatmap colour scale, or candidate priority. Eligible de novo evidence is instead supplied only through detection pattern, confidence and the existing frozen capped LOD-relative `Ranking_Score`. Conventional numeric contrasts remain measured observations, but their magnitude is descriptive and cannot by itself be presented as biological priority.

The final Methods section renders this exact reporting policy once: **“Large conventional Log2FC values are retained as measured numeric contrasts, but are not used alone to infer biological priority, mechanistic importance, or direct regulatory strength.”** This policy preserves quantitative observations and does not alter thresholds, candidate scoring, or direct-attribution gates.

The canonical sidecar writes `co_wave_membership_audit.tsv`, containing static Wave ID and immutable site-key membership in deterministic order. This is a user-facing audit artifact, not a compact sidecar field and never an RAG/LLM input. Until a dedicated per-Wave enrichment result is computed and persisted, a Report may discuss per-Wave counts and transition annotations but may not assign a functional module, pathway enrichment or common regulator to an individual Wave.

When the persisted global adjacency-order null test is not computed or does not support temporal order, Dynamic Co-Wave remains a local sampled-timepoint annotation. The writer must not call it robust, significant, validated or globally temporally resolved; transition totals retain their exposure/LOTO context only.

## 7. Claim ceiling: narrow, not silencing

For an Order with `direct_attribution=no_call`, `R3=0`, or `P3=not_evaluable_or_no_candidate_set`, prohibit only these claims:

1. a named kinase directly phosphorylated a named measured site in this Order;
2. a Wave, co-wave transition, or lagged PTM–protein record caused or controlled another record;
3. the Order demonstrated receptor-to-effector propagation, feedback, phosphatase activation, or a therapeutic response;
4. inhibitor/perturbation-supported language without uploaded matched outcomes.

The same Order may still state that its observed programme is consistent with, contrasts with, or extends a cited biological model; may identify motif/TMM-compatible candidate kinase-family context; and may propose a ranked hypothesis for testing.

## 8. Implementation acceptance tests

1. A Report with valid Order context and RAG sources includes a data-grounded biological model rather than a limitation-only narrative.
2. The Results and Discussion contain named, quantitative observation cards and source-traceable literature comparisons.
3. `DATA-*` labels, full-ledger identity, raw candidate-edge records, and benchmark/locked-score inputs never appear in Report/RAG/LLM prompts.
4. When `R3=0`, direct kinase/site and causal edge claims are blocked, while pathway- and literature-grounded biological synthesis remains permitted.
5. Figure context and caption prompts use measured-abundance and literature-context language, not generic signal-flow assertions.
6. RAG query telemetry records system, pathway, candidate, and temporal query roles; direct-cascade retrieval is disabled when the current Order lacks its required evidence.
7. The final Markdown/DOCX includes the P0–P3 aggregate readiness/no-call note and selected P5 discovery cards without raw full-ledger or de novo pseudo-log2FC leakage.
8. A no-call Order renders Figure 4 and all supplementary cascade diagrams with dashed context-only connectors and no activation/inhibition arrow grammar.
9. Every final bibliography entry corresponds to a resolved collection-local or PubMed reference identity; section-local numeric citations cannot point to a different paper after global assembly.
10. The final Report states `complete_case_no_imputation` and its input exclusions when persisted, reports Dynamic Co-Wave totals with exposure/LOTO/null status, and never turns a sampled-timepoint difference into a continuous biological lag or mechanism.
11. A q≥0.05 pathway anchor is rendered as a top-ranked descriptive trend rather than significant enrichment; protein-abundance-adjusted PTM values are never labelled occupancy or stoichiometry.
12. A conventional-NA/de novo row with pseudo-Log2FC of any magnitude is rendered through detection/LOD context only; it cannot enter generic vector ranking, statistics, figure colour scale or biological-priority prose.
13. The static Wave membership audit is deterministic and separate from compact Report/RAG/LLM payloads; Report text does not assign per-Wave function when no persisted per-Wave enrichment is present.
14. A missing or unsupported global adjacency-order null blocks robust/significant/global-order Co-Wave wording, and final Markdown contains globally unique Q headings and no consecutive table separator rows.

## 9. Methodological references

PhosR documents the value of retaining site, residue, gene, sequence-window, and optional localisation information in phosphoproteomic analysis and supports site-/protein-centric pathway analysis and signalome construction. Wu *et al.* show why protein-expression changes need to be considered when interpreting differential phosphopeptide abundance. These principles support PTM-Vector's use of explicit feature provenance and PTM–protein contrast rather than a naïve activation narrative.

1. [PhosR Bioconductor vignette](https://www.bioconductor.org/packages//release/bioc/vignettes/PhosR/inst/doc/PhosR.html)
2. [Kim *et al.* (2021), Protocol for the processing and downstream analysis of phosphoproteomic data with PhosR](https://pmc.ncbi.nlm.nih.gov/articles/PMC8190506/)
3. [Wu *et al.* (2011), Correct Interpretation of Comprehensive Phosphorylation Dynamics Requires Normalization by Protein Expression Changes](https://www.mcponline.org/article/S1535-9476(20)30185-7/fulltext)
