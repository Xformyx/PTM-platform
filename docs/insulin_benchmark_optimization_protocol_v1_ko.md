# Insulin Blind Benchmark 변수 최적화 Protocol v1

## 1. Reference identity와 연구 원칙

첨부된 `Insulin_Signaling_Phospho_Kinase_Benchmark_v1.xlsx`의 SHA-256은 `a2cb7d6ab1167983198f80627ca412cdde78530cdfe0ecd9dbc6849f073ab484`이며, 현재 runner-only manifest에 기록된 workbook hash와 동일하다. 첨부 workbook에서 독립 재생성한 locked truth와 manifest도 repository bundle과 byte-for-byte 동일했다.

본 연구에서 workbook truth는 **최적화 objective로 사용하지 않는다**. 변수 선택은 raw quantitative data 내부의 재현성, timepoint holdout 예측, TMM reconstruction, identifiability 및 복잡도 제약으로 수행한다. Locked truth는 configuration을 동결한 이후 한 번만 외부 평가에 사용한다. 이는 반복적인 benchmark 점수 확인에 의한 insulin-specific overfitting을 방지하기 위한 핵심 설계다.

현재 workbook은 55개 anchor, 15개 kinase reference, 7개 temporal layer, 10개 ambiguous-site rule, 42개 scoring-template row 및 12개 benchmark rule을 포함한다. 현재 strict scorer가 Tier 1/2 positive truth로 읽는 anchor는 46개이나, 제공 데이터에서 sequence+isoform+species 기준으로 measurable한 anchor는 2개뿐이다. 따라서 현재 canonical weighted score만 최적화하는 것은 통계적으로 정당화할 수 없으며 금지한다.

## 2. 변수 분류

| Layer | Variable | Current default | Candidate range / levels | Status |
|---|---|---:|---|---|
| Preprocessing | Median normalization | global sample-median scaling | fixed; alternative only in ablation | Frozen primary |
| Preprocessing | Protein normalization | phosphopeptide log2FC − protein log2FC | fixed | Frozen primary |
| Preprocessing | BH-FDR method | BH, alpha 0.05 | fixed | Frozen primary |
| Paired occupancy | `PAIR_MIN_REPLICATES` | 2 | 2–3 | Secondary sensitivity only |
| Paired occupancy | `PAIR_MIN_OBSERVED_TIMEPOINTS` | 4 | 3–6 | Secondary sensitivity only |
| Paired occupancy | `PAIR_MIN_COMPLETENESS` | 0.70 | 0.60–0.90 | Secondary sensitivity only |
| Wave eligibility | `correlation_threshold` | 0.70 | 0.55–0.85 | Tunable |
| Wave eligibility | `minimum_variance` | 0.30 | 0.10–0.50 | Tunable |
| Wave eligibility | `minimum_amplitude` | 0.80 | 0.40–1.20 | Tunable |
| Wave clustering | `minimum_cluster_size` | 2 | 2–5 | Tunable |
| Wave clustering | `maximum_waves` | 8 | 6–12 | Tunable with complexity penalty |
| Activity filter | `FC_THRESHOLD` | 0.30 | 0.20–0.58 | Tunable |
| Activity filter | `Q_THRESHOLD` | 0.05 | 0.01, 0.05, 0.10 | Tunable; missing-q policy fixed |
| Robust aggregation | winsor lower/upper | 5/95 percentile | 0/100, 2.5/97.5, 5/95, 10/90 | Tunable |
| Kinase clustering | minimum substrates | 10 | 5–20 | Tunable |
| Kinase clustering | k-means seed | 42 | fixed | Frozen reproducibility |
| TMM profile | `MIN_EXCLUSIVE_FOR_PROFILE` | 3 | 2–6 | Tunable |
| TMM sparse prior | Gaussian log-space sigma | 0.60 | 0.35–1.00 | Tunable, prior-assisted flag retained |
| TMM contribution | NNLS non-negativity | enabled | fixed | Frozen primary |
| TMM guard | guard policy | `group_share` | fixed primary; `strict` ablation | Frozen primary / ablation |
| Identifiability | relative noise | 0.10 | 0.05–0.20 | Tunable diagnostic |
| Identifiability | substitutable coherence | 0.99 | 0.95–0.995 | Tunable diagnostic |
| Identifiability | weak/broken ratio radius | 0.15/0.50 | prespecified sensitivity grid | Diagnostic only |
| Redistribution | over-concentration threshold | 0.25 | 0.20–0.40 | Tunable |
| Redistribution | forced split threshold | 0.35 | 0.30–0.50 | Tunable |
| Redistribution | penalty multiplier / cap | 1.5 / 0.4 | 0.75–2.0 / 0.2–0.5 | Tunable |
| Redistribution | reassignment margin | 0.10–0.15 | 0.05–0.25 | Tunable |
| Kinase co-wave | profile correlation | 0.70 | 0.55–0.85 | Tunable |
| Cascade | active score threshold | 0.30 | data-scale calibrated sensitivity; default retained until calibrated | Tunable after scale audit |
| Directionality | onset threshold | 0.30 | 0.20, 0.30, 0.50 | Prespecified sensitivity |
| Directionality | minimum lag-aware similarity | 0.40 | 0.30–0.70 | Tunable |
| Directionality | bootstrap/permutation iterations | 250/250 | fixed at ≥250 in final | Frozen precision |
| Directionality | stability / p-value gates | 0.70 / 0.05 | fixed primary; sensitivity only | Frozen primary |
| Scorer | Tier weights | Tier 1=2, Tier 2=1 | fixed | Locked |
| Scorer | component weights | 0.25/0.25/0.20/0.20/0.10 | fixed | Locked |
| Biology | motif database, kinase timing priors, truth anchors | current versioned tables | fixed | Locked against insulin tuning |

