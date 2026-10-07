# 회차 05 — 저장 입력에서 v6 소비·export까지

2026-10-07. 기준 main `ece7c5f7e0735cb898519d74a084d79509cc862b`. 브랜치 `feature/round05-diann-input-lineage`. 시작 시 tracked 변경은 없었으며 미커밋 `codex-inputs/`, 이전 성공 ZIP/current pointer를 보존했다. 저장소/상위 경로에 적용할 AGENTS.md는 발견되지 않았다. 회차 06 이후 및 새 자원 수집은 범위 밖이다.

## 실제 입력 확인 범위

제공 g1 archive의 source Order는 **88**, 주문명은 `Insulin_Signaling_V3_261003_Codex_Astra_bundle_5`다. archive의 snapshot/replay config/입력 bytes를 확인했다. **운영 Order 88의 현재 DB·입력 mount를 직접 조회한 것은 아니다.**

별도로 기존 localhost 검증 DB의 **Order 70 / Round01_HIRcB_52030d7a**를 SELECT만으로 조회했다. 상태는 completed, PR/PG/FASTA 경로만 저장돼 있고 main/site report, crosswalk, search FASTA는 NULL이다. `analysis_context.science`에는 experimental_enabled만 있고 DIA-NN 버전은 없다. `acquisition_metadata`에도 버전은 기록되지 않았다. 해당 주문의 입력 폴더와 격리 reference root, 이미 연결된 HIRc-B 자료를 확인했다. 다른 연구의 다운로드 파일을 이 주문의 근거로 가져오지 않았다.

PR은 177,116행, PG는 9,525행이며 각각 21개 injection 열을 가진 정량 matrix다. PR metadata는 Protein.Group, Protein.Ids, Protein.Names, Genes, First.Protein.Description, Proteotypic, Stripped.Sequence, Modified.Sequence, Precursor.Charge, Precursor.Id다. 두 matrix에는 run localization/site probability/q-value 열이 없으며 main report의 Run 등 필수 schema도 없다. FASTA는 54,495개 entry다. g1과 local Order의 세 파일은 hash가 같다.

| 입력 역할 | 실제 파일 / SHA-256 | 저장 | dispatch | parser | matched / unmatched / conflict | 출력 위치 | 제한 |
|---|---|---|---|---|---|---|---|
| PR matrix | `PR.tsv` / `7160e863ddaf5236d22c5dc95fd3b066355341e8b2b130f11ef12e5a46a52ba4` | local Order 70 및 g1 확인 | config→engine bytes 일치 | 기존 prepare_forms/ContrastEstimator | main-report join 대상 아님 | `quant/runlevel.csv`, `comparisons.csv`, `summary.csv` | form 정량이며 측정 localization 없음 |
| PG matrix | `PG.tsv` / `57c874a46f57608a64a779c4ef8ddecd07273cc0603aa228b8fbd662cbfca745` | 동일 | 동일 | 기존 protein_contrasts | main-report join 대상 아님 | `quant/protein_contrasts.csv` 및 parent masks | PG를 pd나 site report로 간주하지 않음 |
| 원본 FASTA | `reference.fasta` / `61b5d367511111d46377c78cfcfc1a09bacb0c1632c9960282520de732823c83` | 동일 | 동일 | science_reference.preflight, site_identity | mapping별 ambiguity를 그대로 보존 | `science/site_identity_audit.csv` | `analysis_reference.fasta`는 파생 파일. MS localization 근거가 아님 |
| DIA-NN main report | 없음 / hash 없음 | missing_input | 경로 없음 | missing_input, 정상 파싱 미실행 | 평가 불가, report 0행 | `science/measurement_observations.csv`(빈 표), readiness | 실제 사용자 report parity 미검증 |
| DIA-NN site report | 없음 / hash 없음 | missing_input | 경로 없음 | missing_input | 평가 불가 | `science/site_report_observations.csv`(빈 표) | 확률 생성 안 함 |
| Run/channel crosswalk | 없음 / hash 없음 | missing_input | 경로 없음 | main report join 미실행 | 평가 불가 | `study/input_lineage.csv` | 파일명 추론 join 안 함 |
| DIA-NN version | 미기록 | not_recorded | 임의 값 주입 없음 | main report 미제공 | 해당 없음 | snapshot/context | 합성 fixture의 2.7.0을 실제 연구 버전으로 쓰지 않음 |
| 실제 search FASTA | 별도 자료 없음 | missing_input | 경로 없음 | 검색/분석 FASTA 동일성 미확인 | 해당 없음 | reference readiness | 분석용 FASTA만으로 동일 검색 FASTA였다고 단정하지 않음 |

