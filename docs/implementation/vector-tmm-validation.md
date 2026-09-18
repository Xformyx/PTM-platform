# Vector / temporal TMM 구현·검증 기록

기준 HEAD와 원격 main: `b150a010fc6374239eec0a2b1d88922d6b871c27`. 저장소는 `Xformyx/PTM-platform`, 브랜치는 `main`, 시작 working tree는 clean이었다. 적용 가능한 AGENTS.md를 repository/상위 경로에서 찾지 못했다. 원자료, 과거 revision, benchmark truth/baseline/preregistration을 변경하지 않았다. 현재 commit은 `git log`로 확인한다.

이 기록은 2026-09-18 상세 명령서의 구현에 해당한다. 앞선 report 통합 계약을 교체하지 않고 pinned inventory/packet handoff를 확장했다. **로컬 구현과 synthetic 검증이 진행되었으며 전체 운영/과학 완료 gate는 아직 통과하지 않았다.** 아래 미완료 항목을 실행하지 않은 테스트의 통과로 집계하지 않는다.

## 단계 상태와 활성 경로

| 단계 | 변경/활성 경로 | 로컬 증거 | 남은 제한 |
|---|---|---|---|
| 1 | annotation_context, vector_projection/vector_plot left join | mixed-case baseline 탈락 재현 후 case/context/charge 충돌 회귀 | 실제 주문의 “18개” 원인 비중 미확인 |
| 2 | plot_selection → service → real GET route | N=2 조건별 4 features/8 rows, global 2/4, RAG 독립 | rag_only 대량 TSV 비용 |
| 3 | typed vector_view.v2, admin/user 공유 controls/chart | TS build, source/mode/count, 실제 chart/browser | 과거 모든 client 버전 배포 시험 미실행 |
| 4 | coverage partitions, row lineage/quarantine/export, annotation cursor | malformed/unknown/conflict/0/null, cursor roundtrip | 대규모 실제 source 시험 미실행 |
| 5 | V fixtures + HTTP + TypeScript + browser | 아래 계층별 V 매핑 | 실주문/staging 미실행 |
| 6 | immutable input → full candidate ledger → API/RAG 공통 service → report | display/RAG budget 불변 job/signature/score, subset/full pointer 분리 | 지원 종별 실제 reference 배포 검증 미실행 |
| 7 | common feature allocation v2, complete signature, bounded_compute/legacy errors | T fixtures, unresolved-only는 completed/not_evaluable/null | 모든 legacy route의 429/504 fault injection 미실행 |
| 8 | production Celery queue/worker, DB job/head, immutable attempts, registry download | 실제 API+SQLite+executor 단계 실패/cancel/redelivery/fencing/tamper | MySQL/Redis/Celery kill/restart/lease 운영 검증 미실행; heartbeat/watchdog 로컬 lock 회귀만 실행 |
| 9 | Parquet/Canvas/full distribution/drilldown/lasso/windowed heatmap, candidate cursor/Canvas line | 1만/10만/100만 행 counts/extrema, 100만 행 browser, 40,000셀 viewport | 완전한 SLO/heap peak/pan 시험 미완료 |
| 10 | indexed medians, SVD geometry reuse, block Pearson, condensed/memmap wave, streamed pair/LOTO events | 기존 exact 결과와 수치/사건/LOTO 회귀 | 대규모 TMM timing/peak RSS/독립 scientific calibration 미실행; 새 approximate wave 미도입 |

계약: [vector view](../vector_view_contract_v2.md), [analysis universe](../analysis_universe_contract.md), [execution/revision](../tmm_execution_and_revision_contract.md), [allocation 변화](../tmm_allocation_change.md).

## 재현된 실패와 예상 변화

