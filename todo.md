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
- [x] fixture 기반 unit test, source-boundary test, syntax/test validation, GitHub main commit/push 수행

## GitHub Credential Security Follow-up
- [x] 대화에 노출된 GitHub PAT를 GitHub 보안 설정에서 revoke
- [x] 브라우저 기반 GitHub 로그인 및 저장소 write 접근 재연결
- [x] 새 PAT를 저장·대화 전송하지 않는 인증 운영 원칙 확인

## Order-Integrated Blind BenchmarkRun Implementation
- [x] 최신 GitHub main 기준 Order·worker·artifact·frontend 통합 지점 재확인
- [x] BenchmarkRun persistence, status lifecycle, permission, immutable source-order snapshot API 구현
- [x] server-side BlindContextBuilder와 lineage-only cell context sanitizer 구현
- [x] 0층+1층 `tmm_full_temporal` artifact adapter와 generic site observation export 구현
- [x] offline locked scorer job, provenance/result bundle, truth-reveal audit 구현
- [x] Order Detail preflight·strict primary launch·status·score/figure results UI 구현
- [x] API/worker/frontend/benchmark boundary 회귀 테스트, syntax validation, GitHub main push 수행

## Benchmark Evaluation 탭 표시 진단
- [x] latest frontend source의 Benchmark tab import·trigger·content 렌더링 조건 확인
- [x] 실행 중인 frontend image/bundle 및 Docker Compose frontend service가 `68b0086` 이후 build인지 확인
- [x] Order 상태·shared view·tab layout에 따른 숨김 조건 수정 및 실제 화면 검증

## Insulin Manifest Runtime Path Repair
- [x] API preflight가 사용하는 manifest lookup 경로와 `BENCHMARK_REFERENCE_DIR` 설정 확인
- [x] API server와 offline benchmark-runner의 insulin reference read-only mount를 공통 contract로 수정
- [x] manifest preflight regression·Compose mount validation·GitHub main 반영 및 재배포 절차 확인

## Start Blind Benchmark HTTP 500 진단
- [ ] 운영 API의 benchmark preflight·registration 500 traceback 및 request payload 확인
- [ ] manifest loading·Order access·BenchmarkRun persistence 예외를 안전한 API 오류로 수정
- [ ] preflight·run registration 회귀 테스트와 GitHub main 반영 후 운영 재실행 확인

## TMM Full Temporal + Locked Score Interrupted
- [ ] 해당 BenchmarkRun의 API TMM task 상태·child artifact·benchmark-runner 로그 수집
- [x] production global-kinase TMM 호출 또는 offline scorer dispatch 중단 원인 수정
- [ ] 동일 snapshot run의 Retry TMM + locked score 완료와 Figure 1–4/data bundle 생성 확인

## Direct TMM Interruption Code Audit
- [x] `run-temporal-analysis` endpoint의 blocking await, timeout, task state transition 및 retry idempotency 점검
- [x] full TMM request build·production endpoint reuse·offline scorer dispatch의 artifact persistence 경로 점검
- [x] backend 코드만으로 재현 가능한 interrupted 상태 회귀 test와 safe resume 처리 추가

## Long-running TMM Watchdog and Queue Diagnosis
- [ ] 2시간 이상 TMM running BenchmarkRun의 Celery queue 소비·worker process·task traceback 확인
- [x] progress heartbeat·soft/hard timeout·stale-task recovery contract를 TMM worker에 추가
- [ ] 동일 snapshot의 stale TMM task를 안전하게 failed/retryable 상태로 복구하고 Figure 1–4 completion 확인

## Benchmark Polling Failed-to-fetch Diagnosis
- [x] BenchmarkEvaluationPanel의 status polling interval·abort·error fallback과 API endpoint contract 감사
- [x] API restart·CORS/network failure·frontend/API/worker revision mismatch를 운영 상태와 코드로 분리
- [ ] polling backoff·last-known status 유지·deployment revision 표시를 추가하고 재배포 검증

