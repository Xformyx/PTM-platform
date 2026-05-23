# Report Generation 파이프라인 분석

## 1. 입력 파일 및 사용 흐름

### 1.1 예상 입력 vs 실제 사용

| 파일 | 생성 단계 | Report Generation에서 사용 여부 |
|------|-----------|--------------------------------|
| `comprehensive_report_phospho.md` | RAG Enrichment | ✅ **사용** — `comprehensive_summary`로 로드, LLM 프롬프트에 주입 |
| `unified_protein_data_enriched_bio_enriched_phospho.tsv` | Preprocessing | ❌ **직접 미사용** — RAG가 이 TSV를 읽어 `enriched_ptm_data_*.json` 생성 |
| `enriched_ptm_data_phospho.json` | RAG Enrichment | ✅ **사용** — `parsed_ptms`, `research_results` 등 모든 섹션의 핵심 입력 |

### 1.2 데이터 흐름

```
Preprocessing
  └─ unified_protein_data_enriched_bio_enriched_phospho.tsv

RAG Enrichment (TSV + MCP/ChromaDB)
  ├─ enriched_ptm_data_phospho.json  ← Report Gen 입력
  └─ comprehensive_report_phospho.md  ← Report Gen 입력 (comprehensive_summary)

Report Generation (LangGraph)
  ├─ enriched_ptm_data (JSON)
  ├─ comprehensive_report (MD) → comprehensive_summary
  └─ output_dir (같은 디렉터리에서 파일 탐색)
```

---

## 2. Report Generation 파이프라인 상세

### 2.1 LangGraph 노드 순서

```
load_context → generate_questions → research → hypothesize
  → validate_hypotheses → network_analysis → write_sections
  → generate_qa_report → drug_repositioning → format_citations → edit_report
```

### 2.2 각 노드별 입력/출력

| 노드 | 주요 입력 | 출력 |
|------|-----------|------|
| **load_context** | enriched_ptm_data, md_report_path, output_dir | parsed_ptms, comprehensive_summary, research_questions |
| **research** | parsed_ptms, questions | research_results |
| **hypothesize** | research_results | hypotheses |
| **validate_hypotheses** | hypotheses, ChromaDB | validated_hypotheses |
| **network_analysis** | parsed_ptms, enriched_data | network_analysis (network_images, legends) |
| **write_sections** | research_results, validated_hypotheses, comprehensive_summary, parsed_ptms | sections (introduction, results, discussion, conclusion, abstract) |
| **format_citations** | sections, network_analysis | final_report (섹션 + Network Visualization + 참고문헌) |
| **edit_report** | final_report | final_report.md 저장 |

### 2.3 comprehensive_summary 로딩

- **경로 1**: `state.md_report_path` (config에서 전달)
- **경로 2**: `output_dir`에서 `comprehensive_report_*.md` glob

**문제 가능성**: API `run-stage` 호출 시 `md_report_path`는 `md_report.exists()`일 때만 설정됨.  
파일이 없으면 `None`이지만, `context_loader`가 `output_dir`에서 glob으로 재탐색함.

---

## 3. 리포트가 부실해지는 원인

### 3.1 comprehensive_summary 부재

- `comprehensive_report_phospho.md`가 없거나, `output_dir` 경로가 잘못된 경우
- RAG Enrichment를 건너뛰고 Report Generation만 실행한 경우

### 3.2 LLM 미가용

- Ollama/LLM이 응답하지 않으면 `[LLM Error...]` 후 **fallback_section** 사용
- fallback은 제목 수준의 짧은 텍스트만 생성

### 3.3 ChromaDB/RAG 컬렉션 비어 있음

- `chromadb_collections`가 비어 있거나, 해당 컬렉션이 비활성화된 경우
- 문헌 검색 결과 없음 → LLM에 전달되는 문맥이 빈약

### 3.4 network_results 구조 불일치 (ptm_only 모드)

- `write_sections`에서 `network_results` 사용 (networks, timepoints 구조)
- **ptm_only** 모드에서는 `network_results`가 state에 설정되지 않음
- `build_structured_protein_data_for_llm`가 빈 결과 반환 → v98 anti-hallucination 데이터 부재

### 3.5 Cytoscape 이미지 미포함

- `format_citations`에서 `generate_network_figure_section(network_analysis)` 호출
- `network_images` 경로가 잘못되었거나, `markdown_to_docx` 변환 시 이미지 처리 실패 가능

---

## 4. API에서 Report Generation에 전달되는 config

```python
# api-server/app/api/orders.py (run-stage: report_generation)
task_config = {
    "order_code": order.order_code,
    "rag_output_dir": str(order_output),
    "enriched_json_path": str(enriched_json),      # 필수
    "md_report_path": str(md_report) if md_report.exists() else None,  # 없으면 None
    "tsv_data_path": ???,  # ❌ 전달되지 않음
    "experimental_context": order.analysis_context,
    "research_questions": report_opts.get("research_questions", []),
    "chromadb_collections": active_collections,
    ...
}
```

**tsv_data_path**는 config에 포함되지 않음.  
Report Generation은 TSV를 직접 사용하지 않고, `enriched_ptm_data`(JSON)만 사용함.

---

## 5. 권장 조치

### 5.1 실행 순서 확인

1. **Preprocessing** 완료 → `unified_protein_data_enriched_bio_enriched_phospho.tsv` 생성
2. **RAG Enrichment** 완료 → `enriched_ptm_data_phospho.json`, `comprehensive_report_phospho.md` 생성
3. **Report Generation** 실행

Report Generation만 단독 실행하면 `comprehensive_report_phospho.md`가 없을 수 있음.

### 5.2 comprehensive_summary 로딩 검증

- `context_loader` 로그: `Loaded comprehensive report summary (N chars) from ...`
- 이 로그가 없으면 MD 파일을 찾지 못한 것

### 5.3 LLM 가용성 확인

- Report Generation 로그에서 `[LLM Error]` 또는 `WARNING: LLM model ... not available` 검색
- Ollama 실행 여부 및 모델 설치 확인

### 5.4 network_results → parsed_ptms 변환 (ptm_only)

- ptm_only 모드에서 `network_results`가 비어 있어 v98 데이터가 없음
- `parsed_ptms`를 `network_results` 형식으로 변환해 writer에 전달하는 로직 추가 검토

### 5.5 Cytoscape 이미지 경로

- `network_images`의 경로가 `output_dir` 기준 절대 경로인지 확인
- `markdown_to_docx`가 해당 경로의 이미지를 정상 임베드하는지 확인

---

## 6. 파일 경로 요약

| 파일 | 경로 |
|------|------|
| Preprocessing 출력 | `{OUTPUT_DIR}/{order_code}/unified_protein_data_enriched_bio_enriched_phospho.tsv` |
| RAG 출력 (JSON) | `{OUTPUT_DIR}/{order_code}/enriched_ptm_data_phospho.json` |
| RAG 출력 (MD) | `{OUTPUT_DIR}/{order_code}/comprehensive_report_phospho.md` |
| Report Gen 출력 | `{OUTPUT_DIR}/{order_code}/final_report.md`, `final_report.docx` |
| Cytoscape PNG | `{OUTPUT_DIR}/{order_code}/PTM_Signaling_Network.png` |

`OUTPUT_DIR`: Docker 기준 `/app/data/outputs` (workers), `/app/data/outputs` (api-server)
