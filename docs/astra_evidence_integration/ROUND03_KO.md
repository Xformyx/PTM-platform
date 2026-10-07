# 회차 03 — 유효 관측 곡선 선택과 표시

2026-10-07. 기준 HEAD `21e136d28957a4c63ee6c66daa2d83cbbf11c528`, 작업 브랜치 `feature/round03-observed-curves`. 시작 시 tracked 변경은 없었고, untracked `codex-inputs/`는 보존했다. 적용할 AGENTS.md는 발견되지 않았다. 회차 01의 로컬 완료 / 운영 미확인 상태를 이어받았다.

## 변경 파일과 기존 자산

| 파일 | 변경 / 재사용 |
|---|---|
| `ptm_shared/astra_figures.py` | 기존 `figure_packet()` / `curves()`와 kinase·protein 호출을 유지. `curve_series()`로 표시 대상과 추적 표를 구성. `ContrastEstimator.metadata()` / `same_time()`으로 기존 canonical arm·reference·pairing·시간 확인. `heatmap_grid()`는 변경하지 않음. |
| `ptm_shared/feature_identity.py` | 기존 `project_reader_display_identity()` / `_text()`에 명시적인 kinase candidate·protein abundance 표시 unit 추가. 기존 precursor 표시는 그대로 유지. candidate gene/resolution/kinase taxon/accession과 protein gene/group을 소비. 기질 taxon을 enzyme taxon으로 채우지 않음. |
| `ptm_shared/astra_package.py` | renderer가 사용하는 `feature_identity.py`를 기존 portable CODE_FILES에 포함. `figure_packet(scientific,directory,design)` 호출은 그대로 유지. |
| `ptm_shared/tests/test_astra_curves.py` | 결측·단일 점·중간 결측·동명 entity·선택 제한·protein·중복 관측 회귀 검사. |
| `scripts/validate_astra_curve_selection.py` | 기존 ZIP 표와 회차 02 renderer로 before/after 그림만 생성. 원본 값·NA·시간·source fields, 실제 SVG marker/label, 기존 그림 보존 검사. |

선정 정책 `finite_observation_count_desc_stable_series_id_12.v1`: 유효 수치와 유효 시간이 함께 있는 관측을 1개 이상 가진 series만 대상으로, 관측 수 내림차순 후 entity/arm/reference/pairing ID 오름차순으로 최대 12개를 표시한다. coverage threshold, kinase 이름, 연구 질문, insulin 기대 경로는 선정에 사용하지 않는다. 같은 점수 곡선이 겹쳐도 임의 offset을 넣지 않는다.

`*_selection.csv`는 모든 해당 track series의 ID↔label, 유효 관측/시점 수, coverage 통과 관측 수, 선택 순위·이유를 보존한다. 제외 이유는 `no_finite_value_at_finite_time` 또는 `display_limit_12`이다. `*_points.csv`는 선택된 series의 모든 원 행과 `plot_series_key`, `display_label`, `plotted_point`를 보존한다. 원본 전체 source CSV는 유지한다. 유효성은 선정에만 사용하고 plot에는 NA를 포함한 배열을 그대로 전달한다.

## 사용 자료와 수정 전후

원본: `/Users/josephk/Downloads/astra_analysis_package_g1-da89accad9bd4319868ecc868dedf685.zip`

run_id: `g1-da89accad9bd4319868ecc868dedf685`

SHA-256: `5bd457114a356a32b50b2ac259d7ea77579f4b16369f70312fff1d2dc8a219fd`

기존 g1 scientific table로 그림만 별도 생성했다. 새 analysis run / 재정량 / source 조회 / ZIP 수정은 수행하지 않았다.

| 실제 g1 지표 | Kinase curated_A | Protein |
|---|---:|---:|
| 전체 series | 336 | 9,525 |
| 전체 유효 series | 7 | 9,406 |
| 전체 유효 관측 | 41 | 56,217 |
| 수정 전 선택 series | 12 | 12 |
| 수정 전 선택 중 유효 series / 관측 | 0 / 0 | 12 / 72 |
| 수정 후 선택 중 유효 series / 관측 | 7 / 41 | 12 / 72 |
| 선택 행에 보존된 NA | 1 | 0 |

모든 선택 kinase 관측은 기존 `coverage_adequate=False`이다. 그림은 **exploratory substrate footprint**로 표시하며 kinase 활성 확정이나 calibrated call을 뜻하지 않는다. legend의 n은 finite observation 수이다.

| 표시명 | 원 candidate_id | 유효 시점 수 | 선정 이유 |
|---|---|---:|---|
| Mapk1 | candidate_487c9714f920cddb6648 | 6 | 유효 관측 수 6, 안정 ID 동률 정렬 |
| ERK1_2 family | candidate_51c41ec6545e8a057a74 | 6 | 동일 |
| Aurkb | candidate_9476e2c09b3e80962dd6 | 6 | 동일 |
| Dyrk1a | candidate_a21fbd516bdf84cb1bc3 | 6 | 동일 |
| Mapk14 | candidate_bb45a2f8a1ce2e861f74 | 6 | 동일 |
| Pak2 | candidate_d09193e9b8bc1dcb86a0 | 6 | 동일 |
| Mapk3 | candidate_e0d8bfcbe04f2d495473 | 5 | 유효 관측 수 5, 표시 한도 이내 |

