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

이를 4개 구성요소로 지지하되, **"기여 4건"이 아니라 "구현된 기반 1 + 특성화 3"으로 서술한다.**
상태를 뭉치면 과장이 된다.

**2026-08-22 갱신.** 이 표는 C2·C3을 "미구현"으로 적고 있었다. 둘 다 구현·실행되었고 사전등록된
판정에서 방법 주장이 부정되었다. 아래는 실행 후 상태다 — 세 확장 전부가 방법 장이 아니라 특성화 장이다.

| | 기여 | 논문에서의 역할 | 현재 증거 |
|---|---|---|---|
| **C0** | 누출 저항 평가 프로토콜 + 표현 학습 기반 | **구현된 방법론 기반** | 공정 프로브, D arm 우세, gate 4/6 — 실측 완료 |
| **C1** | 전달성 분석 (transmissibility, τ) | **특성화 장 (2026-08-22 강등 확정, §9.7)** | τ 실측 완료. E3b 민감도 입증. **E3 예측 타당도는 미평가** |
| **C2** | Coverage 분리 표현 학습 | **한계 기술 장 (2026-08-21 확정, §9.5)** | adversary 구현·E4–E8 실행 완료. **λ\* 미발견 → 인증서 미충족** |
| **C3** | 비교가능성 제약 표현 학습 | **한계 기술 장 (2026-08-22 확정, `c3_prereg_v1.md` §17)** | 제약 구현·E9–E12 실행 완료. E9 primary 통과, **단 λ·T_min 의존으로 일반성 철회** |

### 0.1.1 실패 시 강등 경로 (논제 척추 보호)

각 구성요소의 실패 조건과 강등 경로를 **앞에서** 노출한다. 어느 하나가 실패해도 논제가 무너지지 않아야
한다는 것이 설계 요건이다.

| | 실패 조건 | 강등 경로 | 논제 영향 |
|---|---|---|---|
| C0 | (해당 없음. 실측 완료) | — | 없음 |
| C1 | ~~held-out E3에서 τ가 하류 변화를 구별 못 함~~ → **실제로는 E3 자체가 평가 불가** (§9.7) | **발동 완료 (2026-08-22).** 진단 주장 철회, 퇴화 구조·τ 계층 분해·진단 민감도 특성화만 유지 | 흡수됨. C1은 중심 기여에서 특성화 장으로 이동하고 척추는 C0+감사가 지탱한다 |
| C2 | adversary가 예측력을 보존하며 coverage 누출을 줄이지 못함 (§6.5) | **발동 완료 (2026-08-21).** 방법 주장 철회. 단 "교환의 불가피성"으로는 전환하지 **않는다** — coverage 축은 해결되었고 막힌 것은 ARI 축과 국소 잔존이다 (§9.5) | 제한적. §2.8 교환 결과가 남는다 |
| C3 | E11(구 E10)에서 효과가 C2에 흡수됨 (§7.5) | **다른 경로로 발동 (2026-08-22).** 흡수가 아니라 **적대** — C2+C3가 C2 단독보다 유의하게 나쁘다. 여기에 E12 의 T_min 뒤집힘이 겹쳐 일반성 철회 (`c3_prereg_v1.md` §16.1·§16.2·§17) | 없음. 사전에 허용된 결과 |

C1만이 단일 실패점이다. 그래서 C1 트랙에서는 §5.5.1(held-out 설계)과 §5.5.2(양성 대조)가 τ 측정보다
먼저다(§8.1 4번 → 5번 순서).

