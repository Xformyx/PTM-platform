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

## RAG Enrichment PubMed·Structured DB Evidence 효율 감사
- [x] PubMed/MCP·structured database·LLM 호출 경로와 캐시·rate-limit 정책 점검
- [x] 정보 유형별 근거 중복·고유성·비용·근거 품질 비교
- [x] database-first routing·article budget·LLM escalation·fallback 정책 권고 작성

## RAG Enrichment Database-First Evidence Routing 구현
- [x] 최신 main 동기화 및 enrichment·validation·cache·report 소비 contract 재검증
- [x] structured database-first packet과 db_only·abstract_targeted·fulltext_escalated decision contract 구현
- [x] PubMed·validation·cross-site search 중복 제거와 route provenance·cache 재사용 구현
- [x] Qwen evidence synthesis·report 호환성·회귀 테스트·GitHub main 반영

## RAG Enrichment DB-First 순서 및 Progress 표시 정합성 점검
- [x] 최신 runtime/worker가 DB packet 완료 후에만 literature route를 판정하는지 확인
- [x] `articles` progress count가 route별 실제 PubMed 검색 여부를 정확히 반영하도록 수정
- [x] DB-first execution order와 db_only·abstract_targeted progress 회귀 검증

## PTM Selection Mode 기반 RAG Enrichment Input Filtering
- [x] De novo+Regulated·All PTMs selection mode의 frontend payload·API·worker 전달 경로 점검
- [x] mode별 RAG input universe·gene/site deduplication·DB/PubMed budget 정책 설계
- [x] mode-aware filtering·progress provenance·회귀 테스트 구현

## RAG Enrichment Structured Database Source 실행·표시 감사
- [x] UniProt·STRING·KEGG·iPTMnet·Reactome·BioGRID의 worker 호출·cache·packet 저장 경로 점검
- [x] source별 progress event·API payload·frontend 표시 시점 점검
- [x] source별 호출·저장·표시 차이와 개선 권고 정리

## RAG Enrichment Structured DB Source Summary UI
- [x] Phase A source별 done·cache-hit·empty·skip·error 및 result count event contract 구현
- [x] Worker source-summary provenance와 route 결과 조립 구현
- [x] Admin/User progress 및 Phase modal의 source별 summary UI 구현
- [x] 회귀 테스트·frontend type 검증·GitHub main 반영

## Rat Direct Evidence + Human Ortholog Conserved-site 보조 Evidence 설계
- [x] BioGRID rat organism query·direct interaction coverage·오류/빈 결과 provenance 점검
- [x] iPTMnet exact rat hit 우선, aligned human ortholog conserved-site 보조 evidence contract 설계
- [x] direct·cross-species evidence 분리 표시·routing·report wording 검증 기준 정의
- [x] direct rat hit 보존·unique one-to-one aligned human conserved-site fallback·BioGRID interaction provenance 구현 및 회귀 검증

## Mouse/Rat 공통 Native-species Ortholog Evidence
- [x] direct mouse/rat hit 보존, species-aware one-to-one aligned human fallback 일반화
- [x] human transgene 제외·native_species provenance·mouse regression 검증 및 GitHub 반영

## BioGRID Runtime Error 진단
- [x] MCP server의 BioGRID API key 주입·HTTP response·timeout·source event error 원인 확인
- [x] MCP compose environment에 BIOGRID_API_KEY propagation 추가
- [x] 유효한 BIOGRID_API_KEY로 MCP server 재생성 후 direct rat/mouse query runtime 검증
      (human TP53 100건, mouse Akt1 99건, rat Akt1 23건·Mapk1 100건, worker MCP 경로 포함 `error=None`)
- [x] `.env.example`에 BIOGRID_API_KEY 항목 추가 (compose만 배선되어 있어 설정 가능성이 드러나지 않던 문제)
- [ ] BioGRID `max: 100` 상한 검토 — hub 단백질은 실제 연결 수가 잘려 "100 = 이상"으로 읽어야 함

