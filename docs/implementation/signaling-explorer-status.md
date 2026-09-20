# Signaling Evidence Explorer implementation record

Specification: integrated 2026-09-19 v2. Base: remote main
`37590202aad42243dba8976595854599b6ecaf34`. Working branch:
`feat/signaling-evidence-explorer`. No applicable AGENTS.md found. Initial tree
clean. Scatter commit `923203ee0b83657cec8f7830aba71f771ee0df64` is in main.
No production deployment or new main merge is authorized by this work record.

## Resume point

Latest continuation and remaining work are recorded under “Resumed implementation”
at the end of this file. Machine-readable evidence: `signaling-explorer-validation.json`.

PR01 baseline inspected; PR02–05 component/bundle/API/UI integration implemented
in the working tree and undergoing acceptance review. PR06 optional transparent
KSEA-z/ULM/MLM and partial linear comparison tracks are wired into the durable
worker; magnitude TMM is an explicitly requested comparison. Existing
analysis inputs/results and scatter remain immutable. No external experimental
data, production order access, or domain review supplied. G1–G5 are unevaluated.

## Baseline, actually executed

2026-09-19, Python 3.14 isolated project environment:

```
PYTHONPATH=.:api-server DATABASE_URL=sqlite+aiosqlite:///:memory: /tmp/ptm-integration-20260917-venv/bin/python -m pytest -q ptm_shared/tests/test_vector_view_v2.py ptm_shared/tests/test_scatter_overview.py api-server/tests/test_vector_view_api_v2.py api-server/tests/test_analysis_job_lifecycle.py benchmarking/tests/test_runtime_boundary.py
```

40 passed, 1 dependency deprecation warning, 0 skipped, 3.39 s. These are
synthetic contract/API/worker tests; not live Celery/MySQL or operational orders.

## Inspection findings (code evidence, not operational impact)

| ID | Current status and owner |
|---|---|
| F01 | Present: analysis_universe / production_analysis full_eligible; preserve |
| F02 | Open: context_loader/pathway_expansion still use enriched population |
| F03 | Open: no immutable Explorer bundle |
| F04 | Open: legacy Atlas GET computes from enriched input |
| F05 | Open: receptor refresh context candidate handling needs separation |
| F06 | Confirmed in scorer: insufficient exclusive profiles use Gaussian |
| F07 | Confirmed code boundary: signed target versus nonnegative profiles |
| F08 | Not yet independently rechecked: receptor downstream preview |
| F09 | Not yet independently rechecked: receptor/pathway entity typing |
| F10 | Existing order completion is not an analysis readiness contract |
| F11 | Confirmed: allocation ratio is whole-trajectory, not per-time switching |
| F12 | Preserve: full_eligible applies to frozen input scope |
| F13 | Confirmed: profile eligibility currently counts exclusive feature keys |
| F14 | Confirmed: all_observed and user Modules return before kinase panel |
| F15 | Confirmed: module_response hardcodes confirmed=0 / inferred=all |
| F16 | Not yet independently rechecked: legacy Atlas validation/cap |
| F17 | Present: bootstrap/LOTO options, production defaults 0/false |
| F18 | Confirmed: production Wave call omits replicate_time_series; no-replicate consensus can become computed/0 |
| F19 | Present: complete-case projection records incomplete grid exclusions |
| F20 | Existing GP/biological/event machinery; no default promotion planned |
| F21 | Open: no run-level unified validation registry |
| F22 | Historical benchmark must not be relabelled production validation |
| F23 | Confirmed: temporal_wave_benchmark expected windows multiply discovery scores |
| F24 | Present: all_evaluated versus retained wave sets; downstream audit pending |

## Acceptance tracking

A01–A39: not accepted for the new Explorer yet. Baseline tests above protect
existing vector/scatter/full-universe/job contracts; they do not establish the
new Explorer acceptance conditions. Each subsequent entry must name actual
commands, outcome, numeric impact and remaining limitations. PR01–08 remain
in progress/unimplemented until their active producer/consumer paths are tested.

