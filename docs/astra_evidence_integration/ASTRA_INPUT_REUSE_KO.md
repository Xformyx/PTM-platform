# Astra 최초 입력 재사용 구현 보고서

완료 기록: 2026-10-29 (Asia/Seoul).

작업 기준: 2026-10-28 감사 SHA와 로컬 시작 HEAD 모두 `bbbf78751cb5522c34d115f4eec58406675bd916`.
추적 파일의 선행 수정은 없었으며 미추적 `codex-inputs/`는 기존 자료로 보존했다.
운영 UI·운영 DB·다른 checkout과의 일치는 확인하지 않았다. 이 보고서의 재현은 합성 입력이다.

## 최초 입력과 소비 필드 대응표

| 항목 | 최초 편집/복원 위치 | 저장 필드 | 공통 해석 및 실제 소비 | 패키지 기록 / 제한 |
|---|---|---|---|---|
| 종, PTM/분석 대상 | OrderCreate Project & Files; 재생성 order | order.species, ptm_type; analysis_context.analysis_target | species registry → resolve_study_design.study; science validate_execution, reference preflight | study_design.study; species/PTM 기반 capability |
| PR/PG/FASTA, 등록 reference | 최초 파일 업로드/등록 reference; 재생성 기존 파일 | order 파일 경로; science.reference.reference_id | dispatch INPUT_FIELDS/preflight → worker inputs; science_reference | 입력 inventory, input_lineage, reference inventory; 파일 보존과 소비는 구분 |
| 파일/조건/Control/Rep. | Sample Config file/Condition/Group/Rep. | sample_config.samples | legacy_samples → conditions/injections → contrast estimator | study_design, input snapshot; Rep.는 반복 유형의 선언이 아님 |
| 시간/단위 | 최초 Time Points, 조건명, 기존 manifest/확정 time | analysis_context.time_points, sample_manifest.conditions, 명시적 study_design override | time_list/label_time/time_value; numeric time metadata → temporal | study_design.conditions.time; 단위 없는 시간을 임의 확정하지 않음 |
| 처리명/농도·용량 | 최초 Treatment 및 기존 structured arms | treatment, treatment_arms/study_design.arms, 구형 acquisition_metadata.insulin_concentration | 공통 resolver arms; legacy insulin의 명시적 수치·단위만 제한적으로 변환 | arms/treatments; 자유문장 농도를 추정하지 않음 |
| Cell Type/Biological Question/Special Conditions | 기존 데이터 정보, 재생성 저장 context | cell_type, biological_question, special_conditions (tissue도 보존) | _metadata → study, source queries/reader interpretation | study_context, study_design.study.original_context; 정량 추정값에 사용하지 않음 |
| material/unit/technical injection/pair | 이미 저장된 manifest 또는 사용자 확정 mapping; 필요 시 같은 원본 편집 | sample_manifest, replication_declaration, study_design explicit mappings | resolver → ContrastEstimator / science inference | materials/injections/contrasts; unknown은 descriptive 유지 |
| enrichment | 기존 데이터 정보의 선택 선언 | enrichment_status | _metadata 및 plan/enrichment capability | 미입력 unknown; Astra의 일괄 필수값 아님 |
| DIA-NN 버전 | 원래 데이터 정보의 한 입력; 저장 alias 자동 복원 | science.diann_version + 확인된 processing alias 및 provenance | reconcile_diann_version → parser science.diann_version / study.processing | processing 표시와 parser 동일값; 타 소프트웨어 식별은 별도 |
| acquisition/processing | 선택 원본 metadata; 기존 acquisition_metadata 호환 | acquisition, processing, pre_treatment | _metadata → study/plan upstream_status | 기기/주입량/설정은 metadata; 정량 정책이 upstream normalization 사실을 뜻하지 않음 |
| 연구 질문/문헌 선택 | 기존 AstraWritingIntent; 저장값 복원 | report_options.research_questions, rag_collections; literature request/pins | capture_order, prepare_astra_inputs, literature selection/pinning | input snapshot, literature pin/comparison packet; 설정만 저장된 것을 실제 문헌 실행으로 주장하지 않음 |

