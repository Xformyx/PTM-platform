# Shared-feature allocation correction

## 재현과 수치 변화

합성 K1/K2가 각각 exclusive substrate 3개와 동일 empirical profile을 갖고 shared feature 관측이 `[1,2,1]`인 fixture다. 이전 구현은 kinase마다 자신을 첫 후보로 두고 fit/guard를 다시 실행하여 group_share의 전체 관측이 양쪽에 복제됐다. shared 합계가 `[2,4,2]`가 되었다. 이 값은 생물학적 검증 데이터가 아니다.

`tmm_feature_allocation.v2`는 feature별 전체 candidate set을 deduplicate/정렬하고 같은 profile/config 단계에서 공통 분해/식별성/guard 객체를 사용한다. 구분 불가능한 group contribution은 원장에 `[1,2,1]`로 한 번 기록한다. 개별 kinase ratio는 unresolved이며 해당 shared feature의 individual score 기여를 보류한다. exclusive 기여는 유지한다. conservation 검사에서 unique resolved 몫과 unique group 몫만 합산한다. unsupported fit을 강제로 합 1로 만들지 않는다.

이는 잘못된 점수를 바꾸는 estimator 수정이다. `temporal_mixture_model_full_precursor.v2`, allocation version, 전체 코드 hash가 cache를 무효화한다. 기존 `tmm_feature_allocation.v1`은 명시적 historical 비교용으로 남긴다. 과거 artifact/golden을 덮어쓰지 않으며 해당 shared/group 입력 또는 과거 좁은 후보 모집단을 사용한 주문은 새 revision으로 재계산해야 한다.

FC/q OR 규칙, signed/magnitude 기본, prior/guard threshold, normalization을 이 수정의 성능 개선 명목으로 바꾸지 않는다. NNLS residual은 numerical fit diagnostic이며 생물학적 미귀속 확률이 아니다. direct relation/causal claim과 allocation은 별도다. primary track은 protein-adjusted relative PTM contrast라고 명시하고 occupancy는 별도 track/평가 상태다.

## 결정성과 정확한 최적화

candidate/module/row 순서와 중복 candidate에 불변인 공통 할당을 테스트한다. RNG는 `feature_sha256_seed.v1`을 기록한다. 기존 stochastic 산출물과 byte-identical을 주장하지 않는다. SVD geometry cache는 전체 design bytes/dtype/shape에만 적용하며 profile/mask 변화에서 재사용하지 않는다. allocation/no-call을 캐시된 다른 fit으로 바꾸지 않는다.

trajectory evidence는 score 뒤 독립 stage다. group/interval median 정렬 인덱스로 leave-one/two exclusion을 정확히 계산하고 target detail은 JSONL에 쓴다. mean absolute Pearson coherence는 block sum/count로 계산하며 constant/NaN/zero-profile 규칙과 float64를 유지한다. 계산 불가 coherence를 0.00으로 표시하지 않는다.

wave는 condensed distance + 필요 시 memmap으로 중복 NxN 배열을 제거한다. SciPy average linkage의 quadratic 공간 요구는 남는다. ANN/kNN/community 기반 대체 wave 알고리즘을 동일 estimator라고 도입하지 않았다. 자원 부족은 실패로 기록하며 feature를 임의 삭제하지 않는다. 기존 scientific wave 선택 cap 뒤에도 all_evaluated_waves를 남긴다.

dynamic co-wave pair/LOTO event는 SQLite 임시 spool과 exact intersection/union으로 계산하고 full events를 immutable JSONL로 보존한다. 500개 example은 표시용이다. 기존 결과와 full metrics/event/LOTO 회귀를 비교했으며 permutation default/guard/threshold를 바꾸지 않았다. iteration 순서 기반 새 seed를 주지 않는다.

독립 scientific calibration, 실제 perturbation/holdout 성능, 대규모 TMM peak RSS/처리시간은 미완료다. vector 표시용 100만 행 시험을 TMM 처리 성능이나 생물학적 정확성으로 해석하지 않는다.
