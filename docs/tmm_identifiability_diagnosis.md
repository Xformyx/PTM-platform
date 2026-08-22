# TMM 식별가능성 진단 (v1)

> **이 문서의 수치는 2026-08-18 산출분이며 초과되었다.** 오더 48의
> `orders.kinase_activity_heatmap`이 2026-08-20 재실행으로 덮어써져(kinase 87→29,
> 공유 site 199→49) **이 표는 복구 불가능하다.** 권위 있는 수치는 동결 fixture에서
> 재생되는 `docs/chapter2_audit_protocol_v1.md` §3.4이며, 결론은 유지되거나 강해진다
> (identifiable 1.15%→0.69%, top-1 prior 유래 92.52%→94.14%).
>
> 이 문서는 `detect`·`characterize` 단계의 방법과 원인 분석 기록으로 유효하다.
> `reproduce`·`guard`·`regression-test`는 `docs/chapter2_audit_protocol_v1.md`에 있다.

## 질문

플랫폼은 shared PTM site의 시계열을 후보 kinase들로 분해해 "contribution ratio"를 보고한다.

```
minimize ||A a − y||₂   subject to a ≥ 0        (deconvolve_shared_ptm)
reported ratio = a / Σa
```

지금까지 이 역문제가 **풀 수 있는 문제인지**는 한 번도 검사되지 않았다. 이 진단은 하나의 질문에
답한다: 보고되는 ratio는 데이터가 결정한 값인가, 아니면 동등하게 좋은 해들의 집합 중에서 solver가
임의로 하나를 고른 값인가.

## 방법

`ptm_shared/tmm_identifiability.py`. 진단 전용이며 어떤 점수도 수정하지 않는다.

완료된 오더에 대해 production solver가 받는 설계행렬을 **그대로** 재구성한다. 동일한
`build_kinase_profiles_from_data`, exclusive substrate가 부족한 kinase에 대한 동일한 Gaussian
prior, 미측정 시점에 대한 동일한 0 대입을 사용한다. 재구성이 배포된 추정기와 같다는 것은
`deconvolve_shared_ptm`의 출력과 직접 비교해 확인했다(최대 편차 ≤ 5.0e-05, 오더 47은 정확히 0).

가정 강도 순으로 세 종류의 증거를 계산한다.

1. **구조적 증거 (가정 없음)** — `A`의 rank, 조건수, 열 간 pairwise coherence. rank가 부족하거나
   coherence가 1에 가까우면 어떤 잡음 수준에서도 `a`를 식별할 수 없다.
2. **국소 민감도** — active set 부행렬의 최소 특이값 σ_min(A_S)이 `||δy|| ≤ ε`에 대한 계수 변화량을
   제한한다. 이를 ratio 스케일로 환산한 값이 `ratio_ambiguity_radius`다.
3. **Leave-one-kinase-out** — 후보를 하나 빼고 재적합해 RSS 증가량을 본다. 증가량이 잡음 하한
   `ε²`을 넘지 못하면 그 후보의 부재를 데이터가 감지할 수 없으므로, 데이터가 그 후보를 요구하지
   않는다.

`ε`는 숨은 상수가 아니라 기록되는 가정이다. 아래 결과는 `ε = 0.10·||y||`이며, 부트스트랩 32회로
top-1 안정성을 함께 측정했다. 위 1번의 구조적 결론은 `ε`와 무관하다.

계약 테스트는 `workers/tests/test_tmm_identifiability.py` (24개). 식별 가능한 합성 혼합, collinear
혼합, 시점보다 후보가 많은 경우, 음수 시계열, 0 대입으로 top-1이 뒤집히는 경우를 각각 고정한다.
감사 재현과 guard를 고정하는 테스트는 `workers/tests/test_tmm_audit_protocol.py` (14개)에 있다.

## 결과

완료된 오더 6개, shared site 1,310개.

| order | T | kinases | data-driven profile | sites | identifiable | non-identifiable | equal-weight | duplicate columns | rank-1 design | top-1 from prior |
|---|---|---|---|---|---|---|---|---|---|---|
| 48 | 5 | 87 | 2 | 199 | 3.5% | 59.3% | 36.2% | 91.0% | 50.8% | 84.4% |
| 28 | 9 | 30 | 5 | 52 | 1.9% | 28.8% | 48.1% | 61.5% | 53.8% | 92.3% |
| 36 | 4 | 111 | 4 | 907 | 0.7% | 45.6% | 53.1% | 97.9% | 58.2% | 93.5% |
| 33 | 3 | 32 | 4 | 42 | 2.4% | 66.7% | 28.6% | 88.1% | 26.2% | 90.5% |
| 45 | 3 | 23 | 1 | 24 | 0.0% | 83.3% | 16.7% | 100.0% | 33.3% | 100.0% |
| 47 | 5 | 44 | 0 | 86 | 0.0% | 88.4% | 11.6% | 100.0% | 41.9% | 100.0% |

