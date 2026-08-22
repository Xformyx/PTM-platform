# PTM Representation Learning Contract v1

작성일: 2026-08-17 (GMT+9)
구현 근거: `PTM_Vector_Representation_Learning_Full.pdf`, `docs/attached_representation_learning_proposal_integration_review.md`
상태: **R0/R1/R1.5 구현 완료 — R2 이상은 gate 통과 전까지 production 미반영**
Contract version: `ptm_representation_contract.v1`

## 1. 핵심 원칙

현재 PTM Vector를 **대체하지 않는다.** 두 층이 병렬로 실행되고, 합의와 불일치를 기록한다.

```text
PR / PG / FASTA
        ↓
existing preprocessing and dual-track quantification   ← 변경 없음
        ↓
L1 Quantitative PTM Feature Vector                     ← 변경 없음 (보존)
        ├──────────────────────────────────────┐
        ▼                                      ▼
L2 Track 2 temporal trajectory          L3 multi-view encoder input
        ▼                                      ▼
canonical co-wave + raw Track 2 TMM     L4 learned temporal embedding
        │                                      │
        └────────── evidence concordance ──────┘
                          ↓
        original quantitative values explain the result
```

`create_ptm_vector_data()`는 없어지지 않고 **ML을 위한 feature engineering layer**가 된다.

## 2. 4개 representation 층 (명명 확정)

`ptm_shared/representation/layers.py`가 명명의 단일 출처다. `describe_contract()`로 기계 판독 가능한 형태를 얻는다.

| 층 | 명칭 (`name`) | `method_id` | 단위 | 산출물 | 해석 가능성 |
|---|---|---|---|---|---|
| L1 | `quantitative_ptm_feature_vector` | `L1_quantitative_ptm_feature_vector.v1` | site/form × timepoint | `ptm_vector_data_normalized{suffix}.tsv` | 높음 |
| L2 | `temporal_ptm_trajectory_vector` | `L2_temporal_ptm_trajectory_vector.v1` | site/form | in-memory | 높음 |
| L3 | `multiview_temporal_ptm_input` | `L3_multiview_temporal_ptm_input.v1` | site/form × timepoint × view | in-memory | 중간 |
| L4 | `learned_temporal_ptm_embedding` | `L4_learned_temporal_ptm_embedding.v1` | site/form | `ptm_representation_embeddings{suffix}.tsv` | 낮음 (raw evidence 역추적 필수) |

### 현재 방식의 보존 명명

**L1이 곧 현재 구현이다.** 비교분석 시 이 이름으로 인용한다.

- 명칭: **Quantitative PTM Feature Vector** (`quantitative_ptm_feature_vector`)
- 생산자: `PTMQuantificationAnalyzer.create_ptm_vector_data` (코드·컬럼·파일명 **무변경**)
- 레거시 별칭: `ptm_vector`, `ptm_vector_data_normalized`, `handcrafted_ptm_vector` → `resolve_layer()`가 모두 L1로 해석
- 논문 정의: *a structured feature representation assembled from protein-normalized modification changes, protein abundance changes, statistical evidence, and paired modified/unmodified measurements*

L4 정의: *a latent representation learned from quantitative PTM vectors across ordered timepoints and molecular context.*

`LAYERS`의 모든 층은 `replaces_lower_layers=False`이며, 테스트가 이를 강제한다.

## 3. Encoder 입력 계약 (L3)

`ptm_shared/representation/feature_contract.build_multiview_input()`

| 입력 | 처리 | 근거 |
|---|---|---|
| `PTM_Relative_Log2FC` | primary reconstruction target 및 temporal input | 현재 protein-normalized modified-peptide signal의 primary observed trajectory |
| `Protein_Log2FC` | context branch (`role="context"`); PTM target 대체 금지 | modification signal과 혼동 방지 |
| `Occupancy_Logit_Delta` (Track 1) | `Pair_Quality_Tier ∈ {O1, O2}`일 때만 관측; 부재는 **mask**, **0 채움 금지** | paired subset coverage bias 차단 |
| `q_value` | quality-weighted loss + eligibility mask (**feature 아님**) | 통계 신뢰도를 latent biology 축으로 오인 방지 |
| `time_minutes`, `Δt` | 분 단위 time encoding 5차원 (log/linear/gap/sin/cos) | 0.5–1–2.5–5–10–15–30–60분 불규칙 간격 보존 |
| motif | optional static side feature, 기본 off, ablation 전용 | prior가 latent geometry를 지배하는지 검증 |
| raw sequence / PLM | **현 단계 제외** | PLM은 검증 이후 optional evidence |
| species/reference context | `provenance.species_context`에 metadata로만 기록 | `rat_hir` 등 domain shift 추적, species classifier화 방지 |

