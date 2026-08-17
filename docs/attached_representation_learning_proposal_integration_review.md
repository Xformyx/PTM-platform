# 첨부 PTM Vector Representation Learning 제안 통합 검토

작성일: 2026-08-17 (GMT+9)
검토 대상: `PTM_Vector_Representation_Learning_Full.pdf`
상태: **통합 설계 권고 — production kinase ranking 변경 전 benchmark 필요**

## 종합 판단

첨부 제안의 중심 개념은 정확하고 PTM-platform에 잘 부합한다. 현재 PTM Vector를 버리지 않고, 이를 **interpretable quantitative feature representation**으로 보존한 뒤 temporal multi-view encoder가 latent PTM embedding을 학습한다는 계층적 관점은 적절하다.

특히 아래 세 가지는 그대로 채택할 수 있다.

1. 현재 PTM Vector는 raw intensity가 아니라 protein normalization, condition comparison, statistical evidence, paired modified/unmodified evidence를 거친 **Layer 1 handcrafted representation**이다.
2. ordered timepoint 전체에서 학습한 `z_i = fθ(X_i)`는 **Layer 2 learned temporal PTM embedding**으로 분리해야 한다.
3. representation의 유용성은 latent dimension의 크기가 아니라 kinase recovery, known-substrate grouping, wave stability, cross-condition generalization, TMM profile quality와 같은 downstream benchmark로 판단해야 한다.

다만 첨부한 기본 흐름인 `Learned PTM Embedding → Temporal Wave → TMM → Kinase attribution`은 수정이 필요하다. 이 흐름만 사용하면 learned embedding이 raw quantitative evidence를 대체하게 되어, 현재 플랫폼의 unbiased discovery·provenance·explainability 원칙을 약화시킬 수 있다.

> **최종 권고 architecture는 직렬 대체가 아니라 병렬 evidence design이다. Raw Track 2 trajectory는 canonical co-wave와 TMM의 primary input으로 그대로 유지하고, learned embedding은 temporal neighborhood stability와 profile quality를 평가하는 secondary layer로 병렬 실행한다.**

## 첨부 제안의 항목별 판정

| 첨부 제안 | 판정 | PTM-platform 적용 방식 |
|---|---|---|
| `PTM Vector Table`과 `Learned PTM Representation`의 구분 | **채택** | 문서·UI·Methods에서 quantitative vector, temporal trajectory vector, multi-view input, learned embedding을 명확히 구분 |
| `z_i = fθ(X_i)` latent vector | **채택, 조건부** | site/form별 temporal embedding으로 생성하되 dimension·model version·training cohort·uncertainty를 provenance로 저장 |
| Track 1 + Track 2 + protein context 결합 | **채택, 수정** | Track 2 primary branch, protein context branch, Track 1 optional masked branch로 처리; Track 1 부재를 0으로 채우지 않음 |
| `ΔPTM_absolute` 입력 | **수정 필요** | 현재 calibration 없는 Track 1은 absolute occupancy가 아니라 `apparent_paired_occupancy` 또는 paired signal fraction; physical absolute occupancy라는 명칭 사용 금지 |
| q-value 입력 | **채택, 사용 방식 수정** | raw biological feature가 아니라 quality/loss weight·eligibility mask·provenance로 우선 사용; q-value 자체를 latent biology의 강한 driver로 만들지 않음 |
| motif/sequence 입력 | **조건부 보류** | R1 baseline에서는 제외하거나 low-capacity side feature; temporal-only 대비 incremental gain·leakage·prior dominance가 검증될 때만 추가 |
| learned embedding 후 Wave/TMM | **수정 필요** | raw Track 2 canonical wave/TMM은 계속 primary; embedding-derived neighborhood/wave는 parallel exploratory layer |
| embedding으로 AKT substrate module proximity | **채택, 표현 제한** | “temporal multi-view neighborhood가 AKT-associated reference module과 일치”로 표현; direct kinase substrate 증명·causality 주장 금지 |
| Representation A–E ablation | **강하게 채택** | 동일 downstream task, split, compute budget, missingness policy에서 pre-registered 비교 |
| perturbation recovery | **수정 필요** | primary discovery training label이 아니라 external/held-out evaluation 또는 분석 후 validation recommendation에 한정 |

## 현재 quantitative contract에 맞춘 4개 representation 층

첨부 문서가 제안한 명명 체계를 다음처럼 PTM-platform contract에 맞춰 확정하는 것이 좋다.

