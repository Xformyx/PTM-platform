# Core A/B 범위 결정 — 표현 학습을 기여 주장 수준으로 확정

작성일: 2026-08-20
계기: "왜 '계약'이라는 용어를 쓰는가. 지금 하고 있는 것은 PTM Vector 개선 방법론 설계 아닌가"
결과: **논문 기여 주장 = 표현 학습 자체. Core A/B는 representation 계약 체계로 편입, kinase 계층은 조건부 확장으로 강등**
반영 위치: `docs/ptm_representation_learning_contract_v1.md` §12
성격: 결정 기록. 계약서에 담기지 않는 추론 경로, 기각한 대안, 판단 근거를 남긴다

---

## 요약

용어 질문에서 출발했으나 실제로는 **범위 문제**였고, 확인 결과 지적이 맞았다. 이미 구현되어 실측까지
끝난 평가 장치가 있는데, Core A/B 트랙이 거의 같은 것을 병렬로 다시 설계하고 있었다.

결정 두 건:

| 항목 | 결정 |
|---|---|
| 기여 주장 수준 | **표현 학습 자체** (mask-aware temporal representation) |
| 문서·어휘 체계 | **representation 계약 기준으로 통합** (L1~L4 / A~E / R0~R4 / 6-gate) |

가장 큰 효과는 **BLOCKER 6건 중 5건이 임계 경로에서 빠진 것**이다. 임계 경로에 blocker가 없는 실행
계획이 생겼다.

---

## 1. 용어 문제 — "계약"은 부정확했다

### 1.1 어디서 온 말인지

두 곳에서 겹쳐 들어왔다.

**프로젝트 기존 관행.** `docs/`에 `temporal_wave_contract_v1.md`,
`ptm_representation_learning_contract_v1.md`, `tmm_multikinase_interpretation_contract_v1.md` 등 11개가 있고,
코드에도 `CONTRACT_VERSION` 상수와 `validate_temporal_wave_contract()` 검증 함수가 있다. 여기서
"contract"는 **출력 스키마와 해석 경계**를 뜻하며, 코드가 실제로 검증하는 대상이므로 소프트웨어
용어로 정확하다.

**검토에 투입된 외부 문서.** Core A/B 검토용으로 올라온 문서들의 제목이 "Frozen Contract 수정 명세",
"Frozen Contract 재검토 V3"였고, 그 표현을 그대로 받아 썼다.

### 1.2 왜 부정확한가

P−2 문서에는 성질이 다른 두 종류가 섞여 있었다.

| 성질 | 해당 항목 | 적절한 명칭 |
|---|---|---|
| 코드가 검증하는 인터페이스 | provenance 필드, `design_column_hash`, `policy_hash`, fail-closed 강제 | **계약** (맞음) |
| 검증 전에 자기 손을 묶는 장치 | `N_floor`, τ_min, 분기 규칙, 철회 목록 | **사전등록 (pre-registration)** |

두 번째가 문서 내용의 대부분이었다. 임상시험·registered report의 개념이고 목적은 사후 편향 차단이다.
상대방이 있는 합의도 아니고 코드가 검증하는 것도 아니다. "계약"이라고 부르면 무언가 합의가 완료됐다는
뉘앙스가 생기는데 실제 기능은 다르다.

### 1.3 그런데 분리는 불필요해졌다

당초 "성질별로 문서를 분리"하기로 했으나, §3의 편입 결정 이후 **분리할 대상이 거의 사라졌다.**

- 사전등록 성격 항목(τ_min, `N_floor`)은 kinase 계층과 함께 지연됨
- 남은 것은 representation 계약이 이미 처리 중이다. `PRIMARY_ARM_PREFERENCE`가 `layers.py`에 코드로
  고정되어 있고 테스트가 강제하며, 왜 데이터로 정하지 않았는지가 §8-ter에 서술되어 있다

**코드가 사전등록을 보관하고 문서가 근거를 설명하는 구조**이므로 이미 분리된 상태다. 별도 문서를
만드는 것보다 gate 임계값이 실제로 코드에 고정되어 있는지 확인하는 것이 실질적이다(§7).

---

## 2. 범위 문제 — 지적이 맞았다

### 2.1 이미 있던 것

`docs/ptm_representation_learning_contract_v1.md`를 재확인한 결과, R0~R1.7이 구현 완료이고 실측 결과까지
나와 있었다.

