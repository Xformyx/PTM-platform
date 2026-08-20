# Core A/B P−2 통합 동결 계약 v1

작성일: 2026-08-20
상태: **지연(deferred).** 2026-08-20 범위 결정으로 이 문서는 kinase 계층 조건부 확장 명세가 되었다.

> **상위 문서: `docs/ptm_representation_learning_contract_v1.md` §12.**
>
> 논문 기여 주장 수준은 **표현 학습 자체**로 확정되었고, 어휘·arm·gate 체계는 representation 계약
> (L1~L4 / A~E / R0~R4 / 6-gate)을 기준으로 통일되었다. 이 문서의 독자적 어휘(A0~A4, F00~F11,
> P−2/Stage 0·1)는 **더 이상 명명의 출처가 아니다.**
>
> 편입 결과:
> - A1, A2 → representation 계약의 기존 구현·정책에 흡수 (신규 작업 없음)
> - A3 (`O_ij`) → `missingness_validity` gate 병목의 후보 기제로 재배치 (§12.3)
> - A4 → arm D 내부 아키텍처 선택지로 편입
> - feature universe 4분할, `O_ij` footprint, Kish `n_eff` → 데이터셋 특성화 자료로 재사용 (§12.4)
> - Core B(KSA scorer, 5-gate), `Δ_representation`, IA-07 → **조건부 확장으로 강등.** 6/6 gate 통과 후 재개
>
> 그 결과 BLOCKER-A, B, D, E, F가 **임계 경로에서 빠졌다.** BLOCKER-C만 축소된 형태로 유효하다.
> 이 문서는 kinase 계층을 재개할 때의 설계 근거로 보존한다. **이 문서 단독으로 실행하지 말 것.**

**이하 원문 (편입 전 상태 보존).** 아래 BLOCKER 3건 미해결 기술은 kinase 계층 확장에만 적용된다.

이 문서는 2026-08-19 ~ 08-20 사이 8라운드에 걸쳐 왕복 검토된 Core A/B 설계 계약을 하나로 통합한 것이다. 개별 검토 문서에 흩어진 계약 조각을 모으고, 철회된 주장을 명시하며, 실행 가능한 작업과 차단된 작업을 분리한다.

관련 문서: `docs/tmm_identifiability_diagnosis.md`, `docs/research_notes/public_astral_timecourse_dataset_search.md`, `docs/temporal_wave_contract_v1.md`

---

## 0. 실측 근거값

계약의 모든 수치는 아래 실측에서 나왔다. **데이터셋 로컬 값이며 다른 데이터셋에 복사하면 안 된다.**

### 0.1 HIRc-B feature universe (`Insulin_Signaling_Phosphoproteomics_HIRc-B`)

| universe | feature 수 | 기준 | 허용 용도 |
|---|---:|---|---|
| U-confirmatory | **2,420** | paired control replicate ≥ 2 | A0–A4, 모든 arm, primary 분석 |
| U-low-baseline | 302 | paired control 정확히 1개 | sensitivity 전용, baseline reliability flag 필수 |
| U-denovo | 313 | paired control 0개 | 탐색적 stimulation-induced 층, primary claim 불가 |
| U-unpaired | — | protein 결측 | QC/탐색 전용 |

U-primary(≥1 control) = 2,420 + 302 = 2,722.

### 0.2 `O_ij` comparability footprint

| 기준 | non-comparable pair | 비율 | affected pair 수 |
|---|---|---:|---:|
| U-confirmatory, replicate ≥1, T_min=4 | | **2.51%** | 73,537 |
| U-confirmatory, replicate ≥2, T_min=4 | | **9.07%** | 265,500 |
| (참고) U-primary 기준 | | 4.47% / 14.62% | — |

**집중 구조:** 상위 1% feature(24개)가 non-comparable edge 종단의 39.5%(rep≥1). `corr(non-comparable degree, 관측 timepoint 수)` = −0.764(rep≥1) / −0.869(rep≥2). 상위 5% feature의 평균 관측 timepoint 4.12/6 vs 나머지 5.96/6.

→ **`O_ij`는 전역 그래프 변환이 아니라 소수 저관측 feature에 대한 targeted correctness guard다.**

### 0.3 reliable timepoint 분포와 A3 검정력

| reliable TP | replicate ≥1 | replicate ≥2 |
|---|---:|---:|
| ≤ 4 / 6 (low-observation) | 66 (2.73%) | 197 (8.14%) |
| 5 / 6 | 137 | 241 |
| 6 / 6 | 2,217 (91.6%) | 1,982 (81.9%) |

| | replicate ≥1 | replicate ≥2 |
|---|---:|---:|
| affected pair (raw) | 73,537 | 265,500 |
| cluster 수 (affected pair 보유 feature) | 2,420 | 2,420 |
| **Kish 실효 cluster 수 `n_eff`** | **125** | **432** |
| 설계효과 | 19.3× | 5.6× |

필요 표본(α=.05, power=.80, ψ=0.75): 불일치율 5% → 578, 10% → 289, 20% → 145.
→ **replicate ≥2 (`n_eff`=432)만 검정 가능. replicate ≥1 (`n_eff`=125)은 pair 단위로도 미달.**

### 0.4 Core A 계산 비용 (P0a risk 종결)

affinity/similarity 행렬 0.02초, 약 30MB, B=100 bootstrap graph 재구성 약 2초 (2,722 feature 규모). **P0a blocker 아님.**

### 0.5 TMM 식별가능성 진단 (6개 오더, 1,310 shared site)

| 항목 | 값 |
|---|---:|
| identifiable | 1.1% |
| weakly identifiable | 1.5% |
| non-identifiable | 51.2% |
| equal-weight fallback | 46.2% |
| structurally underdetermined | 94.4% |
| rank-one design | 54.4% |
| `relative_residual ≥ 0.999` | 54.5% |
| top-1이 자신의 ambiguity set 내부 | **89.0%** |
| top-1이 prior 유래 컬럼 | 92.5% |
| duplicate columns (오더별) | 61.5% ~ 100% |

오더 36: kinase 111개 → 서로 다른 컬럼 **9개**, 100개가 동일 컬럼 하나 공유. data-driven profile 확보 4/111, 문헌 prior 등록 7/111.

ambiguity-aware grouping 후: 개별 ratio 7,893개 → 그룹 몫 1,012개(−87.2%), 증거 부족 46.2%. 지원되는 705 site 중 identifiable 27.1% / weakly 42.8% / non-identifiable 30.1%.

0 대입 편향: 평가 가능한 316 site 중 top-1 뒤집힘 **10.1%**.

### 0.6 부호검정 기반 `N_floor` (데이터 독립)

`n = [z_{α/2}·√0.25 + z_β·√(p₁(1−p₁))]² / (p₁−0.5)²`, α=.05 양측, power=.80

| 요구 일관성 p₁ | 필요 표적 수 |
|---:|---:|
| 0.65 | 85 |
| 0.70 | 47 |
| 0.75 | 29 |
| **0.80** | **20** |
| 0.85 | 14 |

PXD014525의 distinct direct target 상한 약 20~25 → **일관성 78% 이상의 효과만 검출 가능.**

---

## 1. 철회된 주장 (재사용 금지)

검토 과정에서 폐기된 것들이다. 이전 문서를 다시 읽는 사람이 이를 유효한 주장으로 집어오는 것을 막기 위해 명시한다.

