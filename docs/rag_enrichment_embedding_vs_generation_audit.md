# RAG Enrichment에서 PubMedBERT Retrieval과 Qwen 14B 생성형 해석의 역할 감사

작성일: 2026-08-17 (GMT+9)
상태: **코드 감사 완료 — retrieval reranking layer는 별도 기능으로 제안**

## 결론

현재 RAG Enrichment에서 PubMedBERT embedding을 추가해도 **즉시 성능이 바뀌지는 않는다.** 이 pipeline의 literature retrieval은 ChromaDB collection 검색이 아니라 MCP server를 통한 PubMed keyword/API search이며, 그 결과 초록을 규칙 기반 extractor와 Qwen 14B 계열 LLM이 읽어 structured evidence로 변환하는 구조다.

따라서 PubMedBERT와 Qwen 14B는 대체 관계가 아니다.

> **PubMedBERT는 biomedical literature의 semantic retrieval·reranking에 적합하고, Qwen 14B는 선택된 근거를 구조화·비교·제한적으로 해석하는 생성형 모델로 유지하는 것이 맞다.**

현 코드 기준으로 Qwen 14B는 계속 사용하는 것이 적절하다. `RAG_ENRICHMENT_LLM_MODEL`을 설정하지 않거나 작은 local model이 선택되면 pipeline은 `qwen2.5:14b`를 fallback으로 사용하며, 14B 미만 local model은 JSON 안정성과 hallucination 위험을 이유로 교체한다. 이 정책은 PubMedBERT를 추가해도 변경할 필요가 없다.

## 현재 코드의 실제 역할 분리

| 처리 단계 | 구현 경로 | 현재 모델/도구 | 관찰·추론 역할 |
|---|---|---|---|
| Experimental input | `workers/rag_enrichment/tasks.py` | enriched PTM vector, context, species | 분석 대상 site·조건·시간 정보 제공 |
| Literature candidate retrieval | `enrichment_pipeline.py` Phase A → `MCPClient.search_pubmed()` | MCP PubMed API | gene, site, PTM type, context keyword 기반 keyword search; **embedding 없음** |
| Structured database evidence | Phase A | KEGG, STRING, UniProt, HPA, GTEx, BioGRID, Reactome, iPTMnet | pathway/annotation/known-site information; gene-level cache 적용 |
| Deterministic text evidence | Phase B | `RegulationExtractor` regex | 초록에서 직접 언급된 kinase–substrate, regulation, disease phrase 추출; LLM 없이 동작 |
| Evidence extraction | Phase B | `AbstractAnalyzer` + Qwen 14B 등 LLM | PubMed abstract를 JSON으로 구조화; upstream/downstream, evidence quality, context alignment 추출 |
| Kinase hypothesis | Phase B | `LLMKinasePredictor` + Qwen 14B | PubMed evidence와 experimental context를 통합해 candidate kinase/alternative regulator를 제한적으로 제안 |
| Functional interpretation | Phase B | `LLMFunctionalImpact` + Qwen 14B | `PTM_Relative_Log2FC`, protein log2FC, pathway, article evidence를 이용해 functional interpretation 생성 |

코드상 `RAGEnrichmentPipeline`은 `qwen2.5:14b`를 fallback으로 지정하고, Phase B LLM module에 PubMed article, PTM relative signal, protein abundance, KEGG pathway와 experimental context를 전달한다. 반면 RAG Collection의 ChromaDB embedding model은 report generation/chat retrieval 경로에 적용되며, 현재 RAG Enrichment의 MCP PubMed search에는 연결되지 않는다.

## PubMedBERT를 지금 RAG Enrichment에 바로 적용하지 않는 이유

PubMedBERT embedding은 text-to-vector representation을 만들어 유사도를 계산하는 retrieval component다. 현재 Phase A는 외부 PubMed API가 반환한 top article 수를 `RAG_MAX_ARTICLES`로 제한하고, Phase B의 LLM은 그 article들을 직접 읽는다. 이 구조에 embedding model 이름만 주입해도 MCP PubMed search query, article candidate ordering 또는 Qwen prompt는 변하지 않는다.

| 변경안 | 현재 RAG Enrichment에 미치는 실제 영향 | 판정 |
|---|---|---|
| RAG Collection을 PubMedBERT로 생성 | report/chat literature retrieval만 개선 가능 | 유용하지만 RAG Enrichment의 MCP PubMed ranking에는 직접 영향 없음 |
| Qwen 14B를 PubMedBERT로 교체 | structured JSON extraction·cross-article synthesis 기능 상실 | 부적절 |
| MCP 결과에 PubMedBERT reranker 추가 | site·PTM·context와 더 의미적으로 맞는 article을 Qwen에 전달 | 검증 후 도입 가치 있음 |
| Qwen 14B로 article relevance judge 추가 | 가능하나 비용·latency·재현성 부담 | PubMedBERT first-pass보다 후순위 |

