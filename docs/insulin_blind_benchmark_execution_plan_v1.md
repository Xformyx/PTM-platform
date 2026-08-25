# Insulin Phospho-Kinase Blind Benchmark: Execution Plan v1

## 1. Objective and Scientific Boundary

This plan evaluates whether PTM-platform can recover coherent temporal kinase
programs from a rat HIRc-B phosphoproteomics time course **without being told
that the stimulus is insulin or being given an insulin-specific biological
question**. The supplied workbook, `Insulin_Signaling_Phospho_Kinase_Benchmark_v1.xlsx`,
is the locked reference for scoring, not an input to the discovery run.

The benchmark contains a rat HIRc-B, human-INSR-overexpressing, unenriched
DIA-NN use case. It explicitly distinguishes measurable Tier 1/2 anchors from
Tier 3/4 interpretation-only sites; supports interval-censored time windows;
requires protein-normalized phosphopeptide interpretation; and keeps de novo
events separate from canonical accuracy. These rules must be preserved.

> The blind phase measures recovery under constrained prior knowledge. It does
> not prove that a general-purpose LLM has no pretraining knowledge of insulin
> signaling. Because the observed data can contain INSR/AKT/MAPK proteins, the
> benchmark must be described as **stimulus-blind and question-blind**, not as
> completely knowledge-free.

## 2. Pre-Registration and Information Partitioning

Before any new benchmark run, make a dated, hashed copy of the workbook and
freeze the run configuration. Do not alter anchor definitions, Tier labels,
time windows, scoring weights, detectability decisions, or negative controls
after seeing the output of the algorithm variant being evaluated.

| Asset | Location / access rule | Role |
|---|---|---|
| `analysis_input/` | Platform input only | PR/PG matrices, sample configuration, Rat_hir FASTA |
| `benchmark_locked/` | Scorer only; never passed to RAG/LLM | Original workbook, anchor truth, temporal windows, known kinase truth |
| `blind_run_manifest.yaml` | Platform and scorer | Run ID, input checksums, version, blind policy, time grid, thresholds |
| `blind_context.md` | Platform only | Generic question and generic treatment wording |
| `reveal_context.md` | Post-score interpretation only | Insulin identity, branch names, workbook literature context |
| `result_bundle/` | Immutable after run | Raw platform outputs, config snapshot, logs, scored tables, figures |

Use the existing **Rat_hir** custom reference. The mixed FASTA must contain the
human INSR entry with accession, `GN=INSR`, and `OX=9606`; the order-level
species remains rat. This avoids false negative mapping caused by human/rat
residue-number offsets.

### Blind context policy

The discovery run should receive no word such as `insulin`, `INSR`, `AKT`,
`PI3K`, `ERK`, `mTOR`, `glucose transport`, or `HIRc-B` in the biological
question. A suitable generic question is:

> “Identify reproducible temporal PTM programs, candidate kinase activities,
> candidate upstream regulators, temporal relationships, and the highest-value
> hypotheses for follow-up validation from this treatment-versus-control time
> course.”

The external Co-Scientist mode must either be disabled in the primary blind
run or receive the same generic context. For a strict literature-blind
sub-analysis, use a collection allowlist that excludes insulin-specific papers
and store its collection identifiers in the manifest. A second,
literature-assisted run may then be evaluated separately; it must never be
merged with the primary blind score.

## 3. Phase A — Input Qualification Before Benchmarking

Perform these checks without assessing pathway correctness.

| Check | Required action | Pass condition |
|---|---|---|
| Species/site mapping | Map by peptide sequence, isoform, residue, and FASTA taxon | Human and rat site numbers stored separately; no residue-number-only match |
| Time axis | Declare `0, 1, 5, 15, 30, 60, 180 min` or actual acquired grid | Numeric minutes preserved; no index-only lag calculation |
| Protein normalization | Compute PTM log2FC minus matched protein log2FC where possible | Activity claims use normalized PTM evidence or state missing normalization |
| Replicates | Register number of replicates and rule before scoring | Regulated call requires predeclared replicate/statistical criterion |
| Detectability | Decide measurable/NA before scoring recall | Unmeasurable pTyr anchors do not enter denominator |
| De novo PTMs | Track control detections, treated detections, first interval, persistence | No infinite or arbitrary fold change enters canonical score |

Export a mapping table containing workbook Anchor_ID, observed peptide,
accession, FASTA taxon, human site, rat site, localization confidence, and
mapping status. This table is an audit artifact, not an algorithm output to
optimize.

## 4. Phase B — Primary Stimulus-Blind Discovery Run

Run the platform with the locked manifest and generic biological question.
Preserve the full output rather than only the final report:

