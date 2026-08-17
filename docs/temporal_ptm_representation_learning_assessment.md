# Temporal PTM Representation Learning 도입 평가

작성일: 2026-08-17 (GMT+9)
상태: **도입 평가 완료 — 현재는 연구·benchmark 단계 권고, production scoring 변경 보류**

## 요약 결론

Representation Learning은 PTM-platform의 dense time-course 데이터를 더 잘 활용할 가능성이 있다. 특히 일정하지 않은 amplitude, 부분 결측, 같은 peak time이지만 서로 다른 상승·감쇠 형태, protein abundance와 modified-peptide signal의 불일치를 저차원 representation으로 정리해 **co-wave의 안정성 평가, unknown site의 neighborhood 탐색, exclusive substrate profile의 품질 평가**를 보완할 수 있다.

그러나 현 단계에서 이를 co-wave, TMM 또는 kinase ranking의 primary score로 대체해서는 안 된다. 현재 시스템의 가장 큰 강점은 raw time-resolved evidence, signed Pearson co-wave, TMM contribution provenance, minute-based directionality 및 explicit uncertainty를 보존하는 점이다. 한 개 또는 소수의 insulin experiment만으로 deep model을 학습하면 biological representation보다 condition·batch·missingness를 외우는 위험이 크다.

> **권장 원칙: representation은 현재 관측 증거를 대체하는 prediction layer가 아니라, raw evidence와 독립적으로 합의하거나 불일치하는지를 보여 주는 secondary, uncertainty-aware representation layer로 시작한다.**

## 현재 플랫폼에 이미 존재하는 representation의 기초

PTM-platform은 아직 neural representation learning을 쓰지 않지만, 다음과 같은 명시적 representation을 이미 보유한다.

| 현재 representation | 입력 | 산출물 | 장점 | 한계 |
|---|---|---|---|---|
| Track 2 temporal vector | protein-normalized modified-peptide log2FC | site × ordered-timepoint vector | 직접 관찰값이며 단백질 abundance로 보정됨 | noise, missingness, 같은 peak의 shape 차이를 모두 raw vector에 남김 |
| Canonical co-wave | Track 2 vector의 signed Pearson·average linkage | wave membership, coherence, peak dispersion | 재현 가능하고 해석 가능하며 threshold provenance 존재 | 선형 상관 및 explicit-fill missing policy에 민감 |
| Track 1 paired signal vector | apparent paired modified-peptide fraction/occupancy-logit | paired-form temporal balance | total proteome 맥락의 orthogonal corroboration | coverage가 제한적이고 physical absolute occupancy가 아님 |
| TMM kinase profile | exclusive substrate temporal profile | shared-site contribution, residual, confidence tier | condition-specific explanatory attribution | candidate profile collinearity와 sparse exclusive substrate에 제한 |
| Directionality contract | onset/peak lag, bootstrap, permutation | D0–D3 temporal-precedence evidence | causal claim을 제한하고 시간 정보를 명시적으로 검증 | 관찰형 데이터에서 causality는 판정하지 않음 |
| Multisite divergence | site-pair trajectory 및 TMM mixture distance | within-protein temporal divergence | same protein 내 PTM form의 이질성 보존 | 높은 차원 pattern을 site-pair별로만 검토 |

새 representation layer는 이 raw feature와 contract를 input으로 사용하되, 결과가 raw evidence를 가리는 black-box score가 되지 않아야 한다.

## 기대 효과

| 기대 효과 | 현재 한계 | representation layer의 가능한 보완 | 주장 경계 |
|---|---|---|---|
| Temporal shape 분리 | 동일 peak time이라도 transient, delayed, sustained, biphasic trajectory가 섞일 수 있음 | amplitude·slope·time gap·shape를 latent coordinate로 압축해 nearest-neighbor 탐색 | learned proximity는 co-regulation 또는 common kinase의 증명이 아님 |
| Missingness robustness | 외부 dataset 및 Track 1 pair에는 incomplete observation이 흔함 | mask-aware reconstruction error와 latent uncertainty 제공 | missing value를 사실처럼 보간하거나 zero로 대체하지 않음 |
| Co-wave stability | single Pearson threshold에서 wave membership이 경계에 있을 수 있음 | bootstrap/repeated masking에서 embedding-neighbor stability를 비교 | canonical wave는 유지하고 learned graph는 secondary evidence |
| TMM profile quality | exclusive substrate가 적거나 heterogeneous하면 data-driven profile 신뢰도가 낮음 | exclusive substrate latent dispersion으로 profile confidence를 보강 | contribution coefficient를 learned latent similarity로 직접 교체하지 않음 |
| Dark modified-peptide prioritization | annotated kinase가 없는 site는 motif/prior 기반 해석이 약함 | well-characterized site와의 reproducible temporal neighborhood 제공 | unknown site의 kinase를 직접 예측했다고 주장하지 않음 |
| Multisite pattern discovery | site pair 수가 많아 manual inspection이 어려움 | 동일 protein의 site embedding separation 및 cross-track discordance 요약 | structural/functional consequence는 별도 가설 |

