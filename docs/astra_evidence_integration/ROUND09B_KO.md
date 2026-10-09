# 회차 09-B — PhosX S/T의 여섯 시간 contrast 실행

기준 main `e28e5960f392dc054609a44720b95a4cdc0d5577`, 기준 run `g0-cd1bc357e03640608c3fefcf444aa120`. 사용자 후속 지시에 따라 main에서 개발했다. 미커밋 `codex-inputs/`, 원본 ZIP, 이전 성공 pointer는 보존했다. 운영 배포·flag·회차 10 작업은 수행하지 않았다.

## 실행 범위와 재사용

기존 design → `ContrastEstimator.metadata()` → `same_time()`으로 Control reference와 각 시간을 확인한 뒤 기존 `science.official_methods.PhosX.contrast_ids`에 아래 여섯 ID를 명시했다. scope 생략으로 대체하지 않았다. 모두 실제 native 실행 `executed`이며 다른 시점 값을 대입하지 않았다.

- 1 min vs Control: `contrast_aea4869f398c5584`
- 5 min vs Control: `contrast_4147ebd64e7ecf80`
- 15 min vs Control: `contrast_eb2f813f825c4ccb`
- 30 min vs Control: `contrast_c15817d77868a59a`
- 60 min vs Control: `contrast_fd5240cdb335e779`
- 180 min vs Control: `contrast_d6757f4b8563521f`

실제 v6 계산 실행 `g0-3ba483e5a13f4e5faec3b684c5b228f5`, 최종 reader revision `g0-1f09d0d2622540cb894a61e0bf1b1aa0`: 기존 `prepare_evidence → kinase_specificity.score_sites → official_specificity.score_phosx → discover/score_candidates → official_method_tracks.execute_tracks → phosx_activity_adapter.execute → write_artifacts → astra_reader.write_reader`. 분석 함수·membership 기준·inference policy를 수정하지 않았다. 기존 code fingerprint/cache 경로에서 확장 scope에 맞는 canonical specificity/discovery/temporal을 생성했다. 1분용 checkpoint를 6시점 결과로 재사용하지 않았다. 기본 정량 cache `quant_v6_59024921d6b79f54630d`와 normalization 대안 cache `quant_v6_66ce0aceb9d95ad1f53c`는 hash 검증 후 재사용했고 `calculate`, 문헌 collect, network 호출은 실행 guard로 금지했다. 문헌 pin은 기존 apply 경로로 사용했다. Publication metadata의 source_requests=24/cache_hits=5는 재사용 pin에 이미 있던 query 기록 수이며 이번 실행의 신규 요청 수가 아니다. 이번 network 호출은 0이다.

원본 정량은 2,824 forms, site audit 11,614행이다. audit의 고유 site ID는 독립 실험 phosphosite 수가 아니다. 아래 form/site는 실제 귀속 적격 form–site 쌍이며, source audit의 복수 mapping을 독립 기질로 세지 않았다.

| 시간(min) | included joint A forms | 귀속 적격 form/site | S/T scored form/site | native ranked groups | selected memberships | 평가 가능 assay | coverage 부족 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1.0 | 2276 | 400 | 390 | 353 | 1595 | 153 | 150 |
| 5.0 | 2310 | 399 | 389 | 357 | 1612 | 158 | 145 |
| 15.0 | 2306 | 403 | 394 | 357 | 1611 | 155 | 148 |
| 30.0 | 2299 | 397 | 387 | 354 | 1601 | 156 | 147 |
| 60.0 | 2215 | 390 | 381 | 348 | 1570 | 152 | 151 |
| 180.0 | 2298 | 392 | 383 | 351 | 1582 | 153 | 150 |

303 assay × 6 contrast의 native 결과는 1,818행이다. 이 수는 활성 kinase 수가 아니다. 미선정 score, 미평가 Tyr, 모든 원본 mapping audit를 보존했다. 실제 audit `69,684`행과 전체 연결 `10,525`행은 로컬 `INPUT_AUDIT.csv`, `LINEAGE.csv`에 있다. ZIP에는 원본 identity/scorer/member/contribution 및 결과 전체 표가 계속 포함된다.

Native input 제외는 기존 공식 입력 경계(동일 group의 window가 하나, 유한하고 0이 아닌 A)에 따른다. 새로운 biological cutoff가 아니다.

