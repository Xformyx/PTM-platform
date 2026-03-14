# PTM Platform Worker Pipeline Manual

**Version**: 1.0  
**Date**: 2026-03-15  
**Author**: Manus AI

---

## 1. 개요

PTM Platform은 대규모 Proteomics 실험 데이터로부터 번역 후 변형(Post-Translational Modification, PTM) 패턴을 분석하고, 최신 연구 문헌과 결합하여 종합적인 과학 리포트를 자동 생성하는 시스템입니다. 전체 분석 파이프라인은 세 개의 독립적인 **Celery Worker**로 구성되어 있으며, 각 Worker는 고유한 역할을 수행하면서 순차적으로 연결됩니다.

| Worker | 역할 | Celery Queue |
| :--- | :--- | :--- |
| **Preprocessing Worker** | Raw 데이터 정량화 및 생물학적 주석(Annotation) 추가 | `preprocessing` |
| **RAG Enrichment Worker** | 문헌 검색(RAG)을 통한 심층 생물학적 컨텍스트 부여 | `rag_enrichment` |
| **Report Generation Worker** | LLM 기반 최종 종합 분석 리포트 생성 | `report_generation` |

세 Worker는 **Celery Task Queue**와 **Redis** 메시지 브로커를 통해 비동기적으로 연결됩니다. 한 단계가 완료되면 `app.send_task()`를 호출하여 다음 Worker의 Queue에 새로운 Task를 자동으로 생성하고, 이전 단계의 출력 파일 경로와 설정 정보를 `config` 딕셔너리로 전달합니다. 이러한 구조 덕분에 각 Worker는 독립적으로 스케일링이 가능하며, 특정 단계만 재실행하는 것도 지원됩니다.

---

## 2. 파이프라인 흐름도

아래 다이어그램은 PTM Platform의 전체 데이터 처리 흐름을 시각적으로 보여줍니다. 분홍색 노드는 각 단계의 진입점을, 녹색 노드는 최종 산출물을 나타냅니다.

![PTM Platform Pipeline Flowchart](pipeline_flowchart.png)

---

## 3. Stage 1: Preprocessing Worker

### 3.1. 목표

사용자가 업로드한 Raw Proteomics 데이터(PR Matrix, PG Matrix, FASTA)를 분석 가능한 **정규화된 PTM 데이터셋**으로 변환합니다. 이 단계에서 PTM 사이트별 상대적 정량 값(Log2 Fold Change)을 계산하고, 단백질 도메인, 모티프, 생물학적 경로 등의 기본 주석을 추가합니다.

### 3.2. 진입점

`workers/preprocessing/tasks.py` 파일의 `run_preprocessing(order_id, config)` 함수가 Celery Task로 등록되어 있습니다. API 서버가 사용자의 Order 생성 요청을 받으면 이 Task를 `preprocessing` Queue에 전송하여 파이프라인을 시작합니다.

### 3.3. 입력 데이터

| 파라미터 | 설명 | 필수 |
| :--- | :--- | :---: |
| `pr_matrix_path` | Peptide Report Matrix 파일 경로 (TSV) | O |
| `pg_matrix_path` | Protein Group Matrix 파일 경로 (TSV) | O |
| `fasta_path` | UniProt FASTA 파일 경로 | O |
| `config_xlsx_path` | 샘플-조건 매핑 설정 파일 (Excel) | X |
| `ptm_mode` | PTM 분석 모드: `phospho` 또는 `ubi` | O |
| `condition_map` | 파일명-조건 매핑 딕셔너리 | X |
| `species_tax_id` | NCBI Taxonomy ID (기본값: `10090`, Mouse) | X |
| `kegg_organism` | KEGG 생물종 코드 (기본값: `mmu`) | X |
| `analysis_options` | Downsampling 모드 및 설정 | X |

### 3.4. 내부 프로세스

Preprocessing Worker는 4개의 순차적 Step으로 구성되며, 각 Step의 출력 파일이 이미 존재하면 해당 Step을 건너뜁니다(Idempotent 설계).

**Step 1: PTM Quantification (0% - 50%)**

