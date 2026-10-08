# 회차 07 — 기존 관측 카드·질문·authoring packet의 Astra 연결

## 범위와 main 기준

회차 06 `43b5bdedc1f98a78cdb567ca56b1127c4fab7e7e`를 원격 main에
fast-forward 통합하고 일반 push했다. 원격 SHA를 확인한 뒤
`feature/round07-reader-evidence`에서 작업했다. 통합 경계의 기존 adapter 테스트는
5 passed (4.89 s)였다. 회차 01–05는 이 커밋의 ancestor다.
미커밋 `codex-inputs/`는 유지하며 커밋 대상에서 제외한다.
운영 배포·flag 변경, 회차 08 문헌 검색·비교, 회차 09 자원 연결은 수행하지 않는다.

## 기존 함수와 실제 호출 경로

`run_primary_analysis → astra_evidence_v6.run → astra_package.run_astra_analysis`
`→ compute_science → astra_evidence_v6.augment → project_card_inputs`
`→ astra_reader.build_reader_tables → 기존 카드/선정/질문/serializer`
`→ write_tables + write_artifacts/write_reader → manifest/ZIP`.

다음은 worker graph나 LLM 초기화 없이 portable package에서 사용할 수 있도록
**구현을 이동**한 것이다. 복사한 두 엔진을 유지하지 않는다.

| 기존 자산 | 공용 위치와 소비 |
|---|---|
| build_feature_observation_cards / build_quantitation_comparison_cards / select_finding_cards | `ptm_shared/measured_feature_cards.py`; worker는 동일 함수의 호환 import |
| observed_time_minutes / summarize_observed_pattern / joint_axis_pattern / build_trajectory_shape_fact | `ptm_shared/reader_observations.py`; 기존 temporal/scientific_semantics도 동일 함수 import |
| build_question_map / audit_question_coverage | `ptm_shared/research_questions.py`; worker는 호환 import |
| build_authoring_packet의 최종 순수 직렬화, build_evidence_utilization, build_module_evidence_index, build_coverage_inventory | `ptm_shared/reader_authoring.py`; 기존 worker build_authoring_packet은 준비된 기존 cards/contracts를 공용 serializer에 전달 |
| identity·metadata | 회차 06 adapter가 사용한 canonical_feature_identity, project_reader_display_identity, build_study_metadata_contract 결과 재사용 |

새 `astra_reader.py`는 기존 카드와 원본 ID를 결합하고 all-row coverage/reader views를
작성한다. 카드 계산·선정 규칙을 새로 만들지 않는다. 다른 form/arm/reference/pairing의
카드가 기존 selector의 feature-level dedup에 합쳐지지 않도록 명시적
`selection_unit_id`/`selection_scope`를 허용했다. 이것은 precursor identity가 아니다.
legacy 호출자는 원래 feature-level 동작을 유지한다. 선정 trace에는 원래
reader_feature_id와 별도 selection_unit_id가 같이 남는다.

기존 question map은 원문을 보존하고 정규화 필드만 trim한다. 시간 조건 매칭에는
card에 이미 있는 numeric time_minutes를 사용한다. 두 reference의 같은 시점을
하나의 관측으로 합치지 않는다. 질문 연결은 선정 이후 수행하여 질문 변경이
수치·kinase membership·관측 선정에 영향을 주지 않도록 했다.

기존 authoring serializer에 legacy estimator 설명을 그대로 넣지 않는다. Astra가
실제 사용한 `A=U_joint−P_joint`와 joint mask 계약을 공급하며, legacy 호출자는 기존
estimator 설명을 유지한다. 같은 관측의 비교 카드는 선정 결과의 보조 설명이고
별도 독립 발견으로 세지 않는다. 기존 utilization은 실제 `trajectory` 필드도 세도록
`report_evidence_utilization.v2`로 구분했다.

## 산출물과 추적

