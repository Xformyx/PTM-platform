# Insulin Signaling Phospho-Kinase Benchmark: 자극원·질문 Blind 실행계획 v1

**작성일:** 2026-08-25
**대상:** PTM-platform의 Canonical Temporal Wave, TMM 기반 다중 kinase attribution, evidence-aware directionality, multisite divergence, Data-Grounded Analysis
**기준 자료:** 사용자 제공 `Insulin_Signaling_Phospho_Kinase_Benchmark_v1.xlsx` [1]

## 1. 목적과 과학적 범위

본 계획의 1차 목적은 rat HIRc-B 세포의 time-course phosphoproteomics에서 PTM-platform이 **자극원이 insulin이라는 사실과 insulin-specific biological question을 알지 못하는 상태**로도 재현성 있는 temporal PTM program, candidate kinase activity, candidate upstream regulator, temporal relationship 및 후속 검증 가설을 복원하는지 평가하는 것이다. 평가는 단일 kinase의 site-level 예측률만이 아니라, receptor-proximal 신호에서 PI3K–AKT, RAS–ERK, mTORC1 및 feedback/recovery로 이어지는 **시간적·분지별 정합성**을 함께 검증한다.

Workbook의 Tier 1/2만 canonical accuracy에 포함한다. Tier 1은 가중치 2, Tier 2는 가중치 1이며, Tier 3/4와 de novo PTM은 발견적 해석에는 사용할 수 있지만 canonical accuracy를 높이는 데 사용하면 안 된다. 0, 1, 5, 15, 30, 60, 180분의 이산 time grid에서는 정확히 같은 minute을 맞혔는지보다 **compatible onset/peak window**를 회복했는지를 평가한다. [1]

> 이 평가는 “완전히 prior-free인 인공지능”을 증명하는 실험이 아니다. 데이터 자체에는 INSR, AKT, MAPK 관련 단백질이 관측될 수 있다. 따라서 정확한 표기는 **stimulus-blind 및 question-blind 평가**이며, benchmark truth와 insulin-specific 문맥이 discovery runtime에 유입되지 않도록 막는 것이 핵심이다.

| 평가 대상 | 평가하지 않는 것 | 원칙 |
|---|---|---|
| Site/PTM 회수, 단백질 정규화 후 조절성, 방향, 시간 창, branch chain coherence | 단일 composite만으로 방법론의 우열을 단정하는 것 | component와 branch score를 항상 분리 보고 |
| Raw co-wave와 TMM-weighted attribution | co-wave를 한 kinase의 직접 표적으로 해석하는 것 | raw membership·TMM contribution·confidence를 동시 표시 |
| D0–D3 observational directionality | time precedence를 causality로 단정하는 것 | causal claim은 독립 perturbation 단계에서만 제한적으로 강화 |
| Inhibitor 사후 검증 | inhibitor를 baseline discovery의 사전입력으로 사용하는 것 | discovery와 perturbation evidence를 별도 run·별도 report로 보존 |

## 2. 사전등록과 정보 분리

분석 시작 전에 workbook 원본의 SHA-256 hash, workbook version, detectable-anchor 판정, replicate rule, 통계 threshold, 시간 grid, platform commit hash, model/prompt version을 `blind_run_manifest`에 기록하고 잠근다. 결과를 본 뒤 anchor, Tier, expected direction/window, 가중치, negative control 또는 denominator를 변경해서는 안 된다.

| 자산 | 접근 권한 | 역할 |
|---|---|---|
| `analysis_input/` | 분석 runtime | PTM/protein matrix, sample sheet, Rat_hir FASTA, generic 조건명 |
| `benchmark_locked/` | 독립 scorer만 | workbook, Anchor_ID, expected direction/window, branch truth, scoring rule |
| `blind_run_manifest.yaml` | 분석·scorer 공통 | 입력 hash, code/model version, time grid, threshold, blind policy |
| `blind_context.md` | 분석 runtime | 자극원·pathway명을 제거한 일반 biological question |
| `reveal_context.md` | scoring 완료 후 | insulin identity, benchmark branch, 해석용 context |
| `result_bundle/` | run 종료 후 불변 | raw output, log, score table, figure, error review |

