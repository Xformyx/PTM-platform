# 전체 흐름 검토 후속 구현: PR-A~E

작성일: 2026-09-13. 작업 시작 브랜치 `main`, HEAD `7d32e89e2b19472fa5c88ef05e940cd1132833d3`, 원격 `Xformyx/PTM-platform`. 시작 시 미커밋 변경은 없었다. 아래는 이 HEAD 위의 로컬 변경 기록이며 새 커밋·배포·실제 주문 실행의 완료 기록이 아니다.

## 범위와 유지한 계약

R-01~06을 API/UI, export/release, 공통 identity/grid, biological unit, finding별 문헌 검색의 다섯 변경 단위로 수정했다. 기존 P1 및 TASK-01·02·10을 재구현하지 않았다. sample-wise PR/PG ratio의 조건별 산술평균을 비교하는 A estimator, 독립 U, 별도 reconstructed 축, conventional/de novo 구분, partial-grid 표시, bibliography 제외 및 수치·부정문·Figure 검증을 유지했다.

R-07 benchmark, outbox/watchdog/운영 공개·배포·분산 Gemini 예산, focused Cytoscape 구현은 이번 변경 범위에 포함되지 않는다. `dense_network`는 technical audit로 유지한다. 아래 시험의 통과는 enrichment-free assay 성능이나 실제 서비스 종단 검증을 의미하지 않는다.

## 기능별 변경

| 단위 | 주요 파일 | 결과와 한계 |
|---|---|---|
| PR-A / R-01 | `ptm_shared/quantitative_fields.py`, `vector_projection.py`, `vector_plot.py`; `api-server/app/api/orders.py`; `frontend/src/lib/quantitation.ts`, `OrderDetail.tsx`, `KinaseModuleAnalysis.tsx`, `QuantitationEvidenceTable.tsx` | API와 report가 같은 축 접근자/projection을 사용한다. 명시적 canonical null은 legacy 값으로 덮어쓰지 않는다. U/P/A의 값·p/q/n·sample ID·부재 사유·통계 단위·identity를 보존하고 화면은 NA를 표시한다. 동일 feature/condition/axis의 효과와 q만 regulated 판정에 사용한다. 다른 조건의 최소 q를 최대 효과에 붙이거나 효과만으로 자동 fallback하지 않는다. |
| PR-B / R-02 | `core/report_finalization.py`, `report_release.py`, `report_artifact_manifest.py`; `workers/report_generation/tasks.py`; `ptm_shared/report_mode.py` | pre-export와 final release를 분리한다. 최종 export와 source/rendered hash 검증 뒤 DB/progress/file metadata에 마지막 판정을 사용한다. audit 부재는 final-ready가 아니다. 구조적 차단과 source 변조는 약한 review 상태로 덮어쓰지 않는다. HTML만 요청한 경우 DOCX를 요구하지 않는다. 현재 호출이 반환한 export만 수집한다. 두 reader mode가 같은 gate를 사용한다. |
| PR-C / R-03·04 | `ptm_shared/feature_identity.py`, `temporal_feature_input.py`, `enrichment_free_temporal_sidecar.py`; report projection/cards/synthesis/claims/Figure | precursor 또는 sequence+charge와 protein-group/taxon/isoform 범위를 공통 identity로 묶는다. 같은 site의 다른 charge/form은 독립 관측이다. 전체 condition grid의 행 부재도 null과 missing reason으로 보완한다. 부분 관측은 남고 clustering eligibility는 별도다. 같은 elapsed time의 서로 다른 condition은 덮어쓰지 않고 Figure에서 구분한다. |
| PR-D / R-06 | `ptm_shared/sample_manifest.py`, `quantitative_fields.py`; API 주문 설정; `workers/preprocessing/{tasks.py,core/ptm_quantification.py}`; measured cards | 명시적 manifest를 sample_config와 PR/PG 열에 대조한다. 기술 반복을 biological unit 안에서 평균한 뒤 명시적 paired/Welch 비교를 사용한다. U/A 효과 estimator는 바꾸지 않는다. biological unit이 부족하면 검정값을 만들지 않는다. 카드의 sample support, biological support, pointwise q와 검정 단위를 분리한다. |
| PR-E / R-05 | `core/finding_literature.py`, `rag_retriever.py`, `nodes/writer_node.py`, `reader_authoring.py`, `graph.py` | 기존 retriever와 LLM client를 사용해 선정 finding별 검색·비교를 생산한다. 일반 DOI reference 하나를 검색 완료로 취급하지 않는다. source quote/context/site 범위를 검증하고 packet 및 Discussion으로 연결한다. 모델의 관계 해석은 사람이 원문을 검토해야 하는 상태를 명시한다. |

