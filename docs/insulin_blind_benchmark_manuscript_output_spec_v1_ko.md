# PTM-platform Insulin Blind Benchmark: 논문용 정량·시각화 산출물 명세 v1

**목적:** Stimulus-blind 및 question-blind benchmark를 논문에서 검증 가능한 방법론·성능·생물학적 사례·외부 검증으로 제시할 수 있도록, framework가 자동 생성해야 할 정량 지표, primary figure, supplementary figure, source-data table 및 재현성 metadata를 정의한다.

**중요한 전제:** 아래는 아직 실제 benchmark 결과가 아니며, 실제 수치·유의성·그래프의 형태는 blind run과 locked scoring 후에만 생성한다. Tier 1/2, detectable-anchor denominator, 단백질 정규화, compatible time window, phosphosite direction과 kinase activity direction의 분리 등은 제공 workbook의 규칙을 따른다. [1]

## 1. 논문에서 검증할 주장과 정량의 연결

논문은 “인슐린 신호를 잘 맞혔다”라는 단일 주장으로 쓰지 않는다. 아래 네 가지 독립된 주장 단위를 구분해야 한다. 이 구조를 따르면 platform의 강점인 unbiased discovery, temporal resolution, multi-kinase attribution, perturbation validation이 서로 다른 증거로 제시된다.

| 논문 주장 | 주 정량 지표 | 시각화 | 주장 한계 |
|---|---|---|---|
| Blind recovery | Detectable anchor recall, regulated anchor recall, direction accuracy, peak-window accuracy | component bar + CI, anchor-window matrix | measurable Tier 1/2 anchor에 한정 |
| Branch coherence | Branch macro-average, chain completeness, contradiction rate | branch-by-metric heatmap, layer graph | time order는 causality가 아님 |
| Multi-kinase attribution | Top-k kinase/module recovery, reciprocal rank, TMM contribution, sparse-profile rate | rank curve, raw-vs-TMM comparison, contribution panel | shared substrate의 기여도는 추론치이며 direct target 증거가 아님 |
| Robustness 및 선택성 | bootstrap CI, replicate resampling, time permutation null, threshold sensitivity, negative-control activation | ablation plot, null distribution, sensitivity plot | acquisition·mapping limitation과 알고리즘 오류를 분리 |
| Perturbation-supported validation | inhibitor interaction effect, target-wave attenuation, target-rank shift, branch selectivity | interaction forest plot, time-course contrast, branch response map | 사용한 inhibitor와 조건에 한정된 support |

## 2. Primary Figure 구성: 권장 5개

논문 본문에서는 benchmark framework의 모든 panel을 한꺼번에 넣지 않는다. **Figure 1–5**는 “무엇을 blind로 했고, 얼마나 회복했으며, 어떤 원리로 회복했는가, 견고한가, perturbation에서 검증되는가”라는 순서로 배치한다.

### Figure 1. Study design, information barrier, and temporal analysis architecture

| Panel | 시각화 | 자동 산출 내용 | 논문 메시지 |
|---|---|---|---|
| 1A | Experimental time-course strip | vehicle/treatment, `0–1–5–15–30–60–180 min`, replicate 수, protein/PTM track | 시간 해상도와 분석 단위를 명확히 제시 |
| 1B | Information-partition schematic | analysis input, generic question, locked truth/scorer, post-score reveal의 분리 | benchmark truth가 LLM/RAG/report에 유입되지 않음을 제시 |
| 1C | PTM-platform analysis flow | normalized PTM → Canonical Wave → TMM → directionality/divergence → Data-Grounded output | site-level 관찰에서 multi-layer inference까지의 경로 제시 |
| 1D | Rat_hir mapping provenance mini-panel | rat order context, human INSR custom FASTA, sequence-aware site mapping | mixed rat/human reference의 오매칭 방지 원칙 제시 |

Figure 1은 성능 그래프가 아니라 **방법론적 공정성**을 보여주는 그림이다. 실제 score를 넣지 않으므로 revision 후에도 재사용 가능하고, legend에는 benchmark truth가 scorer에만 접근 가능하다는 사실을 명확히 기술한다.

### Figure 2. Blind anchor recovery and temporal fidelity

