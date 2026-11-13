# AI01 — canonical effect scope catalog

기준 `fe11ff8472642fd896620b0027acf9a8e0bcae92`, 작업 branch `codex/astra-ai-usability`.
회차 SHA는 최종 통합 보고의 commit 표와 git log에 기록한다.

## 구현과 결정

`astra_evidence_catalog.build_evidence_index`가 패키지 실행 snapshot인
`study/study_design.json`을 읽고 기존 `effect_series.resolve_series`를 소비한다.
DB draft나 label에서 시간을 추측하지 않는다. `astra_evidence_access.v2`로 확장했다.
기존 `series_id`와 evidence/source key는 유지한다. 새 `effect_series_id`,
`reference_strategy`, `effect_kind`, `control_family` filter는 canonical point를 조회한다.
카드는 `effect_memberships_json`에 모든 binding을 보존한다. scalar가 유일하지 않으면 null,
여러 series면 `multiple_canonical_scopes`, 누락 binding은 unresolved다.
동일 membership 안에서 필터들의 AND를 검사하므로 서로 다른 시점의 값을 합쳐 맞추지 않는다.
snapshot 없는 구 archive는 `legacy_design_unavailable`, cross-sectional은 `not_temporal`이다.

정렬은 entity/method/version/score/track/effect scope → 숫자 target time → contrast ID →
source table/key → evidence ID다. 시점별 reference ID/time/pairing은 시간 앞에서 series를 나누지 않는다.
동일 시간의 contrast는 유지하고 null 시간은 마지막에 둔다. 정렬 계약과 snapshot hash가
catalog ID에 포함된다. cursor는 catalog/filter에 결합된다. 구 v1 catalog는 계속 읽는다.

일반 writer, reader projection/revision은 기존 `write_evidence_access`를 공유한다.
기존 CODE_FILES의 catalog 모듈 snapshot 경로를 그대로 이용한다. 새 reader 전용 재현 진입점은 AI04에서 연결한다.

## 재현과 검증

수정 전 production index/query에서 `effect_series_id` 요청은 `ValueError: Unknown filter`였다.
수정 후 raw_ptm/ptm_contrast/method_result 모두 같은 canonical population을 반환한다.
예: `query({'effect_series_id': sid, 'evidence_type': 'ptm_contrast'}, page_size=1)`.
reference hash/물리적 행/label 순서를 섞어도 1/5/15/30/60/180 및 별도 7.5/45/240분 fixture가
metadata 순서로 나온다. mixed pairing, multi-arm card, 0.5h/30min metadata,
동일 시간 tie/null, page 1/5/전체, 다른 catalog/filter cursor 거부, snapshot 변조 거부를 확인했다.
기존 0/5/15/50 summary, 전체 질문/typed citation, 정상 package 생성/reader replay,
reader 실패 시 pointer 보존 및 과학 fingerprint 불변 회귀를 재사용했다.

명령: `PYTHONPATH=.:ptm_shared/tests <기존 runtime>/bin/python -m pytest -q
ptm_shared/tests/test_ai_catalog.py ptm_shared/tests/test_astra_evidence_catalog.py
ptm_shared/tests/test_astra_reader_full.py` — 고유 **17 passed**, skip 없음.
pandas 기존 FutureWarning 2건. 결과 `codex-inputs/astra-ai-20261113/AI01.xml`.

실제 저장 자료 G11 `g3-173714b8042a41afa0248b88dc49d4c3`의 v1 catalog를 그대로 열어
미선정 `quant/comparisons.csv` 행 query→resolve→typed citation을 확인했다.
anchor=`source_anchor_validated`, semantic review=`not_performed`; 실제 matched 데이터 검증은 아니다.
소요 1.852초(한 로컬 측정). 결과/원본 행/hash는 `codex-inputs/astra-ai-20261113/actual_read.json`.
comparisons SHA `0936a28fab025b60255290ce4652a1f7274279740a536824b7802dadfa3b3875`,
method_scores SHA `bac9ec3ce979ced99aee840471afef057cefda197f5c9a8076e3c71045359ccd`,
성공 pointer SHA `a8ef7ab4d97a47b731ed7d88797b71c34534103c2a7d746715df2d506dcff7ef` 불변.

## 보존·한계

science CSV 값/NA/mask/ID는 이 수정에서 쓰지 않는다. catalog/index/guide만 의도적으로 변경한다.
합성 정상 package 테스트는 기존 작은 production 과학 함수를 실행했고 native/RAG/LLM은 대역이다.
실제 과학 재계산, PhosX, 외부 검색/모델 신규 호출은 0회다. 실제 matched/운영 UI 검증은 하지 않았다.
과거 archive를 수정하지 않았다. 최종 새 reader revision 및 통합 검증은 후속 회차에서 한 번 수행한다.