### API/UI의 세부 경계

기존 report 경로의 `quantitative_fields.py`와 `vector_projection.py`는 shared 구현의 호환 import로 남겼다. 전체 이름 변경이나 별도 discovery 엔진은 추가하지 않았다. 동일 feature-condition 중복은 동일 행이면 제거하고, 값이 충돌하면 해당 조건의 정량을 withheld로 둔다. 원본 입력 객체는 바꾸지 않는다.

Top-N의 기존 site 단위 문맥 선택 뒤 표시 관측은 각 canonical feature로 확장한다. site annotation은 문맥이며 form 정량을 집계하지 않는다. 기존 site-level kinase annotation의 highlight는 해당 site에 연결된 모든 form을 선택할 수 있지만 각 선·값의 ID는 분리한다. U/P/A selector는 관측 그래프와 그 축의 판정을 바꾸며 kinase module 분석은 A를 사용한다고 화면에 명시한다. reconstructed 값은 U 토글의 입력이 아니다.

receptor annotation을 고정해도 이전 identity/값의 co-wave·divergence 정량 cache는 새 결과로 반환하지 않는다. 정렬에 불변인 quantitative input hash가 같을 때만 재사용한다. 구 cache의 정량 결과를 다시 얻으려면 refresh/reanalysis가 필요하다. TMM cache에도 현재 temporal input version gate를 적용했다.

legacy browser divergence는 complete observed grid의 유일한 sampled extremum만 요약한다. flat/tie/NA로 임의 peak를 만들지 않는다. form ID가 서로 같은 site label에 덮어써지던 connector도 수정했다. biological unit을 무시하고 시간점들을 섞던 browser permutation p-value는 제공하지 않는다. descriptive 크기·순서 요약을 biological pattern 검정으로 해석해서는 안 된다. 전체 legacy Wave/atlas 분석의 통계 모델을 재설계한 것은 아니다.

### Identity와 grid 이행

`precursor_identity.v2`의 입력은 gene, 후보 position, raw precursor ID, modified sequence, charge, protein group, taxonomy ID, isoform이다. canonical `FEATURE-…`와 reader용 `PF-…`는 구분한다. identity를 만들 수 없는 행은 site로 임의 결합하지 않고 진단 기록으로 남긴다. 동일 precursor 문자열이라도 mapping group이 다르면 별개다.

구 PF ID와 새 canonical ID의 crosswalk 및 ambiguous legacy ID를 packet audit에 남긴다. **구 PF 링크의 자동 재결합은 하지 않는다.** 기존 cached sidecar/Figure/문헌 비교는 현재 identity와 입력으로 재생성해야 한다. 이 정책은 `identity_migration_policy`에 기록한다. 기존 sidecar의 input hash가 다르면 이전 파일을 보존한 뒤 재구성한다.

검증된 study condition grid가 있으면 사용하고, 없으면 실행 입력의 condition 집합이라는 출처를 남긴다. feature 행이 빠진 조건은 `feature_condition_unavailable`이며 0이 아니다. 명시적 null과 행 부재 모두 pattern의 missing list와 Figure gap에 반영한다. 관측한 두 점의 같은 수준은 전체 시간 구간의 지속을 입증하지 않는다. Control의 시간은 설계 근거 없이 0으로 생성하지 않는다.

### Sample manifest 및 통계 단위

입력은 `analysis_context.sample_manifest`이며 task config로 전달된다. `samples`의 각 항목에는 `sample_id`, `condition`, `biological_unit`이 필요하다. `technical_injection`, `batch`, reference와 actual-time metadata를 유지하며 pairing은 `paired` 또는 `unpaired`로 명시한다. paired 비교는 양 조건에 존재하는 같은 biological unit을 사용한다. 파일명 정렬로 대응을 만들지 않는다. 명시적 manifest가 없으면 `sample_observation_biological_design_unavailable`로 기존 비교의 단위를 드러낸다.

