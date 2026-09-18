# PTM 통합 재정비 검증 기록

작성: 2026-09-18. 최신 검증 기준 HEAD는 `6e4b2b88b4d0a7098d1ac3cd593a42338d859144`이며 구현 변경은 그 위의 미커밋 작업 트리다. 최초 감사/재현 기준은 `319a6adba2832a4b5cee7058c311f44396381446`이다. [상태 추적](ptm-report-integration-status.md)과 [계약 지도](ptm-report-contract-map.md)를 함께 읽는다.

## 실행 환경과 결과

macOS, Python 3.14의 별도 임시 venv를 사용했다. 로컬 cache의 wheel을 offline으로 설치했으며 production 환경은 변경하지 않았다. 검증 라이브러리는 pytest 9.1.1, numpy 2.5.3, pandas 3.0.5, scipy 1.18.1, python-docx 1.2.0, langgraph 1.2.11, fastapi 0.141.1이다. production lockfile/컨테이너와 같은 환경이라는 뜻은 아니다.

아래 `$PTM_PYTHON`은 해당 venv의 Python이다. `MPLCONFIGDIR`에는 쓰기 가능한 임시 디렉터리를 사용했다. 각 suite는 별도 프로세스에서 실행했다. 실행 결과와 변경 소스 hash는 [검증 요약 JSON](ptm-report-validation-summary.json)에 기록했다. API의 `app` namespace와 MCP의 `app` namespace, scientific runtime-boundary test의 production import 금지 검사는 한 프로세스에 섞지 않는다.

| 검증 | 실제 결과 | 해석 |
|---|---:|---|
| T1 최초 baseline | 104 passed | 감사 기준 checkout에서 실행 가능한 지정 보호 검사의 결과 |
| 원본 commit의 신규 실패 재현 | 6 failed | 원본 archive의 실제 import 경로에서 OBS-01/02/05, DET-01/03, REL-01 실패 확인 |
| T2 최신 shared + worker 전체 | 1,220 passed, 14 skipped | 최신 source에 대한 계약/회귀. skip은 통과 수에 포함하지 않음 |
| T3 최신 API 전체 | 107 passed | 최신 커밋의 CPU child 반환/timeout/중복 요청 차단 3개 포함 |
| T4 TMM audit + production/truth 경계 | 36 passed | 기존 동결 평가 보호. 신규 독립 과학 성능 증거가 아님 |
| 마지막 변경 경로 집중 검사 | 67 passed | 신규 source/motif/review + cross-talk/finalization |
| frontend `npm run build` | 성공 | TypeScript + Vite. 실제 browser 동작/인용 클릭 검사는 아님 |
| 실제 citation HTML/DOCX converter | 통과 | graph의 최종 registry → 본문/bibliography/HTML modal 데이터/DOI·PMID link 및 DOCX 텍스트 read-back |
| DOCX 시각 render | 실패 | LibreOffice가 Signal 6/AppKit 오류로 종료; PNG/PDF 시각 QA 통과로 기록하지 않음 |
| PPTX 실제 생성/시각 render | 미실행 | python-pptx 없음. pin/SlidePlan/한계/sentinel fixture만 실행 |
| comparison PDF 실제 render | 미실행 | Typst executable 없음. source pin/evidence compatibility/save/export 정책 fixture만 실행 |
| 실제 staging/API→Celery→UI | 미실행 | 사용 가능한 운영 서비스 없음; Docker socket 접근도 제한됨 |
| 실데이터/전문가/독립 perturbation 평가 | 미실행 | 새로운 실데이터·전문가 평가·독립 truth가 제공되지 않음 |

T2 skip 중 13개는 실제 입력 dataset mount가 없기 때문이고 1개는 별도 PTM-CoScientist discussion packet module이 없기 때문이다. warning에는 동일 값 synthetic sample의 scipy precision-loss, pandas regex grouping, figure tight-layout, deprecated plotting API가 있다. 이들을 과학적 정확도 또는 시각 가독성 통과로 해석하지 않는다.

## 실행 명령

T1 — 최초 지정 보호 suite:

```sh
PYTHONPATH=.:workers:api-server "$PTM_PYTHON" -m pytest -q \
  ptm_shared/tests/test_report_mode_contract.py \
  ptm_shared/tests/test_direct_kinase_evidence.py \
  workers/tests/test_evidence_contracts.py \
  workers/tests/test_flow_sample_units.py \
  workers/tests/test_flow_finding_retrieval.py \
  workers/tests/test_report_artifact_manifest.py \
  workers/tests/test_flow_finalization.py \
  workers/tests/test_report_rendering_fidelity.py \
  benchmarking/tests/test_runtime_boundary.py
```

T2 — 최신 shared/worker 전체:

```sh
PYTHONPATH=.:workers:workers/tests:api-server "$PTM_PYTHON" -m pytest -q -rs ptm_shared/tests workers/tests
```

T3 — 최신 API 전체:

```sh
PYTHONPATH=.:workers:api-server "$PTM_PYTHON" -m pytest -q api-server/tests
```

T4 — 동결 평가/production 경계의 별도 프로세스:

```sh
PYTHONPATH=.:workers:api-server "$PTM_PYTHON" -m pytest -q \
  workers/tests/test_tmm_audit_protocol.py benchmarking/tests/test_runtime_boundary.py
```

소스 fixture와 마지막 검토 수정에 대한 집중 검사:

```sh
PYTHONPATH=.:workers:workers/tests:api-server "$PTM_PYTHON" -m pytest -q \
  workers/tests/test_integration_reorganization.py \
  workers/tests/test_crosstalk_pipeline.py workers/tests/test_flow_finalization.py
```

