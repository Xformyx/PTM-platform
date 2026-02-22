# PTM Analysis Platform — Pipeline Guide

## 파이프라인 개요

Order가 시작되면 3단계 파이프라인이 **자동으로 체이닝**되어 순차 실행됩니다.

```
Order Start
    │
    ▼
┌─────────────────────────────────┐
│  Stage 1: Preprocessing         │  Queue: preprocessing
│  입력: pd, pr, fasta 파일       │
│  출력: TSV 파일                 │
│  시간: 2~10분                   │
└─────────────┬───────────────────┘
              │ (자동 체이닝)
              ▼
┌─────────────────────────────────┐
│  Stage 2: RAG Enrichment        │  Queue: rag_enrichment
│  입력: TSV 파일                 │
│  출력: enriched JSON + MD       │
│  시간: 5~20분                   │
└─────────────┬───────────────────┘
              │ (자동 체이닝)
              ▼
┌─────────────────────────────────┐
│  Stage 3: Report Generation     │  Queue: report_generation
│  입력: TSV + enriched data      │
│  출력: 최종 MD 리포트           │
│  시간: 10~30분                  │
└─────────────────────────────────┘
```

---

## Stage 1: Preprocessing

**Celery Task:** `preprocessing.tasks.run_preprocessing`
**Queue:** `preprocessing`
**Worker:** `ptm-worker-preprocessing`

### 처리 과정

1. **PTM Quantification** (`ptm_quantification.py`)
   - pd/pr 파일 (Proteome Discoverer 출력) 로드
   - 샘플 그룹별 평균, fold-change, p-value 계산
   - 통계적 유의성 필터링
   - phospho-site/ubiquitin-site 매핑

2. **Unified Enrichment** (`unified_enricher.py`)
   - MCP Server를 통한 UniProt 단백질 정보 조회
   - InterPro 도메인/모티프 매핑
   - Enhanced Motif Analysis (phosphorylation motif 패턴)
   - 배치 처리로 효율화

3. **Biological Enrichment** (`biological_enricher.py`)
   - MCP Server를 통한 KEGG 경로 분석
   - STRING-DB 단백질 상호작용 네트워크
   - 기능 분류 및 주석(annotation)

### 출력 파일

```
data/outputs/{order_id}/
├── quantification_results.tsv    # 정량 분석 결과
├── enriched_results.tsv          # 도메인/모티프 보강된 결과
└── biological_enrichment.tsv     # 생물학적 경로 보강 결과
```

### 진행률 보고

Redis Pub/Sub 채널 `order:{order_id}:progress`로 실시간 진행률 전송:
- 0~30%: PTM Quantification
- 30~60%: Unified Enrichment
- 60~90%: Biological Enrichment
- 90~100%: 결과 저장 및 Stage 2 체이닝

---

## Stage 2: RAG Enrichment

**Celery Task:** `rag_enrichment.tasks.run_rag_enrichment`
**Queue:** `rag_enrichment`
**Worker:** `ptm-worker-rag`

### 처리 과정

1. **TSV 로드 & Top-N PTM 선택**
   - Preprocessing 결과 TSV 로드
   - fold-change, p-value 기준 상위 N개 PTM 선택

2. **PubMed 문헌 검색** (`enrichment_pipeline.py`)
   - MCP Server의 다중 티어 검색 전략:
     - Tier 1: Gene + PTM type + position
     - Tier 2: Gene + PTM type
     - Tier 3: Gene + general PTM
   - 유전자 별명(alias) 확장 검색
   - 관련성 점수 기반 필터링

3. **Pattern-based Regulation Extraction** (`regulation_extractor.py`)
   - 문헌 초록에서 정규식 패턴으로 조절 관계 추출
   - 상향/하향 조절, 활성화/억제 패턴 인식
   - LLM 없이 패턴 기반으로 동작 (정확도 + 속도)

4. **Pathway & Network 통합**
   - KEGG 경로 정보 통합
   - STRING-DB 상호작용 정보 통합
   - UniProt 기능 정보 보강

5. **MD 리포트 생성** (`report_generator.py`)
   - 중간 보고서 (문헌 증거, 조절 네트워크, 경로 분석 등)

### 출력 파일

```
data/outputs/{order_id}/
├── enrichment_results.json       # 보강된 PTM 데이터 (구조화)
└── enrichment_report.md          # 중간 MD 리포트
```

### LLM 사용 여부

Stage 2에서는 **LLM을 사용하지 않습니다**. 모든 분석은 패턴 매칭, 통계, 외부 DB 조회로 수행됩니다.

---

## Stage 3: Report Generation

**Celery Task:** `report_generation.tasks.run_report_generation`
**Queue:** `report_generation`
**Worker:** `ptm-worker-report`

### LangGraph 파이프라인

7개 노드로 구성된 LangGraph StateGraph가 순차 실행됩니다.

```
context_loader → research → hypothesis → validation → network → writer → editor
```

