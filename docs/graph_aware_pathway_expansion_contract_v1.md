# Graph-Aware Pathway Expansion Contract v1

작성일: 2026-08-23 (GMT+9)  
상태: **선언 후 구현 (2026-08-23).** 사전등록은 탐색적 유지.
사전등록 상태: **탐색적(exploratory).** Insulin Dynamic V1 Figure 1의
`Σ|Log2FC|` 편향을 본 뒤에 규칙을 고정한다. primary 승격 금지.

설계 출처: Graph-aware pathway expansion 개선안 (2026-08). 구체 가중·threshold는
여러 perturbation dataset에서 교차검증 전이다. Insulin canonical hit로
“개선”을 주장하지 않는다.

## 1. 목적과 해석 경계

Pathway ranking은 **직접 PTM 근거**만 1차로 쓴다. Protein abundance와
STRING/BioGRID 1-hop은 독립 보조 열이다. 한 점수로 합치지 않는다.

주장 금지:

- Direct NES를 pathway activation 또는 kinase 활성으로 부르지 않는다.
- STRING support로 pathway를 “발견”했다고 쓰지 않는다.
- Insulin/MAPK/PI3K canonical anchor를 생산 점수 prior로 쓰지 않는다.
- Phosphorylation 증가를 단백질 활성화로 단정하지 않는다.
- De novo LOD-relative를 Direct NES에 넣지 않는다 (방법 A).

## 2. 세 열

| 열 | 근거 | 순위 |
|---|---|---|
| Direct PTM NES + BH-FDR | 해당 pathway에 KEGG/Reactome으로 **직접 소속**된 정량 site/protein | **1차 순위** |
| Protein support | 동일 직접 소속 단백질의 total protein Log2FC | 보조. 60–180분 적응 해석 |
| Network support | STRING/BioGRID 1-hop, degree 정규화 | 보조. FDR·Direct 집합에서 제외 |

합성 `0.75 NES + 0.15 coherence + 0.10 network`는 v1에서 **계산하지 않는다.**

## 3. Site evidence

```text
E(s,t) = M(s,t) × R(s,t) × L(s) × S(s)
```

정량 site만 Direct universe에 들어간다.

| 항 | 정의 | 동결 값 |
|---|---|---|
| M | signed protein-normalized Log2FC | de novo는 M를 정의하지 않음 |
| R | `detected/expected`; CV가 있으면 `R ← R / (1+CV)` | expected 없으면 1.0 |
| L | 귀속 | 단일 protein group 1.0, shared peptide 0.50, localization unverified 0.30 (둘 다이면 0.30) |
| S | 통계 | q < 0.05 → 1.00; q 결측 → 0.70; q ≥ 0.05 → 0.50 |

`L_SHARED = 0.50`, `L_UNVERIFIED = 0.30`, `S_SIG = 1.00`, `S_MISSING = 0.70`,
`S_NS = 0.50` 은 2026-08-23 선언. 측정 후 바꾸면 기존 NES 비교가 무효다.

## 4. De novo — 방법 A

Control 0/n site는 Direct NES universe에서 **제외**한다.

| 표시 | 정의 |
|---|---|
| De novo support | Control 0/n 이고 처리 다수 검출(≥2/n 또는 n≤2이면 완전) |
| High-confidence de novo | `docs/de_novo_representation_contract_v1.md` High 또는 High-shared |

방법 B(LOD-relative cap)는 v1 민감도 열이 아니다.

## 5. Protein contribution cap

```text
E(protein,t) = E(s*,t)   where s* = argmax_s |E(s,t)|
```

한 단백질의 모든 site를 합산하지 않는다. 반응 site 수·concordance·divergence는
해석 층에만 남긴다. `PROTEIN_SITE_CAP = signed_max`.

## 6. 시점별 weighted GSEA / NES

Universe: 해당 시점에 E(protein,t) ≠ 0 인 **정량** 단백질.  
Hit: KEGG 또는 Reactome **직접 소속**. STRING indirect는 hit가 아니다.  
KEGG와 Reactome 이름은 같은 문자열이면 한 pathway로 묶지 않고, 출처를
기록한 채 표시 이름은 그대로 쓴다. 동일 표시명이 양쪽에서 오면 소속을 합친다.

```text
rank proteins by E(protein,t) descending
ES  = weighted Kolmogorov–Smirnov (p=1, |E| 가중)
NES = ES / mean_b |ES_b|
ES_b: 동일 크기 무작위 gene set B회
```