- 1 min: multiple_sequence_windows_within_measurement_group=10, official_native_excludes_zero_A=6
- 5 min: multiple_sequence_windows_within_measurement_group=8, official_native_excludes_zero_A=6
- 15 min: multiple_sequence_windows_within_measurement_group=10, official_native_excludes_zero_A=6
- 30 min: multiple_sequence_windows_within_measurement_group=8, official_native_excludes_zero_A=6
- 60 min: multiple_sequence_windows_within_measurement_group=9, official_native_excludes_zero_A=5
- 180 min: multiple_sequence_windows_within_measurement_group=8, official_native_excludes_zero_A=6

모든 contrast에서 `method_membership.form_ids/site_ids`가 실제 S/T score 대상과 일치하며 A rank가 해당 contrast의 해당 group에서만 왔음을 검사했다. 공유 group `measurement_c75a362784a5ebb25742`의 미평가 Y204(`form_4d626ee8beb45f3f`)가 T205 ranking에 섞이지 않았다. 분모 변화를 숨기기 위해 fixed substrate 집합으로 대체하지 않았다.

- 1→5 min: 공통 349, 빠짐 4, 새로 포함 8 groups.
- 5→15 min: 공통 353, 빠짐 4, 새로 포함 4 groups.
- 15→30 min: 공통 351, 빠짐 6, 새로 포함 3 groups.
- 30→60 min: 공통 342, 빠짐 12, 새로 포함 6 groups.
- 60→180 min: 공통 341, 빠짐 7, 새로 포함 10 groups.

모든 시간의 공통 native ranked group은 331개다. 이 교집합은 설명용 집계이며 별도 재분석을 하지 않았다.

## 자원·환경·파라미터

회차 09 manifest `12eff82db554b22355169115f39fc4ba0ce65584f26aac4dcccf9b4b999dfa0a`를 bytes 그대로 사용했다. PhosX 0.23.1 / code commit `b556f59c39f099b5f3fcb574a8a70856c3fdc82c`; PSSM `7d18a78d6efc45925aacae9c62ea26c5d7c22519eb856b2891debeed0ea42c6d`, background `487beac611126c973c36b3b01161991a7c01d08e8d00f764136eb2c45aac1c11`. 실제 pip freeze는 회차 09의 로컬 freeze와 byte-identical하다. [ROUND09_ENVIRONMENT.lock](ROUND09_ENVIRONMENT.lock)은 같은 환경의 이식용 표기로, PhosX 로컬 경로 대신 검증한 고정 commit URL 및 주석을 사용한다. Python 3.11.13, 기존 설치 환경을 사용했고 의존성을 업그레이드하지 않았다.

A ranking, 10,000 permutations, seed 1729, single spawned worker, min hits 4, top 5, min quantile 0.95. Upstream activation evidence 미실행. 공식 offset −5…+4, 말단 underscore neutral factor, multisite/priming 미해석 제외를 유지했다. enzyme_mapping은 계속 비어 있다. Assay taxon human 9606과 substrate taxon을 구분하고 rat orthology나 human transgene 고유 귀속을 새로 추정하지 않았다. 자원 local-use/파생 수치 export 근거와 원본 재배포 제한은 회차 09 manifest를 그대로 계승한다. raw HDF5는 ZIP에 포함하지 않았다.

## Reader와 코드 변경

- `ptm_shared/astra_reader.py`: 기존 writer에서 canonical comparison metadata·native 결과를 투영하는 `phosx_time_views/write_phosx_time_views`만 추가. 시간은 numeric `time_min`, arm/reference/pairing은 분리한다. 같은 시간의 다른 reference를 합치거나 Control score를 만들지 않는다. 원 `method_result_id`, membership IDs, 입력 hash, per-contrast testing family, score/p/q·NA를 보존한다.
- `scripts/replay_astra_reader.py`: 새 archive의 method 원표를 함께 읽어 writer를 재사용한다. 기존 archive의 코드로도 실행하도록 기능 존재 여부로 구분한다.
- `scripts/validate_phosx_parity.py`: 여러 contrast의 union score 표에서 독립 reference의 form/site와 지정 contrast만 비교한다. 다른 시간에 대해 parity를 주장하지 않는다. 원본에서 기대값을 생성하는 공식 함수 호출은 유지했다.
- `ptm_shared/tests/test_phosx_reader_time.py`: shuffled ID/행, 다른 reference, 동일 assay 표시명, coverage 부족 NA, 원 native zero, 중복 metadata 거절, 지정 contrast 외 데이터의 parity 범위 검사를 추가했다.