Research: G0 incomplete; G1–G5 not_evaluated (independent data unavailable).
No new default model promotion, biological accuracy or calibration claim.

## 2026-09-20 checkpoint (work in progress, not a completion declaration)

- New branch is based on latest fetched main. No original scatter source changed.
- Actual production executor now creates pathway/validation/Explorer artifacts
  and an immutable bundle before fenced DB publication. Legacy result v1 stays
  readable; new result v2 requires the additional artifacts. Read endpoints use
  existing order authorization and verify component checksums.
- A canonical local pathway snapshot adapter uses provider/ID/taxon/release,
  full precursor input and exact protein accession membership. Current metric is
  a descriptive mean of protein medians, **not** Direct NES/ORA or activation.
  Missing reference is not zero coverage. No real reference bundle was supplied.
- Admin and user use the same Explorer; user Modules no longer depends on RAG
  Top N. Legacy observations use the existing vector route, scatter unchanged.
- Wave consensus without usable repeats is null/not_evaluable. Paired biological
  matrices from the validated adapter resample whole units across time.
- Exclusive profile support can use measurement groups (new production policy),
  and unsupported Gaussian priors are withheld in new discovery runs. Legacy
  profile policies remain explicit replay options. Signed-negative shared input
  remains a declared limitation of the signed model; magnitude is comparison-only.
- Benchmark discovery ranking ignores expected windows; historical prior-assisted
  mode is explicit and output overwrite is rejected. Frozen truth/baselines untouched.
- Reports receive pinned pathway values/typed value bindings and component
  revisions. Report sealing records the source analysis; a derived report bundle
  is appended after sealing. Report binding tests and claim browsing remain pending.

Actual checks since baseline:

```
PYTHONPATH=.:api-server DATABASE_URL=sqlite+aiosqlite:///:memory: /tmp/ptm-integration-20260917-venv/bin/python -m pytest -q api-server/tests/test_analysis_job_lifecycle.py
# 8 passed
PYTHONPATH=.:workers /tmp/ptm-integration-20260917-venv/bin/python -m pytest -q workers/tests/test_temporal_wave_contract.py
# 4 passed
PYTHONPATH=.:api-server DATABASE_URL=sqlite+aiosqlite:///:memory: /tmp/ptm-integration-20260917-venv/bin/python -m pytest -q api-server/tests/test_explorer_scientific_boundaries.py api-server/tests/test_analysis_job_lifecycle.py api-server/tests/test_signaling_explorer.py
# 14 passed, 1 dependency warning
PYTHONPATH=.:workers /tmp/ptm-integration-20260917-venv/bin/python -m pytest -q workers/tests/test_analysis_inventory_model_handoff.py workers/tests/test_flow_finalization.py workers/tests/test_report_rendering_fidelity.py
# 64 passed, 3 matplotlib deprecation warnings
cd frontend
npm run build
# tsc + production Vite build passed; existing size/Browserslist warnings
```

An initial incorrect shared Wave test filename ran no tests. A second combined
API/worker invocation failed collection because worker imports were absent.
The separate worker invocation above succeeded; collection failures are not passes.

Browser: actual shared component and CSS, responses generated through real
synthetic API/worker fixture, Chromium. 7 scenarios passed; browser errors 0;
no write requests. Evidence: `/tmp/ptm-explorer-20260919-browser-01/result.json`,
`trace.zip`, desktop/mobile PNGs. Includes points, hover, zoom, track changes,
late pathway response, 390px layout and retry. This is not authenticated
production E2E. Browser skill was read; its control tool was unavailable, so
approved local Chromium fallback was used. Fixture generator and browser runner
are in scripts/. Later code changes require a fresh final run.

Next: complete report/evidence bindings and numeric/registry audits; test optional
comparison adapters and large inventory queries; finish remaining PR06–08
implementation and acceptance scope. External data, live services, scientific
holdouts and actual production-order verification remain unavailable.

## Continued checkpoint — 2026-09-20

