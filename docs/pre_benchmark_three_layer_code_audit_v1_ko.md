# Benchmark 구현 전 PTM-platform 3층 코드 감사 v1

## 감사 목적과 판정 기준

이 감사의 목적은 benchmark가 무엇을 평가하는지 명확히 하는 것이다. 여기서 **Order 결과에 영향한다**는 말은 단순히 파일을 남기거나 progress row를 보이는 것이 아니라, 해당 계산이 `orders` DB의 production analysis field, frontend의 결과 분석 payload, ReportState, LLM writer context, 또는 최종 Report figure/text에 실제로 읽혀 들어간다는 뜻으로 한정한다.

이미지에서 제시한 세 층은 코드의 L1–L4 명명과 정확히 같은 축이 아니다. 본 문서는 사용자 관점의 0/1/2층과 코드 내부의 L1–L4를 구분한다.

| 사용자 관점 | 코드 내부/실제 경로 | Order 결과 영향 판정 |
|---|---|---|
| 0층: 원래 제품 | Order API → preprocessing → RAG enrichment → report generation | **직접 영향** |
| 1층: 시간축 과학 기능 | Canonical co-movement/Wave, global kinase module, receptor inference, Atlas, TMM-enabled API path, directionality, multisite divergence | **대부분 직접 영향**, 단 TMM은 실행 경로가 분기됨 |
| 2층: 확장 검증 stack | L3 multiview input, L4 learned embedding, A–E ablation, C1/C2/C3-style probe/gate results | **현재 additive only**; artifact·progress는 남지만 canonical score/report는 바꾸지 않음 |

## 결론 요약

> **이미지의 큰 구조는 대체로 맞다.** 다만 두 가지 정정이 필요하다. 첫째, L3/L4 Representation Learning은 현재 모든 Order에서 기본적으로 실행될 수 있는 preprocessing substep이지만, 결과에는 영향하지 않는 **additive artifact producer**다. 둘째, TMM은 구현되어 있고 API global-kinase full analysis에서는 production result를 바꾸지만, 일반 Order의 RAG auto-analysis/Report 경로와 동일한 계산인지 보장되지 않아 benchmark 전에 baseline contract를 고정해야 한다.

| 판정 | 결과 |
|---|---|
| 0층 기본 pipeline이 살아 있는가? | 예. preprocessing → RAG → report Celery chain이 유지됨 |
| 1층 시간축 기능이 ordinary report에 실제 사용되는가? | 예. temporal co-movement, kinase annotation, Atlas/claim ledger, auto global analysis가 report graph에 연결됨 |
| L3/L4 representation이 kinase score/rank/report conclusion을 바꾸는가? | 코드 경로상 아니오. additive-only이며 consumer가 없음 |
| L3/L4가 Order에서 실제 실행되는가? | 예. feature flag 기본값이 `1`; failure는 non-fatal |
| representation gate가 production을 열 수 있는가? | 현재 per-Order call은 external evaluation을 전달하지 않아 generalization gate가 not-evaluated가 되므로 실질적으로 아니오 |
| benchmark를 바로 구현해도 되는가? | 0/1/2층 분리 자체는 가능하나, **TMM 실행 경로 통일·명명 정리·baseline manifest 선언**을 먼저 해야 함 |

## 0층: 원래 제품 pipeline

### 확인된 실행 경로

1. `api-server/app/api/orders.py`는 Order context·options를 포함한 config로 preprocessing task를 dispatch한다.
2. `workers/preprocessing/tasks.py`는 preprocessing을 끝낸 뒤 `chain_to_next`가 true이면 RAG enrichment task를 dispatch한다.
3. `workers/rag_enrichment/tasks.py:2355–2406`은 RAG 완료 뒤 report config를 만들고, auto global analysis를 수행한 다음 report generation task를 dispatch한다.
4. `workers/report_generation/tasks.py:406–550`은 DB의 kinase heatmap, receptor inference, signal propagation, raw vector data를 읽어 ReportState에 넣고 graph를 실행한다.

따라서 파일 입력 → preprocessing → RAG → Report라는 0층 제품 경로는 실제 production path다. Benchmark는 이 경로를 대체하면 안 되며, source input snapshot에서 별도 blind run을 만들더라도 같은 analysis contract를 명시적으로 선택해야 한다.

