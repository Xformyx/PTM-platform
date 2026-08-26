# 최종 통합 Temporal PTM–Protein Benchmark: 논문용 섹션 초안

## 사용 범위와 실행 판본

이 섹션은 commit `d3b5c1df873a7721d41c2ce066adacd6e4ceacdc`에서 실행한 최종 통합 benchmark replay에만 근거한다. 현재-head replay는 supplied PR/PG/FASTA의 hash-verified normalized numeric output으로부터 site observation, canonical temporal Wave 및 PTM–protein temporal evidence layer를 다시 계산하였다. temporal kinase attribution은 raw durable worker가 이전에 생성·동결한 truth-free TMM output을 입력으로 사용하였다. 따라서 본 결과는 **current code로 재생성한 raw-vector/Wave/PTM–protein replay와 artifact-freeze 후 독립 평가 결과**이며, TMM을 위한 annotation/database worker 자체를 다시 실행한 별도의 새로운 external-lookup experiment가 아니다. 이 구분은 재현성 및 strict-blind 경계를 위해 명시한다.

분석 중 benchmark workbook, anchor identity, stimulus identity, biological question, RAG 또는 LLM output은 읽지 않았다. 해당 workbook은 artifact freeze 뒤 독립 runner-only score 단계에서만 접근하였다. 입력 및 출력 provenance는 replay manifest에 기록되었다.[1]

## Methods

### Strict-blind 입력과 immutable 평가 경계

Benchmark 입력은 PR matrix, PG matrix, mixed rat plus human INSR FASTA로 구성하였다. SHA-256 hash는 각각 `7160e863…a52ba4`, `57c874a4…ca745`, `61b5d367…23c83`이었다. PTM site는 protein-normalized numeric vector에서 생성했고, FASTA sequence·isoform·species match를 사용하여 mapping validity를 판정하였다. 이 분석 단계에서는 benchmark workbook과 reference label을 사용할 수 없도록 하였다. 동결 artifact가 생성된 뒤에만 locked truth bundle을 가진 offline scorer가 canonical benchmark component를 산출했다.[1] [2]

### Canonical temporal Wave와 TMM attribution

PTM site별 protein-normalized time series에서 canonical Wave를 생성하였다. Frozen temporal configuration은 median aggregation, Wave amplitude threshold 0.40, bootstrap 25회, soft threshold 0.60으로 고정되었다. TMM은 data-driven exclusive substrate profile과 sparse-profile Gaussian fallback을 명시적으로 구분하고, shared site에는 NNLS 기반 fractional contribution을 사용하였다. TMM contribution은 raw module membership을 대체하지 않으며, contribution-weighted cascade는 observed temporal activity의 보조 표현으로만 사용하였다.

### 동일 production/benchmark PTM–protein sidecar

일반 Order와 benchmark는 동일한 PTM–protein temporal engine과 output schema를 사용한다. PG-derived protein trajectory를 수집하고, same-gene PTM–protein pair, canonical Wave에서 non-PTM protein으로의 lag-aware temporal edge, kinase timing prediction, mechanism candidate 및 counterevidence record를 생성하였다. Cross-layer configuration은 truth-free 9-configuration search에서 선택된 absolute change 0.30, lag-aware similarity 0.40, leave-one-timepoint-out (LOTO) stability 0.60으로 고정하였다. 이 선택은 numeric time-course evidence만 사용했으며 locked truth를 사용하지 않았다.[3]

Cross-layer edge는 `temporal_precedence_supported` 또는 `observational_peak_order_only` 같은 관찰적 용어로 저장하며, 모든 edge의 `causality_status`는 `not_tested`이다. 따라서 edge와 mechanism chain은 검증 가능한 가설의 evidence packet이지, PTM이 protein abundance 변화를 유발했다는 인과 증명은 아니다.

### Direct kinase evidence와 timing evaluability