| 철회 대상 | 출처 | 철회 사유 |
|---|---|---|
| Core A residual(A1)의 headline 성능 향상 | 초기 개발계획 | 현 파이프라인이 이미 protein 정규화를 수행. 차이는 `mean` vs `median` 집계뿐이며 MAD 0.06 log2 |
| synthetic selective accuracy **94.98%** | 반합성 시뮬레이션 | 순환성(gate가 truth 생성에 관여). decision-schema/API 테스트용으로만 보존 |
| full F10/F11에서 같은 scorer를 고정한 B-Gate-Only 시뮬레이션 | 동일 | full factorial로는 무효. named `B_GATE_ONLY` harness로만 보존 |
| `O_ij`가 Core A의 headline novelty | 초기 명세 | footprint 2.51%, 24~48개 저관측 feature에 집중. correctness guard로 재배치 |
| "`O_ij`가 4.5%이므로 성능적으로 미미하다" | 재검토 1차 | 총량으로는 맞으나 불완전. 해당 feature 개별로는 결정적 |
| "`O=0` edge가 bridge에 집중되어 그래프를 바꿀 수 있다" | 재검토 응답 | HIRc-B에서 미지지. 저관측 주변부 node |
| Core A graph/bootstrap을 P0a risk로 둠 | 초기 로드맵 | 0.02s / 30MB / B=100≈2s 실측으로 종결 |
| P1′(KSA scan)을 P1-B 뒤에 직렬 배치 | V3 로드맵 | Core A에 의존하지 않음. P0 직후 병렬 |
| `a_{I,k,w} = max_j a_{I,kj,w}` | 본 측의 제안 | **오류.** identifiability margin은 높을수록 안전하므로 max는 가장 쉬운 경쟁자를 골라 낙관 편향. `min_j`가 정답 |
| `gate_evaluability = REDUCED_GATE_SET_T1` | 본 측의 제안 | **오류.** 명세 §15.1의 `ρ`는 기질 축 cosine이며 시간 축이 아님. T=1에서도 정의됨. `SINGLE_CONTRAST_SITE_SPACE_GATE_SET_V1`로 대체 |
| `N_floor`를 `N_upper`와 동시 서명·해시 | 본 측의 제안 | 불충분. `N_upper`를 본 뒤 생성되면 여전히 조정 가능. Stage 0 사전 확정 필요 |
| `N_floor`를 blind conversion pilot 이후 동결 | target floor V1 | 위와 동일 사유로 V2에서 Stage 0 사전 확정으로 이동 |
| long repository copy / 장기 분기 브랜치 | 초기 로드맵 | in-repository feature flag + 독립 모듈 + 짧은 통합 변경 |

---

## 2. 확정된 계약

### 2.1 Arm 정의

| Arm | universe | representation | scorer | gate |
|---|---|---|---|---|
| `F00-product` | 전체 production universe | production feature view | production TMM | production |
| `F00-confirmatory` | U-confirmatory | production feature view | production TMM | — |
| `F00′-adapter` | U-confirmatory | production feature view | `A4_TO_TMM_WAVE_V1`, K=1, p≡1 | — |
| `F10-A4` | U-confirmatory | A4 | `A4_TO_TMM_WAVE_V1`, p only | off |
| `F01-noGate` | U-confirmatory | `RAW_TIME_BASIS_V1` | Core B KSA, m=1 | **off** |
| `F01-B` | U-confirmatory | `RAW_TIME_BASIS_V1` | Core B KSA, m=1 | five-gate on |
| `F11-noGate` | U-confirmatory | A4 | Core B KSA, 실제 m | **off** |
| `F11-full` | U-confirmatory | A4 | Core B KSA, 실제 m | five-gate on |
| `B-P` / `B-E` / `B-O` / `B-M` | U-confirmatory | A4 고정 | Core B nested `m` 변이 | F11과 동일 |

`B-E`: `m_i = e_i` (A2-only). `B-M`: `m_iw = e_i(1−u_i)p_iw` (full).

**모든 출력에 필수 필드:** `representation_mode`, `adapter_version`, `feature_universe`, `score_weight_formula`, `basis_mode`, `KSA_manifest_hash`, `gate_config_hash`, `adapter_type`, `dataset_id`.

### 2.2 대비(contrast) 분해

```
Δ_universe       = F00-confirmatory − F00-product
Δ_adapter        = F00′-adapter     − F00-confirmatory
Δ_representation = F10-A4           − F00′-adapter        ← Core A representation 효과
Δ_scorer         = F01-noGate       − F00-confirmatory    ← scorer 아키텍처 효과 (주: §5.3 제약)
Δ_gate,identity  = F01-B            − F01-noGate          ← 5-gate 순효과
Δ_gate,A4        = F11-full         − F11-noGate
Δ_A4,KSA         = F11-noGate       − F01-noGate
```

`Δ_adapter`가 크면 F10의 이득을 A4에 귀속할 수 없다. **어떤 arm도 미선언 fallback을 공유하지 않는다.**

### 2.3 Adapter 정의

```text
A4_TO_TMM_WAVE_V1
  input                 = r_i(t), p_iw, u_i, H_w(t), wave index w
  score-feature weight  = p_iw only
  제외                  = eligibility/outlier/mapping weight (e, u, m), q_map, Core B KSA direction
  materialized input    = pseudo-feature (feature_i, wave_w)
  pseudo time series    = r_i(t)
  pseudo feature weight = p_iw          # Σ_w p_iw = 1 → feature 총 weight 보존
  output                = TMM score(k, wave_w)
  주의                  = production TMM 은 외부 feature weight 인자를 받지 않으므로
                          실제 구현체는 "TMM-Wave Adapter scorer"(신규 코드)가 된다.
                          따라서 F00′-adapter arm 이 필수다.
```

```text
RAW_TIME_BASIS_V1
  mode        = 고정 canonical time basis
  H_raw       = I_6  (treatment timepoint; control 은 baseline centering 전용)
  wave/index  = learned wave 가 아니라 treatment time basis index
  b_{i,t}     = 관측 raw ratio/residual 응답 r_{i,t}
  p_iw        = absent / not applicable   # 모든 w 에 1 을 넣지 않는다 (simplex 위반 방지)
  m_i         = 정확히 1, identity_weight = true
  e, u, 엔트로피 = 계산하지 않음 (hidden Core A feature 금지)
  output      = kinase × fixed treatment-timepoint score → 사전등록 temporal summary
  IA-05 검사  = p 가 absent, m=1, raw time basis 가 config hash 에 기록되는지
  등가성      = signed·confidence-weighted KSEA 와 동형 (문헌 대비 위치 확보용으로 활용)
```

### 2.4 kinase × wave collapse

| 출력 수준 | 규칙 |
|---|---|
| primary temporal output | `Z_{k,w}` (kinase×wave 표준화 점수) 보존 |
| scalar ranking | `T_k = max_w |Z_{k,w}|` |
| multiplicity 보정 | null replicate마다 `max_w |Z^null_{k,w}|` → max-over-wave empirical p/q |
| 방향 주석 | `w* = argmax_w |Z_{k,w}|`의 sign과 wave prototype |
| K=1 (`F00′-adapter`) | 동일 공식이 self-reducing |
| **cross-arm 비교** | **maxT-calibrated empirical p/q 에서만.** raw `T_k`는 arm 내부 ranking 전용 (K에 따라 팽창) |
| 방향성 | `tier2_truth_directionality`를 P−2 config로 사전 확정. 방향성 있으면 ranking 통계량도 부호 포함 |

사후에 `max`/`sum`을 고르는 유연성은 제거된다.

### 2.5 Feature universe 및 baseline reliability

§0.1의 4분할을 사용한다. U-low-baseline은 폐기하지 않고 아래를 저장한다.

```text
control_paired_replicates
baseline_estimator
baseline_uncertainty_proxy
feature_universe_tier
eligible_for_confirmatory_score = false
```

`q_base`(baseline 품질 가중)는 V1에 도입하지 않는다. 교정 전 은닉 계수를 넣지 않는다.

### 2.6 Ortholog projection record

| 단계 | 필수 기록 | 실패 시 |
|---|---|---|
| rat peptide/site localization | accession, 잔기, 좌표, localization 상태 | 직접 점수 제외 |
| **kinase orthology** | source kinase accession, rat kinase accession, tier(`1:1` / `1:many` / `absent`) | absent → 제외, 1:many → family/group tier 전용 |
| substrate 1:1 ortholog | source/version, target accession | 모호 → 별도 tier |
| sequence alignment | alignment checksum/version | 정렬 없음 → 제외 |
| 잔기 대응 | rat S/T/Y가 동일 target S/T/Y로 사상 | 불일치 → 제외 |
| local flank | 사전 지정 window(±7), indel 상태 | 실패 → `projected_low_confidence` |
| edge inheritance | source edge, direction, evidence tier, projection tier | direct와 projected를 headline coverage에서 합산 금지 |

