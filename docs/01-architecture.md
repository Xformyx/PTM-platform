# PTM Analysis Platform — Architecture Overview

## 플랫폼 개요

질량분석기에서 얻은 PTM(Post-Translational Modification) 데이터를 입력받아
**Preprocessing → RAG Enrichment → Report Generation** 3단계 파이프라인을 거쳐
연구자/제약사에게 양질의 분석 리포트를 제공하는 마이크로서비스 플랫폼.

## 시스템 구성도

```
                         ┌──────────────────────────────────┐
    ptm.xformyx.com ────▶│  Cloudflare Tunnel (cloudflared) │
                         └──────────┬───────────────────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
        :80 / :443 ─────▶│   Gateway (Nginx)     │
                         └──────┬──────┬────────┘
                                │      │
                  ┌─────────────┘      └────────────┐
                  ▼                                  ▼
        ┌──────────────────┐              ┌──────────────────┐
        │  Frontend (React) │              │  API Server       │
        │  Vite + Tailwind  │              │  FastAPI (Python)  │
        │  :80 (internal)   │              │  :8000 (internal)  │
        └──────────────────┘              └──────┬───────────┘
                                                 │
                      ┌──────────────────────────┤
                      │                          │
                      ▼                          ▼
             ┌─────────────────┐      ┌────────────────────┐
             │  MySQL 8.0       │      │  Redis 7           │
             │  메타데이터 DB   │      │  Celery Broker     │
             │  :3306           │      │  Pub/Sub + Cache   │
             └─────────────────┘      │  :6379             │
                                      └────────┬───────────┘
                                               │
                           ┌───────────────────┤
                           │                   │
                           ▼                   ▼
                ┌──────────────────┐  ┌──────────────────────┐
                │  MCP Server       │  │  Celery Workers (x3)  │
                │  FastAPI          │  │  ├─ preprocessing     │
                │  외부 API 게이트  │  │  ├─ rag_enrichment    │
                │  :8001 (internal) │  │  └─ report_generation │
                └──────────────────┘  └──────────┬───────────┘
                                                 │
                              ┌──────────────────┤
                              ▼                  ▼
                   ┌───────────────────┐  ┌──────────────────┐
                   │  ChromaDB          │  │  Ollama (Host)    │
                   │  벡터 DB (RAG)     │  │  Local LLM        │
                   │  :8000 (external)  │  │  :11434 (Host)    │
                   └───────────────────┘  └──────────────────┘
```

## 서비스별 역할

| 서비스 | 컨테이너명 | 기술 스택 | 역할 |
|--------|-----------|----------|------|
| **Gateway** | ptm-gateway | Nginx Alpine | 리버스 프록시, SSL, Rate Limiting |
| **Frontend** | ptm-frontend | React 18 + Vite + Tailwind | SPA UI (Dashboard, Order, RAG, LLM 관리) |
| **API Server** | ptm-api-server | FastAPI + SQLAlchemy | REST API, 인증, Order/RAG/LLM 관리, SSE |
| **MCP Server** | ptm-mcp-server | FastAPI + httpx | 외부 Bio API 게이트웨이 (캐싱, Rate Limiting) |
| **Worker - Preprocessing** | ptm-worker-preprocessing | Celery + pandas/numpy/scipy | Stage 1: PTM 데이터 전처리 |
| **Worker - RAG Enrichment** | ptm-worker-rag | Celery + MCP Client | Stage 2: 문헌/DB 기반 생물학적 보강 |
| **Worker - Report** | ptm-worker-report | Celery + LangGraph + ChromaDB | Stage 3: LLM 기반 연구 보고서 생성 |
| **MySQL** | ptm-mysql | MySQL 8.0 | Order, User, RAG Collection 메타데이터 |
| **Redis** | ptm-redis | Redis 7 Alpine | Celery Broker(DB1), Result(DB2), Pub/Sub(DB0), MCP Cache(DB3) |
| **ChromaDB** | ptm-chromadb | ChromaDB (latest) | 벡터 DB — RAG 문헌 검색용 |
| **Ollama** | Host 머신 직접 실행 | Ollama | 로컬 LLM (qwen2.5 등) |

## 디렉토리 구조