## Benchmark Stage-aware Progress UI
- [x] completed child snapshot의 100% progress가 TMM 진행률로 재사용되는 현재 status payload·UI 경로 감사
- [x] TMM worker heartbeat stage·stage progress·locked scorer 상태를 BenchmarkRun API payload에 추가
- [x] snapshot/TMM/scoring/checkpoint를 분리한 단계별 UI와 완료 판정·Figure 1–4 ready 표시 구현

## Benchmark Figure Publication Rendering Repair
- [x] Figure 1–4 SVG의 Korean glyph fallback·font-family 및 source-data-to-panel 렌더링 경로 감사
- [x] English scientific typography와 explicit unavailable-data panel을 Figure 1–4 renderer에 구현
- [x] regenerated Figure 1–4 SVG와 source-data bundle을 visual/syntax regression으로 검증

## User Raw-data Benchmark Reproduction
- [x] report.pr_matrix.tsv·report.pg_matrix.tsv·Rat+human INSR FASTA의 column schema·sample metadata·mapping provenance 확인
- [x] 동일 strict 0층+1층 TMM pipeline을 로컬에서 실행하여 kinase profile·contribution matrix·cascade artifact 누락 지점 재현
- [x] 실데이터 TMM output persistence를 수정하고 Figure 1–4/source TSV bundle에 실제 profile·cascade를 반영
- [x] raw-data benchmark run 결과와 platform run을 대조하고 논문용 artifact 완전성을 검증

## Insulin Benchmark 변수 최적화 및 논문 전략
- [x] 첨부 workbook과 runner-only locked reference의 hash·sheet·anchor 동일성 검증
- [x] 최신 GitHub main 동기화 및 현재 raw-data 기준선 결과 재현
- [x] preprocessing·Wave·kinase module·TMM·directionality·scoring 변수 registry와 의존성 정의
- [x] insulin truth leakage와 반복 benchmark 과적합을 차단하는 train·validation·locked-test 계약 구현
- [x] 단일 변수 민감도·상호작용·nested optimization·replicate holdout 실행
- [x] 최적 설정의 견고성·독립 subset·효과크기·불확실성 분석 및 baseline 비교
- [x] 선택된 설정을 explicit strict-benchmark production contract로 구현하고 Python·회귀 테스트 검증
- [x] 논문용 Methods·Results·ablation·claim boundary·후속 inhibitor validation 전략 작성
- [x] 서버 이전용 code/config/hash/verification 명령 패키지 작성 및 GitHub main 반영 준비

## Post-optimization Insulin Benchmark Improvement Review
- [x] optimized raw artifact의 profile provenance·candidate multiplicity·guard outcome·directionality·chain completeness 병목 정량화
- [x] preprocessing·Wave·TMM candidate graph·profile estimation·directionality·locked scorer seam별 추가 개발 가능성 감사
- [x] 개선 후보별 예상 효과·과적합 위험·구현 난이도·논문 기여도와 필수 validation 정의
- [x] 서버 승격 전 P0/P1/P2 개발 우선순위와 중단 기준을 포함한 권고안 작성

## Strict-blind Temporal Attribution Upgrade — Full Implementation
- [x] latest GitHub main 동기화 및 workbook-inaccessible truth-free optimization ledger/config registry 구현
- [x] canonical `GENE_SITE` key 단일화와 relative·occupancy contribution matrix/track provenance 분리
- [x] raw weighted sum·support-normalized effect size·evidence mass·shrunken activity의 이중 score contract 구현
- [x] continuous motif likelihood, proteome-background/null calibration, kinase-family ambiguity hierarchy 구현
- [x] resolved shared-site adaptive bootstrap/LOTO CI와 identifiability·top1 probability provenance 구현
- [x] high-identifiability shared site 기반 iterative data-derived kinase profile estimation 구현 및 holdout reject/rounds-zero 동결
- [x] replicate-bootstrap consensus Wave, membership probability, soft boundary membership 구현
- [x] abundance–occupancy concordance/discordance evidence classification과 Report/source-data 전달 구현
- [x] secondary kinase/temporal locked metrics와 prior-aware directionality evidence gate 구현
- [x] actual PR/PG/FASTA에 대한 truth-free trial ledger 반복 실행·중단 기준·configuration freeze 수행
- [x] frozen full run 후 offline locked scorer 실행, Figure 1–4/source data/Methods/Results 재생성
- [x] Python·regression·blind-boundary 검증, GitHub main 반영과 서버 handoff package 작성 준비