tier 라벨: `rat_direct` / `site_conserved_1to1` / `site_conserved_1tomany` / `predicted` / `exclude`.

---

## 3. 평가 endpoint 위계

### 3.1 selective endpoint (coverage-matched)

가장 반복적으로 문제가 된 지점이다. gate가 켜진 arm과 꺼진 arm의 정확도를 그냥 비교하면 gate는 항상 이긴다(쉬운 사례만 답하므로). 따라서:

```text
primary   = AURC  (area under risk-coverage curve, 전 coverage 적분)
secondary = coverage-matched selective accuracy
            사전 지정 coverage grid c ∈ {0.2, 0.4, 0.6, 0.8}
            no-gate arm 은 pre-gate ordering scalar 상위 c 분위로 절단
tertiary  = 자연 동작점 (gate 자체 coverage) — 보고만, 판정 불가
금지      = gate-on 자연 coverage vs no-gate 전체 coverage 직접 비교
```

AURC가 primary인 이유: gate 임계값 튜닝으로 특정 coverage 지점을 유리하게 만드는 것을 막는다. 단 **AURC는 연속 pre-gate risk ordering을 요구하며, 이것이 §3.3의 문제로 이어진다.**

### 3.2 primary/secondary endpoint 분리

```text
primary_endpoint   = Tier-2 kinase attribution accuracy (AURC, coverage-matched)
                     대상: F01-B, F11-full, F01-noGate, F11-noGate
                     데이터: PXD014525 (§5.3)
secondary_endpoint = Core A representation 효과 (Δ_representation)
                     대상: F10-A4 vs F00′-adapter vs F00-confirmatory
                     데이터: HIRc-B (mechanics) + PXD043599 (temporal generalization)
not_measurable     = A4 → Tier-2 transmission (Δ_A4,KSA 의 truth 기반 검증)
                     사유: 시간축 다점 + kinase 교란이 동시에 있는 데이터 부재
```

**A4 transmission이 측정 불가라는 사실은 계약의 결론이며 결함이 아니다.** 이를 measurable로 되돌리려면 §6-D의 자체 교란 실험이 필요하다.

### 3.3 pre-gate ordering scalar `M_order`

AURC와 coverage-matched 절단은 no-gate arm에도 연속 risk 점수를 요구한다. gate margin을 재사용하되 구조적 제약이 있다.

```text
M_kw = w_z·ã_z + w_N·ã_N + w_C·ã_C + w_I·ã_I
  ã_x        = 사전 지정 monotone 정규화 (rank 또는 robust z), null 분포로 교정
  ã_I        = min_j ã_{I,kj,w}          # min. max 아님 (§1 철회 항목)
  w_*        = P−2 에서 동결, config hash 에 포함
제외: a_R  (candidate-model mismatch margin)
  사유: R_w 는 wave 잔차 기반으로 k 에 의존하지 않음 → 후보 순서를 바꿀 수 없다.
        모든 후보에 동일 상수가 더해지므로 ordering 에 정보가 없다.
        gate 판정에는 계속 사용하되 M_order 에서는 구조적으로 제외한다.
```

**Ordering saturation 위험 (실측 근거 §0.5):** duplicate KSA column이 61.5~100%이면 `ρ`가 1에 붙고 `Δ`가 0에 붙어 `ã_I`가 상수화된다. 오더 36에서는 kinase 111개가 실질 컬럼 9개로 붕괴했다. 이 경우 `M_order`는 `ã_z, ã_N, ã_C`만으로 결정되고 AURC는 identifiability 정보를 잃는다.

```text
IA-06 (필수 진단, Stage 1 이전 실행)
  측정: KSA library 의 duplicate/near-duplicate column 비율,
        ã_I 의 분포 (unique 값 수, 분산, tie 비율)
  판정: tie 비율 > 0.5 또는 분산 ≈ 0 이면
        → M_order 를 ordering-degenerate 로 선언
        → AURC 를 primary 에서 내리고 coverage-matched selective accuracy 를 primary 로 승격
        → 이 승격 규칙은 Stage 1 결과를 보기 전에 확정한다
```

### 3.4 Go/No-Go 판정 규칙

```text
Core A 채택 조건 (secondary endpoint)
  Δ_representation 의 부트스트랩 CI 하한 > 0
  AND Δ_adapter 가 Δ_representation 과 같은 방향으로 우세하지 않음
  AND PXD043599 에서 방향 일치
  실패 시 → A4 는 primary representation 이 되지 못하고 선택적 view 로 강등

Core B gate 채택 조건 (primary endpoint)
  Δ_gate,identity 의 AURC CI 하한 > 0 (또는 §3.3 승격 시 coverage-matched)
  AND N_evaluable ≥ N_floor
  실패 시 → five-gate 는 기본 off, 진단 출력으로만 유지

A3 (O_ij) 채택 조건
  primary   = pair 수준 false-merge rate, feature-clustered bootstrap
  stratum   = replicate ≥ 2 (n_eff = 432) 만 사용
  금지      = replicate ≥ 1 stratum 으로 판정 (n_eff = 125, 미달)
  전역 지표 변화로 판정하지 않는다 (2.51% footprint 는 전역 지표에 묻힌다)
```

---

## 4. Gate 계약

### 4.1 다점 시계열 데이터셋 (HIRc-B, PXD043599)

five-gate 전체 평가 가능: `z`(효과크기), `N_eff`(증거량), `C`(coverage/일관성), `I_kj`(식별가능성), `R_w`(candidate-model 정합).

### 4.2 단일 대비 데이터셋 (PXD014525)

```text
SINGLE_CONTRAST_SITE_SPACE_GATE_SET_V1
  evaluable   = z, N_eff, C, I_kj{ρ, Δ}, R_w
  근거        = 명세 §15.1 의 ρ 는 기질 축 cosine,
                Δ 는 replicate bootstrap 분리도,
                R_w 는 site-vector 잔차 → 모두 T=1 에서 정의됨
  degenerate  = wave 다중성 (w 축이 단일), A4 temporal prototype,
                temporal consistency 해석, cross-timepoint C 성분
  결과        = gate 구조는 유지되나 "temporal" 해석은 불가.
                단일 대비 site-space 판정으로 재명명하여 보고한다.
```

이 항목은 본 측의 초기 오류(`REDUCED_GATE_SET_T1`)를 사용자 지적에 따라 수정한 것이다. 명세를 재확인한 결과 사용자 판단이 옳았다.

### 4.3 wave 축 축약

PXD014525에서 `w` 축이 단일이므로 §2.4의 `T_k = max_w |Z_{k,w}|`가 자동으로 `|Z_k|`로 축약된다. maxT null 교정은 그대로 수행하되 max-over-wave 항이 자명해지므로, cross-dataset 비교 시 이 데이터셋의 maxT 교정 통계량을 다점 데이터셋과 직접 병합하지 않는다.

---

## 5. 데이터셋 계약 (Route 1: 분할 검증)

정량 matrix를 보유한 내부 데이터셋 **20개** 전수 조사 결과 **kinase 표적 교란(inhibitor/siRNA/KO) 샘플이 존재하는 데이터셋은 0개**였다(재감사 v2. 초판의 "19개"는 오류. 사전 지정 교란 정의와 데이터셋별 판정은 `integrated_research_design_v2.md` §11.1). 따라서 primary endpoint를 내부 데이터로 검증할 수 없고, 역할을 데이터셋별로 분할한다.

| 데이터셋 | 역할 | endpoint | 상태 |
|---|---|---|---|
| HIRc-B (내부) | Core A mechanics, A0–A4, A3 ablation, arm 전체 | secondary | **사용 가능** |
| PXD043599 | 인간 insulin 시간축 일반화 | secondary | 접근 확인 필요 |
| PXD014525 | Core B scorer/gate 외부 검증 | **primary** | 접근 실사 필요 |
| — | A4 → Tier-2 transmission | (측정 불가) | §6-D |

