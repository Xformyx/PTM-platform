# PTM 표현 학습과 귀속 추론의 합성 — 통합 연구 설계 v2

작성일: 2026-08-20
용도: **외부 전문가 리뷰용.** 자립 문서로 작성되었으며 다른 내부 문서 없이 읽을 수 있다
대체 관계: `integrated_research_design_v1.md`(작업 초안), `2026-08-20_core_ab_scope_decision.md`(범위 결정)를 대체한다
리뷰 요청 사항: §12에 명시

---

## 0. 요약

### 0.1 무엇을 제안하는가

질량분석 기반 PTM(번역후수식) 분석 파이프라인에서, **표현 학습과 하류 귀속 추론의 합성(composition)**을
연구 대상으로 삼는다. 논제는 다음이다.

> 다단계 생물학적 측정 파이프라인에서 표현의 품질만으로는 하류 추론의 품질이 결정되지 않는다.
> 표현과 귀속 추론은 함께 설계되어야 한다.

이를 4개 구성요소로 지지하되, **"기여 4건"이 아니라 "구현된 기반 1 + 중심 특성화 1 + 사전등록 확장
2"로 서술한다.** 상태를 뭉치면 과장이 된다.

| | 기여 | 논문에서의 역할 | 현재 증거 |
|---|---|---|---|
| **C0** | 누출 저항 평가 프로토콜 + 표현 학습 기반 | **구현된 방법론 기반** | 공정 프로브, D arm 우세, gate 4/6 — 실측 완료 |
| **C1** | 전달성 분석 (transmissibility, τ) | **중심 기여 (E1–E3 조건부)** | 정식화 + 기전 진단. **τ 미구현** |
| **C2** | Coverage 분리 표현 학습 | 사전등록 확장 | 문제만 실증. **방법 미구현** |
| **C3** | 비교가능성 제약 표현 학습 | 사전등록 확장, 또는 E10에서 C2에 흡수되면 하위 구성요소 | footprint·검정력 측정 완료. **제약 미구현** |

### 0.1.1 실패 시 강등 경로 (논제 척추 보호)

각 구성요소의 실패 조건과 강등 경로를 **앞에서** 노출한다. 어느 하나가 실패해도 논제가 무너지지 않아야
한다는 것이 설계 요건이다.

| | 실패 조건 | 강등 경로 | 논제 영향 |
|---|---|---|---|
| C0 | (해당 없음. 실측 완료) | — | 없음 |
| C1 | held-out E3에서 τ가 하류 변화를 구별 못 함 (§5.6) | 진단 주장 철회, `H` rank 결핍 특성화만 유지 | **치명적.** 중심 기여이므로 논제 재구성 필요 |
| C2 | adversary가 예측력을 보존하며 coverage 누출을 줄이지 못함 (§6.5) | 방법 주장 철회, MNAR 교환의 **불가피성** 증거로 전환 | 제한적. §2.8 교환 결과가 남는다 |
| C3 | E10에서 효과가 C2에 흡수됨 (§7.5) | 독립 기여 → C2 구현 세부로 강등 | 없음. 사전에 허용된 결과 |

C1만이 단일 실패점이다. 그래서 C1 트랙에서는 §5.5.1(held-out 설계)과 §5.5.2(양성 대조)가 τ 측정보다
먼저다(§8.1 4번 → 5번 순서).

### 0.1.2 주장 범위 (claim scope)

**논문 전체의 기준 주장문(canonical claim).** 아래 문장이 §11의 데이터 제약 하에서 방어 가능한 최대
범위이며, 초록·서론·결론에서 이 범위를 넘지 않는다.

> 우리는 representation이 kinase prediction을 개선했다고 주장하지 않는다. 대신 leakage-resistant
> representation quality가 fixed downstream dictionary에 **언제 보이고 언제 소멸하는지**를 측정하며,
> 이 한계를 관찰 가능한 geometry와 data-availability 조건에 연결한다.

제약을 감추는 것보다 이 범위를 전면에 두는 것이 방어력이 강하다. C1 서술의 문장 순서는 다음이다.

> 표현은 공정한 재구성 과제를 개선하면서도 고정 하류 추정기에는 보이지 않을 수 있다.
> 우리는 하류 귀속을 해석하기 **전에** 그 가시성을 정량화한다.

이것은 부정 결과를 실패가 아니라 **해석 관문(interpretation gate)**으로 위치시킨다.

| 대상 | 사용 문구 | **금지 문구** |
|---|---|---|
| C1 | dictionary-conditioned transmissibility diagnostic | kinase attribution accuracy metric |
| 표현 학습 | 누출 저항 프로토콜 하에서 사전 지정된 내부 시간 예측·robustness를 개선 | kinase prediction을 개선 |
| 부정 결과 | 저rank·prior 의존 dictionary geometry가 야기하는 전달 실패 양식을 식별·특성화 | 파이프라인이 실패 |
| 외부 데이터셋 | 선언된 adapter 하의 외부 방향·시간 일관성 평가 | matched protein 정량 없이 효과크기 외부 재현 |
| 향후 실험 | 귀속 정확도와 전달 검증에 **필수** | optional validation |

### 0.2 이 설계에 이르게 된 경위

초기 계획은 표현 학습(C0에 해당)과 별개로 kinase 귀속 알고리즘(내부 명칭 Core A/B)을 개발하고,
"표현 개선 → 귀속 정확도 개선"을 주장하는 것이었다. 그 과정에서 코드 실사로 **하류 귀속 모델이
표현 개선을 원리적으로 전달하지 못할 수 있다**는 것이 확인되었다(§5.3).

당초 이를 장애물로 판단해 귀속 계층을 유예하고 표현 학습만을 기여로 삼으려 했다. 그러나 그 판단은
(a) 표현 학습 단독의 기여 무게가 부족하고(§3.1), (b) **전달 불가라는 발견 자체가 기여**라는 두 가지를
놓친 것이었다. 본 v2는 그 발견을 C1로 승격한다.

### 0.3 리뷰어가 먼저 알아야 할 두 가지

**(1) C0는 이미 존재하며 실측 결과가 있다.** 제안이 아니라 기반이다. 코드·테스트·산출물이 있고
6개 채택 gate 중 4개를 통과한 상태에서 멈춰 있다(§4).

**(2) 신규성에 대한 자기평가를 §9에 명시했다.** C2의 adversarial invariance 자체는 신규가 아니며,
C1의 수학적 내용은 초등적이다. 어디까지가 기여인지 미리 정리했으므로, 그 판단이 타당한지가 리뷰의
핵심 질문이다.

---

## 1. 대상 시스템 배경

### 1.1 데이터와 측정

인슐린 자극 인산화 프로테오믹스 시계열. DIA-NN 산출물(peptide/protein matrix)에서 시작한다.

| 항목 | 값 |
|---|---|
| 주 데이터셋 | rat HIRc-B, 인슐린 자극 |
| 시점 | 6개 (0.5–1–2.5–5–10–15–30–60분 계열의 불규칙 간격) |
| 규모 | 2,744 site/form (ablation), 2,447 site (프로브) |
| 대조 | paired control 존재 (feature별로 replicate 수 상이) |

**결측이 MNAR이며 구조적이다.** 저농도 site가 체계적으로 미검출되므로 결측 패턴 자체가 정보를 담는다.
이것이 §6과 §7 문제의 근원이다.

### 1.2 파이프라인 2단계 구조

