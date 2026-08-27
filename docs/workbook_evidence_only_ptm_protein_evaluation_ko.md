# Workbook-Evidence-Only PTM–Protein Reference Extension Evaluation

## 목적과 경계

사용자가 제공한 benchmark workbook에는 `Protein_Effectors`, `Cross_Layer_Relations`, `Mechanism_Chains`, `Counterexamples` optional sheet가 없었다. 따라서 알고리즘 결과를 truth로 되돌려 쓰지 않고, workbook의 `Kinase_Reference.Direct_or_preferred_outputs`에 이미 기록된 curated kinase-output 정보만 별도 runner-only optional reference로 구조화했다.

> 이 확장은 curated kinase-to-output 관계만 평가한다. PTM이 non-PTM protein trajectory에 선행한다는 cross-layer relation, protein abundance peak/direction, 또는 counterexample은 workbook에 명시되어 있지 않아 생성하지 않았다.

## Derivation

별도 extension workbook에는 기존 workbook을 복제한 뒤 4개 optional sheet를 추가했다. `Mechanism_Chains` sheet에는 15개 curated kinase reference의 `Direct_or_preferred_outputs`에서 추출한 **82개 unique kinase-output pair**만 기록했다. 각 row에는 source field, source identifier, expected activity direction/time, `workbook_kinase_reference_direct_or_preferred_outputs` origin을 보존했다.

| Optional reference type | Workbook evidence | Derived row count | Evaluation status |
|---|---|---:|---|
| Protein effectors | 없음 | 0 | Not evaluable |
| PTM–protein cross-layer relations | 없음 | 0 | Not evaluable |
| Kinase-output mechanism pairs | `Kinase_Reference.Direct_or_preferred_outputs` | 82 | Runner-only evaluable, but not cross-layer truth |
| Counterexamples | 없음 | 0 | Not evaluable |

Derivation은 raw PR/PG matrix, analysis artifact, prediction, RAG 또는 LLM을 읽지 않았다. Parent locked truth와 workbook SHA-256 일치도 확인했다.

## Runner-Only Integrated Evaluation

Frozen integrated temporal PTM–protein artifact를 변경하지 않고, artifact freeze 뒤 독립 evaluator에서 extension truth를 대조했다.

| Metric | Result | Interpretation |
|---|---:|---|
| Protein-effector reference count | 0 | Workbook에 curated protein trajectory truth 없음 |
| Cross-layer relation reference count | 0 | PTM→protein temporal relation recovery는 계산 불가 |
| Explicit curated kinase-output mechanism references | 82 | Workbook-derived denominator |
| Observed mechanism chains | 8,000 | Algorithmic candidate space; truth가 아님 |
| Evidence-supported chains | 0 | Current strict evidence gate에서 support 없음 |
| Candidate chains matching any curated kinase-output pair | 0 | Current chain target labels와 curated workbook outputs의 exact overlap 없음 |
| Mechanism reference recovery | **0.0 / 82** | Curated kinase-output pair 기준 |
| Refutation status | Not evaluable | Explicit counterexample truth 없음 |

이 0.0 결과는 cross-layer algorithm의 false-positive rate 또는 PTM→protein causality failure를 의미하지 않는다. 평가한 82개는 workbook의 curated kinase-output pair이고, algorithm chain은 current artifact에서 evidence-supported status가 0개이며 target token의 exact match도 없었다. 즉 이 결과는 **현재 evidence gate와 curated output vocabulary 사이의 strict-overlap failure**를 나타낸다.

## 해석 및 다음 단계

이번 확장은 benchmark sheet에 이미 있던 kinase-output 지식을 실제 evaluator denominator로 추가했다는 점에서 의미가 있다. 그러나 PTM–protein cross-layer 성능을 평가하려면 analyst가 다음 optional sheets를 독립적으로 작성해야 한다.

| Required sheet | Minimum curated content |
|---|---|
| `Protein_Effectors` | Gene, expected peak window, expected direction, reference |
| `Cross_Layer_Relations` | Source wave, target gene, direction, admissible lag interval, reference |
| `Mechanism_Chains` | Kinase, target gene, required output token, timing/direction, reference |
| `Counterexamples` | Expected refutation status or exclusion reason, reference |

그 후에는 동일 artifact를 다시 생성하지 않고 runner-only evaluator만 재실행하여 protein recovery, cross-layer recovery, mechanism recovery 및 refutation sensitivity를 계산할 수 있다. Algorithm output을 이 sheet에 자동으로 복사하는 것은 금지한다.

## Reproducibility

Runner-only extension outputs are stored outside the production repository in `benchmark_v1_v2_work/workbook_optional_reference_extension/`: derived truth JSON, derived additive truth JSON, integrated assessment JSON, provenance summary, and the separate workbook extension. The original workbook remains unchanged.