### 5.1 HIRc-B

rat, 6 timepoint, paired control 존재. §0의 모든 실측이 이 데이터셋 기준이다. Core A 내부 기전과 A3 ablation의 유일한 근거.

### 5.2 PXD043599 (인간 primary myotube insulin time-course)

Core A의 시간축 결론이 rat HIRc-B 국소 특성이 아님을 보이는 외부 재현. **matched protein 정량이 없을 가능성이 높으므로** `partial/unpaired-protein adapter`가 필요할 수 있다. 이 경우 U-confirmatory 분할이 성립하지 않으므로 다음을 사전 확정한다.

```text
PXD043599_universe_fallback
  matched protein 있음  → U-confirmatory 동일 규칙 적용
  matched protein 없음  → UNNORMALIZED_PHOSPHO_ADAPTER_V1 적용,
                          결론을 "방향 일치" 수준으로 제한 (효과크기 비교 금지)
  판정 시점              = Stage 0, 실제 데이터 확인 후 즉시 기록
```

### 5.3 PXD014525 (인간 EGF-자극 RPE1, kinase inhibitor 30종)

primary endpoint의 유일한 근거. 아래 제약을 계약에 명시한다.

```text
UNNORMALIZED_PHOSPHO_ADAPTER_V1
  input        = raw phospho log2FC (inhibitor vs vehicle)
  protein 정규화 = 없음 (matched proteome 부재)
  결과         = Core A residual(A1) 정의가 성립하지 않음
                 → 이 데이터셋에서 A4 representation arm 은 실행하지 않는다
  허용 arm     = F01-noGate, F01-B (RAW_TIME_BASIS_V1, T=1)
  주의         = Δ_scorer 는 이 데이터셋에서 F00-confirmatory 상대로 계산할 수 없다
                 (universe 정의가 다름). scorer 효과는 HIRc-B 에서만 대비한다.
```

**단일시점 성질:** 10분 EGF endpoint 단일 대비다. 따라서 이 데이터셋으로 검증되는 것은 *"Core B KSA scorer와 5-gate가 단일 대비 site-space에서 알려진 kinase 억제 효과를 올바른 방향·순위로 회수하는가"* 뿐이다. temporal wave 귀속 정확도는 검증 대상이 아니다.

**Stage 0 사전 확정 항목 (`N_upper`를 보기 전에 서명·해시):**

```text
tier2_truth_directionality     = signed | unsigned      # 사전 확정
tier2_target_definition        = direct substrate only | direct + 1-hop
tier2_evaluable_criteria       = KSA edge 존재 AND site 정량 존재 AND N_eff ≥ 임계
N_floor                        = 20    # p₁ = 0.80, 부호검정, §0.6
                                       # Stage 1 결과 열람 전 확정 (V2 수정사항)
promotion_rule_if_degenerate   = §3.3 IA-06
```

`N_evaluable < N_floor`이면 primary endpoint는 **inconclusive**로 보고하고 Core B gate 채택 주장을 하지 않는다. 사후에 floor를 낮추지 않는다.

### 5.4 사전 조사 이력과의 정합

`docs/research_notes/public_astral_timecourse_dataset_search.md`에 이미 동일한 결론(공개 데이터만으로는 primary 검증 불가 → 자체 데이터 primary + 공개 데이터 secondary 분할)이 기록되어 있다. Route 1은 이 결론과 일치하며, 새로운 발견이 아니라 재확인이다.

---

## 6. BLOCKER

sign-off를 막고 있는 항목이다. A는 신규 발견이며 가장 상류에 있다.

### BLOCKER-A. KSA library 부재 (신규, 최상류)

플랫폼에 **curated kinase-substrate edge table이 없다.** 코드 전수 검색 결과 kinase 추론은 KEA3 **API 호출**에 의존하며, 로컬 KSA edge table은 존재하지 않는다.

이것이 막는 것:

| 의존 항목 | 이유 |
|---|---|
| Core B KSA scorer 전체 | `p_iw`, `ρ`, `Δ` 계산에 edge table 필요 |
| `I_kj` gate | KSA profile 간 유사도 필요 |
| §3.3 IA-06 진단 | duplicate column 비율 측정 대상이 곧 KSA library |
| §5.3 `tier2_evaluable_criteria` | "KSA edge 존재" 판정 불가 |
| §2.6 ortholog projection | edge inheritance의 source edge 부재 |
| `N_upper` 산출 | evaluable target 수를 셀 수 없음 |

```text
stage_0_prerequisite = KSA_LIBRARY_ACQUISITION
  필요 산출물: kinase × substrate-site edge table
              + evidence tier (low-throughput / high-throughput / predicted)
              + source/version + manifest hash (KSA_manifest_hash 필드용)
  후보:       PhosphoSitePlus (라이선스 확인 필요), OmniPath, Signor, KEA3 백엔드 덤프
  차단 해제 전 실행 불가: Stage 1 전체, P1′ 진단, primary endpoint
```

**KEA3 API로 대체 불가:** enrichment 결과만 반환하며 site 수준 edge와 evidence tier를 주지 않는다. `ρ`/`Δ`는 edge 수준 profile을 요구한다.

### BLOCKER-B. PXD014525 접근성 및 evaluable target 수

`N_upper`(distinct direct target 수) 실측 필요. 약 20~25로 추정되며 `N_floor`=20에 매우 근접하다. 여유가 거의 없어 evaluable 기준을 조금만 엄격히 잡아도 inconclusive가 된다. 실사 항목:

- 원자료(site table) 다운로드 가능 여부 및 재처리 필요성
- inhibitor 30종 중 **표적이 KSA library에 존재하는** kinase 수 (→ BLOCKER-A 의존)
- vehicle 대비 replicate 수 (`Δ` bootstrap 성립 여부)
- site 정량 결측률

### BLOCKER-C. PXD043599 protein 정량 유무

§5.2의 fallback 분기 결정. Stage 0에서 확인. 미확인 상태로 Core A 외부 재현을 설계하면 universe 정의가 사후 결정된다.

### BLOCKER-D. A4 transmission 측정 불가 (구조적)

해제 방법은 하나뿐이다: **다점 시계열 + kinase 교란을 동시에 갖는 자체 실험.** 최소 설계는 시간축 4점 이상 × 억제제 2종 이상 × replicate 3. 이 실험이 없으면 "Core A representation이 kinase 귀속 정확도를 개선한다"는 주장은 P−2 범위에서 불가능하며, 계약은 secondary endpoint까지만 지지한다.

---

## 7. 실행 계획

### 7.1 지금 실행 가능 (blocker 무관)

**P−1: `F00-product` 회귀 동결.** 유일하게 즉시 착수 가능한 구현 작업이다.

```text
목적: 현 production 파이프라인의 출력을 고정 baseline 으로 동결
산출: F00-product 재현 스냅샷 (입력 해시 → 출력 해시)
      + 회귀 테스트 (동일 입력 → 동일 출력)
      + §2.1 필수 필드 스키마 추가 (representation_mode, feature_universe 등)
이유: 이후 모든 Δ 대비의 분모. blocker 와 독립.
      또한 §2.1 필드가 없으면 arm 구분 자체가 기록되지 않는다.
```

부수적으로 가능한 것: §0.1 feature universe 분류기 구현(HIRc-B 실측 재현), §2.6 ortholog projection record 스키마 정의, `RAW_TIME_BASIS_V1` adapter 골격(KSA 불필요한 부분까지).

### 7.2 BLOCKER-A 해제 후

P1′ KSA scan(§3.3 IA-06 포함) → `A4_TO_TMM_WAVE_V1` adapter → `F00′-adapter` arm → Core B scorer.

P1′는 Core A에 의존하지 않으므로 P0 직후 병렬 실행한다(§1 철회 항목).

