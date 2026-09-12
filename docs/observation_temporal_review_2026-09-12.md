# TASK-01·02: 관측·분모와 시간 입력 계약 수정

검토 기준 및 작업 시작 HEAD: `e48ffe98ef61bdac5ca2c4e54f5f99b0b7539bd3`.
브랜치: `main`. 시작 시 로컬 변경 없음. 이 문서는 커밋 전 작업 트리의 검증 기록이며,
최종 커밋은 이 문서의 Git 이력에서 확인할 수 있다.

사용자의 2026-09-12 r2 검토 중 A1–A3의 전처리 및 API/TMM 입력 경로를 다룬다.
TASK-03–09 전체 구현이나 경쟁 성능의 실험적 검증으로 해석하지 않는다.
Cursor에서 수정한 DOCX 생성 문제를 재수정하거나 실제 생성으로 검증하지 않았다.

## 재현과 변경

| 반례 | 수정 전 재현 | 수정 후 계약 |
| --- | --- | --- |
| PR control=100, PG 결측; 다른 control PR 결측/PG=1000; treatment PR=200/PG=1000 | PG가 없는 PR 관측을 버림. 해당 feature만 있는 작은 입력에서는 비교/vector까지 사라짐 | PR detection `1/2`, 독립 U=1, U control n=1 유지. A만 NA 및 `protein_denominator_unavailable` |
| PR는 있지만 PG가 모두 결측이거나 protein group 자체가 없음 | 빈 paired table 또는 protein contrast 때문에 중단/feature 삭제 | PR 관측과 U vector 보존. A/G/reconstructed는 계산할 수 없으면 NA |
| 두 control PR 관측 중 한 sample만 PG 가용 | PR detection이 `1/2`로 줄어듦 | PR `2/2`, A control n=1, U control n=2. A는 실제 paired ratio의 평균으로 계산 |
| 같은 G_S1, 5min의 서로 다른 precursor 값 1/3 | 실제 orders.py 루프를 AST 실행: 입력 순서에 따라 최종 값 3/1 | precursor·sequence·charge·protein group을 포함한 안정적 key. 별도 trajectory와 원본 통계 유지 |
| 동일 feature/condition에 서로 다른 값 중복 | 마지막 행 선택 | 해당 condition을 conflicting duplicate로 보류하고 모든 source row 보존 |
| exclusive feature 3개가 1min=1, 15min=1이고 5min 미관측 | profile `[1, 0, 1]`, `data_driven` | 내부 `[1, NaN, 1]`, export null, `partial_data_driven`, support 3/0/3, 전체 grid peak 보류 |
| K1=[1,0,1], K2=[1,1,1]; target의 5min 결측 | 결측을 0으로 넣어 K1을 구분 | 관측된 두 행에서는 후보가 모호한 그룹. 실제 관측 5min=0인 경우와 구분 |
| target=[0.2, missing, 1], K1=[1,0,0.2], K2=[0.2,1,1] | K2 ratio=0.6973 | deconvolution과 attribution이 같은 유효 행으로 fitting: K2=1. 이 synthetic fit은 생물학적 귀속 입증이 아님 |

PR/PG/paired mask는 sample grid에 각각 `PR_Observed`, `PG_Observed`,
`Paired_Ratio_Observed`로 저장된다. 양의 finite intensity만 관측으로 센다.
독립 U estimator와 sample ratio → condition arithmetic mean → log2 contrast인 A estimator는 유지했다.

`PTM_ProteinAdjusted_Control_N`/`Treatment_N`은 실제 유효 paired 수다.
PR/PG 조건별 n과 A missing reason도 vector에 전달한다. 통계 검정은 유효 paired 반복만 사용한다.
기존 `Conventional_Log2FC_NA`는 PR control nondetection/de novo 의미를 유지한다.
A 자체의 conventional 가용성은 별도 `PTM_ProteinAdjusted_Conventional_Log2FC_NA`로 기록한다.
실제 control PR 미검출의 기존 pseudocount 값은 감사용 표현 및 de novo 표시 제한을 유지한다.
PG 누락을 de novo로 바꾸거나 다른 축의 n/p/q로 채우지 않는다.

## 검토 가능한 변경 묶음

1. **관측/분모:** `workers/preprocessing/core/ptm_quantification.py`,
   `ptm_shared/de_novo_representation.py`, report `vector_projection.py`,
   `workers/tests/test_observation_denominator_contract.py`.
2. **feature 입력/연결:** `ptm_shared/temporal_feature_input.py`, API `orders.py`,
   `enrichment_free_temporal_sidecar.py`, `kinase_evidence_ledger.py`,
   `ptm_shared/tests/test_temporal_feature_input.py`, API `test_temporal_feature_input_route.py`.
3. **관측된 시간의 fitting:** API `temporal_kinase_scoring.py`,
   `ptm_shared/tmm_multikinase_integration.py`, API `test_tmm_observation_mask.py`.
4. **재실행/검토 자료:** `scripts/validate_observation_temporal_contract.py`, 이 문서 및
   `docs/validation/task01-02/`의 JUnit/validation JSON.

