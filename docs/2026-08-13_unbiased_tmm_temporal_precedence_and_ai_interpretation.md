# Unbiased Discovery 관점의 TMM·Temporal Precedence와 AI 특이점 해석 평가

## 결론

TMM과 temporal precedence는 SnapKin의 supervised site-level predictor보다 **unbiased discovery에 더 적합한 계층**이 될 수 있다. 그 이유는 외부 label에 가장 가까운 site를 찾는 것이 아니라, 현재 Order의 관찰값에서 shared substrate의 temporal contribution과 event order를 직접 계산하기 때문이다. 그러나 현재 PTM-platform 전체가 자동으로 unbiased한 것은 아니다. candidate kinase set, expected cascade timing, Gaussian fallback, treatment context, motif annotation, ChromaDB는 모두 prior를 도입한다.

> 정확한 주장은 “PTM-platform은 **data-derived discovery mode를 제공할 수 있고**, prior-assisted interpretation과 AI reasoning을 별도 evidence layer로 분리한다”이다. “prior가 전혀 없는 완전한 unbiased inference”라고 주장하면 안 된다.

## 1. SnapKin과 TMM의 bias source 비교

| 요소 | SnapKin | 현재 TMM·temporal precedence | Unbiased discovery 관점 |
|---|---|---|---|
| 초기 후보 공간 | curated kinase–substrate positive label과 training task가 정의 | motif·annotation으로 candidate set을 정의 | 둘 다 prior가 있음; TMM은 candidate **내부** attribution을 data로 재평가 |
| learning signal | 과거 validation, sequence, dynamics로 학습된 global classifier | 현재 Order의 exclusive substrate profile과 observed trajectory | TMM이 새로운 condition의 kinetics에 더 민감 |
| time 정보 | classifier feature | NNLS mixture의 핵심 입력, onset/peak/lag의 직접 output | TMM·precedence에 유리 |
| time prior | training corpus의 dataset distribution에 내재 | data-driven profile 또는 Gaussian expected-peak fallback | fallback은 명시적으로 prior-assisted로 표기 필요 |
| unknown biology | training label coverage 밖에서는 낮은 신뢰도 또는 ranking 불안정 | new Wave·mixed contribution·prior conflict를 보존 가능 | novelty discovery에 유리 |
| output | global site–kinase plausibility | condition-specific contribution + temporal order | 서로 다른 evidence axis |

SnapKin은 known positive label을 중심으로 model boundary가 형성된다. 따라서 학습 label이 풍부한 human kinase, 많이 연구된 motif family, training dataset과 유사한 cell state에 유리하다. pseudo-positive augmentation은 적은 label을 완화하지만, original positive set의 representation bias도 함께 확장할 수 있다.[1]

TMM은 `y_s(t) = Σ a_s,k p_k(t) + ε`를 현재 Order에서 푼다. `p_k(t)`는 exclusive substrate의 median profile이므로, 새로운 stimulus에서의 actual response pattern이 contribution ratio에 직접 들어간다. 이 때문에 TMM은 **“기존 문헌에서 가장 흔한 kinase”**가 아니라 **“이 데이터에서 해당 trajectory를 가장 잘 설명하는 candidate”**를 찾는 데 적합하다.

## 2. TMM과 temporal precedence가 discovery에 유리한 구체적 이유

### 2.1 Data-derived local reference

TMM은 동일 Order의 exclusive substrate에서 kinase profile을 만들고, shared site를 그 profile들의 non-negative mixture로 분해한다. 이는 외부 corpus에서 학습한 average biology보다 현재 sample의 cell state, treatment strength, measurement platform, time resolution을 반영한다.

예를 들어 insulin-like response에서 같은 AKT/SGK/S6K motif site라도, 현재 data에서 early AKT-like exclusive profile과 late S6K-like exclusive profile이 분명히 다르면 TMM은 양자의 contribution을 분리할 수 있다. SnapKin의 score가 높아도 해당 condition에서 profile이 맞지 않으면 높은 contribution을 자동으로 보장하지 않는다.

### 2.2 Shared-substrate를 single-winner로 강제하지 않음

Unbiased discovery의 중요한 원칙은 다의적 evidence를 조기에 하나의 known answer로 붕괴시키지 않는 것이다. TMM의 ratio는 한 site를 AKT 또는 S6K로 강제 배정하지 않고 `0.55 / 0.35 / 0.10`처럼 경쟁 attribution을 유지한다. 이는 다음 두 경우를 모두 보존한다.

1. 실제로 하나의 site가 condition-dependent하게 여러 kinase의 영향을 받는 경우.
2. profile collinearity 또는 정보 부족으로 kinase를 완전히 구분할 수 없는 경우.

후자의 경우가 숨겨지지 않도록 residual, condition number, contribution entropy, bootstrap CI를 다음 TMM upgrade에서 반드시 기록해야 한다.

### 2.3 Novel temporal pattern을 삭제하지 않음

