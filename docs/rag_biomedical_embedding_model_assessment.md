# RAG Collection의 BioBERT·PubMedBERT Embedding 지원성 평가 및 도입 설계

작성일: 2026-08-17 (GMT+9)
상태: **PubMedBERT contract 구현 완료 — 기존 collection의 재색인 및 retrieval benchmark는 운영 단계에서 수행 필요**

## 결론

RAG Collection에서 PubMedBERT 또는 BioBERT 계열 embedding model을 사용할 수 있다. 현재 worker는 database의 `rag_collections.embedding_model` 값을 `SentenceTransformer(...)`에 그대로 전달하므로, sentence-transformers 형식의 biomedical model은 **문서 색인 단계에서 이미 로드 가능**하다.

초기 구현은 biomedical embedding collection을 안전하게 검색할 수 있는 완성된 구조가 아니었다. document indexer는 명시적으로 embedding vector를 ChromaDB에 저장했지만, report/chat retrieval은 `collection.query(query_texts=[...])`로 query embedding을 ChromaDB 기본 embedding function에 위임했다. 따라서 index vector와 query vector가 서로 다른 model 또는 dimension으로 생성될 수 있었다. PubMedBERT 지원 구현에서는 이 경로를 교체해 index와 query 모두 collection embedding contract를 사용하도록 했다.

> 따라서 model 이름을 collection row에 저장하는 것만으로는 충분하지 않다. **문서와 query에 동일한 model·pooling·normalization을 적용하고, model 변경 시 새 Chroma collection으로 재색인**해야 한다.

## 현재 코드 감사

| 경로 | 현재 동작 | 의미 |
|---|---|---|
| `ptm_shared/embedding_registry.py` | allow-listed model key·Hugging Face ID·dimension·normalization·Chroma space를 정의 | index/query 동일 vector space의 single source of truth |
| `api-server/app/api/rag.py` | 지원 model validation·metadata 제공·PubMedBERT collection 생성 허용 | arbitrary model loading을 차단하고 UI에 contract를 노출 |
| `workers/rag_enrichment/document_tasks.py` | DB model name을 `DocumentIndexer`에 전달 | collection별 model 값이 ingestion worker에 도달 |
| `workers/common/document_indexer.py` | registry model로 normalized chunk embedding을 생성하고 Chroma metadata contract와 함께 저장 | PubMedBERT 768D/cosine index 생성 및 index-time mismatch 차단 |
| `workers/report_generation/core/rag_retriever.py` | collection metadata를 검사하고 same-model `query_embeddings` 전달 | report RAG의 index/query symmetry 확보 |
| `api-server/app/api/chat.py` | same-model `query_embeddings` 전달 | chat RAG에도 동일 contract 적용 |
| `frontend/src/pages/RagManagement.tsx` | PubMedBERT selector, 768D/cosine 표시, new collection/reindex 안내 | 기존 collection model overwrite를 피하는 UX |

## raw BioBERT/PubMedBERT와 sentence-transformer 파생 model의 구분

`dmis-lab/biobert-*`나 `microsoft/BiomedNLP-PubMedBERT-base-*` 같은 raw encoder는 biomedical token representation을 위한 base model이다. 이들은 sentence-pair retrieval objective, pooling recipe, normalization contract가 정해진 RAG embedding model이 아니므로, 현재 플랫폼의 `SentenceTransformer` 기반 path에 raw model을 그대로 선택하는 것은 권장하지 않는다.

대신 biomedical corpus와 sentence similarity 또는 retrieval 목적에 맞게 fine-tune된 **sentence-transformer model**을 registry에 넣어야 한다.

| Registry key 제안 | Hugging Face model | 차원 | 용도·평가 | 권장도 |
|---|---|---:|---|---|
| `pubmedbert_embeddings_v1` | `NeuML/pubmedbert-base-embeddings` | 768 | PubMed title–abstract pair로 sentence-transformers fine-tune; medical literature semantic search용 model card와 Apache-2.0 license 제공 | **기본 권장** |
| `pubmedbert_ir_v1` | `pritamdeka/S-PubMedBert-MS-MARCO` | 768 | medical/health information retrieval 용도로 sentence-transformers fine-tune | 연구용 후보; **CC-BY-NC-2.0 license**를 운영 전 검토 |
| `biobert_similarity_v1` | `pritamdeka/S-BioBert-snli-multinli-stsb` | 768 | BioBERT 기반 sentence similarity model | 비교 benchmark 후보; max sequence length 75를 고려하면 긴 문헌 chunk의 primary model로는 비권장 |

`NeuML/pubmedbert-base-embeddings`는 PubMedBERT를 sentence-transformers 방식으로 fine-tune해 sentence/paragraph를 768차원 dense vector로 변환하며, model card는 medical literature semantic search 용도를 명시한다.[1] `S-PubMedBert-MS-MARCO`도 768차원 sentence-transformer로 medical/health retrieval 용도를 표방하지만, 비상업 라이선스이므로 platform의 배포·상업적 사용 조건과 분리해 판단해야 한다.[2]

## 권장 architecture: shared embedding registry + explicit query vectors

공유 `ptm_shared/embedding_registry.py`를 추가해 API와 worker가 공통 registry contract를 사용하도록 구현했다.