```
1단계  측정 → 정량 → 표현
       protein-normalized modified-peptide 신호의 시계열 (Track 2)
       + protein context + occupancy(Track 1, 부분 관측)
       → 표현 z

2단계  표현 → kinase 귀속
       고정 dictionary H (kinase별 시간 프로파일, 열 하나가 kinase 하나)
       비음수 최소자승(NNLS)으로 site별 kinase 기여 계수 추정
```

**C1이 다루는 것은 1단계와 2단계 사이의 전달**이다.

### 1.3 표현 층 명명 (기존 확정)

`ptm_shared/representation/layers.py`가 명명의 단일 출처이며 테스트가 강제한다. 모든 층은
`replaces_lower_layers=False`다 — 상위 층이 하위 층을 대체하지 않는다.

| 층 | 명칭 | 해석 가능성 |
|---|---|---|
| L1 | Quantitative PTM Feature Vector (현 production, 보존) | 높음 |
| L2 | Temporal PTM Trajectory Vector | 높음 |
| L3 | Multi-view Temporal PTM Input (encoder 입력) | 중간 |
| L4 | Learned Temporal PTM Embedding | 낮음 (raw 증거 역추적 필수) |

### 1.4 입력 정책 (기존 확정, 이유 포함)

리뷰 시 이 정책들이 타당한지 확인이 필요하다.

| 입력 | 처리 | 이유 |
|---|---|---|
| `PTM_Relative_Log2FC` | primary target 및 시간 입력 | protein-normalized 관측 궤적 |
| `Protein_Log2FC` | context branch. PTM target 대체 금지 | modification 신호와 혼동 방지 |
| `Occupancy_Logit_Delta` | 특정 품질 tier에서만 관측. **부재는 mask, 0 채움 금지** | paired subset coverage bias 차단 |
| `q_value` | loss weight + eligibility mask. **feature 아님** | 통계 신뢰도를 latent biology 축으로 오인 방지 |
| 시간 | 분 단위 5차원 encoding (log/linear/gap/sin/cos) | 불규칙 간격 보존 |
| motif | optional, 기본 off, ablation 전용 | prior가 latent geometry를 지배하는지 검증 |
| raw sequence / PLM | 현 단계 제외 | 검증 이후 optional |
| site 집계 coverage 스칼라 | **입력 금지** | 넣으면 임베딩이 coverage를 인코딩하게 되어 §6이 잡아야 할 문제를 스스로 만든다 |

---

## 2. C0 — 기존 구현과 실측 결과

제안이 아니라 이미 존재하는 기반이다. 리뷰어가 신규 기여로 오해하지 않도록 먼저 제시한다.

### 2.1 구현 실물

```
ptm_shared/representation/
  layers.py           명명 단일 출처, PRIMARY_SCORE_INPUTS_LOCKED, PRIMARY_ARM_PREFERENCE
  feature_contract.py L3 입력 계약, validate_multiview_input()
  baselines.py        mask_aware_pca / mask_aware_nmf / fpca_lite / handcrafted
  encoder.py          결정적 mask-aware self-supervised autoencoder
  benchmark.py        A~E ablation, 6-gate 판정
  fair_probe.py       누출 저항 held-out 시점 프로브
  metrics.py          additive 필드

workers/tests/test_ptm_representation_learning.py
workers/tests/test_representation_fair_probe.py   (13개)
```

preprocessing 파이프라인에 Step 1c로 통합(실패 시 non-fatal). 산출물이 실제 생성됨:
`ptm_representation_embeddings_phospho.tsv`, `ptm_representation_benchmark_phospho.json`.

### 2.2 인코더 구성

```
목적함수 = quality-weighted masked MSE (Track 2 primary)
         + auxiliary (protein, Track 1)            weight 0.30
         + gap-aware temporal smoothness           weight 0.05
         + L2
self-supervision = 매 epoch 관측 entry 일부를 입력에서 숨기고 loss 에는 유지
held-out         = 학습에 전혀 쓰이지 않는 별도 entry 집합
구현 제약        = NumPy 전용, seed 고정 결정적. PyTorch/CUDA 를 worker 의존성에 추가하지 않음
```

### 2.3 비교 arm

| arm | 내용 | 차원 |
|---|---|---:|
| A | Track 2 시계열만 | 12 |
| B | 현 production handcrafted L1 (protein context + quality feature) | 30 |
| C | B + motif static descriptor | — |
| D | 학습된 temporal 표현 (Track 2만) | 16 |
| E | 학습된 multi-view 표현 (Track 2 + protein + Track 1 gated) | 16 |

### 2.4 C0의 기여 내용 — 평가 프로토콜

**인코더 아키텍처는 신규성이 없다**(§9.4). C0의 기여는 평가 프로토콜이다.

핵심은 프로브 개발 중 발견된 누출이다. 한 timepoint를 Track 2에서만 가리면, 같은 timepoint의 protein
context와 Track 1 occupancy가 **동일 measurement pair에서 계산되므로** 다른 view를 가진 arm이 가려진
값을 대수적으로 복원한다. 잡음 데이터 대조에서 드러났다 — 전체 view를 가리기 전에는 **순수 잡음에서
R² = 1.0**이 나왔다.

```
프로토콜
  전체 view 마스킹      = 같은 timepoint 를 모든 view 에서 제거
  순열 귀무분포          = 프로브 target 을 섞어 no-skill 기준 확립
  짝지은 sign-flip 검정  = 동일 (가린 시점, 분할) 짝에서 baseline 과 비교
  ridge penalty 내부 CV  = 고차원 arm 이 자동으로 유리해지지 않게
  사전등록              = primary arm 순서를 코드에 고정, 테스트가 강제
```

### 2.5 arm 비교에 쓸 수 없는 지표 (보존해야 할 발견)

초기 판정은 편향된 지표를 썼고 결론이 뒤집혔다. 이 사례 자체가 보고 대상이다.

**`raw_evidence_concordance`는 arm 순위에 사용 불가.** 이 지표는 "임베딩 최근접 이웃이 원본 궤적의
peak 시점(±1)과 부호를 공유하는가"를 재는데, arm B의 임베딩은 학습된 표현이 아니라 **원본 궤적 값 그
자체**(30차원)다. 원본 궤적 공간에서 이웃을 찾으면 peak와 부호가 같은 것이 거의 항등식이다. 하한
점검이며 경쟁 벤치마크가 아니다.

**`missingness_r2`도 arm 간 비교 불가.** 예측변수 개수를 보정하지 않은 R²이므로 30차원 arm과 16차원
arm을 나란히 놓을 수 없다.

공정한 대조는 (a) 같은 arm 내 시간 순열, (b) 같은 차원·같은 계열인 D 대 E, (c) 같은 성분 수인 baseline
내부뿐이다.

### 2.6 실측 결과 1 — 공정 프로브

한 timepoint를 모든 view에서 가리고, 각 arm이 남은 데이터로 표현을 만들고, ridge 프로브가 학습에 쓰이지
않은 site에서 가려진 Track 2 값을 예측한다.

| arm | 차원 | 평균 R² | 귀무 R² | B 대비 ΔR² | 우세 fold | p | 판정 |
|---|---:|---:|---:|---:|---:|---:|---|
| A | 12 | 0.9236 | −0.004 | −0.0008 | 50.0% | 0.776 | 차이 없음 |
| B | 30 | 0.9243 | −0.010 | (기준) | — | — | — |
| **D** | 16 | **0.9514** | −0.008 | **+0.0271** | **100.0%** | **0.0001** | **baseline 초과** |
| E | 16 | 0.9183 | −0.010 | −0.0060 | 37.5% | 0.057 | 차이 없음 |