## 3. 최적화 objective

Primary optimization score는 workbook-independent composite로 정의한다.

1. **Replicate stability:** 각 timepoint에서 한 replicate를 outer holdout으로 두었을 때 site trajectory, Wave membership 및 kinase profile의 일치도.
2. **Timepoint prediction:** inner leave-one-timepoint-out에서 omitted profile value와 peak order를 얼마나 복원하는지.
3. **Wave structural quality:** retained-site coverage, within-wave signed correlation, between-wave separation 및 singleton/excluded-site penalty.
4. **TMM reconstruction:** shared-site NNLS relative residual과 timepoint holdout reconstruction error.
5. **TMM identifiability:** identifiable/group-share-resolved fraction, design rank, profile coherence 및 prior-assisted profile fraction.
6. **Parsimony:** 지나치게 많은 Wave, kinase module, edge 및 forced reassignment에 대한 complexity penalty.
7. **Dual-track concordance:** paired occupancy가 qualified인 site에 한해 protein-normalized track과 방향·peak concordance.

Locked anchor recovery, kinase-name recovery 및 workbook temporal-window agreement는 configuration freeze 이후에만 보고한다. 이 결과는 최종 외부 평가이며 search objective가 아니다.

## 4. Nested validation 설계

Outer split은 3개 biological/technical replicate index 중 하나를 각 condition에서 동시에 holdout하는 3-fold grouped split로 한다. Inner split은 6개 numeric timepoint 중 하나를 생략하는 leave-one-timepoint-out이다. Candidate configuration은 inner objective 평균과 worst-fold 성능을 함께 사용해 선택하며, 동률이면 더 단순하고 prior-assisted fraction이 낮은 configuration을 선택한다.

최종 configuration은 모든 training replicate로 refit한 뒤 outer holdout에서 평가한다. 선택이 완료되면 config JSON과 SHA-256을 동결하고, 그 후에만 runner-only workbook으로 canonical·kinase·temporal-layer 외부 평가를 한 번 수행한다.

## 5. 논문 주장 경계

이 데이터에서 TMM input module은 현재 `motif_only_seed` provenance다. 따라서 최적화 후에도 kinase result는 **motif-seeded temporal attribution**으로 기술하고 direct substrate validation으로 서술하지 않는다. Temporal ordering은 observational precedence이며 causality가 아니다. Inhibitor dataset은 알고리즘 동결 후 별도 prospective validation으로 사용한다.
