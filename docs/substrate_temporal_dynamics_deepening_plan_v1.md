# Substrate-level Temporal Dynamics Deepening Plan v1

작성일: 2026-08-22 (GMT+9)  
상태: **계획안 — 구현 전 검토 필요**

## 1. 목표와 해석 경계

현재 canonical Temporal Wave Engine은 co-moving PTM site 집단을 재현 가능하게 만들고, 집단 평균 profile을 `transient_burst`, `sustained_activation`, `biphasic_switch` 등으로 요약한다. 그러나 이는 **wave 수준의 요약**이며, 개별 substrate/site가 같은 wave 안에서 보이는 onset, peak, duration, recovery, rebound, 다중 peak, condition-specific divergence를 설명하지 못한다.

새 층의 목적은 Track 2 protein-normalized relative PTM trajectory를 site/form 단위로 측정·분해하는 것이다. 이는 kinase가 해당 site를 직접 인산화했다거나 관찰된 반복이 biological oscillator임을 증명하지 않는다.

> “Periodic”은 반복된 봉우리처럼 보이는 line plot의 시각적 인상이 아니라, 시간 순서·불규칙 간격·반복성·replicate stability를 통과한 경우에만 사용할 수 있다. 그렇지 않으면 `multi_peak_candidate` 또는 `unresolved_complex`로 기록한다.

## 2. 현 코드 진단

| 영역 | 현재 상태 | 한계 |
|---|---|---|
| Canonical co-wave | `ptm_shared/temporal_wave_engine.py`에서 signed Pearson/average linkage로 wave 생성 | member detail은 peak time과 max FC 중심이며 site-level kinetic descriptor가 없음 |
| Wave pattern | wave 평균 profile에서 `transient_burst`, sustained, biphasic 등을 지정 | cluster 평균이 member별 early/late/rebound heterogeneity를 가릴 수 있음 |
| Frontend trend label | `OrderDetail.tsx`의 별도 heuristic `classifyTrend()` | canonical engine과 별개여서 UI label과 backend provenance가 불일치할 수 있음 |
| Directionality | 분 기반 onset/peak lag, bootstrap·LOTO·permutation 지원 | site 자체의 duration/recovery/repeated-peak feature를 표준 계약으로 내보내지 않음 |
| TMM | condition-specific kinase contribution decomposition | substrate kinetic phenotype의 분포/heterogeneity는 아직 diagnostic evidence로 사용되지 않음 |

## 3. P0 — 입력 및 plot audit

먼저 그림의 높은 반복 peak를 생물학적 주기로 해석하지 않는다. 다음 항목을 dataset별 provenance로 검증한다.

1. x-axis가 replicate/condition block이 아니라 minute-normalized unique timepoint인지 확인한다.
2. raw Track 2 value, replicate count, q-value, missing mask와 line rendering input이 동일한지 확인한다.
3. 0-fill 또는 spline smoothing이 peak를 만들지 않았는지 확인한다. 분류는 관측값에만 적용하고, smoothing은 시각 보조선으로만 표시한다.
4. 동일 site의 PTM form/charge aggregation과 protein-normalization 전후 signal을 분리해 확인한다.

### P0 acceptance criteria

- 모든 plotted substrate에 `timepoint_minutes`, observed/missing mask, Track 2 value, q-value provenance가 존재한다.
- line plot의 x-axis order가 canonical time parser와 동일하다.
- repeated shape가 rendering artifact이면 `plot_artifact_warning`을 남기고 biological class를 부여하지 않는다.

## 4. P1 — Canonical Site Temporal Dynamics Contract

`ptm_shared/substrate_temporal_dynamics.py`를 새 단일 출처로 만든다. API, report, co-wave UI가 같은 계산 결과를 소비하고 frontend local heuristic은 제거하거나 display-only adapter로 축소한다.

### 4.1 Site/form별 관측 feature

| Feature family | 필드 예시 | 의미 |
|---|---|---|
| Signal/quality | `amplitude`, `dynamic_range`, `observed_timepoints`, `replicate_support`, `qvalue_coverage` | 어느 정도의 signal과 관측 근거가 있는가 |
| Onset/peak | `onset_minutes`, `peak_minutes`, `peak_sign`, `peak_prominence`, `secondary_peak_minutes` | 언제 반응이 시작·최대화됐는가 |
| Duration | `active_duration_minutes`, `time_above_threshold`, `auc_signed`, `auc_absolute` | 반응이 얼마나 유지됐는가 |
| Rise/recovery | `rise_slope`, `decay_slope`, `recovery_minutes`, `return_to_baseline` | 급성 relay, adaptation, recovery를 구분하는 관측 feature |
| Shape | `sign_switch_count`, `local_extrema_count`, `peak_separation_minutes`, `monotonicity` | reversal·multi-peak·complexity를 기술 |
| Uncertainty | `bootstrap_class_support`, `leave_one_timepoint_out_stability`, `threshold_sensitivity`, `missingness_warning` | label을 얼마나 신뢰할 수 있는가 |