| 산출물 | grain / 의미 |
|---|---|
| reader/cards.csv | 실제 기존 함수가 생성한 observation 또는 quantitation-comparison card. 전체 보존 |
| reader/findings.csv | 기존 selector가 선정한 관측 1개당 finding_id; card/form/state/question/source-row FK |
| reader/coverage.csv | 기존 adapter의 모든 form×contrast 행당 정확히 1 disposition; 선정/미선정/보류 이유 |
| reader/packet.csv | 결정론적 authoring packet의 canonical JSON. CSV replay 대상 |
| reader/READ_ME.md | Astra의 첫 읽기 자료: 범위, 원문 질문, 15개 이하 주요 관측, 숫자/시간/reference, parent 영향과 제한 |
| reader/authoring_packet.json | 위 canonical packet의 직렬화 view; 전체 정확도 수치·mask·원본 ID |
| reader/coverage_summary.json / question_map.json / selection_audit.json | 같은 packet에서 생성한 view; 별도 수기 입력 없음 |

`source_bindings`는 `adapter_row_id → reader_adapter/form_contrasts.csv →
quant/comparisons.csv (form_id, contrast_id)`를 연결한다. summary/runlevel,
실제 precursor membership, mapping/localization ID도 남긴다.
U_joint/P_joint/A를 기존 unadjusted/protein/adjusted 필드에 그대로 전달하고
U_all/P_all은 별도로 보존한다. 정규화·평균·imputation·재정량을 하지 않는다.
각 trajectory는 원래 결측 시점을 유지한다.

실제 양/음의 A가 다른 시점에 존재하면 해당 **서로 다른 원본 행** ID를 기록한다.
이를 유의한 방향 반전이나 독립 반대 실험이라고 주장하지 않는다. 기존 card의 일반
caution은 interpretation_limits로 표시하며 반대 관측으로 세지 않는다.
기술 반복과 같은 실험의 protein은 독립 validation이 아니다. 확정 kinase call이
없어도 관측 카드는 생성되지만 kinase 활성으로 승격되지 않는다.

`START_HERE_ASTRA.md`는 reader/READ_ME.md를 먼저 읽도록 실제 상대 링크를 제공한다.
전체 emergence/protein/kinase 표는 그대로 있으며, 표현 제약으로 카드에 넣지 못한
관측은 reader/coverage.csv에서 원본으로 연결한다.

## 실제 입력의 coverage

기준은 회차 06 `g0-ae3bd0a0ea5f4a5080617fe5553ccfd1`의 저장 adapter·과학 표다.

| 구분 | form | form×contrast/관측 |
|---|---:|---:|
| 전체 | 2,824 | 16,944 |
| adapter 적격 및 수치 카드 가능 | 2,159 | 12,499 |
| 카드에 보존된 전체 grid | 2,159 | 12,954 (수치 12,499 + 결측 455) |
| 카드 전체 보류 | 665 | 3,990 |
| 요약 선정 | 15 | 90 |
| 요약 미선정, 전체 원본 보존 | — | 16,854 |

관측 카드 2,159개와 parent 비교 카드 12,499개는 독립 발견 수가 아니다.
실제 15개 주요 결과는 서로 다른 관측 카드에서 선정했다.

보류 이유는 중첩된다: 복수 precursor 1,266행(211 forms), 불명확한 precursor identity
1,266행(앞 항목과 중첩), mixed/unknown taxon 12행(2 forms), gene 표시 모호 60행,
quant exclusion 2,785행, 제외된 finite comparison 때문에 state 전체를 보류한
1,032행(172 states). 행별 reason/disposition으로 전체 분모를 검증한다.
보류된 행 중 실제 included=True이고 A가 존재하는 것은 201개 form·1,205행이다.
모두 복수 precursor 표현 제한에 해당한다. 주요 관측이 없다고 결론 내리지 않으며,
이 카드 계약의 표현 제한으로 명시한다.
parent 결측의 U_all을 U_joint로 바꾸거나 복수 precursor에 가짜 ID를 만들지 않는다.

## 질문별 범위

실제 저장 원문 biological question은 다음과 같다.

> Parent-adjusted PTM, kinase candidate and temporal protein evidence for insulin response

기존 question map이 관측 근거를 연결하며 `partially_answerable/observational_only`로
남긴다. U/P/A, parent 영향 및 관측된 시간 양상은 설명할 수 있다. 개별 kinase 활성,
직접 기전·인과, 독립 validation, 문헌 일치 여부까지 답한 상태는 아니다.
`report_options.research_questions`는 실제로 저장된 빈 배열 `[]`이다.
새 질문을 만들어 넣거나 과거 미저장 질문을 복구했다고 하지 않는다.
긴 다국어 원문/줄바꿈과 추가 질문은 합성 fixture에서 보존 및 ID 연결을 검증한다.
문헌 비교는 모두 `not_performed`다.