기술 관측의 평균은 **검정 입력을 만드는 단계**에 적용된다. A의 sample ratio estimator를 biological 평균 estimator로 조용히 바꾸지 않는다. p/q, 계산 방법, 통계 단위, 검정 불가 이유를 축별로 기록한다. 새 population CI는 생성하지 않는다. 이미 존재하는 P 축의 검정 부재도 유지한다.

manifest로 biological n=1이 확인되면 injection 수와 작은 point q만으로 high narrative quality를 주지 않는다. manifest가 있는 경우 biological support와 q의 검정 단위도 일치해야 한다. 기술적 관측 지원은 남는다. 이는 기술적 precision 자체를 측정·인증했다는 뜻이 아니다. secondary PTM track에 대한 별도 manifest UI/설계는 이번 시험 범위 밖이다.

### 문헌 비교의 생산·검증 경계

writer가 선정한 finding마다 query, collection/version, 검색 UTC 시각, source ID/hash, coverage와 성공/실패를 기록한다. 현재 study의 treatment/cell/species 문맥을 사용하며 insulin을 모든 query에 강제하지 않는다. 기존 client의 JSON Schema 출력을 사용한다. 외부 finding/context는 실제 source quote 안의 문자열이어야 하고, site 범위는 해당 site와 gene이 source에 있을 때만 허용한다. DOI/PMID와 source offset/hash를 남긴다. 인용 ID의 존재만으로 현재 실험에서 측정한 edge를 만들지 않는다.

미검색, 검색 실패, 검색 완료·비교 미완료, 일치, 불일치, 양쪽 근거, 검색 범위에서 미설명을 구분한다. 잘못된 quote/schema는 제외 사유와 함께 pending으로 남긴다. source anchor 검사는 모델의 agreement/disagreement 해석이 옳다는 보증이 아니다. `source_anchored_semantic_review_required`를 보존한다. 실제 주요 insulin finding의 인용·조건·방향은 사람이 별도로 점검해야 한다. 일반 Introduction 문헌 설명과 기존 부정문 보존 규칙은 유지한다.

## 반례와 회귀

수정 전에 R01 CSV 경계 fixture 1개와 R02~06의 worker fixture 8개가 실패하는 것을 확인했다. 이후 필요한 연결 시험을 추가했다.

| 반례 | 검증 경로 | 결과 |
|---|---|---|
| U=1, A/P unavailable, legacy A=7, P=Inf | 원 CSV loop 및 실제 FastAPI route → JSON → 실제 React evidence table SSR | canonical null, 축별 q/sample ID와 reason 유지; NA 표시 |
| 5분 큰 효과·큰 q / 40분 작은 효과·작은 q | 실제 UI helper | regulated로 승격하지 않음 |
| audit 없음, export 없음/일부 실패, source/HTML 변조, 구조적 차단+manifest incompatible | 실제 finalization/seal/resolver | final-ready 차단, 강한 사유 유지, stale DOCX 미반환; HTML-only 성공 허용 |
| shadow/opt_in_shadow | 공통 mode 및 finalization | 동일 판정 |
| charge fallback·protein group·taxon/isoform·행 순서·같은 조건 충돌 | 실제 시간 입력/CSV loop/report card | canonical ID 일치, form 분리, 충돌은 해당 조건만 withheld |
| target에 1/15분만 있고 다른 feature에 5분 | 실제 card/pattern | missing 5분, clustering 제외, partial observation 유지 |
| technical 3회, biological 1개 | 실제 전처리 U/A 및 카드 | 기존 효과 유지, biological 검정 불가, high 생물학적 support 방지 |
| rename 및 explicit paired unit | 실제 unit builder | 동일 unit 입력·대응, 기술 평균 후 비교 |
| 일반 reference만 있음, mock 검색 일치/조건 다른 불일치/미검색/실패/pending/위조 quote | 기존 retrieval adapter → packet → fallback Discussion | 상태와 조건 차이 전달, 위조 비교 제외 |