| Registry field | 예시 | 역할 |
|---|---|---|
| `model_key` | `pubmedbert_embeddings_v1` | 사용자·DB에 저장할 안정적인 식별자 |
| `hf_model_id` | `NeuML/pubmedbert-base-embeddings` | sentence-transformers loading 대상 |
| `dimension` | `768` | index/query dimension validation |
| `normalize_embeddings` | `true` | cosine/IP distance의 일관성 확보 |
| `max_sequence_length` | `512` | chunk policy compatibility 확인 |
| `license_class` | `permissive` | 배포 정책 검사 |
| `status` | `supported` / `experimental` / `deprecated` | UI 노출 및 신규 collection 제한 |

색인과 검색은 모두 registry에서 같은 model을 가져와야 한다.

```text
document chunk → model.encode(chunk, normalize_embeddings=True) → ChromaDB embedding
query text    → same model.encode(query, normalize_embeddings=True) → ChromaDB query_embeddings
```

즉, `query_texts`에만 의존하지 않고 report retriever와 chat endpoint가 `query_embeddings=[...]`를 전달한다. Chroma collection metadata에는 model key, Hugging Face model ID, embedding dimension, normalization, distance space와 contract version을 기록한다. 검색 시 metadata dimension 또는 normalization이 registry expected value와 다르면 retrieval을 중단하고 해당 collection을 skip한다. 새로운 model은 existing collection을 덮어쓰지 않으며, model 변경은 새 collection 생성과 원본 document 재색인을 요구한다.

## 안전한 reindex 및 migration 정책

하나의 Chroma collection 내부에서 embedding model을 교체해서는 안 된다. 기존 chunk embedding과 새 query vector가 같은 vector space가 아니기 때문이다. 사용자는 다음 절차로 새 model을 적용해야 한다.

| 순서 | 운영 조치 | 안전장치 |
|---|---|---|
| 1 | 기존 collection metadata·document row·Chroma export를 백업 | rollback 가능성 확보 |
| 2 | 기존 collection을 유지한 채 `__v2_pubmedbert` suffix의 새 Chroma collection 생성 | 기존 report/chat retrieval에 영향 없음 |
| 3 | 원본 document file을 새 registry model로 전체 재색인 | embedding dimension 및 model metadata 검증 |
| 4 | fixed biomedical query set으로 old/new retrieval을 blind 비교 | retrieval quality·latency·failure 비교 |
| 5 | 충분한 결과가 확인된 경우에만 새 collection을 active로 전환 | atomic routing change |
| 6 | 기존 collection은 grace period 동안 read-only fallback으로 유지 | 운영 rollback 가능 |

collection model 변경은 단순 PATCH로 허용하지 않는다. model이 바뀌면 `reindex_required=true`를 반환하고 clone-and-reindex workflow를 강제해야 한다.

## 권장 benchmark

model의 의생명 사전학습 여부만으로 platform retrieval이 개선된다고 가정하면 안 된다. RAG의 실제 query 유형을 반영한 versioned gold set으로 비교한다.

| Benchmark slice | 예시 query | 판정 |
|---|---|---|
| PTM site context | `INSR Y1158 phosphorylation insulin signaling` | 알려진 PTM/kinase 문헌의 recall@k, MRR |
| Temporal mechanism | `AKT early wave mTOR delayed response` | temporal pathway review·primary paper retrieval |
| Non-PTM effector context | `insulin signaling downstream protein abundance response` | total-proteome outcome 문헌 retrieval |
| Negative/ambiguous query | `kinase pathway unrelated to collection` | irrelevant-source suppression |
| Operational slice | 10–20 chunk 및 1000-char chunk | latency, memory, failure, truncation rate |

새 model은 동일 collection·동일 chunking·동일 reranker 조건에서 baseline과 비교해야 한다. report quality는 LLM의 문장 길이가 아니라 retrieval hit의 provenance, relevant citation recall, contradiction coverage, and RAG failure rate로 먼저 평가한다.

## 구현 우선순위

1. **P0: embedding registry 및 explicit query embedding** — 구현됨. index/query model symmetry, dimension guard, normalized vector policy를 적용했다.
2. **P1: collection schema·UI** — 구현됨. supported model selector와 collection contract metadata를 추가했으며, existing collection의 model overwrite를 허용하지 않는다.
3. **P2: migration tool** — 향후 작업. backup, clone, batch reindex, query benchmark, active/fallback switch를 자동화한다.
4. **P3: model evaluation** — 향후 작업. default MiniLM과 PubMedBERT를 동일 gold query set에서 비교한다.

현재 가장 안전한 제품 결정은 **`NeuML/pubmedbert-base-embeddings`를 PubMedBERT 기반 supported biomedical default 후보로 추가하고**, raw BioBERT/PubMedBERT는 UI에서 직접 입력하는 option이 아니라 experimental custom model 또는 model registry 확장 대상으로 제한하는 것이다.

## References

[1] NeuML. *pubmedbert-base-embeddings model card.* https://huggingface.co/NeuML/pubmedbert-base-embeddings

[2] Pritam Deka. *S-PubMedBert-MS-MARCO model card.* https://huggingface.co/pritamdeka/S-PubMedBert-MS-MARCO

[3] Pritam Deka. *S-BioBert-snli-multinli-stsb model card.* https://huggingface.co/pritamdeka/S-BioBert-snli-multinli-stsb

[4] Lee J, et al. BioBERT: a pre-trained biomedical language representation model for biomedical text mining. *Bioinformatics* (2020). https://academic.oup.com/bioinformatics/article/36/4/1234/5566506
