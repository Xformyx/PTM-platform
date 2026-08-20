# PTM 분석 통합 연구 설계 v1 — 표현 학습과 귀속 추론의 합성

작성일: 2026-08-20
상태: **작업 초안. `integrated_research_design_v2.md`로 대체됨.** 외부 리뷰에는 v2를 사용한다.
대체 관계: `docs/2026-08-20_core_ab_scope_decision.md`의 범위 결정을 **개정**한다
포함 범위: 기 구현된 representation learning (R0~R1.7) + Core A/B + 신규 기여 3건
성격: 연구 설계. 논문 기여 구조와 그에 대응하는 구현 계획

---

## 0. 이전 결정의 개정

`2026-08-20_core_ab_scope_decision.md`는 논문 기여 주장 수준을 **표현 학습 자체**로 확정하고 Core A/B를
조건부 확장으로 강등했다. **이 결정을 개정한다.**

개정 사유는 그 결정이 잘못된 축을 최적화했기 때문이다.

| 축 | 이전 결정의 판단 근거 | 누락된 판단 |
|---|---|---|
| 측정 가능성 | 표현 학습은 평가 장치가 이미 작동, blocker 없음 | — |
| 기여의 무게 | **고려하지 않음** | 표준 masked autoencoder + 쉬운 대리 과제 + 작은 이득 |

이전 결정은 "지금 측정 가능한 것"을 기여로 골랐다. 그러나 측정 가능성과 기여의 무게는 독립적인 축이고,
CS 학위논문 심사가 요구하는 것은 후자다.

### 0.1 현재 표현 학습 구현의 CS 기여 무게 — 정직한 평가

| 항목 | 실상 | 심사 관점의 문제 |
|---|---|---|
| 인코더 아키텍처 | quality-weighted masked MSE + auxiliary view + gap-aware smoothness + L2 | masked autoencoder, FPCA, mask-aware NMF는 모두 기존 방법. **아키텍처 신규성 없음** |
| 성능 이득 | arm D가 baseline 대비 ΔR² **+0.0271** | baseline이 이미 R² 0.924. 계약서 스스로 "부드러운 궤적의 한 시점을 이웃에서 맞히는 쉬운 과제"라 기술 |
| 일반화 | 단일 cohort | `generalization` gate 미평가 |
| 하류 유용성 | 미증명 | BLOCKER-E가 원리적으로 불가능할 수 있다고 지적 |

이 상태로 제출하면 "기존 표현 학습 방법을 새 도메인에 적용해 쉬운 대리 과제에서 작은 개선을 얻었고
하류 유용성은 보이지 못했다"가 된다. **도메인 응용 논문이지 CS 방법론 논문이 아니다.**

### 0.2 그런데 가장 강한 기여를 blocker로 분류했다

BLOCKER-E의 내용은 다음이었다. 하류 귀속 모델의 설계행렬 `H`가 prior로 생성되어 rank가 붕괴하고
(kinase 111개 → distinct 열 9개), 그 결과 **상류 표현 개선 중 `col(H)`에 직교하는 성분이 구조적으로
소멸한다.** NNLS의 KKT 조건이 `y`에 대해 `H'y`를 통해서만 의존하므로 계수를 바꾸지 못한다.

이것을 "구현을 막는 장애물"로 분류했다. 그러나 성질을 다시 보면 **결과**다.

> 상류 표현 학습의 이득은, 하류 귀속 모델의 기저가 prior로 생성되고 rank 결핍일 때
> 구조적으로 전달되지 않는다.

표현 학습 문헌은 "더 좋은 표현 → 더 좋은 하류 성능"을 대체로 가정한다. 그 가정이 언제 깨지는지를
정량화하는 진단(τ)은 재사용 가능한 분석 도구이며, 2단계 파이프라인 일반에 적용된다.

**즉 "representation learning이 전부가 아니다"라는 지적의 답은 표현 학습을 더 하는 것이 아니라,
합성(composition) 문제를 기여로 세우는 것이다.**

---

## 1. 논제와 기여 구조

### 1.1 논제

> **다단계 생물학적 측정 파이프라인에서 표현의 품질만으로는 하류 추론의 품질이 결정되지 않는다.
> 표현과 귀속 추론은 함께 설계되어야 한다.**

