# Network Pipeline GAP Analysis: 가이드 문서 vs 현재 코드

## 현재 코드 구조 요약

### network_node.py (run_network_analysis)
- `_build_network_data()`: enriched_data에서 노드/엣지를 빌드 (시간대별 분리 없이 통합)
- `_generate_cytoscape_networks()`: Cytoscape에 condition별 네트워크 생성 (AF, mgAF 등)
- `generate_network_figure_section()`: Base64 이미지 + Legend를 Markdown으로 조립
- 반환: state["network_analysis"] = {"figure_section", "network_images", "network_data", "legends"}

### figure_context.py (FigureInformationGenerator)
- 존재하지만 network_analysis 데이터에서 시간대별 정보가 없어 불완전
- generate_figure_context_for_llm() 메서드 있음

### crosstalk_node.py
- L964: "Cross-Talk Figures (placeholder for crosstalk_figures.py integration)" 주석만 있음
- Table 2A, Figure 2B, Table 2C 미구현

---

## GAP 상세

### GAP 1: 시간대별 네트워크 분석 (🔴 Critical)
**가이드**: analyze_timepoint()으로 각 시간대별로:
  - 활성화된 PTM만 필터링 (threshold 초과)
  - source+target 모두 활성화된 엣지만 active edge로 선택
  - Non-PTM 단백질 수집 (KEGG pathway 기반)
  - 시간대별 stats 집계

**현재**: _build_network_data()가 전체 PTM을 통합 네트워크로 생성
  - condition별 서브네트워크는 있지만 시간대별 분리 없음
  - threshold 기반 활성화 필터링 없음

**수정 필요**:
  - _build_network_data()에 시간대별 분석 로직 추가
  - analyze_timepoint() 함수 구현
  - 각 시간대별 active_ptm_nodes, non_ptm_nodes, active_edges, stats 반환

### GAP 2: Non-PTM 노드 생성 (🔴 Critical)
**가이드**: KEGG pathway에 포함된 Non-PTM 단백질을 별도 노드로 추가
  - TSV에서 해당 시간대에 identification된 단백질만 포함
  - type="Non-PTM", state="non_ptm", shape=DIAMOND

**현재**: Non-PTM 노드 생성 로직 없음
  - 노드는 PTM 노드만 존재
  - enriched_data에서 Non-PTM 정보를 추출하는 로직 없음

**수정 필요**:
  - enriched_data에서 Non-PTM 단백질 추출 로직 추가
  - Cytoscape 스타일에 Non-PTM 노드 타입 추가

### GAP 3: FigureInformationGenerator 연동 보강 (🟡 Medium)
**가이드**: FigureInformationGenerator가 시간대별 상세 데이터 테이블 생성
  - _generate_activated_ptm_section(): 활성화 PTM 테이블
  - _generate_inhibited_ptm_section(): 억제 PTM 테이블
  - _generate_nonptm_section(): Non-PTM 단백질 테이블
  - _generate_signaling_cascade_section(): 신호 전달 경로

**현재**: FigureInformationGenerator 클래스 존재하지만 시간대별 데이터 부족

**수정 필요**:
  - network_analysis에 시간대별 데이터 포함시키기
  - FigureInformationGenerator에 시간대별 메서드 보강

### GAP 4: Legend 생성 보강 (🟡 Medium)
**가이드**: 3종 Legend 생성
  - generate_figure_legend(): 전체 Figure Legend (패널 설명 + 색상 범례 + 통계 테이블)
  - generate_individual_panel_legend(): 개별 시간대 패널 Legend
  - generate_temporal_comparison_legend(): 시간대 간 비교 분석

**현재**: _generate_legends()에서 기본 Legend만 생성

**수정 필요**:
  - 3종 Legend 함수 구현
  - generate_network_figure_section()에서 Legend 삽입 보강

### GAP 5: Cross-Talk Figure (🟡 Medium)
**가이드**: crosstalk_figures.py에서 3종 Figure 생성
  - Table 2A: Dual-PTM 단백질 요약 테이블
  - Figure 2B: Split-cell 히트맵 (이미지)
  - Table 2C: PTM 조절 관계 테이블

**현재**: crosstalk_node.py L964에 placeholder 주석만 있음

**수정 필요**:
  - crosstalk_figures.py 파일 생성 또는 crosstalk_node.py에 Figure 생성 로직 추가

### GAP 6: 색상 팔레트 통일 (🟢 Low)
**가이드**: 
  - non_ptm: #90EE90 (Light Green)
  - inhibited: #4169E1 (Blue)
  
**현재**: 
  - non_ptm 노드 자체가 없음
  - 색상 매핑이 다름 (Purple 등)

**수정 필요**:
  - NODE_COLORS 상수를 가이드 기준으로 통일
