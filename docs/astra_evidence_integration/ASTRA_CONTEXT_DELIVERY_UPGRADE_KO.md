# 기존 연구 정보 전달 개선

기준/작업 시작: `97eb0cb960a730381f8e74d54ad168e0fa4d6480`, branch `codex/astra-context-delivery`.
원래 작업 트리는 tracked clean이며 기존 `codex-inputs/`는 보존한다. 운영 환경과 일치는 확인하지 않았다.

## MC01 — 저장/발행 전달 검증

기존 `capture_order` allowlist와 sanitization, `prepare_astra_inputs`, API dispatch, worker의 `run_primary_analysis` → `astra_package` 경로를 재사용한다. 새 snapshot은 `astra_research_input.v2`와 `study_context_roles.v2`를 기록한다. `biological_question` 키와 기존 원문은 유지한다.

저장된 ORM 연구 필드와 캡처 값을 대조한 뒤 원문 leaf의 JSON 타입/hash를 receipt로 고정한다. task config의 별도 receipt로 snapshot 삭제/교체를 검출한다. 패키지 writer가 실제 JSON bytes를 기록하고 manifest의 raw/canonical pointer를 다시 resolve한다. canonical 값은 resolver 변환이므로 raw와 동일하다고 강제하지 않는다. sample 계획 값은 injection 대응으로 잘못 표시하지 않는다.

`transfer_contract`의 inventory만으로 `unexpected_missing=0`을 주장하지 않는다. 실제 readback 뒤 계산하며 `seal_archive`는 파일 검사와 ZIP entry 검사를 모두 통과해야 원자 발행한다. 구 snapshot에는 `legacy_unverified`를 반환한다. 이는 구 정보가 잘못됐다는 뜻이 아니라 저장 당시 독립 receipt가 없다는 뜻이다.

검증: metadata writer/실제 작은 ZIP seal 및 fault injection 11개, 기존 API 캡처 fixture 2개, inventory 1개, 총 **14 passed**. false→0, 삭제, 값 변경, source_record 교체, raw/canonical pointer, manifest 누락, canonical JSON hash 변경을 경계/field path로 검출했다. 한글/긴 원문/null/false/0/빈 문자열/빈 배열/JSON pointer escaping 및 secret 제외도 확인했다. 이전 성공 pointer/ZIP bytes는 실패 시 보존됐다.

API fixture의 DB는 대역이며 seal fixture의 과학 검증만 대역이다. 실제 production metadata writer, ZIP writer/hash/CRC, 전달 검증 함수를 사용했다. 운영 DB/queue/download 검증은 아니다. 정량·PhosX·검색·모델 호출 0회.

MC01 checkpoint: 소스 검증 완료, 다음 MC02 공통 context projection/consumer 연결. 디스크 약 3.4GiB로 대형 기존 archive는 복제하지 않는다. 실제 자료는 기존 SF 최종 archive를 읽기 전용으로 점검할 예정이다.

## MC02 — 공통 맥락/consumer 연결

MC01 commit: `99752c7`. 새 `study_context_delivery`는 resolver가 아닌 실행 snapshot의 읽기 전용 projection이다. `reader/STUDY_CONTEXT.json/.md`가 원문·실행 설계·명시적 질문·기대/가설 네 역할과 원문 JSON pointer/hash를 제공한다. 기존 `study_display`/`comparison_summary`를 사용하며 원문 dose를 특정 arm에 추정 배정하지 않는다. 구조화된 arms/conditions/contrasts는 그대로 노출한다. host 정보는 transgene/feature taxon을 대신하지 않는다.

`write_reader` → authoring packet, START_HERE/STUDY_BRIEF → context guide, 발행 pointer → `load_report_context` → writer의 temporal/biological synthesis formatter로 연결했다. 새 모듈과 기존 입력 계약은 READER_CODE_FILES에 포함했다. 과거 실행에도 새 reader revision으로 읽기 자료를 추가할 수 있으며 기존 snapshot/BQ 내용은 바꾸지 않는다. 실행 기록은 실제 artifact/manifest를 참조하며 고정 biological p/q 미구현 문장을 brief에서 제거했다.

