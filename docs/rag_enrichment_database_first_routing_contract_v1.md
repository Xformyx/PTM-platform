# RAG Enrichment Database-First Evidence Routing Contract v1

작성일: 2026-08-17 (GMT+9)  
상태: **구현 완료 — route threshold 정책은 현재의 기존 classification·명시적 override를 사용**

## 목적

RAG Enrichment는 structured database와 literature를 같은 종류의 근거로 취급하지 않는다. UniProt, iPTMnet, KEGG/Reactome 및 optional interaction context는 canonical/curated evidence packet을 만들고, PubMed와 Qwen은 이 packet이 채우지 못하는 exact-site, treatment/context, contradiction 또는 strong-claim evidence gap에서만 호출한다.

```text
Raw temporal/PTM evidence
        ↓
Structured database-first packet
(iPTMnet exact site + UniProt + KEGG/Reactome + optional PPI)
        ↓
evidence-gap decision
   ├─ db_only
   ├─ abstract_targeted
   └─ fulltext_escalated
```

## Implemented routes

| Route | Default condition | External literature work | Qwen/full text behavior |
|---|---|---|---|
| `db_only` | curated exact-site evidence가 있고 low-priority observed signal이며 별도 context gap이 없음 | PubMed 검색 없음 | Qwen literature tasks 없음; report는 “문헌을 찾지 못함”이 아니라 database-first decision을 표시 |
| `abstract_targeted` | exact site가 curated DB에 없고 high signal/context/reference complication이 있거나, curated site라도 high-signal context claim이 필요 | exact site/PTM query, `RAG_MAX_ARTICLES` budget 사용 | 기존 source-grounded abstract/kinase/functional analysis 유지; selected article set만 입력 |
| `fulltext_escalated` | `requires_fulltext=true`, `fulltext_escalated=true`, 또는 `evidence_route_override=fulltext_escalated` | targeted article 결과 재사용 | PMC full text는 top article 1개만 분석 |

`evidence_route_override` 값은 `db_only`, `abstract_targeted`, `fulltext_escalated`만 허용한다. 이 override는 threshold를 변경하는 전역 설정이 아니라 특정 PTM에 대한 명시적 audit/request provenance다.

## Structured database packet

새 output `structured_database_packet`은 다음 provenance를 보존한다.

| Field | Source | Meaning |
|---|---|---|
| `iptmnet.sites_found` | iPTMnet exact-site lookup | observed site와 curated PTM evidence의 match count |
| `iptmnet.exact_site_known` | iPTMnet novelty status | curated match 여부; non-match는 biological absence 또는 true novelty 증명이 아님 |
| `iptmnet.pmids` | iPTMnet | curated resource가 제공한 reference PMID |
| `uniprot` | UniProt | function/localization context |
| `pathway_context` | KEGG/Reactome | curated pathway coverage |
| `interaction_context` | STRING | optional network context, direct PTM evidence 아님 |

새 `evidence_gap_decision`은 route, reason codes, literature-required flag를 저장한다. `search_summary`에도 route와 reason codes를 중복해 lightweight consumer compatibility를 제공한다.

## Literature and validation reuse

1. iPTMnet exact-site lookup은 Phase A에서 한 번 실행하고, PTM validator가 `preloaded_iptmnet_data`로 재사용한다.
2. UniProt result도 `preloaded_uniprot_data`로 validator에 전달한다.
3. `abstract_targeted`/`fulltext_escalated`의 selected PubMed article list는 validator의 `preloaded_articles`로 전달된다. validator는 이를 `PubMed(selected)` evidence로 기록하고 context-aware broad PubMed fan-out을 실행하지 않는다.
4. `db_only`에서는 validator가 structured validation을 수행하지만 PubMed search를 추가 실행하지 않는다.
5. full text는 selected top article 1개로 제한한다. full text가 필요한 경우만 explicit escalation route를 설정한다.

## Cache safety contract

Phase B cache key는 이제 task name에 route와 context signature를 포함한다.

```text
<task>__<route>__ctx_<hash>
```

context signature에는 organism/species, treatment, cell type, tissue, biological question, special conditions, Track 2 relative signal, protein log2FC 및 temporal profile summary가 포함된다. 따라서 같은 PMID set이라도 서로 다른 insulin condition, species, observed trajectory 또는 biological question에서 kinase/functional interpretation이 재사용되지 않는다.

partial PMID subset reuse는 route-specific LLM interpretation에서 사용하지 않는다. 새 article이 contradictory evidence를 포함할 수 있으므로, context-specific synthesis는 exact article packet으로만 cache hit한다. immutable article-level fact cache는 별도 schema가 구현될 때 추가한다.

## Report behavior

`db_only` route에서 report의 Literature Evidence section은 “관련 문헌을 찾지 못했다”고 쓰지 않는다. 대신 structured database-first packet이 충분하여 literature retrieval을 escalation하지 않았음을 표시하고, quantitative PTM/protein evidence 및 curated provenance에 기반한 해석임을 명시한다.

`abstract_targeted` route에서 selected article이 0개인 경우에만 “selected literature evidence was not returned”이라고 보고한다. 이는 search failure, low relevance 또는 constrained article budget을 biological absence와 구분하기 위함이다.

## Validation

| Test | Coverage |
|---|---|
| `test_evidence_routing.py` | curated low-priority `db_only`, uncurated high-signal `abstract_targeted`, low-priority uncurated `db_only`, explicit full-text escalation, structured packet provenance |
| Python compilation | evidence routing, enrichment pipeline, PTM validator syntax |
| Existing temporal contracts | canonical wave와 TMM regression tests로 기존 core analysis가 변경되지 않았는지 확인 |

## Operational procedure

새 RAG Enrichment를 적용하려면 worker image를 rebuild/restart해야 한다. 기존 order의 RAG enrichment 결과에는 route provenance가 없으므로, 새 contract를 사용하려면 해당 order에서 enrichment를 재실행해야 한다. 기존 report는 route fields가 없어도 legacy behavior를 유지한다.

`RAG_MAX_ARTICLES` 값은 `abstract_targeted` budget에만 적용된다. route 자체는 current observed classification과 structured evidence gap으로 결정되며, global threshold를 새로 변경하지 않았다.