| Panel | 주 정량 | 표시 방식 | Source data |
|---|---|---|---|
| 2A | Detectable recall, regulated recall, direction accuracy, peak-window accuracy, chain completeness, weighted composite | 각 metric의 point estimate와 95% bootstrap CI; 분자/분모를 점 위에 표시 | `metrics_summary.tsv` |
| 2B | Branch macro-average | 행=branch, 열=component metric의 heatmap; 각 cell에 `n_evaluable` 병기 | `branch_metrics.tsv` |
| 2C | Anchor temporal-window match | 행=Anchor_ID, 열=observed time window; match/partial/miss와 Tier를 동시에 표시 | `anchor_scores.tsv` |
| 2D | Detection vs regulation 분해 | measurable-but-not-detected, detected-but-not-regulated, correct-regulation 상태의 alluvial 또는 stacked bar | `anchor_status_counts.tsv` |

Figure 2의 핵심은 composite이 아니라 **오류의 위치**를 보여주는 것이다. 예를 들어 detectability 때문에 빠진 anchor와 regulation 또는 temporal attribution에서 놓친 anchor가 분리되어야 한다. Branch heatmap은 receptor/INSR, IRS–PI3K, PI3K–AKT, RAS–ERK, ERK–RSK, mTORC1–S6K/4E-BP1, feedback/recovery를 macro-average로 동등하게 다룬다. [1]

### Figure 3. Temporal kinase attribution beyond co-wave membership

| Panel | 주 정량 | 표시 방식 | 논문 메시지 |
|---|---|---|---|
| 3A | Expected kinase/module Top-1, Top-3, Top-5 recovery 및 reciprocal rank | 누적 Top-k curve 또는 paired dot plot | 올바른 kinase/module이 실용적 순위에 도달하는지 제시 |
| 3B | Raw score 대 TMM-weighted score | 동일 kinase/module의 raw→TMM rank shift를 paired line으로 표시 | raw co-wave와 fractional attribution을 구분 |
| 3C | Representative shared-site contribution | site별 stacked contribution + profile fit/residual + sparse flag | shared site를 단일 kinase에 강제하지 않음 |
| 3D | TMM confidence distribution | confidence/entropy/residual/number of informative substrates 분포 | high-confidence 결과와 prior-assisted fallback을 구분 |

Figure 3의 representative example은 결과를 보고 선택하면 안 된다. 대표 kinase/module과 site는 **blind run 전** 선택 규칙을 정한다. 예를 들어 “Tier 1 anchor가 2개 이상이고, TMM confidence가 상위 사분위이며, shared substrate가 하나 이상인 branch”처럼 기계적으로 지정한다. 그렇지 않으면 시각적으로 좋은 사례만 고른다는 비판을 받기 쉽다.

### Figure 4. Reconstructed temporal cascade and evidence-aware directionality

| Panel | 주 정량 | 표시 방식 | 해석 경계 |
|---|---|---|---|
| 4A | Observed-versus-reference layer recovery | reference와 observation을 나란히 둔 directed layer graph | branch layer의 시간적 정합성 |
| 4B | Onset/peak lag | edge별 lag와 95% CI를 가진 dot/interval plot | temporal precedence이며 causal edge가 아님 |
| 4C | D0–D3 distribution | branch별 D-tier stacked bar | 강한 언어를 쓸 수 있는 edge를 제한 |
| 4D | Multisite divergence | 동일 단백질 site pair의 trajectory + mixture divergence | divergent site를 protein-level 평균으로 소거하지 않음 |

Figure 4는 “시계열 자료가 단순 각 timepoint 비교보다 무엇을 더 제공하는가”를 직접 보여준다. 다만 edge에는 `observational temporal precedence`, `directionality-supported`와 같은 표현을 사용하고, inhibitor 결과 전에는 causal arrow 또는 direct regulation이라는 용어를 쓰지 않는다.

### Figure 5. Robustness, error decomposition, and independent inhibitor validation

Figure 5는 두 부분으로 나눈다. inhibitor data가 없는 첫 논문 초안에서는 5A–5C까지만 primary로 사용하고, inhibitor data가 준비되면 5D–5F를 추가한다.

