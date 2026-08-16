# Dual-Track PTM Quantification Contract v1 — Draft

작성일: 2026-08-16 (GMT+9)
상태: **설계 초안 — core quantification 변경 전 사용자 승인 필요**

## 목적

PTM-platform의 unenriched Astral DIA 설계는 total proteome의 non-PTM abundance를 잃지 않으면서, 동일 run에서 검출된 modified peptide를 시간축으로 해석하는 데 목적이 있다. 본 계약은 이를 유지한 채 두 가지 상보적 정량 evidence를 구분한다.

| Track | 대상 | 관찰량 | 주된 용도 |
|---|---|---|---|
| **Track 1: paired occupancy** | 동일 peptide backbone의 modified/unmodified counterpart가 모두 정량된 경우 | paired peptide form의 occupancy 또는 apparent occupancy | stoichiometric switch 후보, site/form-specific temporal change, 구조·기능 가설의 최우선 후보 선별 |
| **Track 2: protein-normalized relative PTM** | counterpart pair가 없거나 occupancy quality gate를 통과하지 못한 모든 검출 modified precursor | `modified precursor / protein-group abundance`의 baseline 대비 log2FC | coverage 보존, co-wave, TMM, candidate kinase-associated program 및 non-PTM effector와의 temporal integration |

두 track은 경쟁 관계가 아니다. Track 1은 높은 특이성이나 제한된 coverage를, Track 2는 더 넓은 coverage와 protein-abundance correction을 제공한다. 기존 Track 2 경로는 삭제하거나 대체하지 않는다.

## 중요한 용어 경계

단순 raw intensity 식

```text
I_modified / (I_modified + I_unmodified)
```

은 0–1 범위의 **paired signal fraction**을 제공한다. 그러나 phosphorylation은 modified와 unmodified peptide의 ionization·fragmentation response factor를 예측 불가능하게 변화시킬 수 있다. 그러므로 calibration 없이 이 값을 물리적·절대적 site occupancy라고 표기하면 안 된다.[1] [2]

| Track 1 상태 | 산식 | 허용되는 표기 |
|---|---|---|
| `calibrated_absolute_occupancy` | `O = (cM × I_M) / (cM × I_M + cU × I_U)` | response factor 또는 isotope/internal-standard/phosphatase-calibration이 provenance에 존재할 때만 `absolute occupancy (%)` |
| `apparent_paired_occupancy` | `O_app = I_M / (I_M + I_U)` | calibration 없는 paired MS-intensity fraction; `apparent occupancy (%)` 또는 `paired signal fraction (%)` |
| `protein_normalized_relative_ptm` | `R = log2[(I_M / I_P)_t / (I_M / I_P)_baseline]` | 기존의 protein-normalized relative PTM signal |

> 구조 변화 또는 chemical stoichiometric switch를 강하게 주장할 최상위 target은 `calibrated_absolute_occupancy`에 한정한다. `apparent_paired_occupancy`는 우선순위화와 temporal pattern discovery에는 유용하지만, calibration 전에는 물리적 점유율의 증명으로 사용하지 않는다.

## Pair matching 계약

현재 `PTMQuantificationAnalyzer`는 `Modified.Sequence`의 UniMod 표기를 통해 modified precursor를 찾고, PG matrix로 나눈 Track 2 값을 생성한다. counterpart peptide matching은 아직 구현되어 있지 않다. 새 matcher는 아래 조건을 모두 provenance로 기록해야 한다.

| Gate | 필수 조건 | 실패 시 처리 |
|---|---|---|
| Same peptide backbone | target UniMod을 제거한 clean sequence와 tryptic boundary가 동일 | Track 2만 사용 |
| Protein mapping | 동일하고 non-ambiguous한 target accession 또는 허용된 protein-group mapping | pair 제외 및 ambiguity flag |
| Modification form | modified row는 target PTM을 정확히 한 개 포함; unmodified counterpart는 target PTM을 포함하지 않음 | multi-form/ambiguous form으로 별도 보존, site occupancy 계산 제외 |
| Site localization | localization confidence와 precursor q-value가 입력 metadata에서 확인됨 | `localization_unverified`로 Track 1 high-confidence 제외 |
| Quantitative completeness | 각 timepoint에서 M/U 모두 최소 replicate 수를 충족 | 해당 timepoint occupancy를 missing으로 저장; 0으로 대체 금지 |
| Signal quality | 기준 intensity·CV·interference threshold를 통과 | low-quality pair로 flag, Track 2 유지 |

charge state·transition이 여럿이면, 동일 form 내에서 validated precursor intensity를 먼저 aggregate한다. 다른 variable modification을 포함하는 species와 multi-phosphorylated peptide는 단순 단일-site counterpart로 합치지 않으며, `peptide_form_occupancy`로 명시적으로 별도 처리한다.

## 저장 계약

기존 vector output에 선택적으로 다음 필드를 추가한다. 내부의 `PTM_Relative_Log2FC` 및 기존 API field는 유지하여 backward compatibility를 보장한다.

