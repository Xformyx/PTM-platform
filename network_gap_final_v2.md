# Network Pipeline GAP Analysis - Final v2

## 가이드 문서 핵심 요구사항 vs 현재 코드 상태

### 현재 코드 파일 구조:
- `workers/report_generation/core/nodes/network_node.py` - 메인 네트워크 노드
- `workers/report_generation/core/figure_context.py` - FigureInformationGenerator
- `workers/report_generation/core/nodes/crosstalk_node.py` - Cross-Talk 분석
- `workers/report_generation/core/nodes/writer_node.py` - LLM 섹션 작성
- `workers/report_generation/core/dynamic_prompt_generator.py` - v98 프롬프트

---

## GAP 1: 시간대별 네트워크 분석 (🔴 Critical)

### 가이드 요구사항:
- `analyze_timepoint()` 함수로 각 시간대별 활성화된 PTM만 필터링
- source+target 모두 활성화된 엣지만 active edge로 선택
- 시간대별 개별 Cytoscape 네트워크 생성 (PTM_Network_5min.png 등)
- 반환 구조: active_ptm_nodes, non_ptm_nodes, active_edges, all_edges, pathway_summary, stats

### 현재 코드 (network_node.py):
- `_build_network_data()` 함수가 전체 PTM을 하나의 통합 네트워크로 생성
- condition별(AF, mgAF 등) 서브네트워크는 있지만 시간대별 분리 없음
- enriched_data에서 직접 노드/엣지 구축 (temporal_df 파싱 없음)
- 시간대별 활성화 필터링 없음

### 수정 필요:
1. `_build_network_data()`에 timepoint 파라미터 추가
2. 시간대별 활성화 PTM 필터링 로직 추가
3. active edge 판정 (source+target 모두 활성화) 로직 추가
4. 시간대별 개별 Cytoscape 네트워크 생성

---

## GAP 2: Non-PTM 노드 생성 (🔴 Critical)

### 가이드 요구사항:
- KEGG pathway에 포함된 단백질 중 PTM이 아닌 것을 Non-PTM 노드로 추가
- TSV에서 해당 시간대에 identification된 단백질만 포함
- Non-PTM 노드: type="Non-PTM", shape=DIAMOND, color=Light Green (#90EE90)

### 현재 코드:
- Non-PTM 노드 생성 로직 없음
- 모든 노드가 PTM 노드로만 구성
- enriched_data에서 KEGG pathway 정보를 추출하지 않음

### 수정 필요:
1. enriched_data에서 KEGG pathway 정보 추출
2. pathway에 포함된 Non-PTM 단백질 식별
3. Non-PTM 노드 생성 및 Cytoscape에 추가
4. DIAMOND shape + Light Green 색상 적용

---

## GAP 3: FigureInformationGenerator 연동 보강 (🟡 Medium)

### 가이드 요구사항:
- `_generate_activated_ptm_section()` - 활성화 PTM 테이블
- `_generate_inhibited_ptm_section()` - 억제 PTM 테이블
- `_generate_nonptm_section()` - Non-PTM 단백질 테이블
- `_generate_signaling_cascade_section()` - Kinase→Substrate→Interactor 경로
- `generate_figure_context_for_llm()` - 시간대별 통합 컨텍스트

### 현재 코드 (figure_context.py):
- FigureInformationGenerator 클래스 존재
- network_analysis state에서 데이터를 받아 LLM 컨텍스트 생성
- 하지만 시간대별 데이터가 없으므로 불완전

### 수정 필요:
1. 시간대별 데이터 구조에 맞게 FigureInformationGenerator 업데이트
2. Non-PTM 섹션 추가
3. Inhibited PTM 섹션 추가

---

## GAP 4: Legend 생성 보강 (🟡 Medium)

### 가이드 요구사항:
- `generate_figure_legend()` - 전체 Figure Legend (패널 설명 + 색상 범례 + 통계 테이블)
- `generate_individual_panel_legend()` - 개별 시간대 패널 Legend
- `generate_temporal_comparison_legend()` - 시간대 간 비교 분석

### 현재 코드:
- `_generate_legends()` 함수가 기본 Legend만 생성
- 패널별/비교 Legend 없음

### 수정 필요:
1. 3종 Legend 생성 함수 구현
2. generate_network_figure_section()에서 Legend 삽입

---

## GAP 5: Cross-Talk Figure (🟡 Medium)

### 가이드 요구사항:
- Table 2A: Dual-PTM 단백질 요약 테이블
- Figure 2B: Split-cell 히트맵 (이미지)
- Table 2C: PTM 조절 관계 테이블
- `generate_crosstalk_figure_section()` 함수

### 현재 코드 (crosstalk_node.py):
- L964: "Cross-Talk Figures (placeholder for crosstalk_figures.py integration)" 주석만 있음
- 실제 Figure 생성 로직 미구현

### 수정 필요:
1. Table 2A 생성 함수 구현
2. Figure 2B (히트맵) 생성 함수 구현
3. Table 2C 생성 함수 구현
4. crosstalk_node.py에 Figure 삽입 로직 추가

---

## GAP 6: 색상 팔레트 통일 (🟢 Low)

### 가이드 요구사항:
- non_ptm: #90EE90 (Light Green)
- inhibited: #4169E1 (Blue)
- STRING edge: #808080 (Gray)
- KEGG edge: #228B22 (Green)
- KEA3 edge: #FF4500 (Orange-Red)

### 현재 코드:
- non_ptm 색상이 Purple (#9370DB)로 다름
- 일부 엣지 색상도 다름

### 수정 필요:
1. NODE_COLORS 상수를 가이드 기준으로 통일
2. EDGE_COLORS 상수를 가이드 기준으로 통일