| Panel | 주 정량 | 표시 방식 | 목적 |
|---|---|---|---|
| 5A | Algorithm version/ablation effect | V0–V5의 paired bootstrap difference와 CI | 어떤 evidence layer가 개선에 기여하는지 제시 |
| 5B | Time-permutation null | observed score와 within-replicate time-permutation distribution | temporal signal의 우연성 검증 |
| 5C | Error taxonomy | acquisition, mapping, localization, normalization, timing, TMM ambiguity, narrative error의 stacked bar | 알고리즘 개선 대상과 assay limitation 구분 |
| 5D | Inhibitor interaction effect | site/wave/kinase별 interaction estimate와 CI의 forest plot | inhibitor-only 효과를 보정한 branch-selective attenuation |
| 5E | Target wave contrast | vehicle, insulin, inhibitor, insulin+inhibitor의 평균±CI time-course | 예상 target wave의 amplitude/onset/persistence 변화 |
| 5F | Branch-selectivity map | 행=branch, 열=readout, 색=interaction effect | 모든 PTM이 아니라 target branch가 선택적으로 감소하는지 확인 |

Inhibitor 검증의 사전등록 contrast는 다음과 같다.

```text
inhibitor-specific insulin effect
= (insulin + inhibitor − inhibitor only)
− (insulin only − vehicle)
```

이 식은 inhibitor-only로 발생한 전반적 변화와 vehicle 대비 insulin 반응을 분리한다. Inhibitory phosphosite은 site phosphorylation direction과 kinase activity direction을 구분한 sign convention을 적용한 후 표시한다. [1]

## 3. Supplementary Figure와 Extended Data 구성

Primary figure는 주장을 보여주고, Supplementary/Extended Data는 그 주장에 대한 **검증 가능성**을 제공한다. 아래 항목은 분석이 시작되면 자동 생성하되, 저널 format에 맞게 Supplementary 또는 Extended Data로 배치한다.

| 권장 번호 | 내용 | 핵심 산출물 |
|---|---|---|
| Supplementary Fig. 1 | Input QC 및 missingness | timepoint별 quantified PTM/protein 수, replicate correlation, missingness, protein-normalization coverage |
| Supplementary Fig. 2 | Sequence-aware mapping audit | Anchor별 peptide, accession, taxon, human/rat site, localization confidence, mapping result |
| Supplementary Fig. 3 | 모든 Tier 1/2 anchor trajectory | anchor별 normalized PTM time-course, replicate points, expected/observed window |
| Supplementary Fig. 4 | TMM model diagnostics | 모든 scored kinase/module의 contribution, residual, entropy, informative-substrate count, sparse fallback |
| Supplementary Fig. 5 | Stability/sensitivity | bootstrap, leave-one-timepoint-out, threshold sweep, time-permutation 결과 |
| Supplementary Fig. 6 | Directionality audit | 모든 D1–D3 edge의 onset/peak lag, similarity, permutation/stability metric, wording eligibility |
| Supplementary Fig. 7 | Multisite divergence atlas | all eligible site pair trajectory, directionality, mixture divergence, evidence gate |
| Supplementary Fig. 8 | Strict literature-blind 대 literature-assisted 비교 | 같은 data output에서 RAG policy가 narrative와 metric에 미치는 영향 분리 |
| Supplementary Fig. 9 | Negative controls 및 false-positive audit | constitutive/stress module, unsupported receptor, false pathway activation |
| Supplementary Fig. 10 | Inhibitor replicate·dose·QC support | replicate dispersion, inhibitor-only effect, protein-level confounding, target engagement support |

## 4. 자동 생성할 정량 표와 source-data 패키지

논문 figure를 이미지로만 내보내면 재현성과 재분석 가능성이 약하다. Framework는 모든 figure에 대응하는 source-data TSV와 기계판독 JSON을 함께 생성해야 한다.

