# Chapter 2 감사 프로토콜 v1 — 배포된 kinase 귀속의 재현 가능한 감사

**상태:** `detect` · `characterize` · `reproduce` · `guard` · `regression-test` 5단계 완료 (2026-08-21)
**대상 코드:** `ptm_shared/tmm_audit.py`, `ptm_shared/tmm_attribution_guard.py`,
`ptm_shared/tmm_identifiability.py`, `scripts/freeze_tmm_audit_fixture.py`,
`scripts/run_tmm_guard_ablation.py`, `workers/tests/test_tmm_audit_protocol.py`
**동결 fixture:** `workers/tests/fixtures/tmm_audit_v1/` (620KB, git 추적)
**선행 문서:** `docs/tmm_identifiability_diagnosis.md` (detect·characterize 원본),
`docs/integrated_research_design_v2.md` §9.5 (프로토콜 요구)

---

## 0. 이 장이 기여인 이유

`integrated_research_design_v2.md` §9.5가 요구한 형태는 다음이다.

```text
detect → characterize → reproduce → guard → regression-test
```

"46%"는 headline 관찰일 뿐이고, 단일 파이프라인 사례로 일반적 CS 방법 주장을 하면 약하다.
장의 기여는 **프로토콜**로 정의된다. 이 문서는 그 5단계를 각각 실행 가능한 산출물로
고정한다.

**주장 범위.** 이 장은 배포된 추정기가 무엇을 결정하지 못하는지를 측정한다. 더 나은
추정기를 제안하지 않으며, 여기서 얻은 어떤 수치도 kinase 귀속의 생물학적 정확도에 대한
진술이 아니다. 측정되는 것은 식별가능성, 즉 해집합의 크기다.

---

## 1. 감사 대상

플랫폼은 공유 PTM site의 시계열을 후보 kinase들로 분해해 contribution ratio를 보고한다.

```text
minimize ||A a − y||₂   subject to a ≥ 0        (deconvolve_shared_ptm)
reported ratio = a / Σa
```

`A`의 열은 kinase profile이고, exclusive substrate가 부족한 kinase는 문헌 peak time에서
만든 Gaussian이 관측인 것처럼 들어간다. `y`는 부호 있는 log2FC이며 미측정 시점은 0으로
채워진다.

---

## 2. detect · characterize (2026-08-18, 원본 문서에 상세)

`docs/tmm_identifiability_diagnosis.md`가 담당한다. 요약하면 세 가지 증거를 가정 강도 순으로
계산했다: 구조적 증거(rank, 조건수, 열 간 coherence, 가정 없음), 국소 민감도(active set
σ_min), leave-one-kinase-out ΔRSS.

원인은 두 가지가 겹친 것으로 측정되었다.

1. **동일한 컬럼의 중복.** `MIN_EXCLUSIVE_FOR_PROFILE = 3`을 만족하지 못한 kinase가 모두
   generic 기본값 `peak_min = 30.0`을 받아 **문자 그대로 같은 컬럼**이 된다. 문헌 prior
   자체가 퇴화한 것은 아니다(서로 다른 peak 8종은 rank 4, 최소 coherence 0.398).
2. **비음수 basis 대 음수 시계열.** `A`의 모든 열은 비음수인데 `y`는 부호가 있다. 감소 위주
   site에서 NNLS는 모든 계수를 0으로 돌려주고 production은 균등 ratio를 보고한다.

`ambiguity_aware_attribution`은 여기서 "그렇다면 무엇을 보고할 수 있는가"에 답한다.
평행 열을 union-find로 병합해 **그룹 몫**을 추정하고, 비음수 조합이 궤적을 설명하지 못하면
`attribution_supported = False`를 반환한다.

---

## 3. reproduce (2026-08-21, 신규)

### 3.1 왜 필요했는가

공표된 감사 표는 살아 있는 MySQL `orders.kinase_activity_heatmap` 행과 **gitignore된**
`data/outputs/**` TSV에서 산출되었다(`.gitignore` line 34). 두 입력 모두 버전 관리 대상이
아니므로 그 표는 **원리적으로 재생성 불가능**했다. 학위논문 표가 재생성 불가능하면 심사에서
방어할 수 없다.

### 3.2 동결 fixture

`scripts/freeze_tmm_audit_fixture.py`가 감사가 소비한 입력 전체를 아카이브한다. site별로
설계행렬 열, 후보 이름, prior 유래 플래그, 0 대입된 target, 관측 마스크, 그리고 **원래
site 인덱스**를 담는다. 인덱스를 보존하는 이유는 site별 seed가 `seed + site_index`이므로
순서가 어긋나면 부트스트랩이 재현되지 않기 때문이다.

열은 중복 제거되어 저장된다. **1,160개 site의 후보 열 7,216개가 서로 다른 벡터 44개로
수축한다.** 이 수축 자체가 §2의 중복 열 관찰과 같은 사실이다.

| 오더 | site | 서로 다른 열 | 배포 solver와의 최대 편차 |
|---|---:|---:|---:|
| 28 Irisin_TimeCourse_Phospho | 52 | 10 | 3.60e-05 |
| 33 Korea_timecouse_drugrepositioning | 42 | 8 | 4.89e-05 |
| 36 KRIBB_SCS_Phosphorylation | 907 | 9 | 4.96e-05 |
| 45 Microgravity_Muscle_Atrophy | 24 | 6 | 4.97e-05 |
| 47 WithoutCu-AmyloidFibril-microglia | 86 | 4 | 0.00e+00 |
| 48 Cu-Amyloid_fibril-microglia | 49 | 7 | 4.92e-05 |

"배포 solver와의 최대 편차"는 동결 시점에 재구성 행렬의 해를 `deconvolve_shared_ptm` 출력과
직접 대조한 값이다. 재생 경로는 라이브 모듈이 없으므로 이 값을 **다시 계산하지 않고
기록된 값을 옮긴다.** 즉 "배포 추정기와 동일하다"는 근거는 동결 시점의 증거다.

### 3.3 계산 지점의 단일화

살아 있는 감사와 fixture 재생이 **모두 `ptm_shared.tmm_audit.audit_sites`를 통과**한다.
계산이 두 곳에 복제되면 재생이 다른 문제를 설명하게 되므로 구조적으로 막았다.

