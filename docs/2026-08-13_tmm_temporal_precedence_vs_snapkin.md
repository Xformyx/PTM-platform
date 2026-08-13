# SnapKin 대비 TMM 및 Temporal-Precedence Attribution의 심층 분석

## 핵심 결론

SnapKin과 PTM-platform은 모두 **kinase–substrate attribution**을 다루지만, 추정하려는 값이 다르다. SnapKin은 대규모 curated label을 학습해 phosphosite `s`가 kinase `k`의 substrate일 **일반적 가능성**을 ranking한다. PTM-platform의 TMM은 이미 확보된 candidate kinase 집합 안에서, 현재 실험 조건의 site trajectory가 각 kinase의 **조건 특이적 temporal profile에 얼마나 기여되는가**를 분해한다. Temporal precedence는 그 attribution을 넘어 Wave 또는 effector 사이의 **관찰된 시간적 순서**를 정량화한다.[1]

> SnapKin은 “이 site는 누구의 substrate일 가능성이 높은가”를 묻고, TMM은 “이 실험에서 여러 후보 중 누가 이 site의 시간 profile을 얼마나 설명하는가”를 묻는다. Temporal precedence는 “그 설명된 activity가 무엇보다 먼저 관찰되는가”를 묻는다.

이 차이는 단순히 feature 개수의 차이가 아니다. **global biochemical likelihood**, **condition-specific temporal attribution**, **observational directionality**라는 서로 다른 evidence axis다. PTM-platform의 장점은 이 세 axis를 provenance와 불확실성 표시를 포함해 연결한다는 점이다.

## 1. 추정 대상의 수학적 차이

### SnapKin: kinase별 supervised posterior ranking

SnapKin은 kinase `k`별로 known positive substrate와 negative/unlabeled site를 사용해 classifier를 학습한다. 개념적으로 출력은 다음과 같다.

```text
Score_SnapKin(k, s) ≈ P(known kinase–substrate-like | motif,
                                        local sequence,
                                        phosphorylation dynamics,
                                        training labels)
```

논문은 pseudo-positive augmentation, negative resampling ensemble, snapshot DNN ensemble, CKSAAP sequence encoding을 결합해 7개 공개 phosphoproteomics dataset의 12개 kinase ranking을 평가했다.[1] 따라서 SnapKin score는 **학습된 reference biology와 feature similarity에 근거한 site-level substrate plausibility**다.

### PTM-platform TMM: candidate set 내부의 조건 특이적 mixture decomposition

PTM-platform은 motif/annotation/curated source로 후보 집합 `C_s`를 먼저 만들고, 각 kinase의 exclusive substrate로 data-driven activity profile을 만든다. shared PTM `s`에 대해 현재 구현은 다음 NNLS model을 푼다.

```text
y_s(t) = Σ[k ∈ C_s] a[s,k] · p_k(t) + ε,     a[s,k] ≥ 0
r[s,k] = a[s,k] / Σ[j ∈ C_s] a[s,j]
```

여기서 `y_s(t)`는 shared PTM의 관찰 time-series이고, `p_k(t)`는 kinase `k`의 exclusive substrate median temporal profile이다. `r[s,k]`는 서로 경쟁하는 후보들 사이의 contribution ratio이며 합이 1이 되도록 정규화된다. exclusive site는 `r=1.0`, shared site는 fractional contribution으로 kinase activity sum과 count에 반영된다.

| 질문 | SnapKin | TMM |
|---|---|---|
| 추정 대상 | site–kinase pair의 learned plausibility | 후보 kinase들 간 site trajectory explanation ratio |
| 비교 범위 | training corpus가 지원하는 kinase별 global ranking | 현재 site의 candidate set 내부 competition |
| 정규화 | kinase별 prediction score, 반드시 합이 1일 필요 없음 | 같은 site의 competing candidate contribution이 합계 1 |
| 조건 의존성 | dynamics feature로 반영 가능하지만 global model output | 해당 Order의 actual time-course에서 재추정 |
| 설명 가능성 | feature/model importance를 별도 해석해야 함 | exclusive profile, coefficient, residual, profile source로 분해 가능 |