## Enrichment-free Temporal Mechanism Benchmark Competitiveness Review
- [x] current benchmark가 PTM·non-PTM protein time-course, cross-layer cascade, falsifiable mechanism hypothesis를 실제 평가하는 범위 감사
- [x] final frozen-v2 artifact와 runner-only secondary score에서 data-anchored kinase coverage·timing accuracy 0의 정확한 원인 분해
- [x] 플랫폼 전체 Wave·TMM·non-PTM effector·RAG·LLM 병용 시 생성되는 추가 데이터 가치와 leakage-safe 평가 계층 정의
- [x] kinase direct evidence·timing·cross-layer mechanism benchmark를 강화하는 P0/P1/P2 재설계와 검증 기준 작성

## Benchmark v1 + Additive v2 Integration Plan
- [x] v1 strict-blind·canonical scoring·TMM·uncertainty·discovery·publication·worker 운영 계약 중 보존할 자산 목록화
- [x] v1 유지·v2 additive 확장·교체 금지 항목을 compatibility matrix로 정의
- [x] 기존 primary score와 Figure 1–4를 깨지 않는 versioned artifact·score·source-data 통합 구조 설계
- [x] shadow run·noninferiority gate·rollback을 포함한 점진적 구현 및 서버 승격 계획 작성

## Benchmark v1 + Additive v2 Full Implementation and Optimization
- [x] latest main 동기화, supplied raw input hash 확인, v1 golden artifact·score·Figure/source semantic baseline 고정
- [x] versioned `v1_core`·`v2_extensions` sidecar artifact와 v1-only compatibility adapter 구현
- [x] 8,905 protein time-course와 2,447 PTM–protein same-gene pair, replicate/missingness provenance 구현
- [x] cross-layer PTM→protein/non-PTM effector DirectedTemporalRelationship와 causal-overclaim-free contract 구현
- [x] accession-first·FASTA record OX·isoform/site-aware direct kinase evidence와 versioned annotation audit 구현
- [x] data-anchored timing coverage/accuracy/error/interval-overlap 및 denominator-zero `not_evaluable` 구현
- [x] ordered mechanism chain·counterevidence·interpretation-ready hypothesis evidence packet 구현
- [x] 기존 v1 truth를 상속하는 runner-only additive v2 truth/workbook adapter와 immutable hash 구현
- [x] `primary_v1`·`kinase_evidence_v2`·`cross_layer_v2`·`mechanism_v2`·`refutation_v2` 독립 scorer 구현
- [x] v1 panel·source columns를 보존하는 additive Figure 1–4/source-data renderer 구현
- [x] truth-free cross-layer 변수 grid를 grouped replicate/LOTO로 병렬 평가하고 hash-chained ledger에 선택·기각 기록
- [x] 동일 raw input에서 v1-only와 v1+v2 shadow run, v1 noninferiority와 v2 acceptance 확인
- [x] frozen full replay 후 runner-only offline locked v1+v2 평가와 final Figure 1–4 재생성
- [x] 논문용 Methods·Results·ablation·claim boundary·source data·visual QC 문서 작성
- [x] Python/TypeScript·blind-boundary·worker·publication regression, GitHub main push, target-server handoff package 작성

## Unified Production + Benchmark Temporal PTM–Protein Analysis
- [x] 일반 Order·benchmark runner의 PTM–protein temporal analysis 경로와 result contract 차이 감사
- [x] 공용 cross-layer configuration·provenance·evidence packet contract 설계 및 benchmark blind-score boundary 명시
- [x] 일반 Order 분석이 공용 PTM–protein sidecar engine을 실행하도록 integration 구현
- [x] Report·Data-Grounded Analysis·RAG/LLM에 공용 cross-layer evidence packet 전달
- [x] 일반 Order와 benchmark shadow replay의 공용-engine parity·v1 noninferiority·blind-boundary regression 검증
- [x] Python/TypeScript 검증, GitHub main 반영 및 운영 적용 가이드 보고

