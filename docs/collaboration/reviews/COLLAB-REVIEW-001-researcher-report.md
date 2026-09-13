# COLLAB-REVIEW-001 — 연구자용 PTM 보고서 구현·검증 기록

코드와 합성 회귀를 수정했다. **Order 74의 실제 재생성과 생물학적 해석의 최종 수용 검증은 미완료**다. 아래 합성 산출물을 실제 인슐린 데이터의 개선 결과로 해석하지 않는다.

시작 시 `main`, `origin=https://github.com/Xformyx/PTM-platform.git`, HEAD `3ba713c80c7705b75135fd52481a125ea369c069`를 확인했다. 처음 작업 트리는 깨끗했다. 기존 Cursor의 DOCX 수정과 이 기준 커밋의 정량·identity·release 계약을 유지했다. 검증 당시 변경은 미커밋 작업 트리였으며 배포하지 않았다. 최종 검증의 파일별 SHA256은 [validation.json](researcher-report-20260913/validation.json)에 있다.

## 기록 범위와 원격 통합

- 날짜·작성자: 2026-09-13, Codex 구현 및 합성 검증 기록. 독립적인 사람의 과학적 리뷰가 아니다.
- 대상: 연구자용 보고서 수정 요청. PI·Scientific Reviewer의 별도 판정과 사용자의 최종 과학적 수용은 기록되지 않았다.
- 판정: `changes_requested` — 코드 회귀는 통과했으나 실제 Order 74의 재생성과 생물학적 수용 조건이 남아 있다.
- Mac Studio staging 및 실제 서비스 검증: 미실행. 아래 격리된 macOS 시험의 범위만 확인했다.
- push 준비 중 원격 `aa27e06f5709f7919d282ac640e8a41759021f51`까지 fast-forward로 반영했다. 두 커밋은 문서 정리와 `.gitignore`만 변경하여 시험 대상 소스 해시는 동일하다.
- 새 문서 정책에 따라 이 검토와 검증 기록을 `docs/collaboration/reviews`에 보존한다. 과거 실행 명령과 경로는 실제 실행 기록이므로 원문을 유지한다. 원자료·생성 보고서는 포함하지 않는다.

## 기능별 검토 단위