이 논제는 세 개의 방법론 기여와 하나의 플랫폼 기여로 지지된다.

### 1.2 기여 구조

| | 기여 | 성격 | 현재 상태 |
|---|---|---|---|
| **C1** | 전달성 분석 (transmissibility) | 분석·이론 | BLOCKER-E에서 승격. τ 정의됨, 미구현 |
| **C2** | Coverage 분리 표현 학습 | 방법 | gate 실패로 필요성 실증됨, 미구현 |
| **C3** | 비교가능성 제약 표현 학습 | 방법·정식화 | `O_ij` 실측 완료, guard→제약 승격 필요 |
| **C0** | 누출 저항 평가 프로토콜 + 표현 학습 플랫폼 | 방법론·기반 | **구현 완료 (R0~R1.7)** |

C0은 기존 구현이고, C1~C3이 신규 기여다. Core A/B는 폐기되지 않고 **C1의 분석 대상**으로 재배치된다.

### 1.3 각 기여의 일반성

CS 기여로 인정받으려면 도메인을 넘는 적용 범위가 있어야 한다.

| 기여 | 일반 문제 형태 | 적용 도메인 |
|---|---|---|
| C1 | 고정된 하류 추정기에 대해 상류 표현 변화의 관측 가능 비율 | deconvolution, unmixing, topic attribution, cell-type deconvolution, source separation — 2단계 파이프라인에서 2단계가 고정 dictionary를 갖는 제약 선형/원뿔 추정기인 모든 경우 |
| C2 | MNAR 구조적 결측 하에서 결측 패턴을 인코딩하지 않는 표현 학습 | single-cell, EHR, 센서 네트워크, 패널 조사 |
| C3 | 부분 비교가능성 관계 위에서의 표현 학습 | 희소 관측 패널 일반, 시계열 정렬 불가 코호트 |
| C0 | 다시점 시계열 표현의 누출 저항 평가 | 다시점 자기지도 학습 평가 일반 |

---

## 2. C1 — 전달성 분석 (transmissibility)

### 2.1 문제 정식화

2단계 파이프라인을 생각한다. 1단계가 표현 `z`를 만들고, 2단계가 고정된 dictionary `H`로 귀속
계수를 추정한다. 표현을 개선했을 때 하류 추정치가 바뀌는가?

```
문제:  상류 표현 변경이 만든 응답 섭동 d 중,
       하류 추정기가 관측할 수 있는 성분은 얼마인가?

관측:  NNLS (비음수 제약 최소자승) 의 KKT 조건은 y 에 대해 H'y 를 통해서만 의존한다.
       ⇒ col(H) 에 직교하는 d 성분은 계수를 전혀 바꾸지 못한다.
       ⇒ rank(H) 가 작으면 대부분의 표현 개선이 소멸한다.
```

### 2.2 진단 지표

```text
τ  =  aggregate_i ( ‖P_H d_i‖² / ‖d_i‖² )
       d_i  = (개선된 표현의 응답벡터) − (기준 표현의 응답벡터)
       P_H  = col(H) 정사영 연산자

해석  = 현재 하류 estimator geometry 에서 보존되는 섭동 energy fraction
보장  = 필요조건만.  τ → 0 ⇒ 효과 없음.  τ 높음 ⇒ 효과 보장 안 됨
금지  = τ 를 효과 크기의 정량적 상한으로 기술하는 것
        (NNLS 는 원뿔 투영이며 이후 feature weight·후보 부분집합·정규화가 개입)
성격  = development decision threshold. effect-size significance threshold 아님
```

**필수 명세 (외부 검토 반영, 누락 시 결과 무효)**

| 항목 | 규칙 |
|---|---|
| zero denominator | `‖d_i‖²` 하한 미달 feature 제외 또는 epsilon 규칙 사전 고정 |
| weighting | projector와 norm에 적용할 고정 feature weight, universe·reliability 정책과 일치 |
| rank tolerance | SVD tolerance 및 condition-number 임계 사전 고정. **tolerance 없이 numerical rank는 정의되지 않는다** |
| aggregation | median 단독 금지. IQR, weighted mean, low-observation stratum 병기 |
| uncertainty | feature-clustered bootstrap, resampling seed 동결 |
| H identity | candidate universe·KSA hash·profile rule·peak table hash·column hash로 실제 scoring `H`와 동일함을 증명 |

