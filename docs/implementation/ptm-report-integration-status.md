# PTM 통합 재정비 구현 상태

작성: 2026-09-18. 최초 checkout과 감사 기준은 `319a6adba2832a4b5cee7058c311f44396381446`이었다. 작업 중 사용자의 최신 커밋 요청에 따라 `6e4b2b88b4d0a7098d1ac3cd593a42338d859144`로 fast-forward했다. TMM API CPU 격리 변경 6개 파일을 보존했으며 겹친 orders.py는 충돌 없는 3-way 병합 후 백업 hash와 대조했다. 시작 시 작업 트리는 깨끗했고 적용할 AGENTS.md는 발견하지 못했다. 사용자 원자료, 과거 산출물, frozen benchmark truth/baseline/사전등록은 수정하지 않았다. 새 구현 commit/push/배포는 수행하지 않았다. 최신 원격 커밋 fetch와 fast-forward만 수행했다.

실제 코드를 변경했으나 **W0–W8 전체 완료 상태는 아니다**. 구현과 fixture 검증, 운영 통합, 렌더, 과학 평가를 구분한다. 확인되지 않은 항목은 아래 제한으로 남긴다. 현재 변경은 운영 rollout 전 검토 대상이다.

## 작업 패키지

| 패키지 | 상태 | 확보한 증거 / 남은 작업 |
|---|---|---|
| W0 | 기준 및 tracker 확보 | 동일 HEAD, 원본 archive에서 6개 import 가능한 실패 재현, baseline 104 pass. 나머지는 개별 baseline 실행 여부를 아래 기록 |
| W1 | 부분 구현·검증 | 기존 identity/evidence/claim 계약 재사용, source status·mapping·revision adapter. 모든 경계 serializer compatibility 증명은 남음 |
| W2 | 부분 구현·검증 | loss/form/charge/QC, biological units, motif anchor, normalization policy, raw inventory. 실제 설계/불완전 replicate/mapping 배포 조합 미완료 |
| W3 | 부분 구현·검증 | source adapter/cache/query quota/upstream handoff. live capability/fulltext/source-faithfulness 평가 미완료 |
| W4 | 부분 구현·검증 | relation scope, pathway denominator, prewriter cross-talk/drug DAG, temporal wiring. cascade 사전 동결·hash 검증. template source 검증과 전체 figure 관계 모델 분리 미완료 |
| W5 | 부분 구현·검증 | 전수 inventory, descriptive module index, adaptive main plan, budget-limited review 상태. 계층별 LLM synthesis와 전체 companion/display 정책 미완료 |
| W6 | 부분 구현·검증 | packet v2, 실제 writer 분할·같은 packet 기반 전체 section 검토, bounded validator repair와 실행 가능한 숫자/표현 규칙·요약 재검증. 추가 검색/새 attempt 및 semantic issue 독립 검증 loop 미완료 |
| W7 | 부분 구현·검증 | revision registry·인용·API/UI·PPTX/비교 pin·migration helper. 실제 모든 format 렌더/브라우저/동시 서비스 검증 미완료 |
| W8 | 회귀 검증, 운영/과학 평가 미완료 | 결과와 명령은 validation 문서. staging/실데이터/domain review/독립 성능 평가를 통과로 기록하지 않음 |

## 이슈별 추적

`baseline_reproduced=true`는 원본 commit의 실제 import 실행에서 실패한 경우다. `static_only`는 소스에서 결함을 확인하고 현재 fixture/회귀를 실행했으나 원본의 해당 개별 fixture는 실행하지 않은 경우다. 모든 행의 `implementation_ref`는 이 문서를 포함하는 구현 변경이며, 짧은 report 경로는 `workers/report_generation/core/`, preprocessing/rag_enrichment/common 경로는 `workers/`를 기준으로 한다. T1–T4 명령은 [검증 기록](ptm-report-validation.md)을 참조한다.

### R01 · W2

- baseline_reproduced: true (OBS-01/02/05)
- affected_paths: `preprocessing/core/ptm_quantification.py; ptm_shared/site_form_provenance.py; ptm_shared/vector_projection.py`
- change_type: bugfix/additive provenance
- implementation_ref: 위 경로의 실제 producer/consumer 변경; [계약 지도](ptm-report-contract-map.md)
- tests_run: OBS-01–05, T2
- expected_numeric_differences: multisite 한 form 유지; charge별 effect 분리; conflict rows quarantine
- integration_status: 로컬 fixture/회귀 범위 구현, 전체 운영 통합 미완료
- remaining_limitations: 중복 FASTA accession의 모든 서열·충돌 annotation fixture는 통과. 모든 실제 importer 조합·species metadata 검증은 남음

