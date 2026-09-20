# Signaling Explorer implementation contract (work in progress)

Base: `37590202aad42243dba8976595854599b6ecaf34`. Branch:
`feat/signaling-evidence-explorer`. This document describes implemented contracts,
not completion of PR01–08 or independent biological validation.

## Immutable components and execution

New durable results use `temporal_analysis_revision.v2`; legacy v1 stays readable.
The executor completes input validation, candidates, score, trajectory diagnostics,
temporal diagnostics, result, optional model comparisons and Explorer index before
publication. All additional artifacts enter the existing checksum registry.
Existing parent-generation checks, attempt token and DB publication fence remain.
Display requests never admit a job or fetch an external source.

`run_evidence_bundle.v1` binds the exact measurement, analysis, pathway, temporal,
annotation and report components. The initial bundle references analysis artifacts;
after a report is sealed, a new descendant bundle references its immutable report
registry. Report source bindings reference the parent bundle, avoiding a circular
hash dependency. Old bundles and numeric files remain unchanged. Failed or late
report publication cannot modify the analysis bundle. Derived report joins are
registered under `.evidence_runs`; they never feed numeric analysis.

The report index reuses sealed `reader_cards`, finding retrieval references and
`structured_decode_audit`. It joins only explicit feature/evidence IDs. Source
quotes retain content hash, offset, scope, disagreement and unverified claim status.
Search timeout remains timeout. No internal prompts/provider output are exposed.
Report claim links record the existing paragraph index and retained/withheld state;
this is a source-trace link, not certification of the biological claim.

## Read API

The `/orders/{id}/evidence-runs` family uses existing order sharing/authorization.
Manifest, pathways, features, contributions, evidence, source-runs, validations,
model-comparisons, model-results, report-claims and unmapped-modules are read-only.
`trajectory-query` is a read-only batch POST (maximum 100 IDs); artifact downloads
are restricted to registered names. Integrity failure yields an explicit conflict.
The run list currently exposes the latest 100 jobs and reports that list scope.

Cursor binding includes bundle, filters, sorting, unit, mode and N. Page size is
bounded (500 maximum); this never truncates the stored inventory. A page cursor
cannot be reused for another pathway or bundle. Whole-artifact export streams the
registered file; custom asynchronous export jobs remain unimplemented.

Feature views support inventory, all-observed, global Top N and per-condition
Top N union. Abs(effect) rankings use a single named track and stable feature ID
tie-break. Selected features retain their complete observed time courses. The
global analysis denominator is returned separately. Kinase/module filters query
existing membership; they do not recompute global kinase scores. No annotation
availability gate is applied to measured features.

## Pathways

`PTM_PATHWAY_SOURCE_BUNDLE_PATH` optionally points to an immutable JSON snapshot
with `schema_version=canonical_pathway_reference.v1` and `pathways` records:
provider, native_id, taxon, release, name, protein_accessions; parent relationships
may be included. Admission pins its SHA-256; worker copy must match before use.
Missing snapshot is unavailable, not successful zero coverage. No production
reference bundle or reference deployment has been supplied or verified here.

Identity is provider/native ID/taxon/release, not the display name. Exact scoped
protein membership is protein context, not site-function or enzyme–site evidence.
Multi-protein ambiguity stays in membership but is withheld from summary values.
All precursor curves remain separate. Background is taxon-specific.

The current implemented metric is `mean_of_protein_median_adjusted_contrast`,
method `full_input_pathway_contrast.v1`: median observed precursor contrasts per
protein, then mean of pathway proteins. It is descriptive, with p/q null. It is
not NES, ORA, pathway activation or a biological replicate test. Existing contrast
values and their estimator remain unchanged. New inferential pathway statistics
need a separate method/version and evaluation; they are not implemented here.

## Numeric corrections and comparisons

New production TMM results use `temporal_mixture_model_full_precursor.v3`.
Profile eligibility counts measurement groups (`measurement_group.v1`), preserving
feature crosswalks. Replicating charge forms cannot create independent anchors.
`observed_support_only.v1` withholds unsupported Gaussian profiles; actual observed
exclusive-substrate footprints remain available. Explicit Gaussian replay requires
`context_assisted`, with its own revision. No performance improvement is claimed.

`discovery_context.v1` separates design fields from treatment/expected target names.
New job signatures use computational context; the same input plus treatment-name
changes reuses a job. Temporal design and biological sample manifest are retained.
The blind report retrieval path receives design context without treatment identity.
Historical results are not rewritten. The Wave benchmark now freezes truth-free
ranking before evaluation; historical prior-assisted mode is separately named.