**2026-08-22 결과.** 네 강등 경로 중 **세 개가 발동했다**(C1·C2·C3). 설계 요건("어느 하나가 실패해도
논제가 무너지지 않아야 한다")은 하나의 실패를 상정했으므로, **셋이 동시에 발동한 상태가 여전히 논제를
지탱하는지는 이 표로 답할 수 없다.** 이것이 외부 검토의 중심 질문이다
(`external_review_request_2026-08-22.md` §2).

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

### 2.8 arm 들은 서로 다른 실패를 한다 — 두 조건을 동시에 만족하는 arm 이 없다

| | 차원 | 예측력 (프로브 ΔR²) | 마스킹 후 군집 ARI (≥0.20) | induced missingness R² (≤0.25) | natural missingness R² |
|---|---:|---:|---:|---:|---:|
| A (원 궤적, 비학습) | 12 | −0.0008 | 0.167 ✗ | **0.0073 ✓** | **0.235** |
| B (production, 비학습) | 30 | 기준 | 0.234 ✓ | **0.885 ✗** | 0.388 |
| D | 16 | **+0.0271** | 0.035 ✗ | 0.462 ✗ | **0.849** |
| E | 16 | −0.0060 | **0.974 ✓** | 0.273 ✗ | 0.409 |

E의 안정성은 protein context와 Track 1이라는 **비시간적 부수 정보**에서 왔고, 그래서 예측력이 없다.
즉 multi-view branch는 robustness를 사고 예측력을 팔았다. **"E로 되돌린다"는 해법이 아니다.**

**A가 보여주는 것 (2026-08-21 추가).** 학습 없는 원 궤적의 induced R²가 0.0073이다. **coverage 얽힘은
데이터에 내재한 것이 아니라 표현이 도입한다.** 동시에 A는 예측 이득이 없고 retention ARI 0.167로
다른 조건에서 실패하므로 **"A로 되돌린다"도 해법이 아니다.** 임계 0.25가 도달 가능하다는 존재
증명이라는 점에서 C2의 표적 설정 근거가 된다(`c2_prereg_v1.md` §2.1).

**두 coverage 지표의 순위가 반대다 (필수 병기).** induced 기준 최악은 B(0.885)이나 natural 기준
최악은 D(0.849)이며 B는 A 다음으로 좋다(0.388). 어느 한쪽만 인용하면 arm 서열이 뒤바뀐다. 판정에
쓰는 것은 gate가 쓰는 induced 지표이며, natural은 항상 병기한다.

**R² 절대값의 arm 간 비교는 판정에 쓰지 않는다** — 예측변수 개수 미보정이며 차원이 12·30·16으로
다르다(§2.5). 위 표는 목표 설정과 실패 양상 기술용이다.

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

**2026-08-21 수정.** 초안은 E1b 실패를 C1 기각 조건으로 두었으나, 외부 검토에서 구성 타당도 질문과
확증 판정의 결합이 부적절함이 지적되어 철회했다. **C1의 관문은 E3 단독이다**
(`c1_prereg_v1.md` §6.6).

- **E3의 held-out OOF에서 high-τ / low-τ의 하류 변화량이 구별되지 않으면 → C1 기각.** τ는 서술 통계에
  그치며 진단 도구로 무효 (동일 `(H, d)` 내 상관은 근거로 인정하지 않는다. §5.5.1)
- `|S-EVAL| < 73`이면 → E3 primary 평가 불가. C1 미평가 선언
- 인코더 출력 열공간이 NNLS 조건 공간과 정렬되지 않으면 → **τ 정의 불성립. 사전등록 무효**
- E1b에서 중복도가 높게 나오면 → τ의 **증분** 가치가 작다는 기술 결과. **C1 기각 아님**
- E2에서 τ가 dictionary 성질과 무관하게 움직이면 → 기전적 corroboration 부재. primary 판정 불변
- E3b 양성 대조에서 dictionary rank를 올려도 τ가 반응하지 않으면 → 진단 구현 자체가 불완전
- τ가 모든 조건에서 높게 나오면 → 전달 실패가 실재하지 않으며 C1의 동기 소멸 (§5.3과 모순되므로 가능성 낮으나 검증 대상)

---

## 6. C2 — Coverage 분리 표현 학습

### 6.1 문제

MNAR 구조적 결측 하에서 표현이 시간 패턴 대신 **coverage를 인코딩**한다. §2.7의 `missingness_validity`
실패가 이것이며, §2.8이 그 구조를 보여준다.

핵심은 단순 실패가 아니라 **교환**이다. D는 예측력이 최고이나 coverage 누출이 최악이고, E는 마스킹
robustness가 유일하게 살아있으나 예측 이득이 없다. 이 교환을 푸는 것이 C2의 과제다.

> **2026-08-21 보강 — 교환은 2-arm이 아니라 4-arm 패턴이다.** `c2_prereg_v1.md` 작성 중 arm 전체를
> 확인한 결과 위 서술이 불완전하다. gate의 두 하위 조건을 **동시에 만족하는 arm은 없으나 각각은
> 개별적으로 만족된다** — retention ARI는 B(0.234)·E(0.974)가, induced R²는 **A(0.0073)**가 만족한다.
> 특히 **학습 없는 원 Track 2 궤적(A)의 induced R²가 0.0073으로 임계의 3%**이며, 이는
> **coverage 얽힘이 데이터 내재가 아니라 표현이 도입하는 것**임을 뜻한다(수공 B 0.886, 학습 D 0.462).
> A는 그 대가로 예측 이득이 없고(ΔR² −0.0008, p = 0.776) retention ARI 0.167로 다른 조건에서 실패한다.
> 판정용 서술은 `c2_prereg_v1.md` §2.1이 정본이다.

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
(a) missingness_validity gate 통과                     # 하위 조건 2개의 논리곱
    = pattern_retention_ari ≥ 0.20  AND  induced R² ≤ 0.25
(b) 동시에 프로브 ΔR² 이득 유지                          # 예측력을 팔지 않았음
(c) 잔여 mask 예측 가능성이 예측기族에 대해 낮음을 제시
    → adversary 하나를 이긴 것은 그 adversary 가 약했다는 증거일 수도 있다
(d) §6.1 의 교환을 실제로 풀었다는 증거
    = D 의 예측력 + E 의 robustness 를 동시에 갖는 arm
```

**(c)가 방법 기여의 핵심이다.** 예측기族 범위를 사전 확정해야 한다.

> **(a)의 초판 오류 (2026-08-21 수정).** 초판은 (a)를 "induced missingness R² ≤ 0.25"로만 적었으나
> 코드의 gate는 **두 하위 조건의 논리곱**이다(`benchmark.py` L585–588). D는 두 조건 **모두** 실패
> (ARI 0.035, R² 0.462)하고 E는 **R² 조건만** 실패(ARI 0.974, R² 0.273)하므로, R² 단독으로 읽으면
> 두 arm의 질적으로 다른 실패가 같은 것으로 보인다. 판정 규칙은 `c2_prereg_v1.md` §1.2가 정본이다.

> **사전등록 완료 (2026-08-21).** `docs/c2_prereg_v1.md` v1 초안 작성. (a)–(d) 정량 판정, 예측기族
> 5종(P1–P5, scikit-learn 미의존), λ sweep 격자 8점과 선택 규칙, frontier 판정, 다중성 논리,
> adversary 없는 대조(E8, veto)를 확정했다. **아직 동결 전이며 §14의 필수 완료 항목 5건이 열려 있다.**
> 그중 3건은 임계에 대한 사용자 승인 사항이다.
>
> 작성 중 발견된 추가 문제 3건도 그 문서에 반영했다 — 단일 seed 판정(§1.3), induced 표적의 영값
> 편중(§2.3), 그리고 **두 coverage 지표의 arm 순위가 반대**라는 사실(§2.2. induced 기준 최악은 B,
> natural 기준 최악은 D). §2.8의 서술은 induced 기준에서만 성립한다.

### 6.4 실험

```
E4  adversary 도입 후 gate 재판정 (induced R², ARI, 프로브 ΔR² 동시)
E5  adversary 강도 sweep → 예측력–독립성 frontier 곡선
    → 교환의 형태를 정량화. frontier 자체가 결과다
E6  예측기族 검증: ridge / kNN / gradient boosting 으로 잔여 mask 예측 가능성 측정
E7  층화 진단: universe 별·저관측 층별 실패 집중 여부
    aggregation = median 단독 금지, 층별 병기
E8  adversary 없는 대조: 기존 하이퍼파라미터 격자만으로 (a)+(b)+(c) 달성 가능한지
    → §6.5 의 세 번째 반증 조건에 배정된 실험. veto 전용(C2 를 실패시킬 수만 있다)
    예산은 E5 격자 점 수 이상 (불공정 대조 방지). c2_prereg_v1.md §10
    ** 실행 완료 2026-08-21: 27 구성 전부 (a) 실패. veto 발동 안 함 (§10.4) **
```

**E8만 완료되었고 E4–E7은 미실행이다.** adversary가 아직 구현되지 않았기 때문이다. E8을 먼저
실행한 이유는 그것이 veto이므로 **방법을 만들기 전에 방법의 필요성을 반증할 수 있기** 때문이다.
§7의 "C1 생존 검정을 C2 구현보다 앞에 둔다"와 같은 논리다.

### 6.5 반증 조건

- E5의 frontier가 (a)와 (b)를 동시에 만족하는 점을 갖지 않으면 → 교환이 근본적이며 C2는 실패
- E6에서 다른 예측기族이 mask를 여전히 맞히면 → adversary가 특정 예측기만 속인 것이며 (c) 미충족
- adversary 없이도 하이퍼파라미터 조정만으로 (a)+(b)가 달성되면 → C2의 방법 기여 소멸

### 6.6 알려진 위험

현 구현이 NumPy 전용 결정적 학습이다. min-max 구조가 이 환경에서 안정적으로 수렴할지 미검증이다.
막히면 MI 상한 penalty로 우회해야 하나, 그쪽은 결정성 유지가 더 어렵다. **PyTorch 도입은 worker 의존성
정책 변경을 요구하므로 별도 판단 사항이다.**

### 6.7 E7 층화 진단 결과 (2026-08-22) — 전체 요약은 실패를 축소해 보여준다

전문 표와 해석 한계는 `c2_prereg_v1.md` §9.2. 세 가지가 논문 서술을 바꾼다.

**첫째, coverage 인코딩은 저관측 층의 인공물이 아니다.** 모집단의 84.8%인 완전 관측 층(2,328
form)에서 족 최대 mask 회수 R²가 **0.9888**이다. 조건 (c) 상한은 0.25다. 전체 값 0.6247은
저관측 층과 섞여 내려간 값이므로 **문제를 축소해 보고한 것**이었다.

이것은 C2의 문제 진술을 강화한다. "결측이 많은 소수 site 때문"이라는 가장 흔한 반론이
층화로 제거된다 — 결측이 **없는** site에서 induced mask가 거의 완전히 복원된다.

**둘째, 저관측 층의 낮은 값을 독립성으로 읽을 수 없다.** `minimum_remaining = 3` 때문에 관측
4/6 site는 최대 1개만 마스킹 가능하고 관측 3/6 site는 아예 불가능하다. 표적 분산이 없으면
R²는 낮게 나온다. **증거 부재와 독립성의 증거가 이 설계에서 분리되지 않는다** — 논문에 이
교란을 명시하고, 분리에는 마스킹 예산을 관측 수에 비례시키지 않는 대체 프로토콜이 필요하다고
적는다.

**셋째, 사전등록한 층 축 하나가 퇴화했다.** 자연 결측률 사분위의 경계 세 개가 모두 0.0이어서
Q2·Q3가 비고 Q1이 완전 관측 층과 동일 집합이 되었다. 조용히 빼지 않고 기록한다 — 선언한 층이
데이터셋에서 퇴화한다는 사실 자체가 특성화 자료다.

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

**재측정 (2026-08-22).** 위의 432/125는 **Core A/B 트랙 모집단**의 값이다. C3의 판정 모집단
(form 단위, `eligible_subset`, HIRc-B)에서 다시 재면 다음이며, `c3_prereg_v1.md` §7.4가
이 값으로 판정한다.

| 계층 | T_min | n_eff | 판정 |
|---|---:|---:|---|
| replicate ≥ 1 | 4 | 304.4 | 5% 불일치 검출 불가 (578 필요). §7.3의 금지가 옳았다 |
| **replicate ≥ 2** | **4** | **995.2** | **충족** |

`rep≥2` 계층은 원 `report.pr_matrix.tsv`의 run 컬럼에서 복원했다(결합률 1.0000). 표현 학습
입력에는 시점별 replicate 수가 없으므로 이 결합 없이는 §7.3이 요구한 계층을 만들 수 없었다
(`c3_prereg_v1.md` §3.1·§12.1).

**`n_eff` 단독으로 검정력을 말하지 않는다.** 제약이 완벽해도 뒤집을 수 있는 쌍은 현재 잘못
병합된 쌍뿐이므로 불일치율은 `FM_exposure`(arm D에서 8.60%)를 넘지 못한다. `rep≥1`에서는
검정 가능한 최소 불일치율(10%)이 그 상한을 넘어 **검정력이 있어도 검출 대상이 없었다.**

### 7.4 실험

**번호 정정 (2026-08-22).** 초판은 C3의 실험을 E8–E11로 적었으나 **E8은 C2의 초모수 통제
실험**(`c2_prereg_v1.md` §11)에 이미 쓰였다. 같은 이름이 두 실험을 가리키면 사전등록의 추적
가능성이 깨지므로 C3을 **E9–E12**로 옮긴다. 이 정정은 실험 내용을 바꾸지 않는다.

```
E9   O 제약 적용 전후 false-merge rate (pair 수준, clustered bootstrap)   ← 초판 E8
E10  O 제약이 induced missingness R² 와 ARI 에 미치는 영향                 ← 초판 E9
E11  C2 × C3 병용: 4조합(무제약 / C2 / C3 / C2+C3)에서 gate 3지표 동시 측정  ← 초판 E10
E12  T_min 민감도: T_min ∈ {3,4,5}. primary = 4, 나머지는 sensitivity      ← 초판 E11
```

**E11이 중요하다.** 두 기여가 같은 병목을 겨냥하므로 상호 대체적인지 상보적인지 보여야 한다.

판정 규칙·임계·모집단은 `c3_prereg_v1.md`에서 확정한다. **그 문서가 동결되기 전에는 제약을
구현하지 않는다** — C1에서 순서를 지킨 덕에 "평가 불가"가 "실패"로 오기록되지 않았다(§8.1).

**`c3_prereg_v1.md` 동결 완료 (2026-08-22).** §12 실측 4건이 §13의 미결 5건을 닫았다.
E9는 3-기준선 설계(대조 손실 없음 / 무제약 대조 / 제약 대조)로 확정되었고, primary 대조는
제약 대조 손실 대 **무제약 대조 손실**이다 — 기준선을 현행 arm D로 두면 "대조 항을 추가한
효과"와 "그 항에서 비교 불가 쌍을 뺀 효과"가 섞이고, C3이 주장하는 것은 후자뿐이다.

### 7.5 반증 조건

- E9에서 false-merge rate가 유의하게 개선되지 않으면 → 제약이 실질 효과 없음
- E11에서 C3의 효과가 C2에 완전히 흡수되면 → 독립 기여로 성립하지 않고 C2의 구현 세부로 격하
- E12에서 결론이 `T_min`에 민감하면 → 정식화가 임계값 의존적이며 일반성 주장 약화
- **자명한 성공(군집을 잘게 쪼개 false merge를 없애는 것)은 실패로 처리한다.** 이 경로를 막는
  동반 지표와 임계는 `c3_prereg_v1.md` §5에서 확정한다

**E9 결과 (2026-08-22).** 상세는 `c3_prereg_v1.md` §15, 산출 레코드는 `docs/results/c3_e9/`.

```text
primary (λ = 1.0)   FM_precision 0.14436 → 0.11548   95% CI [−0.0386, −0.0198]
                    G1a 0.4713 / G1b 0.0702 / G2 no_shrinkage / G3 ΔR² 0.019014
                    → §5.3 다섯 조건 논리곱 통과.  자명한 성공 경로 미발동

선언된 λ 민감도     λ = 0.3 악화 (CI 전부 양수),  λ = 3.0 CI 가 0 을 포함
                    → 효과가 λ 에 단조가 아니다.  **일반성 주장 철회**

병기한 기준선 0     대조 항 없음(현행 arm D) 의 FM_precision 이 0.10421 로 가장 낮다
                    → 대조 항 자체가 악화를 만들고 제약은 약 70% 만 회복한다
```

**이 결과로 성립하는 주장과 성립하지 않는 주장을 구별한다.** §6.2가 primary 대조를
"제약 대 무제약"으로 미리 고정했으므로 §5.3 판정은 형식적으로 성립한다. 그러나 기준선 0이
가장 낮다는 사실 때문에 **"C3가 현행 표현을 개선한다"는 주장은 성립하지 않는다.** 성립하는
것은 조건부 주장 하나다 — "대조 손실을 쓰는 표현 학습에서 비교가능성 관계를 손실에서
존중하면 근거 없는 병합이 줄어든다. 단 λ에 의존하며 대조 항을 쓰지 않는 표현보다 낫다는
뜻은 아니다."

### 7.6 C3의 장 지위 — **확정: 방법 장이 아니다** (2026-08-22)

E10·E11·E12를 모두 실행했다. 상세는 `c3_prereg_v1.md` §16–§17.

```text
E12  T_min 민감도    FM 방향은 견디나 자명성 guard G2 가 T_min ∈ {3,5} 에서 미달
                     개선의 **기제**가 바뀐다 — T_min=4 는 병합을 늘리며 개선, 3·5 는 줄이며 개선
                     → §9 반증 조건 4 발동.  일반성 주장 철회
E11  독립성          C2+C3 가 C2 단독보다 **유의하게 나쁘다** (두 C2 λ 모두)
                     동결 규칙은 "독립"·"흡수" 두 분기만 열거했고 이것은 세 번째 경우다
E11  병기            C3 단독은 현행 arm D 와 통계적 차이 없음 (CI 가 0 을 포함)
E10  gate 지표       C3 는 induced R² 를 0.462 → 0.598 로 **올린다** (기제 설명 후보)
```

**C3를 한계·특성화 장으로 내린다.** primary 통과 1건 대 선언된 민감도 2축 전부 뒤집힘,
현행 표현 대비 차이 없음, 다른 기여와 결합 시 악화가 누적된 결과다. 방법 장이라면 "언제
쓰면 되는가"에 답해야 하는데 답이 "λ ≈ 1, T_min = 4, C2 없이, 대조 손실을 이미 쓰고 있을 때"
이며 처방이 아니다.

**두 사실이 동시에 참이라는 점을 논문에서 지우지 않는다.** §5.3은 결과 열람 전에 동결되어
있었고 λ = 1.0·T_min = 4는 미리 고정된 primary였으며 그 판정은 통과했다. 임계를 사후에
고르지 않았다. "C3가 실패했다"는 **장의 지위에 대한 판단**이고 "C3의 primary가 통과했다"는
**사전등록된 판정의 결과**다. 전자만 쓰면 사전등록이 무의미해지고 후자만 쓰면 과대 주장이다.

### 7.6.1 C2와 C3의 대립 — 이 국면에서 가장 값이 있는 결과

```text
C2  결측 구조를 표현에서 **뺀다**            induced R² 0.564 → 0.042
C3  결측 구조를 비교가능성으로 **존중한다**   induced R² 0.462 → 0.598

같은 표현 안에서 두 목적이 양립하지 않는다.
C2+C3 는 C2 단독보다 근거 없는 병합이 많다 (0.20361 대 0.10898, CI [+0.078, +0.111])
```

두 기여가 각각 자신의 목표에 도달하지 못했지만, **둘이 대립한다는 사실**은 어느 한쪽만
했으면 나오지 않는다. "결측을 빼기"와 "결측을 존중하기"가 PTM 시계열 표현 학습에서 구조적으로
충돌한다는 정량적 증거이며, 이것은 §0.1.2의 주장 범위 안에서 방어 가능한 양의 결과다.

**동반 지표 확정 (2026-08-22).** 4개의 논리곱이며 어느 하나로 성공을 주장하지 않는다.

```
G1a  구조 보존       비교 가능 쌍 ARI(제약, 무제약)          ≥ 0.0237
G1b  식별성 비퇴행    제약 표현의 seed 간 비교 가능 쌍 ARI     ≥ 0.0237
G2   제거 표적성      Δfalse_merges / Δmerged_pairs          ≥ 0.50
G3   예측력          공정 프로브 ΔR²                         ≥ 0.01355  (c2_prereg §7.2 인용)
```

임계 산정의 근거와 **G1a가 약한 기준이라는 사실**은 `c3_prereg_v1.md` §5.2에 있다. 요약하면
arm D의 군집은 인코더 seed만 바꿔도 ARI 0.0237–0.0373만 재현되므로 절대 임계를 쓸 수 없고,
그래서 임계가 잡음 하한 대비 상대값이 되었으며 그 약함을 메우기 위해 G1b를 추가했다.

**이 발견이 C2로 되돌아갔다.** 같은 축에서 재면 arm D의 마스킹 전후 ARI(0.0350)가 인코더
seed만 바꾼 ARI(0.0427–0.0675)보다 **낮다.** 즉 `missingness_pattern_ari_min = 0.20`(§8.2.1)은
무제약 arm D의 재현성 상한보다 3–5배 높으며, 그 조건이 arm D에서 재는 것은 마스킹 강건성이
아니라 군집의 seed 불안정이다. 상세는 `c2_prereg_v1.md` §13.3이며, **임계는 바꾸지 않고 그
조건이 무엇을 재는지를 기술한다** — 임계가 틀린 것이 아니라 그 성질을 이 arm에서 측정할 수
없다는 것이 결론이다.

### 7.6.2 E7이 준 기전 설명 — C3의 여지는 애초에 층 혼합의 산물이었다 (탐색적)

E9의 λ 취약성과 E11의 적대성은 §16까지 **관측 사실로만** 남아 있었다. E7의 층화가 그것에
기전 수준 설명을 준다. 전문은 `c2_prereg_v1.md` §9.2.3–§9.2.4.

FM_precision을 층 내 **비교 불가 기저율**과 나란히 재면 이렇다.

| 층 | FM_precision | 비교 불가 기저율 | 비 |
|---|---:|---:|---:|
| (전체) | 0.1042 | 0.2020 | **0.52** |
| 관측 6/6 (n=2,328) | 0.0313 | 0.0423 | 0.74 |
| 관측 5/6 (n=241) | 0.6335 | 0.7215 | 0.88 |
| 관측 4/6 (n=109) | 0.9760 | 0.9919 | 0.98 |
| 관측 3/6 (n=66) | 1.0000 | 1.0000 | 1.00 |

**비가 어느 층에서도 1을 넘지 않는다** — arm D의 군집은 비교 불가 쌍을 기저율보다 더 선호하지
않는다. 그리고 **전체의 0.52라는 여유는 층 혼합에서 나온다**: 기저율 0.042인 큰 층과 1.0에
가까운 작은 층을 섞으면 각 층의 비가 0.74–1.00이어도 합산 비는 0.52로 내려간다(Simpson 형
역전).

따라서 비교 불가가 밀집한 층에서는 **줄일 여지가 구조적으로 없다.** 남은 여지는 층 간 쌍뿐이고
그것을 줄이는 것은 군집을 층 경계로 쪼개는 것과 같으므로, C3의 이득이 자명성 guard(G2)와 정면
경쟁한다. λ에 취약했던 것과 C2와 결합했을 때 악화된 것이 같은 원인에서 나온다.

**이 설명은 결과를 본 뒤에 얻었으므로 탐색적이며 C3의 어떤 primary 판정도 갱신하지 않는다.**
Chapter 4(특성화 장)의 내용으로만 쓴다. 동시에 이것이 **§0.1.2 범위 안에서 방어 가능한 형태의
기여**다 — "우리 방법이 작동한다"가 아니라 "이 데이터 구조에서 그 목적함수의 여지가 어디에
있고 왜 없는지"를 정량화한 것이다.

---

## 8. 실행 계획

### 8.1 즉시 착수 (blocker 무관, 기존 코드 수정)

**순서 원칙: 단일 실패점을 가장 먼저, 가장 싸게 검정한다.** C1이 유일한 단일 실패점이고(§0.1.1),
E1은 기존 모듈 확장이라 저렴하다(§5.5.0). 따라서 C1 생존 검정이 C2/C3 구현보다 앞에 온다. 순서를
반대로 하면 C1이 죽었을 때 C2/C3 작업이 없어진 척추를 향하게 된다.

**Phase 1 — C1 생존 검정 (선행)**

| 순위 | 작업 | 기여 | 대상 |
|---|---|---|---|
| 0 | gate 임계값 사전등록 강화 (§8.2) | C0 | **완료 (2026-08-22).** `layers.py`, `benchmark.py`, 테스트 11건 |
| 1 | **판정 규칙 동결** — E1b 판별력 기준, E3 블록 분할, τ 임계, aggregation, 출력 통계량 | C1 | `c1_prereg_v1.md` — **동결 완료 (2026-08-22)** |
| 2 | τ 측정 (E1) | C1 | **완료.** `ptm_shared/c1_transmissibility.py` |
| 3 | **E1b 판별력 검정** — τ vs condition number / coherence | C1 | **완료.** `ptm_shared/c1_inference.py` |
| 4 | E3b 기전 양성 대조 (합성 dictionary rank 조작) | C1 | **완료. 기준 충족** (§9.7) |

1번이 2번보다 앞이다. **τ를 계산한 뒤에 판정 규칙을 정하면 C1은 방어할 수 없다.**

**이 순서가 실제로 작동했다 (2026-08-22).** 1번의 선행 측정에서 세 확장 수준 전부가 검정력에
미달함이 드러났다(§9.6 갱신). τ를 먼저 계산했다면 이 사실을 **결과를 본 뒤에** 발견했을 것이고,
그 시점의 모집단 확장은 사후 선택과 구별되지 않는다. E3의 primary 자격은 순서를 지킨 덕에
"평가 불가"로 남았고 "실패"로 오기록되지 않았다.

**Phase 2 — 표현 학습 방법 (Phase 1 결과 확인 후)**

| 순위 | 작업 | 기여 | 대상 |
|---|---|---|---|
| 5 | coverage adversary 목적함수 | C2 | **완료 (2026-08-21).** `coverage_adversary.py`, `encoder.py`. λ\* 미발견 → 한계 기술 장 |
| 6a | C3 사전등록 + 동결 전 실측 | C3 | **완료 (2026-08-22).** `c3_prereg_v1.md` 동결, `comparability.py`, `measure_c3_prefreeze.py`, 회귀 20건 |
| 6b | `O_ij` 비교가능성 제약 구현 + E9 | C3 | **완료 (2026-08-22).** `comparability_constraint.py`, `replicate_stratum.py`, `encoder.py`, `run_c3_e9.py`, 회귀 26건. §5.3 다섯 조건 통과, **단 λ 의존**(§7.6) |
| 6c | E10·E11·E12 | C3 | **완료 (2026-08-22).** `run_c3_e10_e11.py`. 반증 조건 4 발동, E11 은 규칙 밖 분기. **C3 강등 확정 (§7.6)** |
| 7 | universe 층화 진단 + aggregation 규칙 (E7) | C2/C3 | **완료 (2026-08-22).** `replicate_stratum.py`(universe 분할), `run_c2_e7_stratified.py`, 회귀 10건. **전체 요약이 층 구조를 가리고 있었다** (§6.7, §7.6.2) |

Phase 1이 C1을 기각하면 Phase 2는 그대로 유효하나 논제를 재구성해야 한다(§0.1.1 강등 경로). 0번은
Phase 1에 두되 5번의 선행 조건이므로 어느 경로에서도 버려지지 않는다.

**§8.1의 0–7번이 2026-08-22 로 전부 완료되었다.** 이 계획에 남은 미실행 항목은 없다. 다만
"완료"는 **선언한 실험을 선언한 순서로 돌렸다**는 뜻이며 방법이 성공했다는 뜻이 아니다 — C1은
primary 평가 불가(§9.7), C2는 인증서 미통과(§6.4), C3는 강등(§7.6)이다. 다음 작업은 이 계획의
연장이 아니라 **남은 데이터·감사 미결**(§13)에서 고른다.

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

#### 8.2.1 동결 대상 확정 (2026-08-22, 구현 전)

무엇을 동결하는지가 애매하면 "동결했다"는 주장 자체가 검증 불가다. 두 묶음으로 나눈다.

```text
GATE_JUDGEMENT_THRESHOLDS   판정 부등식에 직접 들어가는 값.  위 4개
    time_validity_margin        = 0.01
    missingness_r2_max          = 0.25
    raw_concordance_min         = 0.50
    missingness_pattern_ari_min = 0.20

GATE_PROBE_PARAMETERS       판정값은 아니지만 **판정 대상 수치를 만드는** 값
    artificial_mask_fraction    = 0.15   ← induced 표적을 정의한다. 낮추면 gate 가 쉬워진다
    cluster_distance_threshold  = 0.30   ← retention ARI 의 군집 정의
    minimum_cluster_size        = 2
    seed                        = 0      ← induced mask 추출
```

**`seed` 만 등호가 아니라 집합 소속으로 검사한다.** `c2_prereg_v1.md` §1.3
(`INDUCED_MASK_SEED_SET_V1 = {0,1,2,3,4}`)이 gate 판정을 단일 seed 가 아니라 5 seed 의 중앙값과
「5 중 4 통과」로 정의했기 때문이다. seed 1 로 돌린 실행은 사전등록된 프로토콜의 한 반복이며
이탈이 아니다. 집합 밖의 seed 는 이탈로 본다 — **seed 탐색으로 통과하는 경로**를 막는다.

두 번째 묶음을 함께 동결하는 이유는 **임계를 건드리지 않고도 gate 를 쉽게 만들 수 있기 때문**이다.
`artificial_mask_fraction`을 0.15에서 0.05로 낮추면 `missingness_r2_max = 0.25`는 그대로여도
induced 표적의 분산이 줄어 통과가 쉬워진다. 판정 부등식만 잠그는 것은 반쪽 조치다.

두 묶음 모두 **이미 사전등록되어 있다.** 첫 번째는 이 문서 §8.2, 두 번째는
`c2_prereg_v1.md` §1.1(「동결된 설정값」). 따라서 §8.2.1은 새 값을 도입하지 않고 **선언 위치를
한 곳으로 모으는 것**이다.

#### 8.2.2 이탈 시의 처리 — 표시로 그치지 않는다

초안은 "override 시 non-conformant 표시"였다. 표시만으로는 §8.2의 목적("성공 기준을 조정해서
성공하는 것을 구조적으로 막는 것")이 달성되지 않는다. 표시를 읽지 않으면 그만이다.

```text
확정  GATE_THRESHOLD_CONFORMANCE_V1

  선언값과 실사용값이 다르면
    (1) 이탈 항목·선언값·사용값·방향(완화/강화)을 판정 출력에 기록한다
    (2) production_influence_allowed = False 로 강제한다.  6/6 통과여도 열리지 않는다
    (3) 판정 출력에 threshold_override_is_exploratory = True 를 남긴다

  민감도 분석은 계속 가능하다 — 수치는 그대로 산출된다.
  달라지는 것은 **그 수치로 production 을 열 수 없다**는 것뿐이다
```

**왜 완화만 막지 않고 강화도 막는가.** 방향 판단은 지표마다 부호가 달라(margin·ARI는 클수록
엄격, R²는 작을수록 엄격) 구현 오류가 나기 쉽고, 무엇보다 **강화된 임계로 통과한 결과를 선언
임계의 결과로 보고하면 그것도 사전등록 이탈**이다. 방향은 기록하되 판정은 이탈 여부만 본다.

임계 묶음의 sha256을 판정 출력과 `describe_contract()`에 함께 기록해, 논문 supplement의 수치가
어느 임계 집합에서 나왔는지 사후에 확인 가능하게 한다.

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

### 8.5 변경 기록 의무

개발 종료까지 모든 연구 관련 변경은 **코드와 함께 용도·근거가 남아야 한다.** 논문 methods 절이 사후
재구성이 아니라 기록의 정리가 되도록 한다.

| 장치 | 역할 |
|---|---|
| `.cursor/rules/research-code-provenance.mdc` | 강제 규칙. provenance docstring 4항목, 상수의 선언 위치 인용, 사전등록 상태 단방향성, 주장 범위, 결정성 기록 |
| `docs/implementation_log.md` | append-only 원장. 변경별 구현 대상 설계 §, 사전등록 상태, 논문에서의 용도, 해석 한계 |

핵심은 하나다 — **"이 값은 결과를 보기 전에 정해졌는가"에 답할 수 있어야 한다.** 이 기록이 없으면
falsifiability 주장을 증명할 방법이 없다. 문서에 없는 판정 임계가 코드에 나타나면 사전등록 위반이며
해당 판정을 탐색적으로 강등한다.

---

## 9. 신규성 자기평가

리뷰어가 즉시 제기할 지적을 선제적으로 정리한다. **과대주장을 피하는 것이 이 절의 목적이다.**

### 9.1 C1 — 관련 연구와 실제 신규성

| 인접 문헌 | 관계 |
|---|---|
| **선형 역문제의 resolution matrix (Backus–Gilbert 1968; Wiggins 1972; Jackson 1972)** | **τ_col은 이것의 방향별 평가와 수학적으로 동일하다. 아래 §9.1.1** |
| linear probing / 표현 평가 프로토콜 | "표현이 하류에 유용한가"를 사후 측정. C1은 **사전 진단** |
| deconvolution·NMF 식별가능성, signature matrix collinearity | 매우 가깝다. bulk RNA deconvolution에서 condition number·collinearity 진단은 확립된 관행. 최근에는 식별가능성 조건으로 벤치마크 실패를 설명하는 시도까지 존재 |
| 민감도 분석, influence function | 입력 섭동의 출력 영향. C1은 **특정 상류 표현 변화 방향**에 한정 |
| 맹목 신호 분리 식별가능성 | 유사한 rank/uniqueness 논의 |

**수학적 내용은 초등적이다.** column space 정사영과 NNLS의 KKT 조건이며 새로운 정리가 없다.

### 9.1.1 τ_col은 data resolution matrix의 방향별 Rayleigh 몫이다

선행 조사에서 확인된 사실이며, **논문에서 반드시 먼저 밝혀야 한다.** 숨기면 심사에서 치명적이다.

선형 역문제 `y = A a`에서 고전적 resolution 해석은 두 행렬을 쓴다.

```text
model resolution   R_model = A⁺A = V_r V_rᵀ    (K×K)  어떤 계수 조합이 복원되는가
data  resolution   R_data  = A A⁺ = U_r U_rᵀ   (T×T)  range(A) 로의 정사영
```

`P_col(A) = U_r U_rᵀ = R_data`이고 `P`는 직교 정사영이므로 `Pᵀ P = P`다. 따라서

```text
τ_col = ||P_col(A) d||² / ||d||² = dᵀ R_data d / dᵀ d
```

즉 **τ_col은 새로운 양이 아니라 data resolution matrix를 방향 `d`에서 평가한 Rayleigh 몫이다.**
이 대상은 1968–1972년에 확립되었다.

**남는 차이 (정직한 크기)**

| 항목 | 실제 증분 |
|---|---|
| `τ_act` (활성집합 부분행렬) | NNLS 특유이나 **활성집합 조건부 섭동 해석 자체는 기존 문헌에 있다**(§9.1.3). 이론 신규성이 아니라 **공학적 정식화**로만 제시한다 |
| 적용 대상 | 고전 문헌은 물리 역문제의 해상도 평가. C1은 **학습된 표현과 고정 prior 기반 dictionary의 합성**에 적용. 문제 전이(transfer) |
| 용도 | 해상도 보고가 아니라 **상류 표현 개선의 해석 가능성 관문**으로 사용 |
| 실증 | dictionary가 데이터 추정이 아니라 **문헌 prior로 생성**되어 rank가 붕괴하고, site의 약 46%에서 추정기가 데이터의 함수조차 아니라는 도메인 발견 |

**따라서 C1의 위치를 조정해야 한다.** "새로운 진단 지표"가 아니라 **"확립된 resolution 해석을 표현
학습–고정 dictionary 합성 문제로 전이하고, 그 렌즈로 도메인 병리를 정량화한 분석 기여"**다. 이론
신규성은 사실상 없다.

### 9.1.2 C1의 개념적 주장도 ML 쪽에 선행 연구가 있다

τ라는 **양**만 선행 연구가 아니다. "상류 표현 품질이 고정 하류 추정기로 전달되지 않을 수 있다"는
**개념적 주장 자체**가 표현학습 문헌에 이미 있다.

| 선행 연구 | C1과의 관계 |
|---|---|
| **objective function mismatch / metrics mismatch** (Neural Comput. Appl. 2022) | pretext 과제의 성공이 target 과제 성능을 **해칠 수 있다**는 것을 정식 지표로 정의. C1의 전제와 동일한 명제 |
| SSL 평가 프로토콜 벤치마킹 (IJCV 2025 등) | linear/kNN probing이 하류 성능을 얼마나 예측하는지 체계적으로 측정. 표현 품질 지표와 하류 성능의 괴리가 확립된 관찰 |
| **"Frozen but Not Always Accessible" (arXiv 2026-08, genomic LM)** | **가장 가깝다.** frozen 표현에 국소 생물 신호가 **존재하지만 readout으로 접근되지 않는다**는 것을 layer-wise probing·in-silico mutagenesis·embedding geometry로 보임. 생물 도메인, 같은 달 공개 |
| 표현 평가 프레임워크 (arXiv 2505.06224) | downstream probing이 잠재공간의 내재 구조를 드러내지 못한다는 문제의식 |

즉 **"보이지 않을 수 있다"는 발견은 신규가 아니다.** C1이 남길 수 있는 차이는 그 현상을 **닫힌 형태의
기하 조건으로 귀속**시키는 것(고정된, prior로 생성된 dictionary의 열공간)이지, 현상의 발견이 아니다.

### 9.1.3 조사 후 C1의 정직한 잔여 기여

| 요소 | 선행 연구 상태 | 잔여 |
|---|---|---|
| `τ_col` 이라는 양 | **선행 연구 있음.** data resolution matrix (1968–1972) | 없음 |
| "표현 품질이 하류로 전달되지 않는다"는 현상 | **선행 연구 있음.** objective function mismatch, accessibility | 없음 |
| `τ_act` — 활성집합으로 제한한 resolution | **거의 없음.** 저의 2회 조사는 NNLS **알고리즘** 문헌만 찾았으나, 외부 검토가 인접 문헌을 지목했다 — active set·nonsmoothness·sensitivity(SIAM), parametric QP/NNLS. 활성집합 조건부 섭동 해석은 낯선 방법론이 아니다 | **이론 신규성을 걸면 위험** |
| prior 기반 dictionary의 rank 붕괴가 전달 실패의 기전이라는 실증 | 도메인 특수 | **실재. 가장 방어 가능** |
| site 약 46%에서 추정기가 데이터의 함수조차 아니라는 감사 결과 | 도메인 특수 | **실재. 논쟁 불가능** |

**결론: C1을 "중심 기여"로 유지하는 것은 방어 가능하지 않다.** 남는 무게는 τ가 아니라 도메인 실증에
있고, 그것은 방법 기여가 아니라 감사·특성화 기여다. 재배치는 §9.5에 확정했다.

**τ_act 추가 조사는 time-box를 둔다.** 목적은 신규 수학임을 입증하는 것이 **아니라**, 알려진
활성집합·parametric NNLS 민감도와의 관계를 정확히 인용해 **과대주장을 제거**하는 것이다. 조사 후
안전한 위치는 둘 중 하나다.

```text
가까운 선행식이 발견되면   → τ_act 를 생물 도메인 구현 진단·감사 결과의 일부로 남긴다
충분히 직접적인 선행식이 없어도
                          → "active-set-restricted resolution diagnostic" 이라는
                             공학적 정식화로 제시하고 형식적 이론 신규성은 주장하지 않는다
```

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

정직한 위치: 중간 정도. **C2에 흡수될 위험**이 있고 E11(구 E10)이 그것을 판정한다(§7.5).

### 9.4 C0 — 관련 연구와 실제 신규성

인코더 아키텍처는 신규성이 없다. 그러나 **다시점 마스킹의 대수적 누출**과 그것을 잡아낸 잡음 대조는
실질적 방법론 기여다. 한 view만 가리면 다른 view가 동일 measurement pair에서 값을 복원하므로 순수
잡음에서 R²=1.0이 나온다는 것은 이 분야가 빠지기 쉬운 함정이다.

정직한 위치: 단독 논문은 어렵지만 **더 큰 작업의 방법 섹션으로는 견고**하다.

### 9.5 종합

~~강점은 **C1 + C0 + 통합 논제 + 정직한 부정 결과**다. C2·C3은 보조 기여로 배치하는 것이 실제 무게에
맞다.~~

**2026-08-21 선행 조사로 이 배치가 무효화되었다.** §9.1.1–9.1.3에서 τ라는 양과 "전달되지 않는다"는
현상 모두 선행 연구가 확인되었다. C1을 중심에 둘 수 없다.

**2026-08-21 외부 검토 반영 후 확정 구조.** 저의 초안은 "C2+C3을 중심으로"였으나 검토에서 기각되었고
수용한다. **증거가 있는 것(C0, 감사, C1)에서 증거가 없는 두 방법으로 무게를 전부 옮기면 위험이 C1에서
C2/C3 동시 성공으로 단순 이동할 뿐이다.** 합리적 거래가 아니다.

```text
논제: 구조적 결측 하의 신뢰 가능한 시간 PTM 표현과, 감사 가능한 하류 추론

Chapter 1  누출 저항 표현 평가                                    (C0)  구현·실측 완료
Chapter 2  배포 감사 — 구조적 무반응성과 prior 주도 비식별성        (감사) 실측 완료
Chapter 3  Coverage 분리 표현 학습                                (C2)  **한계 기술 장으로
                                                                        확정 (2026-08-21).
                                                                        방법 장 아님**
Chapter 4  비교가능성 제약 학습                                    (C3)  **한계 기술 장으로
                                                                        확정 (2026-08-22).
                                                                        독립 장 아님**
Chapter 5  기하 조건부 전달 진단 (τ_act)                           (C1)  해석·감사 도구.
                                                                        새 역문제 이론 아님
```

| 요소 | 위상 | 조건 |
|---|---|---|
| C0 + 감사 + C1 | **증거 있는 foundation.** 지금 확정 | 없음 |
| C2 | ~~조건부 중심 방법~~ → **한계 기술 장 (2026-08-21 확정)** | §6.3 인증서 **미충족.** E4 에서 λ\* 없음 |
| C3 | ~~독립성 확인 전 보조 모듈~~ → **한계 기술 장 (2026-08-22 확정)** | E11 이 흡수도 독립도 아닌 **적대**로 해소. E12 에서 반증 조건 4 발동 |

**C2 의 위상이 2026-08-21 에 확정되었다.** E4/E5/E6 를 사전등록된 규칙대로 실행한 결과
λ\* 가 존재하지 않아 §6.3 인증서가 충족되지 않았다(`c2_prereg_v1.md` §6.1, §8.1, §13.1).
**조건부 승격의 조건이 부정적으로 해소되었으므로 C2 는 방법 장이 아니다.** 남는 내용은
`c2_prereg_v1.md` §13.2 의 네 가지이며 그것으로 한계 기술 장을 구성한다.

```text
실패의 구조   coverage 축은 해결되었다   induced R² 0.564 → 0.042, 유효 rank 유지
              국소 성분이 남는다         kNN 회수율 0.625 → 0.513 (−17.9% 뿐)
              ARI 축은 arm 문제였다      arm D 의 출발점 0.036. A 0.162 · B 0.248 · E 0.974
```

**"교환이 근본적"이라고 서술하지 않는다.** §6.1 의 실측은 coverage 축이 해결 가능함을 보였고,
막힌 것은 마스킹 하 군집 안정성이다. 이 구분을 흐리면 §2.1 의 4-arm 관찰을 오독하게 된다.

**arm E 에 대한 실행은 사전등록되지 않았다.** E 가 (a) 에 가장 가깝지만(ARI 0.974,
induced R² 0.273 — 임계 초과분 0.023), 결과를 본 뒤 대상 arm 을 바꾸는 것은 사후 선택이므로
그 실행은 **탐색적이며 primary 승격이 영구 금지된다**(`c2_prereg_v1.md` §6.2·§11).

**C3 의 위상이 2026-08-22 에 확정되었다.** E9 는 사전등록된 §5.3 다섯 조건을 λ=1.0, `T_min`=4 에서
**전부 통과**했다. 그런데도 독립 장이 되지 못한 이유는 통과의 **폭**이다.

```text
λ 의존        개선은 λ=1.0 에서만.  λ=0.3 은 악화(CI 전부 양수), λ=3.0 은 CI 가 0 포함
T_min 의존    G2 가 T_min=4 에서만 통과.  T_min=3 은 0.1251, T_min=5 는 0.2660 (임계 0.50)
              → 반증 조건 4 발동 → 일반성 주장 철회
C2 와 적대    C2+C3 가 C2 단독보다 유의하게 나쁨 (λ=0.50 에서 +0.0777~+0.1105)
              동결 규칙이 열거한 "독립/흡수" 어느 쪽도 아닌 제3 분기
기준선 대비   C3 단독 vs arm D 는 CI 가 0 포함 — "현행 표현을 개선한다"가 성립하지 않는다
```

**"C3 가 실패했다"고 쓰지 않는다.** primary 는 통과했고 통과 사실은 그대로 보고한다. 철회되는 것은
**일반성**이며, 유일한 통과 조합("λ≈1, `T_min`=4, C2 없이, 대조 손실을 이미 쓰는 경우")은 처방이
아니다(`c3_prereg_v1.md` §11·§17).

**Chapter 2를 단순 동기 부여로 두지 않는다.** "46%"는 headline 관찰이고, 장의 기여는 프로토콜로
정의한다.

```text
detect → characterize → reproduce → guard → regression-test
```

재현 가능한 감사 프로토콜, 유병률 추정, 정확한 코드 계보, 회귀 테스트, 완화·guard ablation이 있으면
**경험적 시스템·신뢰성 장**이 된다. 단일 파이프라인 사례로 일반적 CS 방법 주장을 하면 약하다.

**2026-08-21: 5단계 전부 실행 완료.** 상세는 `docs/chapter2_audit_protocol_v1.md`.

| 단계 | 산출물 | 상태 |
|---|---|---|
| detect · characterize | `docs/tmm_identifiability_diagnosis.md` | 2026-08-18 완료 |
| reproduce | 동결 fixture `workers/tests/fixtures/tmm_audit_v1/` (620KB, git 추적), DB 없이 재생 | 완료 |
| guard | `ptm_shared/tmm_attribution_guard.py`, 기본값 `off`로 배포 수치 불변(불일치 0건) | 완료 |
| guard ablation | 발표 기여 쌍의 **47.99%** 보류, kinase 163개 중 **74개**가 공유 증거 과반 상실 | 완료 |
| regression-test | `workers/tests/test_tmm_audit_protocol.py` 20개 (2026-08-22 writer 판별·층화 강건성 6개 추가) | 완료 |
| 원인 규명 | 오더 48 후보 87→29 = **writer 이원화** (§4.3). 층화로 `top1_from_prior`만 일반화됨을 확인 (§4.3.1) | 완료 |

**동결 과정에서 감사 입력의 표류가 드러났다.** 오더 48의 `kinase_activity_heatmap`이
2026-08-20 재실행으로 덮어써져(kinase 87→29, 공유 site 199→49) **2026-08-18 표는 복구
불가능하다.** 결론은 유지되거나 강해진다(identifiable 1.15%→0.69%, top-1 prior 유래
92.52%→94.14%). 이 사건 자체가 동결이 필요한 이유의 실증이며, 재실행이 설계행렬의 **열 집합
자체**를 바꾼다는 점에서 BLOCKER-F(후보 집합 오염 경로)와 같은 축에 있다.

**원인이 규명되었다 (2026-08-22, `chapter2_audit_protocol_v1.md` §4.3).** LLM 예측 변화도 KEA3
응답 변화도 설정 변경도 아니었다 — `kinase_activity_heatmap`에 **후보 어휘가 다른 writer가 둘**
있고(api-server 엔드포인트는 비우세 클러스터를 `_c{n}` 별도 후보로 발행, 파이프라인 worker는
발행하지 않음), 재실행이 오더 48의 endpoint-writer 상태를 pipeline-writer 상태로 교체했다.
6 오더에서 writer 판별과 접미사 변종 유무가 **완전히 일치하며 반례가 없다.** 즉 후보 집합은
데이터의 함수가 아니라 **마지막에 그 행을 쓴 코드 경로의 함수**였다.

규명 과정에서 더 큰 문제가 드러났다(§4.3.1). 동결 fixture 재생을 오더별로 층화하면 공표 비율
중 **`top1_from_prior_rate`만 오더에 걸쳐 좁고**(0.9048–1.0000, 폭 0.095) 나머지는 폭이
0.31–0.45이며 오더 36(site 78.2%)이 통합값을 정한다. 따라서 Chapter 2의 헤드라인 주장은
"top-1 kinase는 데이터가 아니라 prior에서 나온다"로 좁혀야 하며, 95.26%·46.29% 같은 통합
유병률은 **오더별 범위를 병기해야** 쓸 수 있다.

C3의 강등 경로를 **지금 논문 outline에 적어 둔다.** 그러면 C3의 부정 결과가 논문 실패가 되지 않는다.

C1의 신규성 방어는 §9.1의 논변만으로는 부족하고 **E1–E3의 실증에 달려 있다.**

| C1 실험 | 성공 기준 | 실패 시 해석 |
|---|---|---|
| E1 exact-`H` τ 감사 | rank·duplicate·fallback provenance와 함께 τ 계산 가능 | 진단 구현 자체가 불완전 |
| E2 dictionary intervention | prior-free / KSA 변경이 사전 지정 geometry 지표와 τ를 예측 가능하게 변화시킴 | τ는 `H` geometry의 설명변수가 아님 |
| E3 out-of-sample 예측 타당도 | **held-out** 블록에서 high-τ / low-τ가 관측된 `Δẑ`를 구별 | τ는 서술 통계에 그침 |
| E3b 기전 양성 대조 | rank 조작에 τ가 예측 방향으로 반응 | 진단 민감도 미증명 |

E1·E2가 성공하고 E3가 실패하면 C1은 "관찰"이지 "도구"가 아니다. 그 경우 §0.1.1의 강등 경로를 따른다.

**갱신 (2026-08-22) — E3는 실패한 것이 아니라 평가 자체가 불가능하다.** τ를 계산하기 전에
사전등록이 요구한 모집단 측정(`c1_prereg_v1.md` §3.2)을 수행한 결과 **세 확장 수준 전부가
검정력 하한에 미달했다.**

| 수준 | 정의 | `S-EVAL` | adapter 교집합 후 | 임계 73 |
|---|---|---:|---:|---|
| L1 | HIRc-B 확증 universe | ≤ 63 | **≤ 58** | 미달 |
| L2 | HIRc-B 전체 (500 site) | 63 | **58** | 미달 |
| L3 | 동결 6 오더 pool (1,160 site) | 92 | **66** | 미달 |

E3의 실패 조건("τ가 서술 통계에 그침")이 성립한 것이 아니라 **E3를 돌릴 표본이 없다.** 두 상황은
논문에서 다르게 서술된다 — 전자는 τ에 대한 부정 증거이고 후자는 **증거 부재**다.
대응 분기는 `c1_prereg_v1.md` §3.5에 (i) 강등 / (ii) 새 데이터 요건 선언 / (iii) 탐색적 7 오더 pool
로 열거했다.

동시에 §2.1의 정렬 5지점이 전부 해소되었고, 여섯 번째 지점(A6, form 값 집계 비대칭)이 새로
발견되어 실측으로 무해함이 확인되었다(`c1_alignment_check_2026-08-21.md` §7·§8).
따라서 **τ 자체는 계산 가능하다.** 막힌 것은 τ의 계산이 아니라 τ의 **예측력 검정**이다.

### 9.7 C1 확정 (2026-08-22) — 분기 (i)+(iii) 수행 완료

`c1_prereg_v1.md` §3.5.1에서 **(i) 강등 + (iii) 탐색적 7 오더 pool**을 τ 산정 전에 확정하고
E1·E1b·E2(축소)·E3(탐색적)·E3b를 수행했다. 전 결과는 그 문서 §10.1.

| 실험 | 결과 | C1에 대한 기여 |
|---|---|---|
| E1 | τ 산출 완료. `S-EVAL` 124 site에서 `τ_act` p50 = 0.386, p10 = 0.066 | **전달 실패가 실재한다** |
| E1b | `τ_act`는 사전 확정 기하 요약으로 OOF R² 0.125만 설명됨. `τ_col`은 0.552 | `τ_act`에 증분 정보 있음 |
| E2 (축소) | prior 열 제거 시 Δτ_act p50 = −0.038, p10 = −0.324 | dictionary 조작에 반응. 단 한 축만 |
| **E3** | **미평가.** 블록 하한(fold당 군별 5)이 5 fold 전부에서 발동 | 예측 도구 주장 불가 |
| E3b | I3 부호 일치 53/53, I4 113/124 (둘 다 p < 1e-8) | **diagnostic sensitivity 입증** |

**C1의 최종 주장 범위는 이것이다. 이 문장만 쓴다.**

```text
쓴다      "고정 하류 사전은 대부분의 site 에서 퇴화되어 있고(S-DEAD 39%, S-RANK1 49%),
          평가 가능한 계층에서도 상류 표현 변화의 전달 비율 τ_act 중앙값이 0.386 이다"
          "τ 는 설계 rank 조작에 예측된 방향으로 반응한다 (진단 민감도)"
          "τ 의 하류 민감도 예측 타당도는 이 코호트에서 평가할 수 없다 —
          유전자 블록 수가 사전 지정 하한에 미달한다"

쓰지 않는다  "τ 는 하류 민감도를 예측한다"       ← E3 미평가
            "τ 는 예측에 실패했다"              ← 증거 부재이지 부정 증거가 아니다
            "표현 학습이 귀속을 개선한다/않는다" ← 측정하지 않았다
```

**두 개의 새 방법론 관찰이 나왔고, 이것이 C1의 실질 기여다.**

1. **사전등록된 승격 규칙이 무정보 지표를 primary 로 만들 수 있다.** §4.2는 활성집합이 불안정하면
   (`> 0.30`) primary를 `τ_act`에서 `τ_col`로 옮기도록 정했다. 실측 불안정 비율은 0.460이라
   규칙이 발동했지만, `τ_col`은 이 코호트에서 포화되어 있다(`S-EVAL` p50 = 0.989, 여러 오더에서
   정확히 1.0). `K_i ≥ T`이므로 열이 `R^T`를 거의 span한다. **즉 후퇴 지점이 정보를 잃는 지표였고,
   그것을 규칙을 만들 때 알 수 없었다.** 규칙을 어기지 않고 두 값을 모두 보고하며 이 딜레마를
   기술한다.
2. **검정력 사전등록을 site 수로만 하면 블록 하한에 걸려 미평가가 된다.** §3.4는 `S-EVAL` site
   하한 73을 정했고 pool은 124로 이를 넘었다. 그러나 유전자 블록 교차적합(§7.2)의 fold당 군별
   최소 5 블록 규칙이 먼저 걸렸다(101 블록 → fold당 held-out 13–32, q20/q80 후 각 군 2–7).
   **클러스터 단위 추론을 쓰면 검정력 사전등록도 클러스터 수로 해야 한다.**

**부수 확인.** prior 열을 제거하면 `S-EVAL` 124 site 중 **49 site가 열을 전부 잃는다.** 즉
평가 가능 계층에서도 설계행렬 다수가 prior 유래이며, BLOCKER-E가 `S-EVAL`에 한정해 재확인되었다.

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
| gate 임계값 테스트 고정 | **구현 완료 (2026-08-22).** §8.2.1·§8.2.2. `layers.py` 단일 선언, 테스트 11건 고정, 이탈 시 production 강제 차단 |
| coverage adversary | **구현·실행 완료 (2026-08-21).** best-response 2-head. E4/E5/E6 실행. λ\* 미발견 → C2 는 한계 기술 장 (`c2_prereg_v1.md` §6.1·§8.1) |
| `O_ij` 학습 제약 | **구현·실행 완료 (2026-08-22).** `comparability.py`, `comparability_constraint.py`, `replicate_stratum.py`. E9–E12 실행. 회귀 46건. λ·`T_min` 의존으로 일반성 철회 (`c3_prereg_v1.md` §16·§17) |
| τ 측정 | **구현·실행 완료** (C1). `ptm_shared/c1_transmissibility.py`, `ptm_shared/c1_inference.py`, 회귀 테스트 35건 |
| 외부 데이터셋 일반화 | **미평가** |
| kinase 귀속 계층 (Core A/B) | **미구현.** C1의 분석 대상 |

---

## 11. 데이터 제약

리뷰 판단에 필요한 제약을 명시한다.

| 항목 | 상태 |
|---|---|
| 내부 시계열 데이터셋 | 이 규모의 paired control 시계열은 **HIRc-B 1건** |
| 내부 kinase 교란 데이터 | **없음.** 정량 matrix 보유 디렉터리 20개 = **원자료 획득 11건** 전수 조사 결과 적격 0건 (§11.1, 단위 규칙 §11.1.1, 결과 §11.1.2) |
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
n_distinct_experimental_units    = 11        # 2026-08-22 추가. 규칙 §11.1.1, 결과 §11.1.2
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

**실행 수 정정 (2026-08-22).** 아래 "실행 수" 열은 v2 감사(2026-08-20) 당시 **모든 행에서 정확히
1 만큼 과소**였다.

**원인이 규명됐다.** v2 감사의 실행 컬럼 판정식은 `\.(mzML|raw|d)$` 였다(`implementation_log.md`
2026-08-20 항목의 결정성). 그런데 matrix 는 CRLF 로 저장되어 헤더의 **마지막** 컬럼이
`...mzML\r` 로 끝난다. Python `$` 는 `\n` 앞에서는 매치하지만 `\r` 앞에서는 매치하지 않으므로
**모든 파일에서 마지막 run 컬럼 하나가 빠졌다.** 판정식을 그대로 재현하면 BIOEN 5, Insulin 20,
Universe_AF 8 — v2 표의 값과 정확히 일치하고, 개행만 제거하면 6·21·9 가 된다. 이 오류가 새 규칙에
재발하지 않는 이유는 §11.1.1 이 확장자 앵커 대신 경로 구분자 포함 여부를 쓰기 때문이며
`workers/tests/test_dataset_units.py` 가 그 경로를 잠근다.

정정은 교란 판정을 바꾸지 않는다(모든 행 "없음"). 실험에도 영향이 없다 — 표현 학습·C1–C3
파이프라인은 이 표를 읽지 않고 matrix 를 직접 읽는다. 대조 확인: Insulin 은 6 시점 × 3 replicate
+ control 3 = 21 이고 Universe_AF 는 3 조건 × 3 = 9 다. `단위` 열은 §11.1.2 의 획득 단위 번호다.

| 데이터셋 디렉터리 | 실행 수 | 단위 | 교란 탐지 | 판정 |
|---|---:|---:|---|---|
| BIOEN_phosphorylation | 6 | 1 | 없음 | 제외 |
| BioEN | 6 | 1 | 없음 | 제외 |
| BioEn_1 | 6 | 1 | 없음 | 제외 |
| Cu-Amyloid_fibril-microglia-phosphorylation | 18 | 2 | 없음 | 제외 |
| HM_Serum_free_phosphorylation | 12 | 3 | 없음 | 제외 |
| HM_palmitate_phosphorylation | 12 | 4 | 없음 | 제외 |
| HM_serum_phosphorylation | 12 | 5 | 없음 | 제외 |
| **Insulin_Signaling_Phosphoproteomics_HIRc-B** | 21 | 6 | 없음 | 교란 제외 / **표현 학습 primary 채택** |
| Irisin_TimeCourse_Phospho | 29 | 7 | 없음 | 제외 |
| Irisin_TimeCourse_Phospho_qwen3.5_27b | 29 | 7 | 없음 | 제외 (동일 획득 확인) |
| Irisin_Ubiquitylation_Report | 29 | 7 | 없음 | 제외 (동일 획득 확인) |
| Irisin_Ubiquitylation_Report_1 | 29 | 7 | 없음 | 제외 (동일 획득 확인) |
| KRIBB_HSC_ubiquitylation | 15 | 8 | 없음 | 제외 (동일 획득 확인 — 명칭의 HSC/SCS 는 획득 차이가 아니다) |
| KRIBB_SCS_Phosphorylation | 15 | 8 | 없음 | 제외 |
| Korea_Ubiquitylation_Timecourse | 12 | 9 | 없음 | 제외 (동일 획득 확인) |
| Korea_timecouse_drugrepositioning | 12 | 9 | 없음 | 제외 (명칭의 "drugrepositioning"은 보고 모드이며 처리 조건 아님) |
| Microgravity_Muscle_Atrophy_Phosphoproteomics | 12 | 9 | 없음 | 제외 (**오더 33 과 동일 획득 — §11.1.2**) |
| PTM-2026-0001 | 29 | 7 | 없음 | 제외 (동일 획득 확인) |
| Universe_AF | 9 | 10 | 없음 | 제외 |
| WithoutCu-AmyloidFibril-microglia-phosphorylation-1 | 18 | 11 | 없음 | 제외 |
| rag | — | — | matrix 없음 | 감사 범위 외 (문헌 코퍼스) |

**주의 — distinct 실험 수는 20보다 적다.** 실행 수와 명명이 동일한 항목들(BIOEN 계열 3건 n=5,
Irisin 계열 4건 n=28, Cu/WithoutCu 쌍, HM 계열 3건 n=11)은 동일 원자료의 재실행 또는 동일 연구의
조건 분할로 보인다. **논문 supplement에는 디렉터리 수가 아니라 distinct 실험 단위를 명시적으로
선언해야 한다.** 그 규칙과 결과는 §11.1.1 이다.

**HIRc-B paired-control 적격 정의.** feature별 paired control replicate 수로 층을 나눈다:
≥2 (확증, 2,420 feature) / 정확히 1 (sensitivity, 302) / 0 (탐색, 313).

### 11.1.1 distinct 실험 단위 — 동치 규칙 (측정 전 선언)

**declared 2026-08-22, 측정 착수 전.** 디렉터리 수 20은 감사의 폭을 과대표시한다. §11.2의
"내부 데이터셋 20건 전수 감사, 적격 0건"에서 분모가 되어야 하는 것은 디렉터리가 아니라
**원자료 획득(raw MS acquisition)** 이다. 규칙을 결과를 보기 전에 고정한다.

**단위.** 실험 단위 = 하나의 원자료 획득. 디렉터리도, 오더도, 처리 실행도 아니다.

**식별자.** DIA-NN matrix의 run 컬럼명은 획득 파일의 전체 경로다
(예: `C:\Users\admin\Desktop\BIOEN\DIA_mzML\20250707_YWNa_DIA115min_control_1.mzML`).
디렉터리 `d`의 원자료 집합 `R_d` = 그 디렉터리 `report.pr_matrix.tsv`의 run 컬럼명 집합.
경로 문자열을 정규화 없이 그대로 쓴다 — 정규화 규칙 자체가 판정을 흔들기 때문이다.

**동치 규칙.** 두 디렉터리 `d`, `e` 는 `R_d ∩ R_e ≠ ∅` 일 때 같은 획득에 속한다.
distinct 실험 단위 수 = **디렉터리를 정점, 원자료 공유를 간선으로 하는 그래프의 연결 성분 수.**
연결 성분을 쓰므로 추이성은 구성상 보장되며 병합 순서에 의존하지 않는다.

```text
R_d == R_e            → 동일 획득의 재처리 또는 바이트 단위 재실행
R_d ∩ R_e ≠ ∅ (부분)   → 한 획득의 조건 분할 또는 부분집합
R_d ∩ R_e == ∅        → 별개 단위
```

**규칙에 넣지 않은 것과 그 이유.**

| 후보 | 배제 이유 |
|---|---|
| 파일 sha256 동일성 | 동일 획득을 DIA-NN 설정만 바꿔 재처리하면 바이트가 달라진다. 단위는 획득이므로 판정 기준이 될 수 없다. **기술 통계로만 병기한다** |
| 디렉터리명 유사도 | `Korea_timecouse_drugrepositioning`처럼 명칭이 처리 모드를 담는 사례가 있다(§11.1). 명명은 증거가 아니다 |
| 실행 수(`n_runs`) 일치 | 무관한 두 실험이 같은 replicate 설계를 쓸 수 있다. 필요조건도 충분조건도 아니다 |
| 획득 디렉터리 경로 prefix | 한 폴더에 여러 실험을 담을 수 있고 한 실험을 여러 폴더로 나눌 수 있다. **기술 통계로만 병기한다** |

**해석 한계.** 이 수치는 감사의 폭을 정직하게 적기 위한 것이다. **적격 판정(§11.1의 교란 정의)을
바꾸지 않는다** — 적격 0건은 단위를 어떻게 세든 0건이다. 또한 획득이 하나라는 것이 생물학적
독립성이 하나라는 뜻은 아니다. 같은 세포주·같은 배치에서 나온 별개 획득은 별개 단위로 세어지며,
이 규칙은 그 상관을 보정하지 않는다.

**주장 금지.** 이 수를 근거로 표본 크기나 검정력을 논하지 않는다. 검정력 관련 모집단 정의는
`c1_prereg_v1.md` §6, `c3_prereg_v1.md` §9 에 별도로 선언되어 있다.

### 11.1.2 distinct 실험 단위 — 결과 (2026-08-22)

`scripts/audit_distinct_experimental_units.py`, 산출 `docs/results/dataset_audit/distinct_units_v1.json`.

```text
n_directories_scanned              = 21
n_directories_in_scope             = 20     # rag/ 만 제외. §11.1 의 20 과 일치
n_distinct_experimental_units      = 11     # ← supplement 에 선언할 수
n_distinct_raw_runs                = 164
n_raw_runs_summed_over_directories = 331    # 331 − 164 = 167 이 중복 계상분
```

**디렉터리 20개는 원자료 획득 11개다.** 디렉터리 수는 감사 폭을 1.8배 과대표시했다.

| 단위 | 관계 | 디렉터리 | 원자료 |
|---:|---|---|---:|
| 1 | 바이트 동일 재실행 | BIOEN_phosphorylation, BioEN, BioEn_1 | 6 |
| 2 | 단독 | Cu-Amyloid_fibril-microglia-phosphorylation | 18 |
| 3 | 단독 | HM_Serum_free_phosphorylation | 12 |
| 4 | 단독 | HM_palmitate_phosphorylation | 12 |
| 5 | 단독 | HM_serum_phosphorylation | 12 |
| 6 | 단독 | **Insulin_Signaling_Phosphoproteomics_HIRc-B** | 21 |
| 7 | 동일 획득 재처리 | Irisin_TimeCourse_Phospho, Irisin_TimeCourse_Phospho_qwen3.5_27b, Irisin_Ubiquitylation_Report, Irisin_Ubiquitylation_Report_1, **PTM-2026-0001** | 29 |
| 8 | 동일 획득 재처리 | KRIBB_HSC_ubiquitylation, KRIBB_SCS_Phosphorylation | 15 |
| 9 | 동일 획득 재처리 | Korea_Ubiquitylation_Timecourse, Korea_timecouse_drugrepositioning, **Microgravity_Muscle_Atrophy_Phosphoproteomics** | 12 |
| 10 | 단독 | Universe_AF | 9 |
| 11 | 단독 | WithoutCu-AmyloidFibril-microglia-phosphorylation-1 | 18 |

단위별 원자료 수의 합 164 는 `n_distinct_raw_runs` 와 일치한다(성분 간 교집합 없음의 확인).

**§11.1 의 추정이 틀린 지점 세 곳.** 그 항의 "주의" 문단은 네 묶음을 추측했는데 실측과 다르다.

```text
Irisin 계열 4건        →  5건.  PTM-2026-0001 이 같은 획득이다
Cu/WithoutCu 쌍        →  별개 단위 2개.  획득 디렉터리는 같으나 원자료 집합이 서로 소다
                          (Fibril-Cu_* 18개 대 Fibril_* 18개, 교집합 0)
HM 계열 3건            →  별개 단위 3개.  획득 폴더만 공유하고 원자료가 다르다
(추측에 없던 것)        →  Korea 2건 + Microgravity 가 한 획득. 아래 참조
```

**가장 파급이 큰 발견 — 디렉터리명이 획득을 말해 주지 않는다.**

```text
Korea_timecouse_drugrepositioning  ≡  Microgravity_Muscle_Atrophy_Phosphoproteomics
    원자료 12개가 완전히 동일 (교집합 12/12). 획득 폴더 Kim HyunSu_MicroGravidy_Time_Course
KRIBB_HSC_ubiquitylation           ≡  KRIBB_SCS_Phosphorylation
    원자료 15개가 완전히 동일. 명칭의 HSC/SCS 는 획득 차이가 아니다
```

§11.1.1 이 디렉터리명 유사도를 판정에서 배제한 결정이 실측으로 정당화된다. 이름이 서로 무관해
보이는 두 쌍이 동일 획득이고, 이름이 유사한 Cu/WithoutCu 는 별개 획득이다.

**Chapter 2 감사 오더 6건은 획득 5개다.**

| 오더 | 디렉터리 | 단위 |
|---:|---|---:|
| 28 | Irisin_TimeCourse_Phospho_qwen3.5_27b | 7 |
| 33 | Korea_timecouse_drugrepositioning | **9** |
| 36 | KRIBB_SCS_Phosphorylation | 8 |
| 45 | Microgravity_Muscle_Atrophy_Phosphoproteomics | **9** |
| 47 | WithoutCu-AmyloidFibril-microglia-phosphorylation-1 | 11 |
| 48 | Cu-Amyloid_fibril-microglia-phosphorylation | 2 |

오더 33 과 45 는 같은 획득이다. 감사 표(`chapter2_audit_protocol_v1.md` §3)의 통합 서술에
반영해야 한다 — 그 항의 처리는 해당 문서 §3.4·§8 이다.

**민감도 — 획득 경로로 묶으면 8 단위.** HM 3건과 Cu/WithoutCu 쌍이 합쳐진다. §11.1.1 이 경로
prefix 를 판정에서 배제했으므로 **8 은 선언 값이 아니다.** 병기하는 이유는 선언 규칙이 배치
상관을 보정하지 않음을 드러내기 때문이다. 즉 **획득 수준 독립성은 11 이고 배치 수준 독립성은
8 이 상한**이며, supplement 에는 11 을 선언하고 이 문장을 함께 적는다.

**정합성.** pg/pr run 집합 불일치 0, run 컬럼 중복 0, 경로 아닌 run 영역 컬럼 0,
precursor matrix 복수 보유 0.

### 11.2 검증 범위와 그 결과 (Validation scope and consequence)

> 사전 지정된 kinase 교란 정의(선택적 억제제, siRNA, CRISPR/KO, 또는 짝지어진 vehicle/control)로
> 정량 matrix를 보유한 내부 데이터셋 디렉터리 20건 — **원자료 획득 11건** (§11.1.1 의 동치 규칙,
> §11.1.2 의 결과) — 을 전수 감사한 결과 적격 데이터셋은 **0건**이었다. 사용 가능한 paired-control
> 시계열은 HIRc-B 1건에 한정된다.
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

**(1) C1의 신규성이 방어 가능한가. — 질문이 더 날카로워졌다.** 선행 조사에서 `τ_col`이 선형 역문제의
**data resolution matrix의 방향별 Rayleigh 몫과 수학적으로 동일**함을 확인했다(§9.1.1). 즉 이론
신규성은 없다. 남는 것은 (a) `τ_act`의 활성집합 증분, (b) 표현학습–고정 dictionary 합성 문제로의 전이,
(c) prior 기반 dictionary의 rank 붕괴라는 도메인 실증이다.
**이 세 가지로 학위논문의 중심 기여가 되는가, 아니면 C1을 보조 기여로 내리고 다른 축을 중심에 두어야
하는가.** 이것이 현재 가장 중요한 미해결 질문이다.

**(2) 부정 결과를 주 결과로 삼을 수 있는가.** ~~"상류 표현 개선이 하류로 전달되지 않는다"를 주 결과로
제시할 때 무엇이 더 필요한가. positive counterpart가 반드시 필요한가.~~
**→ 외부 검토에서 답을 받았다.** 필수는 아니나 있으면 훨씬 강해지며, **생물학적 truth 없는 기전 양성
대조로 충분하다.** dictionary intervention에서 τ가 오르고 `Δẑ`가 예측대로 반응하면 diagnostic
sensitivity proof로 유효하다(귀속 정확도 증명으로는 무효). §5.5.2 E3b로 설계에 반영했다.

**(3) 통합 논제가 학위논문 척추로 충분한가.** "표현과 귀속은 함께 설계되어야 한다"는 명제가 기여 4건을
묶는 축으로 충분한지, 아니면 각 기여가 독립적으로 평가되어 개별 무게 부족으로 판정될 위험이 큰가.

**(4) C2의 인증서 수준.** ~~예측기族에 대한 경험적 검증(§6.3 (c))으로 충분한가, 형식적 상한이 필요한가.~~
**→ 측정이 질문을 바꿨다 (2026-08-21).** 경험적 검증은 충분히 엄격했다 — 오히려 **gate 가 느슨했다.**
표본 내 선형 gate 는 `latent_dim=8` 에서 0.462 → 0.086 으로 통과하는데 같은 임베딩의 kNN 회수율은
0.625 → 0.598 로 사실상 불변이다(`c2_prereg_v1.md` §10.5). 남는 질문은 §10.5 의 이 취약점이
**C0 gate 자체의 결함으로 논문에 기록되어야 하는가**다.

**(5) C3을 유지할 것인가.** ~~E11(구 E10)에서 C2에 흡수될 위험이 있다.~~
**→ 측정으로 해소 (2026-08-22).** 흡수가 아니라 **적대**였다. 강등은 흡수 때문이 아니라 E12 의
`T_min` 뒤집힘 때문이다(§9.5).

**(6) 기여 4건이 과다한가.** ~~§9.5의 배치(C1·C0 주, C2·C3 보조)가 타당한가.~~
**→ 질문이 역전되었다 (2026-08-22).** 이제 방법 장은 **0건**이고 특성화 장이 3건이다. 질문은
"과다한가"가 아니라 **"부족한가"**다 (`external_review_request_2026-08-22.md` §2).

**(7) 단일 cohort + 외부 1건으로 일반화 주장이 성립하는가.** §11의 제약에서 어디까지 주장할 수 있는가.
**범위 축소 (2026-08-22).** 내부 디렉터리 20개는 독립 획득 **11건**이고 Chapter 2 의 6 오더는
독립 획득 **5건**이다(§11.1.2). 질문은 더 좁아졌다.

---

## 13. 미해결 항목

| 항목 | 상태 |
|---|---|
| gate 임계값 테스트 고정 | **해소 (2026-08-22).** 판정 임계 4개 + probe 설정 4개를 `layers.py`에 단일 선언, sha256 기록, 이탈 시 `production_influence_allowed` 강제 False. `seed` 는 `c2_prereg_v1.md` §1.3 집합 소속으로 검사. 테스트 11건 (§8.2.1·§8.2.2) |
| coverage adversary의 결정성 유지 | **해소 (2026-08-21).** best-response head 는 폐형 해라 반복 간 표류가 없다. RFF bandwidth 를 첫 호출에 동결해 gradient 정합성 확보. 유한차분 검증 + 회귀 테스트 통과 |
| C2 사전등록 (`c2_prereg_v1.md`) | **동결 완료 (2026-08-21).** 동결 전 측정 4건·임계 승인 3건 완료. adversary 미구현, E4–E8 미실행 상태에서 동결 |
| C2 예측기族의 tree 계열 부재 | **결정 완료.** scikit-learn 추가하지 않음. (c)의 주장 범위가 "선형·국소·매끄러운 비선형"으로 제한됨을 논문에 명시 (`c2_prereg_v1.md` §4.3·§14.3) |
| C2 induced 표적의 구조 | **측정 완료.** 표적은 3값(0: 30.4%, 1/6: 55.5%, 2/6: 14.1%)이며 R²는 주로 "마스킹 여부"를 설명한다. natural coverage 교란 우려는 기각(구조적 영값 66개, 2.4%) |
| C2 의 E8 veto 위험 | **해소 (2026-08-21).** E8 실행 결과 27 구성 전부 조건 (a) 실패 → **veto 발동하지 않음** (`c2_prereg_v1.md` §10.4). 다만 이후 E4 가 실패했으므로 이 해소는 무의미해졌다 — veto 는 방법이 성공했을 때만 의미가 있다 |
| **C2 인증서 충족 여부** | **부정적으로 해소 (2026-08-21).** E4 에서 λ\* 없음 → **C2 실패. 한계 기술 장으로 확정** (`c2_prereg_v1.md` §6.1·§13.1). 두 독립 원인: (a) 의 ARI 하위 조건(8 λ 전체 최대 0.066 대 임계 0.20)과 (c)(族 최대 ≥ 0.513 대 임계 0.25) |
| **coverage 인코딩의 국소성** | **발견 (2026-08-21, 사전등록된 E6).** 최적반응 adversary 가 매끄러운 성분을 전부 제거한 뒤에도 kNN 회수율이 0.513 으로 남는다(선형 0.024, 2차 0.094, RFF 0.216). **gradient reversal 로 닿지 않는 성분이 존재한다.** 남은 미결: 국소 성분을 겨냥하는 미분 가능한 penalty 가 있는가 |
| **arm D 의 마스킹 하 군집 취약성** | **재해석 (2026-08-22).** 2026-08-21 발견은 arm D 의 retention ARI 0.036 을 마스킹 취약성으로 읽었다. 그러나 arm D 는 **인코더 seed 만 바꿔도** 비교 가능 쌍 ARI 가 0.0237–0.0373, 전체 쌍 0.0427–0.0675 만 재현된다 — 즉 마스킹 전후 값이 seed 간 값보다 **낮다.** 취약한 것은 마스킹에 대한 강건성이 아니라 **군집 자체의 식별성**이다 (`c3_prereg_v1.md` §12.4·§12.6.1, `c2_prereg_v1.md` §13.3) |
| **arm D 임베딩 기하의 비식별성** | **발견 (2026-08-22, 탐색적).** seed 만 바꾼 두 적합에서 쌍거리 순위 일치도 0.0025–0.0056(행 표준화 인공물 아님: 원본 코사인 0.0023–0.0054), 열공간 정렬 0.178–0.195(무작위 기대값 ≈ 0.006). **부분공간은 부분적으로 재현되고 미세 기하는 재현되지 않는다.** 공정 프로브가 이와 양립하는 이유는 seed 5개를 평균하고 열공간에만 의존하기 때문 — 그러나 **군집 기반 지표는 전부 seed 평균 또는 상대 임계로만 해석해야 한다.** 미결: 이 비식별성이 `PRIMARY_ARM_PREFERENCE` 의 D 선택을 바꾸는가 (별도 사전등록 필요) |
| **`missingness_validity` gate 의 방법론적 취약점** | **발견 (2026-08-21, 탐색적).** gate 는 표본 내 선형 회귀만 쓰므로 **coverage 인코딩을 제거하지 않고 비선형화하는 것만으로 통과될 수 있다.** `latent_dim=8` 에서 gate 지표 0.462 → 0.086(5.4배 감소)인데 kNN 회수율은 0.625 → 0.598(변화 없음). (a)의 R² 조건과 (b)를 동시에 만족하며 (c)를 크게 위반하는 구성이 실재 (`c2_prereg_v1.md` §10.5) |
| **gate 지표가 회수 가능성을 과소평가** | **측정 완료.** gate의 P1(표본 내 선형) 0.462 대 예측기族 최대(kNN) 0.625. **kNN 회수율은 latent_dim·l2·input_mask_fraction 에 거의 불변(0.598–0.625).** C2가 넘어야 하는 값은 0.625다 (`c2_prereg_v1.md` §4.1.1·§10.5) |
| C2 공표 gate 수치의 단일 seed 의존 | **해소.** 5 seed 측정 결과 induced R² 중위수 0.564이며 **공표된 0.462는 5개 중 최솟값**이었다. 다중 seed 규칙으로 판정 (`c2_prereg_v1.md` §1.3) |
| E1b 판별력 판정 기준 / E3 블록 분할 / τ 임계·aggregation·출력 통계량 | **해소. `c1_prereg_v1.md` 동결 (2026-08-22).** 선행 확인 4건 완료 → §3.5.1 분기 (i)+(iii) 확정 → §10.1 실측 기록. 회귀 테스트 35건이 임계를 잠근다 |
| 인코더 출력 열공간과 NNLS 조건 공간의 정렬 | **해소 (2026-08-22).** 5지점 중 3지점이 실측으로 소멸 — A3(control 없음), A4(수열 이미 일치), A1·A5(form·site 수준의 고유 site 집합이 모두 2,377). 집계 규칙은 **`A2 = SITE_LEVEL_ENCODER_V1`** 로 확정되어 집계 함수 자체가 불요. 남은 것은 §2.1.3 결측 비대칭이며 해소 대상이 아니라 병기 대상 |
| **`S-EVAL` 계층 크기** | **측정 완료 (2026-08-22). 세 수준 전부 미달** — L1 ≤ 58, L2 = 58, L3 = 66 대 임계 73. 탐색적 7 오더 pool 은 124. **τ 는 계산되었고**(§9.7) **E3 primary 는 평가 불가.** 추정 범위 0–597 의 하단에 가깝다 |
| **C1 모집단 미달에 대한 분기 선택** | **결정 완료 (2026-08-22, τ 산정 전). (i) 강등 + (iii) 탐색적 7 오더 pool.** C1은 특성화 장이며 E3는 primary에서 내려갔다. 수행 결과는 §9.7 |
| **E3 가 탐색적으로도 평가 불가** | **발견 (2026-08-22).** `S-EVAL` 124 site는 site 하한 73을 넘었으나 **유전자 블록 101개가 fold당 군별 5블록 하한에 걸려 5 fold 전부 non-evaluable.** §7.2가 대체 분할 탐색을 금지하므로 미평가로 종결. **교훈: 클러스터 단위 추론을 쓰면 검정력 사전등록도 클러스터 수로 해야 한다** (`c1_prereg_v1.md` §10.1.3) |
| **§4.2 τ 승격 규칙이 무정보 지표를 primary 로 만듦** | **발견 (2026-08-22).** 활성집합 불안정 비율 0.460 > 0.30 → 사전등록대로 primary가 `τ_col`로 이동. 그러나 `τ_col`은 `K_i ≥ T` 때문에 포화(`S-EVAL` p50 = 0.989, 다수 오더에서 1.0)되어 site를 구별하지 못한다. E1b OOF R²도 `τ_act` 0.125 대 `τ_col` 0.552로 **더 중복된 지표로 이동**. 규칙을 어기지 않고 두 값을 병기하며 딜레마를 기술 |
| A6 — form 값 집계 비대칭 | **해소 (2026-08-22).** NNLS는 last-wins, 인코더는 mean이라 `d`에 집계 차이가 섞일 수 있었다. 실측 `||mismatch|| / ||d_obs||` p50 ≈ 1e-16 으로 부동소수점 수준. `c1_prereg_v1.md` §2.2의 τ 성분 (3)은 **측정해서 배제** (`c1_alignment_check_2026-08-21.md` §7) |
| **`S-EVAL` 에서도 설계행렬이 prior 지배** | **측정 완료 (2026-08-22).** prior 열 제거 시 `S-EVAL` 124 site 중 **49 site가 열을 전부 잃는다**(18 site는 애초에 prior 열 없음). 실제 비교 가능한 것은 57 site. BLOCKER-E를 평가 가능 계층에 한정해 재확인 |
| **오더 간 `S-EVAL` 편차** | **발견 (2026-08-22).** 0.0%(WithoutCu-AmyloidFibril, 86 site 전부 미달)~33.3%(Microgravity). **pool 요약을 오더별 표 없이 보고하지 않는다.** 원인 미규명 — 후보 수·시점 수·사전 열 비중 중 무엇이 지배적인지. **범위 축소 (2026-08-22):** L3 의 6 오더는 독립 획득 5건이고 편차 상단인 Microgravity(오더 45)는 오더 33 과 동일 획득이다(§11.1.2). 따라서 이 편차를 "데이터셋 간"이라 부를 수 없고 후보 요인에 **재처리 차이**가 추가된다 (`c1_prereg_v1.md` §3.1.1 관찰 3) |
| **프로브 분할 결정성** | **해소 (2026-08-22).** `fair_probe.py` 의 분할 seed 가 `hash(arm)` 이어서 프로세스마다 달랐다(`PYTHONHASHSEED` 미설정). `crc32` 로 교체하고 회귀 테스트로 고정. **수정 이전 프로브 절대값은 이후 값과 비교 불가**이며 실행 간 흩어짐은 폭 0.0032 (`c2_prereg_v1.md` §12.1) |
| **C0 공표 프로브 표의 설정 출처** | **확정 (2026-08-22).** `key_level="site"`, `eligible_subset()` **미적용**(2,447 site), epochs 300, arms (A,B,D,E) → ΔR² = 0.02681 로 공표값 0.0271 재현. 차원 4개 일치, B·D·E 평균 R² 소수 4째 자리 일치 (`c2_prereg_v1.md` §7.2.2) |
| **C3 판정 규칙·임계·모집단** | **해소. `c3_prereg_v1.md` 동결 (2026-08-22).** §12 실측 4건(결합률 1.0000, `n_eff` 995.2, 기저 FM_precision 0.1042, 잡음 하한 0.0237)이 §13 미결 5건을 닫았다. 초안 G1 은 기각되고 G1a+G1b 로 대체. G2 는 병합 쌍 비율에서 제거 표적성으로 교체. 회귀 20건 |
| **기존 표현 학습 수치가 계산된 계층** | **발견 (2026-08-22).** 표현 입력의 `observed` 가 run 수준 `replicate ≥ 1` 과 0.012% 만 다르다. 즉 **C0 gate·공정 프로브·C2 E4–E8 은 전부 `rep≥1` 계층에서 계산되어 있다.** §7.3 의 `rep≥1` 금지는 pair 수준 false-merge 검정에 대한 것이어서 site 수준 예측 지표를 무효화하지 않으나, **논문에서 그 계층을 명시해야 한다** (`c3_prereg_v1.md` §11.1) |
| 내부 데이터셋 distinct 실험 단위 수 | **해소 (2026-08-22).** 동치 규칙을 측정 전 선언(§11.1.1: 원자료 공유 그래프의 연결 성분) 후 측정 → 디렉터리 20개는 **획득 11건**(§11.1.2). 배치 수준 상한은 8. §11.1 의 추측 3곳이 틀렸고 특히 **오더 33·45 가 동일 획득**임이 드러났다. §11.1 표의 실행 수는 전 행 +1 과소였고 정정했다 |
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
