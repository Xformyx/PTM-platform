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

## AI Agent Handoff 문서
- [x] 오늘의 Data-Grounded Analysis 및 Co-Scientist 연동 변경사항 Markdown 정리
- [x] 문서 검토 및 전달

## Temporal PTM 연구 방향 검토
- [x] 최신 main 반영 및 첨부 연구 방향 PDF 정밀 추출
- [x] 현 Temporal PTM·Data-Grounded·Co-Scientist 구현과 제안 내용 대응 분석
- [x] 적용 가능한 업그레이드의 우선순위 및 구현 범위 보고

## P0 Canonical Temporal Wave 기반
- [x] 최신 main 반영 및 기존 Report/API co-wave 입출력 계약 점검
- [x] Canonical Temporal Wave Contract와 공용 분석 엔진 구현
- [x] Report temporal_comovement 및 API receptor co-wave 경로 통합
- [x] Wave formal definition, evidence profile, threshold provenance 구현
- [x] 실제 perturbation dataset manifest 스키마 및 Wave vs Site benchmark harness 구현
- [x] Time permutation·threshold sensitivity 회귀 테스트 및 문서화
- [x] Python/TypeScript 검증, GitHub 반영

## P1–P3 Evidence-Aware Directionality 및 선택적 Causal Validation
- [x] 최신 main 반영 및 기존 causal·lag·graph·report·Co-Scientist 경로 점검
- [x] DirectedTemporalRelationship 계약 및 causal 용어를 temporal precedence로 변경
- [x] 실제 minute 기반 onset/peak lag 및 lag-aware similarity 구현
- [x] Bootstrap·leave-one-timepoint·time permutation·threshold stability 구현
- [x] D0–D3 directionality tier 및 Wave evidence profile 확장
- [x] Graph·Report·Co-Scientist에 evidence-aware 표현 및 guardrail 통합
- [x] 분석 완료 후 D2/D3 후보의 causal validation experiment recommendation 구현
- [x] 사용자 업로드 perturbation 결과의 선택형 `perturbation_supported` 평가 구현
- [x] 회귀 테스트·문서화·GitHub 반영

## Temporal PTM 논문 비교 검토
- [x] 첨부 논문 정밀 추출 및 핵심 방법론·결과 확인
- [x] 현재 Temporal Wave·Directionality·Data-Grounded·Co-Scientist 구현과 대응 분석
- [x] 차별점, 도입 우선순위 및 주의사항 보고

## SnapKin 대비 TMM·Temporal Precedence 심층 분석
- [x] SnapKin supervised attribution과 TMM·directionality 계약 재확인
- [x] 공유 substrate·motif ambiguity·시간 정보 처리의 수학적 비교
- [x] PTM-platform 고유 강점, 학술적 주장 경계 및 검증 우선순위 보고

## Unbiased Discovery 및 AI 특이점 해석 평가
- [x] SnapKin 학습 편향과 TMM·directionality 데이터 의존성 비교
- [x] Unbiased discovery 관점의 장점·한계 및 보고 범위 평가
- [x] AI 기반 특이점 탐지·해석의 이점·편향 위험·통제 원칙 정리

## Co-Wave 다중 Kinase 해석 점검
- [x] 최신 main 반영 및 co-wave·TMM·cascade·report 경로 점검
- [x] 동일 Wave의 다중 kinase와 시간대 간 정보 결합 방식 분석
- [x] 현재 동작·한계 및 해석 원칙 보고

## TMM 기반 다중 Kinase 해석 일관성 강화
- [x] 최신 main 반영 및 co-wave·cascade·TMM·directionality 통합 지점 점검
- [x] TMM 후 kinase co-wave 재계산 및 raw/TMM provenance 저장
- [x] TMM contribution-weighted temporal cascade와 sparse-profile confidence 구현
- [x] TMM-weighted kinase-pair directionality 및 report context 통합
- [x] 회귀 테스트·문서화·GitHub 반영

## Rat 배경 + Human INSR 혼합 FASTA 호환성
- [x] 최신 main 반영 및 species·protein normalization·annotation 경로 점검
- [x] Human INSR의 제외·unknown·ortholog 치환 위험 분석
- [x] 혼합 종 allowlist 및 species-aware annotation 보완 구현
- [x] 회귀 검증·GitHub 반영 및 입력 운영 가이드 보고

## Multisite PTM Divergence 활용 Audit
- [x] 최신 main 반영 및 divergence 생성·저장·API 경로 점검
- [x] Kinase·Wave·directionality·Report·Data-Grounded 활용 경로 분석
- [x] 학술적 의미, 해석 경계, 미활용 영역 및 개선 우선순위 보고

## Canonical Multisite PTM Divergence 업그레이드
- [x] 최신 main 반영 및 API·Report·Frontend divergence 구현과 공유 계약 점검
- [x] D0·D1 Canonical observation-first divergence contract와 안전한 wording 구현
- [x] D2 Site-pair directionality, replicate/FDR confidence 구현
- [x] D3 TMM contribution divergence 구현
- [x] D4 API·Report·Frontend·Data-Grounded·receptor scoring evidence gate 통합
- [x] 회귀 테스트·문서화·GitHub 반영