## 변경 경계

공통 `resolve_study_design`, `resolve_context`, `merge_analysis_context`, API `_updated_analysis_context`와 `_attach_enrichment_free_profile`, `capture_order`, 기존 package writer를 재사용한다.
새 자동 Control resolver나 과학 방법은 추가하지 않는다. Legacy 입력/정량 및 recorded package replay는 적용 대상이 아니다.

## 구현 내용과 중복 입력 제거

- Astra의 `SampleDesignFields` → `CanonicalStudyFields` 기본 경로는 입력 정보 요약이다. 기준/처리 조건, 실제 시간, contrast, 기록된 반복 관계, 설명, 버전/reference를 표시한다. 조건별 Arm/Time/Unit/Role 편집표, Reference 및 Pairing dropdown을 요약에서 제거했다.
- `StudyInputFields`는 생성과 재생성이 공유하는 원본 데이터 정보 컴포넌트다. DIA-NN 버전 입력은 여기에만 둔다. 원래 설명 필드 상태와 합쳐 저장하며, 별도 Astra용 Cell Type/Treatment/Time Points/질문 상태를 만들지 않았다. material/unit/pair, 용량, acquisition 등 추가 선언은 선택 영역에 있다. 미입력 반복을 일괄 설문으로 요구하지 않는다.
- 재생성은 저장값을 복원한 요약으로 시작한다. “입력 정보 수정”을 선택해야 같은 원본 상태의 편집 영역이 열린다. 저장된 연구 질문·문헌 선택도 기본적으로 요약한다. 반드시 설정을 재확인하라는 기존 Astra 안내를 없앴다. 새 확인 체크나 popup은 추가하지 않았다.
- 재생성에서 파일/조건/Group/Rep. 변경이 필요하면 원본 Sample Config를 편집한다. PATCH가 해당 필드를 실제로 받은 경우에만 적용한다. 수정하지 않은 sample_config는 다시 정규화하여 덮어쓰지 않는다. 같은 공통 modal을 쓰는 duplicate에서도 명시적 수정값을 보존한다.
- 원본 정보가 변경되면 기존 350ms debounce와 폐기된 요청 응답 무시 처리를 재사용한다. 완료된 해석과 현재 입력의 일치 여부를 따로 확인해 갱신 중인 요약에 이전 설계를 표시하지 않는다. 제출은 `resolveSubmission`으로 현재 입력을 다시 resolve한 뒤 저장하며, 제출 중 편집을 잠근다. 서버도 기존 실행 직전 resolver/validation을 다시 거친다.

## 갱신 결함 수정 원리

`field_provenance`에 최소 정보인 `resolved_value`를 기록한다. 이전 객체/필드가 이 값과 같고 사용자 확정 표시가 없을 때만 자동 갱신한다. 기존 source·confirmation 기록을 유지하며 UI에서 명시적으로 바꾼 값에는 `user_confirmed`를 기록한다. 직접 API로 값이 바뀐 경우도 이전 output과 달라 자동값으로 덮어쓰지 않는다.

기존 injection을 condition/declaration만 보고 즉시 재사용하던 분기를 없앴다. 갱신 가능한 injection은 최신 manifest/replication source를 소비한다. 연결된 material의 biological unit/pair/technical injection도 출처에 따라 갱신한다. 사용자 확정 material과 이를 참조하는 injection은 유지한다. sample_id가 같은 injection의 안정 ID는 재사용한다.

이전 자동 condition이 현재 Sample Config에서 사라지면 활성 설계에서 제거한다. 유지되는 condition의 자동 role/arm/time은 최신 근거를 반영한다. 기존 contrast 전체가 있다는 이유로 생성을 건너뛰지 않고, 자동 contrast는 현재 target/reference와 명시적 pairing 근거로 갱신한다. 사용자 contrast와 유효한 ID는 보존한다. 단일 Control 연결은 기존 `single_existing_reference_group` 규칙을 그대로 쓴다.