대규모 phosphoproteomics에서 site co-regulation, sequence similarity, kinase interaction context를 결합한 model이 known co-regulation recovery와 kinase-substrate association prediction을 개선한 사례가 있다.[1] SnapKin도 temporal abundance feature와 motif/PPI feature를 결합한 ensemble이 kinase-substrate prediction의 성능과 안정성을 높일 수 있음을 보였다.[2] 다만 두 연구의 데이터 규모와 supervised label 구조는 현재의 single-condition dense Astral total-proteome experiment와 다르므로, 해당 성능을 PTM-platform에 그대로 기대해서는 안 된다.

## 권장 architecture: Mask-aware multi-view temporal representation

### 입력 계약

학습 단위는 gene만이 아니라 **modified-peptide form/site**다. 동일 protein의 다른 site가 서로 다른 kinetics를 보일 수 있으므로 protein-level aggregation은 encoder 이전에 수행하지 않는다.

```text
site/form i, timepoint t
  x_ptm(i,t)       = Track 2 protein-normalized modified-peptide log2FC
  x_protein(i,t)   = matched protein-group log2FC
  x_pair(i,t)      = Track 1 occupancy-logit delta (paired subset only)
  m(i,t)           = observed/missing mask
  se(i,t)          = replicate uncertainty or CV when available
  Δt(t)            = true minute spacing between timepoints
  q(i)             = q-value, localization/precursor quality, protein-group ambiguity
```

Track 1은 optional branch이며, pair가 없는 site를 0으로 채우지 않는다. paired and unpaired site가 함께 있는 dataset에서 branch availability mask를 model input과 output provenance에 남긴다.

### Version R1: 작은 self-supervised baseline

첫 구현은 transformer나 graph neural network가 아니라 **mask-aware temporal denoising autoencoder 또는 functional PCA baseline**이 적절하다. insulin dataset의 timepoint 수는 약 9개이고, 동일 condition의 site들은 독립 training cohort가 아니므로 과도한 parameter 수가 위험하다.

| 구성 | 권장 설정 | 이유 |
|---|---|---|
| Temporal encoder | 2-layer temporal convolution 또는 small GRU, latent 16–32D | 짧고 불규칙한 minute-scale sequence에서 parameter 수를 제한 |
| Multi-view fusion | Track 2 branch를 primary, protein branch를 context, Track 1 branch를 optional gated input | total-proteome 설계 의도를 보존하고 paired subset의 coverage bias를 제한 |
| Missingness | observed mask와 uncertainty-aware loss | absent peptide를 measured zero로 해석하지 않음 |
| Reconstruction objective | masked Track 2 reconstruction + optional protein/Track 1 reconstruction | label 없이 temporal structure를 학습 |
| Replicate objective | 같은 site의 biological replicate representation consistency | batch/noise보다 reproducible signal을 보존 |
| Temporal order objective | 실제 minute order와 permuted order를 구분하는 auxiliary task | dense time-course의 순서 정보를 representation에 보존 |
| Output | `temporal_embedding`, reconstruction error, embedding uncertainty, neighbor stability | downstream evidence용 provenance, direct kinase score 아님 |

입력은 whole trajectory를 한 vector로 다루되, absolute timepoint index 대신 실제 minutes와 interval `Δt`를 사용해야 한다. 0, 0.5, 1, 2.5, 5, 10, 15, 30, 60분처럼 불규칙한 sampling interval을 equal spacing으로 가정하면 insulin response의 early kinetics가 왜곡될 수 있다.

### Version R2: temporal co-regulation graph representation

R1이 cross-dataset benchmark를 통과한 뒤에만, site graph를 구축하는 node embedding을 검토한다. graph edge는 **raw evidence와 prior를 구분한 typed edge**여야 한다.