provenance 정책 문자열(계약 위반 감지용):

- `track1_policy = availability_masked_never_zero_filled`
- `qvalue_policy = quality_weight_and_eligibility_mask_not_feature`
- `protein_policy = context_branch_does_not_replace_ptm_target`
- `sequence_policy = plm_and_raw_sequence_excluded_at_this_stage`
- `species_policy = model_domain_metadata_not_input_feature`

`validate_multiview_input()`이 shape·mask 일관성·q-value 미사용을 검증한다.

## 4. R0 baseline / R1 encoder

### R0 (`baselines.py`)

- `mask_aware_pca` — EM 방식 truncated SVD, 미관측 셀은 저랭크 추정으로만 대치
- `mask_aware_nmf` — masked multiplicative update (non-negative shift 기록)
- `fpca_lite` — log-minute 공간 Gaussian smoothing 후 PCA (불규칙 간격 반영)
- `handcrafted_representation` — Representation A/B/C 조립 (학습 없음)

미관측 셀에 어떤 값이 들어 있어도 결과가 바뀌지 않는다는 것을 테스트가 보장한다.

### R1 (`encoder.py`)

NumPy 전용, 결정적(seed 고정) mask-aware self-supervised autoencoder. PyTorch/CUDA를 worker 선언 의존성에 추가하지 않는다.

- 목적함수: quality-weighted masked MSE (Track 2 primary) + auxiliary(protein, Track 1) + Δt 가중 smoothness + L2
- self-supervision: 매 epoch 관측 entry 일부를 **입력에서 숨기고 loss에는 유지**
- held-out: 학습에 전혀 쓰이지 않는 별도 entry 집합 → `representation_reconstruction_error`
- 산출: `embedding`, `reconstruction`, per-site error, `embedding_uncertainty`, perturbed refit들
- provenance: `secondary_use_only=True`, `primary_scores_unchanged=True`, `qvalue_role=loss_weight_only`

site-level 집계 커버리지 스칼라는 **입력에 넣지 않는다.** 넣으면 embedding이 temporal pattern 대신 coverage를 인코딩하게 되어 missingness 게이트가 잡아내야 할 문제를 스스로 만든다.

## 5. Additive 필드 (R2 준비, primary score 불변)

`metrics.build_additive_fields()` → `ptm_representation_embeddings{suffix}.tsv`

| 필드 | 의미 |
|---|---|
| `representation_reconstruction_error` | held-out 관측값 재구성 오차, low-quality embedding flag |
| `embedding_neighbor_stability` | mask perturbation refit 간 top-k neighbor Jaccard |
| `representation_track_concordance` | latent neighbor가 Track 2 peak·direction (+가능시 Track 1 direction) 증거와 합치하는 정도 |
| `co_wave_neighbor_agreement` | canonical co-wave membership과의 일치도 |
| `representation_supported` | 위 일치도가 임계 이상 |
| `representation_discordant` | 불일치 + **neighborhood가 안정적일 때만** (불안정 embedding은 novelty가 아니라 low quality) |
| `profile_representational_dispersion` | 후보 kinase의 exclusive substrate embedding 분산 → heterogeneous profile 경고 |
| `embedding_uncertainty` | perturbation 간 latent 표준편차 |

TMM 계수를 latent similarity로 바꾸지 않는다. `PRIMARY_SCORE_INPUTS_LOCKED = (canonical_co_wave_membership, tmm_contribution_coefficients, kinase_ranking)`.

표현 제한: "temporal multi-view neighborhood가 AKT-associated reference module과 일치"까지만 서술하며, direct kinase substrate 증명이나 causality는 주장하지 않는다.

## 6. Representation A–E ablation (`benchmark.py`)

| Arm | 내용 | guardrail |
|---|---|---|
| A | Track 2 temporal trajectory only | canonical signed Pearson/TMM baseline |
| B | 현재 handcrafted L1 vector (protein context + quality feature) | protein/quality의 incremental value |
| C | B + motif static descriptors | motif prior dominance, kinase-family leakage |
| D | learned temporal representation (Track 2 only) | time permutation, masked reconstruction, wave stability |
| E | learned multi-view representation (Track 2 + protein + Track 1 gated) | availability bias, protein confounding, cross-dataset stability |

측정 지표: cluster 수, bootstrap neighbor retention, held-out reconstruction, artificial masking probe, raw evidence concordance, timepoint leave-one-out ARI, (라벨 제공 시) neighbor enrichment·cluster purity·ARI. scikit-learn 없이 numpy/scipy로 구현.

## 7. 도입 결정 gate

`evaluate_adoption_gates()`는 6개 gate를 모두 통과하지 않으면 `production_influence_allowed=False`를 반환한다.

