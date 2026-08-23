# Quick Analysis Mode Contract v1

작성일: 2026-08-23 (GMT+9)
상태: **선언 후 구현 (2026-08-23).**
사전등록 상태: **탐색적(exploratory).** primary 승격 금지.

구현 대상: 오더 생성 시 `analysis_options.quick_analysis=true` 로
PR/PG 입력을 결정적으로 줄여 **같은 정량·Wave·TMM·RAG 경로**를 빠르게 돈다.

## 1. 목적과 해석 경계

목적은 알고리즘 변경을 같은 코드 경로에서 빨리 확인하는 것이다.
입력을 줄일 뿐, 정규화·Log2FC·occupancy·TMM 산식을 바꾸지 않는다.

주장 금지:

- Quick 결과를 Full 코호트의 효과크기·kinase 순위로 읽지 않는다.
- Quick에서 나온 Wave/TMM/heatmap을 primary 논문 수치로 쓰지 않는다.
- “더 빠른 분석이 더 나은 kinase 예측”으로 서술하지 않는다.
- Downsampling(`analysis_options.mode`)과 혼동하지 않는다. 그것은
  biological enrichment의 non-PTM 행만 줄인다. Quick는 정량 이전 입력이다.

## 2. 무엇을 보존하는가 (알고리즘 본령)

| 보존 | 이유 |
|---|---|
| 모든 sample / 시점 / replicate 열 | 시간 축이 없으면 Wave·TMM·directionality가 성립하지 않는다 |
| 대상 PTM UniMod precursor | `filter_target_ptms`와 같은 우주 |
| 선택된 modified peptide의 unmodified pair | Track 1 occupancy pairing. 없으면 occupancy는 mask |
| 선택된 precursor가 가리키는 PG 행 | Track 2 protein-normalized 비율의 분모 |
| 단백질당 상한 | 한 hub 단백질이 예산을 먹지 않게. 다중 site 구조를 남긴다 |
| 검출률 우선 | 결측이 많은 site는 시간 형태를 연습시키지 못한다 |

## 3. 무엇을 버리는가

대상 UniMod가 없는 precursor, 선택되지 않은 단백질의 PG 행,
검출률이 낮은 PTM precursor(예산 초과분).

Full 코호트의 coverage 통계, understudied tail, 집단 kinase activity는
이 모드의 대상이 아니다.

## 4. 동결 상수

결과를 보기 전에 선언한다. 측정 후 바꾸면 이전 Quick 오더와 비교가 무효다.

```text
QUICK_MAX_PTM_PRECURSORS = 400
QUICK_PER_PROTEIN_CAP    = 4
QUICK_MIN_DETECTION_FRAC = 0.50
```

| 상수 | 값 | 이유 |
|---|---|---|
| `QUICK_MAX_PTM_PRECURSORS` | 400 | Wave clustering 하한(10)과 TMM 후보를 남기면서 RAG/LLM 입력을 제한. 과학적 임계가 아님 |
| `QUICK_PER_PROTEIN_CAP` | 4 | 다중 site divergence를 연습할 최소 여유. hub 독점 방지 |
| `QUICK_MIN_DETECTION_FRAC` | 0.50 | 샘플 열의 절반 이상에서 intensity > 0. 시간 형태가 있는 site를 우선 |

적격 site가 예산보다 적으면 검출률 문을 열고 남은 PTM precursor를 같은 정렬로 채운다.
대상 PTM이 0이면 서브셋을 만들지 않고 실패한다.

## 4.1 사용자 오버라이드 (Custom Quick)

오더 생성 UI에서 아래 항목만 바꿀 수 있다. **기본값은 §4 동결 상수**다.
범위 밖 값은 clamp 하고, 적용된 값을 manifest에 기록한다.
시점·replicate 열은 오버라이드 대상이 아니다.

```text
quick_keep_all_ptm              default false
quick_max_ptm_precursors        default 400   clamp [10, 5000]
quick_per_protein_cap           default 4     clamp [0, 50]   (0 = 상한 없음)
quick_min_detection_frac        default 0.50  clamp [0.0, 1.0]
quick_keep_unmodified_pairs     default true
quick_include_non_ptm           default false
quick_max_non_ptm_proteins      default 200   clamp [0, 5000]
```

