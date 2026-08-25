# 고감도 Phosphoproteomics의 Novel PTM을 보존하는 Dual-Track Benchmark 전략 v1

## 결론

**Canonical benchmark만 보면 최신 고감도 질량분석으로 새롭게 검출된 PTM의 가치를 충분히 반영할 수 없다.** Tier 1/2 anchor는 알고리즘이 이미 확립된 insulin signaling을 얼마나 정확히 복원하는지 평가하는 기준일 뿐이다. 새 장비가 더 깊게 관측한 low-abundance site, novel site, 새로운 temporal pattern, 예상하지 못한 kinase mixture는 canonical accuracy의 분자에 넣으면 안 되지만, 반드시 별도의 **Discovery Track**에서 보존하고 논문화해야 한다.

따라서 framework는 한 run에서 두 결과를 병렬로 생성한다.

| Track | 질문 | 포함 대상 | 논문 역할 |
|---|---|---|---|
| Canonical Benchmark Track | 알려진 canonical signaling을 얼마나 정확히 회복하는가? | measurable Tier 1/2 anchor | algorithm accuracy·temporal fidelity·branch coherence |
| High-sensitivity Discovery Track | 깊은 측정이 무엇을 새롭게 보였는가? | Tier 3/4, de novo, reference-unmatched PTM, novel temporal wave, unexplained multisite divergence | instrument-enabled discovery·생물학적 가설·후속 검증 후보 |

두 track을 분리해야 canonical score가 novel discovery로 부풀려지지 않고, 반대로 최신 장비의 발견력이 “score에 없는 잡음”으로 사라지지 않는다.

## 1. Discovery Track의 대상

| Discovery class | 정의 | Canonical score | Discovery report |
|---|---|---|---|
| Tier 3/4 contextual anchor | 문맥 의존적이거나 해석용으로만 정의된 known site | 불포함 | known-but-noncanonical context로 표시 |
| High-confidence de novo PTM | control에서 미검출, treated time course에서 재현성 있게 관측 | 불포함 | detection pattern·first appearance·persistence를 별도 표시 |
| Reference-unmatched PTM | locked workbook anchor에 없지만 sequence/site mapping과 localization이 가능한 PTM | 불포함 | novel candidate로 표시 |
| Deep-coverage low-abundance PTM | 낮은 signal이나 고감도 acquisition으로 안정적으로 검출된 PTM | 불포함 | quantification/localization/replicate quality와 함께 표시 |
| Novel temporal Wave | canonical anchor 밖에서 안정된 co-wave 또는 cascade position을 보이는 PTM group | 불포함 | Wave stability·TMM·directionality evidence로 표시 |
| Multisite divergence | 같은 protein의 site가 상반된 시간 패턴 또는 kinase mixture를 보임 | 불포함 | site-pair observation과 evidence gate로 표시 |

`novel`은 “생물학적으로 이전에 한 번도 보고되지 않았다”는 의미로 자동 사용하면 안 된다. Primary label은 **reference-unmatched within the locked benchmark** 또는 **not retrieved from the configured ChromaDB evidence**처럼 provenance가 명확한 표현으로 한다. 문헌 미보고 주장은 별도의 curated database/literature verification과 검증이 필요하다.

## 2. Discovery quality tier

고감도 자료에서는 단순 검출 수가 discovery quality가 아니다. 각 candidate에 아래 관찰·추론 분리 evidence를 붙인다.

| Quality tier | 필요한 관찰 증거 | 허용되는 해석 |
|---|---|---|
| DQ0: observed-only | 한 조건 또는 낮은 replicate support, localization/quantification 불완전 | 관측됨; 가설 생성 전 단계 |
| DQ1: reproducible detection | 사전등록된 replicate detection rule 충족, sequence·site provenance 보존 | 재현성 있게 관측됨 |
| DQ2: regulated temporal event | DQ1 + protein-normalized regulation 또는 de novo detection pattern + compatible temporal evidence | 시간 의존적 PTM event |
| DQ3: network-supported candidate | DQ2 + stable Wave, TMM contribution 또는 evidence-aware directionality/multisite support | candidate signaling-module member |
| DQ4: perturbation-supported candidate | DQ3 + 동결된 model에서 독립 inhibitor contrast 또는 orthogonal assay가 지지 | perturbation-supported candidate; direct target 단정 금지 |

이 tier는 canonical truth의 대체물이 아니다. Confidence와 후속 검증 우선순위를 표현하기 위한 discovery provenance다.

## 3. 자동 생성할 discovery 정량

| 정량 | 정의 | canonical score와의 관계 |
|---|---|---|
| Discovery yield | DQ1 이상 candidate 수; PTM/protein/time-window별 분해 | 별도 보고; accuracy에 합산 금지 |
| Reproducible novel yield | DQ1 이상 reference-unmatched/de novo candidate 수와 replicate fraction | acquisition depth와 재현성 동시 제시 |
| Regulated discovery yield | DQ2 이상 candidate의 protein-normalized 변화 또는 de novo pattern | known anchor recall과 분리 |
| Temporal discovery yield | DQ3 candidate의 stable Wave/lag/divergence 수 | time-series가 추가한 정보량 제시 |
| Low-abundance coverage | intensity/precursor quality strata별 reproducible detection | 고감도 장비의 coverage 특성 제시 |
| Kinase-attribution diversity | high-confidence TMM mixture·shared substrate·sparse fallback 분포 | direct substrate count로 과장하지 않음 |
| Validation-ready yield | DQ3–DQ4 candidate 중 predeclared validation gate 충족 수 | 후속 inhibitor/PRM/antibody 후보 queue |