| 단위 | 변경과 목적 | 주요 코드 |
|---|---|---|
| 종·기능 주석 | unknown을 mouse로 바꾸지 않는다. 명시적 host와 transgene, FASTA-native taxon/혼합 group을 구분한다. collapse 뒤에도 구성 feature의 provenance를 유지한다. species/accession/isoform/version 범위가 cache namespace에 들어간다. 이전 native annotation과 현재 scope가 어긋나면 재검토 사유를 기록한다. | `ptm_shared/annotation_species.py`, `species_registry.py`, `workers/common/species_detector.py`, `rag_enrichment/tasks.py`, `enrichment_pipeline.py`, `ptm_merger.py`, `study_metadata.py` |
| UniProt | FUNCTION 원본 comments/texts를 배열로 보존하고 molecule/isoform comment를 일반 기능 요약과 분리한다. 순서가 바뀌어도 마지막 isoform 설명이 일반 기능을 덮지 않는다. 새 cache key로 과거 요약과 구분한다. | `mcp-server/app/tools/uniprot.py` |
| 질문·서사 | 원질문 ID·원문·정규화·자동 질문 병합 이력을 내부 map에 남긴다. gene/time/adjustment 근거를 연결하고 무관한 단백질로 답을 채우지 않는다. 독립 Q&A 생성/조립을 중단한다. validated Results/Discussion을 이후 절의 입력으로 전달한다. | `research_questions.py`, `reader_authoring.py`, `nodes/writer_node.py`, `graph.py` |
| 실패 보존·복구 | provider 응답, transport의 finish/usage/request ID, 예외 종류, latency, decode/거절 사유, 보완 요청과 fallback을 구분한다. 유효 문장과 완성된 문단을 보존하고 누락 finding 문단만 복구한다. repair가 확장한 문단의 이전 prefix를 반복하지 않는다. | `common/generation_trace.py`, `common/llm_client.py`, `quantitative_claims.py`, `writer_node.py`, `report_generation/tasks.py` |
| 문헌 | 기존 retriever를 연구 배경·gene 기능·site 세 층으로 호출한다. 연구 배경 query는 같은 호출 안에서 공유하고 중복 hit를 제거한다. 한 층 실패가 다른 층의 유효 근거를 지우지 않는다. source quote/offset/hash, 외부 조건, 근거 유형과 비교 생성 실패를 남긴다. | `finding_literature.py`, `reader_authoring.py` |
| 선정·그림 | 같은 품질 등급에서 질문 관련성, parent 및 관측 시간 패턴의 다양성을 먼저 고려한다. 40-card 절단 전에도 이를 적용해 지지되는 부분 궤적을 보존한다. heatmap/보정 비교/시간곡선은 frozen findings를 공유한다. | `measured_feature_cards.py`, `figure_manifest.py`, `nodes/signal_flow_figure.py` |
| 내용 QA·NA | 영어 섹션 목표, 내용 역할, 반복, 질문·문헌·본문 Figure coverage를 검사한다. P value와 P test availability를 분리한다. 모든 P q가 미계산이면 열 대신 각주로 설명하며 q=0은 유지한다. | `common/section_budgets.py`, `ptm_shared/quantitative_fields.py`, `scientific_semantics.py`, `reader_authoring.py` |
| export·provenance | 현재 state의 파생 packet을 manifest에 연결하고 runtime/schema/최종 Figure binding을 기록한다. 빈 이미지 경로가 `.` 디렉터리로 등록되는 경로를 막았다. Word의 중복 alt-caption을 없애고 Figure 제목/이미지/캡션을 함께 유지한다. Markdown reference를 native hyperlink로 출력한다. | `report_artifact_manifest.py`, `tasks.py`, `common/markdown_to_docx.py` |

새 문헌 엔진이나 별도 report pipeline을 만들지 않았다. sample-wise arithmetic mean ratio estimator, 독립 U/P/A, reconstructed 축 분리, de novo/LOD 경계, precursor identity, sparse grid, 부정문·문헌 배경 보존 및 release gate를 유지했다. protein 검정이나 CI를 새로 계산하지 않았다.

## 재현 및 수정한 경계 조건

회귀는 [test_flow_researcher_report.py](../../../workers/tests/test_flow_researcher_report.py)의 26개 테스트와 기존 suite를 함께 사용한다.

- 긴 질문 6개를 legacy compressor에 넣어도 답변을 모두 지우지 않는다. 예산 초과를 숨기지 않으며 일반 보고서에는 독립 Q&A가 없다.
- SRC/EGFR/PTK2 질문에 GENE0의 수치를 답으로 배정하지 않는다. 미지원 질문은 unresolved 상태와 관련 Discussion 문단을 갖는다.
- U가 존재하는데 없다고 쓰는 문장, 잘못된 value token, 단일 site로 축약한 다중 수정 precursor, unsupported exact-site/AKT/pathway 활성 주장 등을 거절한다.
- timeout, malformed JSON, 부분 문장 거절을 구분한다. 거절된 문장은 다른 가설 문단에 근거를 제공하지 못한다. 유효 관측 문장은 누락 문단 복구 후에도 남는다.
- 일반 UniProt FUNCTION과 isoform FUNCTION의 순서 반전, rat host/human transgene, mixed group, 종 누락, stale mouse annotation을 시험한다.
- P 값 존재/P q 미계산과 U 자체 결측을 구분한다. q=0, 60분 gap, 축별 원래 support를 보존한다.
- 동일한 후기 패턴 49개 속에서도 지지되는 초기 부분 궤적을 후보로 남긴다. 특정 insulin gene이나 예시 FC는 production 코드에 넣지 않았다.
- heatmap 시간 문자열의 사전순 오류를 수정했다. 1/5/15/30/60/180분 순서와 명시적 elapsed-time label을 검사한다.
- Figure 1–3의 binding, 본문 finding 일치, 각 requested row의 eligibility, 실제 integer concordance numerator/denominator를 확인한다. caption의 Figure 언급만으로 본문 coverage를 충족하지 않는다.
- 짧은 fallback, 반복된 Discussion, 미해결 질문·종 정보 및 인용 부족은 draft 사유로 남는다.

