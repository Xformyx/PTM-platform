# Unified Wave/Report Temporal Upgrade 검증 기록

**작성일:** 2026-08-29

**기준 remote:** `95d112b`

**검증 branch:** `agent/unified-temporal-upgrade`

## 1. 목적과 변경 경계

이번 변경은 서로 다른 두 문제를 해결한다. 첫째, strict benchmark가 결측 timepoint를 생물학적 0으로 채우고 production이 complete vector만 사용하는 차이를 제거하여 두 경로가 동일한 Wave fitting universe를 사용하도록 한다. 둘째, full sidecar의 `temporal_precedence` aggregate를 compact sidecar, Report numerical evidence packet, deterministic fallback, fidelity audit까지 전달한다.

Canonical Wave clustering, TMM coefficient·ranking, kinase score, locked benchmark truth 및 primary scorer는 변경하지 않는다. `transition_resolution`은 계속 local reorganization의 descriptive ratio이며 chronological-order evidence로 승격하지 않는다.

## 2. 구현

| 영역 | 구현 내용 | 안전 경계 |
|---|---|---|
| Shared Wave input | `temporal_wave_input_projection.v1`을 추가하고 strict/production이 `complete_case_no_imputation`을 공용 | missing measurement를 biological zero로 변환하지 않음 |
| Projection provenance | eligible/excluded site 수, exclusion reason, time grid, eligible-key SHA-256을 Wave contract에 저장 | raw value는 저장하지 않음 |
| Temporal precedence compact | status, evaluable count, tier breakdown, replicate mode, replicate no-call/partial-draw count, P4 gate를 aggregate | 개별 event time·raw matrix·known relation registry는 제외 |
| Report packet | `DATA-TEMPORAL-PRECEDENCE` record와 mandatory coverage group 추가 | observation timing만 기술하고 causality 금지 |
| Fidelity audit | `temporal_precedence` available/cited/untraced/review-required telemetry 추가 | 누락 시 deterministic fallback을 삽입 |
| Replicate bootstrap | all-NaN sampled column은 warning 대신 해당 draw를 no-call 처리 | evaluable draw fraction을 별도 보존 |
| Global order output | T-adjacency에 data-dependent verdict와 explicit claim boundary 추가 | p≥0.05이면 global chronological structure claim 금지 |

## 3. 동일 raw insulin sandbox 결과

동일한 6-point insulin input(`1, 5, 15, 30, 60, 180 min`)과 archived TMM payload를 사용했다. 분석 artifact를 먼저 truth-free로 생성한 뒤 locked scorer를 별도 runner에서만 실행했다.

| 지표 | 결과 | 판정 |
|---|---:|---|
| Raw site | 2,447 | 입력 |
| Complete-case eligible site | 2,022 | 425 incomplete site 제외 |
| Eligible-key SHA-256 | `e4a814cf...d6cb3a` | strict/production 동일 |
| Strict Wave member | 629 | parity |
| Production Wave member | 629 | parity |
| Member-set difference | 0 / 0 | **통과** |
| Temporal observations | 629 | immutable Wave scope와 일치 |
| Replicate-level bootstrap | 566 | condition-mean fallback 63 |
| Evaluable event record | 586 | not-evaluable 43 |
| Replicate bootstrap no-call | 7 | warning 대신 explicit no-call |
| Partial-draw replicate site | 131 | uncertainty aggregate 보존 |
| Runtime | 122.300 s | strict build+production sidecar+Report audit 포함 |
| Runtime warning | 0 | **통과** |

Fresh truth-free artifact SHA-256은 `306c19dc6a7740cea3bf4e6ef54c09867423fe23dac91c28dd8afe0465925a5e`이다.

## 4. Temporal statistics와 known-insulin score

| 평가 | 결과 | 해석 |
|---|---:|---|
| `transition_resolution` | 0.721642 | descriptive local reorganization only |
| Exact T-adjacency | 0.042559 | global adjacency statistic |
| Exact T-adjacency p | 0.153953 | **not significant** |
| Within-Wave onset synchrony | 0.2853 vs null 0.2254 | structural synchrony enrichment |
| Synchrony permutation p | 0.001996 | static Wave enriches onset-synchronous events |
| Canonical weighted score | 0.733333 | baseline non-regression |
| Kinase expected timing accuracy | 0.000000 | unresolved direct-evidence gap 유지 |
| Temporal layer coverage | 0.857143 | baseline 유지 |

따라서 이번 변경은 **strict/production consistency와 evidence handoff를 해결**했지만, global chronological-order significance를 새로 만들지는 않았다. `supports_global_temporal_order=false`와 `verdict=not_significant`를 artifact에 명시하여 Report가 이를 과장하지 못하도록 했다.

## 5. Report evidence와 fidelity 결과

`temporal_precedence_status`는 `report_temporal_evidence_packet.v3`의 `DATA-TEMPORAL-PRECEDENCE` record로 변환된다. Generic prose만 제공한 pre-fallback audit은 `review_required`였고 temporal precedence를 포함한 mandatory groups가 누락된 것으로 판정됐다. Deterministic fallback을 적용한 뒤 audit은 `pass`, `temporal_precedence_trace_status=cited`가 되었다.

Report 표현은 다음 범위로 제한된다.

> “관찰된 response timing aggregate와 replicate uncertainty를 기술한다. Direct kinase-substrate regulation, kinase switching, causal propagation 또는 perturbation-supported mechanism을 의미하지 않는다.”

## 6. 검증과 isolation

Expanded targeted suite **142개**가 통과했고 Python compilation 및 `git diff --check`도 통과했다. Production source 정밀 scan에서 workbook, locked score result 또는 locked truth가 `ptm_shared`, Report worker, API runtime으로 유입되는 참조는 발견되지 않았다. Raw replicate matrix/intensity/abundance도 sidecar observation에 저장되지 않았다.

## 7. Acceptance 판정

| Gate | 결과 |
|---|---|
| Strict/production same Wave universe | **PASS** |
| No missing-to-zero imputation | **PASS** |
| Canonical score non-regression | **PASS** |
| Compact→Report packet→fidelity trace | **PASS** |
| Warning-free replicate no-call | **PASS** |
| Truth/RAG/LLM isolation | **PASS** |
| Global chronological-order significance | **NOT ESTABLISHED** |
| Kinase timing accuracy improvement | **NOT ESTABLISHED** |

이번 code set은 engineering/scientific safety gate를 통과한다. 다만 global-order p-value나 kinase timing accuracy를 개선했다고 주장해서는 안 된다. 해당 문제는 relation-level event-order calibration과 독립 perturbation holdout에서 별도로 검증해야 한다.