| 상수 | 값 | 선언 |
|---|---|---|
| `GSEA_WEIGHT_P` | `1` | 2026-08-23 |
| `N_PERM` | `500` | 2026-08-23 |
| `PERM_SEED` | `20260823` | 2026-08-23 |
| `MIN_DIRECT_GENES` | `2` | 이하면 NES를 계산하지 않음 |
| `MIN_UNIVERSE` | `15` | 미달이면 NES 생략, Direct sum of E만 감사 열 |

p-value = (1 + #{|ES_b| ≥ |ES|}) / (1 + B). BH-FDR은 한 시점의 검정된
pathway 집합에서 계산한다. 시점마다 따로.

1·5·15·30·60·180분(존재하는 처리 시점)을 **각각** 계산한다. 전 시점 |E|를
한 벡터로 합치지 않는다. 표시용 peak NES는 signed NES가 최대인 시점이다.

## 7. Network support

```text
NetworkSupport(P,t) = α Σ_{i∈direct, j∈1hop\direct} C(ij) × E(i,t) / √(deg(i) deg(j))
```

| 설정 | 값 |
|---|---|
| `STRING_CONF_MIN` | `0.70` |
| `NETWORK_HOPS` | `1` |
| `NETWORK_ALPHA` | `0.15` (권고 0.1–0.2의 중앙) |
| degree | conf ≥ 0.70 인 undirected STRING/BioGRID 그래프 |
| Direct·FDR | j는 hit·FDR 분모에 넣지 않음 |

## 8. 기능 방향과 용어

Phosphorylation 증가 ≠ 활성화. 아래 **소규모 탐색적 표**에만 FunctionalSign을
준다. 표 밖은 0.

| site | sign | 이유 |
|---|---|---|
| MAPK1 T185 / Y187, MAPK3 T202 / Y204 | +1 | ERK activation loop |
| GSK3A S21, GSK3B S9 | −1 | N-terminal inhibitory |
| AKT1 S473 / T308, AKT2 S474 / T309 | +1 | canonical activation |
| RPS6KB1 T389 | +1 | mTOR-site convention |
| IRS1 S522 | 0 | context-dependent. 표에 넣되 부호 없음 |

이 표는 ranking prior가 아니다. 용어에만 쓴다.

| 용어 | 조건 |
|---|---|
| Pathway activated | Direct 유전자 ≥2, 주석 site ≥2, DirectionConsistency ≥ 0.75, peak NES > 0 |
| Pathway inhibited | 동일, peak NES < 0 |
| Pathway modulated | Direct PTM은 있으나 위 조건 미달 |
| Network-associated | Direct 유전자 < 2 이고 Network support만 존재 |

`DIRECTION_CONSISTENCY_MIN = 0.75`, `MIN_ANNOTATED_SITES = 2` (2026-08-23).

## 9. Prior-free coherence

생산 점수에 `PATHWAY_SIGNAL_ORDER` / Insulin anchor를 **넣지 않는다.**
해당 목록은 그림 배치(화살표 순서)와 사후 benchmark에만 쓴다.

```text
Coverage          = n_direct_evidence_proteins / n_pathway_proteins_in_universe
Connectedness     = KEGG edge로 연결된 evidence pair 비율 (undirected)
TemporalOrder     = 방향이 있는 KEGG edge에서 upstream peak ≤ downstream peak 비율
DirectionConsistency = FunctionalSign≠0 site에서 sign(E)×sign(F) > 0 비율
Coherence         = 관측된 성분만의 기하평균
```

결측 성분은 1.0으로 채우지 않는다. Coherence는 보조 열이다.

## 10. Figure 1

제목: **Time-resolved Direct PTM Pathway Enrichment with Independent Protein and Network Support**

- X축: Direct NES (시점별; 요약 막대는 peak signed NES)
- 순위: peak **signed** Direct NES 내림차순, FDR 주석.
  `|NES|` 로 줄 세우면 큰 pathway의 음수 enrichment가 직접 근거 pathway를
  이긴다. 막대는 부호 있는 NES다.
- Protein support · Network support · de novo counts · coherence는 숫자 주석
- 같은 축에 STRING 누적 \|FC\|를 놓지 않는다

## 11. 결정성

dtype float64. permutation `numpy.random.RandomState(20260823)` 시점별로
pathway 순서를 고정한 뒤 동일 seed에서 size별 독립 스트림을 쓰지 않고,
`(timepoint_index, pathway_index)`로 seed를 `20260823 + 1000*t + p` 로
갈라 재현한다. BH는 표준 단조성 보정.