- L1~L4 명명 체계 (`ptm_shared/representation/layers.py`가 단일 출처, 테스트가 강제)
- A~E ablation arm
- 6개 도입 gate + `production_influence_allowed`
- 누출 없는 held-out 시점 프로브 (순열 귀무분포 + 짝지은 sign-flip 검정)

실측: arm D가 baseline B를 24쌍 **전부**에서 앞섬(ΔR² +0.0271, p = 0.0001). gate 4/6 통과,
`production_influence_allowed = False`.

**이것이 Core A/B에서 만들려던 F00~F11 factorial과 Go/No-Go gate와 같은 종류의 기계다.** 차이는 하나가
이미 돌아갔고 다른 하나는 설계 중이었다는 것뿐이다.

### 2.2 겹침이 거의 정확했다

representation 계약 §11의 남은 과제 3번:

> 프로브 이득이 downstream으로 전달되는지 확인. R² +0.027이 kinase 귀속 정확도로 이어지는지는 별도
> 평가 과제다.

§8-bis 4번에도 같은 유보가 있다. "이 이득이 kinase 귀속 개선으로 이어진다는 증거는 아니다."

**이것이 Core A/B의 `Δ_representation`과 같은 질문이다.** 그리고 전날 발견한 BLOCKER-E는 그 질문에
구조적 상한이 있다는 내용이었다. 즉 representation 작업이 "별도 과제"로 미뤄둔 항목을 Core A/B가 정식
endpoint로 올렸다가, 측정 불가일 수 있음을 발견한 셈이다.

부수 확인: representation 계약 §5의 `profile_representational_dispersion` 필드가 "후보 kinase의 exclusive
substrate embedding 분산 → heterogeneous profile 경고"다. **`MIN_EXCLUSIVE_FOR_PROFILE` 기전을 이미
건드리고 있었다** — BLOCKER-E와 같은 지점이다.

### 2.3 두 문서가 서로 모순이었다

```
# ptm_representation_learning_contract_v1.md §5
PRIMARY_SCORE_INPUTS_LOCKED = (canonical_co_wave_membership,
                               tmm_contribution_coefficients,
                               kinase_ranking)
```

representation 계약은 학습된 표현이 kinase ranking에 영향을 주는 것을 **명시적으로 금지**하고, gate 6개
통과를 조건으로 걸어 두었다. 현재 4/6이므로 문은 닫혀 있다.

반면 Core A/B의 `F10-A4` arm은 A4 표현을 scorer에 먹여 `Δ_representation`을 재는 설계다. **아직 열리지
않은 문이 열린 것을 전제로 설계를 쌓고 있었다.**

### 2.4 명명 체계가 둘로 갈라져 있었다

| | representation 계약 | Core A/B 트랙 |
|---|---|---|
| 표현 층 | L1~L4 | A0~A4 |
| 비교 arm | A~E | F00~F11 |
| 단계 | R0~R4 | P−2 / P−1 / Stage 0·1 |
| 특징 집합 | eligible site/form | U-confirmatory 등 4분할 |

같은 대상에 두 개의 어휘가 붙어 있었고, Core A/B 어휘는 명명의 단일 출처인 `layers.py`에 등록되어 있지
않았다.

---

## 3. 결정과 근거

### 3.1 기여 주장 수준 = 표현 학습 자체

두 후보를 비교했다.

| | 표현 학습 자체 | kinase 귀속 개선 |
|---|---|---|
| 평가 장치 | **이미 구현·실측 완료** (4/6) | 설계 중 |
| 남은 관문 | 2개, 둘 다 계산 가능 | BLOCKER-A/B/E 전부 해제 필요 |
| 원리적 위험 | 없음 | IA-07에서 **측정 불가 판정 가능** |
| 데이터 요구 | 외부 phospho time-course 1건 | KSA library + PXD014525 + 자체 교란 실험 |

표현 학습을 택한 결정적 이유는 **이미 유효한 결과가 있고 남은 병목이 정확히 특정되어 있다**는 점이다.

- `missingness_validity`: arm D의 induced missingness R² 0.462 (상한 0.25), 군집 ARI 0.035 (하한 0.2)
- `generalization`: 외부 데이터셋 미평가

그리고 이 병목 자체가 주장할 만한 발견을 포함한다. handcrafted baseline B의 induced missingness R²가
**0.885**다. **현재 production L1 벡터가 학습 arm보다 coverage와 더 강하게 얽혀 있다**는 뜻이며, 이는
"학습 표현이 handcrafted보다 나쁘다"는 통상적 우려를 반박하는 실측이다.

### 3.2 문서·어휘 = representation 계약 기준으로 통합