`core/ptm_quantification.py`의 `PTMQuantificationAnalyzer` 클래스가 담당합니다. FASTA 파일에서 단백질 서열 정보를 로드한 후, PR/PG Matrix에 Median Normalization을 적용합니다. 이후 PTM 사이트별 상대적 정량 값(PTM Relative Log2FC)과 단백질 수준의 변화(Protein Log2FC)를 계산하고, 조건(Condition) 간 비교 분석을 수행합니다. 또한 `EnhancedMotifAnalyzerV2`를 사용하여 PTM 사이트 주변의 서열 모티프를 분석합니다.

> **핵심 출력**: `ptm_vector_data_normalized_{phospho|ubi}.tsv`, `all_protein_level_changes_normalized_{phospho|ubi}.tsv`

**Step 1b: PTM Vector Report (52% - 55%)**

`core/ptm_vector_report_generator.py`의 `PTMVectorReportGenerator`가 PTM Vector 데이터를 기반으로 2D Scatter Plot(PTM Log2FC vs Protein Log2FC)을 생성합니다. 이 시각화는 PTM 변화가 단백질 발현 변화와 독립적인지(PTM-driven) 또는 연동되는지(Protein-driven)를 직관적으로 보여줍니다.

> **핵심 출력**: `ptm_vector_report_*.png`, `ptm_vector_summary_report*.png`

**Step 2: Unified Enrichment (50% - 70%)**

`core/unified_enricher.py`의 `UnifiedProteinEnricher` 클래스가 담당합니다. MCP-Server를 통해 InterPro 데이터베이스에서 단백질 도메인 정보를 조회하고, 15종 이상의 Kinase 인식 모티프 패턴(PKA, PKC, CK2, CDK, MAPK 등)을 서열 기반으로 매칭합니다. 이를 통해 각 PTM 사이트에 대한 잠재적 조절 Kinase를 예측합니다.

> **핵심 출력**: `unified_protein_data_enriched_{phospho|ubi}.tsv`

**Step 3: Biological Enrichment (70% - 90%)**

`core/biological_enricher.py`의 `BiologicalEnricher` 클래스가 담당합니다. MCP-Server를 통해 세 가지 주요 생물학적 데이터베이스의 정보를 통합합니다.

| 데이터베이스 | 추가되는 정보 |
| :--- | :--- |
| **UniProt** | 세포 내 위치(Subcellular Localization), 단백질 기능 요약, GO Terms (BP, MF, CC) |
| **STRING-DB** | 단백질-단백질 상호작용 파트너 및 상호작용 점수 |
| **KEGG** | 관련 대사/신호전달 경로(Pathway) 목록 |

Downsampling 옵션이 설정된 경우, 이 단계에서 분석 대상 단백질 수를 줄여 처리 시간을 단축합니다. PTM 사이트가 있는 단백질은 항상 유지되며, Non-PTM 단백질만 필터링됩니다.

> **핵심 출력**: `unified_protein_data_enriched_bio_enriched_{phospho|ubi}.tsv`

**Step 4: Finalization (90% - 100%)**

모든 출력 파일 목록을 정리하고 처리 시간을 기록합니다. `chain_to_next` 설정이 `True`(기본값)이면 다음 단계인 RAG Enrichment Worker로 자동 전환됩니다.

### 3.5. 다음 단계로의 전달

Preprocessing이 완료되면 `app.send_task("rag_enrichment.tasks.run_rag_enrichment")`를 호출하여 RAG Enrichment Worker에 다음 정보를 전달합니다.

```python
rag_config = {
    "order_code": order_code,
    "preprocessing_output_dir": str(order_output),   # Stage 1 출력 디렉토리
    "ptm_mode": ptm_mode,                            # phospho | ubi
    "experimental_context": {...},                    # 실험 조건 정보
    "top_n_ptms": 50,                                # 상위 N개 PTM 선별 수
    "chromadb_collections": [...],                    # ChromaDB 컬렉션 목록
    "llm_provider": "ollama",                        # LLM 제공자
    "llm_model": "gemma3:27b",                       # LLM 모델명
    "report_title": "PTM Comprehensive Analysis Report",
}
```