## 2. Shared substrate ambiguity에서의 구체적 강점

phosphoproteomics의 현실은 하나의 motif가 여러 kinase family와 양립하고, 한 site가 실제로 multiple kinase에 의해 서로 다른 조건 또는 시간에서 조절될 수 있다는 것이다. 특히 basophilic motif에서는 AKT, SGK, S6K, RSK, PKA/PKC 등 후보가 겹친다.

SnapKin은 각 kinase classifier가 독립적이므로 하나의 site에 AKT·S6K·RSK 모두 높은 score를 줄 수 있다. 이는 biologically valid한 다중 가능성을 보존한다는 장점이 있지만, **해당 실험에서 어느 후보가 우세했는지**는 score만으로 해결되지 않는다.

TMM은 이 문제를 site에 대해 닫힌 candidate simplex를 만들고, time-course shape로 fractional allocation을 수행한다.

```text
공유 site S, 후보: AKT / S6K / RSK

SnapKin:
  AKT = 0.84, S6K = 0.78, RSK = 0.72
  → 세 candidate의 global substrate plausibility

TMM, 현재 insulin-like time-course:
  AKT = 0.67, S6K = 0.24, RSK = 0.09
  → 이 조건에서 S의 observed temporal profile을 가장 잘 설명하는 relative contribution
```

이것은 “AKT가 보편적으로 S의 유일한 kinase다”라는 주장이 아니다. 다만 **이번 stimulus·cell state·time axis에서** AKT-like empirical profile과의 정합성이 가장 크다는 condition-specific attribution이다. 다음 조건에서 S6K profile이 더 맞으면 TMM fraction은 달라질 수 있고, 바로 그 변화가 biological signal이다.

### TMM의 강점 1: 동일 site의 double counting을 줄인다

shared site를 모든 candidate kinase module에 동일한 가중치로 넣으면, broad motif kinase가 시스템 수준 activity를 과대 점유한다. TMM은 `1.0`을 여러 module에 복제하는 대신 `r[s,k]`로 보존량을 나눠 weighted count와 weighted fold-change에 반영한다. 이는 AKT1에 과도하게 site가 집중되는 문제를 해결하는 데 특히 의미가 있다.

### TMM의 강점 2: unknown 또는 sparse annotation에서도 조건별 signal을 활용한다

SnapKin은 validated training label과 species/site coordinate compatibility에 의존한다. 반면 TMM은 candidate set을 만들 수 있고 각 kinase에 최소 3개의 exclusive substrate가 있으면, 해당 Order 자체에서 profile을 생성한다. 이 점은 rat model, annotation-poor tissue, 새로운 stimulus처럼 supervised label coverage가 약한 상황에서 유리하다.

### TMM의 강점 3: attribution과 kinase activity aggregation을 같은 언어로 연결한다

현재 `compute_weighted_kinase_scores()`는 contribution ratio를 단지 site annotation에 표시하는 데 그치지 않고, condition별 weighted up/down sum과 fractional substrate count로 연결한다. 따라서 보고서의 kinase activity heatmap, co-wave, Data-Grounded Analysis가 같은 attribution 결과를 재사용할 수 있다.

## 3. Temporal precedence가 추가하는 고유한 강점

SnapKin은 phosphosite dynamics를 classifier feature로 활용하지만, 논문의 핵심 output은 site ranking이다. onset lag, peak lag, physical minute 단위 temporal order, bootstrap confidence interval, time-order permutation은 model의 명시적 output이 아니다.[1]

PTM-platform의 `DirectedTemporalRelationship`은 다음을 별도 evidence로 계산한다.

```text
onset lag        : target onset minute − source onset minute
peak lag         : target peak minute − source peak minute
lag-aware fit    : temporal shift 후 profile similarity
bootstrap        : replicate resampling에서 direction의 안정성
leave-one-out    : 특정 timepoint 의존성
permutation      : time order가 null보다 유의한지
threshold grid   : onset threshold 변화에 대한 민감도
```

이 결과는 `D0_unresolved`부터 `D3_mechanistically_supported_directionality`까지 구분된다. D3도 causal conclusion이 아니라, reproducible temporal precedence와 kinase–substrate/motif/PPI/ChromaDB consistency가 함께 있는 **candidate regulatory path**다. intervention evidence는 별도 post-analysis layer에만 들어간다.