### 7.3 BLOCKER-B/C 해제 후

Stage 0 사전 확정 서명 → Stage 1 실행 → primary endpoint 판정.

### 7.4 순서 요약

```
[즉시]      P−1 F00-product 회귀 동결 + 스키마 필드
[병렬 조사]  KSA library 확보 (BLOCKER-A)  ← 최우선
            PXD014525 실사 (BLOCKER-B)
            PXD043599 protein 정량 확인 (BLOCKER-C)
[해제 후]   P1′ KSA scan + IA-06 → adapter → arm 구축
[Stage 0]   사전 확정 항목 서명·해시 (N_floor 포함)
[Stage 1]   실행 및 판정
[별도 결정] 자체 교란 실험 (BLOCKER-D) — 수행 여부는 경영 판단
```

---

## 8. Sign-off 상태

| 항목 | 상태 |
|---|---|
| Arm 정의 및 대비 분해 (§2.1–2.2) | 합의 |
| Adapter 정의 (§2.3) | 합의 |
| kinase × wave collapse (§2.4) | 합의 |
| Feature universe (§2.5) | 합의, 실측 근거 확보 |
| Ortholog record (§2.6) | 합의 |
| selective endpoint (§3.1) | 합의 |
| endpoint 위계 (§3.2) | 합의, A4 transmission 측정 불가 인정 |
| `M_order` (§3.3) | 합의, `min_j` 및 `a_R` 제외 반영. IA-06 승격 규칙 포함 |
| Go/No-Go (§3.4) | 합의, A3 stratum 제약 반영 |
| Gate 계약 (§4) | 합의, 단일대비 site-space 해석으로 수정 |
| 데이터셋 분할 (§5) | 합의, 접근성 미확인 |
| `N_floor` = 20 | 합의, Stage 0 사전 확정 |
| **BLOCKER-A ~ D** | **미해결** |

**결론: 설계 계약은 동결 가능한 수준에 도달했다. 그러나 BLOCKER-A(KSA library)가 Stage 1 전체의 상류에 있어 실행 착수는 불가하다. 즉시 가능한 작업은 §7.1의 P−1뿐이다.**

> **v1.1 수정:** 2026-08-20 코드 실사에서 BLOCKER-E, BLOCKER-F가 추가로 확인되었다. §9 참조. §2.1, §2.2, §3.4, §6, §7이 영향을 받는다.

---

## 9. v1.1 수정 계약 — 설계행렬 및 LLM 오염

### 9.1 BLOCKER-E: prior가 설계행렬 자체를 구성한다

#### 9.1.1 기전 (실측 확인)

production kinase scoring은 NNLS이며 설계행렬 `H`의 각 열이 kinase 하나의 시간 프로파일이다. 열의 출처는 두 가지뿐이다.

```965:966:api-server/app/services/temporal_kinase_scoring.py
MIN_EXCLUSIVE_FOR_PROFILE = 3   # minimum exclusive substrates to build a data-driven profile
_GAUSSIAN_SIGMA_LOG = 0.6       # log-space sigma for Gaussian fallback profile
```

- `data_driven`: exclusive substrate(`len(ptm_to_kinases[pk]) <= 1`)가 3개 이상일 때, 그 |시계열|의 median을 max 정규화
- `gaussian_fallback`: 그렇지 않으면 문헌 `typical_peak_min` 중앙값(없으면 generic 30.0분)에 중심을 둔 Gaussian

**핵심 문제는 fallback 열이 `peak_min` 단 하나의 스칼라의 결정적 함수라는 점이다.** `peak_min`이 취하는 distinct 값은 문헌 표의 소수 midpoint와 30.0뿐이다. 따라서:

```
peak_min 공유  →  수치적으로 동일한 열  →  duplicate column
```

이것이 §0.5 진단 수치의 단일 원인이다.

| 관측 (§0.5) | 이 기전으로의 설명 |
|---|---|
| duplicate columns 61.5~100% | 대부분 kinase가 fallback이고 `peak_min`이 겹침 |
| 오더 36: kinase 111개 → distinct 열 **9개** | data-driven 4개 + 소수 distinct `peak_min` |
| rank-one design 54.4% | 열이 사실상 1개로 붕괴 |
| non-identifiable 51.2% | rank 부족의 직접 귀결 |
| `ρ`→1, `Δ`→0 (`ã_I` 포화, IA-06) | 동일 열이므로 profile cosine이 1 |
| top-1이 자기 ambiguity set 내부 89.0% | 동일 열끼리 구분 불가 |

즉 IA-06의 ordering saturation은 독립 현상이 아니라 **BLOCKER-E의 증상**이다.

#### 9.1.2 왜 이것이 `Δ_representation`을 무력화하는가

`F00′-adapter`와 `F10-A4`는 응답벡터만 다르고 **설계행렬 `H`는 동일하다.** NNLS는 응답을 `col(H)`로 투영한다. 따라서

```
A4 표현이 만든 응답 변화 중 col(H) 에 직교하는 성분은 전부 소멸한다.
rank(H) ≈ 1 이면 두 arm 의 차이는 site 별 스칼라 하나로 축약된다.
⇒ Δ_representation 에는 표본 수와 무관한 구조적 상한이 존재한다.
```

**이는 검정력 문제가 아니라 식별 문제다.** 표본을 늘려도, PXD043599를 추가해도 해결되지 않는다. 기존 §2.2의 3분할 대비(`Δ_universe`/`Δ_adapter`/`Δ_representation`)로도 걸러지지 않는다. 세 대비 전부가 동일한 저rank 기저 위에서 계산되기 때문이다.

#### 9.1.3 BLOCKER-A와의 역방향 결합 (중요)

직관과 반대 방향의 상호작용이 있다. KSA library를 확보하면(BLOCKER-A 해제) site 하나가 사상되는 kinase 수가 **늘어난다.** 그러면 exclusivity 조건 `len(ptm_to_kinases[pk]) <= 1`을 만족하는 substrate가 **줄어든다.**

```
가설: BLOCKER-A 해제  →  exclusive substrate 감소  →  data_driven yield 하락
                      →  gaussian_fallback 비중 증가  →  BLOCKER-E 악화
```

**단, 이 방향은 보장되지 않는다.** 새 library가 기존 site에 edge를 추가하면 위와 같이 되지만, kinase 하나만 갖는 **새 site**를 다수 추가하면 exclusivity가 오히려 증가할 수 있다. 실제 방향과 크기는 library filtering, evidence tier, site mapping, candidate restriction 정책에 따라 달라진다.

```text
KSA_MANIFEST_CHANGE_AUDIT_V1
  발동  = KSA manifest 를 변경할 때마다 (신규 확보, 버전 갱신, tier 정책 변경)
  측정  = pre/post 로 exclusive-substrate yield, fallback fraction,
          rank(H), duplicate-column rate, τ
  판정  = 악화는 가능한 가설이며 empirical audit 으로만 확정한다
```

따라서 계약상 요구는 "A 해제가 E를 악화시키므로 동시 설계"가 아니라 **"A 해제 시 E 지표를 반드시 재측정한다"**이다. 현재 로드맵(§7.4)은 A를 최우선 단독 과제로 두어 이 재측정 의무를 반영하지 못한다.

#### 9.1.4 해결책 E-1: IA-07 설계행렬 전달성 감사 (선행, blocker 무관)

arm을 구축하기 **전에** `Δ_representation`이 원리적으로 측정 가능한지부터 판정한다. 기존 코드와 HIRc-B만으로 계산 가능하다. 설계행렬 빌더는 이미 진단과 공유되도록 작성되어 있다.

```1092:1097:api-server/app/services/temporal_kinase_scoring.py
    """Assemble the NNLS design matrix: one temporal profile column per candidate.

    Kinases without a registered profile fall back to a Gaussian centred on the
    literature peak time, or on a generic 30-minute peak when even that is
    unknown.  Shared by the deconvolution and by its identifiability diagnostics
    so the two can never describe different matrices.
    """
```