- Report descendants now append a verified index over sealed authoring cards,
  retrieved assertions and paragraph evidence bindings. Explicit IDs only; no
  gene-based inferred binding. Actual route tests verify original analysis bytes,
  parent queries, descendant queries, idempotency and source-timeout preservation.
- Numeric Parquet observations speed view ranking without changing membership.
  120,000 synthetic features × 6 declared conditions: all 120,000 preserved;
  702,857 finite observations (17,143 missing slots). New query benchmark at
  `/tmp/ptm-explorer-20260920-scale-02/benchmark.json`: warm p95 overview 0.0154 s,
  feature page 0.1108 s, Top N 0.6820 s (previous JSON path 4.1249 s).
  Build 19.14 s; process peak RSS 1,408,073,728 bytes. macOS15.6.1 arm64, 14 CPUs,
  Python3.14.6. Derived index/query only; no network/browser/concurrency SLO claim.
- Chromium `/tmp/ptm-explorer-20260920-browser-02`: 8 scenarios passed, exit0,
  browser errors0, GET-only requests. Includes Top N projection plus prior7 cases.
  Source/fixture SHA manifest, stdout, exit code, screenshots and trace retained.
  Later backend changes require validation against a fresh final fixture.
- TMM/production lifecycle/registry/benchmark boundary suite: 45 passed, one
  dependency warning, 6.21s. Frontend quantitative/vector/scatter Node tests:
  12 passed, zero skipped. Production tsc/Vite build passed (known bundle-size and
  Browserslist warnings remain).
- Blind admission now excludes treatment/expected target/display labels from the
  calculation context. Three treatment names reuse the same job; prior-assisted
  replay is explicit. Updated API/lifecycle subset: 13 passed, 3.70s.
- A new report test exposed pathway supporting cards being dropped at maximum
  prompt compaction. Fixed supporting-plan evidence propagation and tested the
  actual plan→focus→section path: 2 passed. The preceding worker run had 73 passes
  and this one failure; it is not recorded as all-pass. One mistyped nonexistent
  test filename collected no tests; that invocation is also not a pass.

Next actions: rerun affected report regression; finish acceptance mapping,
source/claim browsing and missing PR06–08 work. No commit/push/merge/deployment of
this Explorer work yet. No real-order or independent-scientific success claim.

## Resumed implementation — 2026-09-20 (latest checkpoint)

### State inspected before editing

HEAD remained `37590202aad42243dba8976595854599b6ecaf34` on
`feat/signaling-evidence-explorer`; origin is `Xformyx/PTM-platform`.
Inspected status, tracked diff, untracked source/tests, recent commits, both
Explorer records and applicable ancestor instructions. No applicable AGENTS.md.
No changes were reset, discarded, staged, committed or pushed. Existing scatter
recovery is already in HEAD and its reader/component files remain unchanged.

Already implemented before this continuation: immutable analysis bundles,
full-inventory pathway projections, read-only Explorer routes, shared admin/user
component, report descendant binding, Wave missing-replicate status, explicit
comparison adapters and a runner-only evaluation module. Previous synthetic
checks exist, but do not establish that all PR01–08 requirements are complete.

Partially complete before this continuation: report packet compaction regression
had only a narrow rerun; report/evidence browsing was first-page-only; optional
model adapters lacked durable-worker acceptance checks; benchmark parity did not
compare biological design, time grid or primary track. Research algorithms and
operational acceptance remain partial as described below.

### Implemented and verified in this continuation

- Re-ran the previously interrupted report regression successfully, including
  plan → focus → compacted section evidence binding.
- Reproduced retrieval prompts/provider output leaking into the source-runs API
  with a failing real route test. Added a public field allowlist and
  `report_explorer_index.v2`. Versioned index paths preserve earlier bytes;
  incompatible v1 report indexes fail explicitly instead of exposing traces.
  Source spans, source hash, prompt hash, identity, timeout and review state stay
  available. No source-faithfulness or biological validation is inferred.