| 능력 | SnapKin | PTM-platform temporal precedence |
|---|---|---|
| Profile dynamics | classifier feature | direct output 및 evidence profile |
| Physical time units | architecture상 필수 아님 | min/hour/day를 minute로 정규화 |
| Lead–lag | 명시적 output 아님 | onset, peak, shifted similarity를 동시 평가 |
| Direction uncertainty | classifier CV variance | bootstrap CI, leave-one-out, permutation, threshold flags |
| Causal language boundary | KS association 문제에 초점 | `causality_status=not_tested`를 기본값으로 강제 |
| Report role | ranked substrate list | signaling order·가설·validation proposal의 근거 |

### Temporal precedence의 강점 1: sequence-equivalent candidate를 kinetic role로 구분한다

AKT와 S6K가 비슷한 motif compatibility를 가지더라도, early 5–15 min Wave의 AKT-like profile과 later 30–60 min S6K-like profile은 현재 data에서 구분될 수 있다. TMM은 shared site에 relative attribution을 주고, precedence는 upstream Wave가 downstream Wave보다 일관되게 선행하는지를 시험한다. 이 조합은 motif alone으로는 보이지 않는 **kinetic role separation**을 제공한다.

### Temporal precedence의 강점 2: “정보가 없었다”도 결과로 보존한다

timepoint가 부족하거나 onset/peak/lag가 충돌하면 D0으로 반환한다. D2/D3은 replicate bootstrap과 permutation을 요구한다. 따라서 platform은 강한 화살표만 만드는 것이 아니라, **어떤 arrow가 아직 주장 불가능한가**를 quality flag와 함께 기록한다. 이는 Data-Grounded Analysis와 Co-Scientist가 unknown을 causal story로 채우는 위험을 줄인다.

### Temporal precedence의 강점 3: 후속 검증 실험을 data-driven하게 좁힌다

D2/D3 `source_precedes_target` 관계만 post-analysis causal validation recommendation 대상으로 보낸다. 이는 inhibitor를 initial unbiased phosphoproteomics design에 미리 넣지 않고도, 분석이 끝난 뒤 가장 정보량이 큰 validation candidate를 선택하게 한다.

## 4. SnapKin보다 PTM-platform이 더 강하게 주장할 수 있는 지점

### 학술적으로 방어 가능한 주장

1. **Condition-specific shared-substrate decomposition:** “PTM-platform은 후보 kinase가 중첩된 site의 time-course를 data-derived kinase profiles의 non-negative mixture로 분해하여, 동일 조건에서 fractional kinase contribution을 제공한다.”
2. **Temporal systems attribution:** “PTM-platform은 site-level candidate assignment를 Wave, TMM-weighted kinase activity, temporal precedence로 확장해 stimulus-specific signaling organization을 해석한다.”
3. **Evidence-aware directionality:** “PTM-platform은 temporal order와 causal support를 분리하고 resampling/permutation evidence가 부족한 관계를 unresolved로 유지한다.”
4. **End-to-end traceability:** “모든 Wave threshold, fallback profile type, exclusive substrate count, TMM contribution, D-tier, literature/provenance를 reportable evidence chain으로 보존한다.”

### 아직 주장하면 안 되는 지점

1. “TMM이 SnapKin보다 universal kinase–substrate prediction accuracy가 높다.”
2. “D3 precedence가 causality를 증명한다.”
3. “data-driven TMM fraction이 true biochemical occupancy 또는 catalytic flux다.”
4. “expected kinase peak prior와 맞는 결과가 independent discovery다.”

## 5. 현재 TMM의 중요한 한계와 강화 우선순위

PTM-platform의 강점을 유지하려면 현재 구현의 fallback과 identifiability를 투명하게 다뤄야 한다.

