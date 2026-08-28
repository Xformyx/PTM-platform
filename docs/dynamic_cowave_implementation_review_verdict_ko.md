# Dynamic Co-Wave 구현 검토 PDF에 대한 코드 대조 판정

**검토 대상:** `Dynamic_CoWave_Implementation_Review_20260828.pdf`
**대조 기준:** `ptm-platform` current `main` (`858d247` 기준)
**판정 범위:** Dynamic Co-Wave algorithm, canonical Wave/TMM/sidecar/Report handoff, benchmark isolation

## 결론

PDF가 지적한 다섯 가지 중 **두 가지는 즉시 수정해야 하는 실제 production 결함**이며, 한 가지는 중요한 설계 검증 과제, 두 가지는 논문용 확장 연구 과제입니다. 또한 코드 대조 과정에서 PDF에 명시되지 않은 더 중요한 결함 하나를 확인했습니다. 현재 low-level pair loop는 모든 qualified site 사이의 pair를 먼저 계산하고, wrapper가 나중에 cross-Wave pair event만 제거합니다. 그러나 site-level partner count는 이미 cross-Wave partner를 포함한 상태로 계산되어 있습니다. 이 경우 `joined_group`, `split_from_group`, `group_persistence`가 **다른 static Wave의 site 때문에** 발생할 수 있어, “static Wave 내부의 local transition”이라는 현재 기능 정의와 어긋납니다.

따라서 권장하는 즉시 작업은 **threshold default 통일**, **inert site event 제거/분리**, **static Wave 내부 pair만 계산**의 세 가지를 하나의 P0 corrective patch로 묶는 것입니다. 이 patch는 canonical Wave/TMM을 변경하지 않지만 Dynamic Co-Wave output과 LOTO/site summary는 바뀌므로, 적용 후 truth-free benchmark와 새 production Report를 재생성해야 합니다.

| 우선순위 | 판정 | 적용 권고 |
|---|---|---|
| P0 | threshold default 불일치 | 즉시 수정 |
| P0 | `state_unchanged_or_inactive` event 노이즈 | 즉시 수정 |
| P0 | **추가 발견: cross-Wave partner contamination + 불필요한 global pair loop** | 즉시 수정 |
| P1-검증 | endpoint-only window state | 현 default 유지, 병렬 sensitivity study 후 결정 |
| P1-통계 | null distribution / permutation | 논문에서 non-random claim 전에 구현 |
| P1-데이터 | replicate-aware posterior / GP/HMM | replicate-level time series persistence를 먼저 갖춘 뒤 별도 연구 |
| P1-평가 | inhibitor M1–M4 / GroupKFold | inhibitor dataset 확보 후 frozen prospective evaluation으로 구현 |
| P2 | pLM + curated evidence secondary attribution | perturbation benchmark 이후, optional prior layer로 구현 |

## 항목별 코드 대조

### 1. DEFAULT_CONFIG threshold 0.50 대 production frozen config 0.40

**판정: 실제 결함이며 즉시 수정해야 합니다.**

`ptm_shared/dynamic_cowave_transition.py`의 `DEFAULT_CONFIG["activity_threshold_fc"]`는 `0.50`이지만, canonical production configuration인 `ptm_shared/temporal_optimization_config.py::DYNAMIC_COWAVE_CONFIG`는 `0.40`입니다. 정상 sidecar builder는 config를 명시 전달하므로 일반 full Order에서는 0.40을 사용합니다. 하지만 public helper를 `analyze_dynamic_co_wave_transitions(wave_contract)`로 직접 호출하거나 `dynamic_transition_config_sha256(None)`를 호출하면 0.50 contract가 만들어집니다. focused regression도 일부 fixture에서 0.50을 명시하고 있습니다.

이는 현재 production output을 즉시 바꾸는 대규모 오류는 아니지만, 재사용·notebook·후속 worker·test에서 config drift를 만들 수 있는 single-source-of-truth 위반입니다. `DEFAULT_CONFIG`를 `DYNAMIC_COWAVE_CONFIG`에서 가져오거나 동일 0.40으로 정렬하고, no-config direct-call regression을 추가해야 합니다. 이 변경 뒤에는 explicit 0.40 production output이 변하지 않아야 합니다.

