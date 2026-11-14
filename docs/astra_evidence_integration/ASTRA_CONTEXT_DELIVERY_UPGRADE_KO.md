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
