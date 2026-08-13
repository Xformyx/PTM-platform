# Temporal PTM 연구 방향 기반 업그레이드 검토

**작성일:** 2026-08-13  
**검토 기준 코드:** `main` at `a595823`  
**검토 대상:** `Temporal_PTM_PhD_Research_Direction.pdf` 및 현재 PTM-platform 구현  
**작성 목적:** Temporal PTM Wave를 박사학위의 중심 검증 가능 방법론으로 발전시키기 위한 코드·데이터·평가 로드맵 제안

## 요약 판단

첨부 문서의 핵심 방향은 타당하며, 현재 시스템은 이미 **해석 가능한 Version 1 baseline**을 상당 부분 갖추고 있다. 특히 protein-abundance 보정 PTM 정량, signed temporal co-movement, co-wave의 kinase/receptor 연결, TMM 기반 shared-substrate 기여도 분리, Data-Grounded Analysis, 그리고 외부 Co-Scientist의 evidence packet 연동은 문서가 제시한 연구 스토리의 출발점으로 충분하다.

다만 현재의 핵심 temporal inference는 여전히 고정 임계값, zero-lag Pearson correlation, hand-authored kinase timing tier, condition 평균 벡터 중심으로 작동한다. 따라서 다음 핵심 명제를 아직 직접 검증하지는 못한다.

> **Temporal PTM Wave가 개별 PTM site 또는 static enrichment보다 kinase activation을 더 정확하고 강건하게 설명하는가?**

현 단계에서 가장 중요한 업그레이드는 복잡한 Transformer나 agent를 먼저 추가하는 것이 아니라, **Temporal PTM Wave의 공식 정의·품질지표·benchmark·재현성 검증 층을 구축하는 것**이다. 이를 통해 현재의 heuristic이 논문 가능한 baseline이 되고, 이후 lag-aware model 및 learned representation의 비교 기준이 된다.

| 결론 | 판단 |
|---|---|
| 현 시스템의 학술적 위치 | 해석 가능하고 biologically informed한 Temporal PTM Wave baseline |
| 가장 큰 연구 공백 | Wave vs Site의 정량 benchmark와 wave의 재현성·교란 검증 부재 |
| 가장 큰 코드 위험 | 서로 다른 두 co-wave 구현과 hard-coded temporal prior가 결과를 과도하게 결정할 가능성 |
| 가장 우선할 구현 | Canonical Wave Contract + Benchmark Harness + Threshold/Time Ablation |
| Co-Scientist의 적절한 위치 | 핵심 Wave 모델 위의 evidence-grounded scientific reasoning layer |

---

## 1. 문서 제안과 현재 코드의 대응

| 문서의 핵심 제안 | 현재 구현 상태 | 근거 코드 | 평가 |
|---|---|---|---|
| Protein-normalized site-level PTM quantification | 구현됨 | `workers/preprocessing/core/ptm_quantification.py` | 강한 baseline |
| Temporal PTM vector | 구현됨 | `vector_plot_raw_data`, `temporal_comovement_node.py` | 집계 Log2FC vector 중심 |
| Signed temporal co-wave | 구현됨 | `temporal_comovement_node.py` | zero-lag Pearson 중심 |
| Wave 기반 kinase inference | 구현됨 | `temporal_kinase_scoring.py`, TMM/NNLS | heuristic + contribution 분리 혼합 |
| Receptor–kinase–substrate cascade | 구현됨 | `orders.py`, network/cascade nodes | 시간적 설명은 가능하나 edge 확률/검증 부족 |
| Lag-aware dependency | 부분 구현 | `temporal_analysis.py` | first-threshold lag 요약; wave 간 dependency model 아님 |
| Soft biological prior | 미구현 | `temporal_kinase_scoring.py` | canonical time window가 hard score/bonus로 작동 |
| Replicate-aware wave reproducibility | 미구현 | preprocessing에는 replicate 값 존재 | report-time wave는 조건 평균 벡터 사용 |
| Wave vs Site benchmark | 미구현 | 테스트는 기능 회귀 중심 | 성능 비교용 dataset/label/metric harness 부재 |
| Learned temporal representation | 미구현 | — | 연구 2단계 과제 |
| Perturbation-aware directional validation | 미구현 | 일부 inhibitor 서술 및 lag 분석 | 표준화된 perturbation benchmark 부재 |
| Data-grounded Co-Scientist | 부분 구현 | external packet node, writer, ChromaDB | evidence gating은 구현; 정량 평가·critic workflow는 확장 필요 |

---

## 2. 즉시 해결해야 할 구조적 문제

### 2.1 Co-wave 구현을 하나의 canonical engine으로 통합해야 한다