FASTA-derived accession/OX taxonomy/site provenance를 사용해 1,388개 accession-first external query를 수행하였다. iPTMnet direct endpoint가 HTTP 503으로 이용 불가였으므로 해당 run에서 UniProt curated modified-residue record만으로 exact-site evidence를 평가하였다. Direct evidence는 accession, taxonomy, residue-position, isoform context가 관측 site와 일치해야 했으며 motif prior 또는 calibrated candidate는 direct evidence로 승격하지 않았다.[4]

Timing accuracy는 direct exact-site evidence가 같은 kinase의 **positive TMM contribution**과 연결된 경우에만 data-anchored로 산출하도록 사전 정의하였다. 따라서 exact-site database coverage와 TMM timing anchor coverage를 별도로 보고했다. direct anchor denominator가 0이면 timing accuracy와 mean timing error는 `not_evaluable`로 기록했고, 0% accuracy로 대체하지 않았다.

### Artifact-freeze 후 독립 평가와 통계 보고

Canonical benchmark component는 Tier 1/2 anchor만으로 계산했다. 구성 요소는 detectable-anchor recall, regulated-anchor recall, direction accuracy, peak-window accuracy, chain completeness이며 가중치는 각각 0.25, 0.25, 0.20, 0.20, 0.10이다.[2] Kinase timing, cross-layer relation, mechanism 및 refutation evidence는 artifact freeze 이후 별도로 평가했으며, canonical composite score와 혼합하지 않았다. Optional reference sheets (`Protein_Effectors`, `Cross_Layer_Relations`, `Mechanism_Chains`, `Counterexamples`)가 없는 경우에는 해당 metric을 `not_evaluable` 또는 descriptive-only로 표시했다.

통계는 benchmark artifact의 count, proportion, median LOTO stability 및 median absolute lag-aware similarity를 보고하였다. Protein layer가 현 PG output에서 condition-level summary만 제공하므로 protein replicate stability, cross-layer p-value 또는 causal effect estimate는 계산하지 않았고, 존재하지 않는 confidence interval을 생성하지 않았다.

## Results

### Artifact 규모와 temporal representation

현재-head replay는 2,447개 site observation을 생성했고, 모두 sequence–isoform–species mapping requirement를 충족했다. Canonical Wave는 8개였으며 834개 Wave member를 포함했다. TMM output에는 141개 kinase-score row와 55개 profile이 있었고, relative contribution matrix는 2,243 site, occupancy contribution matrix는 768 site를 포함했다. Contribution-weighted observed cascade는 6개 timepoint로 구성되었다 (Figure 3–4; Table 1).[1]

| Domain | Final statistic | Interpretation |
|---|---:|---|
| Observed PTM sites | 2,447 | All sequence–isoform–species measurable in frozen artifact |
| Canonical Waves | 8 | 834 total Wave members |
| TMM kinase scores / profiles | 141 / 55 | Profile count is not a direct-kinase validation count |
| Relative / occupancy contribution sites | 2,243 / 768 | Separate quantitative tracks retained |
| Cascade timepoints | 6 | Contribution-weighted observed activity summary |
| Protein trajectories | 8,905 | PG-derived condition-level trajectories |
| Same-gene PTM–protein pairs | 2,447 | Paired by mapped gene identity |
| Retained cross-layer edges | 1,600 | Observational temporal edges |
| Temporally eligible cross-layer edges | 1,154 (72.125%) | Eligibility for hypothesis construction, not causal support |
| Mechanism chain / counterevidence rows | 8,000 / 8,000 | Falsifiability records; no evidence-supported causal chains |

### 통합 benchmark component score

Artifact-freeze 후 locked scoring에서 canonical weighted composite score는 **0.7333**이었다. Detectable-anchor recall은 1.000 (3/3), regulated-anchor recall은 0.333 (1/3), direction accuracy는 1.000 (1/1), peak-window accuracy는 1.000 (1/1), chain completeness는 0.000이었다. 이 component score는 PTM–protein temporal evidence와 함께 보고되지만, 성능의 전체 범위가 아니라 현재 locked Tier 1/2 anchor denominator에서의 performance estimate로 해석해야 한다 (Figure 1–2; Table 2).[2]

