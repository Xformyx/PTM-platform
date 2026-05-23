# Smart Signal Decomposition — Implementation Plan

## Problem Statement
- AKT1에 748개 PTM이 몰림 (RxRxxS/T motif가 너무 broad)
- Receptor inference가 10개 PTM만 매핑 (kinase_modules → Reactome 경로가 단일)
- 시간 축 정보(co-wave)가 kinase 할당에 반영되지 않음

## Phase 1: Temporal-aware Kinase Subfamily Disambiguation
- [ ] `motif_kinase_annotation` 내 motif matching에 temporal context scoring 추가
- [ ] 동일 motif family 내 세분화: AKT vs S6K vs RSK vs SGK (모두 basophilic)
- [ ] co-wave peak time을 기반으로 kinase 확률 분배
- [ ] `global-kinase-modules`에서 inferred 할당 시 temporal_score 반영

## Phase 2: Wave-based Kinase Re-assignment
- [ ] co-wave module별 dominant kinase 추론 (anchor kinase 활용)
- [ ] 같은 wave 내 unassigned PTM을 wave의 dominant kinase로 재할당
- [ ] Wave간 cascade 관계 추론 (Wave1 kinase → Wave2 kinase 활성화)

## Phase 3: Pathway-aware Receptor Deconvolution
- [ ] kinase_modules를 wave별로 그룹화하여 receptor inference에 전달
- [ ] wave별 독립 receptor inference → 다양한 receptor 발굴
- [ ] cascade-level receptor mapping (receptor → wave1 kinase → wave2 kinase → substrate)

## Key Data Flow
```
Frontend: detectCoWaveModules() → peak timepoint별 PTM 그룹화
  ↓
Backend: global-kinase-modules
  ├── motif_kinase_annotation() → 8-source annotation + motif match
  ├── kinase module build → kinase별 PTM 그룹화
  ├── [NEW] temporal_kinase_scoring() → wave 정보로 kinase 재할당
  └── temporal_cascade → wave별 kinase activity
  ↓
Backend: vector-plot (receptor inference)
  ├── Source A: literature upstream_regulators
  ├── Source B: Reactome kinase→receptor
  ├── Source C: Treatment context
  └── [NEW] Source D: Wave-aware cascade receptor mapping
```

## Implementation Notes
- motif_db에서 AKT/PKB: r"R.R..[ST]" — SGK도 동일 패턴
- RSK: r"[RK].[RK]..[ST]" — S6K도 동일 패턴  
- 이들을 구분하려면 temporal context + known anchor 필요
- _RECEPTOR_DOWNSTREAM_KINASES에 이미 receptor→kinase 매핑 있음
  → 역방향 활용: kinase set → 가능한 receptor set → wave timing으로 필터
