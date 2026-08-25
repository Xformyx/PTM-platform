# Locked PTM Benchmark Framework

`benchmarking/` is an **offline evaluation package**. It is not part of `ptm_shared`, worker code, RAG, report generation, or the LLM runtime. Its role is to load an already archived blind-analysis artifact, open a dataset-specific locked reference, calculate scores, and write an auditable bundle.

## Boundary

The production blind analysis receives the 0층 product pipeline and 1층 temporal-science contract, but never receives the workbook, truth JSON, anchor names, expected kinase names, or score output. The scorer runs only after the analysis artifact is archived. L3/L4 representation artifacts are excluded from the primary score.

## Insulin v1 build command

```bash
PYTHONPATH=. python3 -m benchmarking.cli build-insulin-reference \
  --workbook /path/to/Insulin_Signaling_Phospho_Kinase_Benchmark_v1.xlsx \
  --output-dir benchmarks/insulin_signaling_v1
```

The generated manifest fixes the primary contract to `tmm_full_temporal.v1`, requires sequence+isoform+species anchor mapping, keeps Tier 3/4/de novo candidates out of canonical accuracy, and records source/truth hashes.

## Score an archived blind artifact

```bash
PYTHONPATH=. python3 -m benchmarking.cli score \
  --manifest benchmarks/insulin_signaling_v1/insulin_signaling_v1.manifest.json \
  --analysis-artifact benchmark_runs/<run_id>/blind_analysis_artifact.json \
  --output-dir benchmark_runs/<run_id>/locked_score
```

The artifact must provide truth-free `site_availability` and `site_observations` rows. These use generic `gene` and `site` fields and **must not carry workbook `Anchor_ID` values**. The scorer assigns locked anchor IDs only after blind analysis completes. Each availability or observation row needs a `mapping_evidence` object that confirms `sequence_match`, `isoform_match`, and `species_match`; gene/site-only matching is rejected from scoring.