감사 재현을 먼저 테스트로 작성했을 때 기준 코드에서 manifest 후입력(material 0개), 조건 0.5h→0.75h 변경(과거 조건/contrast 잔존), DIA-NN 연결/충돌 검사가 실패했다(6 실패, 1 통과). 수정 후 같은 합성 12 injection에서 manifest 후입력과 처음부터 입력한 경우의 conditions/materials/injections/contrasts/arms가 같다. 12 material과 명시적 paired mapping을 얻으며 반복 resolve 결과도 같다. 시간과 조건명은 테스트 fixture일 뿐 생산 코드에 하드코딩하지 않았다.

기존 `use_confirmed_structured` 시간 충돌 해결 기록도 보존한다. manifest와 Sample Config가 실제로 다른 조건을 선언하면 해당 sample의 `manifest_condition_conflict`를 표시한다.

### 구형 출처 정보의 한계

`resolved_value`가 없고 기존 출처로 자동 생성 여부를 확정할 수 없는 구형 객체는 자동값이라고 추측해 교체/삭제하지 않는다. 이런 객체가 현재 파일에 연결되지 않는 경우 원본 편집 영역에서 **그 조건 기록만** 명시적으로 제거할 수 있다. 현재 입력에 유효한 구형 확정 ID/매핑은 유지한다. 따라서 모든 과거 미확인 draft를 무조건 자동 정리한다는 주장은 하지 않는다. 발행된 구형 패키지는 수정하지 않고 recorded replay 설계를 사용한다.

## DIA-NN 및 unknown 처리

`reconcile_diann_version`은 live Astra의 공통 `resolve_context`/`resolve_study_design` 경로에만 연결했다. `science.diann_version`, DIA-NN임이 확인된 `processing.software_version`, 구형 `acquisition_metadata.diann_version`을 연결한다. 동일값은 자동 통합하고, 한쪽의 확인된 값은 parser와 processing 표시에 함께 전달한다. 연결 provenance를 기록하므로 한 곳에서 수정한 값도 기존 mirror에 반영된다.

서로 다른 확인된 버전은 `diann_version_conflict`로 해당 필드만 안내한다. 정체가 불분명한 software version은 DIA-NN으로 추측하지 않는다. 다른 소프트웨어라고 명시된 값은 보존하고 DIA-NN alias로 사용하지 않는다. 기기·dose·enrichment·upstream normalization 등 다른 필드를 임의로 연결하거나 기본 사실로 생성하지 않았다.

사용자 입력이 필요한 경우는 다음과 같다.

| 상황 | 필요한 원본 수정 / 이유 |
|---|---|
| 숫자 시간의 단위가 없거나 실제 시간 값이 충돌 | 해당 시간/단위를 명시하거나 해당 필드의 기존 structured-time 해결 동작 사용. 실행 축을 결정할 근거가 없음 |
| 기본 흐름의 reference가 없거나 여러 개 | Sample Config의 Control/처리 분류 수정. reference를 임의 선택하지 않음. 기존 명시적 다중 reference 설계는 전역 금지하지 않음 |
| 명시적 paired인데 pair/material mapping이 없음/충돌 | 해당 mapping만 보완. Control 공유나 Rep. 번호로 pair를 만들지 않음 |
| DIA-NN alias가 충돌하거나 software identity가 불명확 | 원본 정보의 단일 DIA-NN 입력에 확인된 값만 기록. 다른 software의 버전을 전용하지 않음 |
| 현재 입력과 불일치하는 출처 불명의 구형 기록 | 해당 조건만 원본 편집에서 정리. 과거 사용자 의도를 자동값으로 추측하지 않음 |

반복 정보 자체가 없으면 `unknown`/descriptive이며 warning이다. 한 Control 조건을 material 또는 biological unit 하나라고 가정하지 않는다. 선택 acquisition/용량/enrichment 정보도 unknown을 유지한다. 공급 intensity 사용은 upstream normalization 선언이 아니다.

