# §2.1 정렬 확인 — 인코더 출력 공간 vs NNLS 조건 공간

**대상:** `c1_prereg_v1.md` §2.1 (동결 전 필수 3건 중 1건)
**질문:** 인코더 재구성 출력의 열 공간이 NNLS의 순서화된 조건 공간과 정렬되는가.
**방법:** 코드 정독. 실행 없음.
**판정:** **조건부 통과.** 값의 종류는 같으나 **다섯 지점이 정렬되지 않으며 명시적 adapter가 필수다.**
미결 설계 결정 1건이 남는다.

---

## 1. 확인된 두 공간

### 1.1 인코더 (L3 → L4)

`ptm_shared/representation/feature_contract.py`, `encoder.py`

```text
행    site_keys = sorted(target_values)
열    timepoints = sorted(timepoint_set, key=(timepoint_to_minutes(label), label))
값    _TARGET_KEYS = ("PTM_Relative_Log2FC", "ptm_relative_log2fc", "log2fc")
      view 이름 = "track2_ptm_relative_log2fc", role = "primary_target"

재구성  reconstruction = output[:, 0:n_time]        # (n_sites, n_time)
        _rmse 가 reconstruction 을 targets[0] (= track2 타깃)과 비교
        → reconstruction 은 Track 2 궤적의 재구성이며 열 순서는 timepoints 와 같다
```

**따라서 `d_i = reconstruction_D[i] − reconstruction_L1[i]`는 `R^{n_time}`의 벡터로 잘 정의된다.**
τ가 필요로 하는 섭동 방향은 원칙적으로 구성 가능하다.

### 1.2 NNLS (배포 추정기)

`scripts/diagnose_tmm_identifiability.py`, `app.services.temporal_kinase_scoring`

```text
열(조건) conditions = heatmap["conditions"]              # 저장된 순서 그대로. 재정렬 없음
값       target = [series.get(condition, 0.0) for condition in conditions]
출처     ptm_vector_data_normalized{_phospho|_ubi}.tsv 의 PTM_Relative_Log2FC
site key f"{gene.upper()}_{position.upper()}"
모집단   shared_sites = 후보 kinase 가 2개 이상인 site 전체
```

### 1.3 핵심 긍정 결과

**두 경로가 같은 물리량을 쓴다 — `PTM_Relative_Log2FC`.** 이것이 정렬의 필수 전제였고 성립한다.
값 공간이 달랐다면 τ는 정의부터 불가능했다.

---

## 2. 정렬되지 않는 다섯 지점

### 2.1 site key 형식 — 구조적 불일치 (가장 심각)

```text
인코더 (key_level="form", 기본값)   f"{gene} {position}|{form}"
                                    예: "AKT1 S473|_AAS(ph)PQR_"
인코더 (key_level="site")           f"{gene} {position}"
                                    예: "AKT1 S473"          ← 공백, 대문자화 없음
NNLS                                f"{gene.upper()}_{position.upper()}"
                                    예: "AKT1_S473"          ← 밑줄, 대문자화
```

**어느 설정에서도 문자열이 일치하지 않는다.** 정규화 사상이 필수다.

**그리고 이것이 단순 문자열 문제가 아니다.** 기본값 `key_level="form"`에서 인코더는 **form 단위**로
행을 만들고 NNLS는 **site 단위**로 푼다. 한 site에 여러 form이 대응하므로 **다대일 관계이며 전단사가
아니다.**

```text
form 3개 → site 1개 인 경우
d_form1, d_form2, d_form3  →  NNLS site 하나의 y ∈ R^T
```

**집계 규칙이 필요하고 어디에도 정해져 있지 않다.** 이것이 미결 설계 결정이다(§4).