Temporal Wave와 D0–D3 relationship은 known pathway와 맞지 않는 결과를 자동 제거할 필요가 없다. 데이터와 prior가 충돌하면 `prior_conflict` 또는 `novel_temporal_candidate`로 남겨야 한다. SnapKin식 classifier는 known label boundary에서 멀어진 candidate를 낮게 rank할 수 있지만, platform은 서로 다른 timing 또는 unusual Wave membership을 **가설 후보**로 보존할 수 있다.

### 2.4 Directionality를 hypothesis prioritization으로 사용

Temporal precedence는 causality를 만들기 위한 장치가 아니라, 생물학적 질문의 우선순위를 정하는 장치다. observed onset/peak lag, lag-aware similarity, bootstrap, time permutation, threshold sensitivity를 통과한 D2/D3 관계는 더 적은 후속 실험으로 큰 정보를 줄 가능성이 높다. 이는 unbiased discovery 뒤의 efficient validation design에 적합하다.

## 3. 현재 코드에서 unbiasedness를 약화시키는 부분

현재 `temporal_kinase_scoring.py`에는 `SIGNALING_CASCADES`, kinase별 expected peak window, wave-tier kinase 목록, treatment context가 존재한다. exclusive substrate가 3개 미만일 때 사용하는 Gaussian profile도 expected peak time을 중심으로 만든 prior다. 또한 일부 redistribution path는 over-concentrated module을 temporal tier 기반으로 다른 kinase에 강제 배정한다.

이 기능들은 user-facing 해석과 sparse data rescue에는 유용하지만, 결과를 **data-only**가 아니라 **prior-assisted**로 분류해야 한다. 특히 exploratory discovery 결과가 expected RAS–MAPK 또는 PI3K–AKT timing과 맞는다고 해서 독립적 발견이라고 표현해서는 안 된다.

| Mode | 허용 evidence | 사용 목적 | Report 표현 |
|---|---|---|---|
| **Data-derived discovery** | measured PTM values, data-driven Wave, data-driven TMM profiles, D0–D2 timing diagnostics | 새로운 temporal organization 탐색 | `observed in this dataset` |
| **Prior-assisted attribution** | motif, curated KS, expected timing, Gaussian fallback, treatment/receptor/PPI support | 후보 해석·sparse data 보완 | `prior-assisted candidate attribution` |
| **Biologically supported interpretation** | D2 + motif/KS/PPI/ChromaDB consistency | 기전 가설 우선순위화 | `consistent with a candidate mechanism` |
| **Post-analysis validation** | user-uploaded perturbation results | 독립적 조건에서 선택 후보 평가 | `perturbation-supported in the uploaded condition` |

### 필수 설계 원칙

1. **Gaussian fallback과 expected-peak score는 data-driven contribution과 같은 confidence tier가 아니어야 한다.**
2. **TMM에서 data-driven profile이 없는 kinase는 “unknown/insufficient anchor”로 남길 수 있어야 한다.** 억지로 known cascade timing에 맞춰 채우지 않는다.
3. **Report에는 data-only와 prior-assisted 결과를 별도 label로 보여야 한다.**
4. **Benchmark에는 data-only TMM, prior-assisted TMM, motif-only, static score를 모두 ablation으로 넣어 prior가 실제 성능을 높였는지 확인한다.**

## 4. AI를 이용한 특이점 인지: 유리한 부분

AI는 discovery score를 대체하는 engine이 아니라, 많은 Wave·site·kinase·directionality·TMM evidence를 동시에 읽는 **특이점 triage와 explanation layer**로 사용할 때 강하다.

| AI가 잘할 수 있는 특이점 | 필요한 구조화 입력 | 연구적 가치 |
|---|---|---|
| **Prior conflict** | high TMM contribution + expected timing 불일치 | 알려진 pathway와 다른 condition-specific branch 발굴 |
| **Mixed attribution** | 높은 contribution entropy, profile collinearity, divergent model support | single-kinase story로 과도하게 단순화하지 않음 |
| **Wave handoff** | early/late Wave, D-tier, shared substrate transition | signal handoff 또는 sequential program 후보 생성 |
| **Autophosphorylation mismatch** | self-PTM timing과 module peak 차이 | kinase activity marker의 context-specific 예외 탐색 |
| **Concordance / contradiction** | TMM, motif, curated KS, ChromaDB, external Co-Scientist evidence | 근거가 일치하는 후보와 반증 가능한 후보를 구분 |
| **Sparse but informative patterns** | low-member Wave + high effect size + reproducibility flags | frequency-based filtering이 놓치는 event 우선순위화 |

특히 AI는 “가장 큰 fold-change”만 찾는 방식보다, **강도는 작지만 여러 evidence axis가 예외적으로 조합된 사건**을 후보로 만들 수 있다. 예를 들어 low abundance PTM이라도 D2 precedence, high TMM contribution, unexpected motif conflict, ChromaDB contradiction이 함께 있으면 후속 검증 가치가 높은 특이점이다.

## 5. AI 특이점 해석의 불리한 부분과 위험