| 층 | 명칭 | 단위 | 내용 | 해석 가능성 |
|---|---|---|---|---|
| L1 | **Quantitative PTM Feature Vector** | site/form × timepoint | `PTM_Relative_Log2FC`, `Protein_Log2FC`, statistical quality, Track 1 paired signal metadata, precursor/localization/missingness provenance | 높음 |
| L2 | **Temporal PTM Trajectory Vector** | site/form | ordered-timepoint Track 2 trajectory와 Track 1 optional trajectory | 높음 |
| L3 | **Multi-view Temporal PTM Input** | site/form × timepoint × view | Track 2 primary, protein context, Track 1 availability-mask branch, time intervals, quality masks | 중간 |
| L4 | **Learned Temporal PTM Embedding** | site/form | encoder가 만든 latent vector, reconstruction error, embedding uncertainty, neighbor stability | 낮음; raw evidence 역추적 필수 |

L4는 L1/L2를 대체하지 않는다. report와 UI는 언제나 L4 conclusion을 L1/L2 raw values, wave evidence, TMM contribution, Track1/Track2 concordance로 다시 설명해야 한다.

## 권장 병렬 architecture

```text
PR / PG / FASTA
        ↓
existing preprocessing and dual-track quantification
        ↓
L1 Quantitative PTM Feature Vector
        ├─────────────────────────────────────────────┐
        │                                             │
        ▼                                             ▼
L2 Track 2 temporal trajectory                 L3 multi-view encoder input
        │                                             │
        ▼                                             ▼
canonical co-wave + raw Track 2 TMM            L4 learned temporal embedding
        │                                             │
        ├──── raw evidence / contribution ──────┤ embedding stability / neighborhood
        │                                             │
        └──────────── evidence concordance ──────────┘
                              ↓
             evidence-aware kinase-associated program
                              ↓
        original quantitative values and citations explain result
```

### Why not use embedding as direct TMM input?

TMM currently interprets an observed shared modified-peptide trajectory as a condition-specific mixture of candidate kinase-associated profiles. Replacing that trajectory with a learned latent vector would remove the coefficient's direct relationship to observed timepoint values. Therefore the TMM score remains based on Track 2 trajectories. A learned representation can instead provide the following additive fields.

| Additive field | Definition | Use |
|---|---|---|
| `profile_representational_dispersion` | exclusive substrates assigned to a candidate kinase의 embedding dispersion | heterogeneous profile warning 또는 confidence modifier 후보 |
| `embedding_neighbor_stability` | bootstrap/replicate/mask perturbation에서 top-k neighbor overlap | learned temporal neighborhood의 robustness 표시 |
| `representation_reconstruction_error` | held-out observed values의 reconstruction error | model fit quality, low-quality embedding flag |
| `representation_track_concordance` | latent neighbor가 Track 1/Track 2 peak·direction evidence와 합치하는 정도 | dual-track concordance와 별도의 secondary support |
| `representation_discordant` | raw co-wave/TMM과 embedding neighborhood의 bootstrap-stable disagreement | biological novelty 또는 technical artifact review queue |

## Encoder input의 수정된 계약

| 제안 입력 | 권장 처리 | 이유 |
|---|---|---|
| `PTM_Relative_Log2FC` | primary reconstruction target 및 temporal input | 현재 protein-normalized modified-peptide signal의 primary observed trajectory |
| `Protein_Log2FC` | context branch; PTM target을 직접 대체하지 않음 | non-PTM downstream response를 보존하되 modification signal과 혼동 방지 |
| Track 1 | optional gated branch + availability mask | paired subset coverage bias·missingness artifact 차단 |
| q-value / precursor q-value | quality-weighted loss 및 eligibility mask | statistical confidence를 biological latent dimension으로 오인하지 않음 |
| `time_minutes`, `Δt` | positional/time encoding | 0–0.5–1–2.5–5–10–15–30–60분 같은 irregular interval 보존 |
| motif | optional static side feature, ablation 필수 | dynamic temporal pattern보다 prior가 latent geometry를 지배하는지 검증 |
| raw sequence/PLM | 현 단계 제외 | PLM은 검증 이후 optional evidence라는 프로젝트 원칙 유지 |
| species/reference context | model/domain metadata; biological signal feature로 직접 사용 금지 | Rat_hir custom reference와 human/mouse domain shift를 추적하되 species classifier가 되지 않게 함 |

## 구체적인 ablation benchmark

첨부 문서의 Representation A–E 설계는 매우 유용하다. 그러나 평가 split과 success metric을 아래처럼 강화해야 한다.