### R02 · W2

- baseline_reproduced: true (DET-01/03)
- affected_paths: `preprocessing/core/ptm_quantification.py; measured_feature_cards.py`
- change_type: bugfix
- implementation_ref: 위 경로의 실제 producer/consumer 변경; [계약 지도](ptm-report-contract-map.md)
- tests_run: DET-01/03, 전체 loss import, T2
- expected_numeric_differences: loss 0행→1행; FC/p/q NA; 유효 BH family 불변
- integration_status: 로컬 fixture/회귀 범위 구현, 전체 운영 통합 미완료
- remaining_limitations: 실데이터 검출/QC 조합 미검증

### R03 · W3

- baseline_reproduced: true (REL-01)
- affected_paths: `rag_enrichment/core/regulation_extractor.py; enrichment_pipeline.py`
- change_type: bugfix
- implementation_ref: 위 경로의 실제 producer/consumer 변경; [계약 지도](ptm-report-contract-map.md)
- tests_run: REL-01/02, T2
- expected_numeric_differences: active/passive 동일 AKT1→FOXO3; 부정/간접 positive edge 제거
- integration_status: 로컬 fixture/회귀 범위 구현, 전체 운영 통합 미완료
- remaining_limitations: 규칙 기반 문장 해석의 recall/precision은 독립 검증되지 않음

### R04 · W3

- baseline_reproduced: static_only
- affected_paths: `mcp-server/app/tools/iptmnet.py; mcp-server/app/main.py; common/mcp_client.py`
- change_type: bugfix/schema adapter
- implementation_ref: 위 경로의 실제 producer/consumer 변경; [계약 지도](ptm-report-contract-map.md)
- tests_run: REL-03; cross_species_iptmnet; T2
- expected_numeric_differences: 동일 K 위치의 PTM type 분리; 명시 all-sites; 효소/PMID 보존
- integration_status: 로컬 fixture/회귀 범위 구현, 전체 운영 통합 미완료
- remaining_limitations: live iPTMnet 및 ortholog 서비스 실행 미완료

### R05 · W3

- baseline_reproduced: static_only
- affected_paths: `rag_enrichment/core/ptm_validation.py; mcp-server/app/tools/iptmnet.py`
- change_type: bugfix
- implementation_ref: 위 경로의 실제 producer/consumer 변경; [계약 지도](ptm-report-contract-map.md)
- tests_run: SRC-03; T2
- expected_numeric_differences: no-hit/error의 high novelty 제거; uncertain/source status 유지
- integration_status: 로컬 fixture/회귀 범위 구현, 전체 운영 통합 미완료
- remaining_limitations: 모든 legacy novelty prose 경로 독립 검토 필요

### R06 · W3

- baseline_reproduced: static_only
- affected_paths: `mcp-server/app/tools/kea3.py; common/mcp_client.py; rag_enrichment/tasks.py`
- change_type: adapter/cache fix
- implementation_ref: 위 경로의 실제 producer/consumer 변경; [계약 지도](ptm-report-contract-map.md)
- tests_run: SRC-01/04; T2
- expected_numeric_differences: actual top_kinases/integrated_ranking 소비; 전체 gene-set key 구분
- integration_status: 로컬 fixture/회귀 범위 구현, 전체 운영 통합 미완료
- remaining_limitations: 실제 KEA3 배포 library/capability 확인 미완료

### R07 · W3

- baseline_reproduced: static_only
- affected_paths: `rag_enrichment/core/llm_kinase_predictor.py; nodes/network_node.py`
- change_type: producer/consumer fix
- implementation_ref: 위 경로의 실제 producer/consumer 변경; [계약 지도](ptm-report-contract-map.md)
- tests_run: SRC-02 실제 predictor alias/source fixture; NET-01; T2
- expected_numeric_differences: kinase aliases 일치; model hypothesis 출처, uncalibrated score 표시
- integration_status: 로컬 fixture/회귀 범위 구현, 전체 운영 통합 미완료
- remaining_limitations: live LLM generation 및 모든 legacy consumer 표시 검토 필요

### R08 · W2