Core A/B 어휘를 살리고 두 체계를 병행하는 대안을 기각했다. 이유:

1. `layers.py`가 이미 명명의 단일 출처이고 테스트가 강제한다. 두 번째 어휘를 등록하면 그 강제가 무의미해진다
2. §2.3의 모순(`PRIMARY_SCORE_INPUTS_LOCKED`)이 병행 상태에서는 해소되지 않는다
3. 평가 장치를 두 벌 유지하면 어느 쪽 판정이 우선인지가 매번 쟁점이 된다

---

## 4. Core A 요소 매핑 결과

| Core A 요소 | 처리 | 근거 |
|---|---|---|
| A1 residual (protein 정규화) | **기존 구현에 흡수.** 신규 작업 없음 | `PTM_Relative_Log2FC`가 이미 protein-normalized. headline 주장은 이전 검토에서 철회됨 (MAD 0.06 log2) |
| A2 eligibility weight `e_i` | **기존 정책에 흡수** | `qvalue_policy = quality_weight_and_eligibility_mask_not_feature` |
| A3 `O_ij` comparability mask | **재배치** → `missingness_validity` 후보 기제 | §5 |
| A4 temporal wave prototype `p_iw` | arm D 내부 아키텍처 선택지 | 별도 표현 층으로 두지 않음 |
| feature universe 4분할 | 데이터셋 특성화 자료로 재사용 | 층화 진단 근거 |
| Core B (KSA scorer, 5-gate) | **조건부 확장으로 강등** | `PRIMARY_SCORE_INPUTS_LOCKED` 준수 |

Core B 강등은 새로운 후퇴가 아니다. representation 계약이 이미 그 경계를 정의해 두었고, **기존 lock을
준수하는 쪽으로 정렬한 것**이다.

---

## 5. A3(`O_ij`)의 재배치 — 편입에서 가장 유용했던 발견

Core A/B 트랙에서 `O_ij`는 비중이 낮은 항목이었다. 전역 footprint가 작아서(replicate≥1에서 2.51%,
replicate≥2에서 9.07%) headline novelty에서 correctness guard로 강등된 상태였다.

그런데 실측에서 그 edge가 **소수 저관측 feature에 집중**되어 있었다.

```
비교 불가 degree 와 관측 timepoint 수의 상관: −0.764 (rep≥1) / −0.869 (rep≥2)
상위 1% feature(24개)가 non-comparable edge 종단의 39.5% 차지
상위 5% feature 평균 관측 4.12/6 vs 나머지 5.96/6
```

**이 성질이 `missingness_validity` 병목과 같은 축이다.** §11.1이 지적한 문제는 임베딩이 temporal pattern
대신 coverage를 인코딩한다는 것이고, `O_ij`는 관측량이 부족한 쌍을 비교 대상에서 제외하는 장치다.

따라서 `O_ij`를 독립 알고리즘 기여로 두지 않고 gate 대응 후보 기제로 재배치했다.

```text
기존 §11.1 방향 = 목적함수에 coverage 예측 가능성 penalty
추가 후보       = O_ij 기반 pairwise comparability 제약
                  (공유 관측 timepoint T_min 미달 쌍을 이웃 계산에서 제외)
판정            = 두 기제 각각, 그리고 병용 시 induced missingness R² 와 ARI
제약            = 어느 쪽도 arm 순위를 바꾸는 데 쓰지 않는다.
                  PRIMARY_ARM_PREFERENCE 는 §8-ter 근거로 고정 유지.
A3 평가 층      = pair 수준 false-merge rate, feature-clustered bootstrap,
                  replicate ≥ 2 계층만 (n_eff = 432)
                  replicate ≥ 1 계층은 n_eff = 125 로 검정력 미달 → 사용 금지
```

`n_eff`는 Kish 실효 cluster 수다. 불일치율 10% 검출에 289, 20%에 145가 필요하므로 replicate≥2만 판정에
쓸 수 있다.

---

## 6. blocker 재분류 — 5건이 임계 경로에서 빠졌다

| blocker | 내용 | 상태 |
|---|---|---|
| A | KSA library 부재 | **임계 경로 밖.** kinase 계층 전용 |
| B | PXD014525 접근성 | **임계 경로 밖.** Tier-2 kinase 검증 전용 |
| C | PXD043599 protein 정량 | **유효, 단 축소.** §6.1 |
| D | A4 transmission 측정 불가 | **임계 경로 밖.** 조건부 확장의 전제 |
| E | prior가 NNLS 설계행렬 구성 | **임계 경로 밖.** scorer 전용 |
| F | LLM 예측 kinase 유입 | **임계 경로 밖.** 단 §6.2 |