**부수 발견.** `scripts/run_representation_fair_probe.py`는 `key_level="site_form"`을 넘기는데,
`_merged_config`는 `"form"`이 아닌 모든 값을 `"site"`로 강제한다(line 107). 즉 이 스크립트는 **site
수준**으로 실행되고 production 표현 학습(`workers/preprocessing/core/ptm_representation_learning.py`
line 41)은 **form 수준**으로 실행된다. C0의 실측 결과가 어느 수준에서 산출되었는지 확인이 필요하다.

### 2.2 조건 집합 — 차원이 다를 수 있다

```text
인코더  condition.lower() == "control" 인 행을 건너뛴다  (feature_contract.py line 497)
NNLS    heatmap["conditions"] 를 그대로 쓴다
```

`heatmap["conditions"]`에 `control`이 포함되어 있으면 `n_time_encoder = T_NNLS − 1`이고 **두 공간의
차원이 다르다.** 데이터 확인 필요(§5).

### 2.3 열 순서 — 보장되지 않는다

인코더는 `timepoint_to_minutes`로 정렬하고, NNLS는 저장된 순서를 그대로 쓴다. 집합이 같아도 **순서가
다르면 `d`와 `A`의 행이 어긋난다.** 집합 동일성이 아니라 **수열 동일성**을 확인해야 한다.

### 2.4 결측 처리 — 비대칭

```text
NNLS    미관측 조건 → 0 으로 대입  (series.get(condition, 0.0))
인코더  미관측 → NaN, observed=False
        그러나 디코더는 모든 시점에 값을 낸다 → reconstruction 은 조밀(dense)
```

따라서 `d_i`는 **NNLS가 단단한 0을 본 자리에 비영(non-zero) 성분을 갖는다.** 치명적이지는 않으나
τ의 해석이 달라진다 — τ는 부분적으로 **대입 채움 방향의 전달성**을 재게 된다.

이것은 기존 실측과 직접 연결된다. 영값 대입은 평가 가능한 site의 **10.1%에서 top-1을 뒤집는다**
(`tmm_identifiability_diagnosis.md`). 즉 대입 채움 방향은 하류 출력을 실제로 바꾸는 방향이다.
**해석 한계로 사전등록에 명시해야 한다.**

### 2.5 site 모집단 — 서로 다른 집합

```text
인코더  observed_counts >= minimum_observed_timepoints (기본 3)  + 선택적 q 필터
NNLS    후보 kinase >= 2 인 shared site 전체.  관측 수 필터 없음
```

τ는 **교집합에서만** 계산 가능하다. 그리고 교집합은 두 집합보다 작다.

**`|S-EVAL|`에 직접 영향한다.** 특히 `T = 3`인 오더(33, 45)에서는 `minimum_observed_timepoints = 3`이
**완전 관측 site만 적격**이라는 뜻이므로 감쇠가 심하다. §3.2에서 추정한 `|S-EVAL|` 범위(0–597)는
이 교집합 감쇠를 **반영하지 않은 값**이므로 실제 상한은 더 낮다.

---

## 3. 판정

| 항목 | 결과 |
|---|---|
| 값의 종류 (`PTM_Relative_Log2FC`) | **일치** |
| `d`의 구성 가능성 | **가능** (`reconstruction` 차분) |
| site key 문자열 | 불일치 → 정규화 필요 |
| form ↔ site 대응 | **다대일. 집계 규칙 미정** ← 미결 |
| 조건 집합 차원 | `control` 포함 여부에 따라 불일치 가능 |
| 열 순서 | 보장 없음 → 수열 동일성 확인 필요 |
| 결측 처리 | 비대칭 → 해석 한계 명시 필요 |
| site 모집단 | 불일치 → 교집합으로 제한 |

**τ 정의는 불성립하지 않는다. 그러나 "그냥 계산하면 된다"도 아니다.** 명시적으로 선언된 adapter를
거쳐야 정의되며, adapter의 한 구성요소(form→site 집계)는 아직 결정되지 않았다.

**사전등록은 무효가 아니다.** §2.1의 최악 시나리오(값 공간 자체가 다름)는 발생하지 않았다.

