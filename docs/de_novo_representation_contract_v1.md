# De novo PTM Representation Contract v1

작성일: 2026-08-23 (GMT+9)  
상태: **선언 — 구현 전 확정. 결과 열람 후 임계 변경 금지.**  
사전등록 상태: **탐색적(exploratory).** 기존 오더의 pseudo-Log2FC 산출을 본 뒤에
표시·순위 규칙을 고정한다. primary 승격은 영구 금지.

## 1. 목적과 해석 경계

Control에서 검출되지 않은 modified peptide(de novo)의 결측은 강도 0이 아니라
**검출한계(LOD) 미만**이다. 여기에 고정 pseudocount를 넣고 Log2FC를 계산하면
(예: 29.1) 정확한 fold change가 아니라 검출 한계 대비  artificially 큰 수가 된다.

이 계약은 de novo를 다음 세 값으로만 양적으로 표현한다.

1. 검출 반복 수 (condition별 `detected/expected`)
2. 처리군 protein-normalized abundance 및 median-normalized log2 intensity
3. LOD 대비 보수적 최소 증가량 (lower-bound, 반드시 `≥`)

> Conventional Log2FC는 de novo에 대해 **NA**다. 이 값은 kinase 활성, occupancy,
> 또는 “기존 정량 site보다 더 강한 조절”을 의미하지 않는다.

주장 금지:

- LOD-relative induction으로 정확한 fold change를 주장하지 않는다.
- de novo 검출이 kinase 귀속 또는 직접 phosphorylation의 증거가 아니다.
- 재현성 등급 High가 생물학적 중요도 순위를 증명하지 않는다.
- Dynamics v1 알고리즘 자체를 교체했다는 주장을 하지 않는다. 바꾸는 것은
  **우선순위 점수에 pseudo-Log2FC를 넣는 경로**다.

## 2. 분류

| 분류 | 정의 |
|---|---|
| De novo | Control 전 replicate에서 해당 modified precursor가 미검출 (`0/n`) |
| 기존 정량 PTM | Control에서 1개 이상 replicate가 검출되어 통상적 protein-normalized Log2FC가 정의됨 |

Control `1/n`은 de novo가 아니라 **Ambiguous**다. “거의 없다”를 0으로 바꾸지 않는다.

## 3. LOD

권장·동결 방법: **각 control run에서 검출된 target-PTM precursor intensity
(`PTM_Intensity`, median-normalized)의 5th percentile.** 실험 LOD는 run별 LOD의
median이다.

```text
LOD_run(s) = percentile_5( { I^M_{p,s} : p detected in control run s } )
LOD       = median_s( LOD_run(s) )
```

| 항목 | 동결 값 | 선언 |
|---|---|---|
| `LOD_PERCENTILE` | `5.0` | 권고 구간 1–5 percentile의 보수 끝. 2026-08-23 선언 |
| 단위 | median-normalized `PTM_Intensity` | 처리군 평균 intensity와 동일 공간 |
| 금지 | 고정 pseudocount (`1`, `1e-6`, `min*0.005`)를 LOD 또는 fold-change 분모로 사용 | §1 |

더 엄격한 local LOD(동일 단백질·유사 intensity 구간)는 이 버전에서 구현하지 않는다.
도입하려면 이 문서에 먼저 선언한다.

Control run에 검출된 target PTM이 없어 LOD를 못 정하면 induction을 계산하지 않고
`lod_unavailable`로 기록한다. 임의 상수를 넣지 않는다.

## 4. LOD-relative lower-bound induction

처리군 시점 \(t\)에서 검출된 replicate의 평균 median-normalized intensity를
\(\bar{I}_t\)라 한다. 미검출 replicate는 0으로 넣지 않는다.

```text
LOD-relative log2 induction_t = log2( Ī_t / LOD )
```

Baseline은 LOD보다 작으므로 실제 증가는 이 값보다 크다. 표시는 항상 부등호다.

```text
≥4.2 log2
≥18-fold above control detection limit
```

이 값은 정확한 fold change가 아니라 **보수적 최소 증가량**이다.
Conventional Log2FC는 `NA`로 두고, 기존 TSV의 감사 열 `Log2FC`는 지우지 않되
`Conventional_Log2FC_NA=true`인 행은 순위·서술에 쓰지 않는다.

## 5. Replicate detection

`expected_n(condition)`은 해당 조건에서 한 개 이상 target PTM이 검출된
unique sample 수다(실험 전체). site의 `detected_n`은 그 site가 그 조건에서
검출된 sample 수다.

| 검출 | 해석 |
|---|---|
| `n/n` (예: 3/3) | 높은 재현성 |
| `≥2` 이면서 미완 (예: 2/3) | 중간 재현성 |
| `1/n` | 탐색적 |
| `0/n` | 미검출 |

표시 순서는 시간 순이다.

```text
Control 0/3 → 1 min 1/3 → 5 min 3/3 → 15 min 2/3 → 30 min 3/3 → 60 min 0/3
```

## 6. 재현성 등급

n은 실험의 control/treatment expected replicate 수다. 아래는 n=3을 기준으로
썼지만 구현은 `detected == expected`를 완전 검출, `detected >= 2`를 다수 검출로
일반화한다. n=1이면 완전 검출과 다수 검출이 같다.

