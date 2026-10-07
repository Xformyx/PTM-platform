# 회차 01 — 일반 요청의 v6 실행 연결 확인

검증일: 2026-10-06~07 (Asia/Seoul). 기준: `6303102a15a9543b121834ebd790a83f8bce01e3` (시작 시 `origin/main`과 동일), 작업 브랜치 `feature/round01-v6-activation`. **격리 로컬 일반 UI → API → worker → v6 ZIP 연결을 확인했다. 운영 활성화는 미확인이다.** 운영 코드와 과학 정책은 변경하지 않았다. 기계 판독 결과는 [ROUND01_RESULTS.json](ROUND01_RESULTS.json)에 기록했다.

## 1. 변경 파일과 설정

- `scripts/validate_astra_activation.py`: 기존 frontend의 `withPersistedExportMode()`로 v5 생성 payload를 만들고, 실제 재실행 화면을 조작하며, API 저장값·실제 Celery dispatch·다운로드한 ZIP을 대조하는 localhost 전용 검증 도구.
- 이 문서와 실행 결과 요약. 새 engine selector나 profile은 추가하지 않았다.
- 격리 API 8017은 `PTM_ASTRA_EVIDENCE_V6=0`, API 8018은 `1`, worker는 `0`. 실제 프로세스에서 해당 flag만 확인했다. UI 5178은 API 8018을 사용한다. API/worker/UI 소스는 모두 기준 commit이다. Docker 운영 image 검증은 아니다.
- 기존 검증용 MySQL 13366에 새 주문만 생성하고 Redis 16386 DB10, 별도 input/output/reference directory를 사용했다. 비밀값과 전체 환경 변수는 기록하지 않았다.

## 2. 실제 재사용 경로

`OrderCreate/withPersistedExportMode` 및 `RerunOptionsModal` → `current_astra_context` → `orders._updated_analysis_context/_attach_enrichment_free_profile` → 저장 Order/dispatch → `preprocessing.tasks` → `run_primary_analysis` → 기존 v5 또는 `astra_evidence_v6.run` → `astra_package.run_astra_analysis` → 기존 다운로드 endpoint.

일반 UI는 v5를 요청한다. API 프로세스 flag가 정확히 `1`일 때 v6로 해석한다. worker는 전달된 mode를 실행한다. 따라서 worker에만 flag를 설정하는 것은 일반 요청의 v6 전환을 보장하지 않는다. 명시적 v6 요청은 이 flag가 없어도 허용되는 기존 동작을 유지했다.

## 3. 변경 전후 실제 실행

사용자 지시서의 `astra_analysis_package_g1-da89accad9bd4319868ecc868dedf685.zip`은 접근 가능한 프로젝트 자료에서 찾지 못했다. 대신 기존 실제 HIRc-B archive `codex-inputs/astra-science-20261001/delivery/astra_hircb_science_v5.zip`을 사용했다. 이는 지정 ZIP 자체의 재현 완료를 뜻하지 않는다.