### 2. `state_unchanged_or_inactive` site event의 노이즈

**판정: 실제 결함이며 즉시 수정해야 합니다.**

`time_varying_comovement.py`는 모든 qualified site와 모든 adjacent-window transition마다 site record를 append합니다. 따라서 inactive→inactive, active이지만 partner가 없는 상태가 유지되는 경우도 `state_unchanged_or_inactive`로 full event set에 포함됩니다. 이 event는 pair transition처럼 의미 있는 co-activity change가 있을 때만 기록되는 것이 아닙니다.

PDF의 핵심 진단은 맞습니다. 다만 정확히 말하면 pair 기반 `transition_resolution` 자체는 `nonpersistence_pair_transition_count / pair_transition_count`이므로 이 site record 때문에 직접 왜곡되지는 않습니다. 대신 다음 값이 영향을 받습니다.

| 영향 받는 결과 | 문제 |
|---|---|
| `site_transition_count` 및 `per_wave_summary.site_transition_count` | inert site/window가 많을수록 의미 없는 count가 커짐 |
| site transition type histogram | `state_unchanged_or_inactive`가 지배해 event interpretation이 흐려짐 |
| site-level LOTO Jaccard | 반복되는 inert event가 stable ID로 남아 site stability를 인위적으로 높일 수 있음 |
| serialized example budget | capped example 안에서 informative event가 뒤로 밀릴 수 있음 |

권장 구현은 `state_unchanged_or_inactive`를 transition event list에 저장하지 않는 것입니다. 필요하다면 quality/profiling 전용 `site_transition_opportunity_count` 및 `unchanged_or_inactive_observation_count`를 summary에 별도로 보존합니다. 이러면 “event count”는 실제 state 또는 group relation 변화만 뜻하게 되고, background exposure와 혼동되지 않습니다.

### 3. endpoint-only window state

**판정: 코드 관찰은 맞지만 즉시 변경하면 안 됩니다.**

현재 local window의 state는 `end` value만으로 `inactive`, `positive_active`, `negative_active`를 결정합니다. `start`와 `local_delta`는 audit을 위해 저장하지만 active 여부에는 쓰이지 않습니다. 이 방식은 “그 interval 말미에 관찰된 state”라는 명료한 discrete time-course semantics를 갖고 있으며, cross-layer onset/peak ordering과도 일관되게 연결됩니다.

`max(abs(start), abs(end))`, signed maximum, mean 등의 대안은 각각 다른 생물학적 질문을 만듭니다. maximum은 window 중 한 번이라도 threshold를 넘은 상태, mean은 interval-average 상태에 가깝습니다. 어느 쪽도 자동으로 더 옳지 않으며, 현 engine을 validation 없이 바꾸면 기존 truth-free selection ledger와 Report interpretation을 동시에 바꾸게 됩니다.

권고는 current endpoint rule을 frozen baseline으로 유지하고, production default를 변경하지 않는 parallel sensitivity evaluator를 추가하는 것입니다. 동일 artifact에서 endpoint/signed-maximum/mean을 비교해 pair/site LOTO, active-pair coverage, transition resolution, event-class composition, cross-layer alignment를 기록합니다. 그 후 사전에 정한 objective와 blind holdout에 따라 선택해야 합니다.

### 4. O(n²) pair complexity

**판정: 성능 우려는 실제이며, 동시에 semantic P0 defect가 존재합니다.**

`compute_time_varying_comovement()`은 현재 `combinations(all_sites, 2)`로 **모든 qualified site의 global pair**를 순회합니다. wrapper는 이후 pair event 중 동일 static Wave인 경우만 retained event로 남깁니다. 따라서 static Wave 밖 pair는 최종 pair summary에는 들어가지 않아도 계산 비용을 이미 발생시킵니다.