| 등급 | 기준 |
|---|---|
| High | Control `0/n`, 처리군 한 시점 이상 완전 검출, 인접 시점 다수 검출(`≥2` 또는 n≤2이면 완전) |
| Moderate | Control `0/n`, 처리군 한 시점 이상 다수 검출. 완전 검출이 있어도 인접 다수가 없으면 Moderate |
| Low | Control `0/n`, 처리군에서 `1/n`만 검출 |
| Ambiguous | Control `1/n` 이상이거나 site-localization/단백질 귀속이 불명확 |
| High — shared peptide | High 기준을 충족하지만 protein group이 다중 accession(`;` 구분) |

INSR/IGF1R 공유 activation-loop peptide처럼 단백질 귀속이 불명확하면 반복 검출이
좋아도 High로 올리지 않고 `high_shared`로 따로 표시한다.

## 7. Peak 결정

De novo peak는 pseudocount Log2FC 최대점이 아니다. 순서:

1. 완전 검출 시점만 후보
2. 그 안에서 protein-normalized abundance(`PTM_Relative_Abundance` 평균)가 가장 높은 시점
3. 동률이면 replicate CV가 낮은 시점
4. 완전 검출이 없으면 다수 검출 시점을 후보로 하고 `provisional peak`로 표시
5. 다수 검출 시점의 abundance가 완전 검출 peak보다 높아도 공식 peak는 완전 검출을 유지하고,
   더 높은 2/n 시점은 `provisional_higher_partial`로만 기록한다

Onset: 검출 `≥1`인 첫 처리 시점.  
Reliable onset: 첫 완전 검출 시점. 없으면 첫 다수 검출 시점.

## 8. 우선순위 점수 — Dynamics v1 amplification loop 차단

Dynamics v1의 문제는 알고리즘이 아니라, PTM priority에 **pseudo-Log2FC**가
들어가는 것이다. 선택된 de novo가 pathway·kinase·문헌 서술로 들어가고 다시
대표 heatmap에 포함되는 증폭이 생긴다.

| 대상 | 규칙 |
|---|---|
| 기존 정량 PTM | `ranking_score = \|PTM_Relative_Log2FC\|` |
| De novo | `ranking_score = w(confidence) × (detected/expected at peak) × min(LOD-relative log2, 4.0)` |
| 구데이터 fallback | LOD가 없으면 de novo 점수는 `1.5 × w(confidence)`. **\|pseudo-Log2FC\|를 쓰지 않는다** |

| 상수 | 값 | 선언 |
|---|---|---|
| `LOD_INDUCTION_RANK_CAP` | `4.0` | de novo induction만으로 \|Log2FC\|=4 조절 site를 초과하지 못하게 하는 상한. 2026-08-23 |
| `w(high)` | `1.00` | 2026-08-23 |
| `w(high_shared)` | `0.70` | 공유 peptide 감쇠. 2026-08-23 |
| `w(moderate)` | `0.55` | 2026-08-23 |
| `w(low)` | `0.20` | 2026-08-23 |
| `w(ambiguous)` | `0.10` | 2026-08-23 |
| Kinase heatmap de novo 가중 | High 0.80 / Moderate 0.50 / Low 0.20 / Ambiguous 0.15 / High-shared 0.50 | 기존 1.5 boost 폐기. 2026-08-23 |
| Heatmap de novo 값 | 해당 시점 LOD-relative log2, cap 4.0 | raw pseudo-Log2FC 금지 |

선택 모드:

| 모드 | 동작 |
|---|---|
| `top_n` | 모든 site를 `ranking_score`로 정렬해 N개. de novo 전량 자동 포함 금지 |
| `de_novo_regulated` | regulated ∪ (de novo 중 High / High-shared / Moderate). Low·Ambiguous는 기본 서술 우주에서 제외 |
| `de_novo` | 사용자가 명시적으로 de novo만 요청한 경우 전 등급 포함 |
| `regulated` / `minor` / `all` | 기존 정의 유지. 순위만 `ranking_score` |

이 점수는 서술 우주를 고르는 내부 rank다. 생물학적 중요도 또는 kinase
예측 품질이 아니다.

## 9. 표시 계약

```text
IRS1 S522
Class: De novo — High confidence
Control detection: 0/3
Treatment detection: 1/3 → 3/3 → 2/3 → 3/3 → 0/3 → 0/3
Onset: 1 min
Reliable onset: 5 min
Peak: 5–30 min response window
Peak normalized abundance: 15 min
LOD-relative induction: ≥X.X log2
Conventional Log2FC: NA
```

LLM·리포트는 de novo에 대해 `Log2FC=29.1` 또는 `>30,000-fold`를 쓰지 않는다.
`Log2FC=NA; LOD-relative induction ≥4.2`만 허용한다.

## 10. 그래프

| 계열 | 축 |
|---|---|
| 기존 정량 PTM | protein-normalized Log2FC |
| De novo | 혼합 보기: LOD-relative induction (lower bound). de novo-only 보기: normalized log2 intensity, LOD 수평 점선 |
| 점 크기 | 검출 replicate 수 |
| 점 테두리 | de novo 여부 |
| 하단 막대 | `0/3`, `3/3`, `2/3` 검출 패턴 |

같은 fold-change 축에 de novo의 pseudo-Log2FC를 놓지 않는다.
Context heatmap은 de novo 셀을 기존 Log2FC colormap 스케일에서 제외하고
`≥x.x` 또는 검출 분수로 주석한다.

## 11. 결정성

- dtype: float64
- percentile: NumPy `np.percentile` (linear, default)
- log2: NumPy `np.log2`
- 시간 정렬: 조건명에서 추출한 분 단위. 비시간 조건은 이름 순
- seed 없음