학습 arm 120 fold, 비학습 arm 24 fold, 짝지은 비교 24쌍. 모든 arm이 순열 귀무분포를 넘었다.

**읽는 법:** 공정한 과제에서는 학습이 이기지만 **temporal-only arm D만** 그렇고 24쌍 전부에서 앞선다.
다만 baseline이 이미 R² 0.924인 과제에서 +0.027이다. 부드러운 궤적의 한 시점을 이웃 시점에서 맞히는
것은 쉬운 과제이며, **이 이득이 kinase 귀속 개선으로 이어진다는 증거가 아니다.** 그 질문이 C1이다.

### 2.7 실측 결과 2 — 6개 채택 gate

primary arm을 데이터로 고르지 않기 위해 순서를 코드에 사전 등록했다(D 우선, 그다음 E). 근거는 §2.6의
누출 없는 프로브 결과이며, gate를 평가하는 데이터로 gate의 피험자를 고르는 것을 막는다.

| gate | primary = E | primary = D (현재) |
|---|---|---|
| `time_validity` | 실패 (margin −0.0016) | **통과 (+0.0533)** |
| `missingness_validity` | 실패 (induced R² 0.273 > 0.25) | 실패 (ARI 0.035 < 0.2, induced R² 0.462) |
| `raw_evidence_concordance` | 통과 (0.520) | 통과 (0.564) |
| `generalization` | 미평가 (단일 cohort) | 미평가 |
| `no_prior_leakage` | 통과 | 통과 |
| `interpretability` | 통과 | 통과 |
| 합계 | 3 / 6 | **4 / 6** |
| `production_influence_allowed` | False | **False** |

**두 gate가 남았고 그것이 C2(missingness)와 §11(generalization)의 대상이다.**

`production_influence_allowed = False`는 학습 표현이 kinase ranking·co-wave·TMM 계수에 영향을 주지
못하도록 잠근 것이다(`PRIMARY_SCORE_INPUTS_LOCKED`). 6/6 이전에 열리지 않는다.

### 2.8 D와 E는 상반된 실패를 한다

| | 예측력 (프로브 ΔR²) | 마스킹 후 군집 ARI | induced missingness R² |
|---|---:|---:|---:|
| B (production) | 기준 | 0.234 | **0.885** |
| D | **+0.0271** | 0.035 | 0.462 |
| E | −0.0060 | **0.974** | 0.273 |

E의 안정성은 protein context와 Track 1이라는 **비시간적 부수 정보**에서 왔고, 그래서 예측력이 없다.
즉 multi-view branch는 robustness를 사고 예측력을 팔았다. **"E로 되돌린다"는 해법이 아니다.**

그리고 **production handcrafted B의 induced missingness R²가 0.885로 가장 나쁘다.** mask indicator를
feature로 직접 포함하기 때문이다. 이는 "학습 표현이 handcrafted보다 신뢰할 수 없다"는 통상적 우려를
반박하는 실측이다.

---

## 3. 문제 진술 — 표현 학습만으로는 부족하다

### 3.1 C0 단독의 기여 무게

C0만으로 학위논문을 구성했을 때 예상되는 심사 지적을 정리한다.

| 항목 | 실상 | 지적 |
|---|---|---|
| 아키텍처 | masked AE + auxiliary + smoothness | masked autoencoder, FPCA, mask-aware NMF는 모두 기존 방법 |
| 성능 이득 | ΔR² +0.0271 | baseline이 이미 0.924인 쉬운 보간 과제 |
| 일반화 | 단일 cohort | `generalization` gate 미평가 |
| 하류 유용성 | 미증명 | §5가 원리적으로 불가능할 수 있다고 지적 |

결론: **도메인 응용이며 CS 방법론 기여가 아니다.**

### 3.2 그런데 하류 전달 실패는 기여다

코드 실사 결과, 하류 귀속 모델의 dictionary `H`는 표현 개선을 전달하지 못할 구조를 갖고 있었다(§5).
이를 장애물로 볼 것인지 결과로 볼 것인지가 갈림길이다.

표현 학습 문헌은 **"더 좋은 표현 → 더 좋은 하류 성능"을 대체로 암묵적으로 가정한다.** 그 가정이 언제
깨지는지를 정량화하고, 실제 파이프라인에서 깨지는 사례를 제시하는 것은 재사용 가능한 기여다.

### 3.3 논제

> 다단계 생물학적 측정 파이프라인에서 표현의 품질만으로는 하류 추론의 품질이 결정되지 않는다.
> 표현과 귀속 추론은 함께 설계되어야 한다.

C0(기반) + C1(전달성) + C2(coverage 분리) + C3(비교가능성)이 이 논제로 묶인다.

---

## 4. 기여별 일반성 주장

CS 기여로 성립하려면 도메인을 넘는 적용 범위가 있어야 한다.

| 기여 | 일반 문제 형태 | 적용 도메인 |
|---|---|---|
| C1 | 고정된 제약 하류 추정기에 대해 상류 표현 변화의 관측 가능 비율 | deconvolution, unmixing, topic attribution, cell-type deconvolution, source separation — 2단계 파이프라인에서 2단계가 고정 dictionary를 갖는 경우 일반 |
| C2 | MNAR 구조적 결측에서 결측 패턴을 인코딩하지 않는 표현 학습 | single-cell, EHR, 센서 네트워크, 패널 조사 |
| C3 | 부분 비교가능성 관계 위에서의 표현 학습 | 희소 관측 패널 일반 |
| C0 | 다시점 시계열 표현의 누출 저항 평가 | 다시점 자기지도 학습 평가 일반 |

---

## 5. C1 — 전달성 분석

### 5.1 문제

1단계가 표현을 개선했을 때, 고정 dictionary `H`로 계수를 추정하는 2단계의 출력이 바뀌는가?

```
관측: NNLS 의 KKT 조건은 응답 y 에 대해 H'y 를 통해서만 의존한다.
      ⇒ col(H) 에 직교하는 응답 섭동은 계수를 전혀 바꾸지 못한다.
      ⇒ rank(H) 가 작으면 표현 개선의 대부분이 소멸한다.
```

### 5.2 지표

```
τ  =  aggregate_i ( ‖P_H d_i‖² / ‖d_i‖² )
        d_i = (개선된 표현의 응답벡터) − (기준 표현의 응답벡터)
        P_H = col(H) 정사영 연산자

해석 = 현재 하류 estimator geometry 에서 보존되는 섭동 energy fraction
보장 = 필요조건만.  τ→0 ⇒ 효과 없음.  τ 높음 ⇒ 효과 보장 안 됨
금지 = τ 를 효과 크기의 정량적 상한으로 기술하는 것
       (NNLS 는 원뿔 투영이며 이후 feature weight·후보 부분집합·정규화가 개입)
성격 = development decision threshold. statistical significance threshold 아님
```

필수 명세 (누락 시 결과 무효):

| 항목 | 규칙 |
|---|---|
| zero denominator | `‖d_i‖²` 하한 미달 feature 제외 또는 epsilon 규칙 사전 고정 |
| weighting | projector와 norm에 적용할 고정 feature weight |
| rank tolerance | SVD tolerance 및 condition-number 임계 사전 고정. **tolerance 없이 numerical rank는 정의되지 않는다** |
| aggregation | median 단독 금지. IQR·weighted mean·저관측 층 병기 |
| uncertainty | feature-clustered bootstrap, seed 동결 |
| H identity | candidate universe·dictionary hash·profile rule·column hash로 실제 scoring `H`와 동일함을 증명 |

### 5.3 실증 근거 — `H`가 왜 rank 결핍인가