### 2.3 실증 근거 (이미 확보)

이 분석이 공허하지 않다는 증거가 이미 있다. production 귀속 모델의 `H`는 두 경로로만 생성된다.
exclusive substrate 3개 이상이면 data-driven 프로파일, 아니면 문헌 `typical_peak_min` 중심 Gaussian.
후자는 **`peak_min` 스칼라 하나의 결정적 함수**이므로 같은 값을 공유하는 kinase는 수치적으로 동일한
열을 받는다.

| 관측 | 값 |
|---|---:|
| duplicate column 비율 | 61.5 ~ 100% |
| 오더 36: kinase 수 → distinct 열 수 | 111 → **9** |
| rank-one design | 54.4% |
| non-identifiable | 51.2% |
| `relative_residual ≥ 0.999` | 54.5% |
| top-1이 자기 ambiguity set 내부 | 89.0% |

근거: `docs/tmm_identifiability_diagnosis.md`, `api-server/app/services/temporal_kinase_scoring.py`

### 2.4 이것이 답하는 질문

C1은 "Core B를 성공시키는" 기여가 아니다. **언제 성공할 수 있고 언제 원리적으로 불가능한지를
특성화하는** 기여다. 이 전환이 중요하다.

```
이전 프레임:  Core B 가 작동해야 한다 → BLOCKER-A/B/E 를 모두 풀어야 한다 → 위험
현재 프레임:  Core B 의 전달 한계를 특성화한다 → BLOCKER 들이 연구 재료가 된다
```

특히 `A4 transmission not measurable`(구 BLOCKER-D)은 유감스러운 한계가 아니라 **C1이 설명하는
현상**이 된다. 측정 불가라는 사실 자체가 τ로 정량화되고 예측된다.

### 2.5 실험 설계

```text
E1  τ 측정 (기본)
    대상: HIRc-B, U-confirmatory
    비교: arm D 표현 vs baseline L1 표현이 만든 응답 섭동
    출력: τ, τ_dd (data-driven 부분행렬), rank, condition number, duplicate group

E2  H 조작에 대한 τ 반응
    prior 열 제거, KSA manifest 변경, MIN_EXCLUSIVE_FOR_PROFILE 변화 시
    exclusive-substrate yield / fallback fraction / rank(H) / duplicate rate / τ 를 pre-post 측정
    → τ 가 설계행렬 성질의 함수로 예측 가능한지 검증 (C1 의 핵심 주장)

E3  τ 의 예측력 검증
    τ 가 높은 하위집합과 낮은 하위집합에서 실제 하류 변화량을 비교
    → τ 가 사전 진단으로 유효한지 (C1 이 도구로 쓸 만한지)
```

E3이 C1을 단순 관찰에서 **검증된 진단 도구**로 만든다. τ를 정의만 하고 예측력을 보이지 않으면
기여가 약하다.

---

## 3. C2 — Coverage 분리 표현 학습

### 3.1 문제

질량분석 프로테오믹스의 결측은 MNAR이며 구조적이다. 저농도 site가 체계적으로 관측되지 않으므로
결측 패턴 자체가 정보를 담는다. 그 결과 표현이 시간 패턴 대신 **coverage를 인코딩**하기 쉽다.

이미 측정된 실패다.

| arm | 차원 | induced missingness R² | 군집 ARI (마스킹 후) |
|---|---:|---:|---:|
| B (handcrafted L1, 현 production) | 30 | **0.885** | 0.234 |
| D (temporal-only 학습) | 16 | 0.462 | 0.035 |
| E (multi-view 학습) | 16 | 0.273 | **0.974** |
| 상한 / 하한 기준 | | 0.25 | 0.2 |

### 3.2 이 표가 담은 두 개의 발견

**(1) 현 production 표현이 학습 표현보다 coverage에 더 얽혀 있다.** handcrafted B의 0.885는 mask
indicator를 feature로 직접 포함하기 때문이다. "학습 표현이 handcrafted보다 신뢰할 수 없다"는 통상적
우려를 반박하는 실측이며, 그 자체로 보고 가치가 있다.

