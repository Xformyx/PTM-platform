# Cytoscape Network Improvement Plan

## 현재 상태 분석

### NODE_COLORS (현재)
- high_active: #FF0000 (Red) — Log2FC > 1.0
- moderate_active: #FF8C00 (Dark Orange) — 0 < Log2FC <= 1.0
- low_active: #FFD700 (Gold) — weak activation
- inhibited: #4169E1 (Royal Blue) — Log2FC < -1.0
- low_inhibited: #87CEEB (Light Blue) — -1 < Log2FC < 0
- non_ptm: #90EE90 (Light Green) — Non-PTM protein
- neutral: #C0C0C0 (Silver) — neutral
- missing: #BDC3C7 (Gray) — missing data

### NODE_SHAPES (현재)
- PTM: ELLIPSE (circle)
- Non-PTM: DIAMOND
- Kinase: DIAMOND

### 문제점
1. Non-PTM protein의 양적 변화(protein_log2fc)가 색상에 반영되지 않음 (모두 Light Green)
2. Kinase/upstream regulator가 Non-PTM과 동일한 DIAMOND이지만 색상 구분 없음
3. 연결되지 않는 노드가 많음 — upstream regulator 기반 연결 강화 필요

## 사용자 요구사항

### 노드 모양
- PTM protein: 동그라미 (ELLIPSE) ✓ 이미 구현
- Kinase/upstream regulator: 마름모 (DIAMOND) ✓ 이미 구현이지만 Non-PTM과 구분 필요

### 색상 체계
- PTM protein 양적 변화: 붉은색 계열 (현재 활성화 상태 기반이므로 수정 필요)
- Non-PTM protein 양적 변화:
  - Control 대비 증가: 녹색 계열
  - Control 대비 감소: 보라색 계열
  - 큰 변화 없음: 회색 계열
- Kinase/upstream regulator: 별도 색상

### 연결 강화
- Upstream regulator 중심으로 PTM protein 간 연결 극대화
- Shared upstream regulator를 허브 노드로 활용

## 구현 계획

### 1. Non-PTM protein에 protein_log2fc 전달
- _build_network_data, _analyze_timepoint에서 Non-PTM 노드 생성 시 protein_log2fc 추가
- enriched_data에서 Non-PTM protein의 Protein_Log2FC 값 추출

### 2. 새 색상 체계
- PTM protein: 붉은색 계열 (진한 빨강 → 연한 빨강, Log2FC 기반)
- Non-PTM protein (증가): 녹색 계열
- Non-PTM protein (감소): 보라색 계열
- Non-PTM protein (변화 없음): 회색 계열
- Kinase/upstream regulator: 별도 색상 (오렌지 또는 금색)

### 3. 노드 타입 세분화
- PTM → ELLIPSE (동그라미)
- Non-PTM → ELLIPSE (동그라미) — 사용자 요청: 단백질은 동그라미
- Kinase/upstream regulator → DIAMOND (마름모) — 사용자 요청

### 4. Upstream regulator 기반 연결 강화
- 같은 upstream regulator를 공유하는 PTM protein끼리 "Shared-Regulator" 엣지 추가
- Upstream regulator를 허브 노드로 배치
- PhosphoSitePlus, KEA3 데이터 활용