Frontend 디렉터리에서 `npm run build`를 실행했다. root에서 `git diff --check`와 변경 Python 71개 파일 AST parse가 통과했고 pyflakes undefined-name은 0개다. unused import 등 전체 lint 경고를 0개로 만들었다는 뜻은 아니다. `git diff --name-only -- benchmarking` 결과는 비어 있다. dependency 설치 실패·중간 collection 오류·skip은 최종 성공 수에 더하지 않았다.

## 실제 재현과 예상 변화

원본은 `git archive 319a6adba2832a4b5cee7058c311f44396381446`로 임시 checkout에 추출했다. 신규 fixture의 원본에서도 import 가능한 6개 테스트를 복사하여 그 checkout의 `ptm_shared`, `workers`, `workers/tests`만 PYTHONPATH에 넣고 실행했다. 함수의 AST를 떼어낸 고립 실행이 아니다. 최신 commit은 이 여섯 producer를 변경하지 않는다.

| 경계 | 의도한 변화 / 보호 |
|---|---|
| loss | 과거 누락 행을 informative row로 유지. conventional FC/p/q는 NA이며 valid BH family만 사용 |
| form/charge | charge 2/3은 별도 feature, 같은 modified form의 multisite는 n을 복제하지 않음 |
| mapping | 반복 peptide occurrence와 accession/FASTA variant를 보존. 충돌·모호성을 첫 match로 확정하지 않음 |
| biological units | 3 biological units × 2 technical repeats에서 n=3; secondary crosswalk는 명시된 설계만 사용 |
| normalization | global 2배 fixture에서 legacy median은 log2FC 0, 명시적 already-normalized 정책은 log2FC 1. 서로 다른 정책이며 golden 변경 없음 |
| motif | 실제 PTM anchor 밖의 일치 거부. legacy unified 소비자와 reference-sensitive cache까지 검사 |
| source | KEA3 실제 response keys, 전체 gene/context/budget cache 구분, no-hit/error 분리 |
| InterPro | 7개 domain/2페이지 fixture에서 표시 5개, full source 7개. 같은 이름 다른 accession 유지 |
| finding | 독립 feature 12개 fixture는 12개 선택 가능; 24개 vector 행 모두 accounting. 동일 input 복제는 finding 수를 부풀리지 않음 |
| cross-talk | 반대 site/form·missing·NA sentinel을 단일 gene 값/기전으로 합치지 않음. 전체 vector → typed count/value card → section packet |
| citations | collection 순서 11111,22222와 첫 인용 22222가 달라도 graph/HTML modal/DOCX의 실제 identity 일치 |
| revision | source 변경/hash 변조 거부, immutable draft bytes와 source pin 유지, stale/mtime fallback 제거 |
| comparison | frozen source species/estimator/design 사용; negative FC 보존, 비교 불가 값은 차이를 만들지 않음 |
| review | 긴 본문의 마지막 한계까지 검토 입력에 포함. 예산 소진은 unresolved; 실행되지 않은 verification은 해결로 승격하지 않음 |

최신 TMM commit의 child-process 격리는 계산 의미 변경이 아니다. API fixture는 프로세스 timeout/중복 실행을 확인하고, T4는 scientific scoring/truth 경계를 별도로 확인했다.

## 중간 실패와 수리

- 초기 환경에서 누락 dependency와 API/MCP namespace 혼합에 따른 collection 오류가 있었다. offline venv 보완 후 suite를 분리했다.
- 기존 동일 점수 kinase의 family 병합 기대, 고정 finding 개수 기대, quote substring과 paraphrase 동일시 기대를 새 계약에 맞게 수정했다. frozen scientific truth/baseline/preregistration을 수정한 것은 아니다.
- 실제 crosstalk import를 복구하면서 과거 테스트가 import 실패를 정상 반환으로 숨기던 문제, 실제 worker TSV/network schema와 fixture의 차이, time-lag helper 인자 오류가 드러났다. 실제 producer 형태의 TSV를 사용하도록 고쳤고 임의 기전과 상충 site overwrite를 제거했다.
- required-module 연결 중 문법 오류와 legacy citation 경로의 미초기화 변수, synthetic analyzer fixture의 누락 초기화가 발생했다. 수정 후 관련 검사와 T2/T3를 재실행했다.
- model projection에서 raw module payload를 제거하면서 DAG fixture가 예전 nested 필드에 접근하던 오류가 발생했다. 분석 status는 유지하고 값은 typed reader card로 전달하도록 맞췄다.
- 최종 static 검사에서 legacy companion의 존재하지 않는 time-lag 호출을 추가로 제거했다. 이를 성공한 causal 분석으로 대체하지 않고 명시적 not_evaluable 문맥을 전달한다.

## 운영 검증 전 남은 경계

코드 구현 전체 완료를 선언하지 않는다. fulltext 우선순위/독립 source-faithfulness, module별 계층적 LLM synthesis, 추가 검색으로 evidence snapshot이 바뀌는 자동 재저술 loop, 모든 companion/figure 경로의 동일 claim 검사, 모든 intermediate artifact의 attempt 격리와 live source snapshot/capability는 후속 구현·검증 대상이다.

compiled LangGraph fixture는 실제 TypedDict와 node 순서·packet 전달을 실행하되 외부 LLM/DB transport를 stub한다. API helper와 converter fixture도 실제 staging의 대체가 아니다. 최종 renderer·사용자 UI·인증된 직접 다운로드·동시 Celery 재시도·부분 export를 운영 환경에서 연결하고, domain expert가 자동 검증기의 false-pass를 표본 검토해야 한다. 현재 변경을 운영 배포하거나 current pointer를 전환하지 않았다.