IA-07(설계행렬 전달성 감사, τ)도 임계 경로에서 빠졌다. τ는 `Δ_representation`이 측정 가능한지 판정하는
장치였고, 그 endpoint를 주장하지 않으므로 지금 필요하지 않다. **조건부 확장 검토 시점의 선행 조건으로
보류**한다.

전날 "IA-07이 P−1과 함께 최우선"이라고 판단했던 것은 kinase 계층을 기여로 주장한다는 전제에서였다.
전제가 바뀌면서 우선순위도 바뀌었다.

### 6.1 BLOCKER-C가 축소된 이유

primary arm이 D(temporal-only)이므로 multi-view branch용 데이터가 필요하지 않다. 다만 **Track 2 자체가
protein-normalized 신호**이므로(§3) matched protein 정량은 여전히 필요하다. 없으면
`UNNORMALIZED_PHOSPHO_ADAPTER_V1`을 적용하고 결론을 방향 일치 수준으로 제한한다. 판정 시점은 데이터
확인 직후로 사전 확정한다.

### 6.2 BLOCKER-F의 잔여 기록

LLM 오염 경로(`LLMKinasePredictor` → `kinase_annotation_node` Source 1 → `candidate_kinases` → NNLS 설계행렬
열)는 kinase 계층에 있으므로 현재 표현 층에 영향이 없다. 다만 두 항목을 남긴다.

- 이 계약 쪽은 §3의 `motif` 처리(기본 off, ablation 전용)와 arm C가 이미 prior dominance를 검증하므로
  추가 조치 불필요
- `workers/common/kinase_weight_manager.py`의 문헌 기반 가중은 **미확인.** kinase 계층 재개 시 선행 실사

---

## 7. 구현 방향

임계 경로에 blocker가 없다.

| 순위 | 작업 | 대응 gate | 선행 조건 |
|---|---|---|---|
| 1 | 목적함수에 coverage 예측 penalty 추가 | `missingness_validity` | 없음 |
| 2 | `O_ij` pairwise comparability 제약 구현·비교 | `missingness_validity` | 없음 |
| 3 | universe 층화 진단 | 원인 규명 | 없음 |
| 4 | 외부 phospho time-course 확보 + inductive 재확인 | `generalization` | 데이터 접근 |
| 5 | 6/6 도달 시 R2 co-wave/TMM provenance 주입 | — | 1~4 완료 |
| — | kinase 계층 조건부 확장 (IA-07 → Core B) | — | 5 완료 + 사용자 승인 |

1~3은 같은 gate를 겨냥하며 상호 배타가 아니다. 각각 그리고 병용해서 측정하고, 어느 조합이
`induced missingness R²`를 상한 이하로 내리면서 ARI를 유지하는지 본다.

**`production_influence_allowed`는 6/6 이전에 열리지 않는다.** 편입으로 변경되지 않는 원칙이다.

### 7.1 착수 전 확인 항목

gate 임계값(`induced missingness R²` 상한 0.25, ARI 하한 0.2, concordance 하한, `time_validity_margin`)이
실제로 코드에 고정되어 있는지 확인이 필요하다. 함수 인자 기본값으로 흩어져 있으면 사후 조정 여지가
남고, §1.2에서 정리한 사전등록 원칙이 형식만 남는다.

---

## 8. 미해결 항목

| 항목 | 상태 |
|---|---|
| gate 임계값의 코드 고정 여부 | **미확인.** §7.1 |
| `kinase_weight_manager` 문헌 가중 | 미확인. kinase 계층 재개 시 |
| 외부 phospho time-course 후보 | PXD043599 외 대안 미조사 |
| `O_ij` 제약과 coverage penalty의 상호작용 | 미측정. 1~2번 작업의 산출물 |

---

## 9. 보존 문서

| 문서 | 역할 |
|---|---|
| `ptm_representation_learning_contract_v1.md` | **상위 계약.** §12가 편입 결과 |
| `core_ab_p2_frozen_contract_v1.md` | kinase 계층 조건부 확장 명세 (지연). 단독 실행 금지 |
| `~/Downloads/Core_A_B_설계행렬_LLM오염_문제진단_20260820.md` | BLOCKER-E/F 진단 기록 |
| `tmm_identifiability_diagnosis.md` | BLOCKER-E의 실측 근거 |
| 이 문서 | 범위 결정의 추론 경로와 기각 근거 |