- Added complete cursor access for kinase, contribution, evidence, report claim,
  source, validation, comparison, hypothesis, suggestion and unmapped-module UI
  lists. Each cursor belongs to its URL/scope. Component errors can retry without
  discarding observed curves. Added model-specific paged result queries and UI.
- Added authenticated `GET .../inventory-export`: a bounded-memory JSONL stream
  over the same base-plus-report index as the API, with bundle/revision/scope
  metadata. The earlier button exported only the base analysis and omitted the
  report's assertions/claim links. This is a streaming read, not a queued custom
  export job; that separate requirement remains pending.
- Corrected legacy U-curve labeling and connected stored `top_n_ptms` as the
  initial display N in both parents. Preserved tab keys. Removed the admin
  single-timepoint gate that prevented otherwise usable result browsing.
- Registered requested comparison outcomes separately: three completed adapters
  plus unavailable raw proDA input now reports a partial comparison component,
  while preserving the signed primary result. Added production scorer →
  two-window comparison and real job → comparison artifact tests.
- Extended engine parity to `engine_parity.v2`: biological sample manifest,
  condition grid, primary track and inference mode must also agree. Missing
  legacy fields prevent an equivalence claim; they do not rewrite old results.
- Broad regression found an already-stale AST fixture missing `cache_hash`.
  `orders.py` was unchanged from HEAD. Updated the fixture to assert that both
  feature values AND analysis signature must match, and that missing legacy
  signatures cannot reuse a sidecar. No production cache protection or frozen
  benchmark expectations were relaxed.

Numerical impact of this continuation: primary TMM arithmetic and thresholds are
unchanged. The actual fixture still yields K1 up-footprint 8 at 5min. Page changes
preserve the five-feature browser inventory and complete trajectories. The
report descendant now exposes all 105 evidence records and 103 paragraph links
for its synthetic feature, including records beyond page one. These counts are
software-fixture accounting, not independent papers or scientific validation.

### Actual final validation

Logs and exact command arrays:
`/tmp/ptm-explorer-20260920-resume-validation/`.

| Check | Actual outcome |
|---|---|
| API/shared/TMM/vector/scatter/runtime-boundary suite | 113 passed, 0 skipped, 1 dependency warning, 8.09s |
| Worker/report/figure/quantitation/retrieval suite | 86 passed, 0 skipped, 3 matplotlib warnings, 20.97s |
| Node quantitative/vector/scatter helpers | 12 passed, 0 skipped |
| `npm run build` | TypeScript and production Vite build passed; existing bundle-size/Browserslist warnings |
| Chromium shared component | 14 scenarios passed, browser errors 0, read-only GET requests |
| `git diff --check` | passed |

The first broad API run was **112 passed / 1 failed**, due to the obsolete AST
fixture. Its `api_shared.log/json` is preserved. Successful rerun is
`api_shared-rerun.log/json`. The prompt-disclosure regression also failed before
its fix. Failures have not been counted as successful runs.

Browser evidence: `/tmp/ptm-explorer-20260920-browser-05/result.json`,
`stdout.log`, `exit-code.txt`, `trace.zip`, desktop/mobile/evidence/legacy PNGs.
Fixture: `/tmp/ptm-explorer-20260920-fixture-05/`, including actual API/worker
responses, complete export and source hash manifest. This final manifest hashes
backend/shared and frontend source dependencies, not only the top component.
Earlier browser-03 passed 12 scenarios; browser-04 was not run because later
source edits required a fresh fixture. Browser-05 includes chart points, hover,
zoom, missing occupancy, U track, Top N, evidence and claim pagination/citation,
late feature/pathway responses, local error retry, model-result selection,
parent/report bundle switching, TSV-only legacy U and 390px layout.

The Browser skill was read. No browser-control tool was available after tool
inspection; the existing local Chromium harness ran with approved execution
permission. It mounts the real component/CSS and uses real synthetic API/worker
responses. This is **not** authenticated admin/user-page or production-order E2E.
No login/production credentials or real raw data were used.