분석 runtime, Report Generation, RAG, 외부 Co-Scientist에는 `benchmark_locked/` 파일을 전달하지 않는다. 특히 `insulin`, `INSR`, `PI3K`, `AKT`, `ERK`, `mTOR`, expected time window, known inhibitor target을 biological question, prompt, system context, RAG query에 넣지 않는다.

### 2.1 Blind biological question

primary run에는 아래의 범용 질문만 제공한다.

> “이 처리 대조군 시간경과 PTM 자료에서 재현성 있는 temporal PTM program, candidate kinase activity, candidate upstream regulator, 관찰 가능한 temporal relationship 및 후속 검증 가치가 높은 가설을 데이터에 근거하여 제시하라.”

외부 Co-Scientist는 primary blind run에서 비활성화하거나 반드시 같은 generic context만 받게 한다. 더 엄격한 **literature-blind sub-analysis**를 수행할 때는 RAG collection allowlist/blocklist로 insulin-specific 논문을 배제하고, 사용 collection ID와 정책을 manifest에 기록한다. 이 run은 문헌 보강 분석으로 별도 보고하며 primary blind score와 합산하지 않는다.

### 2.2 Rat_hir 매핑

현재 Rat_hir 정의를 유지한다. Order-level species는 rat(`10116`/`rno`)로 두되, custom FASTA의 human INSR은 accession, `GN=INSR`, `OX=9606` provenance를 보존한다. Site match는 residue number가 아니라 **peptide sequence + isoform + residue + FASTA taxon**으로 수행하고, human·rat residue number를 별도 열에 기록한다. 예를 들어 human ERK2 T185/Y187과 rat MAPK1 T183/Y185처럼 번호가 다른 orthologous site의 거짓 음성을 방지하기 위한 필수 규칙이다. [1]

## 3. Stage 0 — 입력 적격성 평가

이 단계에서는 biological truth와 대조하지 않는다. 분석 가능성과 score denominator의 정당성만 검증한다.

| 항목 | 실행 방법 | 통과 기준 |
|---|---|---|
| Time axis | 실제 수집 시간(분)을 numeric metadata로 저장 | 0–1–5–15–30–60–180분 또는 실제 grid가 정확히 보존됨 |
| Sequence/site mapping | Anchor별 observed peptide, accession, taxon, human/rat site, localization confidence 표 작성 | residue-only match가 없고 ambiguous match 상태가 명시됨 |
| Protein normalization | 가능한 경우 `PTM log2FC − matched protein log2FC` 계산 | activity claim은 normalized PTM evidence 또는 결측 사실을 표시 |
| Replicate/통계 | replicate 수와 regulated call rule을 run 전 잠금 | 예: ≥2/3 replicate 및 사전등록 기준 |
| Detectability | assay-level 검출 가능 여부를 scoring 전에 판정 | 미검출 phosphotyrosine을 자동 false negative로 계산하지 않음 |
| De novo | control/treated replicate 수, first-detection interval, persistence 기록 | 임의의 무한 FC를 canonical score에 사용하지 않음 |

결과는 `anchor_mapping_audit.tsv`와 `input_qc_report.md`로 보존한다. 이 표는 성능을 좋게 보이게 하는 후처리가 아니라, false negative가 acquisition/mapping 문제인지 알고리즘 문제인지 구분하는 감사 기록이다.

## 4. Stage 1 — Primary Stimulus-Blind Discovery

잠긴 manifest와 generic question으로 baseline을 1회 실행한 뒤, score 전에 출력물을 수정하지 않는다. 최종 narrative뿐 아니라 다음의 기계판독 가능 중간산출물을 모두 보존한다.

| 분석 레이어 | 보존 산출물 | 역할 |
|---|---|---|
| Canonical Temporal Wave | membership, threshold provenance, bootstrap/permutation/stability | 동시성 및 재현성을 구분 |
| Kinase attribution | raw/TMM-weighted profile, candidate set, residual, sparse flag | 공통 substrate의 다중 kinase 기여 분리 |
| TMM | per-site fractional contribution, entropy/collinearity, confidence | “한 site=한 kinase” 강제를 방지 |
| Directionality | onset/peak lag, lag-aware similarity, D0–D3, null/stability | 관찰적 temporal precedence 정량화 |
| Multisite divergence | site-pair trajectory, TMM mixture distance, evidence gate | 같은 단백질의 상반된 PTM을 별도 관찰로 유지 |
| Data-Grounded Analysis | auto-question, hypothesis, vector-data verification, ChromaDB provenance | LLM 문장을 사용자 데이터·ChromaDB 근거에 제한 |
| Report | Results/Discussion 문장과 근거 ID | 과장된 causal wording을 감사 |