## Final Unified Benchmark Raw Replay and Manuscript Section
- [x] immutable raw PR/PG/FASTA input hashes, frozen configuration, runner-only workbook truth boundary 재확인
- [x] final unified benchmark engine으로 full raw replay와 v1+v2 artifact 재생성
- [x] runner-only locked v1 primary 및 additive v2 independent score·통계 요약 생성
- [x] Figures 1–4, source data, SVG text-to-path 및 visual QC 재생성
- [x] 논문용 Benchmark Methods·Results·Discussion·통계표와 figure legends 작성
- [x] blind-boundary·v1 noninferiority·handoff 검증 및 재현성 manifest 작성

## Corrected Integrated Benchmark Reporting and Non-empty Figure Delivery
- [x] SVG attachment blank-rendering 원인 진단 및 PNG/PDF-compatible figure export 경로 확정
- [x] v1/v2 label을 사용자-facing 결과·통계·Figure에서 제거한 통합 temporal PTM–protein benchmark reporting contract 구현
- [x] current-head raw replay 기반 통합 benchmark statistics, Figures 1–4, PNG previews 및 PDF figure bundle 재생성
- [x] 모든 PNG/PDF Figure의 non-empty visual QC, source-data correspondence 및 integrated manuscript section 검증
- [x] corrected code·manuscript·figure bundle GitHub main 반영 및 deliverables 재제공

## Leakage-Safe Truth-Based Development and Holdout Optimization
- [x] locked truth denominator·anchor strata 감사 및 development/holdout 분할 가능성 평가
- [x] truth-free artifact·runner-only development scorer·failure taxonomy protocol 구현
- [x] 사전등록된 제한 변수 후보를 development truth에서 평가하고 ledger에 기록 (eligibility failure로 empty grid/no tuning 결정)
- [x] generalizable 개선 구현 후 untouched holdout truth로 단회 평가 (insufficient denominator로 holdout claim 차단)
- [x] truth-free raw replay·semantic noninferiority·blind boundary·regression 검증
- [x] 최적화 Methods·Results·overfitting boundary 문서화 및 GitHub main 반영

## Workbook-Evidence-Only PTM–Protein Reference Extension
- [x] workbook sheet·curated field 근거와 optional truth schema 감사
- [x] workbook-derived reference만 허용하는 optional PTM–protein truth derivation 구현
- [x] frozen integrated artifact를 runner-only cross-layer·mechanism evaluator로 재평가
- [x] derivation provenance·non-evaluable boundary·benchmark report 업데이트
- [x] regression·blind isolation 검증, GitHub main 반영 및 평가 결과 전달

## Dynamic Co-Wave Transition Truth-Free Candidate Evaluation
- [x] static co-wave baseline, timepoint resolution, transition feasibility 및 confounder 감사
- [x] dynamic local-membership·transition stability·acceptance metrics preregistration
- [x] pair-transition full serialization을 production-safe compact summary·top-event representation으로 제한
- [x] 공용 dynamic co-wave transition engine·artifact provenance·regression 구현
- [x] real raw artifact에서 static 대비 dynamic truth-free metrics 계산
- [x] preregistered adoption gate, blind boundary, v1 noninferiority 및 full regression 검증
- [x] 채택 또는 보류 Methods·Results 문서화, GitHub main 반영 및 결과 보고

## Final Dynamic Co-Wave Truth-Free Graphs and Manuscript Section
- [x] current commit·frozen numeric inputs·truth-free exclusion·graph plan 확인
- [x] selected dynamic transition 포함 final truth-free artifact 및 metric replay 실행
- [x] static 대비 dynamic coverage·LOTO·transition·cross-layer alignment graph와 source data 생성
- [x] PNG/PDF non-empty visual QC와 논문용 truth-free purpose·methods·results·discussion 작성
- [x] artifact integrity·blind boundary·regression 검증, GitHub main 반영 및 graph bundle 전달