- Mixed-case projection/metadata fixture: baseline에서 Rps6/Akt1이 빠지고 INSR만 남았다. 수정 후 세 feature 모두 유지한다. annotation 수정은 ID/값/p/q/mask를 바꾸지 않는다.
- shared identical-profile fixture: baseline에서 shared `[1,2,1]`이 두 kinase 합 `[2,4,2]`로 복제됐다. v2는 group 한 건 `[1,2,1]`, 개별 shared contribution 보류다. 기존 점수 변경이 예상되므로 재계산 revision이 필요하다.
- unresolved-only fixture 추가 중 미실행 bootstrap의 NaN이 strict stage JSON을 실패시켰다. 기존 diagnosis serializer와 evaluated 상태를 사용해 null로 전달했다. 관측 수와 scoring-evaluable count를 분리하여 관측이 있다고 individual score=0 성공으로 표시하지 않는다.
- 첫 browser smoke에서 null 위치의 phantom dot 때문에 5개 대신 9개가 그려졌다. finite dot renderer 적용 후 5개다. null gap은 연결하지 않으며 point-only feature는 남는다.
- 초기 10만 행 columnar 구현은 materialized wide JSON/sort 때문에 512MB DuckDB 제한에서 실패했다. streaming COPY/row groups/spill로 수정한 뒤 100만 행까지 보존 시험을 실행했다. 최초 실패를 성공 성능으로 집계하지 않는다.
- large Heatmap smoke의 첫 스크롤 실패는 harness에 실제 CSS가 빠져 overflow class가 적용되지 않은 경우였다. production build CSS를 포함한 재시험에서 마지막 행의 zero/null과 bounded DOM을 확인했다.
- frozen expected values는 수정하지 않았다. 정확한 최적화는 float64 numeric/mask/conditional policy를 보존한다. scientific thresholds/prior/normalization 변경은 하지 않았다.

## 실행 환경

macOS 15.6.1 arm64, Apple M4 Max, logical CPU 14개, RAM 38,654,705,664 bytes (36 GiB). Python 3.14.6, pytest 9.1.1, NumPy 2.5.3, pandas 3.0.5, SciPy 1.18.1, FastAPI 0.141.1, Celery 5.6.3, SQLAlchemy 2.0.52, DuckDB 1.5.5. Node 24.8.0/npm 11.6.0, Playwright 1.63.0, Chrome 153.0.8010.50. npm을 사용했으며 lockfile을 재작성하지 않았다. API와 worker suite의 app import 경로를 분리했다.

Docker daemon 연결이 실제로 불가능했다. 운영 DB/Redis/Celery, 실제 order PR/PG/FASTA/reference bundle/credential이 없었다. dependency 없는 skip은 통과로 집계하지 않는다. 아래 Python suite에는 skip이 없었다. 최종 Python 회귀는 API/shared 변경 범위 80, worker/report 129, shared/benchmark-boundary 43개로 총 252 passed/0 failed/0 skipped다. Node tests 9개도 모두 통과했다. 마지막 no-call coverage handoff 변경은 해당 lifecycle/handoff 회귀를 추가 실행했다. 실제 XML count와 scale/browser JSON 요약은 [machine-readable 결과](vector-tmm-validation.json)에 보존한다.

## 실행 명령

아래 `$PY`는 이번 검증의 격리 환경 `/tmp/ptm-integration-20260917-venv/bin/python`이었다. repository root에서 실행했다. 결과 XML과 임시 합성 산출물은 `/tmp/ptm-vector-validation`에 기록했다. 원자료를 문서/로그에 복사하지 않았다.