**(2) D와 E는 상반된 실패를 한다.** D는 예측력이 가장 좋지만 coverage 누출이 최악이고, E는 마스킹
robustness가 유일하게 살아있지만 예측 이득이 없다. E의 안정성은 protein context와 Track 1이라는
**비시간적 부수 정보**에서 온 것이므로, "E로 되돌린다"는 해법이 아니다.

즉 이것은 **예측력과 coverage 독립성의 교환**이며, 이 교환을 푸는 것이 C2의 과제다. 단순히 penalty를
추가하는 것으로는 기여가 되지 않는다.

### 3.3 방법 설계

```text
목적함수 확장 (현행: quality-weighted masked MSE + auxiliary + gap-aware smoothness + L2)
  추가항 = coverage adversary
           보조 예측기가 임베딩 z 로부터 관측 마스크 m 을 맞히려 하고,
           인코더는 그것을 실패시키도록 학습 (gradient reversal 또는 min-max)
  대안   = mutual information 상한 penalty (추정 필요, 결정성 유지 어려움)
  제약   = 현 구현의 결정성(seed 고정, NumPy 전용) 유지.
           PyTorch/CUDA 를 worker 선언 의존성에 추가하지 않는다는 기존 원칙 준수
```

**기여가 되기 위한 조건: 인증서(certificate).** "penalty를 넣었더니 R²가 내려갔다"는 방법 기여가
아니다. 필요한 것은 다음이다.

```text
C2 성립 조건
  (a) induced missingness R² ≤ 0.25 달성       # gate 통과
  (b) 동시에 fair probe ΔR² 이득 유지          # 예측력을 팔지 않았음
  (c) 잔여 mask 예측 가능성의 상한 또는 검증 절차 제시
      → 단일 예측기로 못 맞힌 것이 아니라 예측기族에 대해 낮음을 보임
  (d) §3.2(2) 의 교환을 실제로 풀었다는 증거
      = D 의 예측력 + E 의 robustness 를 동시에 갖는 arm
```

(c)가 방법 기여의 핵심이다. adversary 하나를 이긴 것은 그 adversary가 약했다는 증거일 수도 있다.

### 3.4 실험 설계

```text
E4  coverage adversary 도입 후 gate 재판정 (induced R², ARI, fair probe ΔR² 동시)
E5  adversary 강도 sweep → 예측력-독립성 frontier 곡선
    → §3.2(2) 교환의 형태를 정량화. frontier 자체가 결과다
E6  예측기族 검증: ridge / kNN / gradient boosting 으로 잔여 mask 예측 가능성 측정
E7  층화 진단: universe 별(§5.2), 저관측 층별로 실패가 집중되는지
    aggregation 규칙 = median 단독 금지, 층별 병기 (C1 §2.2 와 동일 원칙)
```

---

## 4. C3 — 비교가능성 제약 표현 학습

### 4.1 문제 정식화

표현 학습은 통상 **완전 비교가능성**을 가정한다. 임의의 두 점 사이 거리가 의미를 갖는다는 가정이다.
그러나 희소 관측 패널에서는 성립하지 않는다. 공유 관측 timepoint가 부족한 두 feature는 **비교 자체가
유효하지 않다.**

```
정식화: 부분 비교가능성 관계 O ⊆ V × V 위에서의 표현 학습
        O_ij = 1  ⟺  feature i, j 가 공유 관측 timepoint T_min 이상
        이웃 계산·군집·거리 기반 손실이 O 를 존중해야 한다
```

### 4.2 실측 근거

| 기준 | 비교 불가 pair 비율 | affected pair |
|---|---:|---:|
| U-confirmatory, replicate ≥1, T_min=4 | 2.51% | 73,537 |
| U-confirmatory, replicate ≥2, T_min=4 | 9.07% | 265,500 |

전역 비율은 작지만 **소수 저관측 feature에 집중**되어 있다.

```
비교 불가 degree 와 관측 timepoint 수의 상관: −0.764 (rep≥1) / −0.869 (rep≥2)
상위 1% feature(24개)가 비교 불가 edge 종단의 39.5%
상위 5% feature 평균 관측 4.12/6 vs 나머지 5.96/6
```