| Edge type | source | 기본 사용 정책 |
|---|---|---|
| `observed_cowave` | canonical signed Pearson wave | primary data edge; threshold provenance 필수 |
| `track_concordance` | Track 1/Track 2 peak·direction agreement | paired subset의 quality-weighted data edge |
| `same_protein_multisite` | peptide/site-to-protein mapping | structural relation; direction/kinase는 미가정 |
| `tmm_explains` | shared site–candidate kinase contribution | directed explanatory relation; direct phosphorylation edge 아님 |
| `known_ksa` | curated iPTMnet/UniProt/PhosphoSitePlus | external prior edge; training/validation leakage 방지 필요 |
| `ppi` | STRING/BioGRID | context edge; measured temporal edge와 별도 가중치 |

R2는 relational graph encoder를 사용하더라도 raw co-wave/TMM score를 대체하지 않고, **embedding-neighbor agreement, graph reconstruction uncertainty, held-out edge recovery**를 secondary evidence로만 제공해야 한다. curated KSA edge를 training에 사용한 경우에는 동일 KSA를 performance test에 쓰면 leakage가 발생하므로 kinase-family, dataset, species 단위의 strict holdout이 필요하다.

## co-wave·TMM·directionality와의 결합 규칙

| 현재 engine | Representation Learning이 해도 되는 일 | 해서는 안 되는 일 |
|---|---|---|
| Canonical co-wave | raw wave 안에서 latent dispersion을 계산하고 bootstrap neighbor stability를 추가 | signed Pearson membership과 threshold provenance를 몰래 교체 |
| TMM | exclusive substrate embedding dispersion으로 `profile_representational_stability`를 추가; Track 2 contribution의 confidence에 보조 반영 | NNLS/TMM coefficient를 learned similarity score로 교체하거나 direct kinase activity로 재명명 |
| Directionality | temporal embedding의 order robustness를 diagnostic으로 평가 | learned adjacency로 causality 또는 direction을 단정 |
| Multisite divergence | raw divergence와 latent separation이 동시에 클 때 review priority를 높임 | embedding distance만으로 functional divergence 판정 |
| RAG/LLM | embedding provenance와 raw evidence를 prompt context에 제공 | LLM이 latent cluster 이름만 보고 biological mechanism을 사실처럼 생성 |

### Proposed confidence composition

초기 R1에서는 기존 ranking을 바꾸지 않는다. validation을 통과한 뒤에도 representation은 score replacement가 아닌 bounded modifier 또는 annotation tier로 제한한다.

```text
Primary evidence: Track 2 TMM contribution + canonical wave evidence + directionality tier
Secondary evidence: representation stability + cross-track concordance + reconstruction quality

representation_supported =
  raw_evidence_eligible
  AND embedding_neighbor_stability >= pre-registered threshold
  AND reconstruction_error <= pre-registered threshold

representation_discordant =
  raw_evidence_eligible
  AND embedding result changes under replicate/bootstrap/mask perturbation
```

`representation_supported`는 “학습된 temporal geometry가 관찰형 evidence와 합치한다”는 뜻이지 kinase–substrate relation, direct phosphorylation 또는 causality의 증명이 아니다.

## Benchmark와 성공 기준

Representation Learning의 도입 결정은 visualization이 예쁘거나 cluster가 그럴듯해 보이는지가 아니라, 아래 사전 등록 benchmark를 통과하는지로 정한다.

| 비교 | 평가 지표 | 성공 기준 예시 |
|---|---|---|
| Baseline | signed Pearson+average linkage, functional PCA, PCA/NMF vs R1 encoder | co-wave bootstrap Jaccard/ARI와 held-out reconstruction을 모두 baseline보다 개선 |
| Time permutation | true order vs per-site/order permutation | true-time representation만 known early/intermediate/late insulin anchor에서 유의한 structure 유지; permutation에서는 성능 붕괴 |
| Missingness stress | observed value masking, Track 1 partial observation | predicted neighbor/cluster와 TMM confidence가 robust하며 missingness pattern 자체로 grouping되지 않음 |
| Cross-dataset | insulin primary dataset ↔ PXD043599/PXD001792, 필요 시 other RTK time course | cross-dataset nearest-neighbor와 branch-level chronology가 random/metadata baseline보다 개선 |
| Kinase association | held-out curated KSA family/dataset | AUROC/AUPRC, calibrated precision@k; training–test prior leakage 금지 |
| TMM integration | profile dispersion·exclusive substrate quality | representation feature가 TMM residual/holdout trajectory error를 낮추고 ranking reversal을 과도하게 늘리지 않음 |
| Negative control | biological labels·batch·timepoint labels의 prediction | batch/species/instrument가 latent representation을 지배하지 않음 |

Known insulin chronology는 external anchor로만 사용한다. INSR/IRS early, PI3K–AKT intermediate, MAPK transient, mTOR/S6K later dynamics는 model training label 또는 hard constraint가 아니라, data-driven model의 post hoc temporal concordance benchmark다.[3] [4]

