# Biological Design 명칭 및 저장된 반복 수 표시 수정

작업일: 2026-10-29~30 (Asia/Seoul)

## 기준과 범위

- 작업 시작 HEAD: `8e2c7268c195b89e518726a266d45b055c1eb8f3`. 요청서의 원격 main 감사 SHA와 로컬 HEAD가 같았다.
- 브랜치: `main`. origin fetch/push URL: `https://github.com/Xformyx/PTM-platform.git`.
- 구현·테스트 로컬 커밋: **`6a5de85e62dd6e5980399ca01193d40522f5fd67`**. 이 보고서와 화면 기록은 후속 문서 커밋에 포함한다.
- 기존 Astra 읽기 전용 요약, 원본 편집, 단일 Control 연결, manifest 갱신 기능이 이미 적용된 상태에서 시작했다. 해당 resolver 기능을 다시 작성하지 않았다.
- 이번 변경은 표시명과 표시용 metadata projection이다. `study_design.py`, 정량 엔진, parser의 Rep. fallback, scientific method는 수정하지 않았다.
- 운영 배포 버전과 로컬 HEAD의 일치는 확인하지 않았다. 이번 작업에서 push·배포·flag 변경을 수행하지 않았다.
- 기존 미추적 `codex-inputs/`는 커밋에서 제외했다. 실제 입력·과거 발행 ZIP·성공 pointer·source/literature pin을 변경하지 않았다.

## Biological Design과 호환 키

`ptm_shared/study_display.json`에 공통 표시명, 도움말, 필드 설명을 둔다. 프런트엔드와 Python projection이 같은 파일을 소비한다.

- 표시명: **Biological Design**
- 도움말: “실험 모델, 처리 조건, 시간 계획, 반복 설계와 분석 목적을 설명하세요.”
- 저장 키: **`analysis_context.biological_question` 유지**
- 패키지 필드 설명: “Biological Design 설명을 담는 기존 호환 필드 (biological_question). 원문을 보존하며 report_options.research_questions와 별도로 저장합니다.”

최초 입력, 입력 정보 수정/재생성 모달, Astra 요약, 주문 상세의 표시명을 변경했다. 새 패키지의 `STUDY_BRIEF.md`, `START_HERE_ASTRA.md`, reader `READ_ME.md`, input field manifest에도 해당 이름/설명을 사용한다. 새 `biological_design` 독립 입력 필드나 DB migration은 없다.

공백·개행·한국어/Unicode를 포함한 원문을 저장·재조회·재생성 payload·패키지에서 그대로 보존한다. 요약 화면은 개행도 표시한다. `report_options.research_questions`와 기존 `BQ-001`/`RQ-001` 질문 연결은 유지했다. 기존 BQ 연결을 reader에 표시할 때 제목에 Biological Design을 명시하며, 질문/evidence ID나 문헌 결과를 재분류하지 않는다.

## 원본과 소비 경로

| 정보 | 원본 / 저장 | 표시 소비 |
|---|---|---|
| Biological Design | 최초 form의 `biological_question` → `analysis_context.biological_question` → resolver의 `study.biological_question` | 공통 표시명, `study_display.biological_question.value`; context에 키가 있으면 명시적 null도 그대로 사용 |
| 등록 반복 ID | `sample_config.samples[].replicate` 또는 기존 배열 형식 → `designSamples` / `legacy_samples` → `study_design.injections[].legacy_replicate` | 공통 `study_display()`가 canonical `condition_id`별 고유 Rep. ID 집계 |
| 측정 파일 / 주입 | 기존 resolver의 `input_column`, `injection_id` | 각각 고유 ID 개수. 조건별·전체 수를 따로 제공 |
| 반복 유형 / biological mapping / pairing | 기존 `replication_declaration`, materials, injection의 material 연결, contrasts의 pairing | 별도 상세 정보. Rep. ID 개수로 관계를 만들지 않음 |
| 예정 반복 수 | 새 실험 초기 context의 `replication_plan.default_replicates_per_condition`와 `source` | 저장 context → API/패키지 projection의 `planned_replicate_count`, `planned_summary`; 실제 등록 수와 별도 |
| 실제 연구 질문 | 기존 `report_options.research_questions` | 기존 snapshot/reader question map 그대로 사용 |