현재 co-wave 결과는 두 경로에서 계산된다. Report Graph의 `temporal_comovement_node.py`는 signed Pearson distance와 average-linkage hierarchical clustering을 사용한다. 반면 `api-server/app/api/orders.py`의 receptor score 경로는 별도의 greedy Pearson clustering과 고정 `0.7` threshold를 사용한다. 같은 Order라도 화면·receptor score·Report에 서로 다른 cluster가 사용될 수 있다.

이 중복은 단순 유지보수 문제가 아니라 논문 benchmark의 재현성을 약화시킨다. **하나의 canonical Temporal Wave Engine**이 모든 API, RAG, report, receptor/kinase score에 동일한 `TemporalWaveResult`를 제공하도록 바꾸는 것이 우선이다.

권장 계약은 다음과 같다.

```text
TemporalWaveResult v1
├── analysis_config: 알고리즘/threshold/version/seed
├── time_axis: 원 단위 timepoint 및 시간 간격
├── input_qc: 결측치·replicate·normalization 상태
├── waves[]
│   ├── wave_id, member PTM sites, mean trajectory
│   ├── direction, peak window, pattern
│   ├── coherence, amplitude, lag dispersion
│   ├── replicate stability, dataset reproducibility
│   ├── kinase enrichment, pathway consistency
│   ├── prior agreement / prior conflict
│   └── evidence tier
└── unassigned_sites / exclusions / diagnostics
```

이를 `workers/common/temporal_wave/` 또는 `api-server/app/services/temporal_wave/`처럼 공용 모듈로 두고, 기존 `temporal_comovement_node.py`와 `orders.py`는 이 결과를 소비하는 adapter가 되게 하는 것이 적절하다.

### 2.2 Wave를 “cluster”가 아니라 검증 가능한 functional unit으로 정의해야 한다

현재 cluster는 correlation mean, peak, pattern, pathway/GO annotation을 이미 갖지만, 문서가 제안한 functional signaling unit의 조건을 통합 점수·명시적 QC로 보존하지 않는다. 아래 항목을 별도 scalar와 provenance로 저장해야 한다.

| Wave criterion | 현재 상태 | 권장 업그레이드 |
|---|---|---|
| Temporal coherence | 평균 Pearson r | Pearson, Spearman, lag-aware similarity를 분리 기록 |
| Direction consistency | signed clustering | positive/negative member 비율 및 sign entropy 기록 |
| Activation window | mean-profile peak | peak time의 bootstrap CI 및 peak dispersion 기록 |
| Amplitude | member max FC | robust median/IQR 및 de novo 분리 |
| Kinase coherence | shared kinase annotation | hypergeometric/permutation enrichment와 FDR |
| Pathway coherence | GO/pathway overlap | enrichment effect size, FDR, gene coverage |
| Replicate stability | 없음 | replicate bootstrap에서 membership Jaccard/ARI |
| Dataset reproducibility | 없음 | independent dataset에서 wave matching score |
| Perturbation sensitivity | 없음 | known inhibitor에서 target-wave suppression effect |

`wave_confidence`는 단일 “진실 확률”처럼 해석하지 말고, 위 dimension을 가진 **evidence profile**로 제공해야 한다. 그래야 낮은 prior agreement지만 높은 data coherence를 가진 신규 후보를 걸러내지 않는다.

### 2.3 Hard timing rule을 soft prior로 내려야 한다

`temporal_kinase_scoring.py`의 `SIGNALING_CASCADES`, `WAVE_TIER_KINASES`, `compute_temporal_fit_score`, tier-forced redistribution은 잘 알려진 cascade를 정리하는 데 유용하다. 그러나 canonical window와 tier가 kinase reassignment에 직접적인 점수와 강제 분리를 제공하므로, context-specific delayed activation을 과소평가할 수 있다.

권장 방식은 score를 다음처럼 분리하는 것이다.

```text
posterior kinase evidence
  = data likelihood
  + λ_prior × biological timing prior
  + λ_motif × motif evidence
  + λ_ks × curated kinase–substrate evidence
  + λ_wave × wave coherence
```

여기서 `λ_prior`는 고정 상수가 아니라 benchmark 또는 calibration set에서 조정하고, report에는 `prior_agreement`, `prior_conflict`, `data_override`를 각각 표시해야 한다. **prior conflict는 오류가 아니라 discovery 후보**가 될 수 있다.

---

## 3. 최우선 업그레이드: Wave vs Site Benchmark

문서에서 제시한 가장 중요한 질문은 현재 시스템이 즉시 구현해야 할 평가 프레임이다. 이 benchmark는 모델 복잡도보다 먼저 확립해야 하며, 새 model의 go/no-go 기준이 된다.