Raw co-wave의 동시성은 출발 증거이다. 최종 kinase attribution은 TMM contribution, sparse-profile confidence, motif/evidence 및 temporal profile을 통합해 제시한다. Blind run 중 발견된 pathway 명칭을 benchmark truth에 맞추기 위한 수동 correction에 사용해서는 안 된다.

## 5. Stage 2 — 잠긴 Scoring과 그래프

blind output을 archive한 후에만 독립 scorer가 workbook을 공개한다. Canonical score는 measurable Tier 1/2 anchor만 분모로 사용하며 Tier 3/4와 de novo는 discovery-only panel로 분리한다. [1]

### 5.1 Anchor-level score

| 지표 | 계산 원칙 | 해석 |
|---|---|---|
| Detectable anchor recall | 검출 Tier 1/2 ÷ measurable Tier 1/2 | acquisition·identification 회수율 |
| Regulated anchor recall | 조절 Tier 1/2 ÷ measurable Tier 1/2 | end-to-end regulation 회수율 |
| Direction accuracy | 방향 일치 regulated anchor ÷ regulated anchor | phosphosite sign 회수율 |
| Peak-window accuracy | compatible peak window ÷ regulated anchor | interval-censored temporal 회수율 |
| Chain completeness | branch별 지지된 ordered-layer 관계 | 고립된 hub가 아닌 신호 연쇄 회수 |
| Evidence-weighted composite | detection 25%, regulation 25%, direction 20%, peak 20%, chain 10%; Tier 1=2, Tier 2=1 | 요약 지표; 단독 결론 금지 |

GSK3A S21/GSK3B S9처럼 phosphorylation 상승이 kinase activity 감소를 뜻할 수 있는 inhibitory site는 **site phosphorylation direction**과 **inferred kinase activity direction**을 분리 저장한다. 따라서 site sign 정답을 kinase activation sign 정답으로 치환하지 않는다. [1]

### 5.2 Kinase·wave·branch score

workbook은 부분적인 positive truth set이므로 사전등록된 명확한 negative kinase universe가 없다면 ROC/AUC를 주 지표로 사용하지 않는다. 대신 다음 rank와 coherence 지표를 사용한다.

| 단위 | 주 지표 |
|---|---|
| Kinase/module | Expected kinase/module의 Top-1/3/5 recovery, reciprocal rank, 시간 창별 rank 변화, TMM contribution concordance |
| Wave | stable wave recovery, early/intermediate/late branch placement, D-tier 분포 |
| Branch | receptor/INSR, IRS–PI3K, PI3K–AKT, RAS–ERK, ERK–RSK, mTORC1–S6K/4E-BP1, feedback/recovery의 macro-average |
| Specificity | constitutive site·비인슐린 stress module·unsupported high-confidence receptor 활성화율 |

Branch macro-average를 기본으로 하여 downstream output site가 많은 branch 하나가 전체 composite을 지배하지 않도록 한다. Branch는 최소 2개의 순서화된 layer가 지지되고 high-confidence contradiction이 없을 때 coherent로 판정한다. [1]

### 5.3 필수 그래프 세트

Confidence interval은 anchor bootstrap을 기본으로 하고, replicate가 있으면 replicate resampling 결과를 별도로 제시한다. 단일 composite graph만으로 결론을 내리지 않는다.

