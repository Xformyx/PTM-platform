# SF02 kinase별 저장 substrate 근거

SF01 `cbf3f44` 위에 `kinase_projection`을 추가했다. Source registry의 canonical key를 검증한 뒤 edge → contribution / method membership → canonical effect series로 연결한다. 기존 footprint, fixed-common score, gene weight, native score, exclusion/anchor/inference 값을 그대로 보관하고 재합산·새 순위·활성 판정을 만들지 않는다.

새 locator 표: `signal_flow/kinase_substrate_bundles`, `signal_flow/kinase_substrate_membership`. 안정 bundle/member ID는 기존 evidence ID와 별개다. candidate/series/track 또는 method/version/score_name 범위를 유지한다. 동일 intensity/membership을 사용한 native 결과는 독립 검증 횟수로 세지 않는다.

form/site/gene/measurement group count를 분리한다. 원 contribution의 form/edge FK 불일치는 실패시킨다. 동일한 시점별 measurement group/form/site support의 후보 집합은 `identical_saved_support_not_family`로 노출하며 curated family가 없으면 family_label=null이다. 이는 다른 외부 근거로도 영원히 구별 불가능하다는 주장이 아니다.

첫 entered membership는 initialization, 이후는 저장된 turnover다. 빈 fixed common의 NA를 보존하고 source 없음은 unavailable이다. 제외 후 anchor가 없다는 기존 진단과 no-call은 그대로 전달한다. 제외 진단은 독립 검증이 아니다.

검증: SF01–02 고유 4 tests 통과. 2후보/동일1substrate, 실제 footprint 0/1/2, fixed NA, no remaining anchor, edge FK 오류를 합성 저장 표로 확인. 실제 저장 표 대조는 SF06에서 수행한다. 새 과학 계산/검색/모델 호출 0. UI/패키지 연결은 후속 단계다. 단계 SHA는 최종 보고/checkpoint에 기록한다.