### 3.1 비교 방법

| Arm | 방법 | 현재 구현 활용 |
|---|---|---|
| A | Individual site 기반 kinase score | 기존 PTM site 및 curated kinase-substrate relation |
| B | Static enrichment / KSEA-like score | time 축을 집계한 score |
| C | Current heuristic Temporal Wave | 현재 canonical wave engine으로 freeze |
| D | TMM-weighted Temporal Wave | 기존 NNLS shared-substrate contribution 사용 |
| E | Lag-aware Wave | 신규, Stage 2 |
| F | Learned Wave | 신규, benchmark 통과 후 Stage 3 |

### 3.2 평가 데이터와 지표

실제 공개/내부 perturbation dataset만 사용해야 하며, 시뮬레이션 데이터로 성능을 주장해서는 안 된다. 최소 manifest에는 stimulus/inhibitor, target kinase, species, cell line, timepoints, replicate 수, MS platform, known expected target/wave를 versioned JSON/CSV로 기록한다.

| 평가 목적 | 권장 지표 |
|---|---|
| Target kinase recovery | AUROC, AUPRC, top-k recovery, rank of known target |
| Temporal correctness | target wave peak-time error, temporal ordering accuracy |
| Quantitative reliability | calibration curve, Brier score, confidence-stratified precision |
| Wave robustness | bootstrap membership stability, threshold sensitivity, missingness/noise sensitivity |
| Generalization | leave-dataset/cell-line/species/platform-out performance |
| Biological validity | inhibitor-induced downstream wave suppression and effect size |

### 3.3 반드시 포함할 ablation

Time permutation은 필수다. timepoint 순서를 무작위로 섞은 뒤 동일 pipeline의 성능이 유지되면 temporal claim은 약해진다. 여기에 wave 제거, kinase prior 제거, motif 제거, protein normalization 제거, TMM 제거를 포함해 **어떤 성능 이득이 실제 temporal structure에서 왔는지** 분해해야 한다.

---

## 4. Lag-aware 및 Dynamic Graph 발전 방향

현재 `temporal_analysis.py`는 PTM과 protein abundance의 first-threshold time lag를 요약한다. 이는 report context에는 유용하지만, 현재 코드의 `Causal` 또는 `causal` 표현은 observational time-series만으로는 강하다. 즉시 다음처럼 용어를 조정하는 것이 권장된다.

| 현재 표현 | 권장 표현 |
|---|---|
| Causal | `temporal precedence–supported` |
| Causal: PTM modification precedes… | `PTM change precedes…; candidate propagation relationship` |
| Signal propagation | `putative temporal propagation` |

lag-aware wave 모델은 최소 4개 이상의 informative timepoint에서만 활성화해야 한다. 시간축이 불규칙한 경우 index shift보다 실제 minute 단위를 사용하고, 결과에는 lag value, bootstrap CI, similarity gain over zero-lag, edge direction confidence를 저장해야 한다.

권장 순서는 다음과 같다.

1. **Lag-aware similarity baseline:** 제한된 lag window에서 cross-correlation을 계산하고 pair별 최적 lag를 기록한다.
2. **Lag-aware clustering:** zero-lag similarity와 최적 lag similarity를 옵션으로 비교한다.
3. **Directed candidate edge:** curated kinase-substrate/PPI edge에 한해 temporal precedence score를 추가한다.
4. **Perturbation validation:** known inhibitor/stimulation data에서 edge의 방향·wave suppression을 검증한다.

Dynamic graph는 이 단계 이후의 결과이며, graph arrow는 `causal`이 아니라 `evidence-supported directed signaling hypothesis`로 표기해야 한다.

---

## 5. TMM을 다음 단계의 정량 baseline으로 강화

현재 `build_kinase_profiles_from_data`, `deconvolve_shared_ptm`, `compute_weighted_kinase_scores`는 NNLS를 이용해 shared PTM의 kinase 기여도를 분리한다. 이는 단순 “shared substrate를 임의 배분”하는 것보다 강한 정량 baseline이다.

다만 논문 수준으로 강화하려면 contribution ratio만 저장하는 것을 넘어 아래 diagnostics가 필요하다.

| TMM 보강 | 이유 |
|---|---|
| reconstruction residual / R² | PTM trajectory가 후보 kinase profile로 설명되는지 확인 |
| profile condition number | 후보 profile이 거의 동일하여 분리가 불안정한 경우 표시 |
| bootstrap contribution CI | replicate/시간점 sampling에 대한 기여도 안정성 평가 |
| leave-one-substrate-out profile | 자기 데이터로 만든 profile에 대한 circularity 완화 |
| exclusive vs shared 분리 성능 | TMM이 실제 target recovery에 기여하는지 benchmark |
| `unresolved_shared` class | 약한 분리를 강제 kinase attribution으로 표현하지 않기 위함 |

