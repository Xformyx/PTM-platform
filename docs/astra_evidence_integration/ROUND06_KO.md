# 회차 06 — 기존 카드 입력 투영

## 통합 및 범위

회차 01–04의 ancestor 관계를 확인하고 원격 main을 fetch했다. 다른 원격 변경은 없었다.
회차 05 `3a0e83a9bc3046f875a972e71cc2d6e84e1b096a`를 main에 fast-forward하고
일반 push했다. `git ls-remote origin refs/heads/main`도 같은 SHA를 반환했다.
통합 검증: `api-server/tests/test_astra_measurement_dispatch.py`, **3 passed (12.39 s)**.

이 main에서 `feature/round06-card-input-adapter`를 만들었다. 기존 미커밋
`codex-inputs/`는 커밋 대상에서 제외했다. 운영 배포·v6 flag 변경은 없다.

## 변경과 재사용

Production 변경은 5개 파일이다.

- `ptm_shared/astra_card_inputs.py`: 기존 결과와 원본 PR membership을 카드 입력으로
  투영한다. `astra_card_input.v1`의 별도 namespace이고 정량·통계·순위 계산은 없다.
- `ptm_shared/study_metadata.py`: 기존 worker의 순수 metadata 구현을 그대로 이동했다.
  원 구현과 byte-identical SHA-256:
  `de52100f1b870c51347203159975414582887c06bf6df7eaa02344ddd316657e`.
- `workers/report_generation/core/study_metadata.py`: 동일 공용 함수의 호환 import.
- `ptm_shared/astra_evidence_v6.py`: `augment()`에서 실제 변환 호출, readiness 및
  table key 검증, archive code provenance 등록.
- `ptm_shared/astra_package.py`: 실행에 고정한 snapshot을 augment와 replay에 전달.
  과거 v6 archive에는 새 adapter table을 소급 요구하지 않는다.

실제 재사용 함수: `canonical_feature_identity`, `project_reader_display_identity`,
`build_measurement_provenance`, `build_study_metadata_contract`, 기존 package
`write_tables`/`validate_package`/`replay_package`.
검증에서만 기존 `build_feature_observation_cards`와
`build_quantitation_comparison_cards`를 실행했다. production에서 카드 선정,
`select_finding_cards`, 연구 질문 매핑, reader packet, writer/LLM은 실행하지 않는다.

구현 전 작성한 [원본→대상 필드 대응표](ROUND06_MAPPING_KO.md)를 따른다.
`U_joint → ptm_unadjusted_log2fc`, `P_joint → protein_log2fc`,
`A → ptm_protein_adjusted_log2fc`를 직접 복사한다. `U_all/P_all`은 별도로 남긴다.
원본 비교의 수치·NA·포함/제외·mask·추정기·통계 단위는 `row_json`에 보존한다.
CSV의 빈 exclusion reason/run-mask 셀과 JSON null은 동일 NA 의미로 직렬화한다.
자유기술의 빈 문자열, 0, false, 빈 배열은 이 규칙의 대상이 아니다.

## 산출물과 소비 방법

`reader_adapter/`의 네 CSV는 all-row 자료이며 manifest/hash/FK/replay 대상이다.

| 파일 | grain / 내용 |
|---|---|
| form_identity.csv | form_id; 원 summary, 전체 site mapping, 실제 precursor membership ID |
| form_contrasts.csv | adapter_row_id; form×contrast, 원본 수치/NA·mask·source refs, 지원/보류 이유 |
| precursor_membership.csv | 원본 PR SHA+data row(헤더 다음 1부터); 실제 precursor/charge 및 양수 관측 injection |
| study_metadata.csv | 원 snapshot context·canonical design·필드 출처·충돌·sample 관계·기존 metadata contract |

`consumer_states(tables)`는 form×arm×reference×pairing별 상태를 반환한다.
같은 gene label로 다른 form·taxon·reference를 합치지 않는다.
상태의 `source_adapter_row_ids`에서 비교 행으로 역추적한다. 그 행의 `source_refs`는
summary/comparisons/runlevel의 원본 키를 가리키며 mapping/localization ID는 기존
science 표를 가리킨다. 원 PR 파일 SHA 및 행 번호로 precursor도 확인할 수 있다.