| 현재 구현 세부 | 이점 | 경계 또는 권장 강화 |
|---|---|---|
| Exclusive substrate median profile | outlier에 robust하고 각 Order에서 계산 | profile은 `abs(log2FC)`를 사용하므로 timing magnitude 중심; activation/inhibition sign은 별도 결과로 보고 |
| 최소 3 exclusive substrate | profile을 지나치게 작은 anchor set에서 만들지 않음 | `n_exclusive`, profile dispersion, bootstrap CI를 TMM confidence에 포함 |
| Gaussian fallback | sparse kinase도 model에서 완전히 탈락하지 않음 | biological time prior이므로 `fallback` attribution을 data-driven profile과 같은 confidence로 취급하지 않음 |
| NNLS non-negative coefficient | 해석 가능한 additive mixture | candidate profile이 서로 거의 collinear하거나 timepoint가 적으면 coefficient는 비식별적일 수 있음 |
| ratio normalization | shared site double counting 감소 | residual fit, design-matrix condition number, contribution entropy를 저장해 ambiguous fit을 표기 |
| signed weighted up/down aggregation | effect direction을 kinase score에 반영 | negative trajectory와 non-negative profile fit의 관계를 별도 audit; up/down profile을 분리하는 signed TMM을 고려 |

### 권장 TMM confidence profile

다음 보완은 SnapKin을 복제하지 않으면서 platform의 고유 강점을 강화한다.

```text
TMMEvidenceProfile
├── profile_type: data_driven | gaussian_fallback
├── n_exclusive_substrates
├── exclusive_profile_dispersion
├── fit_residual_norm
├── design_matrix_condition_number
├── contribution_entropy
├── bootstrap_contribution_CI
├── candidate_set_provenance
├── direction_consistency
└── tmm_confidence_tier
```

이 profile은 `data_driven`/충분한 anchor/낮은 residual/낮은 collinearity/좁은 bootstrap CI일 때만 strong TMM evidence로 승격해야 한다.

## 6. SnapKin과의 최적 관계: 대체가 아닌 orthogonal evidence

향후 SnapKin 또는 유사 pretrained classifier를 붙일 때 가장 좋은 구조는 score fusion이 아니라 **evidence matrix**다.

| Evidence axis | 질문 | Platform에서의 역할 |
|---|---|---|
| SnapKin/sequence score | 이 site가 kinase `k`의 biochemical substrate와 닮았는가 | global substrate plausibility |
| Motif/curated annotation | 이미 알려진 recognition/evidence가 있는가 | candidate-set construction |
| TMM contribution | 이 조건의 observed trajectory는 어떤 candidate profile에 얼마나 설명되는가 | condition-specific allocation |
| Directionality tier | 이 activity/event는 무엇보다 먼저 관찰되는가 | kinetic network ordering |
| ChromaDB / Co-Scientist evidence | 이 해석은 문헌과 어떤 점에서 일치·반박되는가 | biological interpretation and hypothesis testing |

예를 들어 SnapKin은 S–AKT pair를 strong하게, TMM은 현재 condition에서 S6K contribution을 strong하게 줄 수 있다. 이 불일치는 오류가 아니라 **global substrate competence와 condition-specific kinase usage가 다를 수 있다는 발견 후보**다. Report는 이를 `evidence_mixed`로 표시하고, Data-Grounded Analysis는 해당 site를 high-value follow-up candidate로 우선순위화해야 한다.

## 최종 포지셔닝

PTM-platform의 차별점은 “더 큰 black-box predictor”가 아니라, **시간이 있는 실제 PTM data에서 shared attribution을 보존량 제약 하에 분해하고, temporal order의 불확실성을 명시하며, interpretation과 후속 validation을 evidence tier에 맞춰 제한하는 시스템**이라는 데 있다.

SnapKin은 site-level supervised substrate plausibility의 강력한 reference다. PTM-platform은 그 결과를 대체한다고 주장하기보다, SnapKin이 해결하지 않는 **condition-specific mixture attribution과 evidence-aware temporal systems reasoning**을 제공한다고 포지셔닝하는 것이 가장 과학적으로 강하다.

## References

[1] Xiao D, Lin M, Liu C, et al. [SnapKin: a snapshot deep learning ensemble for kinase-substrate prediction from phosphoproteomics data](https://doi.org/10.1093/nargab/lqad099). *NAR Genomics and Bioinformatics*. 2023;5(4):lqad099.
