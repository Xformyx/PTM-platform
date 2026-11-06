# Control 비교 방식 확장 — 제공된 감사 원문 보존

사용자가 2026-11-06 개정 2 개발 문서에 제공한 **2절과 3절의 원문**을 아래에 보존한다. 기준은 Xformyx/PTM-platform `42d9a3db8ca92fe1c51a41fb80f7674e7c00d821`이다. 이 파일은 이번 구현에서 원격 감사 전체를 다시 수행했다는 보고가 아니다. 이번 로컬 구현과 검증은 [별도 보고서](CONTROL_COMPARISON_UPGRADE_KO.md)에 기록한다.

## 2. 코드에서 확인한 사항

A. Legacy는 Control의 시간 구분을 잃는다.
- api-server/app/api/orders.py, _build_condition_map(), 약 537행:
  group.lower() == "control"이면 입력 condition에 관계없이 "Control"로 변환한다.
- workers/preprocessing/core/ptm_quantification.py:
  Control 샘플 추출, pivot의 Control 열, Control 대비 PTM/단백질 변화량 및 occupancy 계산이 공통 Control을 전제한다.
  주요 위치: 조건 인식 463–493행, occupancy 786–824행, 비보정 PTM 907–1001행,
  보정 PTM 1054–1172행, 단백질 1210–1249행.
- 따라서 Control 0min, Control 30min, Control 60min을 이 경로에 넘기면 서로 다른 시점의 대조군이 합쳐질 수 있다.
- 단순히 조건 이름에 시간을 붙이는 것만으로 Legacy 지원이 완성되지 않는다.

B. Astra는 별도 분기를 사용한다.
- workers/preprocessing/tasks.py는 활성 primary evidence 경로에서 run_primary_analysis()로 분기한다.
- ptm_shared/enrichment_free_workflow.py는 astra_analysis.v6를 astra_evidence_v6.run()으로 전달한다.
- astra_evidence_v6 → astra_science/generic_workflow.calculate → quantify_contrasts 경로는 canonical study_design을 소비한다.
- 그러므로 Legacy helper의 Control 병합을 발견했다고 현재 Astra 계산도 반드시 그 병합값을 쓴다고 주장하면 안 된다.

C. 다중 reference를 담을 기존 구조는 있다.
- ptm_shared/study_design.py:
  conditions에 role/time/arm_id, contrasts에 target_condition_id/reference_condition_id/pairing이 있다.
  time_value(), same_time()은 단위 변환과 시간 동등성 비교에 재사용할 수 있다.
- 다만 resolve_study_design() 약 313–326행의 자동 연결은 다음 형태다.
  reference = 명시된 reference_condition_id 또는 references가 정확히 1개일 때의 그 reference
- references가 여러 개면 시간 일치 후보를 찾아주는 기능 없이 reference_unresolved가 발생한다.
- 시간 문자열이 없는 Control row를 합치는 legacy_samples() 규칙과, 조건 label 중심 grouping도 점검 대상이다.
  같은 "30min" label을 Control과 Treatment에 모두 사용하면 role conflict가 발생할 수 있다.

D. Astra 입력 화면에는 다중 대조군을 해결할 경로가 부족하다.
- frontend/src/components/CanonicalStudyFields.tsx:
  Astra 생성 화면은 저장 정보 요약으로 개선되어 있다.
  그러나 reference 선택 UI가 !astra 조건 안에 있어 Astra의 원본 정보 편집 모드에서도 그 선택부는 노출되지 않는다.
- 최초 입력의 autoParseColumns()는 condition label과 Control Keyword의 정확 일치를 사용한다.
  "Control 30min" 같은 명칭은 기본 "control"과 일치하지 않으므로 자동 분류만 믿으면 안 된다.
- 해결 방향: Astra 생성 화면에 다시 전체 설계 질문을 추가하는 대신 최초 입력에서 role/time/control 관계를 저장하고 자동으로 소비한다.

E. 핵심 정량 엔진은 재사용 가능하다.
- ptm_shared/contrast_quantification.py:
  ContrastEstimator.indices는 condition_id별 실제 주입을 선택한다.
  condition_values()는 material → biological unit 집계를 수행한다.
  contrast()는 각 contrast의 reference/target을 읽으며, paired일 때 명시된 pair ID를 사용한다.
  quantify_contrasts()는 모든 contrasts를 순회한다.
- U_joint, P_joint, A 및 같은 주입의 joint mask와 A = U_joint - P_joint 관계를 그대로 유지할 수 있다.
- generic_workflow.calculate()는 whole_study 범위에서 normalization을 한 번 수행한 후 contrasts를 계산한다.
  시간별 subset마다 임의 재정규화하는 방식으로 바꾸지 않는다.

F. 시간대별 Control을 한 효과 시계열로 묶는 구조가 없다.
- ptm_shared/astra_temporal.py, integrate_temporal(), 약 93–105행:
  series ID = arm_id + reference_condition_id + pairing
  reference_strategy 문구에 matched_time_controls_remain_separate_series가 명시되어 있다.
- ptm_shared/astra_card_inputs.py 약 171행:
  카드 state도 form_id + arm_id + reference_condition_id + pairing으로 묶인다.
- ptm_shared/astra_figures.py, curve_series():
  같은 reference_condition_id를 곡선 grouping key로 사용한다.
- ptm_shared/astra_reader_temporal.py:
  bindings/series/footprints에서 동일 reference scope를 검증한다.
- ptm_shared/generic_workflow.py, temporal_layers():
  단백질 시간 요약도 protein_group + arm_id + reference_condition_id로 나뉜다.