| 필드 | 예시 | 의미 |
|---|---|---|
| `quantification_track` | `calibrated_absolute_occupancy` / `apparent_paired_occupancy` / `protein_normalized_relative_ptm` | 해당 행의 우선 정량 evidence |
| `paired_peptide_key` | `P12345:AASTYRK:z2` | modified/unmodified counterpart의 stable matching key |
| `paired_form_level` | `site` / `peptide_form` | single-site인지 multi-modified form인지 |
| `occupancy_fraction` | `0.273` | 0–1 범위의 calibrated 또는 apparent fraction |
| `occupancy_percent` | `27.3` | display 전용 값 |
| `occupancy_delta_pp` | `+14.1` | baseline 대비 percentage-point 변화 |
| `occupancy_logit_delta` | `+0.78` | temporal wave/TMM에 사용할 signed, bounded-value-aware 변화량 |
| `occupancy_calibration_type` | `heavy_pair` / `phosphatase` / `response_factor` / `none` | absolute claim 가능 여부의 provenance |
| `pair_quality_tier` | `O1` / `O2` / `O0` | calibrated high confidence / apparent qualified / not qualified |
| `pair_missingness` | `0.11` | M/U pair가 모두 검출되지 않은 fraction |

## Co-wave와 TMM의 통합 규칙

### Version 1: 분리 계산 후 evidence-aware 결합

처음부터 Track 1과 Track 2를 하나의 amplitude로 합치지 않는다. 점유율과 relative log2FC는 다른 scale과 measurement error를 가지므로, 임의 가중 평균은 새로운 편향을 만들 수 있다.

| 분석 단계 | Track 1 qualified pair | Track 2 |
|---|---|---|
| Wave input | `occupancy_logit_delta` 또는 `occupancy_delta_pp` | 기존 `PTM_Relative_Log2FC` |
| Co-wave | occupancy wave 별도 계산, paired form provenance 유지 | 기존 relative-signal wave 유지 |
| TMM profile | 충분한 O1/O2 exclusive substrate가 있을 때 occupancy-specific profile 생성 | 기존 relative-track data-driven profile 유지 |
| Shared-site attribution | occupancy TMM 결과를 Track 1 evidence로 기록 | relative TMM을 coverage-primary attribution으로 유지 |
| Dual-track conclusion | 방향·peak window·candidate ranking이 합치면 confidence 승격 | 불일치 시 결론 병합 금지, `track_discordance` flag |

`dual_track_concordant`는 두 track의 correlation, peak-lag tolerance, contribution-rank concordance, completeness를 만족할 때만 생성한다. `O1` calibrated occupancy와 Track 2가 같은 kinase candidate를 지지하면 TMM conclusion의 설명력을 높일 수 있으나, 이는 직접 kinase activity 또는 direct phosphorylation 증명이 아니다.

### 결측치 처리 계약: observed-only를 기본으로 한다

paired occupancy에서 M 또는 U 중 하나가 검출되지 않은 timepoint는 분자 또는 분모가 없는 값이다. 이를 0으로 바꾸거나 기본 경로에서 선형 보간하면, 실제로 관찰하지 못한 occupancy peak·valley·lag를 인위적으로 생성할 수 있다. 따라서 Track 1의 default policy는 **observed-only**이며, 결측치는 `NaN`과 reason code로 보존한다.

| 상황 | Default policy | Co-wave/TMM 처리 | Provenance |
|---|---|---|---|
| M/U 모두 최소 replicate 수 충족 | observed occupancy 계산 | 분석에 포함 | `observed` |
| M 또는 U가 부족 | occupancy = missing | 0으로 대체하지 않음 | `missing_modified` / `missing_unmodified` / `insufficient_replicates` |
| 관측 timepoint가 너무 적음 | pair의 Track 1 time-series를 drop | Track 2만 유지 | `dropped_insufficient_observations` |
| 내부의 단일 short gap | default 분석에는 drop; optional sensitivity run에서만 linear interpolation | primary evidence에 사용 금지 | `imputed_linear_sensitivity_only` |
| edge gap 또는 2개 이상 연속 gap | 보간 금지 | Track 1 drop, Track 2 유지 | `dropped_gap_too_long` |

#### 분석 적격성 규칙

| 대상 | 최소 요건 | 미충족 시 |
|---|---|---|
| Occupancy co-wave membership | 전체 ordered timepoint 중 **최소 70%**가 observed이고, 최소 4개 observed timepoint 및 peak 전후 각각 1개 이상 observed | occupancy wave 제외; Track 2 wave는 계속 실행 |
| Occupancy-specific kinase profile | 위 coverage 요건을 만족하는 O1/O2 exclusive substrate가 최소 3개 | `occupancy_profile_insufficient`로 기록하고 relative-track profile만 사용 |
| Occupancy TMM shared-site fit | 유효 observed timepoint 수가 `max(4, candidate kinase 수 + 1)` 이상이며, 내부 결측 gap이 1개 timepoint 이하 | occupancy TMM을 수행하지 않고 Track 2 TMM만 보고 |
| Linear interpolation sensitivity run | 보간 대상이 내부 단일 gap이고 양쪽 adjacent point가 observed이며, observed occupancy가 [0, 1] 범위 | 별도 sensitivity result만 생성; primary score/kinase ranking 변경 금지 |