검증: 긴 원문/preview/consumer hash와 published report-input 2개 추가, 기존 isolated bundled reader replay 1개 통과. 해당 suite 14 passed (이전 MC01 회귀 포함), 현재 고유 검증 17개. 새 interpreter/다른 cwd/공백 경로에서 reader 재생성 byte 비교 및 source read-only guard 통과. 첫 replay에서 method registry 작성 순서로 availability가 달라지는 문제를 발견해, 생성 시점의 파일 유무를 실행 사실로 단정하지 않고 최종 실행 manifest를 참조하도록 수정했다. 모델 호출은 없다. 기존 tiny fixture의 production 과학 함수는 package/replay 경계 검증에만 사용했으며 실제 자료의 재계산은 없다.

MC02 checkpoint: 공통 projection·reader·report 연결 검증 완료. 다음 MC03 신규/legacy 질문 계약과 실제 identity 기반 entity routing.

## MC03 — Design/질문 의미와 entity 계약

MC02 commit: `4af4883`. `_questions`는 snapshot의 명시적 `study_context_roles.v2`에서만 Design→BQ 자동 생성을 중단한다. 호환 키/원문은 original_questions와 공통 context에 남는다. 명시적 질문 빈 배열은 빈 상태이며 저장된 question_id는 유지한다. marker가 없는 archive는 문장이나 BQ 존재로 추정하지 않고 기존 BQ-001/RQ 동작을 유지한다.

기존 `build_question_map`의 선택적 `measured_identity.v1` 경로는 전체 observation의 실제 feature identity/taxon/gene을 검증한다. case-insensitive symbol matching은 form/card/taxon을 합치지 않는다. accession/raw_identifier alias는 실제 `science/reference_inventory`의 accession+taxon+gene 일치가 있을 때만 사용한다. 제공되지 않은 gene synonym/family/isoform은 생성하지 않는다. 기술 약자와 미확인 entity는 원문·unresolved로 보존하고 hard gene filter로 쓰지 않는다. ERK/AKT의 정적 family 확장은 신규 계약에 적용하지 않는다. 기존 v2 질문 경로는 그대로다.

검증: 신규/legacy 계약, 빈 질문, 저장 ID, MAPK1+기술 약자, mixed-case/taxon/검증 alias, 모호한 family, Top-N 0/5/15/50의 전체 question source ID 불변 등 신규 5개 case 통과. 기존 reader/전체 접근 회귀 2개 및 frozen 문헌/원문 prompt/pin 변조 차단 회귀 3개 통과. 문헌 테스트는 기존 retriever/model 대역이며 신규 외부 검색/모델 호출은 없다. Design 원문은 기존 literature study context에 계속 전달된다.

MC03 checkpoint: 10개 관련 검증 통과. 다음 MC04 활성 공통 안내의 benchmark 문구 제거 및 report-context 소비 검증. 과거 frozen 결과나 citation을 재분류하지 않았다.

## MC04 — 중립 안내와 실행 고정 report-input

MC03 commit: `c645814`. 활성 `astra_reader`의 expected insulin pathway / insulin cascade 안내 두 곳을 기록된 기대 경로·시간 반응 안내로 일반화했다. 실제 사용자 insulin 원문과 `astra_literature`의 기존 insulin concentration 호환 projection은 변경하지 않았다. biological synthesis의 사용자 표시명도 Biological Design으로 통일했다.

보고서 writer가 발행된 context를 읽은 후 `bind_report_state`로 보고서 입력용 복사본만 바인딩한다. 최신 draft나 report-level override로 실행 설명을 바꾸지 않는다. 기존 reader authoring serializer/formatter에도 같은 binding을 전달하고 새 계약의 명시적 질문만 라우팅한다. 원문/실행 설계/기대/문헌/관측을 구별하며 파일 연결과 의미 검토 완료를 분리한다.

검증: insulin / amyloid-treated microglia / 두 약물 3개 fixture에서 실제 authoring packet/formatter를 실행해 원문·source hash와 빈 질문 유지, draft 미변경, 잘못된 현재 설명 배제를 확인했다. context/질문 suite 21 passed(기존 case 포함), 기존 biological synthesis 17 passed. 새 입력 UI·wizard·필수 질문은 추가하지 않았다. 새 모델/검색 호출 0회.

MC04 checkpoint: 템플릿/formatter 검증 완료. 다음 MC05 실제 저장 archive 읽기, 격리 DB 저장/재조회, 발행/reader revision/replay 및 보존 통합 검증.

