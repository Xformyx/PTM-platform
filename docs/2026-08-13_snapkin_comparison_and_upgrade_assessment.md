# SnapKin 논문과 PTM-platform 비교: 차별점과 도입 평가

## 검토 대상

이 문서는 Xiao *et al.*의 **SnapKin: a snapshot deep learning ensemble for kinase-substrate prediction from phosphoproteomics data**와 현재 PTM-platform 코드를 비교한다. 논문은 phosphoproteomics에서 kinase–substrate(KS) 관계를 **kinase별 supervised ranking 문제**로 정의한다. 반면 PTM-platform은 단일 Order의 unbiased time-course PTM 데이터에서 Wave, TMM, directionality, 문헌 근거를 결합해 **조건 특이적 signaling hypothesis를 생성·검증·보고**하는 시스템이다.[1]

> 결론적으로 두 방법은 경쟁 관계라기보다 분석 계층이 다르다. SnapKin은 “이 phosphosite가 특정 kinase의 substrate일 확률을 얼마나 높게 둘 것인가”에 강하고, PTM-platform은 “이 조건에서 어떤 temporal Wave와 kinase module이 어떻게 관찰되며, 어떤 기전 가설을 우선 검토할 것인가”에 강하다.

## 논문의 핵심 방법

SnapKin은 7개 공개 phosphoproteomics 데이터셋에서 12개 kinase의 알려진 substrate ranking을 평가했다. 입력은 phosphosite의 정량 trajectory, motif score, sequence encoding이며, 비교적 적은 validated positive label과 noisy data를 다루기 위해 세 가지 학습 전략을 결합했다.[1]

| SnapKin 구성 | 논문의 역할 | 핵심 유의점 |
|---|---|---|
| **Pseudo-positive** | 알려진 positive 두 개의 feature vector 평균으로 추가 positive-like example을 구성 | label 부족을 완화하지만 label 오류가 증폭될 위험이 있음 |
| **Data-resampling ensemble** | 서로 다른 negative subset으로 여러 model을 학습 | 평균 성능뿐 아니라 prediction stability를 평가 |
| **Snapshot DNN ensemble** | 하나의 DNN training trajectory에서 여러 near-optimal snapshot을 ensemble | 다수 데이터셋에서 기존 비교 모델보다 높은 ranking 성능을 보고 |
| **CKSAAP sequence encoding** | k-spaced amino-acid pair feature를 dynamics·motif와 결합 | 일부 motif-only 모호성을 줄이는 추가 sequence representation |
| **PPI feature ablation** | STRING 기반 kinase–host-protein proximity를 추가 비교 | 해당 평가에서는 예측 정확도 개선이 뚜렷하지 않았음 |

논문은 5-fold cross-validation을 50회 반복하고 precision–recall 기반 성능과 반복 간 변동성을 함께 비교했다. 이 design의 중요한 메시지는 “더 복잡한 model”보다 **성능과 안정성을 함께 benchmark해야 한다**는 점이다.[1]

## 현재 PTM-platform의 분석 구조

| 계층 | 현재 구현 | 산출물 |
|---|---|---|
| PTM annotation | motif, curated kinase sources, UniProt/iPTMnet 계열 근거 | 후보 kinase–site 목록 |
| Canonical Temporal Wave | signed profile coherence, average linkage, threshold provenance | 재현 가능한 co-wave membership와 evidence profile |
| TMM | shared PTM profile을 candidate kinase profile의 non-negative contribution으로 분해 | exclusive/shared substrate 및 contribution |
| Directionality | 실제 minute 기반 onset/peak lag, lag-aware similarity, bootstrap, time permutation, D0–D3 | temporal precedence evidence; 기본 causality는 `not_tested` |
| Data-Grounded Analysis | temporal cascade, co-wave, autophosphorylation, TMM, vector PTM을 통합 | 데이터 근거 가설·수치 검증 |
| External Co-Scientist | 선택된 세션의 Discussion Evidence Packet을 quality gate 후 연동 | provenance가 보존된 exploratory interpretation |
| Report | Results/Discussion/validation proposal 분리 | 관찰 결과와 후속 validation recommendation 분리 |

