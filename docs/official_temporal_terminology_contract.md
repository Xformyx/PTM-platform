# Official temporal terminology — reader-facing display contract

선언: 2026-09-14. 측정 알고리즘·C1/C2 판정 임계가 아니다.
이 문서는 `f765554`로 git에서 빠진 표시 계약을 복원하고, 선택 상한과
main-figure eligibility를 같은 범위로 맞춘다.

## Reader-facing selected-feature heatmap encoding

- Main heatmap은 가독성 있는 conventional feature card만 올린다.
- 선택 상한과 main 배치 범위는 모두 **12–16** 행이다. 17–20은 이 계약에서
  main이 아니다. 이전 문서의 12–20은 선택 상한 16과 어긋났으므로 폐기한다.
- 부호 패턴 bin은 conventional / protein-adjusted Log2FC `> 0.25` / `< -0.25`.
  활성·직접성·우선순위 임계가 아니다.
- 색 의미는 **protein-adjusted relative PTM log2 contrast** 이다.
  `Red/blue = conventional Log2FC` 문구는 같은 그림에 쓰지 않는다.
- 결측은 0이 아니라 미관측으로 표시한다.

## Structured model JSON

모델이 펜스(````json`)나 한 줄 설명을 붙여도, 첫 `{`부터 마지막 `}`까지
유효한 객체면 본문·문헌 비교 JSON으로 읽는다. 객체를 복원하지 못하면
해당 초안은 거절하고 fallback한다.

## Finding literature

선정된 finding ID는 category가 `candidate_discovery`로 덮여도 검색한다.
`known_agreement` / `disagreement` / `direct_site_evidence` /
`contradictory_evidence`는 `external_finding`이 source quote의 부분
문자열이어야 한다. 배경 관계만 패러프레이즈를 허용한다.

## Research questions

사용자 원문을 다른 질문으로 바꿔 답하지 않는다. kinase/편향 질문을
단백질 보정 질문으로 재작성하지 않는다.

## Release product targets

문헌 20–30편과 섹션 최소 단어는 **제품 목표**이다. 확보된 문헌이 20편
미만이면 20편 미달을 release draft 사유로 쓰지 않는다. 짧은 본문은
품질 기록에 남기되, 빈 섹션·반복·Conclusion 역할 누락만 draft 사유다.

## TMM heatmap cache

캐시 키는 vector TSV 내용 hash와 `precursor_identity` 버전을 포함한다.
전처리만 다시 돌린 TSV는 옛 heatmap을 재사용하지 않는다.
