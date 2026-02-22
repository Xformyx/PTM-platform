# PTM Analysis Platform — API Reference

모든 API는 Gateway를 통해 `http://localhost/api/...` 또는 `https://ptm.xformyx.com/api/...` 로 접근합니다.

`AUTH_ENABLED=false`인 경우 인증 헤더 없이 모든 요청이 허용됩니다.
`AUTH_ENABLED=true`인 경우 `Authorization: Bearer <JWT>` 헤더가 필요합니다.

---

## Health Check

### `GET /api/health`
기본 헬스체크.

**Response:**
```json
{"status": "ok", "service": "ptm-api-server"}
```

### `GET /api/health/detailed`
전체 인프라 상세 헬스체크 (MySQL, Redis, ChromaDB, Ollama).

**Response:**
```json
{
  "status": "ok",
  "checks": {
    "mysql": {"status": "ok"},
    "redis": {"status": "ok"},
    "chromadb": {"status": "ok"},
    "ollama": {"status": "ok", "models_count": 3}
  }
}
```

---

## Orders

### `GET /api/orders`
Order 목록 조회.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `status_filter` | string | (없음) | pending / preprocessing / rag_enrichment / report_generation / completed / failed |
| `page` | int | 1 | 페이지 번호 |
| `page_size` | int | 20 | 페이지 크기 |

### `GET /api/orders/{order_id}`
Order 상세 조회.

### `POST /api/orders`
Order 생성 (multipart/form-data).

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `project_name` | string | Yes | 프로젝트 이름 |
| `ptm_type` | string | Yes | `phosphorylation` / `ubiquitination` |
| `species` | string | Yes | `human` / `mouse` / `rat` |
| `sample_config` | JSON string | Yes | 샘플 그룹 설정 (control/experiment 매핑) |
| `report_options` | JSON string | Yes | 리포트 생성 옵션 |
| `analysis_context` | JSON string | No | 분석 맥락 (연구 질문 등) |
| `pr_matrix` | File | Yes | Protein Report Matrix (pr 파일) |
| `pg_matrix` | File | Yes | Peptide Group Matrix (pg 파일) |
| `fasta_file` | File | Yes | FASTA Reference 파일 |

**Response (201):**
```json
{
  "id": 1,
  "order_code": "PTM-2026-0001",
  "status": "pending",
  "message": "Order created successfully"
}
```

### `POST /api/orders/{order_id}/start`
Order 분석 시작 (Celery task 발행).

### `POST /api/orders/{order_id}/cancel`
Order 취소.

### `GET /api/orders/{order_id}/logs`
Order 로그 목록 조회.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `stage` | string | (없음) | 특정 stage만 필터링 |
| `limit` | int | 100 | 최대 조회 건수 |

---

## SSE (Server-Sent Events)

### `GET /api/events/orders/{order_id}`
Order 분석 진행률을 실시간 스트리밍.

- Redis Pub/Sub 채널 `order:{order_id}:progress` 구독
- 각 워커가 진행률을 publish하면 SSE로 클라이언트에 전달

**Event Format:**
```
data: {"stage": "preprocessing", "step": "quantification", "progress": 35.5, "message": "Running PTM quantification..."}
```

---

## RAG Collections

### `GET /api/rag/collections`
RAG 컬렉션 목록 조회.

### `POST /api/rag/collections`
새 RAG 컬렉션 생성.

```json
{
  "name": "kinase-signaling-2024",
  "description": "Kinase signaling pathway papers",
  "embedding_model": "default"
}
```

### `GET /api/rag/collections/{collection_id}`
컬렉션 상세 조회.

### `DELETE /api/rag/collections/{collection_id}`
컬렉션 삭제.

### `POST /api/rag/collections/{collection_id}/documents`
컬렉션에 문서 업로드 (chunking + embedding).

---

## LLM Models

### `GET /api/llm/models`
등록된 LLM 모델 목록 조회.

### `POST /api/llm/models`
LLM 모델 수동 등록.

```json
{
  "name": "gpt-4o",
  "provider": "openai",
  "model_id": "gpt-4o",
  "is_default": false
}
```

### `PUT /api/llm/models/{model_id}`
모델 정보 수정 (기본 모델 지정 등).

### `DELETE /api/llm/models/{model_id}`
모델 삭제.

### `POST /api/llm/models/sync-ollama`
Ollama에 설치된 모델 자동 동기화.

### `POST /api/llm/models/{model_id}/test`
모델 응답 테스트.

---

## MCP Server (Internal)

MCP Server는 내부 전용 (Docker network 내에서만 접근). Gateway를 통해 노출되지 않습니다.
워커들이 `MCPClient`를 통해 `http://mcp-server:8001`로 호출합니다.

### `GET /tools/uniprot/{protein_id}`
UniProt 단백질 정보 조회.

### `POST /tools/uniprot/batch`
UniProt 배치 조회.

### `GET /tools/kegg/{gene_name}`
KEGG 경로 정보 조회.

### `POST /tools/kegg/batch`
KEGG 배치 조회.

### `GET /tools/stringdb/{gene_name}`
STRING-DB 단백질 상호작용 네트워크 조회.

### `POST /tools/stringdb/batch`
STRING-DB 배치 조회.

### `GET /tools/interpro/{protein_id}`
InterPro 도메인/모티프 정보 조회.

### `POST /tools/interpro/batch`
InterPro 배치 조회.

### `POST /tools/pubmed/search`
PubMed 문헌 검색 (다중 티어 전략).

### `POST /tools/pubmed/search/batch`
PubMed 배치 검색.

### `POST /tools/pubmed/fetch`
PMID로 문헌 정보 가져오기.

### `GET /tools/pubmed/aliases/{gene_name}`
유전자 별명(alias) 조회 (MyGene.info).