- 이는 서로 다른 분모를 무분별하게 연결하지 않기 위한 기존 보호이다.
  보호를 지우는 대신 '동일 시간 대조군 대비 효과'라는 명시적인 새 series 정의를 추가해야 한다.

G. adjacent contrast 역시 별도 확장이 필요하다.
- ptm_shared/evidence_temporal.py, adjacent_contrasts():
  각 series의 reference가 하나여야 하며, 정렬한 condition들의 시간이 중복되면 건너뛴다.
- 동일 시간 Control/Treatment 쌍은 같은 시간을 가지므로 현재 경로에서 인접 구간 결과가 나오지 않는다.
- 기존의 T(t2)-T(t1)와 새로 필요한 [T(t2)-C(t2)]-[T(t1)-C(t1)]는 다른 비교다.
  이름만 바꾸거나 두 독립 표의 p값을 빼서 구현하면 안 된다.

H. method_scores 정렬도 다중 Control 기준으로 확장해야 한다.
- ptm_shared/astra_package.py, order_method_scores():
  현재 정렬 key에서 reference_condition_id가 time_min보다 앞선다.
- 공통 Control에서는 숫자 시간 정렬이 되지만 시간마다 reference ID가 바뀌면 전체 효과 시계열의 시간순을 보장하지 않는다.
- audit의 time_order_complete는 시간값의 누락 여부를 나타내며, 새 효과 series 내 단조 시간 순서까지 검증하지 않는다.
- reference ID를 전역 정렬 key에서 무조건 제거하지 말고, 효과 series 안에서 숫자 time_min을 우선하는 공통 ordering을 사용한다.

I. biological p/q와 kinase method p/q는 구분돼 있다.
- contrast_quantification.quantify_contrasts():
  inference_status = descriptive_only_no_biological_test_implemented
  biological_p_value = None, biological_q_value = None
- astra_plan.resolve_plan(): biological_inference = unavailable_method_not_implemented
- astra_evidence_v6.write_artifacts(): independent_biological_pq = not_computed
- astra_card_inputs는 현재 카드 p/q도 None으로 투영한다.
- 따라서 등록 반복이 3개로 표시되는 것과 생물학적 유의성 검정 수행은 별개의 상태다.
- phosx_activity_adapter.py는 method의 null을 관측 site rank permutation으로 기록하고 biological_p_value는 NaN으로 둔다.
  PhosX q를 생물학적 반복 기반 q로 승격하면 안 된다.

J. 통계 코드 자산도 일부 이미 존재한다.
- ptm_shared/sample_manifest.py:
  unit_test_inputs(), compare_sample_units()가 생물학적 단위, paired/Welch eligibility와 기술 반복 집계를 처리한다.
- ptm_shared/science_inference.py:
  unit_intervals()가 동일 재표집을 contrasts 전체에 공유하는 cluster bootstrap CI를 제공한다.
  최소 단위 수, 불명확한 replication, mixed pairing 등에 제한이 있고 기본은 비활성이다.
- 이 자산을 재사용하되 Legacy의 원자료 척도/평균과 Astra의 material-balanced mean-log 추정량이 일치하는지 먼저 확인해야 한다.
  단순히 helper 호출을 붙여 생물학적 통계가 완성됐다고 하면 안 된다.

## 3. 실제 합성 재현 결과

작은 데이터:
- Control 0min, Control 30min, Control 60min, Drug 30min, Drug 60min
- 조건별 3개 독립 생물학적 시료로 명시, 총 15개 주입
- PTM intensity: 각각 10, 20, 40, 40, 80
- parent protein intensity: 모두 2
- 과학 해석용 실제 결과가 아닌 코드 동작 검증용 데이터

결과:
1) 기존 API _build_condition_map:
   세 시간대 Control 9개가 모두 하나의 "Control" label로 변환됐다.
2) canonical resolver 자동 실행:
   5개 conditions와 3개 references는 유지했으나 contrasts는 0개였다.
   reference_unresolved 2건, contrasts_missing 1건.
3) 명시적 시간대별 reference 연결 후 기존 정량:
   Drug 30min vs Control 30min: A ≈ 1, U_joint = 1, P_joint = 0
   Drug 60min vs Control 60min: A = 1, U_joint = 1, P_joint = 0
   각 비교 양쪽 n=3, runlevel 15행 유지.
4) 같은 처리 관측을 시작 시점 Control로 비교:
   A ≈ 2 및 3, 공통 Control 시료 중복 없이 runlevel 9행.
   이 차이는 비교 대상이 달라진 정상적인 효과 차이다.
5) temporal:
   시간대별 Control은 1점짜리 series 2개로 나뉘었다.
   AUC는 둘 다 미산출, adjacent contrast 0행.
   공통 시작 시점 Control은 2점짜리 series 1개였다.
6) 생물학적 p:
   명시적 독립 생물학적 n=3이어도 기존 Astra 정량 p는 전부 미계산이었다.
7) 동일 label 충돌:
   Control/Treatment를 모두 "30min", "60min"로 표시하면 condition_role_conflict가 재현됐다.
8) 시간 정렬:
   별도의 합성 6시점/시간별 Control metadata와 가상 method 행을 기존 order_method_scores()에 전달했다.
   실제 저장 순서: 1 → 30 → 180 → 60 → 5 → 15분.
   audit time_order_complete는 true였다.
   이는 가상 score 행의 정렬만 실행한 것이며 PhosX/kinase 계산은 실행하지 않았다.

probe의 수치 검증은 log2 연산의 부동소수점 오차를 고려해 절대 허용오차 1e-12를 사용했다.
이 결과는 작은 함수 수준 재현이며 실제 주문의 전체 실행 완료를 의미하지 않는다.