### 3.4 재생된 통합 표 (2026-08-21, 권위 있는 수치)

`workers/tests/fixtures/tmm_audit_v1/pooled_summary.json`

| 항목 | 값 |
|---|---|
| 오더 | 6 |
| 공유 site | 1,160 |
| identifiable | **0.69%** (8) |
| weakly identifiable | 1.47% (17) |
| non-identifiable | 51.55% (598) |
| equal-weight fallback | **46.29%** (537) |
| structurally underdetermined | 95.26% |
| rank-one design | 54.22% |
| `relative_residual ≥ 0.999` | 55.09% |
| top-1이 자신의 ambiguity set 안에 있음 | 89.91% |
| **top-1의 컬럼이 prior 유래** | **94.14%** |

ambiguity-aware 재보고:

| 항목 | 값 |
|---|---|
| 현재 발표되는 개별 kinase ratio | 7,216 |
| 실제 추정 가능한 그룹 몫 | 891 |
| 보고량 감소 | 87.65% |
| 증거 부족으로 귀속 불가 | 46.29% (537 site) |
| 병합 후 남은 지원 site | 623 |
| └ identifiable | 27.13% (169) |
| └ weakly identifiable | 42.38% (264) |
| └ non-identifiable | 30.50% (190) |

개별 kinase 해상도에서 0.69%였던 것이 그룹 해상도에서 27.13%가 되고 42.38%가 약하게 식별
가능해진다. **해상도를 낮추는 대가로 사용할 수 없던 출력의 약 70%가 방어 가능한 진술로
바뀐다.**

> **이 표의 비율을 오더 하나의 기대값으로 읽지 않는다.** site를 오더 구분 없이 pooling하며
> 오더 36이 site의 78.2%를 차지한다. 오더별 값과 어느 비율이 일반화되는지는 **§4.3.1**에
> 있다 — `top1_from_prior_rate`만 6/6 오더에서 0.90 이상이고 나머지는 폭이 0.31–0.45다.
>
> **또한 "오더 6"은 독립 획득 6건이 아니다.** 오더 33과 45는 원자료 mzML 12개가 완전히
> 동일하므로 **독립 획득은 5건**이다(§4.3.2). 오더 수를 표본 수로 서술하지 않는다.

### 3.5 실행

```bash
# 동결 (라이브 DB 필요, 1회)
docker exec -i ptm-api-server env PYTHONPATH=/app:/opt python - \
    --order-ids 48,47,45,36,33,28 \
    --reference-summary /app/data/outputs/_diagnostics/tmm_identifiability/_pooled_summary.json \
    < scripts/freeze_tmm_audit_fixture.py

# 재생 (DB·app.services 불필요, 언제든)
docker exec -w /app ptm-worker-preprocessing env PYTHONPATH=/app:/opt python -c \
  'from pathlib import Path; from ptm_shared.tmm_audit import replay_fixture_dir; \
   print(replay_fixture_dir(Path("tests/fixtures/tmm_audit_v1"))[1]["n_sites"])'
```

---

## 4. 표류 사건 — 프로토콜이 즉시 잡아낸 것

**첫 동결에서 2026-08-18 표가 재현되지 않았다.** 이것이 이 단계의 가치를 보여주는 사례이므로
숨기지 않고 기록한다.

차이는 전부 오더 48 한 곳이었다(1,310 → 1,160, 정확히 150 site).

| | 2026-08-18 | 2026-08-21 |
|---|---:|---:|
| kinase 수 | 87 | 29 |
| module 내 site | 235 | 71 |
| 공유 site | 199 | 49 |
| 조건 목록 | `['0.5','1h','3h','6h','24h']` | 동일 |
| site key 교집합 | — | 47 (152 소실, 2 신규) |

`orders.kinase_activity_heatmap`은 **가변 production 상태**이고, 2026-08-20 06:19 재실행이
후보 집합을 덮어썼다. 사라진 후보는 `CSNK2_C1`…`CSNK2_C5`, `CAMK2_C0`, `CDK1_C3` 같은
**클러스터 접미사 변종**이다(구 후보 집합의 55.2%, 25개 base kinase가 복수 후보로 존재).

따라서 **2026-08-18 표는 복구 불가능하다.** 입력이 아카이브되지 않았고 그 상태로 되돌릴
방법이 없다.

### 4.1 결론은 표류에 견딘다

| 항목 | 2026-08-18 | 2026-08-21 | 방향 |
|---|---:|---:|---|
| identifiable | 1.15% | 0.69% | 더 나빠짐 |
| top-1 prior 유래 | 92.52% | 94.14% | 더 나빠짐 |
| equal-weight fallback | 46.18% | 46.29% | 거의 동일 |
| rank-one design | 54.35% | 54.22% | 거의 동일 |
| 오더 48 중복 열 | 91.0% | 95.9% | 더 나빠짐 |

**접미사 변종이 중복 열의 원인이었다는 가설은 기각된다.** 정리된 후보 집합에서 중복률이
오히려 올랐고(91.0% → 95.9%), 같은 base kinase가 한 site의 후보 목록에 함께 들어온 경우는
199개 중 5개(2.5%)뿐이었다. 중복 열은 §2가 지목한 generic 30분 fallback이 만든다.

### 4.2 이것 자체가 관찰이다

감사 대상이 버전 관리되지 않는 가변 상태였다는 사실, 그리고 재실행이 설계행렬의 **열 집합
자체**를 바꾼다는 사실은 신뢰성 관점의 관찰이다. 후보 집합의 출처와 결정성은
`integrated_research_design_v2.md`의 BLOCKER-F(후보 집합 오염 경로)와 같은 축에 있다.

**단, 이 문서는 그 재실행이 왜 후보를 87→29로 줄였는지 규명하지 않았다.** LLM 예측 기여
변화인지, KEA3 응답 변화인지, 설정 변경인지는 미해결이다 → **§4.3에서 해소.**

### 4.3 원인 규명 (2026-08-22) — 세 후보 전부 아니었다

`scripts/diagnose_heatmap_writer_provenance.py`. 산출 레코드
`docs/results/chapter2_audit/heatmap_writer_provenance.json`.