## 데이터 규모와 도입 시점

| 상황 | 권장 방법 | 판단 |
|---|---|---|
| 단일 insulin Astral dataset만 확보 | functional PCA/denoising autoencoder research prototype | 가능하지만 production score 반영 금지 |
| 2–5개의 compatible dense time-course dataset | self-supervised R1 pretraining + dataset-held-out validation | 가장 현실적인 첫 model-development 단계 |
| 여러 condition/species 및 공개 dataset harmonization | R2 typed graph representation | conditional research project로 검토 |
| curated KSA와 perturbation validation dataset 충분 | weakly supervised association head | TMM 대비 additive gain이 입증될 때만 |

현재 프로젝트에서 PLM은 도입하지 않는 원칙을 유지한다. protein sequence language model embedding은 R1의 필수 입력이 아니며, 나중에 cross-dataset validation에서 sequence/motif feature가 raw temporal representation에 제공하는 incremental value가 증명될 때 optional external evidence layer로만 검토한다.

## 단계적 도입 로드맵

1. **R0 — benchmark harness 확장:** 현재 temporal wave benchmark에 FPCA/PCA/NMF baseline, time permutation, missingness masking, bootstrap neighbor stability를 추가한다. 학습 model을 아직 production에 넣지 않는다.
2. **R1 — self-supervised prototype:** Track 2 primary, protein context, optional Track 1 branch를 사용하는 small mask-aware encoder를 별도 research module로 만든다. output은 JSON artifact이며 canonical result를 수정하지 않는다.
3. **R1.5 — external validation:** primary insulin Astral dataset과 공개 insulin temporal reference에서 dataset-held-out benchmark를 실행한다. failure analysis를 공개한다.
4. **R2 — evidence layer:** validation pass를 한 model에 한하여 `representation_supported`/`representation_discordant` annotation을 co-wave/TMM output에 additive로 기록한다.
5. **R3 — optional graph model:** typed temporal graph representation을 연구 branch에서만 검증하고, label leakage와 species/domain shift가 통제된 경우에만 product integration을 고려한다.

## 논문화 포지셔닝

Representation Learning은 TMM 논문의 중심 기여를 대체하지 않아야 한다. 더 적절한 포지셔닝은 다음과 같다.

> **TMM provides condition-specific, interpretable decomposition of shared modified-peptide trajectories, whereas representation learning provides an orthogonal, self-supervised assessment of temporal neighborhood stability and profile quality.**

이 구분은 TMM의 설명가능성·provenance·unbiased discovery 장점을 보존한다. validation 이후 representation layer가 실질적인 generalization gain을 보인다면, 별도 후속 논문의 방법론 기여가 될 수 있다. 현 단계에서는 **TMM/co-wave benchmark의 robustness analysis component**로 쓰는 것이 논리적으로 가장 강하다.

## 최종 권고

Representation Learning은 도입 가치가 있으나, 지금 바로 kinase prediction score를 바꾸는 기능으로 도입하는 것은 권장하지 않는다. 사용자가 설계하는 dense insulin Astral dataset이 확보된 뒤, R0 baseline과 R1 self-supervised prototype을 먼저 실행해야 한다. 이 결과가 raw co-wave/TMM보다 reproducibility·missingness robustness·held-out biology recovery에서 개선을 보일 때에만 secondary evidence layer로 승격한다.

이 전략은 PTM-platform의 total-proteome + modified-peptide dual-track + dense temporal design이라는 차별점을 가장 잘 살리면서, black-box prediction이 현재의 data-grounded interpretation을 약화시키는 위험을 제한한다.

## References

[1] Jiang W, et al. *Deciphering the dark cancer phosphoproteome using machine-learned co-regulation of phosphosites.* Nature Communications (2025). https://www.nature.com/articles/s41467-025-57993-2

[2] Xiao D, et al. *SnapKin: a snapshot deep learning ensemble for kinase-substrate prediction from phosphoproteomics data.* NAR Genomics and Bioinformatics (2023). https://academic.oup.com/nargab/article/5/4/lqad099/7369457

[3] Turewicz M, et al. *Temporal phosphoproteomics reveals circuitry of phased propagation in insulin signaling.* Nature Communications (2025). https://www.nature.com/articles/s41467-025-56335-6

[4] Köksal AS, et al. *Synthesizing Signaling Pathways from Temporal Phosphoproteomic Data.* Cell Reports (2018). https://pmc.ncbi.nlm.nih.gov/articles/PMC6295338/