- baseline_reproduced: static_only
- affected_paths: `api-server/app/api/orders.py; preprocessing/tasks.py; ptm_shared/sample_manifest.py`
- change_type: wiring/additive crosswalk
- implementation_ref: 위 경로의 실제 producer/consumer 변경; [계약 지도](ptm-report-contract-map.md)
- tests_run: UNIT-01, flow_sample_units, T2/T3
- expected_numeric_differences: secondary 자체 manifest 사용; technical repeats가 biological n 증가시키지 않음
- integration_status: 로컬 fixture/회귀 범위 구현, 전체 운영 통합 미완료
- remaining_limitations: cross-talk의 모든 통계 estimator가 unit crosswalk를 사용하는 것은 아님

### R09 · W4

- baseline_reproduced: static_only
- affected_paths: `reader_authoring.py::_kinase_context_cards`
- change_type: bugfix
- implementation_ref: 위 경로의 실제 producer/consumer 변경; [계약 지도](ptm-report-contract-map.md)
- tests_run: KIN-01 관련 기존 회귀; T2
- expected_numeric_differences: 같은 숫자 3 kinase 후보를 1 family로 병합하지 않고 3개 유지
- integration_status: 로컬 fixture/회귀 범위 구현, 전체 운영 통합 미완료
- remaining_limitations: 실제 생물학적 equivalence evidence 수집은 별도

### R10 · W3

- baseline_reproduced: static_only
- affected_paths: `finding_literature.py; rag_retriever.py`
- change_type: retrieval policy fix
- implementation_ref: 위 경로의 실제 producer/consumer 변경; [계약 지도](ptm-report-contract-map.md)
- tests_run: RAG-01; flow_finding_retrieval; T2
- expected_numeric_differences: n=4 및 review 4/5에도 반환≤4, 원저 slot 유지
- integration_status: 로컬 fixture/회귀 범위 구현, 전체 운영 통합 미완료
- remaining_limitations: 실제 collection relevancy quality 평가 미완료

### R11 · W3

- baseline_reproduced: static_only
- affected_paths: `mcp-server/app/tools/pubmed.py; rag_enrichment/core/llm_kinase_predictor.py; llm_functional_impact.py`
- change_type: versioned search/cache policy
- implementation_ref: 위 경로의 실제 producer/consumer 변경; [계약 지도](ptm-report-contract-map.md)
- tests_run: RAG-02; SRC-04; T2
- expected_numeric_differences: 후속 tier 후보도 rank 참여; 200자 prefix 제거; context/budget key
- integration_status: 로컬 fixture/회귀 범위 구현, 전체 운영 통합 미완료
- remaining_limitations: fulltext depth를 질문 중요도에 배분하는 전 경로 및 실제 source span review 미완료

### R12 · W3

- baseline_reproduced: static_only
- affected_paths: `nodes/writer_node.py; finding_literature.py; citation_formatter.py; graph.py`
- change_type: handoff fix
- implementation_ref: 위 경로의 실제 producer/consumer 변경; [계약 지도](ptm-report-contract-map.md)
- tests_run: flow_finding_retrieval; CITE-01; T2
- expected_numeric_differences: upstream refs를 registry에 전달; DOI 지원; Chroma 재검색 필수 아님
- integration_status: 로컬 fixture/회귀 범위 구현, 전체 운영 통합 미완료
- remaining_limitations: identity supplied와 independently resolved identity 구분; source-faithfulness 검토 필요

### R13 · W5

- baseline_reproduced: static_only
- affected_paths: `measured_feature_cards.py; reader_authoring.py; section_model_packet.py`
- change_type: report policy v1/adaptive planning
- implementation_ref: 위 경로의 실제 producer/consumer 변경; [계약 지도](ptm-report-contract-map.md)
- tests_run: FIND-01/02; bounded retrieval; T2
- expected_numeric_differences: 전수 inventory 보존, word budget main 선택, 중복 parent/pattern 억제
- integration_status: 로컬 fixture/회귀 범위 구현, 전체 운영 통합 미완료
- remaining_limitations: 모든 pathway/figure/companion display cap 이력과 계층별 LLM synthesis 품질 평가 미완료

### R14 · W4/W6