`START_HERE_ASTRA.md → reader/READ_ME.md → reader/PHOSX_TIME_COURSE.md`에서 시간별 분모와 모든 assay의 시간별 score/p/q/기여 수를 읽는다. `reader/phosx_time_summary.csv`, `reader/phosx_assay_time_results.csv`는 원본 표의 투영이다. 새 finding 선정이나 LLM 설명 생성은 없다. native score와 descriptive specificity_A(log2)를 구분하고, coverage 부족의 원 native_score=0은 CSV에 보존하되 평가 가능한 score는 NA로 표시한다. 원본 링크 72개를 검사했다.

시점별 universe와 coverage가 달라 native score 최대 시점을 효소 활성 peak라고 부를 수 없다. Method p/q는 공식 rank null에 대한 값이며 biological p/q가 아니다. 각 contrast q-value를 전체 시간축 FDR로 묶지 않는다. 미측정 localization, 기술 반복, calibration 부재·no-call을 유지했다. 미평가 Tyr는 비활성이 아니다.

## 보존·검증 결과

- 정량 **22 CSV byte-identical**, 원 form/site/contrast identity·값·NA·joint masks 유지. 원 15개 finding ID·순서·cards의 관측, 문헌 선택/비교 pin과 검색·출처·비교 표 유지. Source pin `7560c13a6b430363744157d74ad160a83e0939ec0754cedce20d7c0fe9dcbd8e` 재사용.
- 1분: 기존 score 121,200행의 모든 공통 컬럼/NA, native 303행, membership 106,959행 및 execution input/output hash가 회차 09와 일치. 비교 tolerance `atol=rtol=1e-12`, 실제 이전 표를 기준으로 비교했다.
- 추가 독립 공식 parity는 결과를 보기 전에 선택한 **180분만** 수행했다. 원 FASTA/site identity/A에서 입력을 재구성했고 플랫폼 점수를 기대값으로 사용하지 않았다. raw/percentile 116,049행, native 303행, membership 106,353행 일치. 최대 절대 차이 `{'raw_score': 0.0, 'percentile': 0.0, 'native_score_p_q': 0.0}`. 5/15/30/60분 독립 공식 parity는 미수행이다.
- 동일 외부 hash 자원 + 계산 archive(`g0-3ba483e5a13f4e5faec3b684c5b228f5`) 자체 코드로 **6 contrast conditional method replay** 통과. 최종 표시 수정 archive와는 method 입력·출력 79개 표, replay config, 자원 pin 및 reader 이외 모든 계산 code hash가 동일함을 별도로 검사했다. 표시 수정 후 같은 6개 method 계산을 중복 실행하지 않았으며, 이를 새로운 독립 parity로 세지 않는다. 정량은 재계산하지 않았다. 이 검사는 전체 raw-input pipeline replay나 생물학적 검증이 아니다.
- 외부 자원/network/LLM 없이 저장 결과를 사용하는 **offline reader replay 18개 파일 byte-identical**. 실제 방법 재계산과 구분한다.
- 관련 pytest 고유 **30 passed, 0 skipped**: reader/official adapter 16, 회차 02·03 그림 13, 추가 comparator 1. 새 reader fixture 2개를 다시 실행한 결과를 중복 합산하지 않았다. pandas FutureWarning은 기존 null/concat 경계이며 NA mask를 별도로 비교했다. Fontconfig 기본 cache 권한 경고에서는 Matplotlib 임시 cache가 사용됐고 저장 그림·값을 대조했다.
- schema/FK/hash 검증 통과. 여섯 native 상태와 quant/findings/literature 불변 검사를 seal 직전에 수행한 뒤 격리 output에 게시했다. 실패 확장이 원래 성공 pointer를 바꾸는 경로는 없다. 운영 DB/API/배포 확인으로 확대하지 않는다.

의도된 변화: 추가 5개 contrast의 specificity membership/contribution/native 결과와 그 입력 scope를 참조하는 temporal/fixed membership/sensitivity·inference 설명 자료가 갱신된다. 아래 변화는 정량 변화가 아니다.