원인은 LLM도 KEA3도 설정도 아니고 **`orders.kinase_activity_heatmap`에 서로 다른 후보 어휘를
쓰는 writer가 두 개 있다**는 것이다.

| writer | 코드 | 비우세 클러스터 처리 |
|---|---|---|
| `api_endpoint` | `api-server/app/api/orders.py:7725` | **별도 후보로 발행.** 이름 `f"{kinase}_c{cluster_id}"`, 자기 `substrates` 목록 보유 |
| `pipeline_worker` | `workers/rag_enrichment/tasks.py::_compute_kinase_activity_heatmap` | `cluster_details` 안에만 보관. 후보로 발행하지 않음 |

두 writer는 최상위 키로 구별된다 — endpoint는 `_cache_hash`·`computed_at`·`scoring_method`,
pipeline은 `_cached`·`all_kinase_scores`. `classify_heatmap_writer`가 이 판별을 한다.

**6 오더에서 판별과 접미사 변종 유무가 완전히 일치한다. 반례가 없다.**

| 오더 | writer | 후보 | `_c{n}` 변종 | 갱신 시각 |
|---|---|---:|---:|---|
| 28 | `api_endpoint` | 30 | 7 | 2026-06-19 07:13 |
| 33 | `pipeline_worker` | 32 | 0 | 2026-08-17 02:42 |
| 36 | `api_endpoint` | 111 | 87 | 2026-07-17 02:47 |
| 45 | `pipeline_worker` | 23 | 0 | 2026-07-05 13:48 |
| 47 | `api_endpoint` | 44 | 22 | 2026-08-20 05:13 |
| 48 | `pipeline_worker` | 30 | 0 | **2026-08-20 06:19** |

오더 47과 48은 **같은 실험의 두 arm**(WithoutCu / Cu)이고 같은 날 한 시간 차로 갱신되었는데
writer가 갈렸다. 2026-08-20 06:19 재실행은 오더 48의 endpoint-writer 상태를
pipeline-writer 상태로 교체했고, 그래서 sub-pattern 후보가 전부 사라졌다. 이것이 87→29다.

**어느 writer가 옳은지는 이 진단이 말하지 않는다.** 후보가 많은 쪽이 더 정확한 것이 아니다 —
§4.1에서 변종이 정리된 뒤 중복 열 비율이 오히려 올랐다(91.0% → 95.9%). 그리고 2026-08-18
상태는 이 규명으로도 **복구되지 않는다.**

#### 4.3.1 규명이 드러낸 더 큰 문제 — §3.4 표의 어느 비율이 일반화되는가

writer가 갈린다는 것은 §3.4의 통합 표가 **두 어휘를 섞은 것**이라는 뜻이다. 확인하려고 동결
fixture 재생을 층화했더니, writer보다 **pooling 지배**가 더 큰 문제로 드러났다.

| 오더 | writer | site | 몫 | 구조적 미결정 | rank-1 | 설명 없음 | prior 유래 | 균등 fallback |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 28 | endpoint | 52 | 4.5% | 0.6154 | 0.5385 | 0.4808 | 0.9231 | 0.4808 |
| 33 | pipeline | 42 | 3.6% | 0.8333 | 0.2619 | 0.4048 | 0.9048 | 0.2857 |
| **36** | endpoint | **907** | **78.2%** | 0.9713 | 0.5821 | 0.6196 | 0.9350 | 0.5314 |
| 45 | pipeline | 24 | 2.1% | 1.0000 | 0.3333 | 0.2500 | 1.0000 | 0.1667 |
| 47 | endpoint | 86 | 7.4% | 1.0000 | 0.4186 | 0.2093 | 1.0000 | 0.1163 |
| 48 | pipeline | 49 | 4.2% | 0.9592 | 0.3673 | 0.2245 | 0.9796 | 0.0816 |

| 공표 비율 | 통합 | 오더별 최소 | 오더별 최대 | 폭 |
|---|---:|---:|---:|---:|
| 구조적 미결정 | 0.9526 | 0.6154 | 1.0000 | 0.385 |
| rank-1 설계 | 0.5422 | 0.2619 | 0.5821 | 0.320 |
| 설명 없음 | 0.5509 | 0.2093 | 0.6196 | 0.410 |
| top-1이 ambiguity set 안 | 0.8991 | 0.6923 | 1.0000 | 0.308 |
| **top-1 prior 유래** | **0.9414** | **0.9048** | **1.0000** | **0.095** |
| 균등 fallback | 0.4629 | 0.0816 | 0.5314 | 0.450 |

**`top1_from_prior_rate`만 오더에 걸쳐 좁다.** 6 오더 전부에서 0.90 이상이며 writer·크기·종·
조건 수에 무관하다. 나머지 비율은 폭이 0.31–0.45이고 오더 36(site 78.2%)이 통합값을 정한다.

이것은 Chapter 2의 서술을 다음과 같이 바꾼다.

```text
일반화 가능   "top-1 kinase 는 데이터가 아니라 prior 에서 나온다"  ← 6/6 오더, ≥ 0.90
              이것이 이 장의 가장 강한 주장이며 층화에 살아남는다

데이터셋 국소  "95.26% 가 구조적으로 미결정", "46.29% 가 균등 fallback"
              통합값을 일반 성질로 서술하지 않는다. **지배 오더의 성질**이며 오더별 표를
              반드시 병기한다 (오더 28 은 미결정 61.5%, 오더 48 은 fallback 8.2%)
```

짝지은 준대조(오더 47 대 48, 같은 세포·같은 5 시점·Cu 유무만 다름)에서는 두 writer의 차이가
작다(미결정 1.000 대 0.959, fallback 0.116 대 0.082). 즉 층 수준의 큰 격차
(fallback 0.4947 대 0.1739)는 **writer 효과가 아니라 오더 36의 크기**에서 나온다.
n = 2이므로 검정하지 않으며, writer 효과와 Cu 효과도 이 대조에서 분리되지 않는다.

#### 4.3.2 오더 33 과 45 는 같은 원자료다 — 오더별 폭의 해석이 바뀐다

**발견 (2026-08-22, 탐색적.** 감사 결과를 본 뒤 착수한 데이터셋 단위 감사에서 나왔다.
`integrated_research_design_v2.md` §11.1.2, 산출 `docs/results/dataset_audit/distinct_units_v1.json`.**)**