통합(1,310 site):

- **identifiable 1.1%**, weakly identifiable 1.5%, non-identifiable 51.2%, equal-weight fallback 46.2%
- structurally underdetermined 94.4% (후보 수 > rank(A))
- rank-one design 54.4% (모든 후보에게 단 하나의 시간 형태만 주어짐)
- `relative_residual ≥ 0.999` 54.5% (적합이 아무것도 설명하지 못함)
- top-1 kinase가 자신의 ambiguity set 안에 있음 89.0%
- top-1 kinase의 컬럼이 prior 유래 92.5%

즉 검사한 site의 약 98%에서, 보고되는 kinase 귀속은 데이터가 결정한 값이 아니다.

## 원인

두 가지 기계적 원인이 겹친다. 둘 다 추측이 아니라 측정된 것이다.

### 1. 동일한 컬럼의 중복

오더 36에서 111개 kinase의 profile은 **서로 다른 컬럼이 9개뿐**이고, **100개 kinase가 완전히 동일한
컬럼 하나**를 공유한다.

```
n=100  column=[1.000e+00, 4.289e-03, 5.000e-06, 0.000e+00]
n=  4  column=[1.000e+00, 1.519e-03, 1.000e-06, 0.000e+00]
n=  1  column=[1.000000, 0.497987, 0.485639, 0.347696]
...
```

경로는 fallback의 fallback이다. `MIN_EXCLUSIVE_FOR_PROFILE = 3`을 만족해 data-driven profile을 얻은
kinase는 111개 중 4개뿐이고, 문헌 `typical_peak_min`이 등록된 kinase는 7개뿐이다. 나머지는 모두
generic 기본값 `peak_min = 30.0`을 받아 **문자 그대로 같은 컬럼**이 된다.

한 site의 후보 목록에 이런 kinase가 둘 이상 들어오면 설계행렬에 중복 열이 생기고, NNLS의 해집합은
점이 아니라 단체(simplex)의 한 면이 된다. 이때 보고되는 ratio는 증거가 아니라 solver 내부 구현이
고른 값이다. 문헌 prior 자체가 퇴화한 것은 아니다(서로 다른 peak 8종을 시간당 격자에서 평가하면
rank 4, 최소 coherence 0.398). 문제는 prior가 없는 kinase를 모두 한 컬럼으로 접어버리는 기본값이다.

이것이 시점 수 부족만의 문제가 아니라는 점이 중요하다. T=9인 오더 28도 identifiable 1.9%,
duplicate columns 61.5%다.

### 2. 비음수 basis 대 음수 시계열

`A`의 모든 열은 `np.abs`로 만들어져 비음수인데, `y`는 부호가 있는 log2FC다. 오더 36의 `y` 성분 중
음수 비율 중앙값은 0.75다. 감소 위주 site에서 NNLS는 모든 계수를 0으로 돌려주고, production은
`total < 1e-9` 분기에서 **균등 ratio**를 보고한다(오더 36의 53.1%). 측정처럼 보이지만 증거가 전혀
없는 숫자다. 시간당 격자에서 generic 30분 Gaussian이 첫 시점 스파이크 `[1, 0, 0, 0]`으로 정규화되는
것도 같은 붕괴를 가속한다.

## 0 대입 편향

미측정 시점을 0으로 채우는 것은 "변화 없음"을 주장하는 것이다. 관측된 행만 사용한 적합과 비교하면
모델은 그대로이고 어떤 잔차를 세는지만 달라지므로, 차이는 전부 대입이 만든 편향이다.

전체 1,310 site 중 평가 가능한 것은 316개(24.1%, 나머지는 완전 관측이거나 관측 시점이 2개 미만).
그중 **top-1 kinase가 뒤집히는 비율은 10.1%**이며 오더별로 0%~40%로 갈린다. ratio total variation은
오더 36에서 p90 = 0.44, 오더 33에서 최대 0.95다.

## Ambiguity-aware 추정기 (Chapter 1 출력 형식)

진단만으로는 "보고된 숫자를 믿을 수 없다"에서 끝난다. `ambiguity_aware_attribution`은 그 다음
질문에 답한다: 그렇다면 **무엇을 보고할 수 있는가**.

절차는 세 단계다.

1. **평행 열 병합.** coherence ≥ 0.9999인 후보들을 union-find로 묶는다(전이적). 같은 방향의 열을
   가진 후보들은 합산 계수만 데이터가 결정하므로, 개별 분할은 애초에 추정 대상이 아니다.
2. **축약 설계행렬로 적합.** 그룹당 대표 열 하나로 NNLS를 풀어 **그룹 몫**을 추정한다. 이 값은
   중복을 복제해도 변하지 않는다(테스트로 고정: `test_group_shares_are_unchanged_by_duplicating_a_candidate`).