`H`의 열은 두 경로로만 생성된다.

```
MIN_EXCLUSIVE_FOR_PROFILE = 3      # 이 값 이상의 exclusive substrate → data-driven 프로파일
_GAUSSIAN_SIGMA_LOG = 0.6          # 아니면 문헌 typical_peak_min 중심 Gaussian
generic default peak = 30.0 min    # 문헌 값도 없으면
```

- `data_driven`: exclusive substrate(정확히 한 kinase에만 배정된 site) 3개 이상일 때 그 |시계열|의 median
- `gaussian_fallback`: 문헌 시간창 중앙값에 중심을 둔 Gaussian

**fallback 열은 `peak_min` 스칼라 하나의 결정적 함수다.** 그 값이 취하는 distinct 수는 문헌 표의 소수
midpoint와 30.0뿐이다. 따라서 같은 `peak_min`을 공유하는 kinase는 **수치적으로 동일한 열**을 받는다.

6개 오더, 1,310 shared site 진단 결과:

| 항목 | 값 |
|---|---:|
| duplicate column 비율 | 61.5 ~ 100% |
| 한 오더: kinase 수 → distinct 열 수 | 111 → **9** |
| rank-one design | 54.4% |
| non-identifiable | 51.2% |
| `relative_residual ≥ 0.999` | 54.5% |
| top-1이 자기 ambiguity set 내부 | 89.0% |
| top-1이 prior 유래 열 | 92.5% |
| data-driven 프로파일 확보 (해당 오더) | 4 / 111 |

코드 자신도 fallback을 데이터 증거로 취급하지 않는다고 명시한다(`tier = "tmm_prior_assisted"`,
`"...prior-assisted fallback, not direct data evidence"`). **그러나 등급 라벨링만 하고 dictionary 구성은
막지 않았다.**

### 5.4 C1이 답하는 질문

C1은 하류 귀속을 **성공시키는** 기여가 아니다. **언제 성공할 수 있고 언제 원리적으로 불가능한지를
특성화하는** 기여다. 이 전환으로 기존 장애물이 연구 재료가 된다.

특히 "표현 개선이 귀속 정확도로 전달되는지 측정 불가"라는 결론은 유감스러운 한계가 아니라 **C1이
설명하고 예측하는 현상**이 된다.

### 5.5 실험

```
E1  τ 기본 측정
    대상: HIRc-B, 확증 universe
    비교: arm D 표현 vs baseline L1 표현이 만든 응답 섭동
    출력: τ, τ_dd(data-driven 부분행렬), rank, condition number, duplicate group
    구현: `ptm_shared/tmm_identifiability.py` 확장 (신규 모듈 아님, 아래 §5.5.0)

E1b τ 의 판별력 (discriminance) — C1 신규성의 최소 조건
    같은 site 집합에서 τ 와 **방향 무관** 지표(condition number, active_sigma_min,
    max_column_coherence, n_redundant)의 관계를 측정
    → τ 가 이들의 단조 함수로 설명되면 C1 은 기존 진단의 재포장

E2  H 조작에 대한 τ 반응
    dictionary 변경(prior 열 제거, KSA manifest 교체, MIN_EXCLUSIVE 변화) 시
    exclusive-substrate yield / fallback fraction / rank(H) / duplicate rate / τ 를 pre-post 측정
    → τ 가 dictionary 성질의 함수로 예측 가능한가 (C1 의 핵심 주장)

E3  τ 의 예측력 검증 — held-out 설계 (아래 §5.5.1)
E3b 기전 양성 대조 (positive control, 아래 §5.5.2)
```

**E3이 결정적이다.** τ를 정의만 하고 예측력을 보이지 않으면 관찰에 그치고 도구가 되지 못한다.

### 5.5.0 E1은 신규 구현이 아니다

`ptm_shared/tmm_identifiability.py`에 이미 다음이 구현·테스트되어 있다(`workers/tests/test_tmm_identifiability.py`).

```text
solve_nnls                 NNLS 해
_numerical_rank            rank(H)
_condition_number          condition number
_singular_values           특이값
max_column_coherence       duplicate 열 탐지
group_parallel_columns     평행 열 군집
equal_weight_fallback      prior fallback 판정
zero_imputation_bias       영값 대치 편향
summarize_diagnostics      duplicate_columns / equal_weight_fallback 비율 요약
```

E1이 추가로 필요한 것은 **τ 하나**다 — 상류 섭동 방향 `d`를 `H`의 활성 열공간에 정사영하고 보존 에너지
비율을 계산하는 것. 나머지 provenance(rank, duplicate, fallback)는 이미 나온다.

**결과: E1은 주 단위 작업이며, C1의 생존 여부를 가장 싸게 검정한다.**

### 5.5.0.1 그런데 같은 사실이 C1의 신규성 위험을 키운다

condition number와 coherence 진단이 **이 코드베이스에 이미 있다.** 따라서 "τ는 condition number와
다르다"(§9.1)는 논변은 주장으로 남겨둘 수 없고 **측정해야 한다.** E1b가 그 검정이다.

```text
τ 는 방향 의존   — 특정 섭동 d 가 관측되는지
cond(H) 는 방향 무관 — 모든 방향에 대한 최악의 경우

∴ 두 지표가 site 간에 사실상 같은 순서를 준다면
  τ 는 기존 진단의 재포장이고 C1 의 독립 기여는 성립하지 않는다
```

이것은 외부 데이터·리뷰 없이 지금 검정 가능하며, **C1 신규성 논쟁을 논변에서 실측으로 옮긴다.**

### 5.5.1 E3의 held-out 설계 — 기계적 상관 회피

초판의 E3("τ 상위/하위 부분집합에서 하류 변화량 비교")은 **불충분하다.** τ와 하류 변화량 `Δẑ`가 모두
같은 `H`와 같은 `d`에서 계산되므로 둘은 기계적으로 연관될 수 있다. 그 상관을 제시하는 것은 NNLS
projection 성질의 재진술에 그친다.

```text
E3 설계 (수정)
  분할 단위 = dictionary intervention 또는 site block
              (feature 단위가 아니라 블록 단위로 분할해 의존성 누출 차단)
  calibration set = τ 계산 규칙·임계·aggregation·출력 통계량을 확정하는 데만 사용
  held-out set    = 확정된 규칙으로 τ 를 계산하고 Δẑ 예측을 검정
  사전 확정 항목  = low/high τ 임계, aggregation 규칙, 출력 통계량,
                    검정 방법, seed  ← held-out 결과 열람 전에 동결
  판정            = held-out 에서 high-τ 블록과 low-τ 블록의 Δẑ 분포가 구별되는가
  금지            = 동일 (H, d) 쌍에서 계산한 τ 와 Δẑ 의 상관만 제시하는 것
```

이 보완이 없으면 C1은 "NNLS 투영의 재진술"이라는 리뷰를 피할 수 없다.

### 5.5.2 E3b — 기전 양성 대조

부정 결과만 제시하면 "파이프라인이 작동하지 않았다"로 읽힐 위험이 있다. **생물학적 truth 없이도
진단의 민감도를 증명하는 양성 대조가 가능하다.**

```text
E3b  dictionary intervention 에서 τ 가 오르고 Δẑ 가 예측대로 반응하는 사례
     조작: prior 열 제거(prior-free dictionary), 합성 dictionary rank 조작,
           duplicate 열 병합
     기대: rank 증가 → τ 증가 → Δẑ 반응 증가
     허용 주장: diagnostic sensitivity proof
     금지 주장: individual kinase accuracy proof
```

