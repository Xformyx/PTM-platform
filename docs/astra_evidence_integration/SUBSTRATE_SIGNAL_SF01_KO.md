# SF01 전체 기질 관측 및 canonical scope

기준 작업 SHA `92a3776fcc3747b981a77a4ff0838811b5a9b150`, branch `codex/substrate-signal-flow`.
원격 Xformyx/PTM-platform/main과 일치하는 시작점에서 작업했다. 기존 untracked codex-inputs는 보존했다.

| 원본 / key | 공통 projection | 소비 경계 |
|---|---|---|
| quant/comparisons / form_id, contrast_id | form × effect_series × U_joint/P_joint/A/U_all/P_all trajectory | SF04 UI, SF05 reader/report |
| reader_adapter/form_identity / form_id | 원 identity JSON, 원본 locator | taxon/precursor/측정군 유지 |
| reader_adapter/precursor_membership / membership_id | 명시적 source hash/row/precursor/sequence/taxon crosswalk | 자료 없으면 unavailable, symbol join 금지 |
| temporal/ptm_temporal_features / feature_id | 저장된 pattern/bracket/gap-safe AUC locator | 계산 재실행 없음 |
| study/study_design.json | effect_series.resolve_series | point별 실제 reference/time/pairing |
| kinase edges/contributions/profiles/fixed/anchors/sensitivity/inference/method | SF02 exact bundle | 새 점수/합산 없음 |
| relation bundle / exact identity evidence | SF03 typed links | benchmark registry는 runner-only이므로 사용하지 않음 |
| 기존 catalog / source keys | Sources validation + source SHA/evidence_id | 기존 evidence/source ID 보존 |

`substrate_signal_flow.py`는 새 정량 엔진이 아닌 저장 표 projection이다. `included=false`인 유한 값은 calculation_trace_value에 남고 일반 value는 null이다. 카드 보류와 정량 eligibility는 독립이다. Top-N, pin, 페이지를 projection 인자로 받지 않는다. 동일 시간 tie, 미기록 시간, matched point별 mixed pairing을 canonical resolver에서 가져온다. feature가 없는 경우 패턴을 flat으로 만들지 않는다.

검증: production projection을 실제 저장형 합성 fixture로 호출. mixed pairing/참조 ID 순서/7.5·45·240분, 제외된 유한 값, 별도 form, null 시간, duplicate key 거부, exact crosswalk를 확인한다. 잘못된 matched null-time fixture는 resolver가 정상 거부하여 null-time 검증을 shared scope로 수정했다. 이 단계는 UI/발행 연결 완료 주장이 아니며 SF04/SF05에서 연결한다.

환경: 기존 Python3.11 runtime 재사용, 시작 여유 약22.7GiB. 실제 저장 G11 reader revision 접근 가능. 실제 time-matched 주문은 확인하지 않았다. 새 계산·검색·모델 호출 0회. 단계 SHA는 최종 통합 보고 및 checkpoint에 기록한다.