**2026-08-22 갱신.** 다섯 지점 중 **세 지점이 실측으로 해소되었다** — A3(control 없음),
A4(수열 이미 일치), A1·A5(두 수준의 site 집합 동일). 남은 것은 2.4(결측 처리 비대칭)이며
이것은 해소되는 종류가 아니라 **해석 한계로 병기하는 항목**이다(§2.1.3). 상세는 §5·§6.

---

## 4. 미결 설계 결정 — form → site 집계

선택지와 각각의 성격을 적어 둔다. **결과를 보기 전에 하나로 확정해야 한다.**

| 방안 | 내용 | 문제 |
|---|---|---|
| (a) site 수준으로 인코더 재실행 | `key_level="site"`로 표현을 다시 학습 | C0 실측 결과와 다른 설정이 될 수 있다. 재학습 비용 |
| (b) form별 `d`를 평균 | 같은 site의 form들의 `d`를 산술평균 | form 수가 site별로 달라 가중이 불균등. 우세 form이 희석된다 |
| (c) 최다 관측 form 대표 | 관측 시점이 가장 많은 form 하나를 선택 | 결정적이고 단순. 정보 폐기 |
| (d) form 수준 τ를 계산하고 site로 집계 | τ를 form마다 계산한 뒤 요약 | `A`는 site 단위이므로 form마다 같은 `A`를 쓴다 → τ 차이는 전부 `d` 차이. 해석은 명확하나 독립성이 없다 |

**현 시점 권고는 (a)와 (c)의 조합이다.** C0 실측이 실제로 site 수준이었다면(§2.1 부수 발견) (a)는
재학습이 아니라 **설정 확인**으로 끝난다. 그렇지 않으면 (c)를 쓰고 폐기 정보량을 보고한다.

**이 결정은 `c2_prereg_v1.md` 작성과 무관하게 먼저 내려야 한다.** C1의 primary(E3)가 여기에 걸려 있다.

---

## 5. 남은 확인 (데이터 접근 필요) — **완료 2026-08-22**

`scripts/measure_c1_strata.py`, 오더 52(HIRc-B). 산출물
`data/outputs/_diagnostics/c1_strata_v1/measurement.json`.

```text
[x] heatmap["conditions"] 에 "control" 이 포함되는가
        → 없음. 조건은 ['1min','5min','15min','30min','60min','180min'] 6개.
          **A3 의 차원 불일치는 발생하지 않는다** (오더 52 기준)
[x] heatmap["conditions"] 의 순서가 timepoint_to_minutes 정렬과 같은가
        → 저장 순서 그대로 동일. 집합·수열 모두 일치. **A4 재배열 불필요**
[x] C0 실측 결과가 key_level="site" 인가 "form" 인가
        → **둘 다다.** ablation 은 form(2,819 → 적격 2,744), 공표 프로브 표는 site.
          문서의 "2,447 site" 는 `['Gene.Name','PTM_Position']` 그룹 수와 정확히 일치한다
[x] 인코더 적격 site 와 NNLS shared site 의 교집합 크기
        → §6
```

### 5.1 A1·A5 실측 — **집계 규칙이 모집단을 바꾸지 않는다**

| 수준 | 적격 행 | 정규화 후 고유 site | 다중 form site | ∩ NNLS 전계층 | ∩ S-EVAL |
|---|---:|---:|---:|---:|---:|
| form | 2,744 | **2,377** | 300 | 452 | **58** |
| site | 2,377 | **2,377** | 0 | 452 | **58** |

**두 수준의 고유 site 집합이 같다.** 즉 form 하나라도 적격이면 그 site 는 site 수준에서도
적격이고 그 역도 성립한다. 따라서 §4의 미결(form→site 집계)은 **모집단 크기 문제가 아니라
`d` 구성 방법 문제로 축소된다.** 영향 범위는 다중 form site 300개(2,377의 12.6%)다.