| 그래프 | 구현 | 답하는 질문 |
|---|---|---|
| Weighted metric bar + CI | component bar와 95% bootstrap CI | detection, regulation, sign, timing, chain 중 병목은 어디인가? |
| Branch-by-metric heatmap | 행=branch, 열=component metric | PI3K–AKT, MAPK, mTORC1 회수가 균형적인가? |
| Anchor temporal-window matrix | 행=Anchor_ID, 열=시간 창, 색=match/partial/miss | early·intermediate·late·recovery 창을 회복했는가? |
| Top-k kinase recovery/rank plot | cumulative Top-1/3/5 또는 reciprocal rank | 올바른 kinase/module이 실용적 순위에 도달하는가? |
| Reference-vs-observed layer graph | reference layer와 발견 layer를 나란히 표시 | branch별 최소 두 ordered layer가 이어지는가? |
| Failure taxonomy plot | error category별 stacked bar | 오류가 acquisition·mapping·timing·attribution·LLM 중 어디에서 발생하는가? |
| TMM contribution/confidence panel | contribution, residual, entropy, sparse flag | correct call이 sparse fallback이 아닌 data-grounded profile에 근거하는가? |
| Discovery-only yield panel | de novo·Tier 3/4·novel wave 별도 표시 | 새로운 발견을 보존하되 canonical score와 섞지 않았는가? |

## 6. Stage 3 — 오류 분류 후 알고리즘 개선

점수 하락을 곧바로 threshold 조정으로 해결하지 않는다. 모든 false negative, false positive, wrong-direction, wrong-window call을 하나의 주 오류 범주에 먼저 분류한다.

| 오류 범주 | 판별 증거 | 대응 |
|---|---|---|
| Acquisition/detectability | peptide가 assay에서 검출·정량 불가 | measurable denominator에서 제외; algorithm tuning 금지 |
| Species/isoform mapping | sequence/taxon/site number 불일치 | mapping과 provenance만 수정 |
| Localization ambiguity | multi-site peptide 또는 localization confidence 부족 | strict anchor 제외 또는 partial support 처리 |
| Protein abundance confounding | normalization 후 PTM 변화 소실 | raw PTM만으로 activity claim 금지 |
| Regulation rule | replicate/통계 사전기준 미충족 | 별도 version에서 predeclared rule 검토 |
| Temporal discretization | compatible interval은 맞고 정확한 minute만 다름 | miss가 아닌 window-consistent 처리 |
| Kinase ambiguity | broad motif, shared substrate, high TMM entropy/collinearity | candidate/TMM confidence 개선; 임의의 winner 강제 금지 |
| Sparse profile | exclusive substrate 부족 또는 prior-assisted fallback | confidence 하향; core performance 근거로 사용 금지 |
| LLM/RAG interpretation | data layer는 맞으나 narrative가 누락/과장 | prompt·evidence gate만 수정 |

알고리즘 개선은 한 번에 한 evidence layer만 추가하는 version ladder로 수행한다. 각 version은 동일 input, 동일 manifest, 동일 scorer로 재실행한다.

```text
V0  현재 baseline
V1  V0 + Canonical Temporal Wave 및 stability evidence
V2  V1 + TMM fractional multi-kinase contribution
V3  V2 + minute onset/peak lag 및 D0–D3 directionality
V4  V3 + multisite divergence evidence gate
V5  V4 + Data-Grounded/Report evidence-aware guardrail
```

변경 채택 조건은 사전등록 primary metric의 CI-고려 개선, 핵심 branch의 의미 있는 손실 부재, mapping/detectability 제외 전후 설명 가능성이다. Insulin workbook 전체에 반복 적합한 뒤 같은 workbook으로 일반화 성능을 주장하지 않는다. 최소한 held-out branch subset을 보존하거나, 바람직하게는 별도 stimulus/독립 time-course dataset에서 최종 generalization을 평가한다.

## 7. Stage 4 — Kinase inhibitor 사후 외부 검증

inhibitor 실험은 blind discovery와 benchmark score가 잠긴 **후** 수행한다. 이 단계는 unbiased discovery를 대체하지 않으며, platform이 만든 D2/D3 후보 및 branch-specific 예측이 perturbation에서 유지되는지 확인하는 외부 검증이다.

### 7.1 실험 설계

선택 target/branch마다 가능하면 다음 2×2 contrast를 유지한다.

```text
vehicle
insulin
inhibitor only
insulin + inhibitor
```

동일한 Rat_hir FASTA, acquisition 방식, time grid, replicate rule, protein quantification, QC 및 scoring rule을 적용한다. Early-response target의 경우 1–15분 구간이 predicted onset/peak attenuation을 볼 수 있을 만큼 유지되어야 한다. Inhibitor target은 primary blind score에서 **data-supported하고 branch-coherent한 D2/D3 후보가 나온 뒤** 선택하며, selection rule을 inhibitor data를 보기 전에 기록한다.

### 7.2 Endpoint와 interaction contrast