TMM의 가중치도 hard reassignment보다 후보 kinase별 evidence posterior의 한 항으로 사용해야 한다.

---

## 6. Replicate-aware wave 안정성: 현재 데이터 자산을 활용할 수 있는 즉시 과제

전처리의 `ptm_quantification.py`는 Welch test를 위해 replicate-level values를 이미 구성한다. 반면 report-time co-wave 분석은 condition 수준 aggregate Log2FC 행렬을 사용한다. 따라서 raw replicate를 다시 계산하지 않고도, 전처리 단계에서 아래 artifact를 저장하면 wave stability를 추가할 수 있다.

```text
temporal_replicate_matrix_v1
├── PTM site key
├── condition/timepoint
├── replicate identifier
├── protein-normalized PTM abundance / Log2FC
├── quality flags (missing, pseudocount, localization)
└── preprocessing config/version
```

이를 사용해 timepoint 내 replicate bootstrap을 수행하고, 매 bootstrap에서 wave detection 후 original wave와의 Jaccard/ARI를 계산한다. 안정성이 낮으면 wave를 삭제하지 말고 `low_replicate_stability`로 표기해 report·Co-Scientist가 강한 mechanistic claim을 만들지 못하게 한다.

---

## 7. Learned Temporal PTM Representation은 Benchmark 통과 뒤 시작해야 한다

문서의 representation learning 방향은 유망하지만, 시간점 수가 적은 일반 phosphoproteomics dataset에서 처음부터 큰 Transformer 또는 temporal GNN을 사용하면 데이터 부족과 leakage 문제가 발생할 수 있다. 우선 sequence/motif/position/localization/PTM type/relative abundance/protein abundance/pathway context를 feature schema로 고정하고, 간단한 모델부터 비교하는 것이 바람직하다.

| 단계 | 권장 모델 | 검증 목표 |
|---|---|---|
| 1 | spline/temporal basis + regularized metric | small-T trajectory와 lag를 안정적으로 표현 |
| 2 | contrastive PTM encoder | same-kinase/pathway PTM이 가깝게 배치되는지 확인 |
| 3 | masked-timepoint reconstruction | 관측하지 않은 timepoint 예측 |
| 4 | perturbation-response prediction | treatment 별 response generalization |
| 5 | dynamic graph neural/continuous-time model | 충분한 dataset 이후에만 비교 |

학습·평가 split은 PTM site를 무작위로 나누지 말고 **dataset, treatment, cell line, 또는 kinase family 단위**로 분리해야 실질적인 generalization을 평가할 수 있다.

---

## 8. Co-Scientist 업그레이드 방향

최근 구현된 외부 Discussion Evidence Packet은 외부 세션의 가설을 Report에 무비판적으로 복사하지 않고, schema/quality gate/PTM site/literature re-resolution을 통과한 최대 두 후보만 Addendum 또는 opt-in Enhanced Discussion으로 사용하는 안전한 기반이다.

문서의 data-first Co-Scientist 목표에 도달하려면 다음을 추가해야 한다.

| 구성 요소 | 현재 | 다음 업그레이드 |
|---|---|---|
| Quantitative grounding | Data-Grounded seed + packet validation | Wave ID, measured PTM evidence, TMM, lag, stability를 claim에 직접 연결 |
| Evidence agent | ChromaDB re-resolution | claim-level evidence ledger 및 contradiction coverage |
| Skeptic / critic | 외부 workflow 의존 | 각 claim의 strongest counter-evidence와 unsupported-assumption 표시 |
| Alternative hypothesis | 제한적 | 동일 wave를 설명하는 대체 kinase/cascade 후보 비교 |
| Experiment design | 외부 packet 기반 | perturbation target, expected direction, time window, readout을 구조화 |
| Meta-review | 제한적 | claim confidence와 evidence provenance 기반 release gate |
| Evaluation | packet regression test | blind expert review, citation correctness, unsupported-claim rate, temporal literature holdout |

핵심 데이터 구조는 `ClaimLedgerEntry`이다.

```text
claim_id, wave_id, candidate_kinase/cascade,
measured_ptm_sites, quantitative_metrics,
supporting_literature, counter_evidence,
assumptions, perturbation_test, confidence, report_locations
```