추가로 실제 formatter에서 중복 정량 catalog 때문에 작은 4-finding 입력이 약 212,000자로 커져 200,000자 상한을 넘는 경로를 확인했다. structured writer는 full support를 가진 token catalog를 한 번만 보내며 같은 입력은 약 122,000자가 된다. 결측 record도 별도 전달한다. full audit packet과 validator의 원본 정량 계약은 축약하지 않았다. 이 수치는 fixture의 입력 크기이며 실제 Order 74 실패 원인을 확정한 결과는 아니다.

## 검증 결과와 재실행

최종 선택 suite: **worker/shared 487 passed + API 40 passed = 527 passed**, 실패·오류·skip 0. 새 researcher 회귀 26개가 포함되어 있으므로 합산하지 않는다. Python 3.14.6의 격리 환경에서 실행했고 변경 Python 31개를 Python 3.11 문법으로 파싱했다. 전체 저장소/production container 검증을 뜻하지 않는다.

```sh
PYTHONPATH=workers:workers/tests:api-server:. \
  /tmp/ptm-report-review-venv/bin/python \
  scripts/validate_observation_temporal_contract.py \
  --include-researcher-review \
  --output-dir docs/validation/researcher-report-20260913

PYTHONPATH=workers:workers/tests:. MPLCONFIGDIR=/tmp/ptm-review-mpl \
  /tmp/ptm-report-review-venv/bin/python scripts/render_researcher_fixture.py \
  --output-dir /tmp/ptm-researcher-render
```

API/worker 시험은 기존의 프로세스 분리를 유지한다. HTTP→React 검증은 synthetic DB/storage를 사용한다. Gemini/RAG는 mock이며 실제 API를 호출하지 않았다. UniProt parser 회귀는 원본 함수의 AST 추출 실행이다. live MCP/DB/Chroma/Celery/Cytoscape, PR/PG 전체 재분석, 배포·장애 주입은 실행하지 않았다.

기존 테스트의 변경은 요청된 정책 변경에 한정했다: selected finding만 비교 Figure에 사용, standalone Q&A 제외, concordance supplementary, 수치가 연결되지 않은 legacy cluster image의 audit 분류, 새 Conclusion 상한 및 짧은 fallback의 draft 상태. 숫자/identity/de novo/부정문/구조적 차단 검사는 제거하거나 완화하지 않았다.

Junit와 명령·소스 hash는 [검증 폴더](researcher-report-20260913)에 보존했다. SciPy의 상수 합성값 경고와 기존 pandas/Matplotlib/Starlette 경고가 있다. 임시 환경의 의존성 설치와 macOS LibreOffice/Chrome 실행은 production dependency 재현이 아니다.

## 같은 합성 입력의 수정 전후

기준 커밋의 Python 소스를 별도 디렉터리로 읽어 동일 `fixture_input.json`을 export했다. 입력 SHA256은 `75c3dfed76eb85f5c9c95e49c839f4b688eff756e89cd305ec019ee0e0912d7f`다. 16개 가상 feature이며 실제 Order 74 수치를 사용하지 않았다. 양쪽 모두 deterministic fallback이고 참고문헌은 0편이다.

| 항목 | 기준 커밋 | 수정 후 |
|---|---:|---:|
| Abstract | 108 words | 158 words |
| Introduction | 110 | 110 |
| Methods | 282 | 282 |
| Results | 266 | 680 |
| Discussion | 224 | 296 |
| Conclusion | 71 | 87 |
| 독립 Q&A heading | 1 | 0 |
| heatmap numeric bindings | 0 | 96 |
| 보정 비교 numeric bindings | 0 | 30 |
| U/P/A trajectory bindings | 72 | 72 |
| 최종 품질 상태 | draft | draft |