### 5.2 §4 미결의 해소 — **(a) site 수준을 택한다**

실측이 세 가지를 동시에 만족시켰으므로 (a)가 지배적이다.

```text
1  모집단 손실 없음        site 수준 고유 집합 = form 수준 고유 집합 = 2,377
2  집계 규칙 불필요        A1 정규화 후 NNLS site 와 전단사. §4 의 (b)(c)(d) 가 모두 불요
3  C0 와 불일치 아님       공표 프로브 표가 이미 site 수준(2,447)에서 측정되었다
```

(c)(최다 관측 form 대표)는 폐기한다 — 정보 폐기가 발생하는데 1에 의해 얻는 것이 없다.
**단 τ 산정에 쓰는 인코더는 site 수준으로 다시 적합해야 한다.** C2 작업(form 수준, 2,744)의
가중치를 재사용하지 않는다.

---

## 6. 계층 크기 실측 — **어느 사전등록 수준도 검정력에 미달한다**

`c1_prereg_v1.md` §3.1의 계층 정의를 그대로 적용했다. **τ는 계산하지 않았다** — 모집단 확정이
τ 열람보다 먼저여야 primary 자격이 유지되기 때문이다(§3.2가 요구한 순서).

### 6.1 L2 = HIRc-B 전체 (오더 52, shared site 500)

| 계층 | n | 비율 |
|---|---:|---:|
| S-DEAD | 50 | 10.00% |
| S-NOFIT | 4 | 0.80% |
| S-RANK1 | 383 | 76.60% |
| **S-EVAL** | **63** | **12.60%** |

adapter 교집합 후 **58**. L1(확증 universe)은 L2의 부분집합이므로 **58 이하**다.

### 6.2 L3 = 동결 6 오더 pool (1,160 site)

| 계층 | n | 비율 |
|---|---:|---:|
| S-DEAD | 537 | 46.29% |
| S-NOFIT | 102 | 8.79% |
| S-RANK1 | 429 | 36.98% |
| **S-EVAL** | **92** | **7.93%** |

adapter 교집합 후 **66**(감쇠 28%). 오더별 S-EVAL은 극단적으로 불균등하다.

| 오더 | S-EVAL / site | ∩ 인코더 |
|---|---:|---:|
| Korea_timecouse_drugrepositioning | 13 / 42 (31.0%) | 9 |
| Microgravity_Muscle_Atrophy | 8 / 24 (33.3%) | 6 |
| Irisin_TimeCourse_qwen3.5_27b | 15 / 52 (28.8%) | 5 |
| KRIBB_SCS_Phosphorylation | 53 / 907 (5.8%) | 43 |
| Cu-Amyloid_fibril-microglia | 3 / 49 (6.1%) | 3 |
| WithoutCu-AmyloidFibril-microglia | **0 / 86 (0.0%)** | 0 |

### 6.3 판정 — §3.4 기준 적용

```text
L1  ≤ 58   < 73   → E3 primary 평가 불가
L2  =  58   < 73   → E3 primary 평가 불가
L3  =  66   < 73   → E3 primary 평가 불가
```

**세 수준 전부 미달이다.** §3.4의 마지막 조항이 발동한다 — "L3에서도 미달이면 C1의 예측 진단
주장을 철회하거나 새 데이터를 요건으로 선언한다".

### 6.4 L2 ∪ L3 은 사전등록되지 않았다

합치면 58 + 66 = **124**로 두 번째 구간(73–194)에 들어간다. 그러나 §3.3은 확장 순서를
L1 → L2 → L3으로 고정했고 **합집합 수준을 정의하지 않았다.** 어느 수준도 통과하지 못한 것을
본 뒤에 합집합을 만드는 것은 §3.3이 막으려던 사후 모집단 선택 그 자체다.