```text
IA-07  DESIGN_TRANSMISSIBILITY_AUDIT_V1
  대상        = HIRc-B, U-confirmatory
  측정 1      = distinct column 수, numerical rank(H), condition number,
                data_driven yield, peak_min 의 distinct 값 수
  측정 2      = 핵심 지표 transmissible_fraction
                  d_i      = (A4 응답벡터) − (raw 응답벡터)          # site i
                  P_H      = col(H) 로의 정사영 연산자
                  τ        = median_i ( ||P_H d_i||² / ||d_i||² )
                  해석: 현재 scorer geometry 에서 A4-induced perturbation 중
                        보존되는 energy fraction.
                  주의: τ 는 Δ_representation 의 정량적 상한이 아니다.
                        NNLS 는 직교 투영이 아니라 볼록 cone 투영이고,
                        그 뒤에 비음수 제약·feature weight·후보 부분집합·
                        정규화가 개입한다. τ 가 보장하는 것은 필요조건뿐이다:
                          τ → 0  ⇒ 효과 없음 (col(H) 직교 성분은 KKT 상
                                   H'y 를 통해서만 작용하므로 계수를 못 바꾼다)
                          τ 높음 ⇒ 효과를 보장하지 않는다
                  성격: development decision threshold.
                        effect-size significance threshold 가 아니다.
  측정 3      = τ 를 data_driven 전용 부분행렬 H_dd 로 재계산 → τ_dd
                (prior 열을 제거하면 전달성이 회복되는지)
  사전 확정 임계 = τ_min = 0.20      # Stage 0 에서 동결, 결과 열람 전
```

τ는 부트스트랩 CI와 함께 보고한다. **τ 임계값은 IA-07 실행 전에 동결한다.** τ를 본 뒤 임계를 정하면 §1에서 반복 지적된 사후 조정 문제가 재발한다.

#### 9.1.5 해결책 E-2: τ 결과에 따른 사전 분기

IA-07 결과별 대응을 미리 확정해 사후 선택 여지를 없앤다.

```text
분기 1  τ ≥ τ_min  (설계행렬이 표현 변화를 전달함)
  → 기존 arm 구조 유지
  → 단, prior 기여를 분리하기 위해 F00″-priorfree arm 추가 (E-3)
  → Δ_representation 을 secondary endpoint 로 유지

분기 2  τ < τ_min  이지만 τ_dd ≥ τ_min  (prior 열이 원인)
  → PRIOR_FREE_DESIGN_V1 을 평가 arm 의 기본 설계로 채택 (E-3)
  → 평가 대상 kinase 를 data_driven 프로파일 보유 kinase 로 한정
  → data_driven yield 가 §9.1.3 때문에 부족하면 E-4 를 적용

분기 3  τ < τ_min 이고 τ_dd < τ_min  (설계행렬로 회복 불가)
  → Δ_representation 을 endpoint 에서 제거하고 not_measurable 로 이동
     (§3.2 의 A4 transmission 과 동일 처리)
  → Core A 주장을 representation 수준 내재 지표로 한정한다:
       wave recovery 정확도, residual 구조, O_ij false-merge (A3),
       feature universe 별 안정성, PXD043599 방향 일치
     이들은 kinase scorer 를 경유하지 않으므로 BLOCKER-A/E 와 무관하게 검증된다.
  → Core A 는 "kinase 귀속을 개선한다"가 아니라
     "시간 표현을 개선한다"로 주장 범위를 축소한다.
```

**분기 3이 되어도 Core A 검증 자체는 가능하다.** 잃는 것은 kinase 귀속으로의 전달 주장이며, 이는 이미 §3.2에서 A4 transmission을 not_measurable로 인정한 것과 동일한 성질의 축소다.

#### 9.1.6 해결책 E-3: prior를 은닉 인자에서 측정 축으로 승격

```text
PRIOR_FREE_DESIGN_V1
  설계행렬    = data_driven 프로파일 보유 kinase 열만 사용
  제외 kinase = gaussian_fallback 열 → 점수화하지 않고
                prior_only 로 별도 출력 (report 에는 남기되 primary 지표 제외)
  필수 기록   = kinase 별 profile_type, peak_min, peak_min_source,
                design_column_hash, rank(H), distinct_column_count
  금지        = 평가 arm 에서 fallback 열을 무선언 혼입

신규 arm  F00″-priorfree
  = F00-confirmatory 와 동일하되 PRIOR_FREE_DESIGN_V1 적용
  Δ_prior = F00-confirmatory − F00″-priorfree
```

**`Δ_prior`는 단일인자 대비가 아니다.** fallback kinase를 점수화에서 제외하면 후보가 줄어들고 coverage가 함께 변한다. 따라서 `Δ_prior`는 prior 열 효과와 **candidate availability / coverage loss**를 섞는다. §2.2에서 세운 단일인자 원칙에 대한 예외이므로 아래를 함께 보고하지 않으면 해석할 수 없다.

```text
priorfree_candidate_loss = 점수화에서 제외된 kinase 수와 identity
priorfree_target_loss    = 잃은 KSA edge mass / site coverage / truth-target coverage
priorfree_H_change       = column 수, rank, condition number, duplicate group
```

허용되는 해석은 "prior 열의 순기여"가 아니라 **"prior-free 설계 + eligibility 변화의 합산 효과"**다.

`design_column_hash`를 남기면 duplicate 열을 사후에 재검출할 수 있고, IA-06/IA-07을 재실행 없이 감사할 수 있다. `MIN_EXCLUSIVE_FOR_PROFILE`과 `_GAUSSIAN_SIGMA_LOG`는 **config hash에 포함**한다. 현재는 모듈 상수라 변경이 기록되지 않는다.

#### 9.1.7 해결책 E-4: data_driven yield 확보 (분기 2에서 필요 시)

§9.1.3 때문에 exclusivity 기반 프로파일 추정은 KSA library 확보 후 오히려 악화된다. 대안은 exclusivity를 포기하고 프로파일을 공동 추정하는 것이다.

```text
JOINT_PROFILE_ESTIMATION_V1  (알고리즘 변경, Core A 기여로 편입)
  현재  = H 를 exclusive substrate median 또는 prior 로 고정 → 기여도만 NNLS
  변경  = H 와 기여도를 교대 최적화 (alternating NNLS / 부분지도 NMF)
          초기화: data_driven 열만 사용, prior 는 초기화에도 쓰지 않음
          제약:   비음수, 열 max 정규화, KSA edge 없는 (k,i) 쌍은 기여 0 고정
  효과  = exclusive substrate 없이도 data 유래 열 확보 → rank 회복
  주의  = 이는 baseline 개선이 아니라 Core A 의 알고리즘 기여다.
          따라서 F00 계열이 아니라 별도 arm 으로 평가하고,
          Δ_jointprofile 을 독립 대비로 보고한다.
  사전등록 = 교대 반복 수, 수렴 판정, 초기화 seed 를 Stage 0 에서 동결
```

`MIN_EXCLUSIVE_FOR_PROFILE`을 3에서 낮추는 방식은 **채택하지 않는다.** 프로파일 신뢰도를 떨어뜨리면서 rank를 사는 교환이고, 임계값을 사후에 조정하는 형태가 되기 때문이다.

### 9.2 BLOCKER-F: LLM 예측 kinase가 후보집합에 유입된다

#### 9.2.1 경로 (실측 확인)

```
LLMKinasePredictor.predict()                     # RAG enrichment 단계
  → enrichment_pipeline.py:263 에서 호출
  → enriched_ptm_data 의 rag_enrichment.kinase_prediction.predicted_kinases 로 기록
  → kinase_annotation_node._collect_known_kinases_from_enriched() 가 Source 1 로 수집
  → known kinase 목록 → kinase_modules → candidate_kinases
  → NNLS 설계행렬의 열
```

