# TASK-10 구현·검증 기록

작업일: 2026-09-12–13, Asia/Seoul. 저장소 `Xformyx/PTM-platform`, 브랜치 `main`.
시작 HEAD는 `29563def4bfbeddae82c62459800bcdba3795185`였다. 검토 기준 `e48ffe98ef61bdac5ca2c4e54f5f99b0b7539bd3`의 P1 수정과 그 이후 TASK-01·02의 관측/분모 분리·temporal feature identity 수정이 이미 포함돼 있었다. 시작 작업 트리는 깨끗했으며 기존 변경을 되돌리지 않았다. 이 문서는 커밋 전 TASK-10 작업 트리의 구현·검증 결과를 기록한다.

기존 정량, 후보 packet, reader authoring, FigureManifest, exporter를 확장했다. 새 discovery 엔진이나 LLM 파이프라인을 만들지 않았다. 기존 sample-wise ratio estimator를 유지하며, 새 패턴은 **관측을 설명하는 규칙**이다. 패턴 전체의 통계 검정이나 생물학적 재현성을 새로 계산한 것은 아니다.

## 기능별 검토 단위

아래 네 단위는 공통 카드와 packet을 공유하므로 순서대로 검토한다. 서로 독립적으로 배포할 수 있는 네 커밋을 만들었다는 뜻은 아니다. 경로의 `core/`는 `workers/report_generation/core/`다.

| 단위 | 변경 파일 | 결과와 계약 |
|---|---|---|
| 10A: 관측·후보 전달 | `workers/preprocessing/core/ptm_quantification.py`, `core/quantitative_fields.py`, `core/vector_projection.py`, `core/measured_feature_cards.py`, `core/biological_synthesis.py`, `core/reader_authoring.py` | U/P/A 각각의 실제 sample ID·n·p/q·method·estimator·CI/부재 사유를 보존한다. `selected_cards` 생산 형식과 legacy 형식을 trajectory로부터 reader card로 변환한다. 입력·적격·reader·본문 선택 수와 제외 이유를 기록한다. |
| 10B: 시간·공동 패턴 | `core/temporal_analysis.py`, `core/measured_feature_cards.py`, `core/biological_synthesis.py` | 영 변화, 일정한 비영 변화, 동률, 결측, 시간 미상을 구분한다. 실제 분 단위 시간과 관측 extrema의 부호·범위를 기록한다. 세 축의 동행·분모 기여·PTM 증가를 이미 계산된 값으로 설명한다. |
| 10C: finding·문헌 범위 | `core/reader_authoring.py`, `core/quantitative_claims.py`, `core/biological_synthesis.py` | precursor identity를 유지한 채 품질을 먼저 고려하고 parent/패턴 다양성으로 최대 네 finding을 선택한다. kinase 귀속 가능성과 데이터 적격성을 분리한다. 문헌 비교의 출처·조건 차이·반대 결과와 가설의 관측/인용/검증 예측 연결을 보존한다. |
| 10D: 문장·그림·export | `core/figure_manifest.py`, `core/reader_authoring.py`, `core/quantitative_claims.py`, `core/nodes/writer_node.py`, `core/graph.py`, `core/citation_formatter.py`, `core/report_artifact_manifest.py`, `workers/report_generation/tasks.py`, `workers/common/{llm_client,markdown_to_docx,markdown_to_html}.py` | writer 전에 같은 finding의 세 축 Figure를 고정한다. 숫자·Figure의 feature/condition/axis와 핵심 finding 누락을 검사한다. 잘린/실패한 응답은 완료된 해석으로 표시하지 않는다. 최종 export 파일과 실제 Figure의 hash를 기존 manifest에 추가한다. |

검토용 고정 입력과 재실행 경로는 [fixture exporter](../scripts/render_task10_fixture.py), [검증 runner](../scripts/validate_observation_temporal_contract.py), 아래 네 테스트 파일에 있다. 원본 데이터나 생성 보고서는 저장소에 추가하지 않았다.

- [후보 전달·평평한 궤적](../workers/tests/test_task10_discovery_contract.py)
- [세 축·시간·반복 단위](../workers/tests/test_task10_joint_patterns.py)
- [발견·문헌·상반된 form](../workers/tests/test_task10_findings.py)
- [문장·Figure·LLM 실패·export](../workers/tests/test_task10_render_contract.py)