Discovery yield는 장비 간 공정 비교를 위해 acquisition amount, sample loading, search/database settings, localization threshold, FDR, missingness rule과 함께 표시해야 한다. 단순 PTM 개수 하나만으로 “더 민감하다”고 결론내리지 않는다.

## 4. 논문용 시각화와 보충자료

| 결과물 | 구성 | 보여주는 가치 |
|---|---|---|
| Main/Extended Data: Dual-track summary | 왼쪽 canonical component score, 오른쪽 DQ1–DQ4 discovery yield | accuracy와 discovery를 같은 축에 섞지 않고 병렬 제시 |
| Discovery temporal atlas | 행=novel candidate, 열=timepoint, 색=protein-normalized PTM change; tier·wave membership annotation | 고감도 자료가 만든 시간적 발견 |
| Novelty/quality waterfall | 전체 observed → reproducible → regulated → network-supported → perturbation-supported candidate 수 | 후보 선별 과정의 투명성 |
| Intensity–reproducibility plot | intensity/precursor quality 대 replicate detection·temporal stability | low-abundance 결과의 신뢰도 공개 |
| Wave/TMM discovery network | DQ3 candidate와 canonical wave/kinase contribution 연결 | 새 PTM이 신호 모듈에 어떻게 연결되는지 제시 |
| Multisite divergence atlas | protein별 site pair trajectory 및 mixture distance | protein-level 평균으로 사라지는 조절 가능성 제시 |
| Validation queue table | DQ3/4 candidate, evidence, required next assay, inhibitor/orthogonal support 상태 | 후속 실험의 우선순위 |

Supplementary source data에는 모든 discovery candidate를 포함한다. 대표 사례만 보이면 선택 편향이 생기므로, 본문에서는 미리 정의한 selection rule로 2–4개 exemplar를 선택하고 전체 atlas·TSV는 보충자료에 제공한다.

## 5. Discovery candidate source-data schema

`discovery_candidates.tsv`의 한 행은 하나의 site/form candidate이며, 최소 아래 열을 포함한다.

```text
candidate_id, gene, accession, fasta_taxon, peptide_sequence, modified_sequence,
site, localization_confidence, precursor_charge, protein_group,
control_detection, treated_detection_by_time, first_detection, persistence,
raw_log2fc_by_time, protein_normalized_log2fc_by_time, q_value_by_time,
mean_intensity_by_time, replicate_detection_fraction, missingness_profile,
discovery_class, discovery_quality_tier, canonical_anchor_status,
wave_id, wave_stability, tmm_candidates, tmm_contribution, tmm_confidence,
directionality_tier, multisite_divergence_id, chromadb_evidence_status,
validation_priority, allowed_wording, run_id, input_hash, analysis_commit
```

LLM/Data-Grounded Analysis가 candidate를 해석할 때는 이 table의 observed evidence와 configured ChromaDB evidence만 사용한다. Benchmark workbook truth, non-observed biological expectation, 또는 external untracked knowledge를 novel discovery의 근거로 추가하지 않는다.

## 6. Inhibitor validation과의 연결

고감도 discovery track은 inhibitor experiment를 사전제약하지 않는다. Final model을 freeze한 뒤, inhibitor condition에서 다음 기준을 충족하는 DQ3 candidate가 DQ4로 승격될 수 있다.

| DQ3 관찰 | Perturbation에서 볼 변화 | DQ4 표기 |
|---|---|---|
| Target-associated TMM contribution | target contribution의 2×2 interaction contrast 변화 | perturbation-supported attribution candidate |
| Target Wave member | amplitude 감소, onset 지연, persistence 변화 | perturbation-responsive temporal candidate |
| Downstream directionality | D-tier 약화 또는 lag 변화 | perturbation-consistent temporal relationship |
| Multisite divergence | site-specific contrast가 재현 | condition-sensitive multisite regulation |

DQ4도 direct kinase-substrate 관계의 확정 증거가 아니다. 이는 동결된 분석의 예측이 perturbation pattern과 정합적이라는 강한 후보 근거이며, targeted MS, phospho-specific antibody, genetic perturbation 같은 orthogonal validation의 우선순위를 높인다.

## 7. 논문 표현의 경계

| 허용되는 표현 | 피해야 할 표현 |
|---|---|
| “The high-sensitivity time-course detected additional reproducible, temporally regulated phosphosites outside the locked canonical benchmark.” | “All additional sites are novel biology.” |
| “These candidates were excluded from canonical accuracy and reported in a separate discovery track.” | “Novel candidate count improved benchmark accuracy.” |
| “A candidate was network-supported by stable Wave/TMM/temporal evidence.” | “The candidate is a direct substrate solely because it co-varied with a kinase.” |
| “The inhibitor interaction supported a condition-specific candidate relationship.” | “The inhibitor proved a direct causal kinase-substrate link.” |

## 8. 권장 논문 서사

논문은 두 결과를 경쟁시키지 않고 보완적으로 제시한다.

> “We first used a locked canonical insulin reference to quantify recovery of established temporal signaling. Separately, the high-sensitivity acquisition yielded additional reproducible and temporally structured PTMs outside that reference. These discoveries were not counted toward canonical accuracy; instead, they were ranked by measurement, temporal, network, and perturbation evidence for follow-up validation.”

이 구조라면 benchmark는 기존 생물학에 대한 **정확도**를, discovery track은 최신 고감도 질량분석과 PTM-platform이 제공하는 **새로운 정보량과 가설 생성력**을 담당한다. 두 장점은 서로 상쇄되지 않고 같은 논문의 두 축이 된다.