현재 기존 카드 계약은 단일 precursor이다. 여러 precursor인 form은 새로운
Precursor.Id를 만들지 않고 raw-only로 남긴다. mixed/unknown taxon, 불명확한 gene,
누락 또는 충돌하는 membership도 동일하다. 한 precursor의 다중 modification은
하나의 측정으로 유지한다. 실제 localization이 없어도 sequence mapping은 유지하지만
확률을 생성하거나 localized site로 표시하지 않는다.

기존 카드에는 excluded finite contrast를 판별하는 gate가 없다. 그런 값은 원표에
그대로 보존하고 해당 consumer state를 `raw_only_excluded_finite_contrast`로 보류한다.
유효한 상태의 중간 NA는 원래 시간점으로 유지한다. parent가 없어 U_joint/P_joint/A가
NA이면 U_all로 대체하지 않는다. 독립 생물학적 p/q/CI를 생성하지 않는다.

## 검증

- 작은 fixture: 단일·다중 수정, 복수 charge, parent 결측, human/mouse 동일 gene label,
  실제 mixed-taxon form, 두 reference, 30/60/120분과 중간 NA, 중복 precursor,
  잘못 바꾼 U, excluded finite값, 원문·0·false·빈 배열·metadata 충돌.
- 실제 기존 카드 함수로 수치·시간·NA·mask·biological n=1을 확인했다.
- 새 interpreter에서 repository의 PYTHONPATH 없이 package 코드만으로 offline replay.
- 회차 02·03 그림, 기존 v6 package/interruption, API→worker 경로와 기존 카드 테스트.

명령은 `PYTHONPATH=api-server:workers:.`, `MPLCONFIGDIR=/tmp/ptm-round03-matplotlib`,
`/tmp/ptm-science-v5-venv/bin/python`을 사용했다. 검증 loader는 기존 pure 카드 모듈을
실행하되 `core/__init__`의 전체 graph/LLM 초기화만 피한다. 함수 본문은 mock하지 않는다.

최종 회귀 **46 passed (35.30 s)**:
`test_astra_card_inputs.py`, `test_measured_feature_cards.py`,
`test_astra_evidence_integration.py`, `test_astra_figures.py`, `test_astra_curves.py`,
`test_astra_measurement_dispatch.py`. 이후 comparison 카드 값 검증을 강화한
해당 projection test **1 passed (0.39 s)**.
로그: `codex-inputs/round06-20261007/tests.log`.

기존 회차 05 package도 현재 validator로 재검사: **186 files / 68 scientific tables** 통과.
초기 전체 worker 테스트 import는 환경에 langgraph가 없어 collection 실패했다.
이후 순수 카드 함수만 로딩하여 위의 실제 기존 카드 회귀를 실행했다. 전체 report graph를
실행한 것으로 표시하지 않는다. cache/replay의 optional 빈 셀 직렬화 차이를 발견해
수정한 후 관련 테스트를 통과했다.

## 실제 입력 검증

g1: `astra_analysis_package_g1-da89accad9bd4319868ecc868dedf685.zip`.
회차 05 기준 run: `g0-bdc745269695409786357d6dba6e0fec`.
PR/PG/원본 FASTA의 bytes는 g1과 동일하며 source pin은
`7560c13a6b430363744157d74ad160a83e0939ec0754cedce20d7c0fe9dcbd8e`다.
DIA-NN main/site report 및 실제 버전이 없는 사실은 그대로다.

실제 실행 결과·22개 정량 표 비교·새 run ID는 `ROUND06_RESULTS.json`과 아래 결과
절에 기록한다. 실제 실행은 local engine이며 새 운영 주문/운영 UI 검증이 아니다.
외부 조회와 재정량 호출은 실패하도록 차단했다. 기존 cache 정책은 변경하지 않았다.

현재 제한은 단일 precursor 카드 계약과 입력 부재이다. form 전체를 수용하는 새로운
카드 엔진, 핵심 findings/문헌/질문/새 방법은 이번 회차에서 구현하지 않았다.

### 실제 완료 결과 (2026-10-08 확인)

새 run: **g0-ae3bd0a0ea5f4a5080617fe5553ccfd1**. 실제 v6 `augment()`에서 adapter가
**1회** 호출됐다. 패키지 검사 **194 files / 72 scientific tables** 통과.
총 2,824 forms와 16,944 comparison rows 모두 adapter에 남았다. 이 분모는
13,704 primary included comparisons와 다르다. 12,499행은 카드 행 계약에 적격이며,
form·arm·reference·pairing으로 구분한 **2,159 consumer states**를 반환한다.
서로 겹치는 보류 사유의 행 수를 더해 전체 제외 수로 해석하면 안 된다.