Word count는 repo tokenizer와 본문 section 범위 기준이다. 그림/표의 문장을 본문 분량으로 세지 않는다. 길이가 늘어난 사실을 생물학적 설명력 검증으로 해석하지 않는다. Introduction/Methods의 짧은 fallback과 미확보 문헌은 그대로 audit에 남는다. 숫자나 인용을 채워 목표 분량을 맞추지 않았다.

수정 후 `/tmp/ptm-researcher-render/researcher_fixture.{md,docx,html}`와 그림 3개를 생성했다. DOCX를 LibreOffice로 PDF/page PNG에 렌더링하고, HTML은 Chrome 인쇄 결과를 확인했다. 6-inch Word 삽입에서 heatmap의 모든 라벨, 초기 확대창, 결측 gap, 중첩 U/A 표시, Figure 제목/캡션 및 표의 반복 header를 점검했다. 자동 tick bounding-box 검사는 부분 검사이며 실제 페이지 검수를 대신하지 않는다.

합성 산출물 hash·question paragraph links·Figure/NA/quality 상태와 실행 라이브러리는 [render-comparison.json](researcher-report-20260913/render-comparison.json)에 있다. 원자료와 생성 보고서/PNG/PDF는 git에 포함하지 않았다.

## Order 74에서 남은 필수 작업

로컬 Downloads에서 기존 manifest와 SHA256이 일치하는 enriched JSON, temporal sidecar, prose trace, correctness audit, 원 DOCX를 확인했다. 원본은 변경하지 않았다. manifest가 요구하는 vector TSV(52,331,204 bytes, SHA256 `dccfe77ff4d82152183770ca50109fc4dc0b10b14e0324022524ff6cf54d9be9`)는 로컬 파일과 ZIP 검색에서 찾지 못했다.

enriched의 condition 자료에는 모든 시점의 축별 p/q/n/sample IDs가 보존되어 있지 않다. 대표 top-level 통계를 다른 시점에 복사하여 재생성하지 않았다. 같은 vector와 resolved report/model 설정, sample/study manifest, 올바른 rat/FASTA annotation 경로가 필요하다. 종 scope 수정은 과거 JSON을 자동으로 정정했다는 뜻이 아니므로 영향받은 주석을 재검증해야 한다.

이 입력을 확보한 뒤 실제 provider/RAG로 생성하고, 주요 finding의 기능·site 문헌, DOI/PMID, 모델/종/시간 차이를 사람이 확인해야 한다. 특히 다음은 아직 완료로 판정하지 않는다.

- 실제 Order 74의 Results/Discussion 실패 원인 확정, 실제 Gemini 생성 성공률 및 최종 생물학적 설명 평가.
- 실제 데이터에서 ERK 등 초기 기준점의 선정과 모든 원질문의 내용상 답변. gene/time/adjustment matching은 제한적인 규칙이며 일반 pathway·cluster·causal 질문을 자동으로 모두 해결하지 않는다.
- 검증된 20–30편의 실제 채택, 문헌 paraphrase의 의미 검증, RAG collection/database version의 실운영 확인. quote/provenance 검사가 인용 주장의 진실성을 자동 입증하지 않는다.
- 한국어 전용 분량 정책. 영어 단어 기준을 강제하지 않고 미설정 상태를 표시한다.
- replicate-level protein 검정/FDR family/CI, temporal bootstrap/threshold 및 enrichment-free 성능 검증. 이번 prose 수정에서 estimator나 NA 값을 만들어 채우지 않았다.
- production container digest·실제 resolved model/usage, 최종 Order 74 MD/DOCX/HTML 및 페이지 수용 검수. 실제 서비스 값이 없으면 provenance에도 unavailable로 남는다.

기존 dense network 제외, 최종 source/export integrity와 release 상태의 구분을 유지한다. 이 기록은 코드·합성 회귀의 결과이며 논문 제출 가능 보고서의 완료 승인서가 아니다.