```text
order 33  Korea_timecouse_drugrepositioning
order 45  Microgravity_Muscle_Atrophy_Phosphoproteomics
          → 원자료 mzML 12개가 완전히 동일 (교집합 12/12, 획득 폴더 Kim HyunSu_MicroGravidy_Time_Course)
```

따라서 **감사 오더 6건은 독립 획득 5건이다.** 두 오더는 같은 획득을 다르게 처리한 결과이며
writer 도 같다(둘 다 pipeline). 그런데 값이 다르다 — site 42 대 24.

이것은 §4.3.1 의 "오더별 폭"에 **재처리 성분이 섞여 있다**는 뜻이므로 그 폭을 전부 데이터셋
성질로 읽을 수 없다. 같은 획득 내 차이를 오더 간 폭과 나란히 둔다.

| 비율 | 오더 33 | 오더 45 | 획득 내 차 | 오더 간 폭 | 비 |
|---|---:|---:|---:|---:|---:|
| 구조적 미결정 | 0.8333 | 1.0000 | 0.1667 | 0.385 | 0.43 |
| rank-1 설계 | 0.2619 | 0.3333 | 0.0714 | 0.320 | 0.22 |
| 설명 없음 | 0.4048 | 0.2500 | 0.1548 | 0.410 | 0.38 |
| **top-1 prior 유래** | **0.9048** | **1.0000** | **0.0952** | **0.095** | **1.00** |
| 균등 fallback | 0.2857 | 0.1667 | 0.1190 | 0.450 | 0.26 |

두 가지가 따라 나온다.

**(1) `top1_from_prior_rate` 의 오더 간 폭은 전부 한 획득 안에서 재현된다.** 오더 간 최솟값
0.9048 과 최댓값 1.0000 이 각각 오더 33 과 45 이므로, 이 지표의 폭 0.095 는 서로 다른 데이터셋
사이의 차이가 아니라 **같은 원자료를 두 번 처리한 차이**다. 이는 §4.3.1 의 결론을 약화시키지 않고
강화한다 — 이 지표는 데이터셋을 바꿀 때 재처리를 바꿀 때보다 더 흔들리지 않으며, 두 경우 모두
**0.90 아래로 내려가지 않는다.**

**(2) 나머지 네 비율은 오더 간 폭이 획득 내 차보다 크다** (비 0.22–0.43). "통합값을 일반 성질로
서술하지 않는다"는 §4.3.1 의 판단은 유지된다. 다만 그 폭의 **22–43% 는 데이터가 아니라 처리에서
온다**고 병기해야 한다. 오더별 표를 "데이터셋 간 변동"이라고 이름 붙이지 않는다.

**주장 금지.** n = 1 쌍이다. 획득 내 차의 분포를 추정하지 않으며 위 비를 재처리 변동의 추정값으로
쓰지 않는다. 두 오더의 처리 차이(검색 설정·PTM 종류·조건 정렬)가 무엇인지도 이 관찰은 말하지
않는다 — 오더 33·45 는 조건 목록이 비시간순인 두 오더이기도 하므로(§8) 시간축 뒤틀림이 교란으로
남아 있다.

---

## 5. guard (2026-08-21, 신규)

### 5.1 정책

`ptm_shared/tmm_attribution_guard.py`

| 정책 | 발표 | 가중합 |
|---|---|---|
| `off` (**기본값**) | 현재 배포 동작. 증거 없는 균등 ratio도 그대로 발표한다 | 전부 포함 |
| `strict` | 비음수 조합이 궤적을 설명하지 못하는 site의 `contribution_ratio`를 None으로 발표 | 그 site 제외 |
| `group_share` (2026-08-22, §5.5) | 거기에 더해 ambiguity 그룹 내부의 균등 분할도 None으로 발표 | **`strict`와 동일** |

기본값이 `off`인 이유는 `integrated_research_design_v2.md` §2.7의
`production_influence_allowed = False`를 유지하고 **진행 중인 분석의 수치를 바꾸지 않기**
위해서다. 정책을 켜는 것은 명시적 결정이어야 한다.

`scripts/verify_tmm_identifiability_additive.py`로 오더 36·48·47·28에서 **기존 필드 불일치
0건**을 확인했다. 새로 생긴 것은 `tmm_identifiability.guard_policy`,
`n_guard_withheld`, `n_guard_scoring_excluded` 세 키와 보류 항목의
`guard_scoring_excluded` 플래그다(마지막 둘은 2026-08-22 §5.5 추가).

`api-server/tests/test_temporal_kinase_scoring_guard.py`가 세 정책의 production 출력을
직접 비교한다 — §5.5의 "가중합은 `strict`와 동일"은 정책 함수가 아니라 **`compute_weighted_kinase_scores`
의 실제 출력**에서 확인된다. 이를 위해 `api-server/Dockerfile`에 `ARG INSTALL_DEV_DEPS=true`를
두고 `api-server/tests`를 읽기 전용으로 마운트했다(§6.1의 workers 조치와 같은 이유).

### 5.2 막지 않는 것과 그 이유

`off`·`strict`는 `unresolved_shared`를 막지 않는다. 그룹 몫은 데이터가 결정하므로 **증거가
있고**, 없는 것은 그룹 내부 분할뿐이다. 제외하면 실재 신호를 버리게 되며 균등 분할은 그룹
몫으로 상한이 잡힌다.

**개정 (2026-08-22).** "그룹 몫만 발표하도록 바꾸는 것은 출력 스키마 변경이므로 v1 범위 밖"이라던
판단을 §5.5에서 뒤집었다. 스키마를 **가산적으로** 바꾸면 기존 키의 의미를 건드리지 않고 되며,
그룹 몫을 **가중합에는 남기고 발표에서만 지우면** 위 논거("실재 신호를 버린다")가 유지된다.
남는 46%~ 구간에 대한 이 항의 우려는 §5.5.1이 닫는다 — 다만 실제 구간은 46%가 아니라 96.65%였다.

`unannotated`도 막지 않는다. 증거에 대한 진술이 아니라 주석 계산이 예외로 실패했다는
인프라 오류이며, 코드 버그로 데이터가 조용히 사라지는 것이 더 나쁘다.