- baseline_reproduced: static_only; compiled DAG에서 추가 import 결함 재현
- affected_paths: `graph.py; nodes/crosstalk_node.py; crosstalk_fallbacks.py; nodes/report_copilot_node.py`
- change_type: DAG/wiring/repair
- implementation_ref: 위 경로의 실제 producer/consumer 변경; [계약 지도](ptm-report-contract-map.md)
- tests_run: DAG-01; REVIEW-01; T2
- expected_numeric_differences: cross-talk/drug 선행; crosstalk typed state 보존; major issue는 draft 유지
- integration_status: 로컬 fixture/회귀 범위 구현, 전체 운영 통합 미완료
- remaining_limitations: cascade template source 검증/관계-layout API 분리, 추가 검색 기반 새 evidence attempt 재저술 loop 미완료

### R15 · W4

- baseline_reproduced: static_only
- affected_paths: `ptm_shared/pathway_expansion.py`
- change_type: bugfix
- implementation_ref: 위 경로의 실제 producer/consumer 변경; [계약 지도](ptm-report-contract-map.md)
- tests_run: pathway shared 회귀; T2
- expected_numeric_differences: pathway 실제 크기가 coverage 분모; co-membership으로 시간 방향 생성 안 함
- integration_status: 로컬 fixture/회귀 범위 구현, 전체 운영 통합 미완료
- remaining_limitations: 실제 pathway snapshot별 분모 대조 미완료

### R16 · W7

- baseline_reproduced: static_only
- affected_paths: `graph.py; citation_formatter.py; report_generation/tasks.py; common/markdown_to_html.py`
- change_type: citation identity fix
- implementation_ref: 위 경로의 실제 producer/consumer 변경; [계약 지도](ptm-report-contract-map.md)
- tests_run: CITE-01 실제 HTML/DOCX read-back; T2
- expected_numeric_differences: 수집 11111/22222, 첫 인용 22222가 본문/popup registry 모두 22222
- integration_status: 로컬 fixture/회귀 범위 구현, 전체 운영 통합 미완료
- remaining_limitations: 실제 브라우저 클릭과 DOCX 시각 렌더 미완료

### R17 · W7

- baseline_reproduced: static_only
- affected_paths: `ptm_shared/report_revision.py; api-server/app/core/report_output_files.py; orders.py; frontend report pages`
- change_type: registry/API compatibility migration
- implementation_ref: 위 경로의 실제 producer/consumer 변경; [계약 지도](ptm-report-contract-map.md)
- tests_run: REV-01/02; MIG-01; T3; frontend build
- expected_numeric_differences: completed와 release 분리; blocked fallback 차단; legacy는 미검증 보존
- integration_status: 로컬 fixture/회귀 범위 구현, 전체 운영 통합 미완료
- remaining_limitations: 실제 API 인증/DB/Celery/UI 운영 흐름과 rollout 미완료

### R18 · W7

- baseline_reproduced: static_only
- affected_paths: `common/pptx_generator.py; pptx_generation/tasks.py; api-server/app/api/presentation.py`
- change_type: source revision pin/SlidePlan
- implementation_ref: 위 경로의 실제 producer/consumer 변경; [계약 지도](ptm-report-contract-map.md)
- tests_run: PPTX-01 plan binding; T2/T3
- expected_numeric_differences: mtime/raw top15/12000자 절단 제거; 끝 한계 유지; NA 99 사용 안 함
- integration_status: 로컬 fixture/회귀 범위 구현, 전체 운영 통합 미완료
- remaining_limitations: python-pptx 없음; 실제 PPTX 생성·시각 render 미실행; 파생물은 draft

### R19 · W3

- baseline_reproduced: static_only
- affected_paths: `mcp-server source clients; common/phase_b_cache.py; preprocessing/tasks.py; enrichment_pipeline.py`
- change_type: versioned cache/invalidation
- implementation_ref: 위 경로의 실제 producer/consumer 변경; [계약 지도](ptm-report-contract-map.md)
- tests_run: SRC-03/04; stage cache/history fixture; T2
- expected_numeric_differences: error 성공 cache 금지; subset reuse 제거; input/config 변경 재계산
- integration_status: 로컬 fixture/회귀 범위 구현, 전체 운영 통합 미완료
- remaining_limitations: source live snapshot/모든 transitive parser dependency 및 동시 rerun service 검증 미완료

### R20 · W2

