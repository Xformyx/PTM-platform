# W0 — 공통 evidence/record 계약

선언: 2026-09-14. 기준 커밋 `8a778a2` 이후 `ef5b763`에서 시작.
측정 공식·C1 판정 임계가 아니다.

이미 유지하는 항목: 펜스 JSON 복원, 선정 finding 문헌 검색, quote-bound
agreement, kinase 질문 비재작성, TMM vector hash, heatmap 12–16.

이번 묶음이 추가하는 것:

- `evidence_type`은 카드 역할, `record_type`은 수치 검증/렌더 dispatch.
- 기존 U/P/A record를 유지하고 `kinase_trajectory`를 같은 catalog에 넣는다.
- 가짜 PF/`trajectory`로 aggregate를 우회하지 않는다.
- signed 구간 진단은 `additive_observational_evidence`이며 기본 TMM
  점수·NNLS·ranking을 바꾸지 않는다.
- `delta_tolerance` 기본 0. 기존 표시 ±0.15를 재사용하지 않는다.
- 최소 공통 시점/구간 3개는 계산 조건이지 생물학적 충분 기준이 아니다.

P2 표시 연결(2026-09-14 추가 선언): 기존 dual-track·paired fraction·
multiform·Atlas ledger·cluster pair-window 산출을 카드/`record_type`으로만
연결한다. 새 점수·학습·단백질 p/q/CI를 만들지 않는다. 옛 heatmap에도
`trajectory_evidence`를 가산 부착할 수 있으나 weighted sum은 불변이다.
성능 입증과 실주문 과학 수용은 완료 조건이 아니다.