### 5.3 guard ablation

`scripts/run_tmm_guard_ablation.py`. 동결 fixture만 쓰므로 언제든 같은 값이 나온다.
`fc_threshold = 0.3`(production 기본값)을 두 arm에 동일하게 적용한다.

| 오더 | 공유 site | 보류 site | 보류율 | 공유 증거를 전부 잃는 kinase |
|---|---:|---:|---:|---|
| 28 | 52 | 25 | 48.1% | 3 / 30 |
| 33 | 42 | 12 | 28.6% | 0 / 29 |
| 36 | 907 | 482 | 53.1% | 0 / 111 |
| 45 | 24 | 4 | 16.7% | 1 / 23 |
| 47 | 86 | 10 | 11.6% | 3 / 44 |
| 48 | 49 | 4 | 8.2% | 0 / 29 |

통합:

| 항목 | 값 |
|---|---|
| 보류되는 site | 537 / 1,160 (**46.29%**) |
| 보류되는 (kinase, site) 기여 쌍 | 3,463 / 7,216 (**47.99%**) |
| kinase 수 | 163 |
| 공유 증거의 **과반**을 잃는 kinase | **74** (45.4%) |
| 공유 증거를 **전부** 잃는 kinase | 4 (`CDK1/2_C3`, `CDK5_C3`, `HEATR1`, `PKC_C3`) |

즉 **현재 발표되는 개별 kinase 기여의 약 48%가 증거 없는 균등 fallback**이며, kinase 163개 중
74개는 공유 substrate 증거의 절반 이상이 그렇다.

보류 site 비율 46.29%는 감사의 `equal_weight_fallback_rate`와 **소수점까지 일치**한다.
회귀 테스트가 이 일치를 고정한다(두 경로가 갈라지면 guard가 감사와 다른 것을 막고 있다는
뜻이다).

### 5.4 해석 한계

- 공유 site만 다룬다. exclusive substrate는 guard 대상이 아니므로 집계 밖이며, 따라서
  "공유 증거 중 비율"이지 전체 증거 대비 비율이 아니다.
- q-value가 fixture에 없어 통과 판정은 `|fc| ≥ 0.3`만 쓴다. production이 q-value를 함께
  보는 site에서는 양이 다를 수 있다.
- **보류량은 정확도 개선폭이 아니다.** 측정된 것은 발표 범위의 축소다.

### 5.5 `group_share` 정책 — 그룹 몫 전용 발표 (선언 2026-08-22, 구현 착수 전)

§5.2 는 "그룹 몫만 발표하도록 바꾸는 것은 출력 스키마 변경이므로 v1 범위 밖"이라고 적었다.
그 항목을 여기서 닫는다. **새 측정도 새 임계도 도입하지 않는다** — §3.4 의
`attribution.estimable_group_shares = 891` 과 `per_kinase_ratios_published = 7216`,
`quantity_reduction = 0.8765` 는 2026-08-18 동결분에 이미 있다. 이 정책은 **production 출력이
그 이미 측정된 해상도를 따라가게** 만드는 것이며, 감사 결론을 바꾸지 않는다.

**막는 것.** `unresolved_shared` 의 `contribution_ratio` 를 None 으로 발표한다. 그 값은
`group_ratio / |group|` 즉 **균등 분할**이며 solver 가 고른 값이지 데이터가 정한 값이 아니다.

**막지 않는 것과 그 이유.** 그룹 몫(`group_ratio`)과 구성원 목록(`ambiguity_group_members`)은
그대로 발표한다. 스키마에 이미 있다. 그룹 몫은 데이터가 결정하므로 증거가 있고, 없는 것은
그룹 내부 분할뿐이다 — §5.2 의 논거는 **그대로 유지된다.**

**가중합은 건드리지 않는다.** 이것이 `strict` 와의 핵심 차이다.

```text
정책            unsupported                     unresolved_shared
off             ratio 발표, 점수 포함            ratio 발표, 점수 포함
strict          ratio None, 점수 제외            ratio 발표, 점수 포함
group_share     ratio None, 점수 제외            ratio None,  점수 **포함**
```

즉 `group_share` 의 점수는 `strict` 의 점수와 **정확히 같다.** 바뀌는 것은 발표뿐이다.
비대칭의 근거: 그룹 몫을 점수에서 빼면 §5.2 가 경고한 대로 **실재하는 신호를 버린다.**
반면 균등 분할을 발표하는 것은 없는 것을 있다고 말하는 것이다. 두 행위는 다르며
`GuardDecision` 이 `ratio_for_scoring` 과 `published_ratio` 를 분리해 둔 이유가 바로 이 경우다.

**스키마 변경은 가산적이다.** 기존 키의 의미를 바꾸지 않는다.

```text
신규  GuardDecision.scoring_excluded : bool
신규  detail["guard_scoring_excluded"] : bool          # 보류된 항목에만
신규  tmm_identifiability["n_guard_scoring_excluded"]  # 점수에서 빠진 수
유지  detail["contribution_ratio"], detail["group_ratio"], detail["ambiguity_group_members"]
유지  tmm_identifiability["n_guard_withheld"]          # off·strict 에서 값 불변
```

`n_guard_withheld` 는 "`contribution_ratio` 가 None 인 수"라는 뜻을 유지하므로
`off`(0)·`strict`(unsupported 수)에서 값이 바뀌지 않는다. `group_share` 에서만 커진다.

**기본값은 `off` 로 남는다.** `integrated_research_design_v2.md` §2.7 의
`production_influence_allowed = False` 를 유지한다. 세 정책 중 어느 것도 기본값이 아니게
되는 변경은 별도 결정이다.

**주장 금지.** 이 정책으로 kinase 예측이 개선된다고 서술하지 않는다. 발표 해상도의 하강이다.
`group_share` 를 켠 출력이 옳다는 뜻도 아니다 — 남는 그룹 몫의 30.50% 는 병합 후에도
non-identifiable 이다(§3.4 reduced verdicts).

### 5.5.1 `group_share` 결과 (2026-08-22)