| 파일 | 한 행의 단위 | 필수 열 |
|---|---|---|
| `metrics_summary.tsv` | run × algorithm version × metric | run ID, input hash, scorer version, metric, numerator, denominator, estimate, CI, bootstrap n |
| `branch_metrics.tsv` | run × branch × metric | branch, evaluable anchor n, score, CI, contradiction count, macro-average weight |
| `anchor_scores.tsv` | Anchor_ID × run | Tier, weight, measurable, detected, regulated, direction match, onset/peak match, chain support, error category |
| `anchor_mapping_audit.tsv` | workbook anchor × observed peptide match | sequence, accession, taxon, isoform, human/rat site, localization, mapping status |
| `kinase_rank.tsv` | time window × kinase/module | raw rank/score, TMM rank/score, Top-k status, expected status, confidence |
| `tmm_contributions.tsv` | site × candidate kinase × time window | fractional contribution, residual, entropy, profile source, sparse fallback flag |
| `waves.tsv` | canonical wave × site/member | membership, amplitude, peak/onset, threshold provenance, bootstrap/permutation stability |
| `directionality.tsv` | ordered source-target pair | onset/peak lag, lag-aware similarity, D-tier, CI, permutation p, LOTO support |
| `multisite_divergence.tsv` | protein × site pair | divergence label, trajectory metrics, TMM mixture distance, evidence gate |
| `permutation_null.tsv` | permutation × metric | scheme, seed, statistic, observed statistic, empirical p |
| `error_review.tsv` | evaluated anchor × version | primary error category, supporting evidence, exclusion decision, remediation status |
| `inhibitor_contrast.tsv` | site/wave/kinase × inhibitor | four group summaries, interaction estimate, CI, sign convention, branch-selectivity label |
| `claim_ledger.tsv` | report claim × evidence item | claim category, data object ID, allowed wording, directionality/perturbation tier, ChromaDB provenance |

각 table은 `run_id`, `analysis_commit`, `scorer_commit`, `manifest_hash`, `input_hash`, `generated_at_utc`를 공통 열로 가져야 한다. 이렇게 해야 Figure 2의 숫자와 Supplementary Fig. 3의 source data, final report의 문장이 동일 run을 가리키는지 추적할 수 있다.

## 5. 통계와 표기 계약

| 상황 | 권장 처리 | Figure/표기 |
|---|---|---|
| Anchor 비율 지표 | Tier weight를 반영한 estimate와 anchor bootstrap 95% CI | 분자/분모, bootstrap iteration 수, CI method 병기 |
| Algorithm version 비교 | 동일 anchor에 대한 paired bootstrap difference | 절대점수와 Δscore를 함께 표시 |
| Replicate variation | biological replicate resampling을 anchor bootstrap과 별도로 제공 | replicate 수와 resampling unit 명시 |
| Temporal signal | replicate 내부에서 time label을 permutation하여 null 생성 | observed statistic, null distribution, empirical p |
| 다수 site/edge | pre-registered family에 대해 BH FDR | raw p와 q-value를 source data에 동시 제공 |
| Missing/de novo | main canonical score에서 임의 imputation 금지 | detectability/first appearance/persistence를 별도 표시 |
| Threshold sensitivity | 사전 등록한 threshold grid 전체에서 score 계산 | heatmap 또는 stability profile; 최적점만 선택 금지 |

Bootstrap을 사용할 때 anchor를 독립 표본으로 가정한 confidence interval과 replicate를 재표집한 interval을 혼합하면 안 된다. 두 uncertainty source를 별도 panel 또는 별도 열로 표시한다. Time permutation도 timepoint를 전체 dataset에서 무작위로 섞지 말고, replicate 내부에서 time label을 섞어 marginal intensity와 replicate 구조를 최대한 보존한다.

## 6. Publication result bundle 구조

각 benchmark run은 다음과 같이 self-contained bundle을 만든다. 모든 그래프는 논문 조판용 `SVG`와 `PDF`, preprint/공유용 `PNG`를 함께 내보내며, PDF 속 텍스트는 선택·검색 가능해야 한다.

