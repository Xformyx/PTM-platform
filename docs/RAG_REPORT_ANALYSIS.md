# RAG Enrichment 리포트 분석

## 1. `comprehensive_report_phospho.md`가 최종 RAG 출력인가?

**예.** `data/outputs/{order_code}/comprehensive_report_phospho.md`가 RAG Enrichment 단계의 **최종 출력**입니다.

- **생성 위치**: `workers/rag_enrichment/tasks.py` 129–133행
- **생성 로직**: `ComprehensiveReportGenerator.generate_full_report()` (`workers/rag_enrichment/core/report_generator.py`)
- **저장 경로**: `{OUTPUT_DIR}/{order_code}/comprehensive_report_phospho.md`

RAG 이후 Report Generation(LangGraph) 단계에서는 `final_report.md`가 별도로 생성됩니다.

---

## 2. 6개 참조 파일 사용 흐름

### 2.1 파일 목록 및 사용처

| 파일 | 경로 | 사용 모듈 | 용도 |
|------|------|-----------|------|
| rna_tissue_hpa.tsv | data/local_data/ | HPALocalLoader | HPA 조직 RNA 발현 |
| subcellular_locations.tsv | data/local_data/ | HPALocalLoader | HPA 세포 내 위치 |
| GTEx_Analysis_2017-06-05_v8_RSEMv1.3.0_transcript_tpm.gct.gz | data/local_data/ | GTExLocalLoader | GTEx 발현 (3.5GB) |
| GTEx_Analysis_v8_Annotations_SampleAttributesDS.txt | data/local_data/ | GTExLocalLoader | GTEx 샘플 메타데이터 |
| ptm-expression-patterns-v4.json | data/config/ | PatternLoader | PTM 표현 패턴 (350개) |
| relationship-patterns.json | data/config/ | PatternLoader | 관계 패턴 (85개) |

### 2.2 소스 흐름

```
local_data_loader.py
├── _find_data_root() → /app/data (Docker) 또는 ./data (로컬)
├── LOCAL_DATA_DIR = DATA_ROOT / "local_data"
└── CONFIG_DIR = DATA_ROOT / "config"

enrichment_pipeline.py
├── _query_hpa_local_first() → HPALocalLoader.query() → rna_tissue_hpa.tsv, subcellular_locations.tsv
└── _query_gtex_local_first() → GTExLocalLoader.query_expression() → GTEx GCT + annotations

fulltext_analyzer.py
└── PatternLoader.get_all_patterns_flat(), get_relationship_patterns_flat()
    → ptm-expression-patterns-v4.json, relationship-patterns.json
```

### 2.3 현재 상태

- **local_data**: `rna_tissue_hpa.tsv`, `subcellular_locations.tsv`, `GTEx_Analysis_v8_Annotations_SampleAttributesDS.txt` 존재
- **config**: `ptm-expression-patterns-v4.json`, `relationship-patterns.json` 존재
- **누락**: `GTEx_Analysis_2017-06-05_v8_RSEMv1.3.0_transcript_tpm.gct.gz` (3.5GB) — `data/local_data`에 없음

GTExLocalLoader는 `_sample_attrs` 또는 `_gct_path` 중 하나만 있어도 `is_available()`이 True이므로, annotations만 있어도 GTEx 로더는 사용됩니다. 다만 GCT가 없으면 실제 발현 값은 MCP API로만 조회됩니다.

---

## 3. 구 리포트 vs 신 리포트 차이

### 3.1 구 리포트 (PTM_Comprehensive_Report_v3)

- **출처**: 별도 시스템 (ptm-rag-backend / ptm-preprocessing v2 등)
- **특징**:
  - PTM별 시간점 테이블: PTM | Classification | 3h (Prot/PTM Log2FC) | 6h | 24h | Trajectory
  - KEGG pathway 설명 포함
  - Shared Protein Interaction Network (Protein | Interacting PTMs | Avg. Confidence)
  - Temporal Signaling Cascade (PTM | Trend | Peak Time | 3h | 6h | 24h)

### 3.2 신 리포트 (comprehensive_report_phospho.md)

- **출처**: `report_generator.py` (ptm-platform workers)
- **구조**:
  - Analyzed PTMs Overview: **분류별 개수** (Classification | Count | Significance)
  - Common KEGG Pathways: pathway 이름 + PTM 수 + 유전자
  - Shared Protein Interaction Network: 유사 구조
  - Temporal Signaling Cascade: `condition`별로 그룹화된 리스트

### 3.3 차이 요약

| 항목 | 구 리포트 | 신 리포트 |
|------|-----------|-----------|
| PTM Overview | PTM별 시간점 테이블 (3h/6h/24h) | 분류별 개수 테이블 |
| 시간점 데이터 | PTM 단위로 여러 시간점 표시 | condition별 리스트 |
| 데이터 형식 | PTM 중심 wide format | (PTM, condition) long format |

**원인**: 전처리 출력 `ptm_vector_data_normalized_phospho.tsv`는 **(PTM, Condition)** 조합당 한 행(long format)입니다. RAG는 이 행들을 그대로 개별 PTM으로 처리하고, 구 리포트처럼 PTM 단위로 시간점을 모아서 wide 테이블을 만들지 않습니다.

---

## 4. 결과가 바뀌지 않는 이유 (가능성)

1. **동일 주문 재실행 없음**  
   - `data/outputs/{order_code}/` 아래 파일은 새로 실행하지 않으면 갱신되지 않음.

2. **컨테이너 미재빌드**  
   - 코드 변경 후 `docker-compose build workers` 등으로 이미지를 다시 빌드하지 않으면 이전 코드가 실행됨.

3. **입력 데이터 동일**  
   - 전처리 결과 `ptm_vector_data_normalized_phospho.tsv`가 같으면 RAG 입력이 동일 → 리포트도 동일.

4. **MCP API 캐시**  
   - MCP 서버가 KEGG, STRING-DB 등을 캐시하면 동일 쿼리에 같은 결과 반환.

5. **경로/마운트 문제**  
   - `./data:/app/data` 마운트가 올바르지 않으면 `local_data`, `config`를 못 찾아 로컬 데이터가 사용되지 않음.

---

## 5. 권장 확인 사항

1. **로컬 데이터 로드 여부**  
   - worker 로그에서 `"HPA local data available"`, `"GTEx local data available"`, `"Loaded PTM expression patterns"` 메시지 확인.

2. **GTEx GCT 파일**  
   - `data/local_data/GTEx_Analysis_2017-06-05_v8_RSEMv1.3.0_transcript_tpm.gct.gz` 존재 여부 확인. 없으면 GTEx 발현은 MCP에만 의존.

3. **주문 재실행**  
   - 변경 사항 반영을 위해 해당 주문을 다시 실행했는지 확인.

4. **enriched_ptm_data JSON**  
   - `enriched_ptm_data_phospho.json`에서 `rag_enrichment.pathways`, `rag_enrichment.string_db`, `rag_enrichment.hpa` 등이 채워져 있는지 확인.