## iPTMnet Public Lookup Resilience
- [x] iPTMnet timeout·HTTP error·HTML parse failure·cache fallback의 현재 처리 경로 점검
- [x] bounded retry/backoff·stale cache provenance·failure reason observability 보완 및 회귀 검증
- [x] live iPTMnet direct mouse·rat·human query를 현재 client 경로로 실행하여 hit·empty·error provenance 확인
- [x] live iPTMnet entry table의 checkbox-leading column schema에 맞춘 header-aware parser 수정 및 multi-species re-query
- [x] obsolete GET gene-search fallback을 iPTMnet CSRF POST form path로 교체하고 non-mapped rat site query 재검증
- [x] parser schema repair 이전에 저장된 false-empty result를 우회하도록 iPTMnet success cache version 분리
- [x] gene search에 `selectOrg` taxon filter 배선 — 무필터 검색은 rat `Akt1`에 사람 P31749를 먼저 돌려주어
      사람 증거가 rat site 증거로 보고됐음 (rat P47196 / human P35568 vs rat P35570 분리 확인)
- [x] entry page organism 검증 추가 — 다른 종 entry는 NOVEL이 아니라 UNKNOWN + failure_reason으로 처리
- [x] 헤더 미인식(`entry_schema_unrecognized`) 감지 — table은 있고 컬럼명만 바뀐 경우도 이전과 동일하게
      조용히 NOVEL로 보고되던 구멍을 막음
- [x] entry URL fragment(`#asSub`/`#asEnz`/`#efip`) 제거 — 상위 3개 슬롯이 한 단백질로 소진되던 문제
- [x] association table(`Interactant`/`Association type`)을 substrate PTM 증거와 분리
- [x] cache version v3으로 상향 (파싱 의미 변경) + 회귀 테스트 16개 통과 + live HTTP 경로 재검증

## Research Question-driven Report Coverage
- [x] 첨부 report의 10개 사용자 입력 Research Questions와 실제 section·prompt·evidence 연결 경로 점검
- [x] question별 answer status·evidence source·unanswered limitation을 포함하는 report planning contract 설계
- [x] writer·PDF/report template에 question coverage matrix와 질문별 Results/Discussion rendering 구현·검증

## Substrate-level Temporal Dynamics Deepening
- [ ] 최신 temporal/co-wave substrate pattern code와 transient burst 단일 분류의 적용 범위 점검
- [ ] onset·peak·duration·rebound·반복성·조건 특이성 기반 substrate pattern taxonomy와 confidence guardrail 설계
- [ ] substrate dynamics를 co-wave·TMM·condition comparison·report에 연결하는 phased implementation 및 insulin benchmark 계획 수립

## Temporal Cascade Report Architecture
- [x] 통합 report의 핵심 cascade narrative와 별도 substrate dynamics atlas report의 역할·공유 data contract 정의
- [x] 시간 window·condition·co-wave transition·kinase context 기반의 cascade story generation과 interpretation boundary 설계
- [x] Atlas에 substrate pattern·autophosphorylation·nuclear PTM·upstream kinase/TMM·후속 non-PTM dynamics evidence layer 추가
- [x] Atlas와 통합 report의 shared claim ledger·section-level evidence reference·wording consistency gate 구현

## Atlas Temporal Cascade Narrative Guardrails
- [x] 사용자 제시 시간창별 insulin cascade narrative의 observed data·literature support·hypothesis claim 분해
- [ ] novelty wording·citation verification·site-specific directness·causality boundary를 포함한 Atlas narrative template 정의

## Time-varying Substrate Co-movement Transitions
- [x] windowed co-movement persistence·split·merge·recruitment·independent activation metrics와 stability guardrail 정의
- [x] Atlas transition map과 시간창별 substrate divergence narrative를 co-wave·TMM·autophosphorylation·non-PTM evidence에 연결

## Post-upgrade Temporal Dynamics Review
- [x] 최신 main의 substrate dynamics·transition·Atlas/report 변경 범위와 기존 계획 정합성 검토
- [x] syntax/test·provenance·causality guardrail·regression risk를 점검하고 후속 조치 정리

