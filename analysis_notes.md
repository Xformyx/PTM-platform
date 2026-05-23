# CW Group ↔ Vector Plot Co-Wave Module 연동 분석

## 현재 구조

### Vector Plot (OrderDetail.tsx TopNTimeSeriesPlot)
- **색상 결정**: Activity class 기반 (de_novo=주황, regulated=파랑, minor=초록)
- **Co-Wave Module**: KinaseModuleAnalysis의 `detectCoWaveModules()`로 PTM을 시간 패턴별로 그룹핑
  - Module 1 (peak: 6h), Module 2 (peak: 12h) 등
  - 색상: KINASE_MODULE_COLORS (blue, rose, emerald, amber, violet, cyan, pink, teal)
  - 모듈 클릭 시 해당 PTM들이 Vector Plot에서 하이라이트됨

### Heatmap (KinaseActivityHeatmapView)
- **CW Group**: API에서 kinase들의 substrate activity 상관관계(r≥0.7) 기반 그룹핑
  - G0, G1, G2... (group_id 순서)
  - 색상: COWAVE_GROUP_COLORS (cyan, fuchsia, amber, indigo, lime, pink, sky, orange)
  - API에서 `cowave_groups` 배열로 반환

## 핵심 차이점
- **Vector Plot Co-Wave Module**: PTM 레벨 그룹핑 (시간 패턴 유사한 PTM들)
- **Heatmap CW Group**: Kinase 레벨 그룹핑 (substrate activity 상관관계 기반)

## 연동 방안
두 시스템은 다른 레벨에서 작동하지만 연결 가능:
- Heatmap CW Group의 kinase들은 특정 PTM들을 substrate로 가짐
- 이 PTM들은 Vector Plot의 Co-Wave Module에 속할 수 있음
- **연동**: Heatmap CW Group의 dominant_peak과 Vector Plot Co-Wave Module의 peakCondition이 일치하면 같은 색상 사용

## 구현 방향
1. Heatmap CW Group 색상을 Vector Plot의 Co-Wave Module 색상과 동기화
   - dominant_peak이 같은 CW Group과 Co-Wave Module에 같은 색상 부여
2. CW Group 라벨에 해당하는 Co-Wave Module 번호 표시
3. CW Group 클릭 시 해당 kinase의 substrate PTM들을 Vector Plot에서 하이라이트
