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
