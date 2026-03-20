# Network Pipeline Modification Plan

## 가이드 문서 vs 현재 코드 비교 후 수정 계획

### GAP 1: 시간대별 네트워크 분석
- 현재: `_build_network_data()`가 전체 PTM을 하나의 통합 네트워크로 생성
- 가이드: `analyze_timepoint()`으로 시간대별 네트워크 각각 생성
- 수정: `_build_network_data()`에 시간대별 분석 추가, `_generate_cytoscape_networks()`에서 시간대별 이미지 생성

### GAP 2: Non-PTM 노드 생성
- 현재: PTM 노드만 생성, Non-PTM 없음
- 가이드: KEGG pathway 단백질 중 PTM이 아닌 것을 Non-PTM 노드로 추가
- 수정: `_build_network_data()`에서 enriched_data의 pathway 정보로 Non-PTM 노드 추가

### GAP 3: FigureInformationGenerator 연동 보강
- 현재: 기본 figure_context만 제공 (main + condition별)
- 가이드: 시간대별 PTM 테이블, Non-PTM 테이블, Signaling Cascade 등 상세 데이터
- 수정: figure_context.py에 시간대별 데이터 테이블 생성 메서드 추가

### GAP 4: Legend 생성 보강
- 현재: 기본 Legend만 (전체 통계)
- 가이드: 3종 Legend (전체/패널별/시간대 비교)
- 수정: `_generate_legends()`에 패널별/비교 Legend 추가

### GAP 5: Cross-Talk Figure
- 현재: crosstalk_node.py에 텍스트 기반 분석만
- 가이드: Table 2A, Figure 2B (히트맵), Table 2C
- 수정: crosstalk_node.py에 Figure 생성 함수 추가

### GAP 6: 색상 팔레트 통일
- 현재: non_ptm = Purple (#9B59B6), activated = #E74C3C
- 가이드: non_ptm = Light Green (#90EE90), high_active = #FF0000
- 수정: NODE_COLORS/EDGE_COLORS 상수 변경

## 수정 파일 목록
1. network_node.py - GAP 1, 2, 4, 6
2. figure_context.py - GAP 3
3. crosstalk_node.py - GAP 5