이 집중 구조가 §3의 coverage 얽힘과 **같은 축**이다. C2와 C3은 독립 기여이지만 같은 병목을 겨냥하며,
병용 효과를 측정해야 한다.

### 4.3 guard에서 제약으로

현재 `O_ij`는 사후 correctness guard로 규정되어 있다. C3은 이를 **학습 제약**으로 승격한다.

```text
현재  = 결과 해석 시 비교 불가 쌍을 배제 (사후)
C3    = 이웃 계산·대조 손실·군집이 O 를 존중하도록 학습 (사전)
        비교 불가 쌍은 손실에서 제외하거나 별도 처리
평가  = pair 수준 false-merge rate
        불확실성: feature-clustered bootstrap
        계층: replicate ≥ 2 만 사용 (Kish n_eff = 432)
        금지: replicate ≥ 1 계층 (n_eff = 125, 검정력 미달)
```

필요 표본(α=.05, power=.80, ψ=0.75): 불일치율 5%→578, 10%→289, 20%→145. 따라서 replicate≥2만 판정
가능하다.

### 4.4 실험 설계

```text
E8   O 제약 적용 전후 false-merge rate (pair 수준, clustered bootstrap)
E9   O 제약이 induced missingness R² 와 ARI 에 미치는 영향
     → C2 와 독립적으로 gate 를 움직이는지
E10  C2 × C3 병용: 네 조합(무제약 / C2 / C3 / C2+C3)에서 gate 3지표 동시 측정
E11  T_min 민감도: T_min ∈ {3,4,5} 에서 결론이 유지되는지
     사전 확정: T_min = 4 를 primary, 나머지는 sensitivity
```

E10이 중요하다. 두 기여가 같은 병목을 겨냥하므로 **상호 대체적인지 상보적인지**를 보여야 한다.

---

## 5. C0 — 기존 구현의 위치

기 구현된 representation learning은 폐기되지 않고 **기반 기여 + 평가 장치**로 배치된다.

### 5.1 구현 현황 (실물 확인, 2026-08-20)

```
ptm_shared/representation/
  layers.py           명명 단일 출처, PRIMARY_SCORE_INPUTS_LOCKED, PRIMARY_ARM_PREFERENCE
  feature_contract.py L3 다시점 입력 계약, validate_multiview_input()
  baselines.py        R0: mask_aware_pca / mask_aware_nmf / fpca_lite / handcrafted
  encoder.py          R1: 결정적 mask-aware self-supervised autoencoder
  benchmark.py        A~E ablation, 6-gate 판정
  fair_probe.py       R1.6: 누출 저항 held-out 시점 프로브
  metrics.py          additive 필드

workers/tests/test_ptm_representation_learning.py
workers/tests/test_representation_fair_probe.py        (13개)

data/outputs/Insulin_Signaling_Phosphoproteomics_HIRc-B/
  ptm_representation_benchmark_phospho.json            ← 실제 생성됨
  ptm_representation_embeddings_phospho.tsv            ← 실제 생성됨
```

preprocessing Step 1c로 파이프라인에 통합(progress 56~60%), 실패 시 non-fatal.

### 5.2 C0의 기여 내용 — 평가 방법론

인코더 아키텍처는 신규성이 없다(§0.1). 그러나 **평가 프로토콜은 기여가 된다.**

핵심은 `fair_probe.py` 개발 중 발견된 누출이다. 한 timepoint를 Track 2에서만 가리면, 같은 timepoint의
protein context와 Track 1 occupancy가 동일 measurement pair에서 계산되므로 **다른 view를 가진 arm이
가려진 값을 대수적으로 복원**한다. 잡음 데이터 대조에서 이것이 드러났다 — 전체 view를 가리기 전에는
**순수 잡음에서 R² = 1.0**이 나왔다(`test_probe_reports_no_skill_on_noise`).