---

## 4. Stage 2: RAG Enrichment Worker

### 4.1. 목표

Preprocessing 단계에서 생성된 정량 데이터에 **최신 연구 문헌 정보**를 결합하여 각 PTM 사이트의 생물학적 컨텍스트를 극대화합니다. PubMed 문헌 검색, LLM 기반 초록 분석, 다중 데이터베이스 통합을 통해 풍부한 메타데이터를 생성하고, 이를 바탕으로 1차 종합 리포트(Markdown)를 작성합니다.

### 4.2. 진입점

`workers/rag_enrichment/tasks.py` 파일의 `run_rag_enrichment(order_id, config)` 함수입니다. Preprocessing Worker가 완료 시 자동으로 호출합니다.

### 4.3. 입력 데이터

| 파라미터 | 설명 | 출처 |
| :--- | :--- | :--- |
| `preprocessing_output_dir` | Stage 1 출력 디렉토리 경로 | Preprocessing Worker |
| `ptm_mode` | PTM 분석 모드 | 사용자 설정 |
| `experimental_context` | 실험 조건 (조직, 처리, 생물종 등) | 사용자 입력 |
| `top_n_ptms` | 분석할 상위 PTM 수 (기본값: 50) | 사용자 설정 |
| `chromadb_collections` | ChromaDB 컬렉션 목록 | 사용자 선택 |
| `llm_provider` / `llm_model` | LLM 설정 | 사용자 선택 |

### 4.4. 내부 프로세스

**Step 1: 데이터 로딩 및 Top-N PTM 선별 (0% - 10%)**

Preprocessing의 출력물인 `ptm_vector_data_normalized_{ptm_mode}.tsv`를 로드합니다. 분석의 효율성과 비용을 관리하기 위해, 모든 조건(Condition)에 걸쳐 최대 |PTM_Relative_Log2FC| 값을 기준으로 상위 N개의 고유 PTM 사이트를 선별합니다. 선별된 PTM의 모든 조건 데이터는 유지되어 다중 조건 비교가 가능합니다.

**Step 2: RAG Enrichment Pipeline (10% - 70%)**

`core/enrichment_pipeline.py`의 `RAGEnrichmentPipeline` 클래스가 핵심 로직을 담당합니다. 선별된 각 PTM 사이트에 대해 아래의 18단계 분석을 수행합니다.

| 순서 | 분석 항목 | 데이터 소스 | 방식 |
| :---: | :--- | :--- | :--- |
| 1 | PubMed 문헌 검색 | PubMed (MCP) | Multi-tier 검색 |
| 2 | 조절 관계 추출 | PubMed 초록 | 패턴 매칭 |
| 3 | KEGG 경로 조회 | KEGG (MCP) | API |
| 4 | STRING-DB 상호작용 | STRING-DB (MCP) | API |
| 5 | UniProt 단백질 정보 | UniProt (MCP) | API |
| 6 | HPA 조직 발현 | HPA (Local/MCP) | Local-first |
| 7 | GTEx 조직 발현 | GTEx (Local/MCP) | Local-first |
| 8 | BioGRID 상호작용 | BioGRID (MCP) | API |
| 9 | LLM 초록 분석 | PubMed 초록 | LLM |
| 10 | LLM Kinase 예측 | 문헌 + 컨텍스트 | LLM |
| 11 | LLM 기능적 영향 분석 | 문헌 + 경로 | LLM |
| 12 | PMC 전문(Full-text) 분석 | PMC (MCP) | 패턴 매칭 |
| 13 | PTM 검증/신규성 평가 | iPTMnet (MCP) | API |
| 14 | 조절 관계 병합 | KEGG + PubMed | 통합 |
| 15 | 8-Category 분류 | PTM/Protein Log2FC | 규칙 기반 |
| 16 | 시계열 궤적 추출 | 다중 조건 데이터 | 계산 |
| 17 | Isoform 정보 추출 | UniProt | 파싱 |
| 18 | Enrichment 결과 조립 | 전체 | 통합 |