```515:532:workers/report_generation/core/nodes/kinase_annotation_node.py
    # Source 1: kinase_prediction (LLM-based)
    kp = rag.get("kinase_prediction", {})
    if isinstance(kp, str):
        import ast
        try:
            kp = ast.literal_eval(kp) if kp.startswith("{") else {}
        except Exception:
            kp = {}
    if isinstance(kp, dict):
        for k in kp.get("predicted_kinases", []):
            if isinstance(k, dict) and k.get("kinase"):
                known.append({
                    "kinase": k["kinase"],
                    "confidence": k.get("confidence", ""),
                    "source": "rag_kinase_prediction",
                })
```

#### 9.2.2 왜 심각한가

두 가지가 겹친다.

**(1) 후보집합 오염.** NNLS는 열 간 독립이 아니다. LLM이 kinase 하나를 후보에 추가하면 그 kinase의 기여만 생기는 것이 아니라 **다른 모든 kinase의 기여 추정이 바뀐다.** §9.1의 저rank 상황에서는 특히 그렇다. 동일 `peak_min`을 갖는 열이 하나 추가되면 그 ambiguity set 전체의 몫이 재분배된다.

**(2) Tier-2 독립성 위협.** PXD014525의 ground truth는 "억제제 → 표적 kinase" 문헌 지식이다. LLM은 그 문헌을 학습했고 PubMed abstract를 입력으로 받는다. 즉 정답을 아는 경로가 후보집합에 연결되어 있다.

**주장 범위 주의.** "현재 결과가 오염되었다"는 확정 진술은 **측정 없이 할 수 없다.** 계약과 논문 방법 섹션에서 허용되는 진술은 다음까지다.

> **잠재적 누출 경로(potential leakage path)가 존재하며, blind confirmatory evaluation에서는 허용될 수 없다.**

오염의 실제 크기를 주장하려면 `Δ_llm`(§9.2.4) 측정이 필요하다. 그 전까지는 경로의 존재만 근거로 삼는다.

**완화 요인:** 플랫폼은 이미 이 소스를 최저 신뢰 등급으로 분류하고 있다.

```1085:1089:workers/report_generation/core/nodes/kinase_annotation_node.py
_LOW_CONFIDENCE_SOURCES = {
    "rag_kinase_prediction",   # LLM-based prediction
    "string_db",               # STRING PPI interaction
    "string_db_e3",            # STRING PPI E3
}
```

등급은 있으나 **후보집합 진입 자체를 막지는 않는다.** 등급은 보고용 주석이고, 설계행렬 구성에는 반영되지 않는다. 다만 `source` 태그가 이미 전 경로에 붙어 있으므로 **차단 구현 비용은 낮다.**

#### 9.2.3 해결책 F-1: 증거 출처 화이트리스트

```text
EVIDENCE_SOURCE_WHITELIST_V1
  적용 지점 = candidate_kinases / kinase_modules 구성 시점 (설계행렬 이전)
  허용      = kinase_substrate_pair, iPTMnet, KEA3(집계 아닌 edge 근거 시),
              KSA library edge (BLOCKER-A 산출물)
  차단      = rag_kinase_prediction        # LLM
              string_db                    # PPI 근접성, 기질 근거 아님
              abstract_analysis / fulltext_analysis 계열  # 텍스트 마이닝
  구현      = source 태그 기반 필터. 태그는 이미 존재하므로 신규 수집 불필요.
  기록      = evidence_source_policy, 차단된 kinase 목록과 건수,
              policy_hash → config hash 에 포함
  강제      = 평가 arm 은 policy_hash 불일치 시 실행 거부 (fail-closed)
```

텍스트 마이닝 계열(`_MEDIUM_CONFIDENCE_SOURCES`)도 차단 대상에 포함한다. PubMed abstract에서 추출한 kinase-substrate 관계는 Tier-2 ground truth와 동일한 문헌 풀에서 나오므로 LLM과 같은 오염 성질을 갖는다. 이 판단은 Tier-2 endpoint 한정이며, production 보고서에서는 계속 사용한다.

#### 9.2.4 해결책 F-2: `Δ_llm`을 단일인자 대비로 분리

LLM kinase를 제거하면 후보집합이 바뀌고 NNLS 결과가 바뀐다. 이를 `Δ_universe`에 섞으면 §2.2에서 세운 단일인자 원칙이 깨진다. 따라서 arm을 하나 삽입한다.

```text
신규 arm  F00-noLLM
  = F00-product 와 동일하되 EVIDENCE_SOURCE_WHITELIST_V1 적용

수정된 대비 사슬 (§2.2 대체)
  Δ_llm            = F00-noLLM         − F00-product          # 증거출처 정책 효과
  Δ_universe       = F00-confirmatory  − F00-noLLM            # feature universe 효과
  Δ_prior          = F00″-priorfree    − F00-confirmatory     # prior 열 효과 (§9.1.6)
  Δ_adapter        = F00′-adapter      − F00″-priorfree       # scorer 아키텍처 효과
  Δ_representation = F10-A4            − F00′-adapter         # Core A 표현 효과
```

`F00-product`는 production 현행 동작의 동결 스냅샷이므로 LLM을 포함한 상태를 유지한다(§7.1). 정책 적용 경계는 `F00-noLLM`이다.

#### 9.2.5 해결책 F-3: 오염 잔여 경로 점검

whitelist 적용 후에도 아래 경로로 문헌 지식이 재유입될 수 있다. Stage 0에서 각각 확인하고 기록한다.

| 잔여 경로 | 점검 항목 | 대응 |
|---|---|---|
| `SIGNALING_CASCADES`, `BASOPHILIC_KINASES` 등 하드코딩 prior | 문헌 유래 `typical_peak_min` | E-3의 `PRIOR_FREE_DESIGN_V1`이 동시 해결 |
| KEA3 API | 내부적으로 문헌 집계 사용 | edge 근거 없이 enrichment 순위만 주는 호출은 차단 |
| RAG collection (PubMed 전문) | writer/hypothesis 노드가 kinase 명시 | 서술 생성 전용, 점수 경로 차단 확인 |
| `KinaseValidator`, `kinase_weight_manager` | 문헌 기반 가중 존재 여부 | 미확인. Stage 0 실사 필요 |

마지막 항목은 아직 읽지 않았으므로 **미확인 상태로 기록한다.** whitelist를 구현하기 전에 `workers/common/kinase_weight_manager.py`의 가중 산출 근거를 확인해야 한다.

### 9.3 수정된 실행 순서 (§7.4 대체)

```
[즉시, blocker 무관]
  P−1   F00-product 회귀 동결 + §2.1 provenance 필드
  IA-07 설계행렬 전달성 감사 (τ, τ_dd)        ← 최우선. arm 설계의 전제
  E-3   design_column_hash / profile_type / peak_min_source 기록 추가
        MIN_EXCLUSIVE_FOR_PROFILE, _GAUSSIAN_SIGMA_LOG 을 config hash 로 이동
  F-1   EVIDENCE_SOURCE_WHITELIST_V1 구현 (source 태그 이미 존재)
  F-3   kinase_weight_manager 문헌 가중 실사

[Stage 0 사전 확정]
  τ_min = 0.20, N_floor = 20, policy_hash, tier2_* 항목 서명·해시

[병렬 조사]
  BLOCKER-A  KSA library 확보  ← E-4 설계와 동시 진행 (§9.1.3 결합)
  BLOCKER-B  PXD014525 실사
  BLOCKER-C  PXD043599 protein 정량 확인

[IA-07 결과에 따라]
  분기 1/2  → arm 구축 (F00-noLLM, F00″-priorfree, F00′-adapter, F10-A4)
  분기 3    → Δ_representation 제거, Core A 내재 지표로 축소

[Stage 1]  실행 및 판정
```

**IA-07이 P−1과 함께 최우선이 된 것이 v1.1의 핵심 변경이다.** τ를 모르는 상태로 adapter나 arm을 구현하면, 측정 불가능한 대비를 위한 코드를 쓰게 될 수 있다.

### 9.4 v1.1 sign-off 상태