이 구조가 있으면 LLM이 새 signaling result를 발명할 여지를 줄이고, Report의 문장·citation·반론·실험제안을 모두 추적할 수 있다.

---

## 9. 권장 구현 우선순위

| 우선순위 | 작업 | 기대 효과 | 난이도 | 선행 조건 |
|---|---|---:|---:|---|
| **P0** | Canonical Temporal Wave Contract 및 두 co-wave 구현 통합 | 재현성·단일 진실원 확보 | 중간 | 없음 |
| **P0** | Wave formal definition + evidence profile + threshold provenance | 방법론 주장 가능 | 중간 | canonical engine |
| **P0** | Wave vs Site benchmark harness + time permutation | 핵심 명제 검증 | 중간 | 실제 perturbation dataset manifest |
| **P1** | replicate artifact 및 bootstrap wave stability | 강건성·quality control | 중간 | 전처리 artifact 저장 |
| **P1** | soft prior / prior-conflict reporting | discovery bias 감소 | 중간 | benchmark calibration |
| **P1** | lag-aware similarity baseline | sequential signaling 검증 | 중간 | 4개 이상 informative timepoint |
| **P1** | TMM diagnostics 및 contribution CI | shared substrate attribution 신뢰도 | 중간 | replicate artifact |
| **P2** | perturbation-aware directed graph | 방향성 검증 | 높음 | curated perturbation benchmark |
| **P2** | learned temporal representation | 새로운 computational contribution | 높음 | benchmark 및 다수 dataset |
| **P2** | Co-Scientist claim ledger/holdout evaluation | AI reasoning 논문화 | 중간~높음 | stable wave evidence schema |
| **P3** | multi-PTM joint representation | 확장성 | 높음 | phosphorylation core validation 완료 |

## 10. 0–6개월 실행 제안

### 0–6주: baseline freeze와 공식화

현 `temporal_comovement_node.py`, `temporal_kinase_scoring.py`, API-level co-wave route의 설정을 versioned config로 옮긴다. 기존 결과를 재현할 수 있는 golden Order/dataset fixture를 만들고, temporal wave output schema를 고정한다. 이 단계의 산출물은 **Wave Definition v1**과 **Baseline Reproducibility Report**다.

### 6–12주: 핵심 benchmark

실제 inhibitor/stimulation time-series 데이터의 manifest를 만들고, A–D 방법을 비교한다. time permutation, threshold sensitivity, missingness, replicate downsampling을 포함한다. 결과가 “Current Wave가 Site/Static보다 일관되게 낫다”를 지지하지 않는다면 learned model 개발 전에 wave definition과 score를 재검토한다.

### 3–6개월: 안정성, lag, soft prior

replicate bootstrap으로 wave stability를 추가하고, lag-aware baseline과 soft-prior score를 도입한다. directed edge는 perturbation 없이 causal로 표기하지 않는다. 이 단계에서 첫 method/baseline 논문 또는 핵심 Wave 논문의 결과 기반이 마련된다.

---

## 최종 권고

현재 플랫폼을 새 AI 모델로 대체해서는 안 된다. 현재의 interpretable heuristic, TMM, co-wave annotation, RAG/Co-Scientist integration을 **명시적으로 Version 1 baseline**으로 freeze하고, 그 위에 재현성·benchmark·lag-aware·soft-prior 요소를 순차적으로 쌓는 전략이 가장 강하다.

> 최우선 구현 목표는 “더 복잡한 모델”이 아니라, **Temporal PTM Wave가 개별 site 및 static enrichment보다 kinase activity를 더 잘 설명한다는 주장을 반증 가능하고 재현 가능하게 시험하는 플랫폼**이다.

Co-Scientist는 이 검증된 quantitative layer 위에서 claim, counter-evidence, alternative hypothesis, and experiment proposal을 추적하는 scientific reasoning layer로 확장해야 한다. 그렇게 하면 product 기능을 넘어, 첨부 문서가 제안한 **Evidence-Grounded AI Co-Scientist**의 독립적인 연구 기여도 만들 수 있다.

---

## References

[1] 사용자 제공 문서. *Temporal PTM Vector / Temporal PTM Wave 기반 Kinase Signaling Inference와 Evidence-Grounded AI Co-Scientist: 박사학위 연구방향 정리*. 2026년 8월. 로컬 파일: `Temporal_PTM_PhD_Research_Direction.pdf`.

[2] PTM-platform 현재 코드베이스, `main` at `a595823`; 주요 검토 파일: `workers/report_generation/core/nodes/temporal_comovement_node.py`, `api-server/app/services/temporal_kinase_scoring.py`, `workers/report_generation/core/temporal_analysis.py`, `api-server/app/api/orders.py`.