1. Preprocessing and mixed-FASTA provenance output.
2. Protein-normalized PTM matrix and missingness/QC records.
3. Canonical Temporal Wave results, membership, thresholds, and stability.
4. Kinase evidence before and after TMM, including raw/TMM co-wave provenance.
5. TMM contribution matrix, sparse-profile flags, residuals, and confidence.
6. Directionality D-tier records and time-order/null-test metadata.
7. Multisite divergence observations and evidence gates.
8. Receptor/upstream-regulator candidates.
9. Data-Grounded Analysis questions, hypotheses, data verification, and final
   report text.

No benchmark anchor name, branch name, expected direction, expected window,
or known inhibitor target may enter this run.

## 5. Phase C — Locked Scoring

Score only after the blind run has been archived. Use Tier 1/2 anchors for
canonical accuracy; Tier 3/4 sites and de novo observations are reported in
separate discovery panels and cannot increase canonical accuracy.

### 5.1 Anchor-level measures

| Metric | Numerator / denominator | Interpretation |
|---|---|---|
| Detectable anchor recall | Detected Tier 1/2 anchors / measurable Tier 1/2 anchors | Acquisition and identification recovery |
| Regulated anchor recall | Regulated anchors / measurable anchors | End-to-end regulatory recovery |
| Direction accuracy | Correct phosphosite direction / regulated anchors | Biological sign recovery |
| Peak-window accuracy | Compatible peak window / regulated anchors | Temporal recovery under interval censoring |
| Chain support | Supported branch-layer relationships / evaluable branch relationships | Mechanistic coherence |
| Evidence-weighted composite | Workbook weights: detection 25%, regulation 25%, direction 20%, peak 20%, chain 10%; Tier 1=2, Tier 2=1 | Summary only; always report component scores |

For inhibitory sites such as GSK3A S21/GSK3B S9 or EEF2K regulatory sites,
store phosphosite direction and inferred kinase activity direction in distinct
columns. A correct rise in inhibitory phosphorylation must not be scored as a
rise in kinase activity.

### 5.2 Kinase-level and branch-level measures

Do not use ROC/AUC unless a pre-registered negative kinase universe exists.
Instead report rank and recovery measures that respect the partial truth set.

| Level | Primary measures |
|---|---|
| Kinase | Expected kinase/module Top-1, Top-3, Top-5 recovery; reciprocal rank; rank shift across time windows; TMM contribution concordance |
| Wave | Stable Wave recovery; expected early/late branch placement; directionality tier distribution |
| Branch | Macro-averaged branch score for receptor-proximal, PI3K–AKT, RAS–ERK, mTORC1/S6K, feedback/recovery; avoid output-heavy branches dominating |
| Specificity | Negative-control/stress-module activation rate, unsupported high-confidence receptor rate, false positive kinase-module rate |

### 5.3 Required figures

Generate each figure with bootstrap confidence intervals over anchors and, when
available, replicate-resampling intervals. Do not display a single composite
as the only result.

| Figure | Question answered |
|---|---|
| Weighted component bar chart with CI | Where does recovery succeed or fail: detection, regulation, sign, timing, or chain? |
| Branch-by-metric heatmap | Are PI3K–AKT, MAPK, and mTORC1 recovered evenly? |
| Anchor temporal-window matrix | Which anchors match early, intermediate, late, recovery windows? |
| Cumulative Top-k kinase recovery curve | Does the correct kinase/module reach useful rank? |
| Observed-versus-reference layer graph | Are at least two ordered layers recovered per branch? |
| Failure taxonomy stacked bar | Which errors are acquisition, mapping, regulation, direction, timing, attribution, or interpretation failures? |
| TMM confidence/contribution panel | Are correct calls driven by data-anchored profiles rather than sparse prior-assisted fallback? |
| Discovery-only panel | QC-surviving de novo/unscored sites, explicitly excluded from canonical accuracy |

## 6. Phase D — Error Taxonomy and Algorithm Improvement Loop

Every false negative, false positive, and wrong-time call must be assigned one
primary category before changing the algorithm.

| Error category | Diagnostic evidence | Appropriate response |
|---|---|---|
| Acquisition/detectability | Peptide absent or below assay-level detectability | Exclude from measurable denominator; do not tune algorithm |
| Species/isoform mapping | Sequence or residue mismatch, human-vs-rat numbering conflict | Correct mapping/provenance only |
| Localization ambiguity | Multi-site peptide or uncertain modification localization | Score at module/partial-support level or exclude strict anchor |
| Protein abundance confounding | PTM change disappears after protein normalization | Do not call kinase activity from raw PTM alone |
| Regulation threshold | Replicate/statistical criterion fails | Revisit only predeclared analysis threshold through a separate version |
| Temporal discretization | Correct interval but wrong exact minute | Score compatible window; do not call failure |
| Kinase ambiguity | Broad motif, shared substrate, high TMM entropy/collinearity | Improve candidate set/TMM confidence rather than force winner |
| Sparse TMM profile | Prior-assisted or insufficient exclusive substrates | Downgrade confidence; do not use as primary improvement evidence |
| LLM/RAG interpretation | Data output correct but narrative overstates or misses it | Change prompt/evidence gate, not core scoring |