## 직접적인 차별점

### 1. 분석 단위: site별 supervised ranking 대 조건 특이적 temporal system

SnapKin은 각 kinase에 대해 site를 rank하는 classifier다. 따라서 입력은 site-level feature이고, 주요 평가 지표는 known substrate의 ranking이다. 현재 PTM-platform은 site annotation을 출발점으로 쓰지만, final interpretation은 Wave, kinase module, receptor/cascade, non-PTM effector, temporal precedence 단위로 수행한다. 이는 단일 phosphosite의 정답 예측보다 **실험 조건에서의 signaling organization**을 설명하는 데 더 적합하다.

그러나 이 차이는 자동적인 우위가 아니다. PTM-platform은 아직 kinase-specific prediction calibration이나 PR-AUC/MRR 같은 supervised KS benchmark가 없으므로, **“SnapKin보다 KS 예측이 우수하다”라고 주장할 근거는 현재 없다.** 반대로 SnapKin은 Wave·TMM·time-lag·network directionality를 모델링하지 않으므로, dynamic signaling reconstruction의 대안도 아니다.

### 2. Temporal 정보의 사용 방식

SnapKin은 정규화된 phosphosite dynamics를 classifier feature로 사용한다. 시간축은 예측 성능을 돕는 고차원 vector이지, onset/peak lag 또는 pathway-level temporal precedence의 명시적 산출물은 아니다.[1]

PTM-platform은 Canonical Temporal Wave와 `DirectedTemporalRelationship`을 통해 onset/peak lag를 minute 단위로 분리하고, D0–D3 directionality tier를 산출한다. 따라서 “profile이 분류에 유용한가”뿐 아니라 “어떤 event가 언제 선행했는가”를 보고할 수 있다. 이 부분은 platform의 명확한 차별점이지만, D-tier는 관찰적 evidence이며 causal edge가 아니라는 현재의 guardrail을 유지해야 한다.

### 3. Shared substrate의 처리

SnapKin은 kinase별 독립 classifier를 학습하므로 하나의 site가 여러 kinase에 높은 score를 받을 수 있다. PTM-platform은 TMM으로 shared PTM profile을 multiple candidate kinase profile의 기여도로 분해하고 exclusive/shared 상태를 함께 기록한다. 이는 motif가 넓게 겹치는 AKT–SGK–S6K–RSK 같은 문제에서 **“여러 후보 중 어느 kinase가 이 조건·이 time-course를 얼마나 설명하는가”**를 보여주는 해석 가능한 보완책이다.

TMM 역시 training된 ground truth가 아니다. 따라서 TMM contribution은 functional attribution candidate이지 definitive kinase assignment가 아니며, SnapKin식 supervised benchmark로 별도 교차 검증할 가치가 있다.

### 4. Prior와 interpretation의 경계

SnapKin은 PhosphoSitePlus positive label, motif, CKSAAP, PPI를 supervised feature로 사용한다. PTM-platform은 `SIGNALING_CASCADES`의 expected time window와 receptor/cascade prior를 보유하지만, 현재 코드의 temporal kinase score에는 사전 지식 기반 expected peak window가 직접 들어간다.

이 구조는 user-facing 해석에는 유용하지만, discovery bias가 생길 수 있다. 예를 들어 insulin experiment에서 PI3K–AKT timing prior는 biological plausibility score로 사용하되, data-derived Wave/TMM/directionality score와 구분하여 기록해야 한다. 알려진 path와 어긋나는 Wave를 자동 제거하지 말고 `prior_conflict` 또는 `novel_temporal_candidate`로 보존하는 것이 SnapKin과 차별되는 unbiased discovery의 핵심이다.

### 5. Reproducibility의 정의