Mapk3의 60분은 NA 그대로이며, 30→180분을 선으로 잇지 않는다. 180분 관측은 분리된 점으로 표시된다. 모든 선택 series의 시간·값·NA 및 원본 필드를 exact equality로 확인했다. Protein의 선택 12개는 기존과 같고 label만 gene/group 기준으로 읽을 수 있게 바뀌었다.

로컬 산출물은 저장소 기준 `codex-inputs/round03-20261007/` 아래에 있다.

- [수정 전 kinase SVG](../../codex-inputs/round03-20261007/final/before/figures/kinase_footprints.svg), [수정 후 kinase SVG](../../codex-inputs/round03-20261007/final/after/figures/kinase_footprints.svg)
- [수정 전 protein SVG](../../codex-inputs/round03-20261007/final/before/figures/protein_trajectories.svg), [수정 후 protein SVG](../../codex-inputs/round03-20261007/final/after/figures/protein_trajectories.svg)
- [선정·제외·ID↔label](../../codex-inputs/round03-20261007/final/after/figures/kinase_footprints_selection.csv), [그린 점과 NA](../../codex-inputs/round03-20261007/final/after/figures/kinase_footprints_points.csv)
- [직접 확인한 최종 kinase PNG](../../codex-inputs/round03-20261007/png-final/kinase_footprints.png), [최종 protein PNG](../../codex-inputs/round03-20261007/png-final/protein_trajectories.png)
- [단일 점·중간 결측·동명 entity fixture](../../codex-inputs/round03-20261007/png-fixture/kinase_footprints.png), [전체 결측 fixture](../../codex-inputs/round03-20261007/png-all-missing/kinase_footprints.png)

이 로컬 자료는 원본 연구 자료와 함께 untracked로 보존한다. 검증 수치·선택 ID는 추적 파일 `ROUND03_RESULTS.json`에도 저장했다.

## 검증 결과

```sh
env MPLCONFIGDIR=/tmp/ptm-round03-matplotlib /tmp/ptm-science-v5-venv/bin/python -m pytest \
  ptm_shared/tests/test_astra_curves.py \
  ptm_shared/tests/test_astra_figures.py \
  ptm_shared/tests/test_reader_display_identity.py -q
```

**16 passed (2.88 s)**. 회차 02의 실제 numeric time 정렬, 서로 다른 arm/reference, ID↔label, 중복 cell 거부 검사 5개를 포함한다. 이번 curve 검사는 finite filter 후 12개 제한, 안정 동률 정렬, 입력 행 shuffle, 실제 matplotlib path의 gap 분리, 0인 단일 관측, 전체 NA/빈 표의 안내 및 legend 부재, 동명·다른 taxon/entity, family label, protein reference 분리, legacy precursor label 보존을 확인했다.

```sh
env MPLCONFIGDIR=/tmp/ptm-round03-matplotlib PYTHONPATH=. \
  /tmp/ptm-science-v5-venv/bin/python scripts/validate_astra_curve_selection.py \
  --archive /Users/josephk/Downloads/astra_analysis_package_g1-da89accad9bd4319868ecc868dedf685.zip \
  --output codex-inputs/round03-20261007/final
```

**passed**. 실제 저장 SVG marker는 kinase 41개, protein 72개로 source와 일치한다. 9개 전체 source CSV, 곡선 외 7개 SVG, 두 heatmap ID↔label 표는 회차 02 renderer 출력과 **byte-identical**이다. 따라서 heatmap 50행 선정·cell 값·NA·열 순서도 유지된다. 원본 ZIP hash도 불변이다. 초기 검증 스크립트의 SVG comment 공백 비교 실패를 `.strip()`으로 수정한 후 재실행했다.

기존 `scripts/validate_astra_figures.py`와 로컬 Chrome으로 저장 SVG를 PNG로 렌더링했다. 최종 9개 SVG browser error 0. 수정 전후 kinase/protein 및 두 fixture PNG를 직접 열어 label 잘림·겹침, 한 점 표시, 결측에서 선 단절, 전체 결측 안내를 확인했다. 동일 값의 서로 다른 곡선이 겹치는 것은 원 관측이며, 이를 분리하려고 수치를 바꾸지 않았다.

## 남은 제한

이번 완료 범위는 로컬 그림 생성·표시 검증이다. 운영 배포와 새 분석 실행은 하지 않았다. 기존 정량·coverage·kinase 판정·localization·과학적 불확실성은 그대로다. 결과가 보이게 된 것을 kinase 성능 향상이나 독립 검증으로 해석하지 않는다. 회차 04 이후는 진행하지 않았다.