3. **증거 없음의 명시.** 비음수 조합이 시계열을 설명하지 못하면 `attribution_supported = False`와
   사유를 반환한다. 균등 ratio를 측정처럼 내보내지 않는다.

각 그룹에는 leave-one-group-out ΔRSS 기반 `required` 판정이 붙고, 축약된 문제에 대해 다시
`diagnose_site`를 실행해 **자명한 중복을 제거한 뒤에도 남는 비식별성**을 분리해 보고한다.

같은 6개 오더 1,310 site에 적용한 결과다.

| 항목 | 값 |
|---|---|
| 현재 발표되는 개별 kinase ratio | 7,893개 |
| 실제 추정 가능한 그룹 몫 | 1,012개 |
| 보고량 감소 | 87.2% |
| 증거 부족으로 귀속 불가 | 46.2% (605 site) |
| 병합이 필요한 site | 61.5% ~ 100.0% (오더별) |
| 최대 그룹 크기 p90 | 2 ~ 10 |

중복 병합 뒤 남은 705개 지원 site의 판정 분포가 핵심이다.

| 판정 | 비율 |
|---|---|
| identifiable | 27.1% (191) |
| weakly identifiable | 42.8% (302) |
| non-identifiable | 30.1% (212) |

개별 kinase 해상도에서 identifiable은 1.1%였다. 그룹 해상도로 내려오면 27.1%가 식별 가능해지고
42.8%가 약하게 식별 가능해진다. 즉 **해상도를 낮추는 대가로, 사용할 수 없던 출력의 약 70%가 방어
가능한 진술로 바뀐다.** 이것이 점추정 대신 ambiguity set을 보고해야 하는 이유의 정량적 근거다.

남은 30.1%는 중복 때문이 아닌 진짜 비식별이다. 여기가 Chapter 1의 이론 파트, 즉 anchor 조건과
profile 분리도에 대한 조건을 세워야 하는 영역이다.

## Production 반영 (부가적)

`api-server/app/services/temporal_kinase_scoring.py`에 주석 계층으로 통합했다. 기존 숫자는 하나도
바뀌지 않는다.

설계행렬 조립을 `_build_kinase_design`으로 분리해 deconvolution과 진단이 **같은 행렬**을 쓰도록
고정했다(둘이 갈라져서 진단이 다른 문제를 설명하는 사고를 구조적으로 막는다). 그 위에
`attribute_shared_ptm`이 site별 ambiguity-aware 귀속을 계산한다. 후보 목록을 정렬해 전달하므로
결과가 "어느 kinase가 물어봤는지"에 의존하지 않는다 — 기존 `deconvolve_shared_ptm`은 호출하는
kinase마다 `[canonical] + others` 순서로 불려서 중복 열의 tie-break가 호출자에 따라 달라졌다.

`compute_weighted_kinase_scores`의 각 substrate에 `resolution` 라벨이 붙는다.

| 라벨 | 의미 |
|---|---|
| `exclusive` | 경쟁 kinase 없음 (기존 contribution 1.0) |
| `resolved` | 경쟁자와 분리 가능, ratio를 그대로 읽어도 됨 |
| `unresolved_shared` | 그룹 몫만 추정 가능, `ambiguity_group_members`와 `group_ratio` 동반 |
| `unsupported` | 비음수 조합이 시계열을 설명 못 함, 사유 동반 |

kinase별로 `tmm_identifiability` 요약 블록(`n_resolved` / `n_unresolved_shared` / `n_unsupported`)도
함께 저장된다. weighted sum, contribution ratio, kinase ranking은 모두 종전 경로를 유지한다.

**동일성 증명.** `scripts/verify_tmm_identifiability_additive.py`가 변경 전 모듈 스냅샷을 git에서
꺼내 현재 모듈과 나란히 실행하고, 새로 추가된 키를 제외한 모든 기존 필드를 비교한다. 오더
36·48·47·28에서 **불일치 0건**이다.

실제 라벨 분포는 아래와 같다.

| 오더 | T | exclusive | resolved | unresolved_shared | unsupported |
|---|---|---|---|---|---|
| 36 (KRIBB, 6~48h) | 4 | 42 | 163 | 2,581 | 3,275 |
| 48 (Cu-Amyloid, 0.5~24h) | 5 | 36 | 45 | 634 | 273 |
| 47 (WithoutCu, 0.5~24h) | 5 | 3 | 31 | 427 | 38 |
| 28 (Irisin, 2~90min) | 9 | 39 | 37 | 26 | 57 |