| 위험 | 발생 방식 | 결과 |
|---|---|---|
| **Confirmation bias** | treatment context·known cascade·retrieved literature가 prompt 초기에 과도하게 제시됨 | 예상 pathway를 재서술하고 novelty를 무시 |
| **Narrative overfitting** | AI가 여러 약한 연관을 매끄러운 mechanism으로 연결 | D1/D0 관계가 causal story로 과장 |
| **Salience bias** | top kinase·large fold-change·많은 annotation만 반복적으로 선택 | small but reproducible Wave를 누락 |
| **Multiplicity blindness** | 많은 site/wave 중 흥미로운 하나만 선택 | false discovery가 강조될 수 있음 |
| **Provenance loss** | AI 문장이 source PTM·threshold·fallback type을 숨김 | 재현 불가능한 interpretation |
| **External knowledge leakage** | user data/ChromaDB 밖의 일반 지식을 사실처럼 사용 | 보고 범위와 evidence boundary 위반 |

AI에게 “새로운 것을 찾아라”라고만 지시하면 특히 위험하다. novelty는 AI가 발명하는 속성이 아니라, **명시된 null model 또는 prior와 data의 차이**로 정의해야 한다.

## 6. 권장 AI 특이점 탐지 운영 모델

### Pass A — Blind data anomaly detection

AI 또는 deterministic ranker에 expected pathway label, treatment narrative, ChromaDB conclusion을 주지 않는다. 아래 data-derived field만 제공한다.

```text
Wave membership / coherence / stability
TMM contribution / residual / entropy / profile_type
onset·peak lag / D-tier / permutation result
effect size / q-value / replicate coverage
threshold provenance / missingness flags
```

이 pass의 목적은 “데이터에서 unusual한 구조가 무엇인가”를 정하는 것이다. output은 biological claim이 아니라 anomaly candidate 목록이어야 한다.

### Pass B — Prior-aware interpretation

Pass A 후보에만 motif, curated KS, receptor/PPI, ChromaDB, external Co-Scientist evidence를 추가한다. AI는 각 candidate를 다음 중 하나로 분류한다.

| Label | 의미 |
|---|---|
| `evidence_concordant` | data와 independent prior가 같은 방향 |
| `evidence_mixed` | 일부 evidence가 지지하고 일부가 충돌 |
| `prior_conflict` | data pattern이 expected biology와 다름 |
| `insufficient_evidence` | data 또는 prior가 너무 약함 |

이후 Report는 data-derived observation을 먼저 제시하고, interpretation은 별도 문장으로 제한한다.

### Pass C — Validation recommendation

D2/D3, robust TMM evidence, high anomaly priority인 소수 후보만 post-analysis validation recommendation으로 보낸다. 이 단계에서만 targeted assay, inhibitor/knockdown, rescue, phosphosite mutant 같은 실험을 제안한다. 초기 unbiased phosphoproteomics acquisition에는 intervention을 강제하지 않는다.

## 7. AI guardrail 체크리스트

1. AI는 측정되지 않은 site, kinase, timepoint를 새 evidence로 만들 수 없다.
2. 모든 AI claim은 `source PTM/Wave`, `TMM profile type`, `D-tier`, `data/prior/ChromaDB provenance`를 링크해야 한다.
3. `gaussian_fallback`, `D0/D1`, `replicate unavailable`, `permutation unavailable` 후보는 강한 mechanism claim에서 제외한다.
4. AI가 만든 narrative는 data-only conclusion과 prior-assisted interpretation을 문단 또는 badge로 분리한다.
5. anomaly ranking rule, threshold, model version, input manifest를 저장한다.
6. external Co-Scientist 결과는 existing Discussion Evidence Packet quality gate를 통과한 후에만 Pass B evidence로 사용한다.
7. Report 결과와 ChromaDB 문헌이 불일치하면 둘 중 하나를 숨기지 않고 contradiction으로 기록한다.

## 최종 포지셔닝

TMM과 temporal precedence는 **AI가 prior에 맞는 story를 고르는 도구가 아니라**, unbiased time-course data에서 후보 구조를 먼저 발견하게 하는 quantitative substrate다. AI의 가장 좋은 역할은 그 구조에서 설명하기 어려운 특이점을 놓치지 않고, evidence concordance·conflict·uncertainty를 정리하며, 분석 종료 후 검증 가치가 높은 소수의 질문을 제안하는 것이다.

따라서 PTM-platform의 강한 학술적 주장은 다음과 같다.

> PTM-platform separates data-derived temporal discovery from prior-assisted interpretation. It uses TMM to preserve shared kinase attribution, temporal precedence to quantify observed order without causal overclaiming, and AI only as a provenance-constrained anomaly triage and hypothesis-prioritization layer.

## References

[1] Xiao D, Lin M, Liu C, et al. [SnapKin: a snapshot deep learning ensemble for kinase-substrate prediction from phosphoproteomics data](https://doi.org/10.1093/nargab/lqad099). *NAR Genomics and Bioinformatics*. 2023;5(4):lqad099.
