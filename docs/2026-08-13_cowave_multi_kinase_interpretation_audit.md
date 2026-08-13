# Co-Wave 다중 Kinase 해석: 최신 코드 감사

## 핵심 원칙

동일 timepoint에 함께 증가하거나 감소하는 substrate가 하나의 kinase에만 의해 조절된다고 가정하지 않는다. 현재 PTM-platform은 **substrate co-wave**, **kinase co-wave**, **candidate kinase attribution**, **TMM contribution**, **temporal cascade**, **autophosphorylation**, **directionality**를 서로 다른 evidence axis로 유지한다.

> 같은 timepoint의 co-wave는 “동일한 temporal program 또는 shared upstream context”의 후보이지, “동일 kinase가 모든 substrate를 직접 인산화했다”는 증거가 아니다.

## 두 종류의 Co-Wave

| 종류 | 현재 생성 위치 | 구성원 | 의미 |
|---|---|---|---|
| **Canonical substrate Wave** | `ptm_shared.temporal_wave_engine` → `temporal_comovement_node` | signed temporal correlation이 높은 PTM site | 함께 움직이는 substrate/PTM temporal program |
| **Kinase co-wave group** | `orders.py` kinase activity heatmap | kinase activity score trajectory가 상관된 kinase들 | 같은 시간축에서 함께 활성화되는 kinase module 집단 |

두 결과는 연결되지만 동일한 객체가 아니다. 첫 번째는 site 중심이고, 두 번째는 kinase-module 중심이다.

## 현재 처리 흐름

```text
Observed PTM time-series
  → Canonical substrate Wave (positive signed temporal coherence)
  → PTM별 motif / curated annotation / candidate kinase set
  → 동일 Wave 내 confirmed anchor와 broad-motif candidate score
  → kinase modules와 raw temporal activity profiles
  → TMM NNLS shared-substrate contribution ratios
  → TMM-weighted kinase score / peak / activation state
  → timepoint별 active kinase set과 adjacent-time transition
  → autophosphorylation / directionality / ChromaDB를 이용한 interpretation
```

## 같은 Wave에서 여러 Kinase를 어떻게 다루는가

### 1. 후보를 먼저 보존한다

motif family가 넓으면 `disambiguate_basophilic_kinase()`는 단일 kinase를 반환하지 않고 candidate list를 유지한다. candidate score에는 PTM peak minute, 동일 Wave의 confirmed anchor kinase, treatment context가 반영된다. 따라서 AKT/SGK/S6K/RSK처럼 motif가 중첩되는 family를 초기 단계에서 하나로 붕괴시키지 않는다.

`get_wave_dominant_kinases()`도 이름과 달리 복수 `dominant_kinases`를 반환한다. confirmed anchor가 있으면 최대 다섯 개 anchor를 보존하고, anchor가 없으면 temporal tier에 맞는 최대 세 개 prior candidate를 반환한다. 후자는 반드시 prior-assisted evidence로 해석해야 한다.

### 2. 같은 Wave 안의 direct/indirect/shared substrate를 TMM으로 분리한다

TMM은 각 kinase의 exclusive substrate median profile을 `p_k(t)`로 만들고, shared PTM의 observed profile `y_s(t)`를 후보 profile의 non-negative mixture로 분해한다.

```text
y_s(t) = Σ a_s,k · p_k(t) + ε
r_s,k = a_s,k / Σ a_s,j
```

같은 Wave에서 AKT와 S6K가 모두 active여도 shared substrate는 예를 들어 AKT 0.65, S6K 0.25, RSK 0.10처럼 분해된다. contribution ratio는 kinase별 weighted up/down sum 및 fractional substrate count에 반영되므로, site가 모든 kinase module에 동일하게 중복 집계되지 않는다.

### 3. 같은 timepoint에 공존하는 kinase를 경쟁이 아니라 병렬 branch로 보존한다

heatmap의 `cowave_groups`는 kinase score trajectory의 correlation이 0.7 이상인 kinase를 함께 묶는다. group은 복수 kinase의 목록과 dominant peak를 보존하며, 한 group을 대표하는 단일 kinase를 선택하지 않는다.

따라서 같은 timepoint에서 여러 kinase가 보이면 가능한 해석은 다음 중 하나다.

| 관찰 | 적절한 해석 |
|---|---|
| 서로 다른 substrate set, 같은 peak | 병렬 signaling branch 또는 common upstream regulator 후보 |
| 높은 substrate overlap, self-PTM은 한 kinase만 존재 | self-PTM evidence가 있는 kinase가 더 직접적인 candidate일 수 있음 |
| shared substrate가 많고 TMM fraction이 분산 | 실제 다중 input 또는 profile identifiability 부족; single winner 보류 |
| 같은 kinase가 early/late sub-pattern을 가짐 | kinase의 여러 substrate program, compartment shift, secondary activation 후보 |
| 같은 group이나 direction이 반대 | co-wave로 묶이면 안 되며 canonical signed correlation에서 분리되어야 함 |