Threshold는 fixed `|Log2FC|`만 쓰지 않는다. baseline/replicate noise와 q-value eligibility를 함께 쓰고, dataset-specific threshold provenance를 저장한다. Track 1 apparent paired occupancy는 O1/O2 coverage가 있는 경우 only secondary concordance로 기록하며 Track 2를 대체하지 않는다.

### 4.2 계층형 temporal pattern taxonomy

아래 taxonomy는 exclusive label이 아니라 `primary_pattern` + `modifiers` 구조를 사용한다. 예를 들어 `delayed_single_pulse` + `rebound_absent`는 가능하지만, `oscillatory_supported`는 강한 검증 없이는 생성되지 않는다.

| Layer | Pattern | 최소 관측 정의 |
|---|---|---|
| Baseline | `flat_or_low_evidence` | amplitude/quality가 분류 gate 미달 |
| Monotone | `monotonic_rise`, `monotonic_decline` | Δt 보정 slope 방향이 안정적 |
| Single response | `early_single_pulse`, `delayed_single_pulse`, `transient_suppression` | prominent peak/valley 1개와 recovery 또는 baseline return |
| Sustained | `sustained_activation`, `sustained_suppression` | onset 뒤 최소 active-duration 및 direction consistency |
| Adaptation | `biphasic_switch`, `rebound`, `overshoot_recovery` | 유의한 sign reversal 또는 primary peak 뒤 반대 방향 recovery |
| Recurrent | `multi_peak_candidate`, `oscillatory_supported` | 2개 이상 separated prominent extrema; 후자는 최소 2 cycle, 충분한 sampling, bootstrap stability 필요 |
| Complex | `heterogeneous_or_unresolved` | above criteria가 상충하거나 missingness/LOTO가 불안정 |

`oscillatory_supported`는 일반 6 timepoint experiment에서 대개 보수적으로 비활성화한다. 최소 6–8 observed points, two complete cycles, peak interval consistency, replicate/LOTO support를 요구한다. 이를 만족하지 않으면 “periodic”이라고 쓰지 않는다.

## 5. P2 — Condition-aware substrate divergence

각 site/form에 대해 condition별 dynamics profile을 산출하고, 단순 Log2FC difference가 아니라 feature vector의 차이를 평가한다.

```text
same site/form
  ├─ onset shift (min)
  ├─ peak shift (min)
  ├─ amplitude ratio / sign discordance
  ├─ active-duration difference
  ├─ recovery/rebound difference
  └─ pattern transition (e.g., early pulse → sustained)
```

분류 결과는 `shared`, `condition_shifted`, `condition_specific`, `unresolved`로 표기한다. Multi-site divergence contract와 연결하되, site pair의 observed dynamics가 충분한 evidence tier일 때만 Data-Grounded Analysis로 전달한다.

## 6. P3 — Co-wave·TMM 통합

### Co-wave

- wave 자체의 pattern은 유지하되, 각 wave에 **member dynamics composition**을 추가한다.
- 예: “Wave TW-03은 early pulse 70%, delayed pulse 20%, unresolved 10%로 구성; mean transient burst가 member-level uniformity를 의미하지 않음.”
- cluster coherence가 높더라도 member peak dispersion, pattern entropy, duration heterogeneity를 함께 보여준다.

### TMM

- TMM의 primary input과 contribution coefficient는 변경하지 않는다.
- 후보 kinase별 exclusive/shared substrate의 `peak/onset/duration` 분포, phenotype entropy, TMM residual과의 관계를 **diagnostic evidence**로만 추가한다.
- `dynamic phenotype concordance`는 “조건 특이적 설명력”의 보조 지표이며 direct phosphorylation proof가 아니다.
- time-course에서 kinase profile보다 먼저 일어난 substrate는 TMM attribution confidence를 올리지 않으며, D0–D3 temporal precedence contract를 그대로 적용한다.

## 7. P4 — UI와 report

### UI