## 1층: 시간축 기능의 실제 production 연결

### 1.1 Ordinary report에 자동 연결된 기능

`workers/report_generation/core/graph.py:881–973`에서 ordinary report는 다음 순서로 진행된다.

```text
network_analysis
  → temporal_comovement
  → kinase_annotation
  → (current temporal contract이면) atlas_claim_ledger → generate_atlas_report
  → writer/report/post-processing
```

`temporal_comovement_node.py`는 canonical temporal wave engine을 사용하고, `kinase_annotation_node.py:9–16, 288–313`은 사용자가 별도 버튼을 누르지 않아도 enriched PTM 전체에서 Global Kinase Module을 구성해 LLM context에 붙인다. `hypothesis_node.py`는 evidence-eligible multisite divergence를 data-grounded hypothesis context에 전달한다. Atlas claim ledger도 bounded writer context로 전달된다.

즉 co-wave/Wave, temporal cascade, global kinase modules, receptor-aware signal flow, Atlas, directionality/divergence evidence gate는 1층의 **실제 Report 결과 경로**에 속한다. `temporal_contract=legacy`만 Atlas node를 생략하며, 그 외 current contract는 Atlas를 실행한다.

### 1.2 TMM의 중요한 실행 경로 분기

TMM은 구현되어 있으며, `api-server/app/api/orders.py:8482–8745`의 full `global-kinase-modules` analysis는 다음을 수행한다.

* NNLS 기반 shared-PTM contribution을 계산한다.
* raw up/down sums를 TMM-weighted values로 대체하고 raw values는 provenance로 보존한다.
* raw co-wave와 TMM-weighted co-wave를 모두 보존한다.
* TMM-weighted cascade, kinase-pair directionality, contribution matrix를 저장한다.

반면 ordinary RAG auto-analysis의 `_compute_kinase_activity_heatmap()` (`workers/rag_enrichment/tasks.py:810–980`)은 trajectory clustering, dominant cluster selection, winsorized weighted mean을 수행하지만 TMM scorer를 import하거나 호출하지 않는다. RAG 단계가 DB에 저장한 heatmap은 report task가 기본적으로 읽는다.

따라서 현재 코드에는 다음 두 유효 경로가 있다.

| 경로 | 기본 실행 | TMM contribution | Report/DB 영향 |
|---|---|---|---|
| RAG auto global analysis | 일반 Order에서 자동 | 확인된 코드상 없음 | heatmap·kinase module·receptor 결과가 DB/Report로 전달 |
| API full global-kinase analysis | frontend global annotation의 full/refresh 경로 | 있음 | TMM-weighted heatmap/cascade를 DB에 저장하고 이후 consumer가 사용 가능 |

이 분기는 benchmark의 가장 중요한 사전 조치다. 동일한 “kinase activity”라는 명칭 아래 raw/cluster-weighted 자동 결과와 TMM-weighted full 결과가 섞이면 score 변화를 알고리즘 개선으로 해석할 수 없다.

### 1.3 TMM guard의 현재 상태

`temporal_kinase_scoring.compute_weighted_kinase_scores()`의 현재 default는 `GUARD_GROUP_SHARE`이다. 이는 unsupported shared site를 scoring에서 제외하고 ambiguity group 내부의 개별 균등 분할을 report에서 보류하는 정책이다. `ptm_shared/temporal_contract.py`에는 별도 legacy default 표현이 존재하므로, benchmark manifest는 guard policy를 API implicit default에 맡기지 말고 명시적으로 기록해야 한다.

## 2층: Representation Learning·C0–C3·gate stack

### 2.1 실제 실행 방식

`workers/preprocessing/tasks.py:454–493`은 `PTM_REPRESENTATION_LEARNING_ENABLED`가 `1`이면 per-Order representation analyzer를 실행한다. Docker 기본값도 `1`이며, ablation flag 기본값도 `1`이다. 이 substep은 progress UI에 `Representation Learning (1c)`로 표시되고, errors는 non-fatal이다.

`workers/preprocessing/core/ptm_representation_learning.py`는 다음 두 artifact를 output directory에 쓴다.

```text
ptm_representation_embeddings*.tsv
ptm_representation_benchmark*.json
```

코드 주석과 layer contract는 L1 PTM vector, canonical co-wave, TMM coefficient, kinase ranking을 이 step이 변경하지 않는다고 명시한다. L4는 L1/L2 raw evidence로 traceable해야 하는 secondary evidence다.