| Gate | 구현 |
|---|---|
| `time_validity` | true order held-out error가 permuted order보다 `time_validity_margin` 이상 우수해야 함 |
| `missingness_validity` | 인공 마스킹 재적합 후 cluster ARI 유지(`pattern_retention_ari`) **및** 유도된 missingness rate 예측 R² 상한 이하 |
| `raw_evidence_concordance` | 평균 `representation_track_concordance` 하한 이상 |
| `generalization` | 외부 held-out dataset 결과가 주어져야 통과 (단일 cohort로는 `not_evaluated`) |
| `no_prior_leakage` | prior feature 사용 arm은 feature-free temporal baseline과 비교 필수 |
| `interpretability` | 보고된 모든 site가 gene/position/form/timepoint/Track 상태로 역추적 가능 |

## 8. Insulin 데이터셋 R1 실측 (2026-08-17)

> 이 절은 primary arm이 E였던 시점의 기록이다. arm 간 순위와 gate 판정은 8-bis(공정한 프로브)와
> 8-ter(primary 전환)가 대체한다. 아래 표의 arm별 원시 수치는 그대로 유효하다.

`Insulin_Signaling_Phosphoproteomics_HIRc-B`, 2,744 eligible site/form × 6 timepoint, 약 35초.

| Arm | raw concordance | held-out error | masking retention ARI | induced missingness R² |
|---|---|---|---|---|
| A | 0.588 | — | 0.167 | 0.007 |
| B | 0.656 | — | 0.234 | 0.885 |
| D | 0.564 | 0.524 | 0.035 | 0.462 |
| E | 0.520 | 0.431 | **0.974** | 0.273 |

읽는 법:

- **E(multi-view)가 유일하게 마스킹 하에서 구조를 유지**한다 (ARI 0.97). D(temporal-only)는 붕괴한다 → 통합 검토가 예측한 대로 multi-view branch가 필요하다.
- handcrafted B는 induced missingness R²가 0.885다. mask indicator를 feature로 직접 포함하기 때문이며, coverage 교란에 가장 취약한 arm이다.
- gate 결과: `time_validity` 실패(margin −0.002), `missingness_validity` 실패(0.273 > 0.25), `generalization` 미평가 → **`production_influence_allowed=False`**.

즉 현 시점의 결론은 "learned representation이 kinase ranking을 개선했다"가 아니라 **"E arm이 마스킹 robustness에서 유일하게 유망하며, 시간 순서 유효성과 coverage 독립성은 아직 미달"** 이다. 이것이 R2로 넘어가기 전에 필요한 정확한 상태다.

## 8-bis. 공정한 arm 비교 — held-out 시점 프로브 (R1.6, 2026-08-18)

### 왜 8절의 지표로는 arm을 순위 매길 수 없는가

8절의 `raw_evidence_concordance`는 **arm 간 비교에 사용할 수 없다.** 이 지표는 "임베딩 최근접
이웃이 원본 궤적의 peak 시점(±1)과 부호를 공유하는가"를 재는데, arm B의 임베딩은 학습된 표현이
아니라 **원본 궤적 값 그 자체**다(T=6에서 track2 6 + 관측마스크 6 + protein context 6 + 그 마스크 6
+ quality 6 = 30차원). 원본 궤적 공간에서 이웃을 찾으면 peak 시점과 부호가 같은 것이 당연하므로
거의 항등식이다. 이 지표는 학습 arm이 병목을 통과한 뒤에도 사람이 검토 가능한 증거를 유지하는지
확인하는 **하한 점검**(기준 0.5)이며, 경쟁 벤치마크가 아니다.

`missingness_r2`도 예측변수 개수를 보정하지 않은 R²라서 30차원 arm과 16차원 arm을 나란히 놓을 수
없다. 공정한 대조는 (a) 같은 arm 내 시간 순열, (b) 같은 차원·같은 계열인 D 대 E, (c) 같은 성분 수인
R0 baseline 내부뿐이다.

### 프로브 설계 (`ptm_shared/representation/fair_probe.py`)

한 timepoint를 **모든 view에서** 통째로 가리고, 각 arm이 남은 데이터로 표현을 만들고, ridge
프로브가 학습에 쓰이지 않은 site에서 가려진 Track 2 값을 예측한다. 어느 arm도 정답을 담고 있지
않고, 과제와 모델 계열이 동일하며, ridge penalty를 arm별로 내부 교차검증으로 조정하므로 차원이
넓은 arm이 자동으로 유리해지지 않는다.

**모든 view를 가리는 것이 핵심이다.** 같은 timepoint의 protein context와 Track 1 occupancy는 Track 2
값과 동일한 measurement pair에서 계산되므로, Track 2만 가리면 다른 view를 들고 있는 arm이 가려진
값을 대수적으로 복원한다. 잡음 데이터 대조 테스트가 이 누출을 잡아냈다 — 전체 view를 가리기 전에는
**순수 잡음에서 R² = 1.0**이 나왔다(`test_probe_reports_no_skill_on_noise`).