### Acceptance mapping and remaining work

“Verified” here means the named synthetic software boundary, not full research
acceptance. IDs with broader requirements remain partial even when one fixture
passes.

| IDs | Evidence now available | Remaining boundary |
|---|---|---|
| A01–03 | blind admission, display-budget lifecycle invariance, independent vector/scatter contracts | adversarial filename/query leakage and deployed references not evaluated |
| A04–08 | signed/magnitude mirror, profile duplication guard, group allocation tests | signed primary negative-shared limitation remains; distinct peptides at one confirmed site and prior ablations need additional work |
| A09–14 | null/zero/partial-grid, precursor identity, sample/estimator, pathway ambiguity tests | no operational species/isoform/detection study evaluation |
| A15–18 | empty-RAG-independent access, full membership, late pathway/evidence response and group tests | authenticated parent-page E2E and complete canonical entity harmonization pending |
| A19–21 | condition contribution states, public source status, source spans/citation IDs and sealed report links | broad contradictory-source/domain faithfulness evaluation pending |
| A22–25 | preproc-only state, immutable parent/descendant, cancellation/fencing tests, TSV-only browser | live MySQL/Redis redelivery/process-kill/race/backfill/rollback validation pending |
| A26 | prior 120,000-feature × 6-condition index benchmark and bounded pages/export | final service/browser/concurrent 720,000-row performance not measured |
| A27–30 | GET-only browser, API no-write checks, typed report pathway values, order/bundle guards, unmapped querying | complete raw replicate/QC drilldown and broad report/Explorer field equivalence still partial |
| A31–32 | engine parity v2, absent-replicate null, real paired matrix test | production-equivalent scientific benchmark and complete validation-policy registry pending |
| A33–34 | partial-linear/KSEA-z/ULM/MLM and conditional window adapter tests, durable optional outcomes, model-result UI | R/proDA solver not installed/run; MSstatsPTM, package parity and biological holdout not complete |
| A35–38 | group/no-call representation, missing metric gates, conditional hypotheses/proposals | signed mechanism comparison, hierarchy, open-set/calibration and independent module replication pending |
| A39 | frozen runner refuses output overwrite; no promotion granted | external evidence-bound promotion gates not evaluated |

Next unfinished implementation priorities (do not redo completed scatter work):

1. Full product acceptance: complete independent site/protein support accounting,
   validation registry coverage (Atlas/null/LOTO/cross-layer), raw replicate/QC
   drawers, canonical identity harmonization and legacy receptor context boundary.
   Inspection confirmed old receptor refresh still truncates `downstream_ptms`
   before specificity calculations and Reactome display names are parsed as
   receptor candidates. Those legacy paths are not used by the new Explorer,
   but have not been repaired or removed here.
2. Reference deployment/backfill and provenance: supply/verify an actual canonical
   pathway bundle; test old schema backfill into a new immutable bundle and
   explicit current-pointer rollback. Report claims without explicit feature IDs
   remain context-only; broader linkage must not guess from gene strings.
3. PR06–08: finish applicable quantitation/partial/hierarchical/signed-network
   comparisons and source-bound scientific evaluation interfaces. The current
   two-window NNLS is conditional comparison only, not a hierarchical model or
   evidence of kinase switching. Conditional experiment suggestions are not
   evaluated information-gain predictions. Keep new defaults unpromoted.
4. Run live services, full authenticated admin/user browser flows, failure/retry/
   concurrent publication and end-to-end scale tests. Independent datasets and
   perturbations/domain review are needed for G1–G5. Their absence does not make
   the remaining software tasks complete.

No PR01–08-wide completion claim, production deployment, main merge, new commit
or push was made in this continuation. The requested local fixes and checks above
are complete; the larger integrated specification remains partially implemented.

Final fixture integrity recheck: all 322 recorded source dependencies match the
final fixture; response SHA-256 matches. Desktop and 390px legacy/mobile PNGs
were also visually inspected. No benchmark truth or baseline file was modified.
