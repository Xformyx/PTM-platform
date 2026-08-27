# Dynamic Co-Wave Transition 전체 플랫폼 적용 계약

## 적용 원칙

Dynamic co-wave transition은 strict-blind benchmark 전용 결과가 아니라, 일반 Order와 benchmark가 동일한 `unified_temporal_ptm_protein` sidecar를 생성할 때 사용하는 공용 numerical annotation이다. canonical static Wave, TMM profile, kinase ranking, 기존 primary score는 바꾸지 않는다. Static Wave에 이미 포함된 PTM member가 인접 시간 구간에서 보이는 local co-movement의 persistence, split, merge, recruitment, exit만 별도로 기록한다.

> Dynamic transition은 관찰된 local membership 변화이다. 이는 kinase switching, upstream/downstream direction, direct kinase attribution 또는 causality를 증명하지 않는다.

## 일반 Order 실행 경로

| 단계 | 공용 실행 지점 | 저장 또는 소비 결과 |
|---|---|---|
| Global kinase annotation | `POST /orders/{order_id}/global-kinase-modules` | kinase module·effector·co-wave 기초 결과를 저장하며, 기존 temporal sidecar summary를 보존 |
| TMM/heatmap | `POST /orders/{order_id}/kinase-activity-heatmap` | canonical Wave와 TMM 결과 뒤 `build_production_temporal_ptm_protein_analysis()`를 호출 |
| Full artifact | `temporal_ptm_protein_analysis_v2.json` | PTM–protein sidecar, dynamic transition provenance, compact deterministic example 및 full per-Wave aggregate 저장 |
| Compact projection | `Order.kinase_activity_heatmap`, `Order.kinase_analysis_data` | UI, Chat, Report 및 comparison consumer가 사용하는 DB-safe summary 저장 |
| Full artifact retrieval | `GET /orders/{order_id}/temporal-ptm-protein-analysis` | 인증된 사용자가 complete production artifact를 조회 |

Frontend에서 Global Kinase Module 결과가 준비되면 kinase heatmap view가 자동으로 heatmap/TMM endpoint를 요청한다. 그 endpoint가 dynamic annotation을 포함한 shared sidecar를 생성한다. 따라서 일반 분석에서는 별도 benchmark 실행이나 truth workbook 없이 same-contract dynamic output을 받는다.

## Cache migration과 persistence 보호

Dynamic transition의 frozen configuration과 contract version은 heatmap cache key에 포함된다. 캐시된 compact summary에 `dynamic_co_wave_transition_status=computed`와 현재 configuration SHA-256이 없으면, 동일 temporal arm이라도 legacy/static cache를 반환하지 않고 heatmap/TMM 및 sidecar를 자동 재생성한다. 이미 current dynamic summary가 있는 cache만 재사용하며, 사용자가 명시적으로 바꾼 TMM parameter가 있는 current cache는 기존과 같이 `_stale`로 표시한다.

Global annotation은 normal single request 및 frontend batched merge request에서 `kinase_analysis_data`를 다시 저장할 수 있다. 두 저장 경로 모두 기존 `temporal_ptm_protein_analysis` compact summary를 보존한다. 따라서 Global Annotate를 다시 실행해도 previously computed dynamic transition result가 의도치 않게 DB에서 사라지지 않는다.

## 소비자 적용 범위

| Consumer | dynamic transition 사용 방식 | 금지된 표현 |
|---|---|---|
| Kinase Activity Heatmap UI | status, transition-supported Wave 수, observed pair-transition 수를 접이식 Shared PTM–Protein Temporal Evidence panel에 표시 | kinase switching 또는 causal propagation 표시 |
| Chat | cross-layer temporal evidence와 함께 dynamic status·Wave 수·pair-transition 수를 context로 제공 | direct kinase assignment 또는 인과 주장 |
| Data-Grounded Analysis | 동일 summary를 seed context에 포함하고, orthogonal validation을 묻는 question으로 제한 | local transition을 기전적 proof로 사용 |
| Comparative analysis | 각 Order의 dynamic coverage 및 transition 규모를 observational comparison context에 포함 | 두 condition의 causal pathway 차이 단정 |
| Report generation | Results, Discussion, Abstract supplement에 compact count와 claim boundary를 제공 | LLM이 numerical transition을 새로 생성하거나 score를 수정 |
| Research-question generation | transition이 계산된 경우 reproducibility 및 orthogonal validation을 묻는 falsifiable question 생성 | kinase handoff의 확정적 서술 |

RAG와 LLM은 이 numerical evidence packet의 downstream consumer이다. 이들은 candidate transition을 만들거나 activity threshold를 선택하거나 canonical Wave/TMM/primary score를 바꿀 수 없다. RAG는 transition window, candidate kinase, substrate, target protein에 맞는 기존 문헌을 보조 근거로 검색할 수 있고, LLM은 local transition·counterevidence·후속 validation 우선순위를 서술할 수 있다.

## Frozen shared configuration

Production과 benchmark sidecar의 기본 dynamic configuration은 absolute relative log2FC activity threshold 0.40, minimum observed timepoint 4, retained canonical Wave membership universe, leave-one-timepoint-out stability 및 bounded compact serialization을 사용한다. Configuration provenance에는 dynamic contract version, configuration SHA-256, truth-free selected trial ledger hash와 record hash가 기록된다.

이 값은 truth-free numerical structure test에서 선택되었으며, user-provided workbook truth나 biological label로 선택되지 않았다. Full event set은 metric 계산에 유지하지만, operational payload에는 deterministic pair example 500개, site example 500개, membership example 250개와 full per-Wave aggregate count만 남긴다.

## 운영 시 재계산

새 코드 배포 뒤 legacy heatmap cache가 있는 Order는 Kinase Activity Heatmap을 열거나 refresh하면 current dynamic cache contract가 자동으로 감지되어 재계산된다. 사용자는 별도 truth input을 제공할 필요가 없다. Normalized PTM vector 또는 PG protein output이 없거나 sidecar가 non-fatal failure를 반환하면, 기존 kinase analysis는 계속 제공되고 shared temporal panel에는 `unavailable` provenance가 표시된다.

## 검증 기록

이번 full-platform integration에서는 dynamic cache configuration hash propagation, current sidecar persistence, compact summary, question-generation observation wording을 회귀 테스트로 확인했다. Python regression 17개, Python syntax compilation, TypeScript compiler, Vite production build 및 truth-import boundary scan을 통과했다. Frontend build는 기존 esbuild build-script approval policy를 변경하지 않고 설치된 local binary로 수행했다. Vite는 existing large-chunk warning을 보고했지만 build는 성공했다.
