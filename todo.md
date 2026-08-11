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

## Co-Scientist JSON 및 보고서 기여도 표기
- [ ] 외부 Co-Scientist 모듈 호출 및 JSON 입력·출력 경로 점검
- [ ] 현재 가설·검증 결과가 문장으로 변환되는 지점 점검
- [ ] 보고서 내 Co-Scientist 기반 결과의 명시적 표기 방식 설계
- [ ] 구조화된 provenance 메타데이터 및 보고서 표기 구현
- [ ] Python/TypeScript 검증 및 GitHub 반영

## Co-Scientist 모드 UI 정합성
- [x] 최신 main 반영 후 Report Options의 Research Questions 조건부 렌더링 점검
- [x] Co-Scientist 선택 시 질문 입력 숨김 및 빈 배열 전송 보장
- [x] 수정 동작 검증 및 GitHub 반영

## Data-Grounded Analysis 및 외부 Co-Scientist 보고서 연동
- [x] CoScientist Discussion Evidence Packet v1.0 계약·최신 코드 점검
- [x] 내부 Co-Scientist UI·문서·레포트 명칭을 Data-Grounded Analysis로 변경
- [x] COSCIENTIST_ENABLED 기본 비활성 feature flag 및 안전한 API client 구현
- [x] Discussion Evidence Packet 조회·스키마·품질 게이트·PTM site·문헌 식별자 검증 구현
- [x] Addendum 모드와 선택형 Enhanced Discussion 모드 구현
- [x] 외부 가설·반증 근거·한계·후속 실험의 provenance 및 레포트 통합 구현
- [x] 검증·GitHub 반영