| Canonical benchmark component | Estimate | Denominator | Weighted contribution |
|---|---:|---:|---:|
| Detectable-anchor recall | 1.000 | 3 | 0.2500 |
| Regulated-anchor recall | 0.333 | 3 | 0.0833 |
| Direction accuracy | 1.000 | 1 | 0.2000 |
| Peak-window accuracy | 1.000 | 1 | 0.2000 |
| Chain completeness | 0.000 | Not applicable | 0.0000 |
| **Canonical weighted composite** | **0.7333** | Locked Tier 1/2 component contract | **0.7333** |

### Enrichment-free PTM–protein temporal evidence graph

PG data에서 8,905 protein trajectory를 수집했고, 7,539개 non-PTM-only protein 중 2,691개가 truth-free candidate screening threshold를 통과했다 (candidate coverage 35.694%). 선택된 configuration에서 1,600 edge가 보존되었고, 1,154 edge가 mechanism hypothesis eligibility 기준을 충족했다. Retained edge의 median LOTO stability는 0.8333, median absolute lag-aware similarity는 0.8258이었다. Pre-registered objective는 0.73234였고, causal overclaim rate는 0이었다.[3]

이 수치는 high-dimensional PTM 및 non-PTM time-course를 동일 temporal coordinate에서 연결할 수 있음을 보인다. 그러나 current PG layer는 condition-level summary이므로 protein replicate stability는 unavailable이며, 1,154개의 temporal eligibility는 known mechanism recovery rate나 causal chain count가 아니다 (Figure 4E).

### Direct evidence coverage와 timing evaluation boundary

Accession-first UniProt audit은 1,388 queries 중 47 exact-site direct-evidence row를 발견했으며, 이는 27/2,447 observed site (1.103%)에 해당했다. 모든 hit는 rat taxonomy ID 10116에서 얻었고 gene fallback은 사용하지 않았다. 그러나 47 row 중 positive same-kinase TMM contribution과 연결된 row는 0개였다. 따라서 data-anchored kinase timing coverage는 0.0이며 timing accuracy와 mean timing error는 `not_evaluable`이다.[4]

Optional locked reference sheets가 아직 제공되지 않았으므로 cross-layer score는 `not_evaluable_missing_locked_cross_layer_reference`, mechanism score는 `descriptive_only_no_explicit_v2_chain_truth`, refutation score는 `not_evaluable_ambiguous_site_policy_only`로 표시됐다. 이 결과는 실패나 0% mechanism recovery가 아니라, 현재 analyst-authored PTM–protein reference truth가 없고 strict direct timing anchor가 없다는 측정 가능성의 경계이다.

## Discussion

이 benchmark의 주요 결과는 enrichment-free PTM 및 PG protein time-course를 통합해 대규모 관찰적 temporal evidence graph를 만들면서도 strict-blind canonical component contract를 변화시키지 않았다는 점이다. 2,447 PTM site, 8,905 protein trajectory 및 1,600 cross-layer edge는 temporal hypothesis generation의 입력 규모를 정량적으로 제시한다. 특히 production Order와 benchmark가 동일 PTM–protein temporal engine을 사용하므로, benchmark에서 평가한 representation과 일반 분석에서 보고서·Data-Grounded Analysis·comparative analysis가 소비하는 representation 사이의 알고리즘적 간극을 줄였다.

다만 결과는 PTM signal이 protein abundance change를 유발했음을 입증하지 않는다. Edge selection은 effect size, lag-aware similarity 및 LOTO temporal stability에 기초하며, PG layer에는 replicate-level stability가 없다. 따라서 Figure 4E의 mechanism candidate는 experimental prioritization을 위한 가설이며 causal mechanism recovery나 perturbation-supported pathway로 기술되어서는 안 된다. 후속 inhibitor/perturbation time-course 또는 orthogonal assay가 제공될 때만 `perturbation_supported`의 별도 evidence tier를 평가할 수 있다.