## Dynamic Co-Wave Transition Full Platform Integration Audit
- [x] 일반 Order·preprocessing·kinase module·PTM–protein sidecar 적용 경로 감사
- [x] API response·database persistence·cache invalidation·full artifact endpoint propagation 점검
- [x] frontend temporal evidence panel·comparative analysis·Report·Chat·Data-Grounded Analysis consumer 적용 점검
- [x] 누락된 공용 configuration/provenance/evidence packet 경로 additive integration 구현
- [x] production regression·TypeScript build·blind isolation·backward compatibility 검증
- [x] 운영 적용 범위·재계산 요구사항 문서화 및 GitHub main 반영

## One-Click Order Temporal PTM–Protein Analysis Orchestration
- [x] existing Order execution, worker, API and frontend trigger orchestration gap 감사
- [x] single-run server-side stage·progress·non-fatal sidecar failure contract 설계
- [x] Global Annotation→canonical Wave/TMM→PTM–protein/dynamic sidecar orchestration 구현
- [x] frontend single-run trigger와 artifact-ready/progress 상태 표시 구현
- [x] end-to-end regression, backward compatibility, blind isolation 및 cross-stack validation (sandbox Docker CLI unavailable; target-server compose validation required)
- [x] 운영 사용법·recomputation semantics 문서화 및 GitHub main 반영

## Dated Insulin Report Before–After Comparison
- [x] 두 DOCX 보고서의 날짜·섹션·표·Figure·정량 text를 추출하고 비교 가능한 기준 확정
- [x] kinase·substrate·PTM–protein·temporal/dynamic co-wave·validation content 차이를 정량·정성 분석
- [x] 최신 보고서의 근거성·기전 해석·claim-boundary 개선과 잔여 약점을 평가
- [x] 사용자용 before-after 비교 보고서 작성 및 전달

## Representation-Benchmark-Augmented Report Comparison
- [x] representation benchmark JSON schema·provenance·quality-check audit
- [x] JSON representation coverage와 최신 report narrative·table·figure usage 대조
- [x] before-after report의 objective representation utilization·claim quality 평가
- [x] 정량 보강 comparison report 작성 및 전달

## Report LLM Numerical Evidence-Contract Upgrade
- [x] current report context assembly, supplement budget, numerical evidence loss 및 claim guard audit
- [x] structured site·wave·TMM·cross-layer·transition·uncertainty evidence packet and tiered claim contract 설계
- [x] report state, question generator and section writers에 compact evidence packet·budget allocation·citation token 구현
- [x] report-fidelity evaluator와 synthetic/real artifact contract regression 구현
- [x] LLM context coverage, claim safety, cross-stack validation 및 blind truth isolation 검증
- [x] 운영 적용 문서, GitHub main 반영 및 개선 결과 전달

## Latest-main Synchronization Before Follow-up Review
- [x] local benchmark worktree의 미반영 500-diagnosis 기록을 보존하고 upstream main과 차이 확인
- [x] GitHub `main` 최신 revision으로 안전하게 rebase/sync
- [x] 최신 commit·clean/retained worktree 상태를 확인하고 후속 질의 준비 완료

## Benchmark Figure 1–4 and Data-sheet Bundle Scope
- [x] latest benchmark code의 Figure 1–4 generator, artifact, result bundle, download API/UI 경로 감사
- [x] inhibitor dependency가 있는 Figure 5 이상을 current strict-primary run에서 제외하는 result contract 확정
- [x] Figure 1–4와 별도 source-data sheet의 저장 경로·파일명·provenance 및 UI 노출 규칙 검증

## New Report Numerical Evidence-Packet Utilization Audit
- [x] 19:00 DOCX의 section·table·figure·internal traceability text와 generation metadata 추출
- [x] 이전 DOCX 대비 site·time·transition·TMM·PTM–protein evidence usage 및 claim safety 대조
- [x] structured packet 기여도·정확성 강화·누락 정보 및 residual failure mode 판정
- [x] 객관 비교 결과 보고서 작성 및 전달