기존 테스트는 완화하지 않았다. clean final-ready 시험에는 실제 source와 sealed HTML을 추가해 더 강한 gate를 충족시켰다. 구 TASK-10의 global `retrieval_status=completed`만으로 feature 검색을 완료로 보던 기대는 미검색 상태로 강화했다. 기존 comparison 충돌 제외 시험, de novo 분리와 bibliography/P1 시험을 유지했다.

## 실행 기록

실행 환경은 macOS 15.6.1 arm64, 임시 Python 3.14.6 venv와 Node 24.8.0이다. production Python/container 의존성을 재현한 시험이 아니다. API/worker 시험은 별도 프로세스로 실행한다. worker audit의 API import 금지 조건을 유지한다.

```sh
PYTHONPATH=api-server:workers:workers/tests:. MPLCONFIGDIR=/tmp/ptm-review-mpl \
  /tmp/ptm-report-review-venv/bin/python scripts/validate_observation_temporal_contract.py \
  --include-flow-review --output-dir docs/validation/flow-review-20260913

# frontend 디렉터리
node --test tests/quantitation.test.ts
npm run build

# 저장소 root
PYTHONPATH=workers:workers/tests:. MPLCONFIGDIR=/tmp/ptm-review-mpl \
  /tmp/ptm-report-review-venv/bin/python scripts/render_task10_fixture.py \
  --output-dir /tmp/ptm-flow-render
```

선택 Python suite: **468 passed (worker/shared 428 + API 40), 실패·오류·skip 0**. UI helper: **4 passed**. TypeScript/Vite build 성공. 기존 SciPy 상수 데이터 경고, regex 그룹 경고 및 Starlette deprecation은 남아 있다. Vite bundle 크기와 browserslist 경고는 별도 최적화 대상이다. JUnit·명령·환경·소스 hash는 [validation 기록](validation/flow-review-20260913/validation.json)에 보존한다. 이 숫자는 이전 442개 또는 독립 검토 92개와 합산하지 않는다.

합성 fixture의 MD/DOCX/HTML export, finding coverage `covered`, correctness `draft_review_required`, structural issues 없음까지 확인했다. production exporter로 만든 DOCX를 LibreOffice로 렌더링하고 6쪽 전체를 육안 확인했다. U/P/A Figure, PF 라벨, 불규칙 시간 간격 및 표의 페이지 분할을 확인했다. 실제 인용·실험 설계가 없는 fixture의 review 상태는 유지한다. [렌더 검증 기록](validation/flow-review-20260913/render_validation.json)에 해시·검수 범위를 남긴다. 생성 보고서/PNG/PDF와 원자료는 저장소 변경에 포함하지 않는다.

실제 Gemini/문헌 서비스, 전체 PR/PG 사용자 데이터 재분석, Celery task→실제 DB/broker, 동시 worker·장애 주입, 배포, Cytoscape Desktop은 실행하지 않았다. HTTP→React 시험의 DB/storage는 합성이며 SSR은 브라우저 상호작용·화면 크기별 레이아웃 시험을 대체하지 않는다. DOCX 검수도 실제 사용자 보고서의 과학적 내용 검토를 대체하지 않는다.

## 다음 실제 run에 필요한 자료

현재 code SHA/container digest와 resolved 설정, 실제 PR/PG/FASTA 및 sample manifest, 같은 run의 normalized vector와 축별 support/QC, identity crosswalk 및 temporal sidecar가 필요하다. biological synthesis/authoring packet·plan, finding별 retrieval/comparison 기록, FigureManifest/실제 Figure, prose trace/correctness audit, pre-export/final release, 최종 MD/DOCX/HTML hash와 현재 revision 파일 목록을 함께 보존해야 한다. 실제 provider/model·usage/latency/finish/retry도 제공되는 범위에서 기록한다.

이 자료로 API/UI/report/Figure의 feature·condition·axis·value·NA 일치와 실제 인용의 적절성을 점검한 뒤 해당 revision을 수용할 수 있다. benchmark 적격성, 운영 복구·권한·예산, focused network는 각각 PR-F/G/H의 별도 완료 조건으로 남는다.