```sh
PYTHONPATH=.:api-server $PY -m pytest -q api-server/tests/test_tmm*.py api-server/tests/test_analysis_job_lifecycle.py api-server/tests/test_vector_plot_contract.py api-server/tests/test_vector_plot_http.py api-server/tests/test_vector_view_api_v2.py api-server/tests/test_bounded_compute.py api-server/tests/test_benchmark_tmm_runner_contract.py ptm_shared/tests/test_vector_view_v2.py ptm_shared/tests/test_vector_columnar.py ptm_shared/tests/test_exact_temporal_optimizations.py ptm_shared/tests/test_temporal_feature_input.py ptm_shared/tests/test_kinase_trajectory_evidence.py ptm_shared/tests/test_tabular_import.py --junitxml=/tmp/ptm-vector-validation/api-final.xml

PYTHONPATH=.:workers:workers/tests $PY -m pytest -q workers/tests/test_report_vector_projection.py workers/tests/test_quantitation_estimator_contract.py workers/tests/test_temporal_sidecar_resolution.py workers/tests/test_tmm_identifiability.py workers/tests/test_tmm_multikinase_integration.py workers/tests/test_temporal_wave_contract.py workers/tests/test_de_novo_representation.py workers/tests/test_flow_finalization.py workers/tests/test_report_rendering_fidelity.py workers/tests/test_flow_finding_retrieval.py workers/tests/test_flow_sample_units.py workers/tests/test_analysis_inventory_model_handoff.py --junitxml=/tmp/ptm-vector-validation/workers-final.xml

PYTHONPATH=. $PY -m pytest -q ptm_shared/tests/test_temporal_wave*.py ptm_shared/tests/test_dynamic_cowave*.py ptm_shared/tests/test_tmm_*.py benchmarking/tests/test_runtime_boundary.py --junitxml=/tmp/ptm-vector-validation/shared-final.xml

# 마지막 no-call coverage handoff 변경 후 재실행: 각각 8 passed, 10 passed.
# 위 252개와 중복되는 회귀이므로 총 통과 수에 다시 합산하지 않는다.
PYTHONPATH=.:api-server $PY -m pytest -q api-server/tests/test_analysis_job_lifecycle.py
PYTHONPATH=.:workers:workers/tests $PY -m pytest -q workers/tests/test_analysis_inventory_model_handoff.py workers/tests/test_temporal_sidecar_resolution.py

# frontend 디렉터리
node --experimental-strip-types --test tests/quantitation.test.ts tests/vectorView.test.ts
# repository root
npm --prefix frontend run build
git diff --check
```

실제 규모 시험은 동일 generator로 10,000/100,000/1,000,000 행 각각 fresh directory에서 실행했다. 재현 가능한 저장소 CLI로 옮긴 뒤 10,000행을 다시 실행했다. 전체 tuple/count/extrema 검사를 포함한다.

```sh
PYTHONPATH=. $PY scripts/validate_vector_scale.py 10000 --output /tmp/ptm-vector-validation/scale-script-10000
PYTHONPATH=.:api-server:api-server/tests $PY scripts/build_vector_ui_fixture.py --output /tmp/ptm-vector-validation/ui-release-fixture
frontend/node_modules/.bin/esbuild frontend/tests/vectorView.browser.tsx --bundle --platform=browser --format=iife --jsx=automatic --outfile=/tmp/ptm-vector-validation/browser-current.js
$PY scripts/validate_vector_ui.py --fixture-dir /tmp/ptm-vector-validation/ui-release-fixture --bundle /tmp/ptm-vector-validation/browser-current.js --css frontend/dist/assets/index-BOig9xVd.css --browser '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' --output /tmp/ptm-vector-validation/ui-final-all
```

browser scale은 동일 query methods를 호출하는 임시 runner `PYTHONPATH=. $PY /tmp/ptm-vector-validation/browser_scale.py`로 실행했다. 재실행 가능한 CLI는 `scripts/validate_vector_browser.py --artifact-dir ... --bundle ... --browser ... --output <fresh-directory>`다. 이 CLI로 옮긴 뒤의 별도 scale 재실행은 기록하지 않는다. browser screenshot과 CDP heap snapshot은 synthetic fixture 검증이며 production network/staging은 아니다.

Vite build는 성공했으며 기존 큰 bundle/Browserslist 경고가 남는다. standalone IIFE smoke bundle은 실행하지 않는 CrossTalk worker의 import.meta 경고가 있다. production Vite build는 별도 worker asset을 생성한다. CrossTalk worker의 실제 browser scheduling 성능 시험을 time-series smoke와 혼동하지 않는다.

## fixture 검증 수준

| 요구 ID | 실행 증거 |
|---|---|
| V01–V07 | shared typed fixtures; HTTP에서도 mixed case, empty/failed/partial RAG |
| V08–V10 | shared+real HTTP TSV/Parquet의 union/global/all times, ties/order |
| V11–V16 | shared null/nonfinite/denominator/unresolved/conflict/rag scope/annotation partition; columnar full export |
| V17 | frontend index/count + 실제 checkbox/browser에서 선정 수 유지 |
| V18–V19 | selection hash/revision/annotation 독립 shared+HTTP |
| V20 | LatestRequest/inflight promise 시험 + 실제 component의 N=2 응답을 보류했다가 N=1 응답 뒤 전달하는 browser race 통과 |
| T01–T02 | scorer shared group 보존, candidate/module 순서·중복 불변 |
| T03–T05 | 기존 identifiability, signed/magnitude, prior, masks, adaptive uncertainty, iterative regression |
| T06–T08 | full manifest hash member/weight/31번째 candidate/context/config 변경 |
| T09 | bounded child timeout/busy 시험, legacy exception passthrough 수정; full HTTP fault injection 미실행 |
| T10 | 실제 executor score 후 diagnostics failure/disk error: completed/pointer 승격 없음 |
| T11 | caller await 취소 후 실제 child 종료 전 slot 재배정 금지 |
| T12 | LOD missing/partial/representation 기존+새 fixture, unresolved-only null/no-call |

