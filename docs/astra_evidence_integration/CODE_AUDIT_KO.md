# 2026-10-05 근거 통합 감사

조사 기준 HEAD는 `c63ff3cd5e96f20afb65915df668bddef67b6298`이며 추적 파일 변경은 없었다. 작업 브랜치는 `feature/astra-evidence-integration`이다. 적용되는 AGENTS.md는 없었다. main의 alias 중복 수정과 기존 Order 종 사용, 기본 Astra 흐름은 유지한다.

`codex-inputs`의 분석 ZIP 68개를 provenance로 조사했으나 요청한 g2-8402846e3668422d9fd85571a203b52f는 찾지 못했다. 사용자에게 경로를 요청했다. 기존 HIRc-B PR/PG/FASTA와 이전 self-contained v5 archive는 확보했다. 이를 이용한 대체 회귀와 정확한 g2 비교는 구분한다. 실제 DIA-NN main/site report는 없으며 이전 합성 report는 실험 localization 근거로 쓰지 않는다.

| 항목 | 시작 시 현재 코드 | 수정/검증 목표 |
|---|---|---|
| F01 | matrix에 localization 열 없음, 정상적인 missing input | capability/lineage와 연구자 안내 |
| F02 | main minimum confidence만 파싱, site 원문-only, contrast 연결 없음 | 관측·site·contrast canonical evidence, 조건별 gate |
| F03 | 모든 확정 call no_call 고정 | 독립 상태 축, hash/domain/split 검증한 policy 적용 |
| F04 | 모든 scored pair를 동일 membership으로 집계 | score 기반 명시 선택 정책과 all-row score 보존 |
| F05 | curated_A만 공유 index 생성 | track/domain별 공유와 cross-track 의존성 |
| F06 | preview 예산, STRING 배치내 scope, PubMed 앞 200개 | research_full, 명시 scope, checkpoint/cache 및 coverage |
| F07 | 재배포 불가이면 계산도 중단 | local use/result export/resource redistribution 분리 |
| F08 | GP 코드 포함과 실제 호출 별개 | 실제 함수/stage ledger; 지원 조건의 co-wave만 실행 |

새 과학 경로는 v6로 분리하고 v4/v5 archive는 고정된 포함 코드로 재현한다. 기본 정량 estimator는 변경하지 않는다. 연구 질문/예상 경로는 수치 선택 정책의 입력이 아니다. 독립 benchmark·calibration 전에 성능 개선이나 생물학적 검증을 선언하지 않는다.

## 외부 parser 근거

DIA-NN 공식 README checkout `5598ebbbe7a5313434f4986aa24262337ce6d5b0`의 main output 정의와 공식 discussion #1130의 site report join/column 구조를 확인했다. 원문과 버전/fixture parity를 구분한다. 실제 사용자의 보고서가 없는 상태에서 합성 parser 검사를 실험 원본 parity로 표시하지 않는다.

## 구현 결과와 남은 경계

| 항목 | 실제 변경 | 검증 및 제한 |
|---|---|---|
| F01 | `study/input_capabilities.json`, `input_lineage.csv`; matrix와 장비 raw 재검색 구분 | 실제 HIRc-B는 localization `missing_input`. 입력 정보 부재를 성공값으로 채우지 않음 |
| F02 | `localization_evidence.py`: main 관측→FASTA identity→site report→contrast의 실제 joint mask 연결 | 문서 기반 합성 TSV/Parquet, charge/run/conflict/Protein.Group 순서/channel 검증. site probability grammar는 2.7/2.7.0 계약. 실제 report parity 미검증 |
| F03 | `inference_policy.py`: execution/measurement/inference/entity/validation 분리, policy checksum·split·domain·resource 검사 | artifact 없는 결과는 보정된 call 아님. 합성 positive policy는 call 가능. 실제 calibration artifact 없음 |
| F04 | percentile와 rank를 membership에 소비; 모든 낮은 점수 행도 보존 | adversarial 점수 교환 검사. 공식 PhosX 함수 별도 adapter와 native ranked enrichment 연결. 임의 평균을 PhosX로 이름 붙이지 않음 |
| F05 | track·contrast·enzyme taxon별 공유 측정 index, cross-track dependency | curated가 비어도 motif/specificity 공유 근거 표시. 동일 자료의 방법 일치를 독립 투표로 세지 않음 |
| F06 | v6 `research_full`: 전체 고유 accession, PubMed 200개 단위 pagination, 긴 provider 예산, taxon round-robin, STRING ID resolution 후 전체 induced network | 7개 Reactome query 및 STRING 101개 ID의 배치간 edge 합성 검사. live identifier smoke와 전체 실제 network 완성은 다름. 기존 g2의 각 404 원인 재현은 미실시 |
| F07 | local-use/derived-export/redistribution 권한 분리, 원본 제외 시 동일 hash 외부 자원을 요구하는 conditional replay | 생성한 합성 HDF5에서 실제 공식 함수 계산→결과 export→자원 없이 replay 거절→같은 자원으로 replay 통과. 실제 atlas의 플랫폼 사용 권한은 미확정 |
| F08 | A adapter에서 기존 `compute_target_trajectory_evidence` 호출, gene/group 제외 co-wave, 인접 contrast | 코드 포함만으로 GP 실행했다고 하지 않음. legacy insulin 시간/잡음 가정이 있는 GP는 미실행 상태 유지 |