현재 insulin Report가 언급한 2,447 phosphosite가 모두 qualified라고 가정하는 worst-case에서는 pair가 2,992,681개입니다. 5 timepoint는 adjacent transition 4개이므로 약 11,970,724개, 6 timepoint는 약 14,963,405개의 pair-state comparison이 발생합니다. 실제 qualified member 수와 static Wave 분포에 따라 더 작아질 수 있으므로, 이 수치는 runtime 측정이 아니라 upper bound입니다.

더 중요한 문제는 site event classification입니다. low-level loop는 global pair의 `before_partners`/`after_partners`를 먼저 계산합니다. wrapper는 site 자체가 static membership에 속하는지만 확인하고 이 partner set을 다시 static Wave로 제한하지 않습니다. 결과적으로 서로 다른 static Wave의 two sites가 같은 sign으로 active이면, site-level `joined_group`, `split_from_group`, `group_persistence`와 partner count가 cross-Wave activity로 오염될 수 있습니다.

**권장 P0 수정:** low-level engine에 optional `group_by_site` 또는 equivalent mapping을 추가하고, Dynamic Co-Wave wrapper가 immutable static `wave_id` mapping을 전달합니다. pair loop는 같은 group 안에서만 실행해야 합니다. 다른 consumer인 atlas claim ledger는 group mapping을 전달하지 않으므로 기존 global behavior를 유지할 수 있습니다.

이 수정은 semantic correctness와 performance를 동시에 개선합니다. 또한 다음 regression이 필수입니다.

1. 두 site가 다른 static Wave에 있고 같은 sign으로 active여도 Dynamic Co-Wave에서 partner가 되지 않아야 합니다.
2. 서로 다른 Wave의 co-activity가 same-group site transition type 또는 partner count를 바꾸지 않아야 합니다.
3. 한 static Wave만 있는 fixture에서는 group-aware engine과 기존 intended output이 동일해야 합니다.
4. summary에 `candidate_pair_count`, `evaluated_within_wave_pair_count`, `cross_wave_pair_excluded_count` 또는 동등한 performance/provenance field를 남겨야 합니다.

### 5. null distribution 및 permutation test 부재

**판정: 실제 미구현이며 논문에서 “random보다 의미 있다”는 주장을 하기 전에 반영해야 합니다. 다만 당장 production Report의 blocking bug는 아닙니다.**

현재 LOTO는 timepoint 하나를 제외했을 때 transition ID가 얼마나 유지되는지 측정합니다. 즉 stability/reproducibility proxy에는 유효하지만, 관찰된 transition resolution 또는 co-active pair structure가 random time ordering보다 큰지의 null test는 아닙니다. Dynamic module과 truth-free evaluator 모두 permutation을 구현하지 않았습니다.

권장 null은 단순 label rename이 아니라 **shared time-index permutation**입니다. static Wave membership을 고정한 뒤 모든 trajectory의 time-index를 같은 permutation으로 재배열해 contemporaneous cross-site structure와 per-site value distribution은 보존하고 adjacency ordering만 깨뜨립니다. 각 permutation에서 dynamic metric을 다시 계산해 empirical null을 만들고, global metric과 Wave-level metric의 empirical p-value 및 multi-Wave FDR를 별도 artifact로 저장합니다. site/pair event 각각을 독립 hypothesis로 무차별 FDR 처리하면 pseudo-replication 위험이 있으므로, 주 분석 단위는 Wave 또는 pre-registered global metric이어야 합니다.

## Roadmap 항목의 반영 판단

### 확률적 계층: GP/HMM posterior와 replicate-aware latent curve

**판정: 미구현은 맞지만, 현재 상태에서 바로 구현하면 안 됩니다.**

현재 production sidecar의 non-PTM protein layer는 `condition_level_only` median이며, replicate values are not persisted 상태를 명시합니다. Dynamic Co-Wave 자체도 site-level condition trajectory만 읽습니다. 이 상태에서 95% CI 또는 `P(active|data)`를 표시하면 진짜 replicate uncertainty가 아닌 모델 가정의 confidence가 될 위험이 있습니다.

