# Enrichment-free primary A profile v2

Select **Enrichment-free time course: primary A + frozen kinase + Astra** in the
order's sample-design settings. This is an explicit full-matrix rat/Rat_hir
phosphorylation profile. It produces a deterministic evidence report and portable
Astra package in the preprocessing Celery queue; the legacy precursor estimator,
RAG manuscript and temporal vector pipeline are separate profiles.

Required: complete sample manifest with biological material IDs, unique condition
times with Control at zero, enrichment-free declaration, explicit normalization
policy and a registered frozen annotation SHA-256. Quick analysis, protein
subsetting and secondary cross-talk matrices are rejected. Use supplied intensities
without extra scaling to reproduce the HIRcB reference. DIA-NN upstream normalization
and acquisition metadata remain `unknown` unless explicitly supplied.

Register the frozen snapshot on the API and worker's shared reference volume:

```sh
PYTHONPATH=. python scripts/register_frozen_annotation.py \
  --snapshot /inputs/omnipath_rat_enzsub.tsv \
  --audit-dir /inputs/kinase \
  --sha256 <verified-sha256> --reference-root /app/data/reference
```

The audit directory contains `annotation_metadata.json` with `database_sha256` and
the original retrieval timestamp. Source audit/PMID files are copied when supplied.
Rat_hir additionally requires its custom rat + human INSR FASTA in the registered
`rat_hir` reference directory. No reference is downloaded implicitly.

The API dispatches the complete calculation from original PR/PG through form A,
frozen footprints, strict alternate parent, late protein evidence and export.
The primary input is `primary_A_input.csv`, described by
`primary_input_contract.json`. U/P are explanation/QC channels. The original
`kinase_profiles.csv` keeps seven v1 modes; separate v2 comparison tables expose
all-observed and joint-mask U/P. A = U_joint − P_joint holds at form level;
gene/site medians do not preserve this identity at aggregate score level.

Alternate-parent default is `strict_unmodified_parent_paired_ratios.v2`: for each
unmodified peptide use the PTM/PG/peptide common injection mask, contrast mean
log2(PTM/peptide), then median across at least two sequences. Each condition needs
at least two common observations. The v1 separate-means result and the v2 complete
form-mask sensitivity are retained separately. Peptide masks and exclusion reasons
are exported. This default was selected before comparing the new results.

Baseline-undetected emergence is connected to curated candidates without invented
baseline fold-change. `eligible_A` gates mapping/parent eligibility;
`raw_candidate_A` preserves numerical diagnostics. Different post-reference times
must not be pooled as baseline effects. Strict kinase attribution remains no-call
when localization is unknown. The held-out late layer is retrospective,
same-experiment evidence, not preregistration, independent replication or causality.

Every run writes an immutable directory under `enrichment_free_runs/<run_id>`.
Input hashes, design, normalization factors, annotation hash, estimator versions
and order/run IDs are pinned in `provenance.json`; each exported file has a manifest
entry. The report, primary input and Astra download reference the same provenance.
Copy preserves the settings but creates a new run. All rerun stages route through
the full primary-A profile. Runs recompute rather than reusing a result cache.
Editing order settings never relabels a completed run. Downloads verify checksums.

`GET /api/orders/{id}/enrichment-free-evidence` returns the recorded run. Its
`artifact` query accepts `astra`, `report`, `report_markdown`, `primary_input`, or
`provenance`. The Primary A evidence tab displays the recorded run and downloads.
The ZIP's `rerun.py <new-output-directory>` recomputes all scientific CSV tables
offline. The deterministic platform report and input contract are also in the
platform export; platform registration is not recreated by the portable replay.

Validation scripts:

- `validate_hircb_followup.py`: original v1 tables and declared v2 diagnostic counts.
- `validate_hircb_platform.py`: actual localhost API/MySQL/Redis/Celery create,
  copy, settings edit, rerun and checksum-verified downloads. Requires the isolated
  validation account and inputs; never run on production.
- `validate_primary_a_browser.py`: authenticated local Chrome result view,
  actual downloads and preserved settings in the Copy dialog.

Scientific CSV reproduction across Python/numpy/pandas environments is checked
numerically with matching missing masks and text, at atol=rtol=1e-10. Byte equality
is reported separately; tiny floating representation differences are not silently
reported as byte equality.