판정은 두 관문을 모두 통과해야 한다. 프로브 target을 섞은 **순열 귀무분포**를 넘어야 하고, 동일한
(가린 시점, 프로브 분할) 짝에서 baseline arm과의 **짝지은 차이**가 sign-flip 검정을 통과해야 한다.

### 결과 (`Insulin_Signaling_Phosphoproteomics_HIRc-B`, 2,447 site × 6 timepoint, 3분 39초)

| Arm | 차원 | 평균 R² | sd | 귀무 R² | baseline(B) 대비 ΔR² | 우세 fold | p | 판정 |
|---|---|---|---|---|---|---|---|---|
| A | 12 | 0.9236 | 0.013 | −0.004 | −0.0008 | 50.0% | 0.776 | 차이 없음 |
| B | 30 | 0.9243 | 0.016 | −0.010 | (기준) | — | — | — |
| **D** | 16 | **0.9514** | 0.016 | −0.008 | **+0.0271** | **100.0%** | **0.0001** | **baseline 초과** |
| E | 16 | 0.9183 | 0.021 | −0.010 | −0.0060 | 37.5% | 0.057 | 차이 없음 |

모든 arm이 모든 fold에서 순열 귀무분포를 넘었고(귀무 R² ≈ −0.01), 학습 arm은 120 fold, 비학습 arm은
24 fold, 짝지은 비교는 24쌍이다.

> **설정 출처 (2026-08-22 역추적. 표 자체는 수정하지 않았다.)** 위 표가 어떤 설정에서 나왔는지
> 원 실행 기록에 남아 있지 않아 재현으로 확정했다. 상세 대조는 `c2_prereg_v1.md` §7.2.2.
>
> ```text
> key_level        = "site"                 → 2,447 = ['Gene.Name','PTM_Position'] 그룹 수
> eligible_subset  = 미적용                  ← 적격 필터를 적용하면 2,377 이 되고 표와 다르다
> epochs           = 300 (인코더 기본값)
> arms             = (A, B, D, E)
> ```
>
> 이 설정으로 재현하면 차원 4개가 모두 일치하고 B·D·E 의 평균 R² 가 소수 4째 자리까지 맞으며
> ΔR² = 0.02681 이 나온다. 남은 편차(arm A 의 +0.0043, ΔR² 의 −0.0003)는 **프로브 분할 salt
> 결함**에서 온다 — `hash(arm)` 이 프로세스마다 달라 실행 간 폭 0.0032 로 흩어졌다.
> 2026-08-22 에 `crc32` 로 교체했으므로 **이후 실행은 재현되지만 위 표의 수치와는 정확히 같지
> 않다.** 표를 갱신하지 않은 이유는 공표 시점의 값이기 때문이며, 논문에는 재현된 값과 함께
> 이 사정을 병기한다.
>
> C2 작업의 gate·frontier 수치는 **form 수준 적격 부분집합(2,744)** 에서 나오므로 위 표와 모집단이
> 다르다. 두 표의 절대값을 직접 비교하지 않는다.

### 읽는 법

1. **공정한 과제에서는 학습이 실제로 이긴다.** 단 temporal-only arm D만 그렇고, 24쌍 **전부**에서
   B를 앞선다(p = 0.0001). 8절의 "학습이 handcrafted에 못 미친다"는 인상은 편향된 지표의 산물이었다.
2. **primary arm 지정이 틀렸다.** gate는 E를 primary로 평가했지만, 예측력에서 E는 B와 구별되지
   않고(오히려 −0.006) D가 유일한 승자다.
3. **D와 E는 상반된 실패를 한다.** D는 예측이 가장 좋지만 coverage 누출이 최악(induced missingness
   R² 0.462, 자연 0.849)이고, E는 마스킹 robustness가 유일하게 살아있지만(ARI 0.974) 예측 이득이
   없다. 즉 multi-view branch는 robustness를 사고 예측력을 팔았다. 이 교환을 어느 쪽으로 풀지가
   R2 이전의 실제 설계 결정이다.
4. **이득의 크기를 과장하면 안 된다.** baseline이 이미 R² 0.924인 과제에서 +0.027이다. 부드러운
   궤적의 한 시점을 이웃 시점에서 맞히는 것은 쉬운 과제이고, 이 이득이 **kinase 귀속 개선으로
   이어진다는 증거는 아니다.** 그것은 별도의 downstream 평가가 필요하다.
5. 설정은 transductive(모든 arm이 채점 대상 site의 다른 시점을 봄)이고 단일 cohort다. arm 간 조건이
   동일하므로 비교는 공정하지만, **cross-dataset generalization은 여전히 미평가**다.

