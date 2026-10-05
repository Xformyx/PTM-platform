# 검증 보고서와 독립 평가 계획

이번 검증은 소프트웨어 오류와 실제 HIRc-B 정량 회귀를 대상으로 한다. 독립 biological performance 개선, Astra-only 대비 보고서 우월성, 독립 perturbation 검증은 수행하지 않았다. 실제 calibration artifact가 없는 HIRc-B에서 calibrated call을 강제로 만들지 않았다.

## 실행 환경·명령

- engine/API: 격리 Python 3.14.6 환경, numpy 2.5.3, pandas 3.0.6, pyarrow 25.0.1. 로컬 전역 Python 변경 없음.
- 공식 PhosX: 별도 Python 3.11 환경, pinned upstream 0.23.1 코드, pandas 2.3.3. engine 환경에 호환되지 않는 의존성을 강제로 섞지 않음.
- UI: 저장소의 `npm run build`. 존재하지 않는 npm test를 가정하지 않음.

```sh
PYTHONPATH=. python -m pytest -q ptm_shared/tests/test_astra_package.py ptm_shared/tests/test_astra_science.py ptm_shared/tests/test_astra_evidence_integration.py
PYTHONPATH=. python -m pytest -q ptm_shared/tests/test_official_phosx_adapter.py
PYTHONPATH=api-server:. python -m pytest -q api-server/tests/test_analysis_context_preservation.py api-server/tests/test_astra_input_capture.py api-server/tests/test_analysis_job_lifecycle.py
cd frontend
npm run build
```

공식 adapter test는 공식 PhosX를 설치한 환경에서 실행해야 한다. 미설치 환경의 skip을 통과한 parity 검사라고 세지 않는다. 공개 upstream의 예제 859 site는 100 permutations로 native 계산을 실행했고 upstream의 3개 관련 검사도 통과했다. 합성 HDF5 adapter 검사와 이 공개 예제는 독립 kinase 정답 benchmark가 아니다.

실제 HIRc-B 재실행은 `scripts/validate_astra_science_archive.py --archive <확보한-v5-ZIP> --output <새-디렉터리> --profile v6 --replay`로 수행한다. exact g2는 미확보다. replay는 archive에 포함된 코드·입력·source pin만 사용하고 별도 프로세스/작업 디렉터리에서 1e-10 수치 및 정확한 ID/text/NA를 비교한다.

## 2026-10-05 T01–T18

| ID | 실제 결과/상태 | 범위와 근거 |
|---|---|---|
| T01 | passed | 실제 PR/PG/FASTA 정량 유지, measured localization 없음. missing input 표시 |
| T02 | partial / actual report not run | 문서 기반 합성 main/site TSV/Parquet 검사 통과. 실제 같은-version 사용자 report 없음 |
| T03 | passed synthetic | 정확한 run/charge/precursor, duplicate/conflict, channel crosswalk, PG 순서 변경; 원 row/hash 보존 |
| T04 | passed synthetic | minimum/library/q/site 확률 구분, multisite 복제 방지 및 범위 밖 값 거절 |
| T05 | passed synthetic | baseline만 고신뢰인 경우 target 승격 안 함; 누락 charge도 gate 통과 안 함 |
| T06 | passed local integration | API→DB→worker→site/contrast→archive, package replay, 브라우저 download/copy/rerun. 운영 환경 검증 아님 |
| T07 | passed synthetic | 99.9/0.1 percentile 교환 시 membership 교환. all score pairs는 보존 |
| T08 | partial | 실제 공식 PhosX 함수·공개 예제 실행, synthetic score/percentile/selection parity. 실제 Kinase Library atlas parity 미실시 |
| T09 | passed synthetic | curated_A가 비어도 motif/specificity 공유 measurement 구분, independent_vote_count=1 |
| T10 | passed synthetic | artifact 없이 보정 판정 금지, 합성 policy positive fixture에서 call 가능. 실제 calibration 검증 아님 |
| T11 | passed available baseline / exact g2 not run | 22 quant CSV 값/NA/text 및 byte 회귀; strict parent/emergence 포함 |
| T12 | passed fixture | technical n을 biological n으로 바꾸지 않음. 기존 pair/unit covariance resampling 검사 유지. 전체 CI coverage benchmark는 별도 |
| T13 | passed fixture | charge·mapping·동일 window 다른 site·mixed-species 공유 peptide 의존성 기존 검사 유지 |
| T14 | passed fixture | irregular grid/missing interval, fixed membership, LOTO 및 gene/group 제외. GP 정밀 시간 검증 아님 |
| T15 | passed fixture | U/P/A identity와 parent/normalization 대안·mask 차이 검사 유지 |
| T16 | passed frozen response / live partial | Reactome 7개 query, STRING 101개 ID의 cross-batch scope; HTTP 실패와 no_hit 구분. 전체 HIRc-B live annotation 완료 미실시 |
| T17 | passed local | 중단 시 pointer 보존, 고정 pin의 재개와 clean 과학 CSV 일치, quant 및 네 evidence stage 재사용, 깨진 checkpoint 재계산 |
| T18 | passed engineering | package hashes/schema/FK/NA/IDs, offline replay, permitted 및 restricted synthetic resource의 conditional replay. 실제 atlas license 승인 아님 |

실제 로그/숫자는 delivery의 validation JSON과 `TEST_RESULTS.csv`를 우선한다. 개발 도중 실패한 검사도 logs에 남겼고, 최종 통과와 혼동하지 않는다. 소스 변경 도중 검증을 중지한 code-hash guard 실패, snapshot test의 상대 경로 fixture 누락, 캐시 NaN run 집계, PhosX 미평가 행 순서 문제를 구분했다.

## 독립 평가와 release 판단

기존 `benchmarking/astra_science/protocol.json`의 study/cohort/ancestry split 및 unknown≠negative 원칙을 유지하고 `protocol_evidence_v2.json`에 현 v5/v6, localization-only, specificity-membership-only ablation과 A/B/C Astra authoring 비교를 명시했다. 이번에는 independent labels를 불러 threshold를 맞추지 않았다. calibration envelope의 checksum·domain·resource·split 검사는 외부 truth의 생물학적 타당성을 다시 증명하는 절차가 아니다.

공통 eligible universe와 native method coverage를 나누고 kinase/family resolution, taxon, ST/Y, enrichment, 설계를 층화한다. 원 연구 단위 interval, known target retrieval/direction, truth-evaluable call fraction과 selective risk를 사용한다. 미지 target 전체를 음성으로 두지 않는다. labels가 없으면 stability/abstention–coverage만 보고한다. 기존 insulin 사례는 개발에 사용됐으므로 unseen test가 아니다.

benchmarKIN/공식 comparator의 전체 dataset 정제·native 다방법 실행 및 새로운 held-out calibration은 남아 있다. PTM-SEA/KSTAR/PhosR/MSstatsPTM/RoKAI/PHOTON 미실행을 사용자 데이터 부재로 위장하지 않는다. 이들은 METHOD_INTEGRATION_KO에 별도 개발/자원 준비 상태로 적었다.

A/B/C Astra 실행은 모델 API/실행 접근 미확보로 `not_run_model_access_unavailable`이다. matched model/prompt/tools/time/token/literature와 blinded human rubric을 고정해 결과를 수집해야 한다. 현재 production 기본 활성화를 권고할 독립 정확도 근거는 없으며 v6는 experimental flag를 유지한다.