## 여러 시간대 정보는 어떻게 결합되는가

### Temporal cascade

`kinase_annotation_node.py`는 각 substrate cluster의 peak timepoint에서 cluster site와 겹치는 **모든** kinase module을 `active_kinases`로 기록한다. adjacent timepoint에는 `persistent_kinases`, `new_kinases`, `lost_kinases`를 기록한다. 이는 “A가 B를 유발했다”는 cascade가 아니라, time-ordered **module membership transition**이다.

### Temporal pattern

각 kinase module은 sustained activation, early-only, late-onset, transient spike, progressive amplification/decay, direction reversal 같은 profile pattern을 별도로 가진다. 따라서 동일 Wave가 한 timepoint에서 만났더라도, 전체 time-course에서 persistent인지, early transient인지, late emerging인지를 비교한다.

### Autophosphorylation

high substrate overlap kinase들이 있을 때 self-PTM timing은 추가적인 activity marker다. 현재 heatmap은 substrate gene overlap이 80% 이상인 kinase group에서 self-PTM을 가진 kinase가 있으면 self-PTM 없는 중복 candidate를 UI에서 `hidden_by_self_ptm`으로 표시할 수 있다. 이는 확정 assignment가 아니라 ambiguity를 줄이는 보조 evidence다.

### Directionality

DirectedTemporalRelationship은 PTM–protein abundance 또는 PTM–effector record에서 onset/peak lag, lag-aware similarity, bootstrap, time permutation을 평가한다. D-tier는 Wave 또는 kinase 동시 활성화를 causal edge로 바꾸지 않는다. D2/D3만 분석 종료 뒤 validation experiment 제안의 후보가 된다.

## Data-Grounded Analysis가 사용하는 방식

가설 생성 node는 다음을 동시에 전달한다.

1. timepoint별 cascade flow와 new/lost kinase;
2. kinase co-wave group별 kinase 목록과 substrate 목록;
3. kinase self-PTM timing;
4. TMM exclusive/shared count, profile type, top contribution;
5. observational directionality record.

따라서 LLM은 같은 Wave의 여러 kinase를 한 kinase로 합치지 말고, co-activation, convergent signaling, common upstream regulation, sequential phosphorylation, shared-substrate ambiguity 중 데이터에 맞는 후보 해석을 작성해야 한다. D-tier와 `causality_status=not_tested`가 함께 제공되어 causal overclaim을 제한한다.

## 현재 확인된 한계

| 한계 | 현재 상태 | 영향 | 권장 보완 |
|---|---|---|---|
| `cowave_groups` 생성 순서 | API에서 raw kinase score trajectory로 group을 만든 뒤 TMM을 적용 | group membership/mean correlation은 TMM-weighted peak 변경을 반영하지 않을 수 있음 | TMM merge 뒤 co-wave group을 재계산하고 `raw`/`tmm_weighted` provenance를 함께 저장 |
| temporal cascade score | cluster–module overlap raw count로 active kinase를 기록 | shared substrate가 여러 kinase에 중복 반영될 수 있음 | TMM contribution-weighted active kinase count를 cascade에 추가 |
| fallback profile | exclusive substrate가 3개 미만이면 expected peak Gaussian 사용 | data-derived temporal conclusion처럼 보일 수 있음 | `gaussian_fallback`을 prior-assisted badge·낮은 confidence로 분리 |
| profile identifiability | candidate profile이 매우 유사하면 NNLS fraction이 불안정할 수 있음 | 다중 kinase fraction을 과도하게 해석할 위험 | residual, condition number, entropy, bootstrap contribution CI 추가 |
| directionality coverage | 현재 PTM–effector/timeline 중심 | 모든 kinase-to-kinase transition을 직접 directionality로 검증하지 않음 | future: TMM-weighted kinase profile pair에 DirectedTemporalRelationship 적용 |

## 사용자·보고서용 해석 원칙

```text
같은 Wave = 같은 timing program 또는 shared context 후보
같은 Wave ≠ 하나의 kinase가 모든 site를 직접 조절

TMM high fraction = 이 조건의 candidate profile과 높은 temporal compatibility
TMM high fraction ≠ universal true kinase assignment

earlier Wave = temporal precedence candidate
earlier Wave ≠ causal upstream regulator
```

보고서에는 각 timepoint에 대해 “co-active kinase set”, “TMM dominant contributions”, “persistent/new/lost modules”, “self-PTM support”, “directionality tier”를 나란히 보여 주어야 한다. 이 방식이 같은 시간대의 실제 다중 kinase biology를 보존하면서도, 여러 시간대의 순차적 구조를 해석하는 가장 적절한 현재 운영 방식이다.