성공 기준은 “모든 PTM이 사라지는가”가 아니다. Inhibitor-only 효과를 보정한 뒤 insulin에 의해 유도된 **target branch의 선택적 attenuation**이 관측되는지가 기준이다.

```text
inhibitor-specific insulin effect
= (insulin + inhibitor − inhibitor only)
− (insulin only − vehicle)
```

| Platform readout | 사전등록할 기대 신호 |
|---|---|
| Target kinase activity/rank | insulin+inhibitor에서 target kinase/module activity와 rank 감소 |
| TMM contribution | target kinase의 shared-site fractional contribution 감소 |
| Target substrate wave | amplitude 감소, onset 지연, persistence 소실 중 하나 이상 |
| Temporal relationship | downstream D-tier가 약화·미결정·지연으로 변화 |
| Competing branch | 안정 유지 또는 사전등록된 crosstalk rule에 부합 |
| Negative-control module | 모든 kinase activity가 비특이적으로 소실되지 않음 |

Inhibitory phosphosite은 activity sign을 보정한 뒤 contrast를 해석한다. Inhibitor 결과는 기존 discovery run을 다시 쓰지 않고 optional perturbation evidence schema에 condition-scoped evidence로 업로드한다. Report에서는 “discovery evidence”와 “perturbation-supported validation evidence”를 명확히 구분한다.

## 8. 구현 작업 패키지와 결정 Gate

구현은 insulin-specific hardcoding이 아닌 재사용 가능한 benchmark framework로 시작한다. Workbook은 dataset-specific truth manifest가 되며, 분석 runtime과 scorer 사이의 정보 경계를 코드 구조로 강제한다.

| 작업 패키지 | 구현물 | 완료 조건 |
|---|---|---|
| Versioned manifest | `benchmarks/<dataset>/manifest.{yaml,json}` | input hash, blind policy, time grid, scorer version, threshold가 재실행 가능하게 기록됨 |
| Locked scorer | workbook parser, sequence-aware matcher, scorer JSON/TSV | Report/LLM/RAG runtime에서 import 불가; anchor audit table 생성 |
| Blind mode | generic context, RAG allowlist/blocklist, context audit log | insulin-specific truth field가 primary input에 없음 |
| Metrics/plotting | score bundle, figure module, branch macro-average | component·branch·discovery-only 결과가 분리됨 |
| Error review | anchor별 error taxonomy/resolution | 개선안이 anecdote가 아닌 오류 범주에 연결됨 |
| Inhibitor validator | condition contrast 및 perturbation appendix | discovery record와 독립된 perturbation-supported claim 생성 |

| Gate | 핵심 질문 | 산출물 |
|---|---|---|
| G0 | mapping, detectability, protein normalization, time axis, replicate rule이 준비되었는가? | `input_qc_report.md`, `anchor_mapping_audit.tsv` |
| G1 | blind baseline이 Tier 1/2와 branch coherence를 회복하는가? | locked score table, figure bundle, blind report archive |
| G2 | 실패의 주 원인이 acquisition/mapping이 아니라 개선 가능한 algorithm layer인가? | error taxonomy와 version proposal |
| G3 | 사전등록 algorithm change가 primary 및 branch-balanced metric을 개선하는가? | V0–V5 comparison report |
| G4 | inhibitor 자료가 locked model의 branch-selective attenuation을 지지하는가? | perturbation validation appendix |
| G5 | 별도 stimulus/dataset에서도 결과가 유지되는가? | final generalization report |

최종 논문 또는 보고서의 결론은 네 층으로 구분한다. **(1) 측정된 anchor 회수, (2) 조건 특이적 kinase attribution, (3) 관찰적 temporal precedence, (4) 독립 perturbation-supported validation**이다. Discovery yield는 별도로 중요하게 보고하되 insulin canonical benchmark accuracy를 부풀리는 데 사용하지 않는다.

## References

[1] 사용자 제공 자료. *Insulin Signaling Phospho-Kinase Benchmark v1* (`Insulin_Signaling_Phospho_Kinase_Benchmark_v1.xlsx`). README, Anchor_Reference, Kinase_Reference, Temporal_Layers, Ambiguous_Sites, Current_HIRcB_Check, Sources, Scoring_Template, Benchmark_Rules 시트.