## P1.1 Atlas Quality Promotion and Form-aware Provenance
- [x] oscillatory_supported 승격에 LOTO stability·threshold-insensitivity·missingness gate를 의무화하고 미충족 시 multi_peak_candidate로 강등
- [x] Atlas API/report에 LOTO·threshold sensitivity·q-value coverage·실제 observed count를 노출하고 quality-based narrative eligibility 적용
- [x] site_form_key를 보존하고 명시적 site aggregation contract를 도입하여 first-record form/charge collapse 방지
- [x] P0 ordering/duplicate warning이 있는 trajectory를 atlas_eligible=false 또는 needs_input_audit로 표시
- [x] Atlas frontend UI에 quality·form provenance·claim/transition map을 시각화

## Temporal Substrate Dynamics Atlas Frontend
- [x] Order Detail Atlas tab에 pattern/time-window overview와 quality summary 구현
- [x] observed transition map, site/form drawer, kinase/TMM·self-PTM·nuclear·non-PTM context panel 구현
- [x] Atlas API loading/error/empty states와 TypeScript 검증
- [ ] authenticated Order Detail에서 Atlas visual/end-to-end review 및 GitHub main 반영

## Temporal Atlas Existing-order 500 Recovery
- [ ] `/substrate-temporal` 500 stack trace와 실패 order의 persisted artifact compatibility 원인 확인
- [x] legacy order safe fallback·response serialization guard·endpoint regression 구현
- [ ] 최신 API server 재시작 후 실패 order에서 `/substrate-temporal` runtime recovery 확인 및 GitHub 반영

## P3b Dynamic Transitions and Atlas Evidence-to-Report
- [x] windowed persistence·split·merge·recruitment·exit·independent activation engine 및 stability gate 구현
- [x] per-site/per-window/group transition evidence를 Atlas narrative와 integrated report writer에 전달

## Approved Atlas Implementation Sequence
- [x] Phase 1: P1.1 quality promotion과 P0 Atlas eligibility gate 구현·검증
- [x] Phase 2: form-aware substrate provenance와 explicit site aggregation contract 구현·검증
- [x] Phase 3: P3b dynamic co-movement transition engine 구현·검증
- [x] Phase 4: autophosphorylation·nuclear PTM·TMM·non-PTM context evidence join 구현·검증
- [x] Phase 5: Atlas–integrated report shared claim ledger와 writer integration 구현·end-to-end 검증

## Verification Checklist Follow-up Review
- [x] verification checklist의 완료·부분 완료·미구현 항목을 Temporal Dynamics/Atlas 최신 코드와 대조
- [x] checklist 기반 temporal stability·form provenance·transition·Atlas/report 보완 과제의 우선순위 확정

## Insulin Blind Benchmark — Manuscript Output Package
- [ ] 논문 주장 단위와 benchmark 정량 지표의 claim-to-metric matrix 정의
- [ ] Primary·Supplementary figure, 표, 원자료 파일의 논문용 구성 확정
- [ ] Anchor bootstrap·replicate resampling·time permutation·branch macro-average의 통계 표기 계약 정의
- [ ] SVG/PDF/PNG figure와 TSV/JSON 원자료를 포함하는 versioned benchmark result bundle 설계
- [ ] Locked truth·discovery·scoring·perturbation validation 결과의 물리적·논리적 분리 구현

## Insulin Blind Benchmark — Order 연계 사용 흐름
- [ ] 기존 Order 생성·전처리·분석·Report 흐름을 보존하는 benchmark run 진입점과 권한 모델 설계
- [ ] 완료된 분석 Order를 immutable benchmark input으로 선택하고, generic blind context·manifest·locked scorer를 적용하는 UX 정의
- [ ] Order 결과와 benchmark score/figure/result bundle의 링크·재실행·truth reveal audit 규칙 정의

## Insulin Blind Benchmark — Current Order Blindness Audit
- [ ] Order의 treatment·cell type·biological question·special condition·RAG collection이 worker·LLM·report에 전달되는 실제 경로 감사
- [ ] Benchmark run에서 stimulus·question·dataset-identifying context를 차단하거나 generic 값으로 대체하는 server-side context builder 설계
- [ ] Blind discovery·locked scoring·truth reveal을 분리하고, 원래 Order의 입력·report·rerun을 변경하지 않는 audit log 및 UI 정책 정의