| Representation | 내용 | 필요한 비교/guardrail |
|---|---|---|
| A | Track 2 temporal trajectory only | canonical signed Pearson/TMM baseline |
| B | 현재 handcrafted L1 vector | protein context와 quality feature의 incremental value |
| C | B + motif/static sequence descriptors | motif prior dominance 및 held-out kinase-family leakage 검사 |
| D | learned temporal representation | time-order permutation, masked reconstruction, wave stability |
| E | learned multi-view representation | Track1/Track2 availability bias, protein abundance confounding, cross-dataset stability |

| 평가 질문 | 필수 metric | 금지 또는 주의 사항 |
|---|---|---|
| Kinase recovery | kinase-family/dataset-held-out AUROC/AUPRC, calibrated precision@k | same curated KSA를 training과 test에 중복 사용 금지 |
| Known substrate grouping | adjusted Rand index, neighbor enrichment, cluster purity | motif/kinase label이 input이면 strict family holdout |
| Wave stability | bootstrap Jaccard/ARI, timepoint leave-one-out stability | raw canonical wave를 learned cluster로 대체하지 않음 |
| Perturbation recovery | independent external perturbation dataset recovery | primary unbiased discovery cohort의 training objective로 사용 금지 |
| TMM identifiability | residual, contribution entropy, exclusive-profile dispersion, ranking reversal rate | TMM coefficient를 latent similarity score로 교체 금지 |
| Cross-condition generalization | dataset-held-out, species-held-out, instrument-held-out retrieval | same batch split 또는 same experiment random row split 금지 |

## 도입 결정 gate

R1 prototype은 다음 조건이 모두 충족되기 전에는 production API/kinase ranking에 영향 주지 않는다.

1. **Time validity:** true time order가 permuted order보다 reconstruction, known temporal anchor recovery, wave stability에서 우수해야 한다.
2. **Missingness validity:** artificial masking에서 embedding cluster가 missingness rate 자체가 아니라 raw temporal pattern을 반영해야 한다.
3. **Raw-evidence concordance:** high-confidence representation neighbor가 Track 2 co-wave 및 dual-track direction/peak evidence와 사전 정의된 수준 이상 합치해야 한다.
4. **Generalization:** primary insulin dataset 이외 held-out public/reference dataset에서 baseline보다 개선해야 한다.
5. **No prior leakage:** motif/KSA/PPI-derived feature를 포함한 실험은 feature-free temporal baseline과 strict holdout에서 비교해야 한다.
6. **Interpretability:** every representation-supported conclusion은 original site/form, timepoint values, quality fields, Track1/Track2 status, raw wave, TMM contribution으로 역추적 가능해야 한다.

## 통합 로드맵

| 단계 | 채택 범위 | output | 기존 분석 영향 |
|---|---|---|---|
| R0 | quantitative vector terminology 정리 + FPCA/PCA/NMF baseline | baseline benchmark artifact | 없음 |
| R1 | small mask-aware self-supervised encoder | site/form embedding, reconstruction error, neighbor stability | 없음 |
| R1.5 | A–E ablation + cross-dataset benchmark | benchmark report and failure analysis | 없음 |
| R2 | additive `representation_supported`/`representation_discordant` flags | co-wave/TMM secondary provenance | primary score 불변 |
| R3 | validation 후 bounded confidence modifier | pre-registered calibration and ranking comparison | 사용자 승인 필요 |
| R4 | typed graph representation | research branch only | multi-condition corpus 전까지 보류 |

## 최종 권고

첨부 제안은 **PTM-platform의 현 구조를 가장 잘 확장하는 방향**이다. 특히 “interpretable PTM Vector → learned representation → interpretable evidence explanation”이라는 원칙은 채택한다. 단, implementation graph는 raw canonical co-wave/TMM을 learned embedding 뒤로 보내는 직렬 구조가 아니라, 두 층이 독립적으로 실행되고 합의·불일치를 기록하는 병렬 구조로 수정해야 한다.

이 수정은 TMM의 조건 특이적 설명력, dual-track total-proteome 설계, temporal-precedence와 causality의 분리, PLM 도입 보류, unbiased discovery 원칙을 모두 지킨다. Representation Learning의 첫 논문 기여는 “deep model이 kinase를 맞혔다”가 아니라, **dense temporal total-proteome context에서 learned temporal neighborhoods가 raw co-wave/TMM evidence의 재현성 및 profile quality를 개선하는가**로 정의하는 것이 가장 강하다.