```text
benchmark_runs/<run_id>/
├── manifest/
│   ├── blind_run_manifest.yaml
│   ├── input_checksums.tsv
│   └── environment_lock.txt
├── discovery/
│   ├── raw_platform_exports/
│   ├── data_grounded_evidence.json
│   └── blind_context_audit.json
├── scoring/
│   ├── metrics_summary.tsv
│   ├── anchor_scores.tsv
│   ├── branch_metrics.tsv
│   ├── error_review.tsv
│   └── scorer_audit.json
├── figures/
│   ├── main/Fig1–Fig5.{svg,pdf,png}
│   ├── supplementary/SuppFig1–SuppFig10.{svg,pdf,png}
│   └── figure_manifest.tsv
├── source_data/
│   └── Fig*_source_data.tsv
├── robustness/
│   ├── bootstrap/
│   ├── permutations/
│   └── threshold_sensitivity/
└── perturbation_validation/
    ├── inhibitor_contrast.tsv
    ├── condition_qc.tsv
    └── validation_figure_data.tsv
```

`benchmark_locked/`의 원본 workbook은 archive에는 포함하되 analysis/RAG/LLM process가 접근하는 mount 또는 import path와 분리한다. `scorer_audit.json`에는 truth reveal 시점, truth hash, scorer version, truth 접근 process를 기록한다.

## 7. 논문 Figure에 쓰지 말아야 할 표현과 그래프

다음 사항은 설득력보다 과장을 높일 위험이 있으므로 금지한다.

| 피해야 할 표현/그래프 | 이유 | 대안 |
|---|---|---|
| 단일 overall accuracy만 제시 | acquisition·mapping·timing 오류를 숨김 | component bar + branch heatmap + source data |
| Tier 3/4·de novo를 canonical denominator에 포함 | circular validation과 score inflation | discovery-only panel 별도 제공 |
| raw co-wave를 direct kinase-substrate network로 그림 | 동시성은 direct targeting을 증명하지 않음 | raw membership과 TMM contribution을 분리 표기 |
| temporal arrow를 causal arrow로 표시 | observation-only time course의 과잉 해석 | D-tier 및 “temporal precedence” 표기 |
| inhibitor 후 전체 PTM 감소를 target inhibition으로 주장 | 독성·전역 단백질 변화·batch effect 가능 | 2×2 interaction contrast와 branch-selectivity map |
| 대표 trajectory만 선택하여 보여주기 | 선택 편향 | 전체 anchor trajectory를 Supplementary로 제공하고 representative selection rule 공개 |

## 8. 구현 우선순위

첫 구현은 Figure 2와 그 source data를 완전하게 만드는 것이다. 이유는 이 부분이 blind benchmark의 1차 성능 주장을 가장 직접적으로 지지하고, 나머지 figure의 분모·mapping·time window·branch 정의를 고정하기 때문이다. 다음으로 Figure 3/4의 TMM·temporal layer, Figure 5A–C의 robustness·error taxonomy, 마지막으로 inhibitor 자료가 생긴 뒤 Figure 5D–F를 구현한다.

| 우선순위 | 구현 범위 | 완료 판단 |
|---|---|---|
| P0 | manifest, locked scorer, anchor/branch score, Figure 2, source data | blind run과 score가 재실행 가능하며 Tier 1/2 rule을 자동 감사 |
| P1 | Top-k/rank, TMM confidence, cascade/directionality, Figure 3–4 | raw/TMM과 D-tier가 동일 run metadata로 연결 |
| P2 | bootstrap, replicate resampling, permutation, threshold sensitivity, Figure 5A–C | 모든 CI·null·sensitivity가 machine-readable로 저장 |
| P3 | inhibitor contrast, perturbation appendix, Figure 5D–F | discovery와 perturbation evidence가 물리적으로 분리되어 재현 가능 |

이 설계에 따라 실제 benchmark를 실행하면, 논문 본문에는 **blindness의 엄격성, anchor/branch 회수, TMM 기반 다중 kinase attribution, temporal reconstruction, robustness, 선택적 perturbation validation**을 단계적으로 제시할 수 있다. 실제 수치가 생성되기 전에는 성공 여부나 유의성을 미리 단정하지 않는다.

## References

[1] 사용자 제공 자료. *Insulin Signaling Phospho-Kinase Benchmark v1* (`Insulin_Signaling_Phospho_Kinase_Benchmark_v1.xlsx`). README, Anchor_Reference, Kinase_Reference, Temporal_Layers, Ambiguous_Sites, Current_HIRcB_Check, Sources, Scoring_Template, Benchmark_Rules 시트.