| 항목 | 하는 일 | 끄면 / 0이면 |
|---|---|---|
| Keep all target PTM | 대상 UniMod precursor를 예산 없이 남긴다. cap은 그대로 | 예산을 쓴다 |
| Max PTM precursors | PTM 우주에서 가져올 행 수 | Keep all이 켜지면 무시 |
| Per-protein cap | hub 독점 방지. 0이면 단백질당 제한 없음 | — |
| Min detection | 1차 적격 문턱 | 0이면 모든 PTM이 1차 적격 |
| Keep unmodified pairs | 선택 PTM의 unmodified pair (occupancy) | occupancy는 mask |
| Include non-PTM proteins | PTM에 안 묶인 PG를 추가로 남긴다 (protein-level / network 연습) | non-PTM PG는 버림 |
| Max non-PTM proteins | 위 추가 PG 수. 검출률 높은 순 | Include가 꺼지면 무시 |

non-PTM은 **PG 행만** 추가한다. 그 단백질의 unmodified precursor 전체를 PR에 넣지 않는다.
네트워크 맥락용이지 정량 우주를 되돌리는 것이 아니다.

`keep_all_ptm=true` 이어도 대상 UniMod가 아닌 precursor는 기본으로 버린다
(unmodified pair와 선택한 non-PTM PG 제외).

## 5. 선택 알고리즘 (결정적)

1. PR에서 샘플 열 = `*.mzML` (analyzer와 동일). 없으면 메타데이터 제외 수치 열.
2. `Modified.Sequence`가 대상 UniMod(`phospho`→21, `ubi`→121)를 포함하는 행이 PTM 우주.
3. 행별 `detection_frac` = (finite이고 0보다 큰 샘플 열 수) / 샘플 열 수.
4. 1차 적격: `detection_frac ≥ min_detection_frac` (§4 기본 0.50, Custom이면 §4.1).
5. 정렬: `(-detection_frac, Protein.Group, Precursor.Id)`.
6. 단백질당 `per_protein_cap`까지 탐욕 선택 (`0`이면 상한 없음). 예산은 `max_ptm_precursors` 또는 Keep all.
7. 예산이 남고 적격이 부족하면 문턱 미달 PTM도 같은 정렬로 채운다.
8. `keep_unmodified_pairs`가 켜져 있으면 같은 `Protein.Group` + `Stripped.Sequence` unmodified pair를 추가.
9. PG는 선택된 PR의 `Protein.Group`만 남긴다. `include_non_ptm`이면 남은 PG를 검출률 순으로 추가. 모든 샘플 열은 그대로.

## 6. 정규화 한계 (필수 기록)

`PTMQuantificationAnalyzer`는 로드한 행렬에서 sample median을 다시 계산한다.
Quick 행렬은 행이 적으므로 **median factor가 Full과 다르다.**
같은 site라도 Quick Log2FC는 Full과 수치 비교할 수 없다.
이 한계를 `quick_analysis_manifest.json`에 `median_normalization_not_comparable_to_full=true`로 남긴다.

## 7. Provenance

오더 출력에 `quick_analysis_manifest.json`을 쓴다. 필수 필드:

```text
quick_analysis                         = true
contract                               = docs/quick_analysis_contract_v1.md
preregistration                        = exploratory
max_ptm_precursors / per_protein_cap / min_detection_frac
keep_all_ptm / keep_unmodified_pairs / include_non_ptm / max_non_ptm_proteins
overrides_applied (어느 항목이 기본값에서 벗어났는지)
ptm_mode, unimod_id
pr_rows_before / pr_rows_after
pg_rows_before / pg_rows_after
ptm_precursors_selected
unmodified_pairs_added
sample_columns_kept
median_normalization_not_comparable_to_full = true
primary_claim_allowed                  = false
```

UI는 오더를 Quick / Exploratory로 표시한다.

## 8. 기존 downsampling과의 관계

| | Quick Analysis | `analysis_options.mode` downsampling |
|---|---|---|
| 적용 시점 | 정량 전 PR/PG | biological enrichment의 non-PTM 행 |
| 시간 축 | 유지 | 해당 없음 |
| 정량 산식 | 동일, 입력 N만 감소 | 정량 결과에 손대지 않음 |