## 재현과 수용 fixture

| Fixture | 확인한 동작 | 범위/주의점 |
|---|---|---|
| T10-01 / G1 | production `selected_cards`, legacy `candidate_cards`/`cards` 모두 요약 문자열 없이 정량 trajectory에서 reader card를 만든다. 적격 후보를 “not generated”로 바꾸지 않는다. | identity/숫자 근거가 없는 후보는 제외 사유를 남긴다. 모든 후보의 본문 사용을 강제하지 않는다. |
| T10-02 / G2 | `[0,0,0]`, 일정한 양/음 값, 동률, 중간 NA를 early peak로 만들지 않는다. | 최종 점검에서 옛 `peak_condition`의 첫 시점 누출도 실패 재현 후 수정했다. 일반 후보의 이 필드는 유일한 관측 extrema에만 남고 생물학적 peak를 뜻하지 않는다. |
| T10-03 | 실제 전처리 함수로 PR/PG 모두 두 배, PR 유지/PG 절반, PR 두 배/PG 유지를 계산하고 서로 다른 공동 패턴으로 전달한다. | 새 패턴 규칙이 estimator를 다시 계산하지 않는다. |
| T10-04 | 서로 다른 sample 지원 집합에서 A≠U−P와 실제 축별 sample ID를 확인한다. PG 전부 결측이어도 U=1 및 control sample `c1`을 유지하고 A만 분모 부재로 남긴다. | 공통 sample sensitivity는 `not_computed`; 주 estimator를 교체하지 않는다. |
| T10-05·06 | 같은 parent의 세 form과 기술 반복을 추가해도 명시된 biological unit은 하나다. 공유 분모의 조정값 동조는 남는다. | feature 수를 독립 n으로 사용하지 않고 없는 CI를 만들지 않는다. manifest가 없거나 모순되면 biological n은 unavailable이다. |
| T10-07 | `[0,5,40,180]`의 실제 시간과 마지막 관측 최대를 기록한다. 시간 미상 record는 남기고 시간 모델/패널에서는 제외한다. | onset/lag 추정 모델이나 구간 사이 peak 보간을 추가하지 않았다. |
| T10-08 | 평균이 같아도 반복·q 지원이 다른 관측을 구분하고 더 나은 관측 지원을 먼저 선택한다. | 입력의 분모 QC/CI는 보존하지만 새로운 noise 모델·CI를 추정하지 않는다. |
| T10-09 | localization·kinase annotation이 없어도 precursor/form 관측과 descriptive finding을 보존한다. | no-call을 kinase 비활성이나 exact-site 기전으로 승격하지 않는다. |
| T10-10 | 같은 parent의 상반된 form을 각각 유지하고 행 순서를 뒤집어도 같은 finding을 만든다. | Figure에서도 각 PF ID와 세 축을 별도 행으로 표시한다. |
| T10-11 | 합성 문헌의 일치/불일치·cell model/시간 차이·citation ID를 보존한다. 검색 미실행과 검색했지만 설명 못함을 구분한다. | 비교 문장마다 인용을 붙여 validator 이후에도 일치와 불일치가 모두 남음을 확인했다. 실제 문헌 검색/원문 검증 시험이 아니다. |
| T10-12 | 적격 finding 1개/3개에서 같은 수를 유지한다. 잘못된 수치 제거로 주요 결과가 사라지면 review가 필요하다. 잘못된 Figure condition/axis, Gemini timeout·잘림·filter를 검사한다. | 정상 응답의 기존 P1 mock 시험도 함께 실행했다. 실제 Gemini 호출은 없다. |

추가 회귀는 새 axis pattern에서 de novo의 표시용 큰 수치를 제외하는 경우, final postprocessor가 negated occupancy/activity 제한 문장을 훼손하는 경우, DOCX 변경으로 hash 검증이 실패하는 경우, Figure만 있고 문서 export가 없는 경우를 포함한다. 새 결함은 실패하는 작은 시험을 먼저 확인한 뒤 수정했다.