`scripts/run_tmm_guard_ablation.py`, 동결 fixture만 사용. **기존 arm 수치는 전부 불변**이다
(보류 site 537 / 46.29%, 보류 쌍 3,463 / 47.99%, kinase 163, 전부 상실 4, 과반 상실 74).
스키마 변경이 가산적임의 확인이다.

**독립 경로 재현.** `n_estimable_group_shares = 891` 과
`published_quantity_reduction = 0.8765243902439024` 가 2026-08-18 동결분의
`attribution.estimable_group_shares` · `quantity_reduction` 과 **소수점까지 일치**한다.
guard 경로와 감사 경로가 같은 양을 세고 있다는 뜻이며, 갈라지면 회귀 테스트가 잡는다.

| 정책 | 발표되는 개별 kinase ratio | 보류된 쌍 | 보류율 | 가중합 |
|---|---:|---:|---:|---|
| `off` | 7,216 | 0 | 0% | 전부 포함 |
| `strict` | 3,753 | 3,463 | 47.99% | unsupported 제외 |
| **`group_share`** | **242** | **6,974** | **96.65%** | **`strict` 와 동일** |

발표되는 양의 구성이 바뀐다.

```text
off / strict   개별 kinase ratio 만 발표
group_share    그룹 몫 891 개를 발표
               ├ 다중 구성원 그룹 649 (72.8%)  → 개별 ratio 없음. 몫 + 구성원 목록만
               └ 단일 구성원 그룹 242 (27.2%)  → 몫이 곧 개별 ratio
               7,216 → 891 = 발표량 87.65% 감소
```

**가장 강한 결과 — kinase 163개 중 129개(79.1%)는 개별 기여가 분리되는 공유 site 가
하나도 없다.** `strict` arm 에서 "공유 증거를 전부 잃는 kinase"는 4개였다. 그 4개는 증거가
아예 없는 경우이고, 129개는 **증거가 있으나 그 증거가 자기 것인지 그룹 동료 것인지 데이터가
말하지 못하는** 경우다. 두 수를 섞어 읽지 않는다.

| 오더 | 발표 쌍 | 보류 | 그룹 몫 | 감소 |
|---:|---:|---:|---:|---:|
| 28 | 120 | 83 | 49 | 59.2% |
| 33 | 187 | 177 | 47 | 74.9% |
| **36** | **6,019** | 5,856 | 576 | **90.4%** |
| 45 | 119 | 119 | 29 | 75.6% |
| 47 | 496 | 465 | 126 | 74.6% |
| 48 | 275 | 274 | 64 | 76.7% |

**§4.3.1 의 pooling 경고가 여기에도 적용된다.** 통합 87.65% 는 오더 36(발표 쌍의 83.4%)이
정하며 오더별 감소는 59.2%–90.4% 다. 통합값을 오더 하나의 기대값으로 서술하지 않는다.
다만 폭이 다른 공표 비율(0.31–0.45)보다 좁고, 동일 획득인 오더 33·45 가 74.9% 와 75.6% 로
근접한다(§4.3.2) — 이 지표는 재처리에 크게 흔들리지 않는다. **n = 1 쌍이므로 검정하지 않는다.**

**§5.2 가 남긴 미결이 닫혔다.** 다만 닫힌 방식이 §5.2 의 예상과 다르다 — 그 항은 "guard 가
막지 않는 46%~ 구간이 남는다"고 적었는데, 실제로 남아 있던 구간은 46% 가 아니라 **개별 ratio
7,216 개 중 6,974 개(96.65%)** 였다. `unresolved_shared` 는 site 의 일부가 아니라 **발표되는
숫자의 대부분**이었다.

---

## 6. regression-test (2026-08-21, 신규)

`workers/tests/test_tmm_audit_protocol.py` — 14개. 기존 `test_tmm_identifiability.py`
24개와 함께 **38개 통과** (2.39s).

| 묶음 | 고정하는 것 |
|---|---|
| fixture 무결성 | manifest sha256 일치, 스키마 버전, 결정성 기록(scipy 경로·dtype·ε·부트스트랩), 배포 solver 편차 ≤ 5e-05 |
| reproduce | 재생이 `pooled_summary.json`과 **한 필드도** 다르지 않음, headline 수치 리터럴 고정, 두 번 재생 시 동일, DB·`app.services` 없이 동작, fixture 변조 시 거부 |
| 감사 결론 | identifiable < 2%, top-1 prior 유래 > 90%, rank-one > 50%, 그룹 해상도 회복 > 60% |
| guard | `off`는 pass-through, `strict`는 `unsupported`만 보류, 정책 이름 오타는 예외, ablation 수치 고정, 보류율 == 균등 fallback 비율 |

수치가 바뀌면 코드가 틀렸다는 뜻이 아니라 **바뀐 사실을 사람이 검토해야 한다**는 뜻이다.

### 6.1 실행 환경 — 해소 (2026-08-22)

```bash
docker exec -w /app ptm-worker-preprocessing \
  env PYTHONPATH=/app:/opt python -m pytest tests/test_tmm_audit_protocol.py -q
```

**정본 환경은 worker 이미지 + scipy 1.17.1 + numpy 2.4.6 + pytest 9.1.1이다.**

#### 진단 (2026-08-21)

당시 **`pytest`가 어느 이미지에도 없었다.** 저장소에 `requirements*.txt`는 없고 서비스별
`pyproject.toml`을 쓰는데, 세 서비스 모두 pytest를 `[project.optional-dependencies] dev`에만
선언하고 Dockerfile은 런타임 의존성만 설치했다. **한 곳의 누락이 아니라 저장소 전체의 관례였다.**

| 서비스 | pytest 선언 | 이미지 설치 명령 (2026-08-21 시점) |
|---|---|---|
| `workers` | dev extra | `pip install --no-cache-dir --no-deps .` |
| `api-server` | dev extra | `pip install --no-cache-dir .` |
| `mcp-server` | dev extra | `pip install --no-cache-dir .` |

위 명령을 쓰려면 컨테이너에 pytest를 임시 설치해야 했고, 컨테이너를 재생성하면 사라졌다.

호스트에는 pytest 9.1.1이 있으나 **scipy가 없어 `solve_nnls`가 projected-gradient
fallback으로 떨어진다.** solver 경로가 다르면 고정된 수치가 재현되지 않으므로 호스트는
정본 환경이 아니다.