## 실제 호출 경로

`OrderCreate` / user order API → `Order` 파일 필드 → `prepare_astra_inputs` → worker config → `run_primary_analysis` → `astra_evidence_v6.run` → `astra_package.run_astra_analysis`.

1. preflight: Order의 종·canonical design·실제 FASTA 검사. 새 종 입력 폼 없음.
2. `quant_cached` → 기존 contrast estimator, 동일 injection U/P/A 및 strict parent. audit-only에서 report 추가는 정량 fingerprint를 바꾸지 않음.
3. `prepare_evidence` → main 관측, site report, site identity, contrast별 localization, specificity score와 membership.
4. `resolve_sources` / source pin → typed discovery → `score_candidates`. localized track은 해당 contrast 관측만 사용.
5. temporal adapter → 원래 irregular grid, fixed/available membership, 인접 구간, gene/group 제외 anchor.
6. `augment` → repository z-score, optional native PhosX, uncertainty, 정책 적용, 실제 제공된 perturbation record.
7. schema/FK/ID/hash 검증 → immutable archive → atomic current pointer. API의 preview와 다운로드는 동일 recorded run 참조.

`reproducibility/stage_ledger.json`은 archive 작성 시점 ledger다. 최종 publication 완료 시각은 run의 `stage_checkpoint.json`에 기록된다. ZIP 내부에 자기 발행 완료 시각을 소급 기입하지 않는다.

## 회귀 중 발견해 수정한 추가 오류

- 캐시 CSV의 빈 joint-run 문자열이 NaN으로 복원될 때 가짜 `nan` injection 1개로 세던 v6 localization 집계를 수정했다.
- PhosX 미평가 행의 set 기반 순서를 안정화했다. 원 값·NA는 그대로이며 method p/q가 없는 native zero를 별도 typed 결과에서는 결측으로 표시한다.
- localization evidence ID가 있다는 사실과 그 evidence가 threshold를 통과했다는 사실을 분리했다. 실패 행의 ID도 추적용으로 남는다.
- measured-gene z-score의 null universe는 taxon+검증된 FASTA gene으로 구분한다. 동일 symbol의 다른 종을 병합하지 않는다.

## 실제 데이터 기준선

확보한 이전 v5 archive 및 고정 source pin을 사용한 main baseline과 v6를 비교했다. 2,824 forms, 2,625 parent-eligible forms, primary 13,704행과 repeated-joint 11,920행은 서로 다른 모집단이다. candidate 338개 / edge 50,568행 / profile 28,392행은 이번 확보 archive 기준이며, 사용자 g2의 336/50,556/28,224와 동일 기준선이라고 주장하지 않는다. 차이 원인의 정확한 귀속에는 요청한 g2 원본이 필요하다.

정량 회귀는 22개 quant CSV를 비교한다. 수치 허용오차 1e-10, ID/text/NA 정확 비교 및 byte 비교를 별도로 기록한다. 실제 결과는 delivery의 `BEFORE_AFTER_METRICS.csv`, `REPLAY_VALIDATION.json`, 실행 validation.json을 따른다.