## 검증 명령과 구분

- `scripts/validate_astra_reader.py --package <round06-run> --output <new-preview>`:
  기존 source tables만 읽으며 전체 16,944 source rows / 14,658 cards / 15 findings의
  값·시간·NA·joint mask·identity와 FK를 대조한다. 원본은 변경하지 않는다.
- `ptm_shared/tests/test_astra_reader.py`: 기존 함수 호출 spy, 단일/다중 수정,
  multi-precursor/mixed-species 보류, parent 결측, reference 분리, 중간 NA,
  question 원문, 행 순서와 질문 변경에 대한 선정 재현성, no-call에서 관측 유지,
  위조 mask 거절, 실제 v6 경로 및 별도 interpreter의 offline replay.
- 회차 02·03 `test_astra_figures.py`, `test_astra_curves.py`를 유지한다.
- worker의 관측·질문·authoring·metadata 관련 회귀로 공용화의 legacy 영향을 검사한다.
- `scripts/replay_astra_reader.py`: 최종 ZIP에서 추출한 **패키지 자체 코드만** 사용,
  네트워크 차단, 저장 adapter/계산 표로 reader CSV 4개와 view 5개 byte 비교.
  실제 대형 입력에서는 변경한 reader 경계의 replay이며 전체 과학 계산 재실행이 아니다.
  합성 입력에서는 정식 package replay.py로 전체 scientific tables와 reader views를 검증한다.

검증 실행 기록(중복 test 포함):

1. reader/adapter + 기존 measured_feature_cards/companion/identity/joint-pattern +
   회차 02·03 그림: **73 passed, 5 warnings, 12.56 s**.
2. 마지막 selection audit 수정 후 reader + 기존 flow_researcher_report /
   study_metadata_and_event_contracts + v6 evidence integration:
   **56 passed, 1 warning, 21.54 s**.
3. 이동한 기존 quantitation/claim/flow-review/typed-record 소비 경계:
   **32 passed, 1.70 s**.

명령 공통 환경: `PYTHONPATH=api-server:workers:workers/tests:.`,
`MPLCONFIGDIR=/tmp/ptm-round03-matplotlib`,
`/tmp/ptm-science-v5-venv/bin/python`, `pytest -q --tb=short --import-mode=importlib`.
worker core/__init__의 graph 초기화를 피하는 기존
`scripts.validate_astra_card_inputs.card_builders()` namespace loader를 사용한다.
함수 mock 대체가 아니라 실제 순수 consumer 함수를 import한다.

초기 collection에서 `test_measured_feature_authoring.py`는 환경의 `langgraph` 미설치로
실행하지 못했다. graph/LLM 환경 전체 설치는 이번 범위에 추가하지 않았다.
같은 authoring serializer의 기존 소비 경계는 위 identity/companion/flow/metadata
테스트로 검증했다. joint-pattern의 test helper 경로 누락은 workers/tests를
PYTHONPATH에 포함한 다음 정상 실행했다. 실제 수행하지 않은 graph 테스트는 통과로 세지 않는다.

공용화한 관측/시간 순수 함수 7개의 AST가 회차 06 커밋과 동일하다
(EXTRACTION_PARITY.json). `select_finding_cards`의 변경은 위의 명시적 selection scope와
원 ID를 보존한 audit에 한정된다.

실행별 결과·최종 run/ZIP/checksums·회귀/그림/정량 비교는 ROUND07_RESULTS.json에 기록한다.
실제 DIA-NN report와 specificity 자원은 이 작업에서 새로 추가하지 않았다.
합성 성공을 실제 localization 검증이나 과학적 성능 향상으로 확대하지 않는다.


## 최종 실제 패키지 및 비교

- 실제 run: `g0-8e634f6ca5c847a08726cb69bf91f9a2`.
- 로컬 ZIP: `codex-inputs/round07-20261008/execution/output/astra_analysis_package_g0-8e634f6ca5c847a08726cb69bf91f9a2.zip`.
- ZIP SHA-256: `03d7a67a53326595d56c01cc1ef4c28f01f1ee183a7f744681f5eed6d054df2b`; 207,358,999 bytes.
- 기존 pin: `7560c13a6b430363744157d74ad160a83e0939ec0754cedce20d7c0fe9dcbd8e`.
  bytes/hash 보존, refresh=false, network requests=0. 원 pin의 수집 정책은 unknown이며
  research_full을 새로 수행했다고 표시하지 않는다.