**이것은 진단이 민감하다는 증명이며 귀속 정확도 증명이 아니다.** 그 구분을 결과 서술에서 유지한다.
양성 대조가 하나라도 있으면 C1의 방어력이 크게 올라간다.

### 5.6 반증 조건

- **E1b에서 τ가 방향 무관 지표(condition number 등)의 단조 함수로 설명되면 → C1은 기존 식별가능성
  진단의 재포장이며 독립 기여로 성립하지 않는다** (§5.5.0.1. 사전 확정 판정 기준 필요)
- E2에서 τ가 dictionary 성질과 무관하게 움직이면 → C1의 예측 주장 기각
- E3의 **held-out** 블록에서 high-τ / low-τ의 하류 변화량이 구별되지 않으면 → τ는 서술 통계에 그치며
  진단 도구로 무효 (동일 `(H, d)` 내 상관은 근거로 인정하지 않는다. §5.5.1)
- E3b 양성 대조에서 dictionary rank를 올려도 τ가 반응하지 않으면 → 진단 구현 자체가 불완전
- τ가 모든 조건에서 높게 나오면 → 전달 실패가 실재하지 않으며 C1의 동기 소멸 (§5.3과 모순되므로 가능성 낮으나 검증 대상)

---

## 6. C2 — Coverage 분리 표현 학습

### 6.1 문제

MNAR 구조적 결측 하에서 표현이 시간 패턴 대신 **coverage를 인코딩**한다. §2.7의 `missingness_validity`
실패가 이것이며, §2.8이 그 구조를 보여준다.

핵심은 단순 실패가 아니라 **교환**이다. D는 예측력이 최고이나 coverage 누출이 최악이고, E는 마스킹
robustness가 유일하게 살아있으나 예측 이득이 없다. 이 교환을 푸는 것이 C2의 과제다.

### 6.2 방법

```
현행 목적함수에 추가
  coverage adversary = 보조 예측기가 임베딩 z 로부터 관측 마스크 m 을 맞히려 하고,
                       인코더는 실패시키도록 학습 (gradient reversal 또는 min-max)
대안                 = mutual information 상한 penalty
제약                 = 현 구현의 결정성(seed 고정, NumPy 전용) 유지
```

### 6.3 기여 성립 조건 — 인증서

"penalty를 넣었더니 지표가 내려갔다"는 방법 기여가 아니다.

```
(a) induced missingness R² ≤ 0.25 달성                 # gate 통과
(b) 동시에 프로브 ΔR² 이득 유지                          # 예측력을 팔지 않았음
(c) 잔여 mask 예측 가능성이 예측기族에 대해 낮음을 제시
    → adversary 하나를 이긴 것은 그 adversary 가 약했다는 증거일 수도 있다
(d) §6.1 의 교환을 실제로 풀었다는 증거
    = D 의 예측력 + E 의 robustness 를 동시에 갖는 arm
```

**(c)가 방법 기여의 핵심이다.** 예측기族 범위를 사전 확정해야 한다.

### 6.4 실험

```
E4  adversary 도입 후 gate 재판정 (induced R², ARI, 프로브 ΔR² 동시)
E5  adversary 강도 sweep → 예측력–독립성 frontier 곡선
    → 교환의 형태를 정량화. frontier 자체가 결과다
E6  예측기族 검증: ridge / kNN / gradient boosting 으로 잔여 mask 예측 가능성 측정
E7  층화 진단: universe 별·저관측 층별 실패 집중 여부
    aggregation = median 단독 금지, 층별 병기
```

### 6.5 반증 조건

- E5의 frontier가 (a)와 (b)를 동시에 만족하는 점을 갖지 않으면 → 교환이 근본적이며 C2는 실패
- E6에서 다른 예측기族이 mask를 여전히 맞히면 → adversary가 특정 예측기만 속인 것이며 (c) 미충족
- adversary 없이도 하이퍼파라미터 조정만으로 (a)+(b)가 달성되면 → C2의 방법 기여 소멸

### 6.6 알려진 위험

현 구현이 NumPy 전용 결정적 학습이다. min-max 구조가 이 환경에서 안정적으로 수렴할지 미검증이다.
막히면 MI 상한 penalty로 우회해야 하나, 그쪽은 결정성 유지가 더 어렵다. **PyTorch 도입은 worker 의존성
정책 변경을 요구하므로 별도 판단 사항이다.**

---

## 7. C3 — 비교가능성 제약 표현 학습

### 7.1 정식화

표현 학습은 통상 **완전 비교가능성**을 가정한다. 임의 두 점 사이 거리가 의미를 갖는다는 가정이다.
희소 관측 패널에서는 성립하지 않는다.

```
부분 비교가능성 관계 O ⊆ V × V 위에서의 표현 학습
  O_ij = 1  ⟺  feature i, j 가 공유 관측 timepoint T_min 이상
  이웃 계산·군집·거리 기반 손실이 O 를 존중해야 한다
```

### 7.2 실측 근거

| 기준 (확증 universe) | 비교 불가 pair 비율 | affected pair |
|---|---:|---:|
| replicate ≥ 1, T_min = 4 | 2.51% | 73,537 |
| replicate ≥ 2, T_min = 4 | 9.07% | 265,500 |

전역 비율은 작으나 **소수 저관측 feature에 집중**되어 있다.

```
비교 불가 degree 와 관측 timepoint 수의 상관: −0.764 (rep≥1) / −0.869 (rep≥2)
상위 1% feature(24개)가 비교 불가 edge 종단의 39.5%
상위 5% feature 평균 관측 4.12/6 vs 나머지 5.96/6
```

이 집중 구조가 §6의 coverage 얽힘과 **같은 축**이다. C2와 C3은 독립 기여이나 같은 병목을 겨냥한다.

### 7.3 guard에서 제약으로

```
현재  = 결과 해석 시 비교 불가 쌍을 배제 (사후 correctness guard)
C3    = 이웃 계산·대조 손실·군집이 O 를 존중하도록 학습 (사전 제약)
평가  = pair 수준 false-merge rate
        불확실성: feature-clustered bootstrap
        계층: replicate ≥ 2 만 사용 (Kish 실효 cluster 수 n_eff = 432)
        금지: replicate ≥ 1 계층 (n_eff = 125, 검정력 미달)
```

필요 표본(α=.05, power=.80, ψ=0.75): 불일치율 5%→578, 10%→289, 20%→145. **따라서 replicate≥2만
판정 가능하다.** 이 제약은 사전 확정이며 결과를 본 뒤 완화하지 않는다.

### 7.4 실험

```
E8   O 제약 적용 전후 false-merge rate (pair 수준, clustered bootstrap)
E9   O 제약이 induced missingness R² 와 ARI 에 미치는 영향
E10  C2 × C3 병용: 4조합(무제약 / C2 / C3 / C2+C3)에서 gate 3지표 동시 측정
E11  T_min 민감도: T_min ∈ {3,4,5}. primary = 4, 나머지는 sensitivity (사전 확정)
```

**E10이 중요하다.** 두 기여가 같은 병목을 겨냥하므로 상호 대체적인지 상보적인지 보여야 한다.

### 7.5 반증 조건

- E8에서 false-merge rate가 유의하게 개선되지 않으면 → 제약이 실질 효과 없음
- E10에서 C3의 효과가 C2에 완전히 흡수되면 → 독립 기여로 성립하지 않고 C2의 구현 세부로 격하
- E11에서 결론이 `T_min`에 민감하면 → 정식화가 임계값 의존적이며 일반성 주장 약화

---

## 8. 실행 계획

### 8.1 즉시 착수 (blocker 무관, 기존 코드 수정)