```
ptm-platform/
├── api-server/              # FastAPI API 서버
│   ├── app/
│   │   ├── api/             # 라우터 (health, orders, rag, llm, events)
│   │   ├── core/            # DB, Redis, Security, Logging
│   │   ├── models/          # SQLAlchemy 모델 (Order, User, Report, etc.)
│   │   ├── config.py        # 환경 설정 (pydantic-settings)
│   │   ├── dependencies.py  # Auth dependency (InternalUser 지원)
│   │   └── main.py          # FastAPI app 진입점
│   ├── Dockerfile
│   └── pyproject.toml
│
├── mcp-server/              # 외부 Bio API 게이트웨이
│   ├── app/
│   │   ├── tools/           # UniProt, KEGG, STRING-DB, InterPro, PubMed
│   │   └── main.py          # FastAPI app + 엔드포인트
│   ├── Dockerfile
│   └── pyproject.toml
│
├── workers/                 # Celery 워커 (3개 워커가 공유)
│   ├── celery_app.py        # Celery 앱 설정, 큐 라우팅
│   ├── common/              # 공유 모듈
│   │   ├── mcp_client.py    # MCP Server HTTP 클라이언트
│   │   ├── llm_client.py    # Ollama/OpenAI/Gemini 통합 클라이언트
│   │   └── progress.py      # Redis Pub/Sub 진행률 리포터
│   ├── preprocessing/       # Stage 1: 전처리
│   │   ├── tasks.py         # Celery task 정의
│   │   └── core/            # 핵심 분석 로직
│   │       ├── ptm_quantification.py
│   │       ├── unified_enricher.py
│   │       ├── biological_enricher.py
│   │       ├── enhanced_motif_analyzer_v2.py
│   │       └── config.py
│   ├── rag_enrichment/      # Stage 2: RAG 보강
│   │   ├── tasks.py
│   │   └── core/
│   │       ├── enrichment_pipeline.py
│   │       ├── regulation_extractor.py
│   │       └── report_generator.py
│   ├── report_generation/   # Stage 3: 리포트 생성
│   │   ├── tasks.py
│   │   └── core/
│   │       ├── graph.py              # LangGraph StateGraph
│   │       ├── rag_retriever.py      # ChromaDB 검색 + BM25
│   │       └── nodes/               # LangGraph 노드
│   │           ├── context_loader.py
│   │           ├── research_node.py
│   │           ├── hypothesis_node.py
│   │           ├── validation_node.py
│   │           ├── network_node.py   # Cytoscape 연동
│   │           ├── writer_node.py    # LLM 기반 섹션 작성
│   │           └── editor_node.py    # 최종 리포트 편집
│   ├── Dockerfile
│   └── pyproject.toml
│
├── frontend/                # React SPA
│   ├── src/
│   │   ├── pages/           # Dashboard, OrderList/Create/Detail, RAG, LLM, etc.
│   │   ├── components/      # Layout, Sidebar
│   │   ├── hooks/           # useSSE
│   │   └── lib/             # api.ts, types.ts
│   ├── Dockerfile
│   └── package.json
│
├── gateway/                 # Nginx 설정
│   └── nginx.conf
│
├── data/                    # 데이터 (Volume Mount)
│   ├── inputs/              # Order별 입력 파일 (pr, pg)
│   ├── reference/           # Reference 데이터 (FASTA 등)
│   │   └── mouse/           # Species별 Reference FASTA
│   └── outputs/             # 분석 결과 (TSV, MD)
│
├── storage/                 # 영속 스토리지 (Volume Mount)
│   ├── mysql/
│   ├── redis/
│   ├── chromadb/
│   ├── reports/             # 생성된 리포트
│   └── logs/
│
├── scripts/
│   └── init-db.sql          # MySQL 초기화 스크립트
│
├── docker-compose.yml
├── .env                     # 환경변수 (git 제외)
└── .env.example             # 환경변수 템플릿
```

## 데이터 흐름

```
1. 사용자가 Order 생성 (pd/pr 파일 업로드)
        │
        ▼
2. API Server → Celery로 preprocessing task 발행 (Queue: preprocessing)
        │
        ▼
3. Preprocessing Worker 실행
   ├── PTM Quantification (pandas/numpy/scipy)
   ├── Unified Enricher (MCP → UniProt, InterPro)
   ├── Biological Enricher (MCP → KEGG, STRING-DB)
   └── 결과: TSV 파일 생성 (data/outputs/{order_id}/)
        │
        ▼  (자동 체이닝)
4. RAG Enrichment Worker 실행
   ├── PubMed 검색 (MCP → NCBI/EuropePMC)
   ├── Pattern-based Regulation Extraction
   ├── Pathway/Network 분석 (MCP → KEGG, STRING)
   └── 결과: enriched JSON + MD 리포트 (data/outputs/{order_id}/)
        │
        ▼  (자동 체이닝)
5. Report Generation Worker 실행 (LangGraph)
   ├── Context Loading (TSV + enriched data)
   ├── Research (질문별 데이터 분석)
   ├── Hypothesis Generation (LLM)
   ├── Validation (ChromaDB RAG + LLM)
   ├── Network Analysis (Cytoscape 연동)
   ├── Section Writing (LLM + RAG)
   └── Final Report Editing & Compilation
        │
        ▼
6. 최종 Markdown 리포트 저장 (storage/reports/{order_id}/)
```

## 네트워크 구성

- 모든 서비스는 `ptm-platform-network` (Docker bridge)에서 통신
- Gateway만 외부 포트 노출: `:80`, `:443`
- Ollama, Cytoscape는 `host.docker.internal`을 통해 호스트 머신에 접근
- Cloudflare Tunnel(`cloudflared`)이 `localhost:80`을 `ptm.xformyx.com`으로 터널링

## Redis DB 할당

| DB | 용도 |
|----|------|
| 0 | 일반 캐시 + Pub/Sub (진행률 SSE) |
| 1 | Celery Broker (태스크 큐) |
| 2 | Celery Result Backend |
| 3 | MCP Server 캐시 (외부 API 응답) |