**8-Category Cell-Signaling 분류 시스템**은 PTM Log2FC와 Protein Log2FC의 조합을 기반으로 각 PTM 사이트의 생물학적 의미를 자동으로 분류합니다.

| 분류 | PTM 변화 | 단백질 변화 | 의미 |
| :--- | :---: | :---: | :--- |
| PTM-driven hyperactivation | 강한 상승 | 안정 | PTM에 의한 과활성화 |
| PTM-driven inactivation | 강한 하강 | 안정 | PTM에 의한 비활성화 |
| Compensatory PTM hyperactivation | 강한 상승 | 하강 | 보상적 PTM 과활성화 |
| Synergistic activation | 상승 | 상승 | 시너지 활성화 |
| Synergistic suppression | 하강 | 하강 | 시너지 억제 |
| Protein-driven (PTM passive) | 약함 | 변화 | 단백질 주도 변화 |
| Discordant regulation | 상승 | 하강 (또는 반대) | 불일치 조절 |
| Baseline / low-change state | 약함 | 안정 | 기저 상태 |

**Step 3: Markdown 리포트 생성 (70% - 95%)**

`core/report_generator.py`의 `ComprehensiveReportGenerator`가 Enrich된 모든 PTM 데이터를 종합하여 포괄적인 Markdown 형식의 **1차 종합 리포트**를 생성합니다. 다중 조건 데이터는 `core/ptm_merger.py`의 `merge_multi_condition_ptms()`를 통해 동일 유전자+위치 기준으로 병합되어, 조건 간 비교 테이블과 시계열 궤적이 자동 생성됩니다.

> **핵심 출력**: `enriched_ptm_data_{ptm_mode}.json`, `comprehensive_report_{ptm_mode}.md`

### 4.5. 다음 단계로의 전달

RAG Enrichment가 완료되면 `app.send_task("report_generation.tasks.run_report_generation")`를 호출하여 Report Generation Worker에 다음 정보를 전달합니다.

```python
report_config = {
    "order_code": order_code,
    "rag_output_dir": str(order_output),
    "enriched_json_path": str(enriched_json_path),   # Stage 2 JSON 출력
    "md_report_path": str(md_path),                  # Stage 2 MD 리포트
    "experimental_context": {...},
    "research_questions": [...],                     # 사용자 연구 질문
    "chromadb_collections": [...],
    "llm_provider": "ollama",
    "llm_model": "gemma3:27b",
    "report_title": "PTM Comprehensive Analysis Report",
}
```

---

## 5. Stage 3: Report Generation Worker

### 5.1. 목표

RAG로 보강된 데이터와 사용자의 연구 질문을 바탕으로, **LangGraph StateGraph** 기반의 자율 에이전트 시스템을 통해 학술 논문 수준의 최종 종합 분석 리포트를 생성합니다. 가설 생성 및 검증, 네트워크 시각화, LLM 기반 섹션 작성, 인용 포맷팅까지 전 과정을 자동화합니다.

### 5.2. 진입점

`workers/report_generation/tasks.py` 파일의 `run_report_generation(order_id, config)` 함수입니다. RAG Enrichment Worker가 완료 시 자동으로 호출합니다.

### 5.3. 입력 데이터

| 파라미터 | 설명 | 출처 |
| :--- | :--- | :--- |
| `enriched_json_path` | Stage 2의 Enriched PTM JSON 파일 경로 | RAG Enrichment Worker |
| `md_report_path` | Stage 2의 종합 MD 리포트 경로 | RAG Enrichment Worker |
| `research_questions` | 사용자 정의 연구 질문 목록 | 사용자 입력 / AI 생성 |
| `chromadb_collections` | ChromaDB 컬렉션 목록 (가설 검증용) | 사용자 선택 |
| `llm_provider` / `llm_model` | LLM 설정 | 사용자 선택 |
| `report_type` | 리포트 유형: `comprehensive` 또는 `extended` | 사용자 선택 |

### 5.4. LangGraph StateGraph 구조

Report Generation Worker의 핵심은 `core/graph.py`에 정의된 **LangGraph StateGraph**입니다. `ReportState`라는 TypedDict 상태 객체를 통해 모든 노드가 데이터를 공유하며, 아래의 11개 노드가 순차적으로 실행됩니다.

