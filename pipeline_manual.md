# PTM Platform Worker Pipeline Manual

## 1. 개요 (Overview)

PTM Platform은 복잡한 Proteomics 데이터를 분석하여 심층적인 생물학적 인사이트를 담은 리포트를 생성하는 자동화된 시스템입니다. 전체 분석 파이프라인은 세 개의 독립적인 Celery Worker로 구성되어 있으며, 각 Worker는 특정 단계를 순차적으로 수행합니다.

- **Preprocessing Worker**: 초기 데이터(Raw data)를 정량화하고 기본적인 주석(Annotation)을 추가합니다.
- **RAG Enrichment Worker**: Preprocessing된 데이터에 문헌 검색(RAG)을 통해 심층적인 생물학적 컨텍스트를 부여합니다.
- **Report Generation Worker**: RAG로 보강된 데이터를 기반으로, LLM과 네트워크 분석을 통해 최종 종합 분석 리포트를 생성합니다.

이 세 Worker는 Celery의 Task Queue와 Redis를 통해 비동기적으로 연결되어, 한 단계의 출력이 다음 단계의 입력으로 자동 전달되는 파이프라인을 구성합니다.

## 2. 파이프라인 흐름도 (Pipeline Flowchart)

아래 다이어그램은 PTM Platform의 전체 데이터 처리 흐름을 시각적으로 보여줍니다.

![PTM Platform Pipeline](pipeline_flowchart.png)

## 3. Worker 상세 설명 (Worker Details)

### 3.1. Preprocessing Worker

**목표**: Raw Proteomics 데이터(PR/PG Matrix, FASTA)를 분석 가능한 정규화된 PTM 데이터셋으로 변환합니다.

**진입점**: `workers/preprocessing/tasks.py`의 `run_preprocessing` 함수

**주요 프로세스**:

1.  **PTM Quantification (0-50%)**: `core/ptm_quantification.py`
    -   입력된 PR(Peptide Report), PG(Protein Group) Matrix를 로드하고 Median 정규화를 적용합니다.
    -   PTM Site의 상대적 정량 값(Log2 Fold Change)과 단백질 수준의 변화를 계산합니다.
    -   **주요 출력**: `ptm_vector_data_normalized_{ptm_mode}.tsv`, `all_protein_level_changes_normalized_{ptm_mode}.tsv`

2.  **Unified Enrichment (50-70%)**: `core/unified_enricher.py`
    -   정량화된 데이터에 단백질 도메인(InterPro) 및 서열 모티프(Motif) 정보를 추가합니다.
    -   `MCP-Server`를 통해 외부 데이터베이스 조회를 수행하고 결과를 캐시합니다.
    -   **주요 출력**: `unified_protein_data_enriched_{ptm_mode}.tsv`

3.  **Biological Enrichment (70-90%)**: `core/biological_enricher.py`
    -   `MCP-Server`를 통해 UniProt, STRING-DB, KEGG 등 주요 생물학적 데이터베이스의 정보를 통합합니다.
    -   단백질 기능, 세포 내 위치, 상호작용, 관련 경로 등의 주석을 추가합니다.
    -   **주요 출력**: `unified_protein_data_enriched_bio_enriched_{ptm_mode}.tsv`

**완료 후**: `RAG Enrichment Worker`를 위한 Celery Task(`rag_enrichment.tasks.run_rag_enrichment`)를 생성하여 파이프라인의 다음 단계로 데이터를 전달합니다.

### 3.2. RAG Enrichment Worker

**목표**: Preprocessing 단계에서 생성된 정량 데이터에 최신 연구 문헌 정보를 결합하여 생물학적 컨텍스트를 극대화합니다.

**진입점**: `workers/rag_enrichment/tasks.py`의 `run_rag_enrichment` 함수

**주요 프로세스**:

1.  **데이터 로딩 및 필터링 (0-10%)**:
    -   Preprocessing의 출력물인 `ptm_vector_data...tsv` 파일을 로드합니다.
    -   분석의 효율성을 위해 Log2FC 값을 기준으로 상위 N개의 주요 PTM 사이트를 선별합니다.

2.  **RAG Enrichment (10-70%)**: `core/enrichment_pipeline.py`
    -   선별된 각 PTM 사이트에 대해 `MCP-Server`를 통해 PubMed 문헌을 검색합니다.
    -   LLM을 사용하여 초록을 분석하고, 조절 관계(Kinase-Substrate), 기능적 영향 등을 예측합니다.
    -   HPA, GTEx, BioGRID 등 추가적인 데이터베이스 정보를 통합하여 풍부한 컨텍스트를 생성합니다.
    -   PTM 변화량과 단백질 변화량을 기준으로 각 PTM의 중요도를 8가지 카테고리로 자동 분류합니다.
    -   **주요 출력**: `enriched_ptm_data_{ptm_mode}.json`

