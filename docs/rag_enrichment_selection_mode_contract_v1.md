# PTM Selection Mode 기반 RAG Enrichment Input Contract v1

작성일: 2026-08-18 (GMT+9)  
상태: **구현 완료**

## 목적

PTM Selection Mode는 단순한 화면 표시 필터가 아니라, RAG Enrichment가 외부 structured database와 literature를 조회하는 **실제 input universe**를 결정한다. 이전 구현은 selection mode로 condition rows를 일부 걸렀더라도, 선택된 site의 모든 condition/timepoint row를 각각 RAG worker에 전달했다. 따라서 85개의 표시 PTM이 약 4,459개의 외부 enrichment job으로 확장될 수 있었다.

새 contract는 선택된 condition rows를 gene+position site 단위로 collapse하고, dense temporal trajectory를 보존한 하나의 RAG work item으로 만든다.

```text
normalized vector TSV rows
        ↓
PTM Selection Mode filtering
        ↓
selected condition/timepoint rows
        ↓
site-level collapse with condition_data + trajectory
        ↓
one structured database-first RAG job per unique selected site
        ↓
evidence-gap routing
```

## Mode별 input universe

| Selection Mode | RAG input | Automatic PubMed policy | Intended use |
|---|---|---|---|
| `de_novo_regulated` | De novo 또는 Regulated classification을 만족하는 selected site trajectories | high-signal evidence gap, receptor/transgene context, explicit request에만 `abstract_targeted` | 기본 discovery report; focused interpretation |
| `de_novo` | De novo selected site trajectories | high-priority evidence gap에서만 targeted literature | new/condition-emergent modification 중심 |
| `regulated` | q < 0.05와 effect-size rule을 통과한 regulated site trajectories | high-priority evidence gap에서만 targeted literature | statistical regulation 중심 |
| `all` | 모든 unique observed site trajectory | **broad annotation mode:** automatic high-signal/context PubMed escalation 없음; explicit request 또는 receptor/transgene/full-text override만 literature route | global annotation/coverage audit |
| `minor` | minor classification site trajectory | `all`과 동일하게 database-first; explicit escalation만 literature | low-amplitude pattern review |
| `top_n` | max absolute Track 2 relative signal을 기준으로 선택한 top-N unique site trajectory | default focused-route policy | 빠른 exploratory run |

`all`과 `minor` mode에서 structured database lookup을 완전히 생략하지 않는다. 이 mode는 **broad annotation**을 위해 선택한 coverage universe이므로, one site trajectory당 iPTMnet/UniProt/pathway/PPI packet은 생성한다. 다만 많은 coverage site를 선택했다는 이유만으로 PubMed와 Qwen latency가 폭증하지 않도록 automatic literature escalation을 억제한다.

## Site-level collapse

`collapse_ptm_rows_for_enrichment()`은 selected rows를 `(Gene.Name, PTM_Position)` 기준으로 group한다.

| Stored field | Meaning |
|---|---|
| representative row | max `abs(PTM_Relative_Log2FC)` condition row; legacy field compatibility 유지 |
| `condition_data` | 선택된 모든 condition/timepoint의 PTM relative signal, protein signal, q-value 및 absolute PTM field |
| `trajectory` | minute-aware condition ordering으로 구성한 temporal PTM/protein trajectory |
| `rag_source_row_count` | site-level RAG job으로 collapse된 원본 selected condition-row 수 |
| `rag_selection_mode` | 해당 job을 만든 selection mode의 provenance |

후속 `merge_multi_condition_ptms()`는 pre-collapsed item의 `condition_data`와 `trajectory`를 보존한다. 따라서 report, co-wave, TMM context와 non-PTM temporal interpretation에 필요한 dense time-course 정보가 external database query 절약 때문에 손실되지 않는다.

## Evidence routing interaction

| Route factor | `de_novo_regulated` / focused mode | `all` / `minor` broad annotation mode |
|---|---|---|
| uncurated + high observed signal | `abstract_targeted` 가능 | `db_only` 유지 |
| curated + high observed signal + experimental context | `abstract_targeted` 가능 | `db_only` 유지 |
| receptor/transgene/mixed-species reference | `abstract_targeted` | `abstract_targeted` |
| `requires_literature_validation` | `abstract_targeted` | `abstract_targeted` |
| `requires_fulltext` / explicit full-text override | `fulltext_escalated` | `fulltext_escalated` |

이 정책은 `all` mode의 high-signal site가 biological relevance가 없다는 뜻이 아니다. broad coverage mode에서는 automatic literature budget을 사용하지 않는 것이며, 해당 site를 추후 explicit validation candidate로 지정하면 targeted evidence route를 사용할 수 있다.

## Progress semantics

RAG progress total은 더 이상 selected raw condition rows의 개수가 아니다. external lookup 작업 수인 **unique selected site trajectories**를 표시한다.

```text
[85 unique PTMs selected from 4,459 condition rows] mode='de_novo_regulated'
Herc1 S2718: [db_only] structured DB, 2 pathways, PubMed skipped (4/85)
```

`abstract_targeted`인 경우에는 only selected article count를 표시한다.

```text
Herc1 S2718: [abstract_targeted] 3 selected articles, 2 pathways (4/85)
```

## Regression coverage

| Test | Verifies |
|---|---|
| `test_rag_input_collapse.py` | multiple condition rows가 one site RAG job으로 collapse되고 time trajectory가 보존되는지 |
| `test_evidence_routing.py` | All PTMs broad mode가 uncurated high signal을 automatic PubMed로 승격하지 않는지, explicit literature request는 동작하는지 |
| existing evidence-routing tests | focused selection에서 db-only, targeted abstract, full-text escalation이 유지되는지 |

## Operational procedure

새 behavior는 RAG Enrichment worker rebuild/restart 후 생성하는 run에 적용된다. 기존 in-flight run은 이미 raw condition-row jobs를 queue에 제출했으므로 중단 후 다시 실행해야 한다. 새 run의 첫 progress line에서 `unique PTMs selected from <condition rows>`와 route label을 확인한다.