기존 테스트 변경은 packet/manifest 버전, 같은 PF를 observation과 comparison 두 finding으로 중복 선정하던 기대, 새 Figure의 동적 번호/삽입 수에 한정했다. 무근거 기전·숫자 변조·de novo·partial grid·bibliography 제목 제외의 기존 assertion을 삭제하거나 느슨하게 만들지 않았다.

## 주요 schema와 해석 경계

| 계약 | 버전/규칙 |
|---|---|
| 정량 필드 | `report_quantitative_fields.v2`: 축별 sample·method·CI/부재 사유 추가 |
| 생산 후보 / synthesis | `candidate_discovery_packet.v2`, `biological_synthesis_packet.v2` |
| reader adapter | `candidate_reader_adapter.v1`: source schema/field와 count·exclusion audit |
| 관측 패턴 | `observed_joint_pattern.v1`: descriptive; point q는 pattern q가 아님 |
| 발견 선택 / finding | `report_finding_selection.v1`, `report_finding.v1` |
| 문헌 비교 | `finding_literature_comparison.v1`: supplied records 범위, novelty 불허 |
| reader / Figure manifest | `reader_authoring_packet.v5`, `report_figure_manifest.v5` |
| Figure 수치 연결 / 누락 검사 | `joint_trajectory_binding.v1`, `finding_coverage_audit.v1` |
| 최종 파일 기록 | `report_rendered_artifacts.v1` |

기존 `abs(A−P)` 점수는 **좌표 차이**로 유지하고 `absolute_adjusted_minus_protein_coordinate_distance.v1`과 해석 경계를 붙였다. 독립 U/P 불일치나 새 보정값으로 이름만 바꾸지 않았다. ±0.15는 기존 비교의 설정 가능한 descriptive tolerance이며 통계적 유의성이 아니다.

sample manifest는 `samples`의 `sample_id`, `biological_unit`, `technical_injection`, `batch`, pairing metadata와 `conditions`의 condition, `time_minutes` 또는 `elapsed_time`/`time_unit`, `reference_id`를 보존한다. 파일명 정렬로 pairing이나 biological n을 추측하지 않는다. 기존 vector에 sample 목록이 없으면 복구한 것처럼 채우지 않는다.

finding의 O1은 관측/descriptive 범위다. O2·개입 근거·population 재현성은 별도의 주장별 분석이 있어야 하며 이번 구현은 이를 생성하지 않는다. 부정문·문헌 배경·근거가 연결된 가설의 기존 P1 보호를 유지했다. 상반된 form은 Discussion에서 함께 설명할 수 있지만 Results와 Figure에서는 identity가 유지된다.

## 실행한 검증

최종 선택 suite는 **442 passed**: worker/shared 406, API 36. 실패·오류·skip은 0이다. Python 3.14.6, macOS 15.6.1 arm64의 임시 가상환경에서 실행했다. Python 3.11 문법 검사 26개 Python 파일과 `git diff --check`도 통과했다. 이는 저장소 전체 suite나 운영 컨테이너 검증이 아니다.

[명령·runtime·source SHA256](validation/task10/validation.json), [worker/shared JUnit](validation/task10/worker-shared.xml), [API JUnit](validation/task10/api.xml).

```sh
/tmp/ptm-report-review-venv/bin/python scripts/validate_observation_temporal_contract.py \
  --include-task10 --output-dir docs/validation/task10

PYTHONPATH=workers:workers/tests:. MPLCONFIGDIR=/tmp/ptm-review-mpl \
/tmp/ptm-report-review-venv/bin/python scripts/render_task10_fixture.py
```

동일한 값의 합성 반복에서 SciPy precision-loss 경고 5개와 기존 PTM 정규식 capture-group 경고 12개가 있었다. 이 입력의 통계값으로 성능이나 population CI를 주장하지 않는다. API suite에는 source-extracted route 연결 검증이 포함되며 실제 HTTP/DB/broker 통합 실행을 뜻하지 않는다.

합성 3-feature fixture는 실제 packet → finding → deterministic fallback → 문장 검증 → 최종 후처리 → DOCX/HTML exporter를 통과했다. PR/PG → vector 계산은 별도 수용 fixture에서 실제 계산 함수를 실행했다. 두 단계를 production 주문 전체의 종단 실행으로 합쳐 표현하지 않는다.