먼저 preprocessing contract가 timepoint별 replicate values, missingness, normalization variance를 reproducibly persist해야 합니다. 이후 충분한 timepoint 수와 replication이 있는 dataset에서 hierarchical/empirical-Bayes uncertainty model을 parallel v2로 검증해야 합니다. 5–6 timepoint에서 high-parameter HMM/GP를 바로 production default로 채택하는 것은 overfitting 위험이 있어 권고하지 않습니다.

### Inhibitor M1–M4와 held-out protein evaluation

**판정: 현재 미구현은 맞지만, inhibitor outcome이 없는 insulin-only dataset에서 구현·성능 주장할 수는 없습니다.**

이것은 production Dynamic Co-Wave bug가 아니라 prospective perturbation benchmark입니다. inhibitor experiment가 확보되면 inhibitor identity/result를 분석 rule selection에 사용하지 않고, data split·feature set·threshold·primary metric을 사전 동결해야 합니다. split은 protein-level GroupKFold 또는 held-out protein scheme을 사용해 같은 protein의 여러 phosphosite가 train/test에 함께 들어가는 leakage를 막아야 합니다.

M3의 유용성을 주장하려면 M1 individual FC, M2 FC+static Wave, M3 M2+Dynamic Co-Wave, M4 M3+motif/pLM의 held-out performance와 calibration을 비교해야 합니다. 현재는 이 framework를 준비할 수는 있어도 모델의 우월성을 주장할 근거는 없습니다.

### pLM + curated evidence secondary attribution

**판정: 부분 미구현이 맞으며 P2가 적절합니다.**

TMM temporal compatibility와 curated lookup은 존재하지만 pLM probability를 secondary prior로 결합하는 calibrated scoring formula는 현재 없습니다. pLM은 candidate expansion/secondary ranking에 유용할 수 있으나, temporal evidence를 덮어쓰거나 benchmark truth를 유출해서는 안 됩니다. perturbation benchmark로 temporal-only baseline을 먼저 고정한 뒤, pLM을 optional secondary feature로 ablation 평가하는 순서가 적절합니다.

## 권고 구현 순서

| 순서 | 작업 | production output 영향 | 적용 후 필수 검증 |
|---:|---|---|---|
| 1 | default threshold를 canonical 0.40으로 정렬 | no-config direct-call 결과만 의도적으로 정렬 | config hash, explicit 0.40 output 불변 regression |
| 2 | inert `state_unchanged_or_inactive`를 event list에서 제외하고 exposure counter 분리 | site event count, site LOTO, Report dynamic site count 변화 | event meaning, LOTO, summary, Report packet regression |
| 3 | Dynamic wrapper가 same-static-Wave pair만 계산하도록 group-aware engine 사용 | cross-Wave-contaminated site event 정정, runtime 감소 | cross-Wave isolation 및 single-Wave equivalence regression |
| 4 | per-Wave size·candidate pair·runtime profiling artifact | numerical algorithm은 불변 | 실제 production-like artifact의 resource baseline |
| 5 | shared time-index permutation evaluator + Wave-level FDR | benchmark/statistical appendix 추가 | truth-free artifact, reproducible seed, null calibration |
| 6 | replicate persistence → uncertainty v2 → inhibitor M1–M4 | 별도 versioned research track | prospective frozen protocol 및 held-out evaluation |

## 지금 하지 말아야 하는 변경

Dynamic event만 보고 TMM kinase score를 재가중하거나 kinase switching을 선언하면 안 됩니다. endpoint rule을 validation 없이 maximum/mean rule로 바꾸면 안 됩니다. Report worker가 sidecar가 없을 때 Dynamic Co-Wave를 독립 재계산하면 안 됩니다. 또한 null test, pLM, inhibitor evaluation을 production LLM prompt에 곧바로 넣어 causality confidence를 부여해서는 안 됩니다.

현재 user-facing Report issue는 별도로 `7174d1b`에서 해결한 readiness preflight가 담당합니다. sidecar가 missing인 Report-only rerun은 canonical heatmap/TMM/sidecar preparation을 먼저 dispatch해야 하며, packet `status=available` 및 `record_count>0`가 확인된 뒤에만 Dynamic/TMM/cross-layer prose uptake를 평가해야 합니다.