시간 척도 가설이 여기서 다시 확인된다. 분 단위 9시점인 오더 28은 문헌 prior의 척도와 맞아
`exclusive + resolved`가 76/159(47.8%)인데, 시간 단위 4시점인 오더 36은 205/6,061(3.4%)에
불과하다. **prior의 시간 척도와 실험 설계의 시간 척도가 어긋나면 kinase 귀속이 붕괴한다**는 것이
동일 코드·다른 데이터로 재현된 셈이다.

## 한계

정직하게 기록해 둘 것들.

- 오더 33과 45의 저장된 condition 목록은 시간순이 아니다(`['24h','3h','6h']`). 단위 인식 정렬이
  들어오기 전의 레거시 산물이고 현재 코드는 `['3h','6h','24h']`로 올바르게 정렬한다. 두 오더의
  진단은 그 뒤틀린 시간축을 물려받는다. 다만 정렬이 올바른 오더 36·47·48에서도 결론은 같다.
- `ε = 0.10·||y||`는 가정이다. replicate 수준 분산에서 site별 `ε`를 추정하면 개선된다. 단, 중복 열과
  rank 결과는 `ε`와 무관하다.
- Insulin 오더(T=6)는 `kinase_activity_heatmap`이 아직 저장되지 않아 제외됐다. 저장되면 시점 수에
  따른 식별성 변화를 보는 사례로 추가한다.
- kinase 모듈은 저장된 substrate 목록에서 재구성했다. 목록이 잘린 kinase 수는 6개 오더 모두 0이므로
  재구성 아티팩트는 아니다.

## 논문에 대한 의미

Chapter 1의 전제는 실체가 있다. 예상보다 강한 형태로 있다. 문제는 "조건이 나쁘다"가 아니라
"설계행렬에 중복 열이 있어 해집합이 점이 아니다"이므로, 필요한 것은 더 나은 적합이 아니라 **무엇이
식별 가능한지에 대한 규정**이다.

이 진단이 직접 뒷받침하는 기여는 세 가지다.

1. **비식별 인증서.** site별로 계산 가능한 판정(rank, σ_min, leave-one-out ΔRSS)으로 점추정 대신
   ambiguity set을 보고한다. 지금 89.0%의 site에서 top-1이 자기 ambiguity set 안에 있다는 사실이
   이 출력 형식이 필요한 이유의 실증이다.
2. **prior와 증거의 분리.** top-1의 92.5%가 prior 유래 컬럼에서 나온다. prior를 basis에 직접 넣는
   설계는 사후 평가가 같은 prior DB를 라벨로 쓰는 순환성과 맞물린다. anchor 기반 부분 supervision을
   명시적으로 정식화하면 이 순환을 끊을 수 있다.
3. **결측 기제의 모형화.** 0 대입이 평가 가능한 site의 10.1%에서 승자를 바꾼다. 결측을 잡음이 아니라
   측정 과정의 일부로 모형화해야 하는 이유가 여기서 정량화된다(Chapter 2).

즉시 가능한 공학적 개선도 함께 나온다. 동일한 profile 컬럼을 공유하는 후보들 사이에서는 분해를
시도하지 않고 묶어서 ambiguity set으로 보고하는 것, 그리고 모든 계수가 0으로 붕괴할 때 균등 ratio를
측정처럼 보고하지 않는 것이다.

후자는 2026-08-21에 `ptm_shared/tmm_attribution_guard.py`의 정책 계층으로 구현되었다.
**기본값은 `off`이며 배포 수치를 바꾸지 않는다**(오더 36·48·47·28에서 기존 필드 불일치 0건).
`strict`를 켜면 발표되는 개별 kinase 기여의 47.99%가 보류되고 kinase 163개 중 74개가 공유
증거의 과반을 잃는다. 정량은 `docs/chapter2_audit_protocol_v1.md` §5.3.

## 재현

```bash
docker exec -i ptm-api-server env PYTHONPATH=/app:/opt python - \
    --order-ids 48,47,45,36,33,28 --bootstrap 32 \
    < scripts/diagnose_tmm_identifiability.py
```

산출물은 `data/outputs/_diagnostics/tmm_identifiability/`에 오더별 JSON과 `_pooled_summary.json`으로
기록된다. **이 경로는 gitignore 대상이므로 아카이브가 아니다** — 동결 fixture는
`workers/tests/fixtures/tmm_audit_v1/`이다.

테스트는 다음으로 돌린다.

```bash
docker exec -w /app ptm-worker-preprocessing \
  env PYTHONPATH=/app:/opt python -m pytest tests/test_tmm_identifiability.py -q
```

2026-08-22부터 `workers/Dockerfile`이 dev extra(`pytest`)를 함께 설치하므로 위 명령은 새로
빌드한 컨테이너에서 임시 설치 없이 동작한다. 그 전까지는 매번 임시 설치가 필요했고 컨테이너
재생성 시 사라졌다. 경위와 왜 이것이 연구 사안인지는 `docs/chapter2_audit_protocol_v1.md` §6.1.