## DOCX·HTML 실물 검사

LibreOffice 26.8.0의 임시 read-only mount와 문서 skill의 `render_docx.py`로 DOCX를 PDF/PNG로 변환했다. HTML은 Chrome 152의 독립 임시 프로필에서 PDF로 인쇄했다. DOCX와 HTML 인쇄본 각각 6쪽 전체를 확인했다. 도구·파일 hash와 점검 결과는 [render validation](validation/task10/render_validation.json)에 보존한다. 생성 파일 자체는 `/tmp/ptm-task10-render`에 있으며 저장소 산출물로 추가하지 않았다.

수정/확인 항목: U/P/A 축과 불규칙 시간 간격, 모든 PF/후보 residue 라벨, 상반된 같은-parent form, 축별 n/q와 NA, Figure 번호/본문 연결, 캡션의 localization·occupancy·activity 제한, 결론의 한계와 다음 검증. DOCX 표 헤더를 페이지마다 반복하고 행 분할을 막았다. 비교 Figure의 범례가 관측 점을 덮지 않도록 옮겼다. HTML 확대 버튼을 이미지 아래로 옮기고 인쇄본에서는 목차·버튼을 제외해 본문 폭과 그림 라벨을 확보했다.

이 fixture에는 실제 study/sample metadata와 문헌이 없다. 따라서 bibliography는 기존 정책대로 blocked이며 output correctness는 `draft_review_required`다. structural reason은 없고 finding coverage는 covered다. 렌더링 성공을 출판 가능한 과학적 해석 완료로 간주하지 않았다.

## 남은 범위와 다음 실제 실행에 필요한 자료

실제 Gemini·문헌 검색, 기존 주문/09시23분 DOCX 재생성, 전체 PR/PG 원자료 재분석, 같은 입력의 세 차례 생성, production Celery/DB/broker, Cytoscape Desktop, 배포는 실행하지 않았다. Microsoft Word에서의 표시와 production 컨테이너 Python 환경도 별도 확인이 필요하다. Cursor의 기존 DOCX 생성 오류 수정은 보존했으며 이번에는 합성 입력에서 exporter와 LibreOffice 렌더링을 검증했다.

문헌 비교는 feature에 연결된 `feature_comparisons`가 명시적으로 제공되면 보존하고 문장에 연결한다. 일반 reference의 제목/초록만으로 exact-feature 일치나 반대 결과를 자동 판정하지 않는다. 실제 RAG가 적절한 논문과 조건 차이를 찾는지, 모델이 이 근거를 이용해 유용한 가설을 작성하는지는 실제 입력에서 확인해야 한다. 합성 `KNOWN_FIXTURE`는 canonical insulin 반응의 실험적 입증이 아니다.

새 시간 요약은 reader/candidate 경로에 적용했다. 기존 temporal 모듈의 모든 legacy 모델을 재작성하지 않았다. 공동 sample sensitivity, parent 단위 재표본추출, population CI, pattern-level 다중검정과 검증용 holdout은 계산하지 않고 부재 상태로 남긴다. 최종 export hash 확장은 TASK-06의 raw-file/run ID/container digest/budget·usage 전체 구현을 대체하지 않는다. dense Cytoscape는 계속 technical audit이며 자동 본문 승격하지 않았다.

finding audit는 명시된 PF/근거·수치 문장의 누락과 동일 문장의 중복을 검사한다. 모든 자연어 의미 중복, 기전 타당성, 문헌 내용의 사실성을 증명하는 검증기는 아니다. 안전한 문장으로 복구되지 않거나 주요 결과가 빠지면 review가 필요하다.

다음 실행에서는 같은 run의 vector TSV, sample manifest(실제 biological/technical unit·batch·pairing·시간/reference), replicate-level 입력과 PR/PG 결측/QC, FASTA·precursor/localization provenance, 실제 문헌과 조건 비교를 공급해야 한다. 그 실행의 authoring/evidence packet, Figure manifest, prose trace, output correctness audit, artifact manifest, 최종 Markdown/DOCX/HTML을 함께 보존한다. 실제 resolved provider/model·설정·finish 상태·usage/latency 및 git/container/timezone 정보를 추가 확인하되 비밀키는 기록하지 않는다.