## 저장·실행·패키지 경계

검증한 경로는 `UI → /orders/resolve-design → create/PATCH → SQLite ORM 재조회 → _attach_enrichment_free_profile.experimental_context → preprocessing worker 분기 → 기존 package metadata writer`다.

`merge_analysis_context`의 생략 키 보존/structured 값 원자 교체/명시적 null 삭제 계약을 유지한다. null로 지운 source가 직전 study metadata나 연결된 DIA-NN mirror에서 되살아나는 경로를 차단했다. GET으로 completed 주문을 읽는 것만으로 설계를 재해석하거나 DB를 변경하지 않는다.

기존 `capture_order`, `prepare_astra_inputs`, `resolve_plan` fingerprint, `_updated_analysis_context` 실행 검증, package `json_write`를 사용했다. `write_study_inputs`는 기존 패키지 내 세 JSON 쓰기만 추출한 경계이며 파일 내용/위치는 같다. 패키지 code inventory에 새 metadata helper도 포함했다. 원본 입력 snapshot, 기존 성공 pointer와 source/literature pin의 발행/재사용 정책은 바꾸지 않았다. 동일 수치 설계의 fingerprint는 반복 해석으로 바뀌지 않고 실제 반복 설계 변경 시 기존 규칙대로 바뀐다.

## 수정 파일과 재사용 함수

| 파일 | 변경 / 재사용 |
|---|---|
| `ptm_shared/study_design.py` | 기존 공통 resolver 내 자동 결과 갱신·보존, `legacy_samples`, time 변환, 단일 Control, validation 재사용 |
| `ptm_shared/study_input_metadata.py` | 확인된 DIA-NN alias만 정합화하는 작은 helper; 별도 설계 resolver가 아님 |
| `ptm_shared/study_execution.py` | 기존 `resolve_context`에 metadata 연결 |
| `ptm_shared/analysis_context.py` | 기존 merger의 null 삭제가 canonical fallback에서 되살아나지 않도록 처리 |
| `api-server/app/api/orders.py` | resolve 응답에 정합화 context 반환; 명시적 sample_config 수정 지원. 기존 create/PATCH/dispatch/preflight 재사용 |
| `ptm_shared/astra_package.py` | 기존 study JSON writer 경계 추출 및 helper code inventory 추가 |
| `frontend/src/components/CanonicalStudyFields.tsx` | Astra 읽기 전용 요약, 최신 응답 처리, 기존 원본 확정 편집 동작 재사용 |
| `frontend/src/components/SampleDesignFields.tsx` | Astra의 중복 버전/design axis/reference 입력을 원본 영역으로 이동 |
| `frontend/src/components/StudyInputFields.tsx` | 생성·재생성이 공유하는 원본 정보 편집 영역 |
| `frontend/src/lib/analysisContext.ts` | 저장된 metadata 복원, 현재 source 제출 resolve. 기존 context merger/샘플 변환 재사용 |
| `frontend/src/pages/OrderCreate.tsx` | 원본 정보와 요약 연결, 제출 전 현재 입력 resolve |
| `frontend/src/components/RerunOptionsModal.tsx`, `frontend/src/pages/OrderDetail.tsx` | 저장값 요약 및 명시적 원본 수정 payload 전달 |
| `ptm_shared/tests/test_study_input_reuse.py`, `api-server/tests/test_astra_input_reuse.py` | resolver/metadata/HTTP/DB/dispatch/worker/package 경계 회귀 |
| `frontend/tests/analysisContext.test.ts`, `frontend/tests/astraInputReuse.browser.*`, `scripts/validate_astra_input_reuse_browser.py` | 상태/비동기 응답/요약/재생성/Legacy 브라우저 검증 |

## 검증 결과와 실행 범위

