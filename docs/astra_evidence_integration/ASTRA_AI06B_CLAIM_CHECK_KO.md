# AI06-B — 구조화된 주장 검증

기준: `1034ce52059cc244f11d054cf540b5bdb0dace08`, branch `codex/astra-ai-usability`.
로컬 완료 SHA는 최종 통합 보고서의 회차 표에 기록한다. push/배포 없음.

## 계약과 재사용

`astra_claim_check.check_claims` / `EvidenceCatalog.check_claims`는 기존
`validate_citations`, 동일 세션의 검증된 `source_rows`, `resolve_series`,
`quantitative_fields.field_semantics`를 소비한다. 새 모델·검색·과학 계산은 없다.
`astra_claim_check.v1` ledger는 claim_id/run_id/catalog_id/evidence_refs,
field_path/asserted_value/unit/claim_level, 선택적 target/reference/time/comparison_kind,
rounding_precision/tolerance/literature_refs를 받는다. 여러 anchor 중 값을 주장할
대상은 value_evidence_id로 지정해야 하며 첫 binding을 임의 선택하지 않는다.

```sh
PYTHONPATH=PACKAGE/reproducibility/code python -m ptm_shared.astra_evidence_catalog \
  --package PACKAGE check-claims --claims claims.json
```

출력은 anchor_status, numeric_status, scope_status, restriction_status,
literature_anchor_status, semantic_review_status를 분리한다. 근거 행의 실제 값,
canonical point, 공통 field descriptor, 실패/미확인 사유를 함께 반환한다.
기계적 통과는 `mechanically_validated_not_semantically_reviewed`이며 의미 검토는
항상 `not_performed`다. 자연어 주장을 keyword로 승인하지 않는다.

## 확인한 경계

- 변경 전 API가 없어 production 호출 fixture가 AttributeError로 실패했다.
- 값 0.373313567 → 선언 정밀도 3의 0.373은 통과한다. 부호 반전은 거부한다.
- tolerance는 유한·비음수이고 max(1e-6, |원값|×1e-6) 이하만 허용한다.
  명시한 반올림 허용범위와 기계 오차 이외로 범위를 늘리지 않는다.
- source NA=주장 0은 실패, NA=NA 또는 미기록 필드는 unverifiable다.
- 잘못된 Control/시간/unit, method q→biological q, no-call→kinase inactivity,
  footprint/상대 효과→확정 kinase call, fragment→whole-paper review는 거부한다.
- 유효한 no-call 상태 인용은 통과한다. localization을 승격하지 않는다.
- 다른 run/catalog의 anchor를 현 run으로 소급 귀속하지 않는다.
- JSON 내부 값은 명시적 경로만 지원한다. 예: card_json.source_bindings.1.A.
  여러 binding에 대한 암묵적 대표 scope는 허용하지 않는다.
- 구형 detection에 버전이 없으면 저장 값은 보존하고 해당 post-reference 필드의
  semantics를 unknown/legacy_detection_semantics_not_versioned로 둔다.
  reader-only 수정으로 과거 0을 새 계산 결과라고 설명하지 않는다.

## 검증과 보존

AI06-B 전용 12개 + 공통 semantics 3개 + bundle 4개 = 19개 통과.
결과: `codex-inputs/astra-ai-20261113/AI06B.xml`.
합성 저장 표와 실제 production catalog/resolver를 사용했다. 실제 저장 표의 대표
주장과 새 reader revision은 최종 통합 점검에서 별도로 확인한다.
숫자 표/ID/NA/mask/pin을 수정하지 않는다. 변경은 checker, 공통 descriptor,
CLI/guide와 code snapshot 목록이며 기존 발행 ZIP/pointer는 수정하지 않는다.
새 checker는 일반 writer와 revision의 READER_CODE_FILES에 포함된다.