- 원 archive SHA-256: `18a7482c5b76d1f8f5e0a0c21737fb317199d4572b7108a521cf4b80eef5af2e`.
- 실제 입력: PR 177,116행, PG 9,525행, 21 injections / 7 materials / 7 conditions / 6 contrasts. 기존 Order의 Rat_hir 및 설계를 그대로 사용했다.
- 고정 source registry pin: `7560c13a6b430363744157d74ad160a83e0939ec0754cedce20d7c0fe9dcbd8e`, 24개 기존 query 기록. `refresh_references=false`. 이 오래된 pin에는 acquisition_policy 필드가 없으므로 research_full 수집 완료라고 표시하지 않는다.
- 주문 70: 일반 v5 생성 요청 → flag 0 API → v5 dispatch → `g1-5c8d1fdd140e42fcad6cbb1380a0a593` 완료·다운로드.
- 같은 주문의 실제 UI **Re-run from Beginning → Confirm & create Astra package**: 브라우저 PATCH 요청 v5 → flag 1 API 저장 v6 → dispatch v6. 실행 중 이전 v5 성공 pointer 보존을 확인했다.
- 첫 v6 run `g2-de5039ca5d9841d8a5c3bb617d4d2b63`은 로컬 의존성 파일 소실로 package 조립에서 실패했다. 같은 버전을 복구한 뒤 기존 **Retry Analysis** 화면으로 다시 v5 요청 → v6 저장/dispatch를 확인했다. 새 run **`g3-0d38baee90a74fab8516a9b2fe5738af`**는 `completed_with_limitations`로 완료·다운로드됐다.
- 새 ZIP의 context / plan / provenance / replay가 모두 `astra_analysis.v6`, schema는 `astra_analysis_package.v6.experimental`이다. 기존 성공 v5 ZIP은 서버에서도 원래 SHA 그대로 보존됐다.
- `science/localization_by_contrast.csv` 69,684행, `science/inference_results.csv` 6,084행, `study/input_lineage.csv` 12행 및 `methods/method_registry.json` 존재를 확인했다. main report 부재로 measurement observations는 0행이고 readiness는 `missing_input/main_report_not_provided`다. localization table의 행 수를 측정 확률 또는 독립 site 수로 해석하지 않는다.
- 별도 주문 71은 일반 v5 생성 payload가 flag 1 API에서 v6로 저장되는지 확인한 draft다. 이 주문의 분석 완료를 주장하지 않는다.

## 4. 검증 기록과 재실행

원 실행 증거는 `codex-inputs/round01-20261006/`에 둔다. `ui-request.json`, `v5-dispatch.json`, `v6-dispatch.json`, `local-runtime.json`은 요청·저장·실행의 서로 다른 경계를 기록한다. `normal-rerun.png`는 실제 버튼을 누르기 전 화면이다.

- selector의 flag 없음/0/1 × v4/v5/v6: 9개 조합 통과, 입력 객체 불변.
- frontend `node --experimental-strip-types --test frontend/tests/analysisContext.test.ts`: 4 passed.
- `PYTHONPATH=.:api-server /tmp/ptm-science-v5-venv/bin/python -m pytest -q api-server/tests/test_analysis_context_preservation.py api-server/tests/test_astra_input_capture.py`: 7 passed.
- 두 실제 API의 `/orders/resolve-design`: 동일 v5 입력이 flag 0에서 v5, flag 1에서 v6 plan으로 해석됨.
- 기존 `test_interruption_keeps_pointer_then_reuses_quant`와 `test_species_package_replay_no_confirmed_calls`(종별 parameterization 포함): 3 passed / 30.69초. 실패 시 이전 성공 pointer 보존, cache 재사용 및 기존 v5 replay의 합성 회귀 검사다.
- 원 archive → 새 v5, 새 v5 → 새 v6의 정량 22개 표: 각각 22개 모두 byte-identical. ID/text/NA 정확 비교와 수치 `atol=rtol=1e-10` 비교도 통과했다. PR/PG/FASTA 및 source pin의 bytes/hash도 동일하다.
- 다운로드한 v6 ZIP의 포함 코드로 `replay.py --validate-only`: 177 manifest 파일 / 68 scientific table 검증 통과. 패키지의 Python 코드 42개(`__init__.py` 제외)는 checkout과 동일했다. 실제 전체 자료 replay 재계산을 이번에 다시 수행했다고 주장하지 않는다.
- 실제 Results의 패키지 다운로드와 API 다운로드 SHA-256이 동일했다: `7b9ca2a9d6859507defc86e8171b6ed563e9ae68d9bca511d5a89a6c309b2354`. Results/Data Files의 run ID도 동일하며 브라우저 page error는 0개였다.

완료 ZIP: `codex-inputs/round01-20261006/astra_analysis_package_g3-0d38baee90a74fab8516a9b2fe5738af.zip`. 화면 증거: `normal-rerun.png`, `v6-results.png`, `v6-data-files.png`. ZIP 내부의 `START_HERE_ASTRA.md`를 시작점으로 사용한다.