`/orders/resolve-design`는 기존 `study_design`·`analysis_context` 옆에 표시 전용 `study_display`를 반환한다. 이 projection은 수치 설계 안에 삽입하지 않는다. UI는 동일 projection을 읽는다. 저장/DB 재조회/dispatch/worker는 기존 경로를 그대로 이용하며, 패키지 writer는 `study/study_display.json`을 추가한다. reader metadata에도 같은 helper 결과를 넣는다. `capture_order`, `write_study_inputs`, `transfer_contract`, `metadata_packet` 경계를 재사용했다.

## 집계와 unknown 처리

1. 조건 이름이나 contrast 수가 아닌 canonical `condition_id`로 그룹화한다. Control도 한 조건으로 집계한다.
2. 조건 안의 저장된 `legacy_replicate` 고유 ID 개수가 등록 반복 수다. `max(Rep.)`, 총 파일 수/조건 수, 파일 순서로 계산하지 않는다.
3. 숫자 `1`과 직렬화된 문자열 `"1"`은 같은 ID로 읽는다. 명시적 `"01"`, `"1.0"`, `"A"`, `"a"`는 서로 다른 ID로 유지한다.
4. 파일은 고유 `input_column`, 주입은 고유 `injection_id`로 센다. 같은 주입의 중복 기록이나 PR/PG 양쪽의 같은 주입을 더하지 않는다. 하나의 Control을 다섯 contrast가 참조해도 Control 등록 수는 그대로다.
5. 같은 Rep. ID에 여러 측정 파일/주입이 있으면 ID 개수와 파일·주입 수를 따로 표시한다. 이 사실만으로 technical 또는 biological 관계를 선언하지 않는다.
6. 번호 누락, 비연속 번호, 중복 주입 기록, 매핑 불일치는 해당 조건의 상세 상태로 표시한다. 누락 샘플이나 번호를 생성하지 않는다. 예를 들어 1·2·4는 등록 ID **3개**이며 비연속 상태를 표시한다.
7. materials가 없어도 등록 반복 수를 표시한다. 유형 미지정, 기록된 material/biological unit 수, 미매핑 주입과 기존 descriptive/추론 제한은 별도 상세로 남긴다. 기존 unknown/paired/unpaired 의미와 오류 정책을 변경하지 않는다.

조건별 수가 같고 번호 누락/매핑 충돌이 없으면 “등록 반복: 조건별 3반복 · 총 18개 측정 파일”처럼 표시한다. 조건별 수가 다르면 “Control 3 · 0.5h 3 · 1h 2 …”처럼 실제 등록 수를 표시한다. 주입 수와 biological unit 수를 하나의 n으로 표현하지 않는다.

## 예정 기본값 3과 실제 등록 수

기존 별도 반복 계획/개수 기본값 경로는 확인되지 않았다. 개별 샘플의 Rep. 번호와 분리된 표시 metadata `replication_plan`을 추가했다.

- 새 OrderCreate의 `newExperimentContext()`만 예정 기본값 **조건별 3**을 초기화한다.
- 이미 저장된 계획 2/4, 명시적 null 및 기존 context는 우선 보존한다.
- 기존 주문 복사·재진입·재생성은 `withPersistedExportMode()`로 원래 값을 복원한다. 계획이 없던 기존 주문에 소급해서 3을 넣지 않는다.
- 실제 등록 수는 언제나 실제 sample mapping에서 집계한다. 예정 3·등록 2라면 두 값을 각각 표시하며, 실제 등록 수를 3으로 덮어쓰지 않는다.
- 예정 수 수정은 원본 데이터 정보의 기존 선택 상세 영역에만 있다. Astra 실행 요약에 새로운 질문·확인 체크는 없다.
- 개별 행의 `replicate`, parser fallback 1, 파일/열/측정값, biological unit 또는 pairing을 바꾸지 않는다.

## 변경 전후 화면