```text
C0 프로토콜
  전체 view 마스킹      = 같은 timepoint 를 모든 view 에서 제거 (누출 차단)
  순열 귀무분포          = 프로브 target 섞어 no-skill 기준 확립
  짝지은 sign-flip 검정  = 동일 (가린 시점, 분할) 짝에서 baseline 과 비교
  ridge penalty 내부 CV  = 고차원 arm 이 자동으로 유리해지지 않게
  사전등록              = PRIMARY_ARM_PREFERENCE 를 코드에 고정, 테스트가 강제
```

**사전등록이 코드에 있다는 점이 방법론적으로 중요하다.** "이 데이터셋에서 이긴 arm을 primary로 쓴다"고
하면 gate를 평가하는 데이터로 gate의 피험자를 고르는 셈이 된다. 순서를 누출 없는 프로브 결과에 근거해
고정하고 테스트로 강제한 구조는 그대로 논문 방법 섹션이 된다.

### 5.3 기존 지표 중 arm 비교에 쓸 수 없는 것 (보존해야 할 발견)

`raw_evidence_concordance`는 arm 간 순위에 사용할 수 없다. arm B의 임베딩은 학습된 표현이 아니라
**원본 궤적 값 그 자체**이므로(T=6에서 30차원), 원본 궤적 공간에서 이웃을 찾으면 peak 시점과 부호가
같은 것이 거의 항등식이다. 이 지표는 하한 점검이며 경쟁 벤치마크가 아니다.

`missingness_r2`도 예측변수 개수를 보정하지 않은 R²이므로 30차원 arm과 16차원 arm을 나란히 놓을 수 없다.

이 두 항목은 **편향된 지표가 어떻게 결론을 뒤집을 수 있는지의 사례**이므로 C0의 일부로 보고한다.
초기 판정에서 "학습이 handcrafted에 못 미친다"는 인상이 편향된 지표의 산물이었고, 공정한 프로브에서
뒤집혔다(D가 24쌍 전부에서 B를 앞섬, p=0.0001).

### 5.4 명명 체계 통합

`layers.py`가 명명의 단일 출처이며 테스트가 강제한다. Core A/B 어휘를 병행하지 않고 편입한다.

| Core A/B 어휘 | 통합 후 위치 |
|---|---|
| A1 residual | `PTM_Relative_Log2FC` (이미 protein-normalized). 신규 작업 없음 |
| A2 eligibility weight | `qvalue_policy` 기존 정책 |
| A3 `O_ij` | **C3으로 승격** |
| A4 temporal wave prototype | arm D 내부 아키텍처 선택지 |
| feature universe 4분할 | 데이터셋 특성화 + C2/C3 층화 근거 |
| F00~F11 factorial | A~E ablation에 통합. C1의 `H` 조작 실험(E2)이 별도 |
| Core B KSA scorer, 5-gate | **C1의 분석 대상** |

feature universe (HIRc-B 로컬 값, 외부 복사 금지):

| universe | feature 수 |
|---|---:|
| paired control replicate ≥ 2 | 2,420 |
| paired control 정확히 1 | 302 |
| paired control 0 | 313 |

---

## 6. Core A/B와 blocker의 재배치

### 6.1 성공 대상에서 분석 대상으로

가장 중요한 전환이다.

```
이전:  Core B 가 작동해야 논문이 성립 → BLOCKER-A/B/E 전부 해제 필요 → 고위험
현재:  Core B 는 C1 이 특성화하는 대상 → blocker 가 연구 재료
```

### 6.2 blocker 성격 변화

| blocker | 이전 성격 | 현재 성격 |
|---|---|---|
| A. KSA library 부재 | 해제 필수 | **C1 E2의 실험 조건.** manifest를 바꿔가며 τ 반응을 측정하는 것이 실험 설계. 다만 최소 1개 버전 확보는 필요 |
| B. PXD014525 접근성 | primary endpoint 전제 | 선택적. Tier-2 성공 주장을 하지 않으므로 필수 아님 |
| C. 외부 시계열 데이터셋 | `generalization` gate | **여전히 필요.** C2/C3 일반화 주장의 전제 |
| D. A4 transmission 측정 불가 | 구조적 한계 | **C1이 설명하는 현상.** τ로 정량화·예측 |
| E. prior가 설계행렬 구성 | 설계 구멍 | **C1의 실증 근거 (§2.3)** |
| F. LLM 예측 kinase 유입 | 오염 경로 | C1 실험에서 `H` 구성의 통제 변수. `CONFIRMATORY_CANDIDATE_UNIVERSE_V1` 필요 |