localhost runtime은 기존 `scripts/run_local_study_validation.py`로 시작했다. 비밀 환경 파일은 저장소/패키지에 포함하지 않는다. 검증 도구의 순서는 `create`(flag 0 API), `wait --label v5`, `rerun`(flag 1 API 및 UI), `wait --label v6`, `compare`, `results`이다. 생성 단계에는 `--archive`, 공통으로 `--base-url`·`--output`, 브라우저 단계에는 `--ui-url`을 준다. test 계정은 `PTM_TEST_EMAIL`/`PTM_TEST_PASSWORD` 환경 변수에서만 읽는다.

시작 전 같은 archive의 `references/source_pin.json` bytes를 SHA-256 파일명으로 격리 `REFERENCE_DIR/source_pins/<sha>.json`에 준비한다. API와 worker는 같은 디렉터리를 읽는다. 신규 source 수집을 이 비교에 섞지 않는다. frontend는 같은 checkout에서 API 8018을 proxy하도록 실행한다. 기존 실제 주문을 대상으로 검증 도구를 실행하지 않는다.

첫 import 시도 주문 69는 과거 archive의 첨부파일 저장 경로가 새 주문의 upload scope 밖이라 start에서 거절됐다. 검증 도구가 원 archive에 실제 포함된 첨부 bytes를 정상 upload API로 다시 등록하도록 수정했고, 그 주문은 취소했다. 운영 파일 접근 검사를 완화하지 않았다.

검증 도중 `/tmp/ptm-science-v5-venv`의 NumPy 등 package 파일과 distribution metadata가 사라진 것을 확인했다. g2는 소프트웨어 버전 값을 쓸 수 없어 조립 단계에서 실패했고, 실제 API에서 v5 성공 pointer 보존을 확인했다. 기존 `python-engine.lock`의 동일 105개 버전을 복구했다. 실패 기록·당시 누락 version·stage ledger는 `failed-g2/`에 보존한다. 재시도 준비는 flag 0 API에서 요청 mode만 v5로 되돌렸으며 나머지 context 불변을 검증했다. 복구 후 UI의 실패 주문 버튼명이 **Retry Analysis**임을 반영했다. 다운로드한 v5 ZIP의 자체 `replay.py --validate-only`는 manifest 147개 파일/57개 scientific table 검증을 통과했다. 이는 실자료 전체 replay 재계산과 구분한다.

## 5. 운영 적용 범위와 남은 제한

실제 운영 `https://ptm.xformyx.com/api/version`은 `6303102`를 반환했다. 이것은 공개 version marker이며 실행 중인 모든 프로세스의 commit 증명이 아니다. `/api/health/runtime-banner`는 401이었다. 운영 API flag·worker release·mount는 미확인이고 운영 설정 변경/재배포는 하지 않았다.

기존 Compose의 `api-server.env_file: .env`가 flag를 전달하므로 새로운 selector 코드가 필요하지 않다. 운영 적용 시 기존 환경 파일에서 `PTM_ASTRA_EVIDENCE_V6=1`을 설정하고 API 컨테이너를 재생성해야 한다. 단순 Git push나 환경 파일 수정만으로 실행 중 프로세스에 새 flag가 주입되는 것은 아니다. 같은 release의 worker/reference mount를 확인한 후 일반 UI 요청으로 새 run을 만들고 context/plan/provenance/replay를 확인한다. flag를 0으로 복원하면 새 일반 v5 요청의 자동 승격을 중지하며, 이미 저장된 명시적 v6 주문을 v5로 바꾸지는 않는다. 과거 archive와 성공 pointer를 삭제하지 않는다.

실제 DIA-NN main/site report, specificity 자원, calibration artifact는 이번 입력에 없었다. v6 실행 연결 성공은 localization/공식 자원 parity/생물학적 성능 검증을 뜻하지 않는다. source coverage 확대, heatmap 및 빈 그림 수정은 다음 회차이며 이번에는 수행하지 않았다.
