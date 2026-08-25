# Current Order가 Stimulus-Blind Benchmark에 적합한가: 코드 감사와 분리 설계 v1

## 결론

**아니다. 현재 Order를 입력값과 분석 결과까지 그대로 재사용하면 stimulus-blind 및 question-blind benchmark가 아니다.** 현재 Order 생성 UI는 treatment, cell type, time points, biological question, special conditions, selected RAG collections 및 research questions를 보존하고, 이 중 여러 항목을 preprocessing, receptor inference, RAG enrichment, report generation, AI chat 및 external Co-Scientist 경로에 전달한다.

따라서 benchmark는 “완료된 Order의 기존 report를 다시 채점”하는 기능이 아니라, 기존 Order의 원자료·sample configuration·FASTA를 immutable source로 삼아 **별도의 blinded analysis run**을 생성해야 한다. 일반 Order와 원래 결과는 수정하지 않는다.

## 확인된 컨텍스트 유입 경로

| 코드 위치 | 확인된 동작 | Blindness 위험 | benchmark 대응 |
|---|---|---|---|
| `frontend/src/pages/OrderCreate.tsx:198–206, 531–540` | cell type, treatment, time points, biological question, special conditions를 `analysis_context`로 전송 | stimulus·질문·dataset identity가 저장됨 | source Order에는 유지하되 blind run에는 원문을 복사하지 않음 |
| `frontend/src/pages/OrderCreate.tsx:557–591` | research questions, report type, LLM/RAG model, 선택 RAG collection을 `report_options` 및 `rag_collections`로 전송 | 질문과 insulin-specific literature가 LLM/RAG에 유입 가능 | benchmark는 fixed generic question과 policy-controlled collection만 사용 |
| `api-server/app/api/orders.py:961–979` | `analysis_context`, `report_options`, `rag_collections`가 Order DB record에 영구 저장 | 기존 Order 결과를 재사용하면 누출 확정 | source record read-only; benchmark record에 sanitized snapshot 생성 |
| `api-server/app/api/orders.py:1207–1224, 1496–1514` | Order context가 `experimental_context`로 preprocessing worker에 전달 | preprocessing 이후 receptor/RAG/report chain에 전파 | 별도 task config에서 generic `experimental_context`만 전달 |
| `workers/preprocessing/tasks.py:865–885` | experimental context, ChromaDB collection, research question, report type를 후속 worker config로 전달 | blind policy가 없으면 downstream 전부 오염 | benchmark 전용 config schema와 denylist audit 필요 |
| `workers/common/receptor_inference.py:260–265` | receptor inference가 `experimental_context.treatment`를 읽음 | treatment-context 기반 receptor ranking 오염 | blind run은 treatment text를 빈 값 또는 `Treatment A`로 설정하고 treatment-context source 비활성화 |
| `workers/common/collection_selector.py:201–208` | treatment와 biological question에서 keyword/pathway를 추출 | RAG collection/pathway prior 오염 | primary strict run에서는 collection selector와 context keyword inference 비활성화 |
| `workers/rag_enrichment/tasks.py:1852–1866, 2122–2167` | experimental context를 RAG pipeline과 PTM enrichment에 전달 | stimulus-specific 문헌 검색 가능 | primary run은 RAG off 또는 strict allowlist; literature-assisted run은 별도 결과 |
| `workers/report_generation/core/graph.py:34–47` | report state가 experimental context, research questions, ChromaDB collections를 보유 | final narrative가 user prior에 의해 유도될 수 있음 | generic context·빈 user RQ·blind policy metadata만 전달 |
| `api-server/app/api/chat.py:597–635` | Order context를 AI chat experiment context에 포함 | completion 후 chat에서 benchmark truth를 재주입할 수 있음 | blind analysis window에서는 chat/Co-Scientist context를 source Order가 아니라 blind snapshot으로 제한 |

## 안전한 사용 흐름

```text
원래 Order
  ├─ 사용자 입력: treatment, biological question, RAG, report options
  ├─ 일반 분석 및 원래 Report: 기존 동작 그대로 유지
  └─ [Benchmark Evaluation 시작]
       │
       ├─ source files·sample configuration·FASTA·code version의 immutable snapshot
       ├─ server-side BlindContextBuilder
       │    ├─ treatment → "Treatment A"
       │    ├─ biological question → 고정 generic question
       │    ├─ special conditions → 제외
       │    ├─ research questions → 빈 배열
       │    ├─ RAG → off 또는 strict allowlist
       │    └─ project/order name·원본 파일명 → neutral benchmark run ID
       │
       ├─ 별도 blinded preprocessing → wave/TMM/directionality/report artifact
       ├─ artifact archive 및 hash lock
       ├─ locked scorer만 workbook truth를 열어 score·figure 생성
       └─ scoring 완료 후에만 truth reveal 및 paper bundle 열람
```