- baseline_reproduced: static_only
- affected_paths: `preprocessing/core/enhanced_motif_analyzer_v2.py; preprocessing/core/unified_enricher.py`
- change_type: motif policy/bugfix
- implementation_ref: 위 경로의 실제 producer/consumer 변경; [계약 지도](ptm-report-contract-map.md)
- tests_run: MOTIF-01; T2
- expected_numeric_differences: 실제 modified residue에서만 motif; generic regulator 별도 context
- integration_status: 로컬 fixture/회귀 범위 구현, 전체 운영 통합 미완료
- remaining_limitations: legacy unified consumer anchor/typed metadata/cache 변경도 연결함. 외부 motif 기능 해석과 실제 후보 precision은 독립 평가 미완료

### R21 · W2

- baseline_reproduced: static_only
- affected_paths: `ptm_quantification.py; ptm_shared/quantitation_estimator_contract.py; reader_authoring.py; orders.py`
- change_type: versioned normalization policy
- implementation_ref: 위 경로의 실제 producer/consumer 변경; [계약 지도](ptm-report-contract-map.md)
- tests_run: NORM-02 2배 shift; T2
- expected_numeric_differences: legacy median log2 0 유지; explicit already_normalized log2 1; 별도 policy
- integration_status: 로컬 fixture/회귀 범위 구현, 전체 운영 통합 미완료
- remaining_limitations: 정규화 선택 UI와 독립 실데이터 estimator 평가 미완료

### R22 · W4

- baseline_reproduced: static_only
- affected_paths: `nodes/network_node.py`
- change_type: relation level/identity fix
- implementation_ref: 위 경로의 실제 producer/consumer 변경; [계약 지도](ptm-report-contract-map.md)
- tests_run: NET-01; T2
- expected_numeric_differences: PPI gene 수준; reciprocal 유지; multi-form node ID; fallback 직접근거 강등
- integration_status: 로컬 fixture/회귀 범위 구현, 전체 운영 통합 미완료
- remaining_limitations: actual network export/시각화 전체 read-back 및 annotation identity 없는 legacy row 해석 미완료

### R23 · W2/W4

- baseline_reproduced: static_only
- affected_paths: `ptm_shared/temporal_input_reconstruction.py; rag_enrichment/tasks.py; orders.py`
- change_type: versioned replicate adapter/wiring
- implementation_ref: 위 경로의 실제 producer/consumer 변경; [계약 지도](ptm-report-contract-map.md)
- tests_run: TIME-01; study context 회귀; T2/T3
- expected_numeric_differences: 3 biological units×2 technical repeats → n=3 trajectory; means-only no-call
- integration_status: 로컬 fixture/회귀 범위 구현, 전체 운영 통합 미완료
- remaining_limitations: paired complete-unit adapter 범위 밖 불완전 설계의 새 uncertainty estimator는 미구현

### R24 · W4/W7

- baseline_reproduced: static_only
- affected_paths: `temporal_kinase_scoring.py; mcp-server/app/tools/tf_targets.py; dynamic_prompt_generator.py; compare.py; SignalPropagationTimeline.tsx`
- change_type: semantics/derived revision
- implementation_ref: 위 경로의 실제 producer/consumer 변경; [계약 지도](ptm-report-contract-map.md)
- tests_run: CMP-01; T2/T3/T4; frontend build
- expected_numeric_differences: negative FC 보존; ORA/footprint≠activation; 비교 source scope 고정
- integration_status: 로컬 fixture/회귀 범위 구현, 전체 운영 통합 미완료
- remaining_limitations: comparison PDF Typst renderer 없음; TF/TMM 전체 scientific semantics 전문가 검토 미완료

### R25 · W3

- baseline_reproduced: static_only
- affected_paths: `docker-compose.yml; uniprot.py; interpro.py; kea3.py; preprocessing/core/biological_enricher.py; preprocessing/core/unified_enricher.py`
- change_type: source/provenance preservation
- implementation_ref: 위 경로의 실제 producer/consumer 변경; [계약 지도](ptm-report-contract-map.md)
- tests_run: REF-01; T2
- expected_numeric_differences: UniProt PTM/GO 전체 payload 및 source evidence 보존; top-K display 분리
- integration_status: 로컬 fixture/회귀 범위 구현, 전체 운영 통합 미완료
- remaining_limitations: InterPro 전체 페이지/원본 record/상태→unified TSV 보존 fixture 통과. GO의 모든 downstream projection, 실제 reference deployment/library capability 및 licensed source audit 미완료

### R26 · W3/W6