| 사유 | 행 수 |
|---|---:|
| 원 비교 excluded | 3,240 |
| multiple precursors / precursor identity 불가 | 각각 1,266 (동일 행의 복수 사유) |
| gene 표시 불명확/없음 | 60 |
| mixed/unknown taxon | 12 |

172 consumer states에는 excluded finite 비교가 있어 원값을 바꾸지 않고 전체 상태의
카드 소비를 보류했다. 전체 원표는 유지한다.

대표 원본 추적(모두 첫 target 1 min, contrast `contrast_aea4869f398c5584`):

| gene / form / 실제 precursor | U_joint | P_joint | A | reference/target joint n |
|---|---:|---:|---:|---:|
| Dock7 / form_5f6b1591279b085d / SPS(UniMod:21)GSAFGSQENLR2 | -0.0504072064726166 | -0.0000804535575085 | -0.0503267529151028 | 3/3 |
| Sik3 / form_0307f4dc0d707fd5 / IQPSS(UniMod:21)PPPNHPSNHLFR3 | 0.3812828811164372 | -0.1192121191149304 | 0.5004950002313722 | 2/3 |
| Rbm26 / form_927c72b605b8f2bd / RLNHS(UniMod:21)PPQSSSR3 | 0.2214193486198219 | 0.0266273003848453 | 0.1947920482349825 | 3/3 |

이 세 상태를 기존 두 카드 함수로 읽고 모든 trajectory point의 숫자/NA/시간과
각 축의 reference/target injection ID 집합, comparison 카드 숫자를 확인했다.
Sik3의 P_all은 -0.118119756269948로 P_joint와 다르며, 카드에는 P_joint가 들어간다.
값의 근거는 `quant/comparisons.csv`의 form_id+contrast_id, mask는 `quant/runlevel.csv`,
precursor는 `reader_adapter/precursor_membership.csv`의 원 PR SHA+row다.
전체 정밀도와 원본 row 키는 검증 JSON에 남아 있다.

**정량 22개 CSV는 회차 05와 모두 byte-identical**이다. ID/text/NA exact 검사 및
수치 atol=rtol=1e-10 검사를 별도로 통과했다. primary 및 normalization sensitivity
cache는 reused이고 네트워크 요청은 0회다. source pin과 이전 ZIP bytes도 불변이다.
v6 파일 전체 hash가 evidence cache에 참여하는 기존 규칙 때문에 identity/discovery/
footprint/temporal은 재실행됐다. cache 정책을 우회하거나 재정량하지 않았다.
시간 단계 1,272.23 s, footprint 123.98 s, 정량 cache 읽기 32.50 s.

ZIP: `codex-inputs/round06-20261007/execution/output/astra_analysis_package_g0-ae3bd0a0ea5f4a5080617fe5553ccfd1.zip`
(189,886,495 bytes), SHA-256
`bb15c1ef3e4c31fd5031ae5ff863d34cb0f72cccc8606dafecbc31eda23c222d`.
원 ZIP/입력/임시 출력은 git에 추가하지 않았다.
상세: `codex-inputs/round06-20261007/validation/CARD_INPUT_VALIDATION.json`,
`CARD_INPUT_EXAMPLES.json`, `execution/ACTUAL_EXECUTION.json`, `actual_run.log`.
기존 미커밋 7,776개 파일의 size/mtime_ns가 모두 보존됐고 기존 그림 구현도 변경되지 않았다.

새 ZIP만 `/tmp/ptm-round06-archive-reprojection`에 풀고 그 안의 code/input/table/snapshot으로
adapter를 다시 실행했다. ID/text/NA와 JSON 내 수치(atol=rtol=1e-10)를 전수 비교해
4개 adapter 표가 일치했다: identity 2,824행, contrast 16,944행, 실제 precursor membership
3,035행, metadata 1행. CSV를 읽을 때 `data_dictionary.json`의 문자열 타입을 사용해
taxon ID가 숫자로 자동 추정되지 않게 했다. 네트워크 0, 재정량 없음.
`validation/REPLAY_VALIDATION.json`은 **실제 archive의 adapter 재투영 및 전체 package 검사**
결과다. 실제 72개 과학 표의 전체 재계산을 다시 했다는 뜻은 아니다.
별도의 합성 archive는 repository 없이 새 interpreter에서 전체 **72개 표 byte-identical**
offline replay를 통과했다 (`validation/SYNTHETIC_REPLAY_VALIDATION.json`).