테스트: `workers/tests/test_representation_fair_probe.py` (13개). 러너:
`scripts/run_representation_fair_probe.py` → `ptm_representation_fair_probe{suffix}.json`.

## 8-ter. primary arm 전환 (E → D) 과 gate 재판정 (2026-08-18)

### 무엇을 바꿨는가

gate가 판정하는 primary arm이 `benchmark.py` 안에 `"E" if "E" in learned_arms else ...` 로 인라인
박혀 있었다. 이것을 `layers.py`의 선언으로 끌어냈다.

```python
PRIMARY_ARM_PREFERENCE: Tuple[str, ...] = ("D", "E")
```

`select_primary_variant()`가 실제로 적합된 학습 arm 중에서 이 순서대로 고르고, ablation 산출물이
`primary_arm_preference`를 함께 기록한다. E는 ablation 표에서 그대로 보고되며, 판정 대상만 아니다.

**순서를 데이터로 정하지 않고 사전 등록하는 이유**가 중요하다. "이 데이터셋에서 이긴 arm을 primary로
쓴다"고 하면 gate를 평가하는 데이터로 gate의 피험자를 고르는 셈이어서, arm 하나만 우연히 통과해도
전체가 통과한 것처럼 보인다. 순서는 8-bis의 누출 없는 프로브 결과에 근거해 코드에 고정하고, 그
근거를 주석과 이 문서에 남긴다. D가 적합되지 않으면 E로, 둘 다 없으면 남은 학습 arm으로 내려간다
(`test_primary_arm_falls_back_when_the_preferred_arm_did_not_fit`).

### 재판정 결과 (`Insulin_Signaling_Phosphoproteomics_HIRc-B`, 2,744 site × 6 timepoint, 47초)

| gate | primary = E (이전) | primary = D (현재) |
|---|---|---|
| `time_validity` | 실패 (margin −0.0016) | **통과 (margin +0.0533)** |
| `missingness_validity` | 실패 (induced R² 0.273 > 0.25, ARI 0.974) | 실패 (ARI 0.035 < 0.2, induced R² 0.462) |
| `raw_evidence_concordance` | 통과 (0.520) | 통과 (0.564) |
| `generalization` | 미평가 | 미평가 |
| `no_prior_leakage` | 통과 | 통과 |
| `interpretability` | 통과 | 통과 |
| 합계 | 3 / 6 | **4 / 6** |
| `production_influence_allowed` | False | False |

### 읽는 법

1. **`time_validity`가 뒤집힌 것이 핵심이다.** 같은 순열 검정에서 E는 margin −0.0016으로 시간 순서를
   전혀 쓰지 않았고, D는 +0.0533으로 쓴다. 8-bis의 프로브(D만 baseline 초과, p = 0.0001)와 완전히
   독립적인 지표가 같은 결론을 냈다. 서로 다른 두 검정이 일치한다는 점이 arm 전환의 근거다.
2. **`missingness_validity`의 실패 이유가 바뀌었다.** E는 마스킹 하에서 군집이 유지됐지만(ARI 0.974)
   그 안정성은 protein context와 Track 1이라는 **비시간적 부수 정보**에서 온 것이고, 그래서 예측력이
   없었다. D는 그 정보가 없으니 군집이 거의 무작위로 붕괴한다(ARI 0.035). 즉 이전의 3/6은 "더 나쁜
   arm이 더 좋아 보이던" 상태였고, 지금의 4/6은 남은 병목이 무엇인지 정확히 가리킨다.
3. **남은 병목은 missingness 얽힘 하나다.** D의 induced missingness R² 0.462(상한 0.25), 자연
   missingness R² 0.849. 다만 handcrafted baseline B가 0.885라는 점을 같이 봐야 한다. **현재 production
   L1 vector 자체가 coverage와 강하게 얽혀 있고**, 학습 arm이 그보다 나쁘지는 않다.
4. `production_influence_allowed`는 여전히 False다. arm을 바꿔 gate 통과 수가 늘었어도 production
   영향은 열리지 않는다 — 이것이 gate 설계의 의도대로 동작한 것이다.

## 9. 산출물 · 운용

preprocessing **Step 1c** (`workers/preprocessing/tasks.py`, Step 1b 직후, progress 56–60%). 실패해도 non-fatal이며 파이프라인을 막지 않는다.

| 파일 | 내용 |
|---|---|
| `ptm_representation_embeddings{suffix}.tsv` | site/form별 latent vector(`z000`…) + additive 필드 |
| `ptm_representation_benchmark{suffix}.json` | layer contract, 보존 baseline 선언, encoder provenance, A–E ablation, gate 판정 |