**순서 원칙: 단일 실패점을 가장 먼저, 가장 싸게 검정한다.** C1이 유일한 단일 실패점이고(§0.1.1),
E1은 기존 모듈 확장이라 저렴하다(§5.5.0). 따라서 C1 생존 검정이 C2/C3 구현보다 앞에 온다. 순서를
반대로 하면 C1이 죽었을 때 C2/C3 작업이 없어진 척추를 향하게 된다.

**Phase 1 — C1 생존 검정 (선행)**

| 순위 | 작업 | 기여 | 대상 |
|---|---|---|---|
| 0 | gate 임계값 사전등록 강화 (§8.2) | C0 | `layers.py`, `benchmark.py` |
| 1 | **판정 규칙 동결** — E1b 판별력 기준, E3 블록 분할, τ 임계, aggregation, 출력 통계량 (§5.5.0.1, §5.5.1) | C1 | 신규 사전등록 문서 |
| 2 | τ 측정 (E1) | C1 | `tmm_identifiability.py` 확장 |
| 3 | **E1b 판별력 검정** — τ vs condition number / coherence | C1 | 동일 모듈 |
| 4 | E3b 기전 양성 대조 (합성 dictionary rank 조작) | C1 | 동일 모듈 |

1번이 2번보다 앞이다. **τ를 계산한 뒤에 판정 규칙을 정하면 C1은 방어할 수 없다.**

**Phase 2 — 표현 학습 방법 (Phase 1 결과 확인 후)**

| 순위 | 작업 | 기여 | 대상 |
|---|---|---|---|
| 5 | coverage adversary 목적함수 | C2 | `encoder.py` |
| 6 | `O_ij` 비교가능성 제약 | C3 | `encoder.py`, `benchmark.py` |
| 7 | universe 층화 진단 + aggregation 규칙 | C2/C3 | `benchmark.py`, `metrics.py` |

Phase 1이 C1을 기각하면 Phase 2는 그대로 유효하나 논제를 재구성해야 한다(§0.1.1 강등 경로). 0번은
Phase 1에 두되 5번의 선행 조건이므로 어느 경로에서도 버려지지 않는다.

### 8.2 0번의 내용과 근거

gate 임계값은 `benchmark.py` 모듈 상단 DEFAULTS에 모여 있고, 판정 결과에 실제 사용값이 함께 기록된다.

```
time_validity_margin        = 0.01
missingness_r2_max          = 0.25
raw_concordance_min         = 0.50
missingness_pattern_ari_min = 0.20
```

**그러나 어떤 테스트도 이 값을 고정하지 않으며, config override가 계약 이탈로 표시되지 않는다.**
primary arm 순서는 `layers.py`에 선언되고 테스트가 강제하는데(§2.7), gate 임계값은 같은 대우를 받지 못했다.

1번 작업이 겨냥하는 값이 `missingness_r2_max = 0.25`다. 현재 상태로는 이 값을 0.30으로 바꾸면 통과한다.
**성공 기준을 조정해서 성공하는 것을 구조적으로 막는 것**이 0번의 목적이다.

작업 내용: 임계값을 `layers.py`로 이동, 값 고정 테스트 추가, override 시 non-conformant 표시,
운영 판정값임을 명시, 임계값 해시를 출력에 기록.

### 8.3 데이터 확보 후

| 작업 | 기여 | 전제 |
|---|---|---|
| 외부 시계열 데이터셋으로 `generalization` 평가 | C0/C2/C3 | §11 |
| τ의 dictionary 조작 반응(E2) 및 예측력 검증(E3) | C1 | dictionary 최소 1버전 |

### 8.4 불변 원칙

```
production_influence_allowed 는 6/6 gate 통과 이전에 열리지 않는다.
PRIMARY_SCORE_INPUTS_LOCKED 는 유지된다.
C1 은 관찰·분석이며 production 귀속 결과를 바꾸지 않는다.
```

---

## 9. 신규성 자기평가

리뷰어가 즉시 제기할 지적을 선제적으로 정리한다. **과대주장을 피하는 것이 이 절의 목적이다.**

### 9.1 C1 — 관련 연구와 실제 신규성

| 인접 문헌 | 관계 |
|---|---|
| linear probing / 표현 평가 프로토콜 | "표현이 하류에 유용한가"를 사후 측정. C1은 **사전 진단** |
| deconvolution·NMF 식별가능성, signature matrix collinearity | 매우 가깝다. bulk RNA deconvolution에서 condition number·collinearity 진단은 확립된 관행 |
| 민감도 분석, influence function | 입력 섭동의 출력 영향. C1은 **특정 상류 표현 변화 방향**에 한정 |
| 맹목 신호 분리 식별가능성 | 유사한 rank/uniqueness 논의 |

**수학적 내용은 초등적이다.** column space 정사영과 NNLS의 KKT 조건이며 새로운 정리가 없다.

condition number 진단과의 차이를 분명히 해야 한다. condition number는 dictionary의 **일반적** 조건화를
재고, τ는 **특정 섭동 방향**이 관측되는지를 잰다. 같은 `H`에서 어떤 상류 변화는 전달되고 어떤 것은
소멸할 수 있으므로 두 지표는 다르다. 그러나 **이 구분이 기여로 충분한지가 리뷰 질문 (1)이다**(§12).

**이 논변은 자체 코드베이스에서 반박될 수 있다.** condition number와 column coherence는
`tmm_identifiability.py`에 이미 구현되어 동일 site들에 대해 산출된다. 즉 "인접 문헌과 가깝다"가 아니라
**"인접 지표가 같은 데이터에 이미 계산되어 있다"**가 정확한 상태다. 따라서 이 절의 논변은 E1b(§5.5.0.1)의
실측으로 뒷받침되어야 하며, 그 전에는 미해결로 취급한다.

정직한 위치: 이론 신규성은 낮고, **진단 도구로서의 정식화와 실제 파이프라인에서 부정적 전달을 설명한
실증**이 기여다. dictionary가 데이터 추정이 아니라 **문헌 prior로 생성**되어 rank가 붕괴한다는 병리는
구체적이고 다른 도메인에도 존재할 형태다.

### 9.2 C2 — 관련 연구와 실제 신규성

| 인접 문헌 | 관계 |
|---|---|
| domain-adversarial training (DANN) | adversarial invariance 기법 자체가 확립됨 |
| fair representation learning | 보호 속성 불변 표현. 기법 동형 |
| HSIC / MMD 독립성 penalty | 대안 기법으로 이미 존재 |
| 프로테오믹스 MNAR 결측 대치 | 도메인 문헌 존재 |

**adversarial 분리 자체는 신규가 아니다.** 신규성 후보는 넷이다.

1. 불변 대상이 label/domain이 아니라 **구조적 결측 패턴**
2. 단일 adversary가 아닌 **예측기族에 대한 인증서**(§6.3 (c))
3. 예측력–독립성 **frontier의 정량화**(E5)
4. **handcrafted production 표현이 학습 표현보다 coverage에 더 얽혀 있다는 실측**(0.885 vs 0.462)

정직한 위치: 방법 신규성은 점진적이다. 4번이 가장 견고한 실증이고 2·3번이 방법론적 실체를 준다.
**headline으로 삼기 어렵다.**

### 9.3 C3 — 관련 연구와 실제 신규성

| 인접 문헌 | 관계 |
|---|---|
| 결측 데이터 군집화, 부분 거리(Gower 등) | 쌍별 유효 관측만 사용하는 관행 존재 |
| incomplete multi-view learning | 시점/view 결측 처리 |
| masked similarity | 유사 |