| 항목 | 상태 |
|---|---|
| BLOCKER-E 기전 규명 | 완료, 코드·진단 수치로 확인 |
| BLOCKER-E 해결책 E-1~E-4 | 설계 완료, IA-07 실행 대기 |
| BLOCKER-F 경로 규명 | 완료 |
| BLOCKER-F 해결책 F-1~F-2 | 설계 완료, 즉시 구현 가능 |
| F-3 잔여 경로 | **미완.** `kinase_weight_manager` 실사 필요 |
| §2.2 대비 사슬 | v1.1에서 5단계로 확장 (§9.2.4) |
| τ_min = 0.20 | 제안값. Stage 0 서명 전 검토 필요. 운영 판정값임을 §9.1.4에 명시 |

---

## 10. 외부 검토 반영 (2026-08-20)

출처: `~/Downloads/Core A_B P−2 Frozen Contract v1 및 LLM 오염 진단_ 통합 검토 의견.md` (Manus AI)

이 검토는 **범위 결정 이전 상태**를 대상으로 작성되었다. 따라서 "P−2 v1.2가 sign-off의 필요조건"이라는 결론은 이 문서가 지연된 뒤에는 **kinase 계층 재개 시점의 조건**으로 읽어야 한다. 검토 내용은 범위 결정을 반박하지 않고, 오히려 kinase 경로의 선행 비용을 독립적으로 올려 지연 결정을 뒷받침한다.

### 10.1 즉시 수정한 오류 (반영 완료)

| 오류 | 위치 | 수정 |
|---|---|---|
| τ를 `Δ_representation`의 상한으로 기술 | §9.1.4 | energy fraction 및 필요조건으로 재기술. 운영 판정값 성격 명시 |
| `Δ_prior`를 단일인자 대비로 기술 | §9.1.6 | coverage-loss confound 명시 + 3개 진단 필수화 |
| BLOCKER-A → E 악화를 단정 | §9.1.3 | 가설로 격하 + `KSA_MANIFEST_CHANGE_AUDIT_V1` 재측정 의무 |
| LLM 오염을 사실로 단정 | §9.2.2 | 잠재적 누출 경로 존재까지로 주장 범위 축소 |

### 10.2 재개 시 필수 재작업 (미반영, 설계 재작업 필요)

**아래 항목은 kinase 계층을 재개할 때 착수 전에 처리해야 한다. 현재 문서 본문은 이 재작업이 반영되지 않은 상태다.**

#### (1) F-1이 불충분하다 — candidate universe를 독립 구성해야 한다

§9.2.3의 `EVIDENCE_SOURCE_WHITELIST_V1`은 **증거 출처**로 필터링한다. 그런데 LLM이 kinase X를 제안하고 X가 마침 curated KSA edge를 가지면, "edge 증거 허용" 규칙에 의해 후보집합에 진입한다. 즉 화이트리스트는 LLM의 증거 출처는 막지만 **LLM의 선택 영향은 막지 못한다.**

오염된 목록을 필터링하는 것과 목록을 독립적으로 구성하는 것은 다르다. F-1은 후자여야 한다.

```text
CONFIRMATORY_CANDIDATE_UNIVERSE_V1  (F-1 대체)
  population          = frozen KSA-manifest kinase, 사전 선언된 organism/site mapping 적격성
  candidate inclusion = KSA edge support + 사전 선언된 실험적 검출/증거 규칙만
  prohibited inputs   = RAG/LLM prediction, PubMed/abstract/fulltext ranking,
                        report narrative, inhibitor name/target label,
                        Tier-2 outcome label, post-hoc 수동 추가
  구성 방식           = input phosphosite/KSA matrix 에서 label-blind 하게 생성
  provenance          = kinase별·edge별 source ID, candidate_universe_hash
  enforcement         = 금지 소스가 scorer input 에 도달하면 fail-closed
  production scope    = production 보고서 변경 없음. confirmation arm 전용
  LLM 허용 범위       = post-hoc narrative hypothesis 전용. scorer input 과 strict one-way separation
```

#### (2) IA-07 명세 누락 6건

| 항목 | 필요 보완 | 이유 |
|---|---|---|
| zero denominator | `‖d_i‖²`가 매우 작은 feature의 제외/epsilon 규칙 | 수치 불안정 및 trivial perturbation 방지 |
| weighting | projector와 `d_i` norm에 적용할 고정 feature weight | U-confirmatory·reliability·mapping 정책과 일치 필요 |
| rank tolerance | SVD tolerance 및 condition-number 임계 | **numerical rank는 tolerance 없이는 정의되지 않는다** |
| aggregation | median 외 IQR, weighted mean, low-observation stratum | **소수 feature 집중을 숨기지 않기 위해.** §0.2에서 그 집중을 직접 관측했으므로 median 단독은 자기모순 |
| uncertainty | feature-clustered bootstrap + 고정 resampling seed | timepoint/feature 의존성 반영 |
| H identity | candidate universe·KSA hash·profile rule·peak table hash·column hash | 감사가 실제 scoring `H`와 동일함을 보장 |

#### (3) E-4를 별도 R&D arm으로 격리

§9.1.7의 `JOINT_PROFILE_ESTIMATION_V1`을 **E-2 분기 2의 자동 remedy로 두지 않는다.** `H`와 기여도를 동시 추정하면 scale/rotation/local optimum ambiguity가 생긴다(NMF 비유일성). initialization, regularization, held-out validation, stability selection, 독립 식별가능성 분석을 **별도 계약으로 동결**한 뒤에만 착수한다. 즉 go/no-go 후속 연구 arm이다.

#### (4) F-3을 sign-off blocker로 승격

§9.2.5의 잔여 경로 실사를 backlog가 아니라 **blocker**로 둔다. 대상: `KinaseInferenceWeightManager`, `KinaseValidator`, `get_kinase_strategy_weights`, KEA3 호출 모드, 모든 downstream candidate augmentation 모듈. 산출물은 서술이 아니라 **코드 경로별로 "금지 소스 없음"을 증명하는 machine-readable provenance test**여야 한다.

#### (5) Tier-2 baseline의 candidate universe 통일

`F00-product`는 production 동작 스냅샷이며 **validation effect estimator가 아니다.** Tier-2 confirmatory 비교에서 `F01-noGate`와 `F01-B`는 **동일한 frozen LLM-free candidate universe**를 공유해야 한다. 그렇지 않으면 gate 효과와 candidate-set 효과가 다시 섞인다.

#### (6) 재개 전 4개 산출물 관문

검토가 제시한 관문을 그대로 채택한다. P1 arm/adapter는 아래 넷이 모두 존재하기 전에 착수하지 않는다.

```
1. exact-H IA-07 감사 결과 (실제 scoring H 와 동일함이 해시로 증명된 것)
2. frozen KSA manifest + matrix 감사
3. LLM-free candidate universe 정책 및 해시
4. 잔여 누출 감사 보고서 (machine-readable provenance test)
```

### 10.3 검토의 한계

검토자는 §3.4에서 `temporal_kinase_scoring.py` source tree에 접근할 수 없어 **line-level claim을 독립 확인하지 못했다**고 명시했다. 따라서 BLOCKER-E 기전에 대한 동의는 추론 수준의 동의이며 독립 검증이 아니다. 코드 사실은 §9.1.1, §9.2.1의 직접 인용으로 확인된 것이고, 외부 검토가 이를 확증한 것으로 인용해서는 안 된다.

### 10.4 활성 트랙으로 전이된 지적

두 항목은 kinase 계층이 아니라 현재 진행 중인 representation 트랙에 적용된다. `docs/ptm_representation_learning_contract_v1.md`에서 처리한다.

- **임계값의 성격 명시.** `induced missingness R²` 상한 0.25, ARI 하한 0.2 등은 운영 판정 임계값이며 통계적 유의성 임계값이 아니다. 이 구분이 계약에 명시되어 있지 않다
- **aggregation 보고 규칙.** `missingness_validity` 진단에서 평균/중앙값만 보면 특정 universe나 저관측 층에 집중된 실패를 놓친다. §12.4 층화 진단을 보고 통계량 수준에서도 요구해야 한다
