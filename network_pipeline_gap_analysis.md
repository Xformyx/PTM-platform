# Network Pipeline Gap Analysis

## 가이드 문서 vs 현재 코드 비교

### 가이드 문서 핵심 파이프라인 (10단계)

```
STEP 1: 데이터 파싱 (ptm_network_automation.py)
  - parse_temporal_signaling_table() → PTM 시간대별 Log2FC
  - parse_connection_evidence_table() → PTM 간 연결 증거
  - parse_common_kegg_pathways() → KEGG pathway 정보
  - parse_tsv_proteins() → Non-PTM 단백질 정보

STEP 2: 시간대별 네트워크 분석
  - analyze_timepoint() → 시간대별 노드/엣지/pathway 집계
  - PTMNonPTMNetworkAnalyzer.analyze() → Kinase 노드, Inhibited 노드 포함

STEP 3: Cytoscape 네트워크 생성
  - create_cytoscape_network() + apply_visual_style() + save_network_image()

STEP 4: Figure Legend 생성
  - generate_figure_legend() → 전체 Legend (패널별, 비교 포함)
  - FigureInformationGenerator → LLM용 상세 데이터 테이블

STEP 5: 레포트 통합
  - generate_network_figure_section() → Base64 이미지 + Legend 삽입
  - LLM 섹션 (Results/Discussion)에 figure_context 주입
```

---

## GAP 분석 결과

### GAP 1: 시간대별 네트워크 분석 누락 (심각도: 🔴 높음)

**가이드**: `analyze_timepoint()`으로 시간대별(2min, 5min, 10min...) 분석
- 시간대별로 활성화된 PTM만 필터링
- 시간대별로 활성화된 엣지만 선택 (source+target 모두 활성화)
- 시간대별 pathway 집계
- 결과: 시간대별 패널 네트워크 이미지 (PTM_Network_5min.png, PTM_Network_10min.png...)

**현재**: `_build_network_data()`가 전체 데이터를 한 번에 처리
- 시간대별 분리 없이 전체 PTM을 하나의 네트워크로 생성
- condition별 서브네트워크는 있지만 시간대별은 아님
- 결과: 단일 PTM_Signaling_Network.png

**영향**: 시간 경과에 따른 PTM 활성화 변화를 시각적으로 보여줄 수 없음

---

### GAP 2: Non-PTM 노드 생성 누락 (심각도: 🔴 높음)

**가이드**: KEGG pathway에 포함된 Non-PTM 단백질을 별도 노드로 추가
- TSV에서 해당 시간대에 identification된 단백질만 포함
- Non-PTM 노드: type="Non-PTM", state="non_ptm", DIAMOND 모양

**현재**: `_build_network_data()`에서 enriched_data의 connections에서 엣지만 추출
- Non-PTM 노드를 KEGG pathway 기반으로 추가하는 로직 없음
- enriched_data에 Non-PTM 정보가 있을 수 있지만 노드로 변환하지 않음

**영향**: 네트워크가 PTM 노드만으로 구성되어 생물학적 맥락이 부족

---

### GAP 3: FigureInformationGenerator 연동 불완전 (심각도: 🟡 중간)

**가이드**: 
```python
figure_info = FigureInformationGenerator(results, analyzer, ptm_type)
figure_context = figure_info.generate_figure_context_for_llm()
# → Results/Discussion 프롬프트에 삽입
```

**현재**: 
- `figure_context.py`에 FigureInformationGenerator 클래스 존재 ✅
- `writer_node.py`에서 `FigureInformationGenerator(network_analysis)` 호출 ✅
- 그러나 `network_analysis`에 시간대별 데이터가 없으므로 figure_context가 불완전할 수 있음

**영향**: LLM이 Figure 데이터를 참조하여 Results/Discussion을 작성할 때 불완전한 데이터 사용

---

### GAP 4: Legend 생성 간소화 (심각도: 🟡 중간)

**가이드**: 3종 Legend
- `generate_figure_legend()` → 전체 Legend (패널 설명, 색상 범례, 통계 테이블, Methods)
- `generate_individual_panel_legend()` → 시간대별 패널 Legend
- `generate_temporal_comparison_legend()` → 시간대 간 비교 분석

**현재**: `_generate_legends()` → 기본 Legend만 생성
- full_legend, node_legend, edge_legend 3종
- 시간대별 패널 Legend 없음
- 시간대 비교 Legend 없음

**영향**: Figure Legend의 학술적 완성도 저하

---

### GAP 5: 색상 팔레트 차이 (심각도: 🟢 낮음)

| State | 가이드 | 현재 |
|-------|--------|------|
| high_active / activated | #FF0000 (Red) | #E74C3C (Red) |
| moderate_active | #FF8C00 (Orange) | #FF8C00 (Orange) ✅ |
| low_active / baseline | #FFD700 (Gold) | #F7DC6F (Yellow) |
| inhibited | #4169E1 (Blue) | #3498DB (Blue) |
| non_ptm | #90EE90 (Light Green) | #9B59B6 (Purple) ⚠️ |

**영향**: 시각적 차이만 있고 기능적 영향은 없음. non_ptm 색상이 크게 다름.

---

### GAP 6: Cytoscape 시각화 스타일 (심각도: ✅ 양호)

현재 코드가 가이드보다 더 세분화된 스타일을 적용:
- 노드 타입: 5종 (PTM, Non-PTM, Kinase, Interactor, Pathway-Member)
- 엣지 타입: 10종 (STRING-DB, KEGG, Literature, Pathway, Shared Pathway, Predicted, Co-activation, Kinase-Substrate, Kinase-Substrate-Predicted, Unknown)
- Kinase 노드: 별도 border 스타일 (hollow effect)
- 레이아웃: 최적화된 force-directed + overlap removal

---

### GAP 7: Cross-Talk 모드 (심각도: 🟡 중간)

**가이드**: `crosstalk_figures.py`에서 Table 2A, Figure 2B, Table 2C 생성

**현재**: `crosstalk_node.py`가 LLM 기반 분석만 수행. Figure 생성 로직 없음.

---

## 수정 우선순위

| 순위 | GAP | 설명 | 예상 작업량 |
|------|-----|------|------------|
| 1 | 시간대별 네트워크 분석 | analyze_timepoint() 구현 또는 시간대별 분리 로직 추가 | 대규모 |
| 2 | Non-PTM 노드 생성 | KEGG pathway 기반 Non-PTM 노드 추가 | 중규모 |
| 3 | FigureInformationGenerator 연동 보강 | 시간대별 데이터 전달 | 소규모 |
| 4 | Legend 생성 보강 | 패널별/비교 Legend 추가 | 중규모 |
| 5 | Cross-Talk Figure | Table 2A/Figure 2B/Table 2C 구현 | 대규모 |
| 6 | 색상 팔레트 통일 | 가이드 색상으로 변경 | 소규모 |