- `engine.run`에서 adapter와 reader builder 각각 1회 호출 spy 확인.
  기본 정량 및 normalization sensitivity cache 재사용. 새로운 정량 실행이 발생하면
  검증 runner가 실패하도록 guard했다. 전체 v6 module hash가 기존 evidence cache key에
  포함되어 evidence downstream은 기존 엔진으로 한 번 실행됐다. 별도 cache 체계를 만들지 않았다.
- 기존 성공 archive/current pointer를 수정하지 않고 새 실행 경로에서 생성했다.
  이전 미커밋 8,909개 파일의 크기/mtime 보존, baseline ZIP hash 보존을 확인했다.
- manifest 210 files / scientific CSV 76개 검증.
- **정량 22개 포함 기존 scientific CSV 72개 전부 byte-identical**.
  정량 ID/text/NA exact 및 numeric atol=rtol=1e-10 검증도 통과.
- 그림 source/selection/ordered-column/points CSV 15개와 legends JSON 동일.
  SVG 9개는 timestamp metadata와 임의 생성 XML ID를 제외한 요소·경로·label 동일.
  회차 02·03 선정 및 시간축 코드는 변경하지 않았다.
- 새 package의 START_HERE/reader Markdown 상대 링크 55개 실제 파일 존재 확인.
  reader의 모든 16,944 원본 행 / 14,658 cards / 15 findings에 대한 binding 검증 통과.
- 실제 ZIP을 `/tmp/ptm-round07-archive`로 별도 추출하고 패키지 코드만 사용하여
  reader CSV 4개 + Markdown/JSON view 5개를 재생: **9/9 byte-identical**, 네트워크 0.
  실제 큰 입력의 전체 과학 계산을 다시 실행한 검증은 아니다.
- 합성 정식 offline replay: **76/76 scientific CSV + 5/5 reader views byte-identical**.

과학 표/원자료가 바뀌지 않았으므로 이번 증분은 기존 관측의 읽기·선정·질문·출처 전달이다.
학술적 우월성, 새 kinase 활성, 문헌 비교 완료 또는 독립 검증을 주장하지 않는다.
운영 API/UI/배포의 새 실행을 확인한 것은 아니며 worker가 호출하는 같은 v6 engine 경로를
로컬 실제 입력으로 실행했다.

### 선정된 주요 관측의 예

아래 값은 표시상 6자리로 반올림했다. 정확한 값·전체 시간 grid·NA·mask는 reader/cards.csv의
source_bindings와 quant/comparisons.csv에서 아래 두 키로 찾는다. 예시 시점은 해당 카드의
관측된 절대 A 최대 시점이며, kinase 활성 peak 또는 연속 시간의 생물학적 peak가 아니다.

| 표시명 | 분 | U_joint | P_joint | A | form_id | contrast_id |
|---|---:|---:|---:|---:|---|---|
| DOCK7 | 15 | 0.495153 | -0.049591 | 0.544744 | form_5f6b1591279b085d | contrast_eb2f813f825c4ccb |
| SIK3 | 15 | 0.964560 | -0.014212 | 0.978773 | form_0307f4dc0d707fd5 | contrast_eb2f813f825c4ccb |
| RBM26 | 15 | 0.334968 | -0.009584 | 0.344552 | form_927c72b605b8f2bd | contrast_eb2f813f825c4ccb |
| ITPR1 | 60 | -0.767259 | -0.011877 | -0.755382 | form_50dd63617f0b3f64 | contrast_fd5240cdb335e779 |
| OSBPL3 | 60 | -0.707834 | -0.180763 | -0.527071 | form_6939a1c00932ed01 | contrast_fd5240cdb335e779 |

DOCK7/RBM26/ITPR1/OSBPL3의 다른 시점에 반대 부호 A가 존재하는 행도 보존했다.
작은 부호 차이를 유의한 반응 반전으로 간주하지 않는다. SIK3라는 단백질의 PTM 관측은
SIK3 효소 활성 확정과 다르다. 모든 예는 same-experiment descriptive evidence다.