```
load_context → generate_questions → research → hypothesize
  → validate_hypotheses → network_analysis → write_sections
  → generate_qa_report → drug_repositioning → format_citations
  → edit_report → END
```

### 5.5. 노드별 상세 설명

**Node 1: `load_context` (2% - 5%)**

`nodes/context_loader.py`가 담당합니다. Stage 2의 출력물인 `enriched_ptm_data.json`과 `comprehensive_report.md`를 로드하고, PTM 데이터를 구조화된 형식으로 파싱합니다. 연구 질문이 제공되지 않은 경우 데이터 기반으로 기본 질문을 자동 생성합니다.

> **State 업데이트**: `parsed_ptms`, `comprehensive_summary`, `research_questions`

**Node 2: `generate_questions` (5% - 10%)**

`nodes/question_generator.py`가 담당합니다. LLM을 사용하여 PTM 데이터와 종합 리포트 내용을 분석하고, 7가지 카테고리(temporal_pathway, ecm_context, pathway_crosstalk, kinase_phosphatase, adaptation_mechanism, network, novelty)에 걸친 연구 질문을 자동 생성합니다. 각 질문은 실제 데이터의 특정 단백질과 PTM 사이트를 참조해야 합니다.

> **State 업데이트**: `research_questions`, `ai_questions_metadata`

**Node 3: `research` (10% - 30%)**

`nodes/research_node.py`가 담당합니다. 각 연구 질문에 대해 관련 PTM 데이터를 필터링하고, 활성화/억제된 PTM 패턴, 경로 농축(Pathway Enrichment), 조절 패턴을 분석합니다. 이 결과는 가설 생성의 근거 자료로 사용됩니다.

> **State 업데이트**: `research_results`

**Node 4: `hypothesize` (30% - 40%)**

`nodes/hypothesis_node.py`가 담당합니다. 연구 분석 결과를 바탕으로 **IF-THEN-BECAUSE** 형식의 구조화된 가설을 생성합니다. LLM이 사용 가능한 경우 LLM 기반으로, 그렇지 않으면 규칙 기반(Rule-based)으로 가설을 생성합니다. 각 가설에는 지지 PTM 목록과 검증 가능한 예측이 포함됩니다.

> **State 업데이트**: `hypotheses`

**Node 5: `validate_hypotheses` (40% - 55%)**

`nodes/validation_node.py`가 담당합니다. 생성된 각 가설을 **ChromaDB 벡터 데이터베이스**의 문헌 데이터를 통해 검증합니다. `RAGRetriever`가 가설과 관련된 문헌을 검색하고, LLM이 각 문헌 증거를 "supporting", "contradicting", "neutral"로 분류합니다. 최종적으로 각 가설에 신뢰도 점수(Validity Score)가 부여됩니다.

> **State 업데이트**: `validated_hypotheses`

**Node 6: `network_analysis` (55% - 65%)**

`nodes/network_node.py`가 담당합니다. PTM 데이터를 기반으로 단백질 상호작용 네트워크를 구축하고, 호스트 머신에서 실행 중인 **Cytoscape Desktop**의 CyREST API(`host.docker.internal:1234`)를 통해 네트워크를 시각화합니다. 활성화/억제 상태에 따라 노드 색상이 결정되며, STRING-DB, KEGG, Literature 등 상호작용 유형에 따라 엣지 색상이 구분됩니다. 생성된 네트워크 이미지(PNG)는 최종 리포트에 포함됩니다.

> **State 업데이트**: `network_analysis`, `network_results`

**Node 7: `write_sections` (70% - 85%)**

`nodes/writer_node.py`가 담당합니다. 검증된 가설, 네트워크 분석 결과, ChromaDB 문헌 컨텍스트를 종합하여 LLM이 리포트의 주요 섹션을 작성합니다. 각 섹션은 독립적으로 생성되며, Anti-Hallucination 시스템(v98)이 LLM 출력을 실제 데이터와 대조 검증합니다.