Create an immutable comparison ladder. Each version changes one evidence layer
and runs against the identical locked input and scorer.

```text
V0  Current baseline
V1  Canonical Wave + stability only
V2  V1 + TMM fractional contribution
V3  V2 + temporal precedence/D-tier
V4  V3 + multisite divergence evidence gate
V5  V4 + AI/RAG interpretation guardrails
```

Accept an algorithm change only if the pre-registered primary metric improves
with confidence intervals, no essential branch suffers a material decline, and
the gain remains after mapping/detectability exclusions. Do not tune repeatedly
against the entire insulin workbook. Preserve a held-out branch subset or,
preferably, a separate stimulus/dataset for final confirmation.

## 7. Phase E — Independent Kinase-Inhibitor Validation

This phase occurs **after** the blind insulin benchmark is scored and the
algorithm version is locked. It is external validation, not an input to the
unbiased discovery run.

### 7.1 Pre-register the perturbation experiment

For each selected kinase/branch, use a factorial contrast where feasible:

```text
vehicle control
insulin only
inhibitor only
insulin + inhibitor
```

Use matched acquisition, FASTA, time grid, replicate structure, protein
quantification, and QC rules. The early insulin grid must retain enough points
to test the predicted onset/peak interval. Select inhibitor targets only after
the blind result has identified high-confidence, biologically coherent D2/D3
candidate programs; record the selection rule before examining inhibitor data.

### 7.2 Pre-register expected readouts

The validation endpoint is not that every PTM vanishes. The expected signature
is a **branch-selective attenuation** relative to insulin-only, adjusted for
inhibitor-only and vehicle response.

| Platform readout | Expected validation signature |
|---|---|
| Target kinase activity score | Rank/activity reduction in insulin + inhibitor relative to insulin |
| TMM contribution | Reduced target-kinase fractional contribution for relevant shared sites |
| Target substrate Wave | Reduced amplitude, delayed onset, or loss of persistence in predicted target Wave |
| Directionality | Predicted downstream relationship becomes weak, unresolved, or delayed |
| Competing branch | Remains stable or follows a separately pre-registered crosstalk rule |
| Negative-control modules | No indiscriminate loss of all kinase activity |

Calculate the interaction contrast at each site or Wave:

```text
inhibitor-specific insulin effect
= (insulin + inhibitor − inhibitor only)
− (insulin only − vehicle)
```

Apply the expected-site activity sign before interpreting inhibitory regulatory
phosphosites. Upload the resulting condition-scoped evidence only through the
platform's post-analysis perturbation evidence layer, so it cannot modify the
original discovery run.

## 8. Required Implementation Work Packages

| Work package | Deliverable | Acceptance condition |
|---|---|---|
| Benchmark manifest | Versioned YAML/JSON schema with input hashes, blind policy, time grid, thresholds, scorer version | Re-running a manifest reproduces all rows and figures |
| Locked scorer | Workbook parser and site/sequence-aware matcher | Cannot be imported by analysis/RAG runtime; writes anchor-level audit table |
| Blind-mode policy | Generic question template, RAG collection allowlist/blocklist, context audit log | No insulin-specific benchmark field enters primary run |
| Metrics and figures | Machine-readable score JSON/TSV plus figure set | Components, branches, intervals, and discovery-only results remain separate |
| Error review table | One row per evaluated anchor with failure category and resolution | Algorithm changes trace to a category, not anecdote |
| Inhibitor validator | Condition-aware contrast evaluator and report appendix | Perturbation result is separate from discovery and supports only scoped claims |

## 9. Decision Gates and Deliverables

| Gate | Decision question | Deliverable |
|---|---|---|
| G0 | Are mapping, detectability, time axis, replicates, and protein normalization ready? | Input qualification report |
| G1 | Does the stimulus-blind baseline recover Tier 1/2 anchors and coherent branches? | Locked score table + figure bundle |
| G2 | Are failures predominantly algorithmic rather than acquisition/mapping limitations? | Error taxonomy and version-change proposal |
| G3 | Does one pre-registered algorithm change improve primary and branch-balanced metrics? | Version-comparison report |
| G4 | Does independent inhibitor data show branch-selective attenuation predicted by the locked model? | Perturbation validation appendix |
| G5 | Does a held-out stimulus/dataset retain performance? | Final generalization report |

The final claim should distinguish four layers: measured anchor recovery,
condition-specific kinase attribution, observational temporal precedence, and
independent perturbation-supported validation. Discovery yield remains an
important output, but it must never inflate canonical insulin benchmark
accuracy.