SnapKin은 classifier performance의 반복 cross-validation 표준편차로 model stability를 평가한다. PTM-platform은 새 Directionality contract에서 bootstrap, leave-one-timepoint-out, time-order permutation, threshold sensitivity를 도입해 **관찰된 temporal relationship의 안정성**을 평가한다.

두 안정성은 다르며 모두 필요하다. SnapKin의 안정성은 “같은 task에서 classifier ranking이 흔들리는가”이고, platform의 안정성은 “같은 experiment의 Wave/lag가 resampling과 threshold 변화에 견디는가”이다.

## 논문에서 배울 점

### A. 성능과 불확실성을 함께 benchmark하라

SnapKin의 가장 강한 교훈은 method claim마다 repeated validation과 variance를 보고한다는 점이다. PTM-platform도 forthcoming insulin time-course benchmark에서 다음을 함께 보고해야 한다.

| 비교 | 필수 지표 |
|---|---|
| Site-only 대 Wave/TMM | known kinase substrate recovery, Precision@k, Recall@k, MRR 또는 PR-AUC |
| Temporal contribution | original time order 대 time-permuted order의 성능 차이 |
| Wave robustness | bootstrap membership stability, threshold sensitivity, leave-one-timepoint-out |
| Prior 영향 | data-only 대 data + temporal prior 대 data + prior + TMM ablation |
| Generalization | insulin training/selection과 독립된 time-course 또는 species/condition에서 재평가 |

이 benchmark는 PTM-platform을 SnapKin과 직접 경쟁시키기 위한 것이 아니라, **각 feature가 platform의 claim에 실제 기여하는지** 보여주기 위한 것이다.

### B. Broad motif 문제에는 richer sequence feature가 필요하다

현재 platform은 motif family와 temporal context를 사용해 AKT/S6K/RSK/SGK 같은 broad motif family를 분해한다. SnapKin의 CKSAAP 결과는 position-specific motif score보다 더 풍부한 local sequence encoding이 kinase discrimination에 도움을 줄 수 있음을 시사한다.[1]

권장 도입은 즉시 deep learning model을 배포하는 것이 아니라, **feature-ablation harness**다. 31-residue window에서 기존 motif, CKSAAP, physicochemical encoding을 각각 계산하고, known KS benchmark에서 추가 feature가 실제로 subfamily calibration을 개선할 때만 score로 승격한다. 그렇지 않으면 sequence feature는 explanation-only 정보로 남겨야 한다.

### C. Resampling ensemble은 score가 아니라 confidence layer로 먼저 도입하라

Pseudo-positive self-training을 바로 적용하면 error propagation 가능성이 있다. 반면 SnapKin의 resampling ensemble 원리는 platform에 낮은 위험으로 적용할 수 있다. 예를 들어 PTM subset, eligible kinase source, TMM anchor, timepoint를 반복 resample해 kinase score·rank·Wave membership의 분포를 저장할 수 있다.

이 경우 출력은 `kinase_score_mean`, `kinase_score_CI`, `rank_stability`, `selection_frequency`가 된다. 이는 기존 D-tier와 잘 맞지만, Wave directionality의 stability와 KS attribution stability를 **별도 축**으로 유지해야 한다.

### D. PPI는 predictive core가 아니라 support evidence로 유지하라

논문은 PPI score 추가가 평가한 조건에서 mTOR prediction accuracy를 개선하지 못했다고 보고했다.[1] 현재 platform의 PPI/receptor/signal-flow 정보는 network interpretation에는 유용하지만, 이를 primary kinase score의 강한 가중치로 사용하면 hub bias와 annotation density bias를 만들 수 있다.

따라서 PPI는 다음처럼 처리하는 것이 권장된다.

```text
data-derived Wave / TMM / temporal score → primary evidence
motif / sequence classifier              → substrate recognition support
PPI / receptor / literature              → biological plausibility support
```

### E. Label quality와 evidence type을 명시적으로 모델링하라