## MC05 — 통합 검증과 지원 경계

MC04 commit: `b588d3c`. 2026-11-15 KST에 통합 검증을 마쳤다. 저장 당시 source record/허용된 제외 사유/계약 marker를 독립적으로 대조하고, canonical study에서 원문 설명·host taxonomy·실제 injection/Rep. 매핑이 사라지는 오류도 발행 전에 거부한다. `false`와 `0`을 Python equality로 혼동하지 않도록 reader projection도 JSON 값·타입으로 검증한다. manifest의 의미 역할을 관측 결과로 바꾸는 변형도 검출한다. 새 provenance에는 revision의 발행 run과 원래 execution snapshot run을 구분한다.

일반 writer는 reader가 없는 구 Astra profile에서도 공통 맥락 파일을 생성한다. explicit literature selection revision은 기존 허용 정책과 parent receipt 이력을 유지한 채 새 selection receipt만 기록한다. 질문용 reference inventory가 reader-only replay의 입력 목록에서 빠지지 않도록 연결했다. 실제 측정 accession alias 질문을 ZIP 자체 코드로 재현하는 검증을 추가했다.

### 실제 호출 경로

1. 기존 OrderCreate/StudyInputFields/수정 UI → `Order`의 sample_config / analysis_context / report_options JSON 저장. 새 UI는 없다.
2. API ORM 재조회 → `prepare_astra_inputs` → `capture_order` / `verify_order_capture` → 기존 dispatch의 `user_input_snapshot` + 별도 `research_input_receipt`.
3. `_attach_enrichment_free_profile` → `preprocessing.tasks.run_preprocessing` → 기존 `run_primary_analysis` → `astra_package`: snapshot receipt와 원문 보존 계약을 검증한 후 기존 정량/cache 경로를 사용한다.
4. `transfer_contract` → 실제 CSV/JSON → `write_study_inputs` → `write_context` → `write_reader`. 원문/full locator와 bounded preview가 같은 source hash를 참조한다.
5. `validate_delivery` → `seal_archive`의 JSON pointer/값/타입/consumer link/ZIP entry bytes 검증 → 기존 atomic publish/성공 pointer. 실패하면 이전 성공이 유지된다.
6. 발행 pointer → `load_report_context` / `bind_report_state` → 기존 writer의 temporal·biological synthesis·reader authoring serializer/formatter. 모델 호출 없이 report-input까지만 검증했다.
7. CODE_FILES / READER_CODE_FILES → 일반 발행·immutable reader revision·bundled `reader_replay.py`. 과거 archive의 코드는 덮어쓰지 않는다.

전체 필드 대응과 conversion/제한은 `ASTRA_CONTEXT_DELIVERY_MAPPING.csv`의 21개 항목을 참조한다. 실제 각 leaf의 pointer는 패키지 `study/input_field_manifest.csv`가 제공한다. `source_receipt`와 `input_delivery_receipt`는 전달 검증용 metadata이며 별도의 입력 저장소나 설계 resolver가 아니다.

### 검증 결과

- 고유 자동 case **69개 통과**, 실패/skip 0. 최종 전체 suite 68개, 이후 변경 경계 31개 및 metadata 경계 26개를 재검증했다. 중복 case를 합산하지 않았다.
- 원래 inventory의 성공 표시와 실제 readback을 분리했다. 원문·snapshot·context·canonical·manifest·ZIP·reader의 삭제/변형/잘못된 pointer/stale binding을 경계와 field path로 검출했다.
- 실제 FastAPI ASGI + 격리 SQLite ORM 생성/GET/PATCH/재조회 → 실제 capture/profile 준비 → worker 함수 → metadata ZIP 검증 통과. Celery/Redis/progress/run-control과 과학 sink만 대역이다. 운영 queue/DB에 접속하지 않았다.
- 공통/시간대별/직접 연결의 실제 contrast IDs·양쪽 시간·반복·unknown pairing 보존. 두 arm의 다른 dose/unit/vehicle/exposure, rat host와 human transgene, 예정 3/등록 2, 조건별 6주입/2 biological units를 분리했다. 자유문장 dose를 새 사실로 파싱하지 않았다.
- Design-only/빈 질문, MAPK1 + DIA/DIA-NN/FASTA, mixed-case/실제 accession alias, 모호한 taxon/family, 과거 BQ/RQ/frozen pin, Top-N 0/5/15/50의 전체 질문 접근을 검증했다.
- context-only 변경에서 기존 quant cache를 재사용하고 U/P/A·NA·ID를 보존했다. 작은 기존 archive의 과학/metadata table 50개는 기존 scientific replay에서 byte-identical이었다. reader/field manifest/새 context 산출물 변경과 과학 수치 불변을 구분한다.
- bundled reader는 저장소 밖 cwd·공백 경로·PYTHONPATH 없는 새 interpreter에서 source hash 검증과 과학/네트워크/문헌 실행 guard를 통과했다. native PhosX 실수치 검증은 이 회차 범위가 아니다.
- 경고는 기존 pandas empty/all-NA concatenation FutureWarning이다. frontend 변경이 없어 frontend build는 수행하지 않았다. 새로운 방법, 대규모 과학 계산, 운영 end-to-end는 수행하지 않았다.

