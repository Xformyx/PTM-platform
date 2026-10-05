# Astra v6 근거 통합 인계

`astra_analysis.v6`는 experimental 기능이다. Localization의 관측→site→contrast 연결, specificity score의 실제 membership 반영, track별 공유 근거, policy 기반 판정, 공식 PhosX 선택 실행, 인접 시간 비교와 gene/group 제외 co-wave, 자원 조회 범위 및 checkpoint를 연결했다. 종 정보는 기존 Order 값을 재사용한다. 모든 비교 방법의 통합이나 과학적 정확도 개선이 완료된 상태는 아니다.

## 실제 검증 결과

- Engine 회귀 65개, API 계약 17개, 공식 PhosX adapter 3개, 프런트 context 4개 검사 통과. 프런트 build와 격리 API→worker→Results→download→Copy→Rerun 검사 통과.
- 실제 PR 177,116행 / PG 9,525행 / 21 injections로 실행했다. 이전 확보 v5 기준과 정량 CSV 22개가 수치·ID·NA 및 byte 수준에서 같았다.
- 새 실제 패키지의 과학 표 68개 모두 외부 통신 없는 replay에서 byte-identical이었다. 실행 ID는 `g0-18db51669e094784aece6fe5989b6486`이다.
- 기록된 stage 시간 합은 1,627.48초, process peak memory는 4,167,876,608 bytes, ZIP은 179,327,834 bytes다. 고정 source pin 실행이며 전체 live DB 조회 시간이나 replay 시간을 포함한 수치가 아니다.
- 실제 report/atlas/calibration 미제공으로 localized/specificity evidence 및 calibrated call이 새로 생겼다고 주장하지 않는다. 후보 수나 no-call 감소를 성공 기준으로 사용하지 않았다.

## 패키지와 코드 버전의 범위

실제 패키지는 검증한 실행 코드를 그대로 포함하며 수정하지 않았다. 패키지 생성 후 최종 소스에는 `diann_evidence.py`의 report/matrix accession 불일치 거절 조건 두 줄이 추가됐다. 이 차이는 [CODE_SNAPSHOT_DIFF.json](CODE_SNAPSHOT_DIFF.json)에 기록했고 최종 코드에서 engine 검사를 다시 실행했다. 실제 HIRc-B 실행에는 main report가 없으므로 이 조건은 소비되지 않았다. 최종 commit 전체를 실자료로 다시 실행했다고 표현하지 않는다.

요청한 exact g2 ZIP은 찾지 못했다. 따라서 338 candidate / 50,568 edges / 28,392 profiles는 확보한 다른 v5 입력·pin 기준이며 요청 g2의 336 / 50,556 / 28,224와 동일 기준선이 아니다.

## 실행 및 산출물 위치

저장소의 `codex-inputs/evidence-20261005/delivery/`에 실제 `astra_analysis_package.zip`, API에서 다운로드한 `synthetic_api_package.zip`, START_HERE, 로그, 화면 캡처, 환경 lock, 검증 JSON 및 checksums가 있다. 원자료를 포함하는 ZIP과 연구 입력은 Git에 올리지 않는다. Astra에는 실제 ZIP을 전달하고 내부 `START_HERE_ASTRA.md`부터 읽게 한다.

플랫폼에서는 운영자가 `PTM_ASTRA_EVIDENCE_V6=1`을 적용한 환경에서 기존 Order의 **Astra 분석 패키지 생성**을 실행하고 Results의 **Astra 분석 패키지 → 패키지 다운로드**를 이용한다. 추가 species나 preset 입력은 없다. 이번에는 격리 로컬 검증만 수행했으며 운영 배포와 운영 URL 확인은 하지 않았다.

## 문서와 남은 작업

- [코드 감사](CODE_AUDIT_KO.md): F01–F08, 실제 호출 경로, 수치 모집단과 한계.
- [검증 및 benchmark](BENCHMARK_REPORT_KO.md), [검사 목록](TEST_RESULTS.csv), [실제 전후 지표](BEFORE_AFTER_METRICS.csv), [replay](REPLAY_VALIDATION.json).
- [방법별 상태](METHOD_INTEGRATION_KO.md): 공식 PhosX와 repository z-score를 구분. Kinase Library runtime, 공식 PTM-SEA/KSTAR/PhosR/MSstatsPTM 등의 통합·실행은 남아 있다.
- [입력 부족](NEEDS_USER_DATA_KO.md): exact g2, 실제 DIA-NN main/site report와 버전, 승인된 specificity 자원, 독립 calibration/perturbation 자료.
- [migration·배포·복구](MIGRATION_AND_OPERATIONS_KO.md): API/worker 공통 reference, conditional replay, feature flag 및 rollback.

독립 benchmark, 실제 atlas parity, Astra A/B/C 비교와 독립 실험 검증은 미실시다. 현재 결과로 플랫폼의 과학적 우월성이나 production 기본 활성화를 권고하지 않는다.