#### 1. Context Loader (`context_loader.py`)
- Stage 1/2 결과물 (TSV + JSON) 로드
- 연구 질문 자동 생성 (PTM 데이터 기반)
- ReportState 초기화

#### 2. Research Node (`research_node.py`)
- 연구 질문별 관련 PTM 데이터 분석
- 키워드 추출, 경로 매핑
- 조절 패턴 식별

#### 3. Hypothesis Node (`hypothesis_node.py`)
- **LLM 사용**: IF-THEN-BECAUSE 형식의 가설 생성
- LLM 미사용 시 규칙 기반 fallback

#### 4. Validation Node (`validation_node.py`)
- **ChromaDB RAG 검색**: 가설 관련 문헌 검색
- **LLM 사용**: 증거 기반 가설 검증 (supported/partially/unsupported)
- BM25 reranking으로 검색 품질 향상

#### 5. Network Node (`network_node.py`)
- Temporal signaling network 분석
- **Cytoscape 연동** (Option A: `host.docker.internal:1234`)
  - py4cytoscape로 네트워크 생성/스타일링
  - PNG 이미지 내보내기
- Cytoscape 미실행 시 텍스트 기반 네트워크 범례 생성

#### 6. Writer Node (`writer_node.py`)
- **LLM + RAG 사용**: 보고서 섹션 작성
  - Abstract, Introduction, Results, Discussion, Conclusion
- ChromaDB에서 관련 문헌 검색 후 LLM에 컨텍스트 제공
- LLM 오류 시 데이터 기반 fallback 섹션 생성

#### 7. Editor Node (`editor_node.py`)
- 전체 섹션 통합
- 메타데이터 (생성 일시, 모델 정보) 추가
- 네트워크 그림 참조 삽입
- 참고문헌 목록 생성
- 최종 Markdown 리포트 컴파일

### 출력 파일

```
storage/reports/{order_id}/
└── final_report.md               # 최종 연구 보고서
```

### LLM Client 추상화

`common/llm_client.py`의 `LLMClient` 클래스:

| Provider | 모델 예시 | 설정 |
|----------|----------|------|
| **ollama** (기본) | qwen2.5:7b, qwen2.5:32b | `OLLAMA_URL` |
| openai | gpt-4o, gpt-4o-mini | `OPENAI_API_KEY` |
| gemini | gemini-2.0-flash | `GEMINI_API_KEY` |

### ChromaDB RAG Retriever

`report_generation/core/rag_retriever.py`:

- 다중 컬렉션 동시 검색
- cosine similarity 기반 필터링
- BM25 reranking (rank-bm25)
- 가설 검증용 / 섹션 작성용 특화 검색 메서드

---

## 태스크 체이닝 메커니즘

각 단계 완료 시 `celery.current_app.send_task()`로 다음 단계를 자동 발행합니다.

```python
# preprocessing/tasks.py 마지막 부분
current_app.send_task(
    "rag_enrichment.tasks.run_rag_enrichment",
    args=[order_id],
    queue="rag_enrichment",
)

# rag_enrichment/tasks.py 마지막 부분
current_app.send_task(
    "report_generation.tasks.run_report_generation",
    args=[order_id],
    queue="report_generation",
)
```

각 워커는 지정된 큐만 consume하므로 태스크가 올바른 워커에서 실행됩니다:
- `ptm-worker-preprocessing`: Queue `preprocessing`
- `ptm-worker-rag`: Queue `rag_enrichment`
- `ptm-worker-report`: Queue `report_generation`

---

## 진행률 모니터링

모든 단계에서 Redis Pub/Sub로 진행률을 보고합니다.

```python
# workers/common/progress.py
def publish_progress(order_id, stage, step, progress, message):
    redis.publish(f"order:{order_id}:progress", json.dumps({
        "stage": stage,
        "step": step,
        "progress": progress,
        "message": message,
    }))
```

API Server의 SSE 엔드포인트 (`/api/events/orders/{order_id}`)가
이 채널을 구독하여 프론트엔드에 실시간 스트리밍합니다.

---

## MCP Server 역할

외부 Bio 데이터베이스 API 호출을 **중앙 집중화**합니다.

| 기능 | 외부 API | 용도 |
|------|---------|------|
| UniProt | uniprot.org REST API | 단백질 서열, 기능, 위치 정보 |
| KEGG | rest.kegg.jp | 대사/신호 경로 매핑 |
| STRING-DB | string-db.org API | 단백질 상호작용 네트워크 |
| InterPro | ebi.ac.uk InterPro API | 도메인, 모티프, 패밀리 분류 |
| PubMed | NCBI E-utilities + Europe PMC | 관련 문헌 검색/메타데이터 |
| Gene Alias | MyGene.info | 유전자 별명/심볼 조회 |

MCP Server는 **Redis(DB3)에 응답을 캐싱**하여 중복 호출을 방지하고,
rate limiting으로 외부 API 사용량을 제어합니다.