**임계 경로에 남는 blocker는 C(외부 데이터셋)와 A의 최소 1개 버전 확보뿐이다.**

### 6.3 보존 문서

| 문서 | 역할 |
|---|---|
| `ptm_representation_learning_contract_v1.md` | C0 계약. §12는 편입 기록 |
| `core_ab_p2_frozen_contract_v1.md` | C1 분석 대상의 설계 명세. §10.2 재작업 항목 유효 |
| `2026-08-20_core_ab_scope_decision.md` | **이 문서로 개정됨.** 추론 이력으로 보존 |
| `~/Downloads/Core_A_B_설계행렬_LLM오염_문제진단_20260820.md` | C1의 기전 진단 |
| `tmm_identifiability_diagnosis.md` | C1의 실측 근거 |

---

## 7. 실행 계획

### 7.1 즉시 착수 (blocker 무관, 기존 코드 수정)

| 순위 | 작업 | 기여 | 대상 파일 |
|---|---|---|---|
| 1 | coverage adversary 목적함수 추가 | C2 | `encoder.py` |
| 2 | `O_ij` 비교가능성 제약을 학습에 도입 | C3 | `encoder.py`, `benchmark.py` |
| 3 | universe 층화 진단 + aggregation 규칙 | C2/C3 | `benchmark.py`, `metrics.py` |
| 4 | τ 측정 구현 (E1) | C1 | 신규 모듈 + 기존 `H` 빌더 재사용 |
| 5 | gate 임계값 코드 고정 + 성격 명시 | C0 | `layers.py`, `benchmark.py` |

5번을 먼저 하는 편이 낫다. 1~4의 판정 기준이 되는 값들이고, 함수 인자 기본값으로 흩어져 있으면
사후 조정 여지가 남는다. 임계값은 **운영 판정값이며 통계적 유의성 임계값이 아니라는 점**을 함께
명시한다.

### 7.2 데이터 확보 후

| 작업 | 기여 | 전제 |
|---|---|---|
| 외부 시계열 데이터셋으로 `generalization` 평가 | C2/C3 | BLOCKER-C |
| τ의 `H` 조작 반응 (E2) 및 예측력 검증 (E3) | C1 | KSA manifest 최소 1버전 |

### 7.3 불변 원칙

```
production_influence_allowed 는 6/6 gate 통과 이전에 열리지 않는다.
PRIMARY_SCORE_INPUTS_LOCKED 는 유지된다.
C1 은 관찰·분석이며 production 귀속 결과를 바꾸지 않는다.
```

---

## 8. 미해결 및 판단 필요

| 항목 | 상태 |
|---|---|
| gate 임계값의 코드 고정 여부 | **미확인.** §7.1의 5번 |
| coverage adversary의 결정성 유지 가능성 | 미검증. min-max가 NumPy 결정적 구현에서 안정한지 |
| C2 (c) 인증서의 구체적 형태 | 미확정. 예측기族 범위를 사전 확정해야 함 |
| 외부 시계열 데이터셋 후보 | PXD043599 외 미조사. protein 정량 유무 확인 필요 |
| C1 E3의 검증 설계 | τ 하위집합 분할 기준 미확정 |
| `kinase_weight_manager` 문헌 가중 | 미확인. C1의 `H` 통제에 영향 |

---

## 9. 이 설계가 조언에 답하는 방식

> "Representation Learning이 전부가 아니다"

맞다. 그리고 답은 표현 학습을 더 쌓는 것이 아니다. **표현이 하류로 전달되는지를 묻는 것이
독립적인 기여**이며, 그 질문에 답하는 도구(τ)와 그 답이 부정적인 이유(prior로 생성된 rank 결핍
설계행렬)를 이미 확보했다.

기여 구조를 다시 보면 C0(평가 방법론)은 이미 있고, C2·C3은 측정된 실패에서 필요성이 실증된
방법 기여이며, C1은 표현 학습 문헌의 암묵적 가정을 검사하는 분석 기여다. **네 개가 "표현과 귀속의
합성" 논제로 묶인다.**