## 반드시 마스킹·차단할 항목

| 항목 | 원래 Order에서의 보존 | blind run 처리 | 이유 |
|---|---|---|---|
| Treatment | 보존 | `Treatment A` 또는 빈 값 | insulin·drug·stimulus identity 차단 |
| Biological question | 보존 | 고정 generic question | pathway/kinase/기대 결과 유입 차단 |
| Cell type·special condition | 보존 | primary strict run에서는 제외; 필요 시 generic `cultured cells` | dataset identity 및 disease prior 감소 |
| Project/order code·파일명 | 보존 | neutral `benchmark_run_<uuid>`와 sanitized filenames | name에 포함된 insulin/HIRc-B 단서 차단 |
| Sample condition label | 원본 보존 | `Control`, `Treatment A 1 min` 등 neutral label | time 정보는 유지하고 stimulus명만 제거 |
| User research question | 보존 | 빈 배열 | direct prompting 차단 |
| RAG collection | 보존 | off 또는 manifest-defined strict allowlist | insulin-specific literature 역유입 차단 |
| External Co-Scientist/AI Chat | 원래 Order와 별도 | primary run 비활성 또는 blind snapshot만 사용 | user goal·stored context 재유입 차단 |
| Benchmark workbook | 서버 locked storage | scorer process만 read | truth leakage 차단 |

Species, PTM type, numeric timepoints, replicate structure, sample-control 관계, PR/PG matrix, Rat_hir custom FASTA provenance는 **유지해야 하는 분석 정보**이다. 시간값 자체는 biological prior가 아니라 temporal inference의 입력이다. 단, 파일명·condition label·project name에 stimulus가 포함된 경우 반드시 neutral alias를 사용한다.

## 두 가지 run을 구분해야 하는 이유

| Run | 목적 | Context 정책 | 허용되는 해석 |
|---|---|---|---|
| 일반 Order 분석 | 사용자의 실제 연구 해석·Report | 원래 treatment/question/RAG 모두 허용 | data-grounded biological interpretation |
| Primary blind benchmark analysis | 알고리즘의 blind recovery 평가 | sanitized context, no user RQ, no insulin-specific RAG | data-driven discovery 및 locked score 전 artifact |
| Literature-assisted benchmark analysis | blind data output에 문헌 보강이 더하는 가치 평가 | explicit allowlist, distinct run ID | primary score와 분리된 narrative comparison |
| Perturbation validation | post-analysis causal validation | inhibitor condition metadata 허용 | perturbation-supported, condition-scoped claim |

일반 Order의 결과를 benchmark score에 바로 사용하면 “분석 알고리즘의 blind performance”와 “사용자가 제공한 hypothesis 및 literature prior를 포함한 assisted performance”가 섞인다. 두 결과는 모두 가치가 있지만 서로 다른 성능 지표로 보고해야 한다.

## 구현 권고

1. `Order`를 수정하거나 일반 rerun option을 덮어쓰지 않는다. 새 `BenchmarkRun` record를 만들고 `source_order_id`만 참조한다.
2. Server-side `BlindContextBuilder`가 source Order를 읽되, denylist와 allowlist를 적용해 sanitized `benchmark_context`를 생성한다. Frontend가 만든 context를 신뢰하지 않는다.
3. `BenchmarkRun`은 source file checksum, source order snapshot hash, sanitized context hash, manifest hash, code/model version, RAG policy, truth reveal timestamp를 기록한다.
4. Benchmark worker는 source Order의 기존 preprocessing/report artifact가 아니라 source input snapshot에서 다시 실행한다. 그렇지 않으면 이미 context-influenced receptor/RAG/report artifact가 재사용될 수 있다.
5. Locked scorer는 별 process/package로 실행하고, analysis·RAG·LLM worker import path와 object storage mount를 분리한다.
6. Primary blind artifact가 archive된 뒤에만 scorer 결과 및 figure bundle을 사용자에게 노출한다. 분석 중에는 raw truth·expected branch·anchor names가 UI/API response에 나타나지 않아야 한다.

## 현재 temporal-wave benchmark helper와의 관계

`ptm_shared/temporal_wave_benchmark.py`는 real-data manifest와 declared known target을 직접 받아 site 대 wave score, time permutation, threshold sensitivity를 JSON/Markdown으로 생성하는 **개발자용 harness**이다. 이 helper는 generic stimulus-blind user workflow, context sanitization, locked workbook scorer, RAG/LLM isolation, paper figure bundle을 아직 제공하지 않는다. 새 benchmark framework는 이 helper의 wave/permutation 기능을 재사용할 수 있으나, 별도의 `BenchmarkRun`과 server-side blind policy를 추가해야 한다.