두 파일은 report generation의 디렉터리 스캔에 자동 포함되어 UI 파일 목록·미리보기·다운로드로 노출된다.

환경 변수:

```bash
PTM_REPRESENTATION_LEARNING_ENABLED=1   # 0이면 Step 1c 전체 skip
PTM_REPRESENTATION_ABLATION_ENABLED=1   # 0이면 encoder만 적합, ablation/gate skip
```

테스트:

```bash
# 컨테이너
docker exec -e PYTHONPATH=/app:/opt -w /app ptm-worker-preprocessing \
  python -m pytest tests/test_ptm_representation_learning.py -v
# 레포 루트 (scipy 필요)
python -m pytest workers/tests/test_ptm_representation_learning.py -v
```

## 10. 로드맵 상태

| 단계 | 범위 | 상태 |
|---|---|---|
| R0 | terminology + PCA/NMF/FPCA baseline | **완료** |
| R1 | mask-aware self-supervised encoder | **완료** |
| R1.5 | A–E ablation + gate 판정 | **완료** (단일 cohort; cross-dataset 미평가) |
| R1.6 | 편향 없는 held-out 시점 프로브로 arm 순위 | **완료** — D가 baseline 초과(p=0.0001) |
| R1.7 | primary arm 사전 등록(D) + gate 재판정 | **완료** — 4/6 통과, `time_validity` 통과로 전환 |
| R2 | additive `representation_supported`/`representation_discordant` 필드 | **계산·기록 완료**, co-wave/TMM provenance 주입은 미연결 |
| R3 | bounded confidence modifier | 미착수 (gate 통과 + 사용자 승인 필요) |
| R4 | typed graph representation | 보류 (multi-condition corpus 필요) |

## 11. 다음 단계

1. **`missingness_validity` — 남은 유일한 계산 가능 병목.** D는 군집 안정성(ARI 0.035)과 coverage
   독립성(induced R² 0.462)에서 동시에 미달이다. E가 이 gate에서 나아 보였던 것은 비시간적 부수
   정보 덕이었으므로 "E로 되돌린다"는 해법이 아니다. 목적함수에 **coverage 예측 가능성에 대한 penalty**
   (임베딩에서 관측 마스크를 맞히지 못하게 하는 항)를 넣는 것이 방향이다.
2. 외부 held-out dataset을 `run_ablation(external_evaluations=...)`로 투입해 `generalization` gate 평가.
   프로브도 같은 dataset에서 inductive 모드로 재확인. 이것과 1번이 통과하면 6/6이 된다.
3. 프로브 이득이 downstream으로 전달되는지 확인. R² +0.027이 kinase 귀속 정확도로 이어지는지는
   별도 평가 과제다.
4. gate 통과 후에만 R2 단계로: co-wave/TMM 결과에 secondary provenance로 부착.

앞선 판본에서 "현 목적함수는 시간 순서를 요구하지 않으므로 `time_validity`를 구조적으로 통과할 수
없다"고 적었으나, 그 관찰은 E에만 해당했다. 같은 목적함수의 temporal-only arm D는 margin +0.0533으로
통과한다. 순서 의존적 항을 새로 넣을 필요는 없고, 부수 view가 시간 신호를 밀어내지 않게 하는 것이
실제 문제였다.

## 12. Core A/B 편입 (2026-08-20)

### 12.1 배경과 결정

Core A/B 알고리즘 명세를 별도 트랙으로 검토하면서 독립적인 평가 골격(`F00`~`F11` factorial, Go/No-Go,
`P−2 frozen contract`)을 설계했다. 그 과정에서 **이 계약과 거의 같은 기계를 병렬로 만들고 있었다는
것**이 확인되었다.

| | 이 계약 | Core A/B 트랙 |
|---|---|---|
| 표현 층 명명 | L1~L4 | A0~A4 |
| 비교 arm | A~E ablation | F00~F11 factorial |
| 단계 | R0~R4 | P−2 / P−1 / Stage 0·1 |
| 채택 판정 | 6-gate + `production_influence_allowed` | Go/No-Go 규칙 |
| 사전등록 | `PRIMARY_ARM_PREFERENCE` 코드 고정 | τ_min, `N_floor` 사전 확정 |

또한 두 트랙의 태도가 모순이었다. 이 계약은 §5에서 `PRIMARY_SCORE_INPUTS_LOCKED`로 학습 표현이
kinase ranking에 영향을 주는 것을 **금지**하고 gate 6개 통과를 조건으로 걸었다(현재 4/6). 반면 Core A/B의
`F10-A4` arm은 그 문이 열린 것을 전제로 설계를 쌓았다.

**결정: 이 계약의 어휘와 gate 체계를 기준으로 삼고, Core A/B 요소를 그 안에 편입한다.**
논문 기여 주장 수준은 **표현 학습 자체**이며, kinase 귀속으로의 전달은 조건부 확장으로 강등한다.

