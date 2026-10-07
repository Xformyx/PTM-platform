# 회차 06 — 구현 전 입력 계약 (2026-10-07)

기준 main: 3a0e83a9bc3046f875a972e71cc2d6e84e1b096a. 수치 변환 정책:
`astra_card_input.v1`. 카드 생성/선정은 이번 production 경로에서 실행하지 않는다.

| 원본 표·키 | 대상 | 의미/제한 |
|---|---|---|
| quant/summary.form_id | adapter row.form_id | 정량 form; 카드 precursor ID와 별개 |
| summary Protein.Group + Modified.Sequence → inputs/PR의 동일 키 | precursor_membership | 실제 PR row, Precursor.Id, charge; 원본 행 번호(헤더 다음 1) 보존 |
| PR membership가 정확히 1행인 form | card row Precursor.Id/Charge | 유일한 실제 precursor만 지원; 복수/충돌/누락은 raw-only |
| summary Genes, representative_sites, Protein.Group, Modified.Sequence | gene, position, protein_group, modified_sequence | position은 FASTA의 대표 표시 좌표; localization 확정 아님 |
| science/site_identity_audit (form_id, identity_id) | mapping records, measurement_group_ids, taxon | 전체 매핑 후보 유지; mixed/unknown taxon은 카드 지원 보류 |
| quant/comparisons (form_id, contrast_id) | adapter row / source key | 포함/제외 및 모든 기존 비교 값 보존 |
| comparisons U_joint/P_joint/A | ptm_unadjusted_log2fc / protein_log2fc / ptm_protein_adjusted_log2fc | 동일 joint-mask 추정값의 직접 투영. U_all/P_all 대체 금지 |
| comparisons U_all/P_all | U_all/P_all | 별도 원본값; parent 없음으로 joint NA이면 이 값으로 채우지 않음 |
| comparisons reference/target_joint_run_ids 및 runlevel | axis control/treatment_sample_ids + runlevel refs | 실제 injection ID; mask와 observation flag 대조 |
| comparisons included/exclusion_reasons, inference_status, estimator_version | 동일 필드 / 축 missing reason·method | 제외된 finite 값도 raw로 보존하되 카드 입력 보류; p/q/CI 생성 없음 |
| study_design injections → materials | sample_manifest.samples | injection/material/biological unit/pair 분리. 주입 수를 biological n으로 사용하지 않음 |
| comparisons arm, reference, pairing + form_id | consumer_state_id | 서로 다른 reference/form/arm을 같은 소비 상태에서 합치지 않음 |
| comparison time_min/reference_time_min + design conditions | time_minutes / reference_time_minutes / condition | canonical 수치 복사; 원 time 단위·label·ID 동시 보존 |
| localization_by_contrast (form_id, contrast_id) | localization records/IDs/status | contrast별 실제 근거; 없는 probability 생성 없음 |
| user_input_snapshot.original.analysis_context + canonical context/design | study metadata contract + source records/conflicts | 기존 build_study_metadata_contract 재사용; 원문·0·false·누락 보존 |

기존 카드의 identity 계약은 precursor 단위다. charge-collapsed form을 가짜 precursor로
승격하지 않는다. 복수 precursor/혼합종/identity 불충분/제외된 비교는 adapter 전체 표에
남기고 소비자 입력에서 보류 사유를 공개한다. 다중 modification은 하나의 측정 행으로
남는다. 단일 precursor의 다중 site도 독립 site로 분리하지 않는다.

공용 metadata 함수는 worker 모듈에서 ptm_shared로 이동하고 worker에는 호환 import를
유지한다. 두 구현을 복사해 유지하지 않는다. 수치 투영과 입력 상태 생성은 네트워크,
정규화, 재집계, LLM 및 핵심 findings 선정을 호출하지 않는다.
