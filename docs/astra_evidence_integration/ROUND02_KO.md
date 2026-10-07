# 회차 02 — heatmap 시간축 수정

2026-10-07. 회차 01은 로컬 검증 완료(`c3ea822e8447a157e5ecb32bfa0cc8e09f5b9146`)로 유지한다. 그 HEAD에서 `feature/round02-heatmap-time-axis`를 만들었다. 적용되는 AGENTS.md는 없었고, 기존 `astra_figures.py`의 ID 정렬 및 `aggfunc='first'`는 아직 수정되지 않은 상태였다.

## 변경 파일과 기존 함수 재사용

- `ptm_shared/astra_figures.py`: 기존 `figure_packet()`·`save()`·`heat()` 경로를 유지한다. `heatmap_grid()`가 canonical design으로 열 metadata를 만들고 `pivot().reindex(columns=ordered_ids)`를 적용한다. `ContrastEstimator.metadata()`와 `study_design.same_time()`을 재사용하며 정량은 실행하지 않는다.
- `ptm_shared/astra_package.py`: 기존 그림 생성 호출에 이미 가진 `design`만 전달한다.
- `ptm_shared/tests/test_astra_figures.py`: 불규칙·혼합 단위·복수 arm/reference/pairing·동일 시각의 별도 contrast·NA·중복 cell·저장 SVG label 회귀 5건.
- `scripts/validate_astra_heatmap_axis.py`: 기존 ZIP의 표와 검토된 renderer로 수정 전후 그림을 별도 폴더에 생성하고 값/NA/ID/다른 그림의 불변성을 검증한다.

`workers/common/temporal_utils.condition_sort_key()`는 Control을 inf로 보내므로 호출하지 않았다. 새 시간 parser도 만들지 않았다. design의 `time.minutes`를 우선하고, 표의 `time_min` 및 identity가 충돌하면 오류를 반환한다. 조건명이 시간 문자열인 경우의 공백 정리는 label 표시만을 위한 것이며 시간 정렬 입력이 아니다.

Contrast는 arm / 실제 reference / pairing으로 구분하고 각 그룹 안에서 numeric time으로 정렬한다. Detection은 실제 조건 ID를 유지하면서 시간순으로 배치한다. 같은 시간의 다른 조건/contrast를 합치지 않는다. 여러 그룹은 label에 arm·reference·pairing을 명시한다. 동일 entity×column 중복은 값이 같아도 오류이며 첫 행 선택/평균을 수행하지 않는다.

## 사용한 실제 archive

- 파일: `/Users/josephk/Downloads/astra_analysis_package_g1-da89accad9bd4319868ecc868dedf685.zip`
- run_id: `g1-da89accad9bd4319868ecc868dedf685`
- SHA-256: `5bd457114a356a32b50b2ac259d7ea77579f4b16369f70312fff1d2dc8a219fd`
- 이 회차에는 지정된 g1 파일을 사용했다. 회차 01에서 사용한 대체 archive와 구분한다. ZIP에 포함된 renderer가 기준 HEAD의 코드와 byte-identical임을 확인한 뒤 오류를 재현했다. 원본 ZIP hash는 작업 후에도 동일했다.

## 수정 전후 산출물

| 그림 | 수정 전 실제 열 순서 | 수정 후 실제 열 순서 |
|---|---|---|
| PTM contrast | 5 → 1 → 30 → 180 → 15 → 60분 | **1 → 5 → 15 → 30 → 60 → 180분** |
| Detection | Control → 60 → 180 → 5 → 30 → 15 → 1분 | **Control → 1 → 5 → 15 → 30 → 60 → 180분** |

PTM tick label은 `1 min`~`180 min`, detection은 `Control (0 min)` 뒤에 같은 시간 label을 표시한다. PTM에 Control 열을 추가하지 않았다. 원 ID와 label·시간·arm/reference/pairing·열 순서는 각 `<figure>_columns.csv`에 남겼고 `figure_legends.json`에서 연결한다. SVG의 각 label에도 `heatmap-column-N` 식별자를 두어 대응표와 대조했다.

그림은 `codex-inputs/round02-20261007/`에 저장했다.

- PTM: [수정 전 PNG](../../codex-inputs/round02-20261007/png-before/substrate_contrast_heatmap.png) / [수정 후 PNG](../../codex-inputs/round02-20261007/png-after/substrate_contrast_heatmap.png) / [새 SVG](../../codex-inputs/round02-20261007/after/figures/substrate_contrast_heatmap.svg)
- Detection: [수정 전 PNG](../../codex-inputs/round02-20261007/png-before/emerging_detection.png) / [수정 후 PNG](../../codex-inputs/round02-20261007/png-after/emerging_detection.png) / [새 SVG](../../codex-inputs/round02-20261007/after/figures/emerging_detection.svg)
- 복수 arm/reference fixture: [PTM](../../codex-inputs/round02-20261007/png-fixture/substrate_contrast_heatmap.png) / [Detection](../../codex-inputs/round02-20261007/png-fixture/emerging_detection.png)

## 수치·NA·시각 검증

| 비교 모집단 | cell 수 | NA 수 | 결과 |
|---|---:|---:|---|
| 전체 PTM form×contrast grid | 16,944 | 2,234 | 각 원 ID의 값·NA 정확 일치 |
| 표시 PTM 50개 form | 300 | 25 | 행 ID·값·NA 정확 일치 |
| 전체 detection form×condition grid | 19,768 | 0 | 각 원 ID의 값 정확 일치 |
| 표시 detection 50개 form | 350 | 0 | 행 ID·값 정확 일치 |

모든 비교는 tolerance 완화 없이 `check_exact=True`로 확인했다. source CSV 9개와 다른 그림 SVG 7개도 수정 전후 byte-identical이다. 기존 first-50 행 선정, kinase 곡선 선정, 색상/값 범위는 유지했다.

합성 fixture는 입력 행과 design 순서를 섞고 `120 s`, `0.5 h`, `1 d`, `30 s`를 기존 `time_value()`로 canonical 값에 변환한다. 여러 arm/reference와 30분의 서로 다른 세 contrast를 모두 유지하며, 전부 NA인 form도 보존한다. 저장 SVG의 label 순서와 CSV metadata의 label이 일치한다.

`PYTHONPATH=. /tmp/ptm-science-v5-venv/bin/python -m pytest -q ptm_shared/tests/test_astra_figures.py`: **5 passed, 6.29초**. 기존 `scripts/validate_astra_figures.py`로 저장 SVG 6개를 렌더링한 뒤 직접 열어 확인했다. 수정 전후·fixture에서 label 잘림/겹침이 없고, 수정 후 시간순서와 그룹 구분이 읽힌다. browser page error는 0개다. 기계 판독 결과: [ROUND02_RESULTS.json](ROUND02_RESULTS.json).

재현 명령:

```sh
PYTHONPATH=. /tmp/ptm-science-v5-venv/bin/python scripts/validate_astra_heatmap_axis.py \
  --archive /Users/josephk/Downloads/astra_analysis_package_g1-da89accad9bd4319868ecc868dedf685.zip \
  --output <새로운-출력-디렉터리> \
  --baseline-commit c3ea822e8447a157e5ecb32bfa0cc8e09f5b9146
```

기존 계산 표만 읽었으며 전체 전처리·reference 수집·정량 재실행은 없었다. 결과 ZIP을 덮어쓰거나 과거 run provenance를 변경하지 않았다. 출력은 그림 검토용 sidecar이며 새 분석 package/run으로 표시하지 않는다. 회차 03 이후와 운영 배포는 이 회차의 범위에 포함하지 않았다.