| 섹션 | 최대 토큰 | 주요 내용 |
| :--- | :---: | :--- |
| **Abstract** | 6,144 | 연구 요약, 주요 발견, 결론 |
| **Introduction** | 12,288 | 실험 배경, 연구 목적, 관련 문헌 |
| **Results** | 16,384 | PTM 분석 결과, 통계, 경로 분석 |
| **Discussion** | 12,288 | 결과 해석, 기존 연구와의 비교 |
| **Conclusion** | 8,192 | 핵심 발견 요약, 향후 연구 방향 |

> **State 업데이트**: `sections`, `collected_references`

**Node 8: `generate_qa_report` (85% - 88%)**

`nodes/qa_report_node.py`가 담당합니다. 2-Pass 접근법으로 Q&A 형식의 보조 리포트를 생성합니다. Pass 1에서는 개별 PTM에 대한 상세 Q&A(PTM당 9-10개)를, Pass 2에서는 전체 데이터에 걸친 글로벌 Cell-Signaling 트렌드 Q&A(10-15개)를 생성합니다.

> **State 업데이트**: `qa_report`, `qa_questions`

**Node 9: `drug_repositioning` (88% - 95%)**

`nodes/drug_repositioning_node.py`가 담당합니다. `report_type`이 `extended`인 경우에만 실행됩니다. PTM 분석 결과를 기반으로 약물 재배치(Drug Repositioning) 후보를 탐색하고 점수를 매깁니다.

> **State 업데이트**: `drug_repositioning_results`

**Node 10: `format_citations` (95% - 97%)**

`core/citation_formatter.py`의 `CitationFormatter`와 `ReportPostProcessor`가 담당합니다. 모든 섹션을 조합하고, Results와 Discussion 사이에 Network Visualization 섹션을 삽입합니다. 인라인 인용([N])을 정규화하고, Vancouver 스타일의 참고문헌 목록을 생성합니다. 또한 빈 섹션 제거, 헤딩 정규화 등의 후처리를 수행합니다.

> **State 업데이트**: `final_report`, `citation_data`

**Node 11: `edit_report` (97% - 100%)**

`nodes/editor_node.py`가 담당합니다. 최종 리포트를 `final_report.md`로 저장하고, 네트워크 이미지 파일을 출력 디렉토리에 복사합니다. 이후 `common/report_postprocessor.py`의 `postprocess_full_report()`가 PTM 용어 교정, 인용 삽입, 가짜 참고문헌 제거 등의 최종 후처리를 수행하고, `common/markdown_to_docx.py`의 `convert_report_to_docx()`가 Word 문서(.docx)로 변환합니다.

> **최종 출력**: `final_report.md`, `final_report.docx`, `*.png` (네트워크 이미지)

---

## 6. Worker 간 데이터 흐름 요약

아래 표는 세 Worker 간에 전달되는 핵심 데이터의 흐름을 정리한 것입니다.

| 전달 구간 | 전달 방식 | 핵심 전달 데이터 | 데이터 형식 |
| :--- | :--- | :--- | :--- |
| **Preprocessing → RAG Enrichment** | Celery `send_task()` | `preprocessing_output_dir` (TSV 파일 경로) | 파일 경로 (String) |
| **RAG Enrichment → Report Generation** | Celery `send_task()` | `enriched_json_path`, `md_report_path` | 파일 경로 (String) |

모든 Worker는 공유 볼륨(`./data:/app/data`)을 통해 동일한 파일 시스템에 접근하므로, 파일 경로만 전달하면 다음 Worker가 해당 파일을 직접 읽을 수 있습니다.

### 6.1. 공유 인프라 서비스

| 서비스 | 용도 | Worker 사용 |
| :--- | :--- | :--- |
| **Redis** | Celery 브로커, 진행률 SSE Pub/Sub, MCP 캐시 | 전체 |
| **MySQL** | Order 상태, 진행률, 로그 저장 | 전체 |
| **ChromaDB** | 문헌 벡터 DB (가설 검증, 섹션 작성용 RAG) | RAG, Report |
| **MCP-Server** | 외부 API 중계 (PubMed, UniProt, KEGG 등) | Preprocessing, RAG |
| **Ollama / LLM** | 텍스트 생성 (초록 분석, 가설, 섹션 작성) | RAG, Report |
| **Cytoscape Desktop** | 네트워크 시각화 (호스트 머신에서 실행) | Report |