따라서 합집합 수준의 지위는 **탐색적이며 primary 승격은 영구 불가**다. 이 사실을 기록해 둔다.
보고할 때 124를 검정력 근거로 제시하지 않는다.

> **HIRc-B가 L3에 없는 이유는 데이터가 아니라 시점이다.** 사전등록 당시 오더 52에는
> `kinase_activity_heatmap`이 없었고(그래서 「Insulin 오더 포함」이 Chapter 2의 미결 항목이었다)
> 2026-08-22 확인 시점에는 저장되어 있다(2.3 MB, 전 오더 최대). 즉 L3의 6 오더 구성은
> **데이터 가용성의 흔적**이다. 그렇다 해도 지금 7 오더 pool을 새 primary 수준으로 선언하는 것은
> 결과를 본 뒤의 변경이므로 하지 않는다.

---

## 7. A6 — 여섯 번째 불일치 (2026-08-22 추가) 와 그 해소

A1–A5 점검에서 **놓친 지점**이 있었다. `d = reconstruction − y` 의 크기에 직접 들어가므로
기록한다.

```text
NNLS     ptm_shared/tmm_audit.py load_timeseries 는 같은 (site, condition) 의 여러 form 행을
         순회하며 딕셔너리에 덮어쓴다 → **마지막 행 승리(last-wins)**
인코더   ptm_shared/representation/feature_contract.py 는 같은 (site, condition) 의 표본을
         **평균**한다 (np.mean)
```

두 경로가 같은 TSV 를 읽지만 **form 이 여럿인 site 에서 값이 갈릴 수 있다.** 보정하지 않기로
했다 — primary baseline 은 "NNLS 가 실제로 소비하는 값"이어야 하고(`c1_prereg_v1.md` §2.1.4),
인코더 입력으로 baseline 을 바꾸면 τ 가 배포 추정기를 기술하지 않게 된다. 대신 크기를 측정했다.

### 7.1 실측 (7 오더 pool, adapter 내 1,410 site)

```text
||agg_mismatch||          p50 ≈ 1e-16     (오더별 9e-17 ~ 2e-15)
||agg_mismatch|| / ||d_obs||  p50 ≈ 1e-16
```

**부동소수점 수준이다.** last-wins 와 mean 이 실제로 갈리는 site 가 없다. 원인은 A2 확정
(`SITE_LEVEL_ENCODER_V1`, §2.1.2)과 같다 — 오더 52 에서 form 수준과 site 수준의 고유 site 집합이
동일했고(2,377), 조건별로 값을 내는 form 이 사실상 하나다.

따라서 `c1_prereg_v1.md` §2.2 가 나열한 τ 의 세 성분 중 **(3) form 집계 차이는 실질적으로
무해**하다. 논문에서 (1) 궤적 변화와 (2) 대입 채움 두 성분만 서술하고, (3)은 측정해서 배제했다고
쓴다. **측정 없이 배제했다고 쓰지 않는다.**

## 8. 정렬 점검의 최종 상태

| 지점 | 내용 | 상태 |
|---|---|---|
| A1 | site key 정규형 | 해소. `f"{GENE}_{POSITION}"` |
| A2 | form → site 집계 | 해소. `SITE_LEVEL_ENCODER_V1` (집계 함수 불요) |
| A3 | control 성분 | 해소. 7 오더 전부 control 조건 없음. 인코더에 없는 조건 0 |
| A4 | 조건 수열 | 해소. 재배열 불필요 |
| A5 | 모집단 교집합 | 해소. adapter 내 1,410 / NNLS 1,660 site |
| A6 | form 값 집계 비대칭 | 해소. 실측 불일치 ≈ 1e-16 |

**τ 는 잘 정의된다.** 남은 해석 한계는 정렬 문제가 아니라 §2.1.3 의 결측 처리 비대칭(대입 채움
방향이 `d` 에 섞임)이며, 그것은 `d_obs` secondary(§2.1.4.1)로 측정된다.