| 표 | 이전 행 | 새 행 |
|---|---:|---:|
| `evidence/coverage_funnel` | 9 | 9 |
| `evidence/emergence_evidence` | 19768 | 19768 |
| `evidence/feature_evidence_ledger` | 16944 | 16944 |
| `kinase/candidate_sensitivity` | 34346 | 59702 |
| `kinase/kinase_candidate_edges` | 168738 | 170556 |
| `kinase/kinase_candidate_summary` | 641 | 641 |
| `kinase/kinase_technical_omissions` | 3660 | 11664 |
| `kinase/kinase_temporal_profiles` | 53844 | 53844 |
| `kinase/method_executions` | 6 | 6 |
| `kinase/method_membership` | 106959 | 642360 |
| `kinase/method_scores` | 344 | 1859 |
| `kinase/substrate_contributions` | 13408 | 21219 |
| `reader/packet` | 1 | 1 |
| `science/evidence_dependency_groups` | 12284 | 20785 |
| `science/group_excluded_anchors` | 22486 | 38697 |
| `science/inference_results` | 11538 | 11538 |
| `science/kinase_calls` | 11538 | 11538 |
| `science/specificity_scores` | 121200 | 123018 |
| `temporal/group_excluded_cowave` | 6452 | 6504 |
| `temporal/kinase_fixed_membership` | 53844 | 53844 |
| `temporal/kinase_temporal_features` | 8974 | 8974 |
| `temporal/target_excluded_anchors` | 3226 | 3252 |

그림 renderer·시간축·선정 규칙은 수정하지 않았다. 그림 관련 25개 중 21개는 byte-identical이고 나머지는 확장된 근거 분모/source와 연결된 변경이다. 세부 파일은 JSON에 기록한다.

## 최종 표시 점검과 불변 revision

최초 reader 요약 표에서 header와 delimiter 사이 빈 줄이 확인되어 기존 writer의 표 직렬화 규칙으로 수정하고 회귀 assertion을 추가했다. 수치 CSV는 정상이었다. `astra_reader_revision`의 불변 복사 절차를 따라 기존 `write_reader`, `read_tables`, `StageLedger`, `seal_archive`를 호출해 새 run을 만들었다. 새 수집/계산/캐시 시스템은 추가하지 않았다. 문헌 collect와 compute_science를 guard로 금지했으며 79개 scientific table과 문헌 pin·그림을 모두 byte 그대로 보존했다. 변경된 reader 내용은 `PHOSX_TIME_COURSE.md`의 표 공백뿐이며 원 계산 archive도 유지했다. 코드 provenance·부모 manifest hash·재사용 ledger를 새 패키지에 기록했다. 최종 reader 자체 코드의 offline replay를 다시 수행했다.

## 산출물과 실행 시간

새 run **`g0-1f09d0d2622540cb894a61e0bf1b1aa0`**, ZIP `codex-inputs/round09b-20261009/execution/output/astra_analysis_package_g0-1f09d0d2622540cb894a61e0bf1b1aa0.zip` (SHA-256 `ff57954305b15debbebedefde90ecfafcdee16d77ffbe78530778716d4fb6a97`). Reader는 `codex-inputs/round09b-20261009/execution/output/enrichment_free_runs/g0-1f09d0d2622540cb894a61e0bf1b1aa0/reader/PHOSX_TIME_COURSE.md`.

실제 v6 계산 실행 2305.595초, reader 표시 수정 및 재봉인 88.330초. 조건부 method replay는 485.68초, 최종 offline reader replay는 28.85초였다. Native 각 시점 runtime, stage peak memory, cache 재사용·재계산 내역은 [ROUND09B_RESULTS.json](ROUND09B_RESULTS.json)에 있다. 실행시간이나 후보 수 증가는 성능 향상의 근거가 아니다. 로그·설정·원 자원은 `codex-inputs/round09b-20261009/` 및 회차 09 자원 폴더에 보존하고 커밋하지 않는다.

재현 명령(같은 고정 Python 환경):

```sh
python scripts/validate_phosx_parity.py --source <round09-package> --manifest <same-manifest> --contrast contrast_d6757f4b8563521f --output <new-independent-reference> --actual <round09b-package>
python scripts/replay_phosx_evidence.py --package <round09b-package> --specificity-manifest <same-manifest> --output <new-method-replay>
python scripts/replay_astra_reader.py --package <round09b-package> --output <new-reader-replay>
```

실험적 해석·생물학적 정확도 개선·Astra 보고서 우월성·calibrated call은 이번 회차의 검증 결과가 아니다. 운영 배포와 flag는 변경하지 않았다.
