# AI02 — matched detection quantity와 사용 제한

AI01 `81f89ac` 다음 회차. branch `codex/astra-ai-usability`; 회차 SHA는 최종 commit 표 참조.

## 재현과 변경

실제 `quantify_contrasts`를 합성 C30=2, C60=3, T30=3, T60=5 (log2), parent=0으로 실행했다.
독립 biological unit을 조건별로 명시한 12주입이다. 수정 전 주 matched A는 1/2,
detection eligible_A는 0/0이었다. reference별로 잘린 trajectory의 self-reference 결함이다.

`detection_by_arm`은 matched에 기존 `effect_series.resolve_series`를 재사용한다.
target의 첫 유효 반복 관측(유한 주입 관측 ≥2)을 같은 arm/family/effect series에서 찾는다.
명시적 independent_biological_units + unpaired + 모든 target의 완전한 서로 겹치지 않는 unit
mapping일 때만 기존 `ContrastEstimator.contrast/condition_values`로 처리 arm 변화를 계산한다.
Control-target paired/unknown/mixed 또는 technical-only/미확정 unit 관계는 그 track만 null,
`ambiguous_unit_relationship`, `inference_use_allowed=false`로 남긴다. 종단 pair를 만들지 않는다.
기존 shared-reference 정상 경로는 유지했다. 실제 reference의 검출 수와 주 U/P/A는 변경하지 않는다.

| quantity | 필드/원본 | fixture 결과 |
|---|---|---|
| matched treatment effect T(t)-C(t) | quant/comparisons A, U_joint/P_joint | 1, 2 |
| target arm T(t)-T(first valid) | detection post_reference_U/raw_candidate_A/eligible_A | 0, 2 (지원 관계) |
| matched effect interval change | 기존 temporal effect_interval_contrasts; detection으로 대체 안 함 | 1 |
| 실제 Control 검출 | reference_detected_n / actual reference_condition_id/time | 3 / C30,C60 |

`target_arm_post_reference.v2`를 detection 행에 기록한다. quantity, source log quantity,
joint/own mask, post-reference pairing, canonical series, status/reason 및
`detection_count_unit=finite_injection_observation`를 추가했다.
`baseline_status`는 호환 필드이며 실제 reference 검출 상태이다. time-zero 여부를 뜻하지 않는다.
생물학적 p/q는 계속 미계산이다. 하나의 파생 track 미지원은 주 matched 분석 실패가 아니다.

## cache·소비 경계

기존 quant fingerprint에는 contrast_quantification.py hash가 이미 있었다.
이제 detection이 사용하는 effect_series.py 및 effect scope도 quant 의존성에 포함한다.
reference strategy만 바뀌어도 detection 의미가 달라질 수 있어 새 quant→discovery→temporal lineage가 필요하다.
label/assignment source만 바뀌는 것은 기존 수치 의미를 바꾸지 않는다.
원본 입력/source pin은 재사용하며 native method version은 바꾸지 않았다.
generic_workflow의 detection 설명과 기존 emergent_kinase_evidence의 DETECTION_COLUMNS 전파를 연결했다.
reader-only replay는 저장 detection 표만 읽으며 새 계산으로 바꾸지 않는다.

## 검증

`test_ai_detection.py`, `test_generic_study.py`, `test_control_quantification.py`,
`test_control_effect_series.py`: 최초 **32 passed**, paired 경계 1건 추가 후 AI02 파일 **6 passed**.
중복을 제외한 **33개 고유 테스트** 통과, skip 없음.
결과: `codex-inputs/astra-ai-20261113/AI02.xml`, `AI02_added.xml`.

shared 수치/NA/mask, C03 실제 함수 temporal interval, 지연 검출·parent 결측,
기술주입3/biological unit1, 미선언/unknown/mixed, Control-target pair와 cross-time pair 불일치,
단일 unit count 및 새로운 fingerprint를 확인했다. main A=1/2 및 runlevel=12는 유지됐다.
공통 Control의 기존 회귀 수치와 estimator 버전도 유지했다.
의도 변경은 detection schema/파생 값과 그 소비 설명/cache 의존성이다.
CSV 열이 추가되므로 detection은 byte-identical을 주장하지 않는다.

합성 작은 과학 함수 실행만 사용했다. 실제 저장 표/ZIP/pin/pointer는 쓰지 않았다.
실제 대형 과학 재계산, PhosX, 외부 검색, RAG/LLM 호출은 0회다.
실제 matched 및 운영 환경의 새로운 계산 검증은 미확인이다.