실제 입력의 dispatch 검증은 저장 경로→별도 local config→engine/package의 hash 비교다. 새 운영 queue 메시지를 검사한 것으로 표시하지 않는다. HTTP upload→실제 ORM 저장/재조회→dispatch helper→실제 worker 분기는 아래 합성 검증으로 별도 확인했다.

## 발견한 문제와 최소 수정

생산 코드 변경은 **`ptm_shared/astra_evidence_v6.py::write_artifacts()` 한 곳**이다. main report 없이 crosswalk만 있으면 `observations()`는 파일 읽기 전에 반환한다. 그런데 기존 input_lineage는 crosswalk의 경로 존재만 보고 `consumed`로 표시했다. 회차 05 fixture에서 이 오표시를 재현했다.

해당 조건만 `accepted_but_unused`로 바꾸고 기존 `study/input_lineage.csv`에 reason을 기록한다:
`main_report_not_provided; observations_returns_before_reading_crosswalk`.
원 파일은 계속 inputs에 복사/보존한다. 이것은 **소비 상태 전달의 수정**이며 parser·정량·localization policy 수정이 아니다. 실제 HIRc-B에는 crosswalk도 없어 이전 과학 결과를 바꾸는 사유가 없다.

API 파일 저장, DB 필드, v6 INPUT_FIELDS, worker config 전달에서는 누락을 발견하지 않았다. 정상인 경로는 수정하지 않았다. 새 입력 관리 시스템, 수집 engine, normalization, threshold, specificity, 문헌 기능은 추가하지 않았다.

## 재사용한 실제 경로

`OrderCreate.scienceFiles` / `SampleDesignFields.science.diann_version`
→ `orders.create_order.save_upload` 및 Order 파일 필드
→ `prepare_astra_inputs / capture_order`
→ `_attach_enrichment_free_profile`의 기존 v6 INPUT_FIELDS
→ `preprocessing.tasks.run_preprocessing`의 기존 primary 분기
→ `enrichment_free_workflow.run_primary_analysis`
→ `astra_package.run_astra_analysis` immutable copy
→ `astra_evidence_v6.prepare_evidence`
→ `diann_evidence.observations(exact_group_sets=True)`
→ `localization_evidence.read_site_report / observation_sites / by_contrast`
→ `score_candidates`의 localization_ids/measurement_status
→ 기존 CSV/FK validator/archive/replay.

`user_orders` 파일-role 매핑 및 기존 create/start 위임도 코드로 대조했다. 해당 사용자 API에 대해 새 운영 요청을 보낸 것으로 보고하지 않는다.

## 합성 연결 검증

`api-server/tests/test_astra_measurement_dispatch.py`가 HTTP multipart upload를 실제 `/orders` route로 보내고, 임시 SQLite에 **실제 Order ORM**으로 저장한 뒤 새 session에서 다시 읽는다. prepare_astra_inputs와 dispatch helper를 거쳐 실제 Celery task 함수의 primary 분기를 호출한다. broker/진행 상태 DB/웹훅은 fixture로 대체하며 scientific consumer는 실제 함수를 호출한다. 운영 MySQL/Celery의 새 end-to-end 실행과 구분한다.