`workers/.pytest_cache/`가 2026-08-17자로 남아 있다. 그날 pytest를 돌린 곳은 어느 이미지에도
pytest가 없으므로 **호스트였고, 따라서 scipy 없는 fallback solver 환경이었다.** 즉
`test_tmm_identifiability.py` 24개는 감사 수치를 만든 환경에서 검증된 적이 없었다. 이 공백은
2026-08-21에 컨테이너에서 38개 통과를 확인해 닫혔다(그 24개는 합성 구성 계약이라 두 solver
모두에서 통과하지만, "통과했다"는 진술의 환경이 명시되지 않았던 것은 사실이다).

#### 조치 (2026-08-22)

`workers/Dockerfile`이 `optional-dependencies.dev`를 함께 설치한다. 빌드 인자
`INSTALL_DEV_DEPS`(기본 `true`)로 제어하며, 경량 production 빌드는 `false`로 끈다.

```bash
docker compose build celery-worker-preprocessing   # dev extra 포함
docker compose up -d celery-worker-preprocessing
docker exec ptm-worker-preprocessing python -m pytest tests/ -q
#   211 passed, 1 skipped  — 임시 설치 없이
```

**왜 이것이 연구 사안인가.** 고정된 수치를 검증할 수 있는 환경이 존재하지 않으면 그 수치는
고정된 것이 아니다. 감사 수치는 scipy 경로에서 산출되었으므로 scipy 없는 호스트는 검증 주체가
될 수 없고, pytest 없는 이미지도 될 수 없었다. 두 조건을 동시에 만족하는 환경이 이제 이미지에
있다. 이는 §7의 "재현 가능"과 §6의 "회귀 방어"를 처음으로 **자동**으로 만든다.

api-server·mcp-server는 그대로 두었다. 연구 회귀 스위트가 worker 이미지에서만 돌고,
`ptm_shared`가 두 이미지에 동일하게 마운트되므로 검증 환경을 늘릴 이유가 없다.
`temporal_kinase_scoring.py`의 additive 검증은 별도 스크립트
(`scripts/verify_tmm_identifiability_additive.py`)가 담당한다.

---

## 7. 논문에 쓸 수 있는 문장과 쓸 수 없는 문장

권장 — **오더에 걸쳐 성립하는 주장** (§4.3.1로 층화 확인. 이 장의 가장 강한 진술):

- "top-1 kinase의 프로파일 열은 검사한 6 오더(독립 획득 5건) 전부에서 90% 이상 prior 유래이며,
  데이터에서 추정된 것이 아니다." (오더별 0.9048–1.0000, 폭 0.095)
- "이 비율의 오더 간 변동 폭은 같은 원자료를 두 번 처리했을 때의 차이와 같다(양쪽 모두 0.095).
  즉 데이터셋을 바꾸는 것이 재처리를 바꾸는 것보다 이 지표를 더 흔들지 않는다." (§4.3.2)
- "감사 입력이 버전 관리되지 않는 가변 상태였고, 재실행이 설계행렬의 열 집합을 바꾸었다.
  동결 없이는 감사 표가 재현되지 않는다."
- "후보 집합은 데이터의 함수가 아니라 **마지막에 그 행을 쓴 코드 경로의 함수**였다. 같은
  실험의 두 arm이 하루 안에 서로 다른 후보 어휘로 기록되었다." (§4.3)

권장 — **pooling된 유병률.** 아래 문장을 쓸 때는 **오더별 범위를 같은 문단에 병기한다**:

- "배포된 추정기에서 개별 kinase 기여는 검사한 site의 97.8%에서 데이터가 결정한 값이 아니다."
  (identifiable 0.69% + weakly identifiable 1.47%를 제외한 나머지)
- "발표되는 개별 kinase 기여의 47.99%는 비음수 조합이 궤적을 설명하지 못해 균등 fallback으로
  생성된 값이다." → 오더별 균등 fallback은 8.2%–53.1%다
- "해상도를 그룹으로 낮추면 사용할 수 없던 출력의 약 70%가 방어 가능한 진술이 된다."
- "그룹 해상도로 발표하면 개별 kinase ratio 7,216개가 그룹 몫 891개가 된다(87.65% 감소).
  이 감소는 구현된 정책(`group_share`)으로 재현되며 감사 수치와 소수점까지 일치한다." (§5.5.1)
  → 오더별 감소는 59.2%–90.4%이고 오더 36이 발표 쌍의 83.4%를 차지한다
- "검사한 kinase 163개 중 129개(79.1%)는 개별 기여가 데이터로 분리되는 공유 site가 하나도
  없다." (§5.5.1) → `strict`의 "공유 증거를 전부 잃는 4개"와 **다른 진술**이다. 4개는 증거가
  없고, 129개는 증거가 있으나 그것이 자기 것인지 그룹 동료 것인지 알 수 없다
- "이 권고는 배포 기본값이 아니다. 기본값은 `off`이며 발표된 분석 수치는 guard 이전 값이다."
  (§5.1) → 논문의 권고와 배포 동작이 갈린다는 사실을 숨기지 않는다

금지:

- "guard 적용으로 kinase 예측이 개선되었다" — 개선이 아니라 발표 범위의 축소다.
- **"`group_share`가 켜져 있다" 또는 그 함의.** 기본값은 `off`다(§5.1). 정책은 구현되고
  측정됐으나 배포되지 않았다.
- **"그룹 몫은 신뢰할 수 있다".** 병합 후에도 그룹의 30.50%는 non-identifiable이다(§3.4).
  `group_share`는 해상도를 데이터가 지지하는 수준으로 낮추는 것이고 정확도 보증이 아니다.
- **`strict`의 "전부 상실 4개"와 `group_share`의 "분리 불가 129개"를 같은 종류로 합치는 서술.**
  전자는 증거의 부재, 후자는 증거의 귀속 불가다.
- "이 감사로 kinase 귀속이 틀렸음을 보였다" — 측정된 것은 식별가능성이며 정답과의 거리가
  아니다.