### 2.2 격리 확인

정확한 artifact filename과 `production_influence_allowed`를 API, RAG, report generation, frontend result component에서 검색한 결과, preprocessing producer와 Order progress row 외에 production consumer는 확인되지 않았다. ReportState에도 representation embedding/manifest field가 없고, writer context에도 이 artifact가 주입되지 않는다.

`ptm_shared/representation/benchmark.py:550–730`의 adoption gate는 external evaluation이 없으면 generalization gate를 `not_evaluated`로 처리하고 `production_influence_allowed=False`를 반환한다. Per-Order analyzer의 `_run_bounded_ablation()`은 external evaluation을 전달하지 않으므로, 정상적인 live Order에서도 L4 결과가 production co-wave/TMM/ranking을 여는 경로는 없다.

### 2.3 명명 혼선

현재 UI는 “Representation Learning (1c)”, 내부 contract는 L1–L4, 사용자 개념도는 “2층 확장 검증 stack”이라는 세 용어를 쓴다. 이는 분석 결과의 기능보다 **설명과 benchmark 설계에 더 큰 위험**이다. Benchmark UI와 Methods에서는 다음처럼 고정하는 것이 좋다.

| 표시 명칭 | 의미 |
|---|---|
| Production analysis layer | 0층 pipeline + 1층 temporal science features |
| Additive representation validation layer | L3/L4 embedding, A–E ablation, C-series probes, adoption gates |
| Production influence | 명시적 gate 통과와 별도 integration approval 후에만 가능한 미래 상태 |

## 실행 확인

현재 최신 worktree에서 다음 focused tests를 실행했다.

| Test scope | 결과 |
|---|---|
| temporal contract, TMM integration, directed relationship, multisite divergence, C1 transmissibility, coverage adversary | **72 passed** |
| temporal kinase scorer guard | **12 passed** |
| representation integration, C1, coverage adversary, de novo representation, fair probe | **126 passed** |

Sandbox에는 worker scientific dependency 일부가 처음 빠져 있어 `pytest`, `scipy`, `biopython`, `statsmodels`를 설치한 뒤 실행했다. 이 설치는 sandbox environment만 변경했으며 repository source/dependency manifest는 변경하지 않았다. `workers/pyproject.toml`에는 biopython, scipy, statsmodels가 이미 선언되어 있었다.

## Benchmark 전 필수 조치

| 우선순위 | 조치 | 이유 |
|---|---|---|
| P0 | benchmark manifest에 **production target contract**를 명시: `auto_raw_temporal` 또는 `tmm_full_temporal` | 현재 TMM path 분기를 숨기지 않음 |
| P0 | strict primary benchmark는 L3/L4 artifact를 score/report input에서 제외하고 flag·artifact hash를 기록 | 2층 검증 stack이 0/1층 평가에 섞이지 않게 함 |
| P0 | UI/문서 명칭을 production temporal layer와 additive representation validation layer로 통일 | “Representation Learning이 현재 production 분석인가?” 혼선 제거 |
| P1 | RAG auto heatmap과 API full TMM heatmap을 단일 shared builder로 통합하거나, 서로 다른 result type/version으로 강제 분리 | 같은 Order에서 raw와 TMM 결과가 섞이는 위험 제거 |
| P1 | guard policy, temporal contract, heatmap scoring method, source stage를 result bundle과 report figure metadata에 저장 | version 비교·benchmark 재현성 확보 |
| P2 | representation gate가 production influence를 얻는 경우에만 별도 benchmark arm으로 평가 | L4 효과를 canonical baseline 변화로 잘못 주장하지 않음 |

## Benchmark-ready 판정

**부분 준비됨(conditional go)**으로 판정한다. 0층 pipeline, 1층 report path, 2층 additive isolation의 큰 경계는 코드와 focused tests로 확인됐다. 그러나 benchmark 구현 전에 canonical production baseline을 한 가지로 선언해야 한다. 특히 TMM을 platform의 평가 대상에 포함하려면 full TMM path를 explicit하게 실행·기록하거나 RAG auto path와 공유해야 한다. 이 결정을 고정한 뒤에야 score 차이가 data, model, execution path 중 무엇에서 왔는지 해석할 수 있다.