신규성 후보: 비교가능성을 **학습 목적함수를 제약하는 명시적 관계**로 다루는 것, 집중 구조의 실측
(상관 −0.86), false-merge 평가에 검정력 분석을 결합한 것(n_eff 432 대 125).

정직한 위치: 중간 정도. **C2에 흡수될 위험**이 있고 E10이 그것을 판정한다(§7.5).

### 9.4 C0 — 관련 연구와 실제 신규성

인코더 아키텍처는 신규성이 없다. 그러나 **다시점 마스킹의 대수적 누출**과 그것을 잡아낸 잡음 대조는
실질적 방법론 기여다. 한 view만 가리면 다른 view가 동일 measurement pair에서 값을 복원하므로 순수
잡음에서 R²=1.0이 나온다는 것은 이 분야가 빠지기 쉬운 함정이다.

정직한 위치: 단독 논문은 어렵지만 **더 큰 작업의 방법 섹션으로는 견고**하다.

### 9.5 종합

강점은 **C1 + C0 + 통합 논제 + 정직한 부정 결과**다. C2·C3은 보조 기여로 배치하는 것이 실제 무게에
맞다. 이 배치가 타당한지가 리뷰 질문 (6)이다.

C1의 신규성 방어는 §9.1의 논변만으로는 부족하고 **E1–E3의 실증에 달려 있다.**

| C1 실험 | 성공 기준 | 실패 시 해석 |
|---|---|---|
| E1 exact-`H` τ 감사 | rank·duplicate·fallback provenance와 함께 τ 계산 가능 | 진단 구현 자체가 불완전 |
| E2 dictionary intervention | prior-free / KSA 변경이 사전 지정 geometry 지표와 τ를 예측 가능하게 변화시킴 | τ는 `H` geometry의 설명변수가 아님 |
| E3 out-of-sample 예측 타당도 | **held-out** 블록에서 high-τ / low-τ가 관측된 `Δẑ`를 구별 | τ는 서술 통계에 그침 |
| E3b 기전 양성 대조 | rank 조작에 τ가 예측 방향으로 반응 | 진단 민감도 미증명 |

E1·E2가 성공하고 E3가 실패하면 C1은 "관찰"이지 "도구"가 아니다. 그 경우 §0.1.1의 강등 경로를 따른다.

---

## 10. 구현 현황 대비 제안

리뷰어가 "무엇이 이미 있고 무엇이 계획인가"를 혼동하지 않도록 분리한다.

| 항목 | 상태 |
|---|---|
| L1~L4 명명, 입력 계약, 검증 함수 | **구현·테스트 완료** |
| R0 baseline (PCA/NMF/FPCA/handcrafted) | **구현 완료** |
| mask-aware 결정적 인코더 | **구현 완료** |
| A~E ablation, 6-gate 판정 | **구현 완료, 실행됨 (4/6)** |
| 누출 저항 공정 프로브 | **구현 완료, 실행됨 (D 우세, p=0.0001)** |
| primary arm 사전등록 + 테스트 강제 | **구현 완료** |
| additive 필드 (reconstruction error, neighbor stability 등) | 계산·기록 완료, provenance 주입 미연결 |
| gate 임계값 테스트 고정 | **미구현** (§8.2) |
| coverage adversary | **미구현** (C2) |
| `O_ij` 학습 제약 | **미구현** (C3) |
| τ 측정 | **미구현** (C1) |
| 외부 데이터셋 일반화 | **미평가** |
| kinase 귀속 계층 (Core A/B) | **미구현.** C1의 분석 대상 |

---

## 11. 데이터 제약

리뷰 판단에 필요한 제약을 명시한다.

| 항목 | 상태 |
|---|---|
| 내부 시계열 데이터셋 | 이 규모의 paired control 시계열은 **HIRc-B 1건** |
| 내부 kinase 교란 데이터 | **없음.** 정량 matrix 보유 20개 데이터셋 전수 조사 결과 적격 0건 (§11.1) |
| 외부 시계열 후보 | 인간 insulin 시계열 1건 후보. **접근성 및 matched protein 정량 유무 미확인** |
| kinase-substrate dictionary | 플랫폼에 curated edge table **없음.** 현재 외부 API 호출과 하드코딩 prior에 의존 |

### 11.1 내부 데이터셋 교란 감사 (재현 가능)

이전 판본은 "19개 데이터셋"이라고 기술했다. **재감사 결과 20개이며 초판 수치는 오류였다.** 아래 표와
정의를 supplement로 제공한다.

```text
internal_dataset_audit_version   = v2
internal_dataset_audit_date      = 2026-08-20
audit_scope                      = data/inputs/*/ 중 정량 matrix
                                   (*pr_matrix*.tsv | *pg_matrix*.tsv | *report*.tsv) 보유 디렉터리
n_dataset_directories_scanned    = 21
n_with_quantitative_matrix       = 20        # rag/ 는 문헌 코퍼스로 matrix 없음 → 제외
n_qualifying_perturbation        = 0
```

**kinase 교란 정의 (사전 지정).** 아래 중 하나 이상에 해당하는 샘플이 존재하고, **대응되는
vehicle/control 샘플**이 함께 있을 때만 적격으로 판정한다.

```text
선택적 kinase 억제제 처리 (화합물명 또는 inhibitor/inhib 표기)
siRNA / shRNA / knockdown
CRISPR / knockout
vehicle 또는 DMSO 대조 (억제제 처리와 짝지어진 경우)
```

탐지 방식: 정량 matrix 헤더의 실행(run) 컬럼명을 위 정의의 정규표현식으로 검사. 검사 문자열에는
화합물명(MK-2206, rapamycin, wortmannin, LY294*, torin, U0126, PD0325*, staurosporin, trametinib,
dasatinib)과 일반 표기(inhibitor, inhib, DMSO, vehicle, siRNA, shRNA, knockdown, CRISPR, KO, siCtrl,
scramble)를 포함했다.

| 데이터셋 디렉터리 | 실행 수 | 교란 탐지 | 판정 |
|---|---:|---|---|
| BIOEN_phosphorylation | 5 | 없음 | 제외 |
| BioEN | 5 | 없음 | 제외 |
| BioEn_1 | 5 | 없음 | 제외 |
| Cu-Amyloid_fibril-microglia-phosphorylation | 17 | 없음 | 제외 |
| HM_Serum_free_phosphorylation | 11 | 없음 | 제외 |
| HM_palmitate_phosphorylation | 11 | 없음 | 제외 |
| HM_serum_phosphorylation | 11 | 없음 | 제외 |
| **Insulin_Signaling_Phosphoproteomics_HIRc-B** | 20 | 없음 | 교란 제외 / **표현 학습 primary 채택** |
| Irisin_TimeCourse_Phospho | 28 | 없음 | 제외 |
| Irisin_TimeCourse_Phospho_qwen3.5_27b | 28 | 없음 | 제외 (동일 데이터 재실행 추정) |
| Irisin_Ubiquitylation_Report | 28 | 없음 | 제외 |
| Irisin_Ubiquitylation_Report_1 | 28 | 없음 | 제외 (동일 데이터 재실행 추정) |
| KRIBB_HSC_ubiquitylation | 14 | 없음 | 제외 |
| KRIBB_SCS_Phosphorylation | 14 | 없음 | 제외 |
| Korea_Ubiquitylation_Timecourse | 11 | 없음 | 제외 |
| Korea_timecouse_drugrepositioning | 11 | 없음 | 제외 (명칭의 "drugrepositioning"은 보고 모드이며 처리 조건 아님) |
| Microgravity_Muscle_Atrophy_Phosphoproteomics | 11 | 없음 | 제외 |
| PTM-2026-0001 | 28 | 없음 | 제외 |
| Universe_AF | 8 | 없음 | 제외 |
| WithoutCu-AmyloidFibril-microglia-phosphorylation-1 | 17 | 없음 | 제외 |
| rag | — | matrix 없음 | 감사 범위 외 (문헌 코퍼스) |