- "재현 가능하므로 타당하다" — 재현 가능성은 추적 가능성이고 타당성이 아니다.
- 6개 오더의 유병률을 플랫폼 전체나 다른 파이프라인으로 일반화하는 서술.
- **pooling된 유병률을 오더 하나의 기대값으로 제시하는 서술.** 위 두 그룹을 섞지 않는다 —
  구조적 미결정 95.26%는 오더 28에서 61.5%이고, 통합값은 오더 36(site 78.2%)이 정한다.
- "endpoint writer의 후보 집합이 진짜다" 또는 그 역 — 어느 어휘가 옳은지 이 감사는 판정하지
  않는다. 변종이 정리된 뒤 중복 열 비율은 **올랐다**(91.0% → 95.9%, §4.1).
- **"6 오더"를 독립 표본 6개로 서술하는 것.** 오더 33·45는 동일 획득이므로 독립 획득은 5건이다
  (§4.3.2). 오더 수를 n으로 쓰는 문장을 쓰지 않는다.
- **오더별 표를 "데이터셋 간 변동"이라고 이름 붙이는 것.** 그 폭의 22–43%는 같은 획득의 재처리
  차이로도 나타난다(§4.3.2). "오더 간 변동"이라고만 적는다.

---

## 8. 미해결 항목

| 항목 | 왜 남았는가 | 파급 |
|---|---|---|
| ~~**오더 48 후보 집합이 87→29로 줄어든 원인**~~ | **해소 (2026-08-22).** 세 후보(LLM·KEA3·설정) 전부 아니었다 — `kinase_activity_heatmap`에 후보 어휘가 다른 writer가 둘 있고, 재실행이 endpoint-writer 상태를 pipeline-writer 상태로 교체했다. 6 오더에서 판별과 변종 유무가 완전히 일치한다 (§4.3) | §4.2는 관찰에 머물지 않는다 — **후보 집합이 데이터가 아니라 "마지막에 어느 코드가 그 행을 만졌는가"의 함수**다. 다만 §4.3.1에서 식별성 병리의 크기는 writer보다 pooling 지배에 훨씬 민감함이 드러났다 |
| **writer 통일 여부** | §4.3이 원인을 규명했으나 통일은 production 동작 변경이므로 별도 판단이다. 감사 결론(§4.3.1)은 통일 없이도 서술 가능하다 | 통일하면 후보 집합이 결정적이 되나 어느 어휘가 옳은지는 미정이다. 후보 수가 많은 쪽이 옳다는 근거는 없다(§4.1) |
| ~~**`pytest`가 이미지에 없음**~~ | **해소 (2026-08-22).** `workers/Dockerfile`이 `ARG INSTALL_DEV_DEPS=true`로 dev extra를 함께 설치. 새로 빌드한 컨테이너에서 211 passed, 1 skipped 확인 (§6.1) | 회귀 방어가 처음으로 자동이 되었다 |
| **`ε = 0.10·||y||`** | replicate 수준 분산에서 site별 추정 가능하나 미실행 | 국소 민감도 계열 수치만 영향. 구조적 결론(rank, 중복 열)은 무관 |
| 오더 33·45의 조건 목록 비시간순 | 단위 인식 정렬 도입 전 레거시 산물 | 두 오더의 시간축이 뒤틀림. 정렬이 올바른 36·47·48에서 결론 동일. **두 오더는 동일 획득이므로(§4.3.2) 이는 한 획득의 문제이며 독립 2건이 아니다** |
| **오더 수를 독립 획득 수로 읽어 왔다** | **해소 (2026-08-22).** 오더 33·45 가 원자료 12개 전부 동일. 감사 오더 6건 = 독립 획득 5건 (§4.3.2, `integrated_research_design_v2.md` §11.1.2) | §3.4·§4.3.1 의 오더별 폭에 재처리 성분이 섞인다. `top1_from_prior_rate` 의 폭 0.095 는 **전부 한 획득 안에서 재현**되므로 그 주장은 오히려 강해지고, 나머지 네 비율은 폭의 22–43% 가 처리에서 온다고 병기한다 |
| Insulin 오더(T=6) 제외 | `kinase_activity_heatmap` 미저장 | 시점 수에 따른 식별성 변화 사례 부재 |
| ~~`unresolved_shared`의 그룹 몫 전용 발표~~ | **해소 (2026-08-22).** `group_share` 정책을 구현 착수 전 §5.5에 선언하고 구현·측정했다. 스키마 변경은 가산적이며 가중합은 `strict`와 동일하다 — 그룹 몫은 점수에 남기고 발표에서만 지운다 (§5.5.1) | 발표되는 개별 kinase ratio 7,216 → 891 그룹 몫(**87.65% 감소**). 동결 감사값과 소수점까지 일치. **남아 있던 구간은 §5.2가 적은 46%가 아니라 96.65%였다** — kinase 163개 중 129개는 개별 기여가 분리되는 공유 site가 하나도 없다 |
| `group_share`를 기본값으로 할지 | 기본값 변경은 배포 수치를 바꾸므로 별도 결정이다. `production_influence_allowed = False` 유지 중 | 켜지 않으면 논문의 권고와 배포 동작이 갈린다. 그 사실을 §7에 명시했다 |

---

## 9. 산출물 목록

```text
ptm_shared/tmm_audit.py                          입력 조립·집계·동결·재생·ablation·writer 판별
ptm_shared/tmm_attribution_guard.py              guard 정책
scripts/freeze_tmm_audit_fixture.py              동결 (라이브 DB 필요)
scripts/run_tmm_guard_ablation.py                ablation (fixture만)
scripts/diagnose_heatmap_writer_provenance.py    §4.3 원인 규명 + 층화 (DB + fixture)
scripts/verify_tmm_identifiability_additive.py   guard additive 검증 (중첩 dict 비교 추가)
workers/tests/test_tmm_audit_protocol.py         회귀 테스트 20개
docs/results/chapter2_audit/
  heatmap_writer_provenance.json                 writer 판별·층화·오더별 범위 (2026-08-22)
workers/tests/fixtures/tmm_audit_v1/
  manifest.json                                  sha256·가정·결정성
  order_0*.json                                  오더별 동결 입력 (6개)
  pooled_summary.json                            권위 있는 통합 표 (2026-08-21)
  superseded_pooled_summary_2026-08-18.json      초과된 산출물 (표류 증거로 보존)
  drift_vs_reference.json                        표류 필드 목록
```