### 12.2 Core A 요소 매핑

| Core A 요소 | 이 계약에서의 위치 | 처리 |
|---|---|---|
| A1 residual (protein 정규화) | §3 `PTM_Relative_Log2FC`가 이미 protein-normalized | **기존 구현에 흡수.** 신규 작업 없음. Core A/B 검토에서 headline 주장이 이미 철회됨 (MAD 0.06 log2) |
| A2 eligibility weight `e_i` | §3 `qvalue_policy = quality_weight_and_eligibility_mask_not_feature` | **기존 정책에 흡수** |
| A3 `O_ij` comparability mask | **신규.** 이 계약에 대응물 없음 | §12.3 참조 — `missingness_validity` 병목의 후보 기제로 편입 |
| A4 temporal wave prototype `p_iw` | L4 / canonical co-wave membership | arm D 내부의 아키텍처 선택지로 편입. 별도 표현 층으로 두지 않음 |
| U-confirmatory 등 feature universe 4분할 | §8 "eligible site/form"의 세분화 | **특성화 자료로 편입** (§12.4) |

### 12.3 A3 (`O_ij`)의 재배치 — 남은 병목과의 연결

Core A/B 트랙에서 `O_ij`는 "wave 오배정을 막는 correctness guard"로 규정되었고, HIRc-B 실측에서
전역 footprint가 작다는 것이 확인되었다(replicate≥1에서 non-comparable pair 2.51%, replicate≥2에서 9.07%).
동시에 그 edge가 **소수 저관측 feature에 집중**되어 있었다.

```
비교 불가 degree 와 관측 timepoint 수의 상관: −0.764 (rep≥1) / −0.869 (rep≥2)
상위 1% feature(24개)가 non-comparable edge 종단의 39.5% 차지
상위 5% feature 평균 관측 4.12/6 vs 나머지 5.96/6
```

**이 성질이 `missingness_validity` 병목과 정확히 같은 축이다.** §11.1이 지적한 문제는 임베딩이 temporal
pattern 대신 coverage를 인코딩한다는 것이고(arm D의 induced missingness R² 0.462, 상한 0.25), `O_ij`는
관측량이 부족한 쌍을 비교 대상에서 제외하는 장치다. 따라서 `O_ij`를 독립 알고리즘 기여로 두지 않고
**`missingness_validity` 대응 후보 기제**로 재배치한다.

```text
A3_AS_MISSINGNESS_MECHANISM
  기존 §11.1 방향  = 목적함수에 coverage 예측 가능성 penalty 추가
  추가 후보        = O_ij 기반 pairwise comparability 제약
                     (공유 관측 timepoint T_min 미달 쌍을 이웃 계산에서 제외)
  판정 기준        = 두 기제 각각, 그리고 병용 시 induced missingness R² 와 ARI
  주의             = 어느 쪽도 arm 순위를 바꾸는 데 쓰지 않는다.
                     PRIMARY_ARM_PREFERENCE 는 §8-ter 근거로 고정된 상태를 유지한다.
  A3 평가 층       = pair 수준 false-merge rate, feature-clustered bootstrap,
                     replicate ≥ 2 계층만 사용 (n_eff = 432)
                     replicate ≥ 1 계층은 n_eff = 125 로 검정력 미달 → 사용 금지
```

Kish 실효 cluster 수와 필요 표본은 Core A/B 트랙에서 산출된 값을 그대로 쓴다. 불일치율 10%를 검출하려면
289, 20%면 145가 필요하므로 replicate≥2 계층만 판정에 사용할 수 있다.

### 12.4 HIRc-B 특성화 자료 (재사용)

Core A/B 트랙의 실측을 이 계약의 데이터셋 특성화로 편입한다. **HIRc-B 로컬 값이며 외부 데이터셋에
복사하면 안 된다.**

| universe | feature 수 | 기준 |
|---|---:|---|
| paired control replicate ≥ 2 | 2,420 | 확증 분석 가능 |
| paired control 정확히 1 | 302 | sensitivity 전용 |
| paired control 0 | 313 | 탐색 전용 |

§8의 "2,744 eligible site/form"과 위 분할의 관계를 기록해 두면, `missingness_validity` 실패가 특정
universe에 집중되는지 확인할 수 있다. **이것이 §12.3 판정의 층화 근거가 된다.**

### 12.5 Core B 및 kinase 계층 — 조건부 확장으로 강등

Core B(KSA scorer, 5-gate 선택적 의사결정)와 `Δ_representation`(표현 개선이 kinase 귀속으로 전달되는지)는
**이 계약의 기여 주장에서 제외**한다. §5의 `PRIMARY_SCORE_INPUTS_LOCKED`가 이미 그 경계를 정의하고
있으므로 새로운 후퇴가 아니고, 기존 lock을 준수하는 것이다.