- main TSV, site Parquet, Run+Channel crosswalk 및 명시적 **합성 2.7.0** 버전의 byte/hash와 context가 유지됨.
- observation 124행 모두 export: matched 106, restricted 16, conflict 2. run/charge/channel 불일치, matrix 미검출/비기여, 중복 행을 삭제하거나 최고 confidence로 대체하지 않음.
- site report 3행: matched 1, main_report_unmatched 1, main_report_ambiguous 1.
- run confidence 0.98, library confidence 0.999, Q.Value 0.001, site probability 0.99/0.1을 각 필드로 유지. 낮은 target site probability를 높은 baseline 또는 run/library confidence로 승격하지 않음.
- 모든 localization row의 reference/target observation ID가 해당 contrast의 실제 joint injection mask 안에 포함됨. localized_A contribution의 localization_ids가 eligible row를 가리킴.
- prepare_evidence, observations, read_site_report, observation_sites, by_contrast, score_candidates 각각 실제 호출 1회 확인.
- 같은 source pin, audit_only에서 report 추가 전/후 정량 22표 byte-identical. quant calculator를 실패하도록 막은 후에도 cache 재사용으로 완료.
- network 차단 offline replay: scientific 68표 모두 byte-identical, source/observation/site/contrast ID 보존.
- 미기록 version 및 미지원 main-report header는 unsupported_schema+구체적 사유로 남고, 관측/확률을 생성하지 않으며 정량을 유지.
- main report 없는 crosswalk는 copied이지만 accepted_but_unused로 기록하는 회귀 포함.

이 fixture는 실제 DIA-NN 사용자 report 또는 공식 실제 report parity 검증이 아니다.

## 실제 재실행·수치 보존·검사

원본 g1 ZIP과 회차 04 성공 패키지는 읽기 전용 기준선이다. 기존 `validate_astra_reference_refresh.py`의 **prepare/reuse만** 재사용하여 별도 `codex-inputs/round05-20261007/execution/`을 만들었다. refresh 단계는 실행하지 않았다. 기존 source pin `7560c13a6b430363744157d74ad160a83e0939ec0754cedce20d7c0fe9dcbd8e` 및 audit_only를 유지하고, quant cache miss 시 중단하도록 하여 불필요한 재정량을 막았다.

재사용한 검증 스크립트의 provenance용 local ID(`round04-local`, `Round04_HIRcB_local`)는 그대로다. 새 run_id와 출력 root로 이번 실행을 식별하며, 이를 새 운영 Order 또는 실제 DB Order 70의 재실행으로 표시하지 않는다.

새 실제 run은 **`g0-bdc745269695409786357d6dba6e0fec`**다. 회차 04의 `g0-8584adc408d24b81b2f5162735d066bf`와 비교한 정량 22표는 전부 byte-identical이며 ID/text/NA 정확 비교와 수치 atol=rtol=1e-10 검사도 통과했다. primary/alternative normalization cache 모두 reused, 외부 source 요청 0회다. 과학 계산 코드는 바꾸지 않았지만 기존 stage cache가 v6 파일 전체 hash에 의존하므로 export 함수 변경 후 identity/discovery/footprint/temporal은 기존 엔진으로 다시 실행됐다. cache 정책을 우회하거나 수정하지 않았다.

실제 report 관측 0행, observation_site 0행, site identity mapping 11,614행, localized eligible 0이다. 11,614는 독립 site 수가 아니며 ambiguity와 복수 mapping을 포함한다. FASTA나 motif로 localization_probability를 만들지 않은 것을 확인했다. 새 package의 manifest 186 files / scientific 68 tables 검증 통과. runtime과 상세 표 상태는 [ROUND05_RESULTS.json](ROUND05_RESULTS.json)에 기록했다.

기존 회차 04 성공 pointer는 `g0-8584adc408d24b81b2f5162735d066bf`, 로컬 주문 70의 pointer는 `g3-0d38baee90a74fab8516a9b2fe5738af` 그대로다. 별도 출력 root에만 새 패키지를 publish했다. 전체 실자료 offline 재계산을 추가 수행했다고 주장하지 않는다.

검증 명령:

```sh
env PYTHONPATH=api-server:workers:. MPLCONFIGDIR=/tmp/ptm-round03-matplotlib \
 /tmp/ptm-science-v5-venv/bin/python -m pytest \
 api-server/tests/test_astra_measurement_dispatch.py api-server/tests/test_astra_input_capture.py \
 ptm_shared/tests/test_astra_evidence_integration.py::test_documented_curly_grammar_does_not_copy_minimum \
 ptm_shared/tests/test_astra_evidence_integration.py::test_baseline_confidence_never_promotes_low_target_or_missing_charge \
 ptm_shared/tests/test_astra_evidence_integration.py::test_exact_group_sets_and_channel_crosswalk \
 ptm_shared/tests/test_astra_evidence_integration.py::test_documented_site_report_join_and_no_minimum_replication \
 ptm_shared/tests/test_astra_science.py::test_exact_diann_observations_charge_run_library_conflicts \
 ptm_shared/tests/test_astra_science.py::test_raw_diann_version_invalid_numeric_and_fractional_charge \
 ptm_shared/tests/test_astra_figures.py ptm_shared/tests/test_astra_curves.py \
 -q --tb=short --import-mode=importlib --basetemp=/tmp/ptm-round05-final
```

**24 passed, 14.62 s.** 회차 02/03 그림 회귀 포함. 프런트 코드는 변경하지 않아 기존 빌드를 반복하지 않았다. 최초 새 fixture의 SQLite RAG table 누락 및 의도치 않게 ambiguous가 된 site test row를 바로잡은 뒤 위 검사를 통과했다. 실제 프로그램 오류를 시험 실패로 숨기지 않으며 그 두 fixture 준비 오류를 생산 코드 수정으로 계산하지 않는다.

합성 worker run은 `g0-167dee5cb566498b8bcef3fe464d62ba`다. 원 행/실패 예제 및 실제 파일별 전체 lineage는 로컬 산출물에 보존했다.

- [실제 파일별 INPUT_LINEAGE.csv](../../codex-inputs/round05-20261007/INPUT_LINEAGE.csv)
- [실제 입력/정량 검증](../../codex-inputs/round05-20261007/ACTUAL_VALIDATION.json)
- [합성 연결 검증](../../codex-inputs/round05-20261007/SYNTHETIC_VALIDATION.json), [대표 정상·실패·충돌 행](../../codex-inputs/round05-20261007/SYNTHETIC_LINEAGE_EXAMPLES.csv)
- [합성 offline replay](../../codex-inputs/round05-20261007/SYNTHETIC_REPLAY_VALIDATION.json)
- [새 실제 패키지](../../codex-inputs/round05-20261007/execution/output/astra_analysis_package_g0-bdc745269695409786357d6dba6e0fec.zip)
- [실제 실행 로그](../../codex-inputs/round05-20261007/actual_run.log), [테스트 로그](../../codex-inputs/round05-20261007/tests.log)

실제 산출물 감사에는 새 검증 스크립트 `scripts/validate_astra_measurement_lineage.py`를 사용했다. 기존 manifests/capabilities/lineage와 `validate_package`, `compare_quant`를 읽기 전용으로 재사용하며 새 입력 관리 체계나 계산을 추가하지 않는다.

백그라운드 프로세스도 용도를 확인했다. 기존 localhost API 8000/8011/8016/8017/8018 및 대응 검증 worker와 caffeinate는 과거 작업의 프로세스라 임의 종료하지 않았다. 이번 회차에 새 상주 API/worker는 시작하지 않았으며 pytest·실제 검증·산출물 감사 프로세스는 모두 정상 종료됐다. 기존 미커밋 7,444개 파일은 크기/mtime 비교에서 변경·유실이 없었다.

## 필요한 실제 자료와 남은 제한

현재 PR·PG·FASTA로 정량 및 서열 매핑은 가능하다. 실제 run localization 연결을 추가 검증하려면 **동일 DIA-NN 분석의 main report TSV/Parquet와 기록된 DIA-NN 버전**이 필요하다. site report가 있으면 같이 연결하고, Run/Channel이 matrix column과 다르면 해당 injection을 확인한 crosswalk가 필요하다. 실제 검색 FASTA 또는 확인 가능한 hash도 검색/분석 reference 동일성 확인에 필요하다.

확인하지 못한 버전·localization·raw spectrum 결과는 채워 넣지 않았다. 실제 report 부재 때문에 이번 소프트웨어 연결 검증을 생물학적 성능 검증으로 확대하지 않는다. 이 제한은 다음 회차의 독립적인 작업을 막는 조건이 아니다.