### 6.2. 진행률 보고 체계

모든 Worker는 `common/progress.py`의 `publish_progress()` 함수를 통해 실시간 진행률을 보고합니다. 이 함수는 세 가지 채널로 동시에 진행 상황을 전파합니다.

1. **MySQL `orders` 테이블**: `progress_pct`, `stage_detail`, `current_stage` 컬럼 업데이트
2. **MySQL `order_logs` 테이블**: 모든 진행 이벤트를 시계열로 기록 (감사 추적용)
3. **Redis Pub/Sub**: `order:progress:{order_id}` 채널로 JSON 메시지 발행 (프론트엔드 SSE 실시간 스트리밍용)

---

## 7. 인프라 구성

### 7.1. Docker Compose 서비스 구성

PTM Platform은 `docker-compose.yml`에 정의된 **10개의 서비스 컨테이너**로 구성됩니다.

| 서비스 | 컨테이너명 | 역할 |
| :--- | :--- | :--- |
| `mysql` | ptm-mysql | 관계형 데이터베이스 (Order, Log 저장) |
| `redis` | ptm-redis | 메시지 브로커, 캐시, Pub/Sub |
| `chromadb` | ptm-chromadb | 벡터 데이터베이스 (문헌 임베딩) |
| `api-server` | ptm-api-server | FastAPI REST API 서버 |
| `mcp-server` | ptm-mcp-server | 외부 API 중계 서버 |
| `celery-worker-preprocessing` | ptm-worker-preprocessing | Preprocessing Worker |
| `celery-worker-rag` | ptm-worker-rag | RAG Enrichment Worker |
| `celery-worker-report` | ptm-worker-report | Report Generation Worker |
| `frontend` | ptm-frontend | React 프론트엔드 |
| `gateway` | ptm-gateway | Nginx 리버스 프록시 |

### 7.2. 네트워크 및 외부 연결

모든 컨테이너는 `ptm-platform-network`라는 Docker Bridge 네트워크를 공유합니다. 호스트 머신에서 실행되는 **Cytoscape Desktop**과 **Ollama**에 접근하기 위해 `host.docker.internal` 호스트 매핑을 사용합니다.

```
Docker Network (ptm-platform-network)
├── mysql:3306
├── redis:6379
├── chromadb:8000
├── api-server:8080
├── mcp-server:8001
├── celery-worker-preprocessing
├── celery-worker-rag
├── celery-worker-report
├── frontend:3000
└── gateway:80/443

Host Machine
├── Cytoscape Desktop → host.docker.internal:1234
└── Ollama → host.docker.internal:11434
```

---

## 8. 운영 가이드

### 8.1. 특정 단계만 재실행

각 Worker는 `chain_to_next` 설정을 통해 독립적으로 실행할 수 있습니다. 특정 단계에서 오류가 발생한 경우, 해당 단계만 재실행하면 이전 단계의 출력물을 재사용합니다.

### 8.2. 코드 변경 후 적용

Worker 코드를 수정한 경우, Docker 이미지를 재빌드해야 합니다. Docker의 빌드 캐시가 새 코드를 포함하지 않는 경우가 있으므로 `--no-cache` 옵션을 사용하는 것이 권장됩니다.

```bash
# 특정 Worker만 재빌드 및 재시작
docker compose build --no-cache celery-worker-report
docker compose up -d celery-worker-report
```

### 8.3. Idempotent 설계

Preprocessing Worker는 각 Step의 출력 파일 존재 여부를 확인하여, 이미 완료된 Step을 건너뜁니다. 따라서 중간에 실패한 경우 동일한 Order를 다시 실행하면 완료된 부분은 건너뛰고 실패한 지점부터 재개됩니다. 강제로 처음부터 재실행하려면 해당 Order의 출력 디렉토리를 삭제해야 합니다.