**주의 — distinct 실험 수는 20보다 적다.** 실행 수와 명명이 동일한 항목들(BIOEN 계열 3건 n=5,
Irisin 계열 4건 n=28, Cu/WithoutCu 쌍, HM 계열 3건 n=11)은 동일 원자료의 재실행 또는 동일 연구의
조건 분할로 보인다. **논문 supplement에는 디렉터리 수가 아니라 distinct 실험 단위를 명시적으로
선언해야 하며, 이 확인은 미완이다**(§13).

**HIRc-B paired-control 적격 정의.** feature별 paired control replicate 수로 층을 나눈다:
≥2 (확증, 2,420 feature) / 정확히 1 (sensitivity, 302) / 0 (탐색, 313).

### 11.2 검증 범위와 그 결과 (Validation scope and consequence)

> 사전 지정된 kinase 교란 정의(선택적 억제제, siRNA, CRISPR/KO, 또는 짝지어진 vehicle/control)로
> 정량 matrix를 보유한 내부 데이터셋 20건을 전수 감사한 결과 적격 데이터셋은 **0건**이었다. 사용
> 가능한 paired-control 시계열은 HIRc-B 1건에 한정된다.
>
> **따라서 본 연구는 개별 kinase 귀속 정확도를 추정하지 않고, 표현→귀속 전달을 교란 truth에 대해
> 비교하지 않으며, 학습된 표현이 kinase 활성 예측을 개선한다고 주장하지 않는다.** C1은 그보다 앞선
> 질문을 평가한다 — 상류 표현 섭동이 고정 하류 dictionary 추정기에 기하적으로 보이는가.
>
> 이 특성화를 귀속 정확도 주장으로 전환하려면 **동일 시스템에서 시간 분해 교란 실험**이 필요하다.
> 이는 optional validation이 아니라 필수 요건이다.

### 11.3 이 제약이 각 기여에 미치는 영향

- **C0/C2/C3**: `generalization` gate에 외부 데이터셋 1건이 필요하다. primary arm이 temporal-only(D)이므로
  다시점 데이터는 불필요하나, Track 2가 protein-normalized 신호이므로 matched protein 정량은 필요하다.
  없으면 미정규화 adapter를 쓰고 결론을 방향 일치 수준으로 제한한다
- **C1**: dictionary 최소 1버전이 필요하다. E2는 dictionary를 **바꿔가며** τ 반응을 보는 실험이므로
  복수 버전이 있으면 더 강해진다. E3b 양성 대조는 합성 dictionary 조작으로 가능하므로 외부 데이터에
  의존하지 않는다
- **kinase 귀속 성공 주장**: 내부 교란 데이터가 없어 불가능하다. **이것이 C1을 성공 주장이 아닌 특성화
  기여로 설정한 실질적 이유 중 하나다**

---

## 12. 리뷰어에게 묻는 것

우선순위 순이다.

**(1) C1의 신규성이 방어 가능한가.** deconvolution의 condition number / collinearity 진단 문헌이
확립되어 있는데, "특정 섭동 방향의 관측 가능성"이라는 구분이 독립 기여로 충분한가. 아니면 기존 진단의
특수 사례로 취급될 것인가. §9.1이 핵심 쟁점이다.

**(2) 부정 결과를 주 결과로 삼을 수 있는가.** ~~"상류 표현 개선이 하류로 전달되지 않는다"를 주 결과로
제시할 때 무엇이 더 필요한가. positive counterpart가 반드시 필요한가.~~
**→ 외부 검토에서 답을 받았다.** 필수는 아니나 있으면 훨씬 강해지며, **생물학적 truth 없는 기전 양성
대조로 충분하다.** dictionary intervention에서 τ가 오르고 `Δẑ`가 예측대로 반응하면 diagnostic
sensitivity proof로 유효하다(귀속 정확도 증명으로는 무효). §5.5.2 E3b로 설계에 반영했다.

**(3) 통합 논제가 학위논문 척추로 충분한가.** "표현과 귀속은 함께 설계되어야 한다"는 명제가 기여 4건을
묶는 축으로 충분한지, 아니면 각 기여가 독립적으로 평가되어 개별 무게 부족으로 판정될 위험이 큰가.

**(4) C2의 인증서 수준.** 예측기族에 대한 경험적 검증(§6.3 (c))으로 충분한가, 형식적 상한이 필요한가.

**(5) C3을 유지할 것인가.** E10에서 C2에 흡수될 위험이 있다. 미리 C2의 구현 세부로 강등하는 것이
나은가.

**(6) 기여 4건이 과다한가.** §9.5의 배치(C1·C0 주, C2·C3 보조)가 타당한가.

**(7) 단일 cohort + 외부 1건으로 일반화 주장이 성립하는가.** §11의 제약에서 어디까지 주장할 수 있는가.

---

## 13. 미해결 항목

| 항목 | 상태 |
|---|---|
| gate 임계값 테스트 고정 | 미구현. §8.2. 1번 작업의 선행 조건 |
| coverage adversary의 결정성 유지 | **미검증.** min-max가 NumPy 결정적 구현에서 안정한지 (§6.6) |
| C2 인증서의 예측기族 범위 | 미확정. 사전 확정 필요 |
| E1b 판별력 판정 기준 (τ가 방향 무관 지표와 "구별된다"의 정량 정의) | **미확정. C1 신규성의 최소 조건** (§5.5.0.1) |
| E3의 calibration / held-out 블록 분할 기준 | **미확정. C1 방어의 핵심 선행 조건** (§5.5.1) |
| E3의 τ 임계·aggregation·출력 통계량 | 미확정. held-out 결과 열람 **전**에 동결해야 함 |
| 내부 데이터셋 distinct 실험 단위 수 | **미확정.** 디렉터리 20개 중 재실행 중복 존재 (§11.1). supplement에 선언 필요 |
| 외부 시계열 데이터셋 접근성 | 미확인 |
| dictionary(KSA) 확보 경로 및 라이선스 | 미조사 |
| kinase 귀속 계층 재개 시 선행 조건 | 별도 문서 `core_ab_p2_frozen_contract_v1.md` §10.2에 6건 기록 |

---

## 부록 A. 용어

| 용어 | 의미 |
|---|---|
| PTM | 번역후수식. 본 연구에서는 주로 인산화 |
| site/form | 수식 부위 및 형태. 분석의 기본 단위 |
| Track 1 / Track 2 | occupancy 기반 / protein-normalized ratio 기반 정량 경로 |
| co-wave | 시간 프로파일이 유사한 site 집합 |
| dictionary `H` | kinase별 시간 프로파일 행렬. 열 하나가 kinase 하나 |
| exclusive substrate | 정확히 한 kinase에만 배정된 site |
| induced missingness R² | 인공 마스킹 후 임베딩에서 유도 결측률을 예측한 R². 낮아야 함 |
| ARI | Adjusted Rand Index. 마스킹 전후 군집 일치도 |
| `n_eff` | Kish 실효 표본 수. 군집 상관 보정 |
| `production_influence_allowed` | 학습 표현이 production 점수에 영향을 줄 수 있는지의 잠금 |
