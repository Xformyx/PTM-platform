# SF03 관측 순서 / prior / 가설 분리

SF02 `300172d` 다음 단계. `observed_order`는 저장 onset bracket만 비교한다. 실제 간격·NA·AUC를 재계산하지 않으며 겹침/동일 bin/좌측 censoring/관측 부족은 unresolved 또는 not_evaluable이다. `trajectory_projection`은 저장 feature의 시간·값·null mask가 적격 곡선과 맞는 경우에만 feature를 연결한다.

`evidence_map`은 bundle_member, candidate_association, method_contribution, same_parent_mathematical_dependence, observed_before, curated_enzyme_substrate_prior를 분리한다. 모든 edge는 source refs와 `causality_status=not_established`를 가진다. 관측 선후 링크는 기존 candidate support 안의 인접한 저장 bracket 탐색용이며 전체 가능한 pair의 통계 검정이 아니다.

`temporal_relation_registry`는 runner-only benchmark 정답 registry이므로 production/LLM 문맥에 가져오지 않았다. `kinase_relation_evidence`의 엄격한 source-versioned identity 보호도 유지했다. symbol-only PPI, motif, orthology는 exact native 방향 관계로 승격하지 않는다. 기존 candidate edge에서 exact native site/source/accession/taxon 근거가 있는 prior만 방향을 표시한다. 관계 source가 없으면 missing_exact_prior이며 관측은 남는다.

같은 accession/taxon의 실제 upstream form이 있으면 저장 bracket과 target bracket을 비교한 consistency를 별도 기록한다. 이것은 측정 form 반응 순서이며 kinase 활성 시작 시간이 아니다. 반대 순서는 inconsistent로 남고 prior 자체를 거짓으로 판정하지 않는다. 후보의 직접 활성화·cascade는 새로 생성하지 않는다.

가설 ledger는 실제 bundle/trajectory/prior/order IDs, 저장된 반대·no-call 진단, phosphatase/위치/turnover·공통 Control·정규화·부모단백질·membership 대안과 필요한 perturbation/direct assay를 제공한다. semantic review는 not_performed다.

검증: 누적 고유 6 tests 통과. 분리/겹침/좌측 censoring/미기록 bracket, prior 없는 경우 방향 edge 부재, exact prior와 반대 관측의 counterevidence 보존을 production 함수로 확인. 실제 저장 관계 검증은 SF06에 구분 기록한다. 새 계산/검색/모델 0회. 단계 SHA는 최종 보고/checkpoint 참조.