논문도 curated positive label의 validation type과 biological context가 다르며 false positive가 있을 수 있다고 지적한다.[1] Platform이 향후 supervised layer를 도입할 때는 모든 KS annotation을 같은 positive로 취급하지 말아야 한다.

| Evidence provenance | 권장 사용 |
|---|---|
| Direct site-specific biochemical/targeted MS validation | 높은 training/sample weight |
| Literature-curated association | 중간 weight, provenance 기록 |
| Motif/database-only prediction | negative가 아닌 unlabeled 또는 soft prior |
| Platform TMM/Wave-derived candidate | training positive로 사용하지 않고 evaluation 대상 |

## 권장 도입 우선순위

| 우선순위 | 작업 | 이유 | 지금 바로 SnapKin을 넣지 않는 이유 |
|---|---|---|---|
| **S1** | Insulin real-data manifest로 data-only/motif/TMM/Wave ablation benchmark 완성 | platform 자체 claim의 기준선 확보 | 특정 external model score를 넣으면 source attribution이 흐려짐 |
| **S2** | Kinase attribution resampling ensemble + rank stability | SnapKin의 가장 안전한 교훈을 불확실성 layer로 적용 | pseudo-positive label 증강보다 낮은 bias 위험 |
| **S3** | CKSAAP/sequence feature extraction + held-out benchmark | broad motif subfamily 분해를 정량적으로 평가 | 성능 이득이 확인되기 전 deep model 배포는 과도함 |
| **S4** | SnapKin 또는 유사 pretrained model을 optional external evidence source로 adapter화 | independent orthogonal KS ranking을 제공 | platform score와 무가중 합산하면 calibration이 깨질 수 있음 |
| **S5** | Evidence-weighted multi-dataset training | 장기적으로 species/condition transferability 강화 | labelled corpus, split strategy, leakage control이 먼저 필요 |

## 실제 통합 시 지켜야 할 원칙

1. SnapKin score는 `snapkin_support_score`라는 별도 provenance field로 저장하고, 기존 motif/TMM/Wave score를 덮어쓰지 않는다.
2. 학습·validation split은 phosphosite 또는 protein family leakage를 막도록 설계한다. 같은 kinase의 매우 유사한 sequence가 train/test에 섞이면 성능이 과대평가될 수 있다.
3. 공개 pretrained model을 사용해도 Rat ortholog mapping, site coordinate, isoform mapping을 audit해야 한다.
4. Dynamic time-course에서 high score site와 high contribution site가 다를 수 있음을 허용한다. 하나는 biochemical substrate likelihood이고 다른 하나는 조건 특이적 temporal attribution이다.
5. Co-Scientist와 LLM은 independent model disagreement를 감추지 말고 `evidence_concordant`, `evidence_mixed`, `evidence_conflicting`으로 보고해야 한다.

## 최종 평가

PTM-platform의 독창성은 SnapKin보다 더 높은 site-level KS prediction score를 당장 주장하는 데 있지 않다. 더 강한 차별점은 **unbiased time-course PTM에서 site annotation → Wave → TMM contribution → evidence-aware directionality → data-grounded hypothesis → optional post-analysis validation**으로 이어지는 해석 가능한 end-to-end reasoning chain이다.

SnapKin은 이 chain에서 특히 **sequence feature 확장**, **resampling 기반 attribution uncertainty**, **repeated benchmark discipline**, **label-quality-aware supervised learning**을 강화하는 좋은 reference다. 가장 좋은 전략은 SnapKin을 대체하거나 무비판적으로 흡수하는 것이 아니라, benchmark를 통과한 feature와 independently calibrated score만 platform의 evidence layer로 추가하는 것이다.

## References

[1] Xiao D, Lin M, Liu C, et al. [SnapKin: a snapshot deep learning ensemble for kinase-substrate prediction from phosphoproteomics data](https://doi.org/10.1093/nargab/lqad099). *NAR Genomics and Bioinformatics*. 2023;5(4):lqad099.