### 실제 저장 자료 확인

기존 SF 최종 실제 shared-Control archive:
`codex-inputs/substrate-signal-20261114/final-reader-revision-v3/astra_analysis_package_g0-adfcea86b3504959b75986baf994ade4.zip`

원본 ZIP SHA256: `ea3a905d2c5d60ea9735a0f62714f8d6338f38fcc5d6f5ad98964b32a2924926`.

실제 metadata/source-pin 13개 파일의 ZIP entry와 기존 추출본 hash를 대조했다. 684 raw pointer와 97 canonical pointer가 resolve됐고 미해결 pointer는 0이었다. 기존 `BQ-001`·원문·frozen 문헌 binding/pin과 원본 ZIP/성공 pointer hash를 보존했다. 309MB source pin은 streaming hash로 읽었고 복제하지 않았다.

이것은 접근 가능한 저장 결과 한 건의 검증이다. 최초 운영 DB와 독립적으로 대조한 것은 아니므로 구 `unexpected_missing=0`을 DB→ZIP 전체 증명으로 승격하지 않았다. 구 snapshot은 계속 `legacy_unverified`이며 과거 질문 의미도 재분류하지 않았다. 실제 time-matched 자료, 운영 UI/queue/download는 미검증이다.

현재 코드의 실제 자료 기반 맥락 preview는 `codex-inputs/context-delivery-20261114/actual-context-preview/reader/STUDY_CONTEXT.md`와 `.json`이다. 원문 ZIP을 수정한 reader revision이 아니라, 동일 원문 locator/hash를 사용한 별도 projection이다. 실제 full reader revision/replay는 약 4.7GiB 추출본 + 0.6GiB ZIP + 2.5GiB replay + 2GiB reserve가 필요하여 만들지 않았다. 원본/실패 후보/cache/runtime 삭제로 공간을 확보하지 않았다.

### 변경·보존 및 판단 한계

허용 변경: 새 input receipt/field manifest/전달 검증, context JSON·guide·brief·START_HERE, 신규 계약의 질문 map/전체 link, authoring/report-input, reader code snapshot/catalog descriptor hash. catalog_id가 달라질 수 있지만 과거 evidence/source key를 새 run 소속으로 재표시하지 않는다.

보존: 원본 PR/PG/FASTA, quant 값·NA·mask·normalization, kinase/method 점수·membership·coverage/no-call, canonical condition/contrast/material/pair IDs, source/literature pin과 과거 BQ/RQ·frozen 문헌 결과, 기존 성공 ZIP/pointer, SF 전체 관측·signal-flow bindings. 수치 엔진 파일은 변경하지 않았다.

새 실제 자료 과학 계산 **0회**, 신규 외부 검색 **0회**, 실제 모델 호출 **0회**. 합성 검증에서는 기존 함수를 실행했다. 한 번의 계측 suite에서 `calculate`/`quantify_contrasts` 각각 12회, native dispatch 4회, literature collect 대역 14회를 기록했다. 이것은 해당 suite의 계측이며 개발 전체 누적 횟수나 실제 native/LLM 실행 횟수가 아니다. 계측 overhead가 커 후속 검증은 계측 없이 실행했다.