## Rat_hir Species Registry 호환성
- [x] 최신 main 반영 및 custom species alias·FASTA 선택·annotation 경로 점검
- [x] Rat_hir의 rat-base alias·custom FASTA registry 및 human INSR provenance 정의
- [x] Species validation·UI·FASTA selection·rat annotation routing 보완 구현
- [x] 회귀 검증·GitHub 반영 및 Rat_hir 입력 가이드 보고

## TMM Benchmark용 공개 DIA·Astral Time-course 자료 조사
- [x] 공개 time-course DIA 및 Orbitrap Astral phosphoproteomics 후보 탐색
- [x] 시간 해상도·장비·processed data 접근성·benchmark 적합성 검증
- [x] 직접 설계 insulin signaling time-course와 공개 자료의 보완 전략 보고

## 비-enrichment 입력과 PTM Activity·TMM 해석 범위 정합성 감사
- [x] 입력 data matrix·정량 열·PTM site provenance의 실제 의미 점검
- [x] PTM activity·TMM·kinase annotation의 관찰값과 추론값 경계 감사
- [x] 방법론 용어·benchmark 설계·필요 코드/문서 정정 권고

## Dual-Track PTM Quantification: Absolute Occupancy + Protein-Normalized Signal
- [x] PR matrix 내 modified/unmodified counterpart peptide 매칭 가능성·식별자·missingness 감사
- [x] occupancy 및 protein-normalized track의 계산 계약·quality gate·provenance 설계
- [x] co-wave·TMM·report에서 track별 사용·병합·우선순위 규칙 설계
- [x] paired occupancy 결측치의 observed-only·drop·sensitivity-only imputation 계약 추가
- [x] P0: modified/unmodified pair audit·quality tier·missingness provenance 구현
- [x] P1: dual-track vector output·API metadata·occupancy 표시 계약 구현
- [x] P2: track별 co-wave/TMM·concordance/discrepancy evidence 구현
- [x] 기존 Track 2 호환성·Python 회귀 테스트·문서화·GitHub 반영

## Dual-Track PTM Quantification 논문 Methods 초안
- [x] 구현 계약과 관찰·추론 경계 재검증
- [x] 논문용 Methods 섹션 초안 작성 및 참고문헌 정리
- [x] 실험별로 채워야 할 파라미터·제한 사항 안내

## RAG Collection Biomedical Embedding Model 지원성 감사
- [x] 현재 embedding provider·collection metadata·retrieval 경로 점검
- [x] BioBERT·PubMedBERT embedding 적합성·차원·운영 제약 검증
- [x] collection 재색인·model registry·fallback 도입 설계 및 권고 작성

## RAG Collection PubMedBERT Embedding 지원 구현
- [x] 최신 main 동기화 및 기존 index/query embedding 계약 재검증
- [x] shared embedding registry·explicit query embedding·dimension guard 구현
- [x] RAG API·frontend PubMedBERT selector·collection metadata와 reindex protection 구현
- [x] 회귀 테스트·문서화·GitHub main 반영

## RAG Management PubMedBERT Selector 노출 점검
- [ ] 실행 중인 frontend bundle과 source의 selector option 포함 여부 확인
- [ ] 최신 frontend rebuild·restart 및 cache 무효화
- [ ] RAG Management selector 노출과 새 collection 생성 흐름 확인

## RAG Enrichment Retrieval·Qwen 생성 역할 감사
- [x] 현재 RAG Enrichment의 ChromaDB retrieval·MCP·LLM 호출 경로 점검
- [x] PubMedBERT embedding과 Qwen 14B의 역할·품질·운영 제약 비교
- [x] RAG Enrichment의 retrieval·reranking·생성 모델 권장 정책 작성

## Rat_hir Order Creation 실패 점검
- [x] Rat_hir frontend payload·API validation·서버 로그의 실패 지점 확인
- [x] custom reference alias·FASTA 조건·order schema 정합성 수정
- [x] Rat_hir/Rat order creation 회귀 테스트 및 운영 전제 문서화

## Temporal PTM Representation Learning 도입 평가
- [x] 현재 temporal PTM·co-wave·TMM contract와 학습 입력 후보 점검
- [x] representation learning 모델 계열·기대 효과·과적합 및 해석 위험 비교
- [x] TMM·co-wave 결합 architecture·benchmark·도입 우선순위 권고 작성

## 첨부 Representation Learning 제안 통합 검토
- [x] 첨부 문서의 model architecture·learning objective·data contract 추출
- [x] 현재 co-wave·TMM·directionality·dual-track contract와 정합성·위험 비교
- [x] 채택·수정·보류 항목과 benchmark gate를 포함한 통합 권고 작성
