# PTM 벡터 2차원 플롯 검토

ptm-preprocessing_v2_260131의 TSV 기반 벡터 2D 시각화와 ptm-platform 구현 현황 비교입니다.

---

## 1. ptm-preprocessing_v2_260131 — 벡터 플롯 기능

### ptm_vector_report_generator.py

**위치:** `ptm-preprocessing_v2_260131/src/ptm_vector_report_generator.py`

**라이브러리:** matplotlib + seaborn (Plotly 아님)

**기능:**
- PTM 벡터 TSV(`ptm_vector_data_normalized_*.tsv`)를 읽어 2D scatter plot 생성
- **상단 행**: Protein_Log2FC vs PTM_Relative_Log2FC (조건별 A, B, C)
- **하단 행**: Protein_Log2FC vs PTM_Absolute_Log2FC (조건별)
- 임계값 라인: ±0.5, ±1.0 (dashed/solid)
- 색상: Phosphorylation (파란 계열), Acetylation (빨간 계열)
- 출력: `ptm_vector_report_phospho.png`, `ptm_vector_report_ubi.png`, `ptm_vector_summary_report.png`
- `generate_combined_summary_report()`: Residual 히스토그램, 조건별 bar chart 포함

**호출 흐름:**
- `PTMVectorReportGenerator`는 analysis_engine에서 **직접 호출되지 않음**
- 별도 스크립트나 GUI에서 사용하는 것으로 보임

**Condition 가정:**
- `conditions = ['A', 'B', 'C']` 고정 — ptm-platform은 `Control` + treatment 조건(동적) 사용

---

## 2. ptm-platform — 현재 구현

### ✅ 있는 것

| 항목 | 상태 |
|------|------|
| ptm_vector_data TSV 생성 | ✅ `ptm_quantification.create_ptm_vector_data()` |
| ptm_vector_data_normalized_*.tsv | ✅ Preprocessing 출력 |
| ptm_vector_data_with_motifs_*.tsv | ✅ Motif 분석 포함 |
| RAG/Report에서 vector TSV 사용 | ✅ RAG enrichment 입력으로 사용 |

### ❌ 없는 것

| 항목 | 상태 |
|------|------|
| **2D scatter plot 생성** | ❌ 없음 |
| **ptm_vector_report_*.png** | ❌ 생성 안 함 |
| **Frontend에서 벡터 플롯 표시** | ❌ 없음 |
| Plotly / matplotlib 시각화 | ❌ 없음 |

---

## 3. ptm-platform workers 구조

```
workers/preprocessing/core/ptm_quantification.py
  - create_ptm_vector_data() → TSV 저장
  - ptm_vector_data_normalized{phospho|ubi}.tsv
  - ptm_vector_data_with_motifs{phospho|ubi}.tsv
```

**없는 부분:**
- TSV → 2D plot 이미지 생성 로직
- `PTMVectorReportGenerator`에 해당하는 모듈

---

## 4. 구현 방향 제안

### 옵션 A: 백엔드에서 PNG 생성 (ptm-preprocessing 방식)

- workers에 `ptm_vector_report_generator` 유사 모듈 추가
- Preprocessing 완료 후 `ptm_vector_data_*.tsv`로 scatter plot PNG 생성
- Condition은 `Control` + 실제 treatment 조건 사용하도록 수정
- matplotlib 사용 (ptm-platform workers에 이미 의존성 있음)

### 옵션 B: Frontend에서 Plotly 인터랙티브 플롯

- API: `GET /orders/{id}/files/ptm_vector_data_normalized_*.tsv` 또는 JSON 전달
- Frontend: recharts 또는 plotly-react로 scatter plot 렌더링
- 인터랙티브 zoom, hover tooltip 가능

### 옵션 C: 둘 다

- 백엔드에서 PNG 생성 (리포트/다운로드용)
- Frontend에서 Plotly/recharts로 인터랙티브 시각화 (Order 상세 화면)

---

## 6. 구현 완료 (2025-02)

ptm-platform에 벡터 2D 플롯 기능이 추가되었습니다.

| 구성요소 | 경로 |
|----------|------|
| 리포트 생성기 | `workers/preprocessing/core/ptm_vector_report_generator.py` |
| 파이프라인 연동 | `workers/preprocessing/tasks.py` (Step 1b) |
| API | `GET /api/orders/{id}/vector-plots` |
| 프론트엔드 | OrderDetail > Vector Plot 탭 |

- Preprocessing 완료 직후 `ptm_vector_data_normalized_*.tsv`로 PNG 생성
- `ptm_vector_report_{phosphorylation|ubiquitylation}_*.png`, `ptm_vector_summary_report_*.png`
- Order 상세 화면에서 Vector Plot 탭으로 확인