- Python 경계 테스트: **52 passed, 2 deselected**. 새 입력 재사용 테스트 16개 포함. 두 제외 항목은 전체 bundle replay/publication과 registry recovery 테스트로 이번 범위에 필요하지 않다.
- 프런트엔드 상태 테스트: **7 passed**.
- `npm run build --prefix frontend`: 성공. 기존 Browserslist 데이터 갱신 및 큰 bundle 경고는 남으며 빌드 오류는 없다.
- 합성 브라우저: 성공, page error 0. 실제 공통 resolver를 호출하고 보조 API 응답만 대역 처리했다. 오래된 응답 지연, 90→120분 조건 변경, 미리보기 뒤 manifest 입력, 버전 단일 수정, 재생성 읽기 전용 표시/저장, Legacy manifest 입력 유지 확인. 전체 OrderCreate wizard를 실제 업로드까지 클릭한 E2E는 아니며, 생성에서 쓰는 공통 source/summary와 실제 RerunOptionsModal을 검증했다.
- HTTP/SQLite 검증은 실제 resolve/create/PATCH/GET, 임시 SQLite ORM 재조회, dispatch/preflight, `capture_order` 및 package JSON writer를 사용했다. worker의 실제 preprocessing 분기를 통과하되 broker/운영 DB/progress/webhook과 과학 엔진은 대역 처리했다. worker 대역은 전달받은 context를 실제 JSON writer로 기록했으며 ZIP/과학 결과를 생성한 것으로 주장하지 않는다.
- DIA-NN 버전 네 입력 경로에서 실제 `diann_evidence.observations`에 한 행의 합성 report를 전달해 기록된 버전과 processing 표시값이 일치함을 확인했다. 충돌·다른 software·식별 불가도 별도로 검증했다.
- 작은 기존 합성 PR/PG fixture로 U/P/A, NA, mask, 집계·shared Control 표본 수 및 반복 resolve 수치 동일성을 확인했다. 실제 설계를 바꾼 결과까지 이전 수치와 같다고 요구하지 않았다.
- replay 검증은 archived config가 compute 경계에 그대로 전달되는지 확인하는 대역 테스트다. archive integrity/과학 compute는 대역 처리했으며 전체 ZIP 재생성이나 대규모 offline replay를 실행하지 않았다.

실행 명령:

```sh
PYTHONPATH=api-server:workers:.:ptm_shared/tests codex-inputs/round11-20261010/runtime/bin/python -m pytest -q ptm_shared/tests/test_study_input_reuse.py ptm_shared/tests/test_generic_study.py api-server/tests/test_analysis_context_preservation.py api-server/tests/test_astra_input_reuse.py api-server/tests/test_astra_input_capture.py ptm_shared/tests/test_astra_execution_profile.py -k 'not bundle and not atomic'
node --experimental-strip-types --test frontend/tests/analysisContext.test.ts
npm run build --prefix frontend
# localhost 개발 서버 실행 후
PYTHONPATH=. codex-inputs/round11-20261010/runtime/bin/python scripts/validate_astra_input_reuse_browser.py
```

브라우저 검증 기록과 화면: `/tmp/ptm-astra-input-reuse-browser/validation.json`, `initial-summary.png`, `rerun-summary.png`.
기존 로컬 Python runtime을 재사용했고 SQLite 검증용 `aiosqlite`만 cached wheel로 설치했다. 대형 입력/패키지를 복사하거나 삭제하지 않았다. 실제 PhosX·전체 정량·RAG·LLM 계산, 외부 참조 수집, 운영 DB 접근은 하지 않았다.

## 로컬 커밋과 운영 반영 여부

- 데이터 흐름: `ffca7443cc66f6f1fa0dacfe68f3f9a20604e2f9` — `fix(astra): refresh source-derived study design and unify DIA-NN metadata`
- UI: `def06fa6b84bf53a2fd39c6ea53ba698da04d90a` — `feat(astra): summarize saved inputs and edit the shared source once`
- 이 완료 보고서는 별도 문서 커밋으로 기록한다.

**로컬 구현·검증만 완료했다. push, 운영 배포, 운영 flag 변경은 수행하지 않았다.** 운영 코드·데이터에 이 문서 작성이나 로컬 변경이 반영되었다고 보고하지 않는다.