이 결정의 실질적 효과는 다음과 같다. Core A/B 트랙에서 식별된 blocker 대부분이 **임계 경로에서
빠진다.**

| blocker | 성격 | 이 계약에서의 상태 |
|---|---|---|
| A. KSA library 부재 | 데이터 | **임계 경로 밖.** kinase 계층 전용 |
| B. PXD014525 접근성 | 데이터 | **임계 경로 밖.** Tier-2 kinase 검증 전용 |
| C. PXD043599 protein 정량 | 데이터 | **유효, 단 축소.** §12.6 |
| D. A4 transmission 측정 불가 | 구조 | **임계 경로 밖.** 조건부 확장의 전제 |
| E. prior가 설계행렬 구성 | 설계 | **임계 경로 밖.** NNLS scorer 전용 |
| F. LLM 예측 kinase 유입 | 오염 | **임계 경로 밖.** 단 §12.7 참조 |

IA-07(설계행렬 전달성 감사, τ)도 임계 경로에서 빠진다. τ는 `Δ_representation`이 측정 가능한지 판정하는
장치였고, 그 endpoint를 주장하지 않으므로 지금 필요하지 않다. **조건부 확장을 검토하는 시점의 선행
조건으로 보류한다.**

상세 분석은 `docs/core_ab_p2_frozen_contract_v1.md`(kinase 계층 지연 확장 명세)와
`~/Downloads/Core_A_B_설계행렬_LLM오염_문제진단_20260820.md`에 보존한다.

### 12.6 `generalization` gate — 요구사항 축소

primary arm이 D(temporal-only)로 전환되었으므로(§8-ter) 외부 데이터셋 요구가 완화된다.

```text
arm D 가 필요한 것 = Track 2 temporal trajectory 뿐
  → protein context branch, Track 1 occupancy 미필요
  → 단, Track 2 자체가 protein-normalized 신호이므로
    matched protein 정량은 여전히 필요하다 (§3)

matched protein 정량이 없는 데이터셋의 경우
  → UNNORMALIZED_PHOSPHO_ADAPTER_V1 적용
  → 결론을 "방향 일치" 수준으로 제한, 효과크기 비교 금지
  → 판정 시점을 데이터 확인 직후로 사전 확정
```

따라서 BLOCKER-C는 유효하지만 범위가 좁아졌다. multi-view branch용 데이터는 필요하지 않고 Track 2
정규화에 필요한 만큼만 확인하면 된다.

### 12.7 잔여 오염 점검 (`no_prior_leakage`와의 연결)

Core A/B 트랙에서 확인된 LLM 오염 경로는 kinase 계층에 있으므로 임계 경로 밖이다. 다만 이 계약의
`no_prior_leakage` gate와 성질이 같으므로 두 항목을 기록해 둔다.

- `LLMKinasePredictor`(RAG enrichment) → `kinase_annotation_node` Source 1 → `candidate_kinases` →
  NNLS 설계행렬 열. 이 계약의 표현 층은 이 경로를 거치지 않으므로 현재 영향 없음
- `workers/common/kinase_weight_manager.py`의 문헌 기반 가중은 **미확인.** kinase 계층 재개 시 선행 실사

이 계약 쪽에서는 §3의 `motif` 처리(기본 off, ablation 전용)와 arm C가 이미 prior dominance를 검증하는
장치이므로 추가 조치가 필요하지 않다.

### 12.8 편입 후 로드맵

임계 경로에 blocker가 없다.

| 순위 | 작업 | 대응 gate | 선행 조건 |
|---|---|---|---|
| 1 | 목적함수에 coverage 예측 penalty 추가 | `missingness_validity` | 없음 |
| 2 | `O_ij` pairwise comparability 제약 구현·비교 (§12.3) | `missingness_validity` | 없음 |
| 3 | universe 층화 진단 (§12.4) | `missingness_validity` 원인 규명 | 없음 |
| 4 | 외부 phospho time-course 확보 및 inductive 재확인 | `generalization` | 데이터 접근 |
| 5 | 6/6 도달 시 R2 co-wave/TMM provenance 주입 | — | 1~4 완료 |
| — | kinase 계층 조건부 확장 (IA-07 → Core B) | — | 5 완료 + 사용자 승인 |

1~3번은 같은 gate를 겨냥하며 상호 배타가 아니다. 세 가지를 각각 그리고 병용해서 측정하고, 어느 조합이
`induced missingness R²`를 상한 이하로 내리면서 ARI를 유지하는지 본다.

**`production_influence_allowed`는 6/6 이전에 열리지 않는다.** 이 원칙은 편입으로 변경되지 않는다.