3.  **Markdown 리포트 생성 (70-95%)**: `core/report_generator.py`
    -   Enrich된 모든 PTM 데이터를 종합하여 포괄적인 Markdown 형식의 1차 리포트를 생성합니다.
    -   여러 조건(Condition)의 데이터를 병합하여 비교 분석 테이블을 포함합니다.
    -   **주요 출력**: `comprehensive_report_{ptm_mode}.md`

**완료 후**: `Report Generation Worker`를 위한 Celery Task(`report_generation.tasks.run_report_generation`)를 생성하여 다음 단계로 데이터를 전달합니다.

### 3.3. Report Generation Worker

**목표**: RAG로 보강된 데이터와 사용자의 연구 질문을 바탕으로, LangGraph 기반의 자율 에이전트 시스템을 통해 최종 분석 리포트를 생성합니다.

**진입점**: `workers/report_generation/tasks.py`의 `run_report_generation` 함수

**주요 프로세스 (LangGraph 기반)**:

-   **StateGraph 정의**: `core/graph.py`에 정의된 `ReportState`라는 상태 객체를 통해 모든 노드(Node)가 데이터를 공유하며 파이프라인이 진행됩니다.

-   **주요 노드(Node) 실행 순서**:
    1.  `load_context`: RAG Enrichment 단계의 출력물(JSON, MD 파일)을 로드하고 분석을 준비합니다.
    2.  `generate_questions`: (필요시) LLM을 사용하여 데이터 기반의 연구 질문을 자동 생성합니다.
    3.  `research`: 각 연구 질문에 대해 관련 PTM 데이터를 분석하고 요약합니다.
    4.  `hypothesize`: 분석 결과를 바탕으로 'IF-THEN-BECAUSE' 형식의 가설을 생성합니다.
    5.  `validate_hypotheses`: 생성된 가설을 ChromaDB의 문헌 데이터를 통해 검증(RAG)하고 신뢰도 점수를 부여합니다.
    6.  `network_analysis`: Cytoscape REST API를 사용하여 PTM 상호작용 네트워크를 시각화하고 이미지를 생성합니다.
    7.  `write_sections`: 검증된 가설과 네트워크 분석 결과를 바탕으로, LLM이 리포트의 주요 섹션(초록, 서론, 결과, 토론, 결론)을 작성합니다.
    8.  `edit_report`: 모든 섹션, 그림, 표, 참고 문헌을 취합하여 최종 리포트(`final_report.md`, `.docx`)를 완성합니다.

**완료 후**: 최종 산출물인 `final_report.md`, `final_report.docx` 및 각종 이미지 파일(`*.png`)을 출력 디렉토리에 저장하고 파이프라인을 종료합니다.

## 4. 데이터 흐름 및 주요 파일

| 단계 (Worker) | 입력 파일 | 출력 파일 | 다음 단계로 전달 | 
| :--- | :--- | :--- | :--- |
| **Preprocessing** | `*.mzML`, `*.fasta` | `ptm_vector_data...tsv` | `ptm_vector_data...tsv` 파일 경로 |
| **RAG Enrichment** | `ptm_vector_data...tsv` | `enriched_ptm_data...json`<br>`comprehensive_report...md` | `enriched_json_path`, `md_report_path` |
| **Report Generation** | `enriched_ptm_data...json`<br>`comprehensive_report...md` | `final_report.md`<br>`final_report.docx`<br>`*.png` (네트워크 이미지) | (파이프라인 종료) |

## 5. 인프라 및 실행 환경

-   **Docker & Docker Compose**: 전체 시스템(API 서버, Worker, DB 등)은 `docker-compose.yml`에 정의된 9개의 서비스 컨테이너로 구성되어 격리된 환경에서 실행됩니다.
-   **Celery & Redis**: 세 Worker는 Celery를 통해 Task로 관리되며, Redis를 메시지 브로커(Message Broker)로 사용하여 Task를 각 Worker의 Queue(`preprocessing`, `rag_enrichment`, `report_generation`)에 분배하고 파이프라인을 연결합니다.
-   **MCP-Server**: 외부 생물학 데이터베이스(UniProt, KEGG, PubMed 등)와의 연동을 전담하는 중계 서버입니다. API 호출, 캐싱, 속도 제한을 관리하여 Worker의 부담을 줄입니다.
-   **LLM & RAG**: `LLMClient`를 통해 Ollama, OpenAI, Gemini 등 다양한 LLM을 선택적으로 사용하며, `RAGRetriever`가 ChromaDB 벡터 데이터베이스에서 관련 문헌을 검색하여 LLM의 답변을 보강합니다.