## 권장 운영 정책

### 현재: Qwen 14B 유지

RAG Enrichment의 `AbstractAnalyzer`, `LLMKinasePredictor`, `LLMFunctionalImpact`는 생성형 reasoning과 strict JSON parsing이 필요하므로 Qwen 14B를 계속 유지한다. 다만 Qwen의 출력은 evidence extraction/hypothesis layer이며, deterministic MCP evidence·regex evidence·실험 data를 대체하지 않는다.

`RAG_ENABLE_LLM=false`일 때에도 Phase A의 PubMed/annotation retrieval 및 Phase B의 regulation extractor가 동작하므로, LLM failure가 annotation pipeline 전체를 중단시키지 않는 현재 구조도 유지한다.

### 향후: PubMedBERT semantic reranking adapter 추가

PubMedBERT의 실질적 가치는 MCP PubMed keyword search로 넓게 확보한 candidate article을 **semantic rerank**하는 데 있다. 새 adapter는 기존 PubMed retrieval을 대체하지 않고 다음 순서로 추가해야 한다.

```text
site/context-aware PubMed API query
        → top 20–50 candidate title + abstract
        → PubMedBERT query/article embedding similarity
        → metadata-aware score (site/PTM/species/year/evidence type)
        → MMR diversity selection of top 3–5 articles
        → deterministic extractor + Qwen 14B evidence JSON
```

query text는 `GENE + residue/site + PTM type + species + treatment + time window + biological question`으로 구성한다. reranker는 article의 title·abstract 및 PMID를 보존하며, 최종 LLM prompt에 ranking score 자체를 biological evidence로 제시하지 않는다. score는 **어떤 abstract를 읽을지 정하는 retrieval provenance**일 뿐이다.

| Guardrail | 요구 사항 |
|---|---|
| Source provenance | 각 article의 PMID, original PubMed rank, PubMedBERT rank, semantic score, retrieval query를 저장 |
| Site specificity | gene-only match와 exact residue/site match를 구분하여 metadata boost하되, exact-site 부재를 negative evidence로 해석하지 않음 |
| Species/context | rat_hir의 human INSR처럼 FASTA-native taxon, treatment, cell type을 ranking metadata로 사용 |
| Diversity | 같은 review 또는 동일 주장만 반복되는 결과를 MMR/source-type diversity로 제한 |
| Citation grounding | Qwen은 선택된 article text에만 근거해 JSON을 생성하고 PMID-level citation을 유지 |
| Fallback | PubMedBERT loading/rerank failure 시 original MCP PubMed rank를 그대로 사용 |
| Evaluation | fixed PTM/time-course query set에서 Recall@k, site-specific article recovery, latency, Qwen evidence extraction failure를 baseline과 비교 |

## 우선순위 판단

| 작업 | 우선순위 | 이유 |
|---|---|---|
| Qwen 14B를 RAG Enrichment LLM으로 유지 | **현재 유지** | structured extraction, evidence synthesis, kinase/functional hypothesis 역할에 적합 |
| PubMedBERT RAG Collection 사용 | **즉시 활용 가능** | report/chat의 collection-backed literature search에 적용 가능 |
| MCP PubMed semantic reranker | **중간·검증 후 도입** | 현재 keyword candidate recall이 충분한지 먼저 benchmark해야 함 |
| PubMedBERT가 Qwen 역할을 대체 | **도입하지 않음** | embedding model은 generative JSON extraction 또는 evidence synthesis를 수행하지 않음 |
| LLM relevance ranking을 primary retrieval로 사용 | **후순위** | 비용·latency·prompt variability가 증가; deterministic semantic rerank 이후 필요 시 추가 |

## 최종 권고

현재 플랫폼에서는 **Qwen 14B를 제거하거나 PubMedBERT로 바꾸지 않는 것**이 맞다. 먼저 PubMedBERT를 RAG Collection 기반 report/chat retrieval에 적용하고, 실제 insulin/PTM query set에서 MCP PubMed top results가 context-irrelevant하거나 site-specific literature를 반복적으로 놓치는 증거가 생길 때에만 `MCP candidate retrieval → PubMedBERT rerank → Qwen evidence extraction` adapter를 추가한다.

이 순서는 Qwen이 일반 지식으로 문헌을 판단하도록 과도하게 확장하지 않고, retrieval accuracy와 generation quality를 독립적으로 측정하게 한다. 또한 사용자의 data-grounded 원칙에 따라 final interpretation은 실험 vector, MCP/Chroma source text, 그리고 provenance가 기록된 retrieved evidence에 제한된다.