아래 이미지는 **실제 주문이 아닌**, 6조건×Rep. 1·2·3을 직접 등록한 로컬 fixture의 실제 컴포넌트 화면이다. 같은 샘플과 원문으로 변경 전후를 캡처했다.

| 위치 | 변경 전 | 변경 후 |
|---|---|---|
| 설명 필드 | Biological Question | Biological Design, 개행 보존 |
| 반복 요약 | 반복 정보: 미기록 — descriptive 분석 · 18 injection | 등록 반복: 조건별 3반복 · 총 18개 측정 파일 |
| 상세 | materials 부재가 반복 정보 전체 미기록으로 표시됨 | 각 조건의 1·2·3, 등록 3, 파일 3, 주입 3; 반복 유형 미지정; 기록된 material/biological unit 0 |

[변경 전](design_replicate_display/before.png) · [변경 후](design_replicate_display/after.png) · [반복 상세](design_replicate_display/after-detail.png)

## 검증 결과와 실제 실행 경계

| 검증 | 결과 |
|---|---|
| 공통 표시/metadata, API 저장·재조회·dispatch, 기존 수치 불변, reader writer | **13 passed** |
| 프런트엔드 context/원문/계획 기본값·저장값 테스트 | **9 passed** |
| 새 합성 브라우저 검증 | 통과; 6조건의 ID/등록 수/파일 수/주입 수, 유형 미지정, 원문·연구 질문 보존, 수정 없는 재생성 payload 확인; page errors 0 |
| 기존 입력 재사용 브라우저 회귀 | 통과; 최신 응답, 원본 수정, manifest 반영, 재생성 읽기 전용, Legacy 입력 유지; page errors 0 |
| 프런트엔드 build | 통과. 기존 Browserslist 데이터 및 큰 bundle 경고만 있음 |
| diff whitespace 검사 | 통과 |

핵심 fixture 결과:

| 입력 | 확인한 출력/보존 |
|---|---|
| 6조건×1·2·3, materials=0 | 각 조건 3등록, 총 18파일/18주입, pairing unknown |
| 3/3/2/3/3/3 | 조건별 실제 개수, 총 17파일. 일괄 3으로 표시하지 않음 |
| 1·2·4 | 등록 3, 비연속 번호 상태 |
| 각 Rep. ID에 주입 2개 | 각 조건 3등록·6파일·6주입, 총 36파일/주입; 유형 자동 확정 없음 |
| 번호 누락/중복 레코드/상충 매핑 | 해당 조건에만 상태 표시, 고유 파일/주입 수 유지 |
| 계획 2/3/4와 실제 등록 2 | 실제 2 유지; 계획과 일치/불일치 별도 표시 |
| 저장된 paired biological mapping, 수정 없는 재생성 | condition/injection/material/pair ID와 설계 그대로 유지 |
| 한글·공백·개행 포함 Biological Design | 최초 입력 payload→저장→GET→Astra/재생성→패키지에서 원문 보존; 별도 연구 질문 보존 |

API 검증은 격리된 SQLite와 실제 FastAPI resolve/create/PATCH/GET, 기존 dispatch 및 worker 분기를 사용했다. worker의 과학 실행은 metadata writer 대역으로 교체했다. PR/PG에는 동일 합성 주입이 포함되지만 파일/주입 수는 12 또는 18로 유지됐다. 브라우저는 실제 React 컴포넌트와 공통 Python resolver/projection을 사용하고 보조 HTTP 응답을 대역 처리했다. reader 검증은 저장된 합성 결과 테이블을 읽고, 계산·문헌 검색 함수를 금지한 상태에서 Markdown/metadata만 기록했다.

기존 작은 수치 fixture 테스트를 재사용해 U/P/A·NA·mask·집계/표본 수가 포함된 결과 DataFrame의 정확한 일치를 확인했다. 구현 전 저장해 둔 동일 입력의 v5/v6 quant fingerprint도 구현 후 새 프로세스에서 비교했으며, 계획 metadata 3을 추가해도 같았다:

- v5: `quant_v5_e3c9c2b8462435fb7f67`
- v6: `quant_v6_171be8faf79b3a007a44`