선형 보간이 sensitivity 결과에서도 원래의 observed-only conclusion과 다른 co-wave membership, peak window 또는 top kinase rank를 만들면 `imputation_sensitive` flag를 부여한다. 이 경우 dual-track concordance를 승격하지 않으며, report에는 observed-only 결과만 주된 근거로 사용한다.

현재 `ptm_timeseries` 경로는 존재하지 않는 condition 값에 대해 일부 분석 함수가 `0.0`을 default로 읽는 구조다. Track 1 도입 시에는 실제 zero intensity, missing precursor, insufficient replicate를 명시적으로 분리해야 하며, occupancy path에는 NaN-aware filtering을 먼저 적용한 뒤 적격한 complete/near-complete vector만 co-wave 및 NNLS에 전달해야 한다.

### Version 2: multi-view TMM은 별도 검증 후

향후에는 occupancy-logit trajectory와 protein-normalized relative trajectory를 measurement variance로 표준화한 multi-view objective로 공동 적합할 수 있다. 그러나 이 단계는 synthetic pair benchmark, real heavy-standard subset, missingness stress test에서 Version 1보다 안정적임이 검증된 뒤에만 도입한다.

## Report·3D 구조 활용 규칙

| Evidence tier | 보고서 표현 | 구조/기능 활용 |
|---|---|---|
| O1 calibrated | “S123 occupancy increased from 12% to 47% (calibrated).” | stoichiometric switch 및 구조 모델링의 최우선 candidate; 구조 효과는 별도 검증 가설 |
| O2 apparent paired | “paired signal fraction increased from 12% to 47%; calibration unavailable.” | strong temporal candidate; absolute structural threshold 주장 금지 |
| Track 2 only | “protein-normalized modified-peptide signal increased.” | kinase-associated program, wave, TMM 및 downstream response 해석 |
| Discordant tracks | “paired and protein-normalized evidence were discordant.” | biological heterogeneity, pair interference, multi-form ambiguity를 포함한 검토 대상으로 격리 |

## 검증 계획

| 검증 | 성공 기준 |
|---|---|
| Unit test: sequence matcher | UniMod removal, same backbone, multi-modified exclusion, shared peptide ambiguity를 올바르게 구분 |
| Unit test: numerical contract | calibrated/apparent formula, denominator zero·missing value handling, 0–1 bounds, baseline transforms 확인 |
| Regression test | 기존 Track 2 TSV/API/TMM output이 occupancy metadata 부재 시 byte-level 또는 semantic backward compatibility 유지 |
| Pair completeness audit | per-timepoint M/U detection, intensity, CV, q-value, localization provenance를 표로 출력 |
| Dual-track concordance | O1/O2 subset에서 occupancy와 Track 2의 sign/peak/rank agreement를 보고; 불일치를 숨기지 않음 |
| Calibration subset | heavy peptide pair, response-factor measurement 또는 phosphatase control이 있는 small targeted set에서 O1 validity 평가 |
| Missingness stress test | 실제 complete pair vector에 단일/연속/edge gap을 주입하여 observed-only, drop, sensitivity interpolation의 peak·wave·kinase rank 안정성 비교 |

## 구현 순서와 승인 지점

1. **P0 — provenance-only pairing audit:** PR matrix에서 pair candidate와 quality table을 출력하고, 기존 Track 2·co-wave·TMM에는 영향을 주지 않는다.
2. **P1 — Track 1 output:** apparent/calibrated occupancy field와 confidence tier를 vector output·API·frontend에 노출한다. 분석 ranking은 변경하지 않는다.
3. **P2 — dual-track evidence layer:** co-wave/TMM을 track별로 실행하고 concordance/discrepancy만 보고한다. 기존 relative TMM score를 대체하지 않는다.
4. **P3 — optional decision policy:** real insulin dataset과 calibration subset에서 검증 후에만, O1 evidence를 TMM/report priority에 반영한다.

P0–P2는 기존 기능을 보존하는 additive 변경이지만, P3는 kinase ranking과 report priority에 영향을 줄 수 있는 핵심 scoring 정책 변경이다. 따라서 P3 전에는 사용자 승인이 필요하다.

## References

[1] Johnson H, et al. *Rigorous Determination of the Stoichiometry of Protein Phosphorylation Using Mass Spectrometry.* J Am Soc Mass Spectrom (2009). https://www.liverpool.ac.uk/pfg/PDF/09_Johnson_JASMS.pdf

[2] Chaube RC. *Absolute quantitation of post-translational modifications.* Frontiers in Chemistry (2014). https://www.frontiersin.org/journals/chemistry/articles/10.3389/fchem.2014.00058/full

[3] Li Y, et al. *Absolute Quantitation of Isoforms of Post-translationally Modified Proteins in Transgenic Organism.* Molecular & Cellular Proteomics (2012). https://pmc.ncbi.nlm.nih.gov/articles/PMC3412961/