- baseline_reproduced: static_only
- affected_paths: `nodes/research_node.py; nodes/hypothesis_node.py; nodes/validation_node.py; finding_literature.py`
- change_type: claim boundary fix
- implementation_ref: 위 경로의 실제 producer/consumer 변경; [계약 지도](ptm-report-contract-map.md)
- tests_run: RAG-04/05; REVIEW-01; T2
- expected_numeric_differences: gene-count confidence/keyword self-validation 제거; faithful paraphrase 보존 후 pending
- integration_status: 로컬 fixture/회귀 범위 구현, 전체 운영 통합 미완료
- remaining_limitations: 독립 source-faithfulness 및 과학 검증 자동화/전문가 평가 미완료

### R27 · W6

- baseline_reproduced: static_only
- affected_paths: `section_model_packet.py; quantitative_claims.py 소비 계약; nodes/writer_node.py`
- change_type: packet v2/partition
- implementation_ref: 위 경로의 실제 producer/consumer 변경; [계약 지도](ptm-report-contract-map.md)
- tests_run: LLM-01/02; packet 회귀; T2
- expected_numeric_differences: 축/분모/estimator/support/반증 보존; indivisible overflow는 review
- integration_status: 로컬 fixture/회귀 범위 구현, 전체 운영 통합 미완료
- remaining_limitations: provider 실제 tokenizer 없는 경우 byte fallback; 모든 model budget 운영 설정 검증 미완료

### R28 · W8

- baseline_reproduced: not_run (새 평가 범위)
- affected_paths: `benchmarking/tests/test_runtime_boundary.py; workers/api tests`
- change_type: validation only; frozen files unchanged
- implementation_ref: 위 경로의 실제 producer/consumer 변경; [계약 지도](ptm-report-contract-map.md)
- tests_run: T1/T2/T3/T4; converter read-back; frontend build
- expected_numeric_differences: frozen truth/baseline/preregistration 변경 없음
- integration_status: 로컬 fixture/회귀 범위 구현, 전체 운영 통합 미완료
- remaining_limitations: staging, 실제 UI, 전체 시각 render, 대표 실데이터 및 독립 과학 성능은 미완료

## 완료 판정

| 항목 | 판정 |
|---|---|
| 구현 전체 완료 | 아니오. 위 R별 남은 구현/통합 경계를 해결해야 함 |
| 실행 가능한 계약/회귀 | 실제 결과를 validation 문서에 기록; skip은 pass에 포함하지 않음 |
| 실제 API→Celery→저술→export→UI | 미완료. 고정 fixture의 compiled graph/API helper/converter 검증과 다름 |
| 출력 검증 | HTML/DOCX 생성 및 텍스트/인용 read-back 수행. DOCX 시각 렌더 실패, PPTX/PDF 시각 렌더 미실행 |
| 레포트 품질 평가 | 미완료. 실데이터/전문가 표본 검토 없음 |
| 독립 과학 성능 평가 | 미완료. frozen audit 재생은 새로운 holdout 성능 평가가 아님 |

## 최신 commit 재확인

`319a6ad..6e4b2b8`은 TMM 계산의 API 프로세스 격리, timeout 설정/entrypoint와 3개 운영 테스트를 추가한다. 정량/근거/저술 결함의 R01–R28 producer는 변경하지 않아 기존 개별 재현은 여전히 유효한 baseline이다. 최신 HEAD에서 shared/worker/API/benchmark-boundary 검증을 다시 수행하며, API_CPU_BOUND_TIMEOUT_SEC를 과학적 threshold로 취급하지 않는다. 원격 갱신 전 79개 작업 파일을 백업했고, orders.py 외 모든 hash가 동일하며 orders.py는 사전 3-way merge 결과와 일치했다.

## 사용자 요청에 따른 저장소 반영

위 검증은 commit 전 작업 트리에서 수행했다. 검증 후 사용자가 현재 브랜치에 일반 push를 요청하여 `main`과 `origin=https://github.com/Xformyx/PTM-platform.git`을 확인했다. 원격 main과 local HEAD는 모두 `6e4b2b88b4d0a7098d1ac3cd593a42338d859144`였으며, 변경 소스 78개 파일의 hash가 검증 snapshot과 일치했다. 이 문서를 포함하는 commit은 해당 snapshot과 구현/검증 문서를 기록한다. 저장소 반영은 W0–W8 전체 완료 또는 운영 배포를 의미하지 않는다.