자료 저장, reader/report 연결, 모델의 실제 열람, 의미 승인, 연구 성능 향상은 별개다. 이번 결과는 저장 정보와 source scope의 전달·검증 완료이며 새 보고서 모델 품질 또는 생물학적 타당성을 승인한 결과가 아니다.

기존 caffeinate PID 2450/5292는 유지했고 `pmset`의 PreventUserIdleSystemSleep=1을 확인했다. 작업용 Python/서버/브라우저 잔여 프로세스는 최종 점검에서 없었다. 최초 디스크 여유 약 3.35GiB, 최종 값과 산출물 hash/명령은 RESULTS.json에 기록한다. 기존 untracked `codex-inputs/`는 커밋하지 않는다. push·merge·배포·flag 변경은 수행하지 않았다.

### 최종 current-code revision / archive reader replay

최종 코드로 작은 합성 archive의 immutable reader revision을 생성하고, 그 새 archive 자체 코드의 reader-only replay를 별도 경로에서 실행했다. 원본 합성 ZIP hash는 유지됐고 저장 표 125개의 hash를 보존했다. 새 reader 산출물 35개는 byte-identical이었다. 이 검증은 자동 case 수에 별도로 더하지 않았다.

- 새 합성 ZIP: `codex-inputs/context-delivery-20261114/final-synthetic-reader-revision/astra_analysis_package_g0-720c6f3ba6a54a9f9f0550e75ec5f7e3.zip`
- SHA256: `31b581df33419597b7658eeca4cb6fc1e79a10cbba13e35cb46cb4e652caded0`
- 크기: 2630248 bytes
- reader replay 출력: `codex-inputs/context-delivery-20261114/final-synthetic-reader-replay`
- 현재 코드 revision 중 신규 과학/외부 검색/실제 모델 호출: 모두 0회. 기존 archive 코드를 덮어쓰지 않았다.

새 출력 경로로 reader-only 재현하는 명령(저장소 루트 기준):

```sh
env -u PYTHONPATH codex-inputs/round11-20261010/runtime/bin/python -I -B \
  codex-inputs/context-delivery-20261114/final-synthetic-reader-revision/enrichment_free_runs/g0-720c6f3ba6a54a9f9f0550e75ec5f7e3/reader_replay.py \
  --output /tmp/ptm-context-reader-new-output
```

출력 경로는 아직 존재하지 않는 새 경로여야 한다. 현재 코드 revision 생성과 해당 archive 자체 코드 replay는 서로 다른 검증이며, 과거 실자료 reader 전부와 byte-identical이라고 주장하지 않는다.

MC05 checkpoint: 69개 고유 자동 case와 최종 합성 revision/replay 통과. 실제 저장 자료의 제한은 위와 같다. 다음 명령은 필요한 소스·테스트·문서의 로컬 커밋이며 추가 과학 실행이나 원격 변경은 없다.

### 로컬 커밋과 최종 상태

브랜치: `codex/astra-context-delivery`. 구현·검증 단계별 커밋은 다음과 같다.

| 단계 | 상태 | 로컬 SHA |
|---|---|---|
| MC01 | 구현·가능한 검증 완료 | `99752c7965e923dc1b1cc9af51ef36806888ced9` |
| MC02 | 구현·가능한 검증 완료 | `4af4883a87e317f9982fc72b762c6b8d5a49b452` |
| MC03 | 구현·가능한 검증 완료 | `c6458144cdcef7ce077d6145d67375013b3eab49` |
| MC04 | 구현·가능한 검증 완료 | `b588d3c71f1e0e4cd23240dd669436a7ecd6c7b4` |
| MC05 | 구현·가능한 검증 완료 | `fe58f925798775df97499d19d57a45b77f0f8b35` |

최종 디스크 가용 공간: 7,126,220,800 bytes (약 6.64 GiB). 2026-11-15 11:55:56 KST 프로세스 점검에서 이번 작업의 Python/서버/브라우저 잔여 프로세스는 0개였으며 기존 caffeinate 2개는 유지했다.

체크포인트: MC01–MC05 완료. 독립적으로 가능한 개발·검증은 끝났으며, 실제 운영 DB/queue/download·실제 matched 입력·대형 실제 revision/replay·신규 모델 보고서는 위에 명시한 범위대로 미검증이다. 구현 커밋 이후 이 SHA와 최종 결과를 기록하는 문서 커밋만 추가한다. 원격 변경은 없다.