gene/site의 수치 aggregate를 새로 만들지 않았다. `sites`에 constituent feature 목록,
`aggregation_rule=none_feature_level_only`, opposite-form condition을 남긴다.
같은 feature의 여러 시점은 같은 key를 쓰며, 동일 sample/feature의 통계적 독립성을 새로 주장하지 않는다.
여러 form의 상관과 오차 전파를 추정하는 새 모델은 이번 범위에 없다.

occupancy는 기존 **logit delta** 축과 O1/O2 eligibility를 유지하며, A 결측만으로 버리지 않는다.
precursor ID도 sequence+charge도 없는 legacy 입력은 identity unavailable로 보류한다.
API의 `ptm_key`가 gene_site만인 계약에 의존하는 외부 소비자는 `gene`/`site` 표시 필드와
`feature_id`/원본 `precursor_id`를 구분해야 한다.

partial feature는 입력/측정 기록과 TMM에 남긴다. 기존 Wave complete-grid clustering은 그대로다.
legacy cluster 경로에서 모두 partial인 경우 관측 목록을 반환하되 clustering eligible=false로 표시한다.
TMM은 target과 모든 후보 profile이 finite인 행에서 fitting하며, 2개 미만이면 attribution을 보류한다.
후보 profile의 공통 관측 구간이 적으면 해상도를 얻을 수 없다는 보수적 제한이 있다.
Gaussian prior와 iterative data-assisted profile은 실측으로 승격하지 않는다.

feature-level 입력 해시는 행 순서에 불변이다. 이전 sidecar의 입력 해시가 다르면
기존 파일을 내용 해시가 붙은 previous artifact로 보존하고 다시 계산한다.
현재 실행에서 reference bundle에 접근할 수 없다면 새 mapping/reference 결과가 unavailable일 수 있다.
이를 오래된 aggregate 결과로 대신하지 않는다. 전체 run/export manifest 완성은 TASK-06 범위다.

## 검증 기록

최종 회귀 실행: **378 passed** (`worker-shared` 342, `api` 36).
기존 P1의 157개 검증을 포함하며 동일 테스트 파일을 중복 실행 집계하지 않았다.
실행 환경은 Python 3.14.6이며 Python 3.11 문법도 별도로 확인했다.
실제 배포 이미지와 동일한 dependency/runtime 검증은 아니다.

```sh
PYTHONPATH=api-server:workers:. /tmp/ptm-report-review-venv/bin/python \
  scripts/validate_observation_temporal_contract.py
```

임시 venv 경로는 교체할 수 있다. 실제 실행 인자·기준 commit·Python/platform·source SHA256·
JUnit SHA256은 [validation.json](validation/task01-02/validation.json)에 보존한다.
JUnit은 [worker-shared.xml](validation/task01-02/worker-shared.xml), [api.xml](validation/task01-02/api.xml).
이 산출물은 합성 회귀 시험 결과이며 원자료나 생성 과학 보고서가 아니다.

확장 검증에서 확인한 기존 실패는 숨기거나 테스트를 느슨하게 하지 않았다.

- `workers/tests/test_tmm_audit_protocol.py::test_replay_needs_no_database_or_production_module`은
  API 모듈이 이미 import된 같은 pytest 프로세스에서는 실패한다. 원래 독립성 assertion을 유지하고
  worker와 API를 별도 프로세스로 실행하면 통과한다.
- `api-server/tests/test_unified_temporal_ptm_protein_context.py::test_shared_summary_reaches_question_context_without_causal_claim`은
  `local co-wave membership transitions` 문구 assertion에서 실패한다. **수정 전 HEAD를 별도 디렉터리에
  git archive하여 동일 Python으로 실행해도 같은 assertion으로 실패**했다. 이 테스트는 최종 범위 suite에
  포함하지 않았으며 해당 질문 생성 코드/테스트는 수정하지 않았다.
- synthetic 동일 반복의 scipy precision-loss 경고와 기존 정규식 capture-group 경고는 남는다.

## 미실행 범위와 후속 작업

실제 주문·원자료로 전처리/정량 전체를 재실행하지 않았다. 실제 HTTP/DB/Celery,
동시 worker, Gemini, Cytoscape Desktop, DOCX/HTML 렌더링도 실행하지 않았다.
API 경로 시험은 실제 소스의 입력/cluster/cache 연결 부분을 AST로 실행한 것이며
HTTP 통합 시험을 대신하지 않는다. 현재 생성 중인 보고서에 대한 영향도는 판정하지 않았다.

기존 heatmap UI와 일부 legacy 요약 소비자는 empty sum을 0으로 표시할 수 있다.
이번에는 API의 observation counts/missing conditions와 TMM profile null을 제공했으며,
모든 UI/다운스트림 소비자의 NA 표시 전환까지 완료했다고 주장하지 않는다.
최종 DOCX/화면과 수치 연결은 TASK-07·08에서 같은 실행의 artifact로 확인해야 한다.

다음에는 TASK-03 benchmark 적격성과 biological sample manifest, TASK-04·05 복구/권한,
TASK-06 실행 추적, TASK-07 통합 검증을 분리해 진행한다.
Cytoscape의 기존 dense_network technical_audit 정책은 그대로이며 TASK-09 본문 삽입을 켜지 않았다.
이번 입력 계약을 재사용해 네트워크 identity/provenance와 렌더 검증부터 보완해야 한다.