## 규모 측정 결과

모든 행은 4조건 합성 입력이고 feature 수는 행 수/4다. 원자료의 biological n을 뜻하지 않는다. 기본 full density는 64 bins, browser는 한 조건의 96 bins라 payload 크기를 혼용하지 않는다.

| source rows | identified features | finite density observations | ingest s | full density query s | response bytes | peak process RSS bytes |
|---:|---:|---:|---:|---:|---:|---:|
| 10,000 | 2,500 | 9,896 | 2.166 | 0.0108 | 16,303 | 265,748,480 |
| 100,000 | 25,000 | 98,969 | 21.516 | 0.0831 | 17,477 | 274,939,904 |
| 1,000,000 | 250,000 | 989,690 | 212.639 | 1.0023 | 17,991 | 708,624,384 |

모두 source row/count/ID/null roundtrip과 extrema X=[-2.5,2.5], Y=[-40,40]를 보존했다. 조회한 200 features의 전체 800 timepoint rows를 회수했다. 새 CLI 10,000행 재실행은 ingest 2.189s였으며 이전 run을 대체하지 않고 별도 보존한다.

100만 행 browser: manifest 270 bytes, 실제 density response 302,424 bytes, 200행 exact coordinates 18,436 bytes. CDP used heap **snapshot** 18,402,660 bytes, DOM 1,028개(200행 상세 table 포함), drill 0.329s, hover event 0.0197s, page errors 0. peak heap, 첫 유효 표시, pan SLO를 측정한 값은 아니다.

실제 time-series component: 3 precursor, finite dots 5, SVG line containers 3. gap path가 끊어지고 checkbox 변경으로 selection label은 바뀌지 않았다. 실제 job executor가 만든 K1 결과를 Kinase Modules/Heatmap에 넣어 page errors 0을 확인했다. 500×80=40,000셀 virtual Heatmap과 전체 Canvas 궤적은 마지막 행 접근 시 DOM 342개, 0/null 보존, errors 0이었다. 모든 궤적에서 빠진 조건 40의 Canvas pixel column에 그려진 픽셀은 0이었다. evidence SSR 시험을 chart browser 시험으로 보고하지 않는다.

## 미완료 gate / 배포 전 필요 사항

운영 입력과 실제 reference snapshot 대조, species별 매핑 정확성, 실제 API→Redis→Celery→report provider→export→UI staging, MySQL 동시 submit/publish race, worker kill/API restart/broker redelivery/stale lease, heavy-job health/login latency, 물리 disk-full/resource exhaustion 시험이 남아 있다. 별도 heartbeat thread, stale attempt fencing, 만료 lease에서도 실제 lock이 살아 있으면 재할당하지 않는 회귀는 로컬 SQLite/실제 flock으로 실행했다. 지금 수행한 실패 주입은 SQLite executor 수준이다.

heartbeat/watchdog와 candidate cursor/Canvas line/annotation cursor를 구현했으나 운영 환경의 장애 회복 및 큰 TMM의 단계별 성능/자원 SLO 검증은 남아 있다. 이 항목 때문에 전체 명령서의 완전 완료로 표시하지 않는다. 새로운 approximate wave/약한 신호 estimator는 별도 사전 평가 대상이며 이 변경에서 임의로 활성화하지 않았다.

실제 LLM 저술/문헌 source-faithfulness, 새 DOCX/PPTX/PDF 실제 운영 render, domain expert/holdout/perturbation 기반 독립 scientific evaluation은 미완료다. local schema/render regression 통과는 생물학적 타당성 인증이 아니다.