전역 spaghetti plot을 primary interpretation view로 쓰지 않는다. 다음의 drill-down 구조를 사용한다.

1. **Dynamics atlas:** pattern × peak window × condition의 site count heatmap.
2. **Pattern filter:** early/delayed/sustained/rebound/multi-peak/unresolved filter.
3. **Small multiples:** 선택된 substrates의 raw Track 2 trajectory와 optional replicate/CI를 개별 panel로 표시.
4. **Site detail drawer:** raw values, missing mask, protein context, Track 1 availability, feature values, stability flags, candidate kinase/TMM evidence를 보여준다.
5. **Wave composition panel:** wave 평균선과 member temporal phenotype distribution을 동시에 표시한다.

### Report/RAG

- Results에 “Substrate Temporal Dynamics Atlas”를 추가한다.
- 각 user Research Question에는 가장 관련 있는 substrate trajectory 2–5개와 `answer status`를 연결한다.
- RAG에는 observed facts만 넣는다. 예: “MAPK8-associated substrates show delayed single pulses at 30–60 min”은 가능하지만 “MAPK8 drives oxidative stress”는 direct evidence/validation 없이는 쓰지 않는다.

## 8. P5 — Benchmark와 acceptance criteria

### Insulin signaling primary benchmark

직접 설계할 insulin time-course에 dense early timepoints와 biological replicates를 확보한다. 알려진 early AKT/ERK dynamics는 calibration anchor로만 쓰며, prior가 class를 결정하지 않게 한다.

| 검증 | 기준 |
|---|---|
| Time-order validity | time permutation에서 pattern/kinase linkage가 유지되면 실패 처리 |
| Replicate stability | bootstrap class support와 feature CI를 기록 |
| LOTO stability | 한 timepoint를 제외해도 primary pattern이 불필요하게 바뀌지 않는지 측정 |
| Missingness robustness | observed mask perturbation에서 class change rate 기록 |
| Condition contrast | condition-label permutation보다 observed dynamics divergence가 커야 함 |
| Interpretability | 모든 label이 raw site/form/timepoint/Track 2 evidence로 역추적 가능해야 함 |

### 구현 순서

| Priority | Deliverable | 범위 |
|---|---|---|
| P0 | x-axis/provenance audit | 즉시, 기존 output 변경 없음 |
| P1 | `substrate_temporal_dynamics.v1` pure engine + tests | site-level feature/label source of truth |
| P2 | API/TSV schema + condition comparison | observables와 uncertainty 노출 |
| P3 | co-wave/TMM diagnostics | ranking 불변, explanation 보강 |
| P4 | UI dynamics atlas + report integration | spaghetti plot 대체가 아닌 drill-down 보완 |
| P5 | insulin benchmark + frozen thresholds | production labels의 evidence gate |

## 9. 외부 방법론 근거

연속 시간 trajectory를 사용하면 independent categorical timepoint 비교보다 시간점 사이의 의존성, transient response와 permanent change를 명시적으로 다룰 수 있다. 다만 본 플랫폼은 count-model을 그대로 이식하지 않고, protein-normalized quantitative PTM Track 2와 불규칙 minute time encoding에 맞춘 descriptive feature contract를 사용한다.[1]

Temporal phosphoproteomics에서 trajectory cluster와 기능 enrichment를 결합해 stage-specific PTM regulation을 해석하는 접근은 유용하지만, cluster 평균만으로 개별 phosphosite의 kinetic diversity를 대체할 수는 없다.[2] 최신 longitudinal proteome/phosphoproteome 연구도 protein과 phosphosite trajectory의 discordance 및 early plateau/late increase 등 site-level dynamics의 별도 해석 필요성을 보여준다.[3]

## References

[1] Fischer DS, Theis FJ, Yosef N. [Impulse model-based differential expression analysis of time course sequencing data](https://pmc.ncbi.nlm.nih.gov/articles/PMC6237758/). *Nucleic Acids Research*. 2018;46:e119.

[2] Dumrongprechachan V, et al. [Dynamic proteomic and phosphoproteomic atlas of corticostriatal axons in neurodevelopment](https://elifesciences.org/articles/78847). *eLife*. 2022;11:e78847.

[3] Hao Y, et al. [Temporal dynamics of proteome and phosphorproteome during neuronal differentiation in the reference KOLF2.1J iPSC line](https://pmc.ncbi.nlm.nih.gov/articles/PMC12190317/). *bioRxiv*. 2025; updated peer-reviewed version cited in PubMed.