전체 정량 workflow, PhosX, RAG/LLM, 전체 ZIP 재생성 또는 대규모 replay를 실행하지 않았다. 라벨 변경으로 기존 결과/수치 캐시를 재계산하지 않았다. 과거 패키지의 기록된 설계도 수정하지 않았다.

재현 명령:

```sh
PYTHONPATH=api-server:workers:.:ptm_shared/tests codex-inputs/round11-20261010/runtime/bin/python -m pytest -q ptm_shared/tests/test_study_display.py api-server/tests/test_astra_input_reuse.py ptm_shared/tests/test_study_input_reuse.py::test_unchanged_design_preserves_quantitative_outputs_and_cache_dependencies ptm_shared/tests/test_astra_reader_temporal.py::test_saved_values_na_scope_links_questions_and_writer
node --experimental-strip-types --test frontend/tests/analysisContext.test.ts
npm run build --prefix frontend
PYTHONPATH=. codex-inputs/round11-20261010/runtime/bin/python scripts/validate_astra_design_display_browser.py
PYTHONPATH=. codex-inputs/round11-20261010/runtime/bin/python scripts/validate_astra_input_reuse_browser.py --url http://127.0.0.1:5193 --output /tmp/ptm-astra-design-display-reuse
```

브라우저 명령은 로컬 Vite 서버(5193)가 필요하다. `--before`는 변경 전 소스에서 기록하는 모드이며, 변경 후 검증에는 사용하지 않는다.

## 수정 파일

| 파일 | 수정 내용 |
|---|---|
| `ptm_shared/study_display.py`, `study_display.json` | 읽기 전용 집계/Markdown helper, 공통 표시명/설명/새 실험 계획 기본값 |
| `api-server/app/api/orders.py` | 기존 resolve 응답에 표시 projection 추가 |
| `frontend/src/lib/analysisContext.ts`, `frontend/tsconfig.json` | 공통 JSON 표시명 import, projection 타입, 새 실험 계획 초기화 |
| `frontend/src/components/CanonicalStudyFields.tsx` | `legacy_replicate` 타입, API projection 요약/상세 소비 |
| `frontend/src/components/StudyInputFields.tsx` | 원본 선택 상세의 계획 개수와 실제 Rep. 번호 분리 |
| `frontend/src/components/RerunOptionsModal.tsx`, `frontend/src/pages/OrderCreate.tsx`, `OrderDetail.tsx` | 동일 필드의 표시명/도움말 통일, 원문 호환 키 유지 |
| `ptm_shared/astra_inputs.py`, `astra_package.py` | 패키지 제목/필드 설명, 표시 JSON, 재현 코드 inventory 추가 |
| `ptm_shared/astra_card_inputs.py`, `astra_reader.py` | reader에 같은 projection 사용, 기존 질문 연결 보존 |
| `ptm_shared/tests/test_study_display.py`, `test_astra_reader_temporal.py` | 집계/metadata/reader 검증 |
| `api-server/tests/test_astra_input_reuse.py` | 기존 경계 테스트에 18파일·원문·계획·projection 일치 추가 |
| `frontend/tests/analysisContext.test.ts`, `astraDesignDisplay.browser.html`, `astraDesignDisplay.browser.tsx` | 계획 우선순위/원문 및 합성 UI fixture |
| `scripts/validate_astra_design_display_browser.py`, `validate_astra_input_reuse_browser.py` | 새 표시 검증 및 기존 회귀 fixture 응답 갱신 |
| 이 보고서, `design_replicate_display/*.png` | 변경 전후 화면과 검증 기록 |

## 실제 주문 검증 여부

요청서의 화면에 해당하는 실제 주문 ID를 로컬에서 명확히 식별할 근거가 없어, 특정 주문의 DB/Sample Config를 조회하거나 실제 반복 수를 확인하지 않았다. 다른 주문을 사용자 주문으로 간주하지 않았다. **18÷6으로 사용자 실제 주문이 조건별 3반복이라고 확정한 것이 아니다.** 이 보고서의 조건별 수는 모두 fixture에 직접 저장된 Rep. ID와 고유 파일/주입을 집계한 결과다. 운영 UI 반영 여부는 이번 로컬 구현·검증 범위에 포함되지 않는다.