Signed primary TMM still has the documented negative shared-substrate limitation.
The optional `tmm_magnitude.v1` comparison preserves original signed observations
and records a separate allocation ledger; it has not been promoted to the default.
No q/FC threshold, prior weight or signed/magnitude default was silently altered.

Optional `ksea_z.v1`, `ulm_t.v1`, `mlm_t.v1` are transparent NumPy/SciPy comparison
implementations, not claims of package-level parity. Effects are adjusted log2
contrasts; grouping, background, rank deficiency, missingness and BH family are
explicit. The KSEA z implementation uses the log contrast directly, not the
KSEAapp input adapter that expects a non-log ratio. MLM with rank deficiency
withholds individual scores. `partial_linear.v1` fits only observed real times;
predicted points never become observations. These models do not establish kinase
activity, correct-target probabilities, external accuracy or default promotion.

Method references: [KSEA source](https://github.com/casecpb/KSEA/blob/master/app.R),
[ULM definition](https://decoupler.readthedocs.io/en/v1.9.2/generated/decoupler.run_ulm.html),
[MLM definition](https://decoupler.readthedocs.io/en/stable/api/generated/decoupler.mt.mlm.html).

The registry distinguishes condition-mean noise sensitivity from biological-unit
resampling. Shared-fit evaluations count once per track/feature. Wave consensus
without usable repeats is null/not_evaluable; paired resampling uses the same
unit indices across time. Feature/site/protein counts are not biological n.

## UI, compatibility and rollback

Admin and user screens share `SignalingEvidenceExplorer`; existing tab keys remain.
Missing bundle falls back to the existing TSV vector observation route. The restored
scatter component/reader remain independent and unchanged. Zero is a point, missing
time is a gap; curves use actual minute spacing and occupancy is not filled from A.
Read requests have cancellation and ownership guards. Display state is not analysis
configuration. Old result/release provenance remains visible.

Rollback is code/config and explicit prior revision selection; it never deletes
raw files or completed revisions. An incompatible index is reported rather than
read under a different schema. Operational rollout/backfill/production verification
have not been performed. The shared browser harness is synthetic API/worker data,
not authenticated production E2E.

## Outstanding scope

PR06–08 are not complete: MSstatsPTM/proDA execution, hierarchical/time-varying TMM,
typed signed mechanism comparison, calibration/open-set research, external holdout
binding/promotion and experiment-selection algorithms remain outstanding. Rscript
is not installed in the validation environment. Actual independent data are absent.
G1–G5 remain not_evaluated. Full acceptance accounting, operational concurrency,
reference deployment, custom asynchronous export, broad source/claim coverage and
production-browser validation also remain to be completed.

## Resume changes, 2026-09-20

`report_explorer_index.v2` whitelists public retrieval accounting. Resolved prompts,
provider raw output and transport are excluded from reader APIs and full Explorer
export. Prompt/content hashes and source-span provenance remain. Indexes live
under a versioned report-revision directory. A v1 derived report bundle is
incompatible with this reader; republishing its already sealed report creates a
new v2 descendant without changing prior artifacts. The original analysis bundle
remains readable independently.

`GET /orders/{id}/evidence-runs/{bundle}/inventory-export` is a read-only JSONL
stream. Its first row binds bundle/revisions/scope/units; following rows are the
full typed inventory, including the descendant report index. It uses bounded
fetches and order authorization. It does not create an export job or new analysis.
Custom asynchronous filtered exports remain pending. Registered artifact download
continues to mean the specific original artifact, not an implicit merged export.

`model_id` filters model-comparisons/model-results and enters cursor binding.
Other component kinds reject that filter. Frontend pagination also retains bundle,
feature/pathway/track/model ownership. Component errors have an explicit retry;
late responses cannot replace another scope. Comparison component status reports
partial/unavailable when requested adapters did not complete, with per-model
reasons and completed/requested counts. No unavailable result is counted as a
successful estimate.

Engine parity v2 additionally requires identical sample-manifest hash, condition
grid, primary track and inference mode. Older comparator metadata missing those
fields stays a historical comparator. These changes do not alter primary TMM
arithmetic or promote any comparison model.

The existing optional proDA adapter and R script, two-window allocation adapter,
conditional intervention proposals and frozen evaluation runner now have synthetic
contract checks. proDA's R execution remains untested/unavailable here. The
conditional two-window model is not a hierarchical replacement; its individual
outputs are withheld on insufficient anchors/rank. Proposals depend on explicit
single-driver/selective-perturbation assumptions and are not executed experiments.
See the latest status checkpoint for pending scientific and product acceptance.