Direct kinase evidence에서도 같은 보수적 원칙을 적용했다. 47 exact-site UniProt row는 accession/site-aware lookup이 단순 motif prior보다 엄격한 evidence를 제공할 수 있음을 보이지만, positive TMM contribution과의 교집합이 0이므로 timing accuracy를 산출할 denominator가 없다. iPTMnet endpoint의 503 outage는 source availability limitation으로 provenance에 보존했다. 추후 source가 이용 가능해지고 exact site–kinase–TMM contribution linkage가 형성되면, frozen artifact를 변경하지 않는 독립 timing evaluation을 수행할 수 있다.

Composite score 0.7333은 3개의 detection/regulated denominator와 각각 1개의 direction/peak denominator에 기반하므로, precision estimate 또는 generalizable clinical performance로 과대해석해서는 안 된다. 그럼에도 PTM–protein temporal layer를 결합한 뒤 canonical score와 semantic fields가 정확히 보존되었다는 사실은 기존 anchor metric을 덮어쓰지 않는다는 noninferiority gate를 만족한다. 다음 단계는 analyst-authored optional PTM–protein reference truth를 독립적으로 작성하고, protein replicate-level input을 추가하며, perturbation data에서 cross-layer and kinase timing hypothesis를 prospective하게 평가하는 것이다.

## Figure legends

**Figure 1. Strict-blind integrated temporal analysis contract.** Frozen normalized PTM vectors and FASTA mapping were analyzed without workbook truth, stimulus identity, RAG or LLM context. The locked evaluator accessed truth only after artifact freeze. Figure 5 and later perturbation panels were excluded because no inhibitor/perturbation benchmark set was included.

**Figure 2. Integrated blind benchmark performance.** Component-wise locked evaluation shows detectable-anchor recall, regulated-anchor recall, direction accuracy, peak-window accuracy and chain completeness under the immutable component contract. The canonical weighted composite was 0.7333.

**Figure 3. TMM multi-kinase attribution.** Contribution-weighted kinase activity ranks and shared-site fractional attribution records are shown. The plot displays observed TMM-derived activity; it does not validate kinase–substrate causality or direct timing accuracy.

**Figure 4. Observed temporal cascade and enrichment-free PTM–protein evidence.** Panels 4A–4D summarize contribution-weighted observed cascade and temporal directionality. Panel 4E reports 8,905 protein trajectories, 2,447 same-gene PTM–protein pairs, 1,600 retained cross-layer edges, 1,154 temporally eligible edges, 8,000 mechanism candidates, zero evidence-supported causal mechanisms and `not_evaluable` data-anchored kinase timing. Temporal precedence is observational, not causal.

## Reproducibility and source data

| Item | Current-head record |
|---|---|
| Code commit | `d3b5c1df873a7721d41c2ce066adacd6e4ceacdc` |
| Temporal / cross-layer config SHA-256 | `ee1671c9…fa9455` / `c4cdd0b4…57790` |
| Final artifact SHA-256 | `d4530554…e332c` |
| Locked component score | `locked_v1_score/locked_score_result.json` |
| Post-freeze PTM–protein assessment | `runner_only_v2/additive_v2_score.json` |
| Figures and source data | `corrected_integrated_benchmark/publication_bundle/figures/Fig1.svg`–`Fig4.svg`; `source_data/` |
| PNG/PDF visual QC | `corrected_integrated_benchmark/raster_figures/figure_raster_qc.json` |

## References

[1] [Current-head raw-vector replay manifest](../../benchmark_v1_v2_work/final_unified_raw_replay_current_head/replay_manifest.json).

[2] [Locked v1 benchmark manifest and scoring contract](../benchmarks/insulin_signaling_v1/insulin_signaling_v1.manifest.json).

[3] [Truth-free cross-layer optimization result](../../benchmark_v1_v2_work/cross_layer_optimization.json).

[4] [Accession-first direct-evidence audit and strict TMM linkage result](../../benchmark_v1_v2_work/final_direct_kinase_evidence_audit.json).