## Representation Benchmark Delta for 19:00 Report Audit
- [x] previous and newly supplied representation JSON의 schema·hash·metric·gate delta 확인
- [x] representation delta와 19:00 Report numerical evidence utilization의 관계 평가
- [x] updated report-fidelity conclusion과 comparison addendum 작성 및 전달

## Report Temporal Evidence Utilization Failure Diagnosis
- [x] Report worker state·packet snapshot·prompt·budget·section writer·deployment code path 감사
- [x] packet delivery failure, stale deployment, prompt omission 및 LLM non-consumption 원인 분리
- [x] mandatory numerical evidence utilization·per-section traceability·review-required failure visibility 구현
- [x] synthetic/real artifact fidelity and prompt-budget regression, blind truth isolation 검증
- [x] 운영 재배포·재실행 절차 문서화 및 GitHub main 반영

## New Report Temporal Evidence Utilization Review
- [x] 신규 DOCX와 representation benchmark JSON의 schema·section·numeric evidence 추출
- [x] dynamic Wave·TMM·uncertainty·PTM→protein·counterevidence의 Report prose 활용 대조
- [x] traceability·observational claim boundary·representation delta를 종합 판정
- [x] 검토 결과와 재현 가능한 후속 조치를 보고

## Production Temporal Sidecar Persistence Repair
- [x] canonical heatmap/TMM completion path와 Order DB update 지점을 latest main에서 확정
- [x] shared sidecar full artifact 생성 및 compact summary의 atomic persistence 구현
- [x] normal Order·legacy cache·Report state의 sidecar 전달 회귀 테스트 구현
- [x] artifact contract·blind truth isolation·worker suite 검증
- [x] 운영 재기동·새 Order/Report artifact 확인 절차 문서화 및 GitHub main 반영

## Post-Fix Production Report Evidence Review
- [x] 신규 packet·fidelity·representation·DOCX의 구조와 핵심 numeric record 추출
- [x] Results·Discussion의 dynamic/TMM/cross-layer/counterevidence prose 활용 대조
- [x] fallback·traceability·observational boundary·representation isolation 종합 판정
- [x] 검토 결론과 재현 가능한 다음 조치를 보고

## Temporal Evidence Readiness Before Report Rerun
- [x] Report rerun API·heatmap computation·UI readiness 상태와 safe dispatch seam 확정
- [x] missing sidecar에서 canonical heatmap/TMM/sidecar를 선행 생성하는 backend orchestration 구현
- [x] UI에 temporal evidence ready/missing·생성 진행·Report 대기 상태 표시
- [x] duplicate dispatch·legacy/manual rerun·normal full Order·blind truth isolation 회귀 검증
- [x] 운영 문서·GitHub main 반영 및 새 Report acceptance criteria 전달

## Dynamic Co-Wave Developer Handoff
- [x] 최신 engine·TMM·sidecar·Report preflight source contract와 commit 상태 확인
- [x] implementation map·data schema·claim boundary·failure semantics를 포함한 인수 문서 작성
- [x] command·file path·acceptance criteria를 code와 대조해 developer handoff 전달

## Dynamic Co-Wave Implementation Review Follow-up
- [x] 첨부 implementation review PDF의 주장·근거·권고 사항 구조화
- [x] 각 지적 사항의 current main code 대조와 existing coverage 확인
- [x] 반영 필요성·우선순위·lineage/claim-boundary 위험을 판정
- [x] 판정 보고와 권고 구현 순서를 전달

## Dynamic Co-Wave P0 Corrective Patch
- [x] default config·inert site event·static-Wave pair scoping seam과 impacted consumers 확인
- [x] canonical threshold alignment·inert event exposure 분리·group-aware pair calculation 구현
- [x] cross-Wave isolation·single-Wave equivalence·version/cache·summary/LOTO/Report packet regression 추가
- [x] shared temporal·benchmark·Report worker·blind truth isolation 전체 검증
- [x] P0 semantics·artifact rerun requirement 문서화 및 GitHub main 반영