## Insulin Blind Benchmark — Order Detail Entry UX
- [ ] 완료된 time-course Order Detail의 Benchmark Evaluation 버튼·eligibility preflight·권한 정책 설계
- [ ] source Order의 민감 문맥을 표시하지 않고 generic context만 생성하는 locked primary benchmark modal 설계
- [ ] strict primary·literature-assisted secondary·perturbation validation을 별도 run type으로 노출하는 결과·재실행 UX 정의

## Insulin Blind Benchmark — Cell Context Policy
- [ ] cell lineage/class와 식별성 높은 cell-line·transgene·disease model 명칭을 분리하는 benchmark context schema 정의
- [ ] strict primary에서 lineage-level context만 보존하고, dataset-identifying alias를 차단하는 server-side sanitizer 설계
- [ ] cell context 보존·완전 마스킹·literature-assisted 세 조건을 구분해 성능과 specificity를 보고하는 policy 정의

## Insulin Blind Benchmark — Iterative Development and Generalization
- [ ] benchmark 결과 기반 개선 요구를 error taxonomy와 preregistered change request로 기록하는 version ledger 설계
- [ ] development subset·frozen internal test·external held-out stimulus/dataset을 분리하는 anti-overfitting protocol 정의
- [ ] version별 paired bootstrap·branch safety·negative-control·permutation 결과를 비교하고 최종 freeze를 선언하는 release gate 설계

## Insulin Blind Benchmark — Optimized Model and Inhibitor Validation
- [ ] insulin benchmark 최적화 score를 development-performance로 명확히 고정하고 final model freeze를 선언하는 release policy 정의
- [ ] 동일 time-course vehicle·insulin·inhibitor·insulin+inhibitor contrast의 sample·normalization·replicate contract 정의
- [ ] TMM contribution·target Wave·kinase rank·directionality·branch selectivity를 포함한 perturbation validation endpoint와 논문 figure 설계

## Insulin Blind Benchmark — High-sensitivity Discovery Track
- [ ] Tier 1/2 canonical score와 novel·Tier 3/4·deep-coverage PTM discovery 결과를 분리 보존하는 dual-track result contract 정의
- [ ] novel PTM의 sequence/localization·replicate·temporal reproducibility·protein-normalization·multi-evidence 품질 등급과 validation queue 설계
- [ ] discovery yield·time-resolved novelty atlas·kinase/TMM/wave linkage·supplementary source-data를 포함하는 논문용 visualization bundle 정의

## Pre-Benchmark PTM-platform Three-Layer Code Audit
- [x] 0층 원래 Order 전처리→RAG→Report pipeline의 task dispatch·artifact·kinase score/report 영향 범위 확인
- [x] 1층 Temporal Wave·TMM·directionality·dual-track·Atlas의 Order 결과·frontend·report 실제 연결과 feature gate 감사
- [x] 2층 Representation Learning C0–C3·gate·tau·pre-registration stack의 runtime isolation, persisted artifact, Order/kinase score/report 부작용 감사
- [x] benchmark가 평가할 production analysis contract와 제외할 experimental validation contract를 문서·test·manifest 수준에서 확정

## Benchmark Framework Implementation — P0/P1
- [x] generic `benchmarking` package와 versioned manifest/contract schema 구현
- [x] analysis runtime에서 import할 수 없는 locked-truth adapter·scorer boundary 구현
- [x] insulin workbook을 `insulin_signaling_v1` dataset manifest와 locked reference bundle로 변환
- [x] sequence-aware anchor matcher, Tier 1/2 component scorer, provenance/result bundle writer 구현
- [x] production contract (`tmm_full_temporal`)·blind policy·input/truth hash를 immutable result metadata로 저장
- [ ] fixture 기반 unit test, source-boundary test, syntax/test validation, GitHub main commit/push 수행
