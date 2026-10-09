# 회차 09 — 공식 PhosX Ser/Thr 자원의 실제 연결

기준 main: `d18965af492ad9943493aeb088e32d8e7732b07f`. 기준 패키지: `g0-cebc9961d46d4fb28c35e1eb2e8d87dd`. 이번 검증은 로컬 v6 패키지 실행이다. 운영 DB·배포·flag는 변경하지 않았다. 기존 `codex-inputs/`와 성공 패키지는 보존하며 원자료·행렬·문헌·DB 자료는 Git에 넣지 않는다.

## 재사용과 수정 경계

- `kinase_specificity.score_sites → official_specificity.score_phosx`: 기존 공식 scoring·percentile·binarisation 함수를 그대로 호출한다. 새 scorer나 일반 percentile gate로 대체하지 않았다.
- `astra_evidence_v6.prepare_evidence/discover/score_candidates → astra_discovery.score_candidates`: 기존 site 귀속·parent·joint A 적격성을 사용한다. `science.official_methods.PhosX.contrast_ids`로 실행 범위를 명시하고, 그 외 contrast의 specificity footprint는 `not_requested`다. 생략하면 기존 전체 contrast 동작을 유지한다. 원본 identity audit는 전부 남긴다.
- `official_method_tracks.execute_tracks → phosx_activity_adapter.execute`: 기존 native ranked enrichment를 실행한다. 평가 불가 score의 뒤쪽 행이 유효 assay label→candidate 연결을 `None`으로 덮어쓰던 결함을 수정했다. 이것은 점수·threshold 변경이 아니다.
- `astra_package.run_astra_analysis`: 명시적으로 전달한 기존 `finding_literature_pin`은 `astra_literature.apply`의 hash·finding 순서·원 관측·선택 검사를 거쳐 재사용한다. 검증 실패를 신규 검색으로 우회하지 않는다.
- `evidence_methods.registry`: 실제 실행 contrast와 요청하지 않은 contrast를 분리한다. `astra_reader.write_reader` 및 v6 START_HERE addendum에 기존 점수·membership·기여도·registry 링크와 해석 범위를 연결한다.
- `scripts/validate_phosx_parity.py`: 기준 패키지의 FASTA/site identity/A에서 독립적으로 공식 입력을 생성하고 공식 함수를 실행하는 검증 도구다. 플랫폼 출력으로 정답을 생성하지 않는다.

전달 경로는 기존 Order `specificity_manifest_path` → API `_attach_enrichment_free_profile`의 `INPUT_FIELDS` 복사 → worker `run_primary_analysis`의 config 전달 → v6 `INPUT_FIELDS` → package immutable copy → `_LOCAL_SPECIFICITY` → canonical scoring → candidate edge/contribution → native method → writer다. 이번 실제 검증은 등록된 로컬 manifest를 worker와 동일한 v6 실행 config에 전달했다. 운영 업로드/API/DB를 새로 실행한 검증으로 확대하지 않는다. 업로드 manifest만 있고 상대 경로 행렬/background가 없으면 실행 가능한 자원 등록이 아니다.

## 자원·환경과 이용 범위

실제 자원은 이미 설치된 `/tmp/ptm-official-methods-20261005-venv`와 `/tmp/ptm-evidence-20261005-phosx/phosx/data`에서 찾았다. 새 atlas나 임의 행렬을 다운로드해 대신 사용하지 않았다. 설치 파일과 고정 checkout의 scorer·native 함수·행렬 bytes를 대조했다.

- PhosX `0.23.1`, commit `b556f59c39f099b5f3fcb574a8a70856c3fdc82c`.
- Ser/Thr PSSM 303개: `S_T_PSSMs.h5`, SHA-256 `7d18a78d6efc45925aacae9c62ea26c5d7c22519eb856b2891debeed0ea42c6d`.
- Background 10,000 × 303: `S_T_PSSM_score_quantiles.h5`, SHA-256 `487beac611126c973c36b3b01161991a7c01d08e8d00f764136eb2c45aac1c11`.
- Metadata: `kinase_metadata_annotated.h5`, SHA-256 `ab48c161eb8f35225cc410331c71cd0d35c1fd198a828a6eb78069d3fc341952`. Family/specificity/서열은 있지만 검증된 accession·rat orthology crosswalk는 없다. 따라서 `enzyme_mapping={}`이고 공식 assay label을 그대로 보존한다. Assay taxon=9606, inferred kinase taxon은 unknown이다. 기질 taxon을 enzyme taxon으로 복사하지 않는다.
- Python 3.11.13, pandas 2.3.3, numpy 2.4.6. 기존 PhosX 환경을 유지하고 v6 import에 없던 scipy/jsonschema/biopython/statsmodels만 고정 버전으로 추가했다. 전체 lock은 실제 산출물의 `python_environment.lock`에 있다.
- 공식 offset −5…+4, 중심 index 5; 말단 `_`는 공식 neutral factor. Multisite/priming 미해석·site 귀속 불명확성은 기존 gate에서 보존/제외한다. Tyr를 Ser/Thr 행렬로 평가하지 않는다.
- Native 설정: A ranking, 10,000 permutations, seed 1729, spawned single worker, min hits 4, top 5, min quantile 0.95, timeout 14,400초. Upstream activation evidence는 실행하지 않는다. 공식 CLI 기본값 전체와 같은 실행이라는 주장을 하지 않는다.

[고정 PhosX 배포](https://github.com/alussana/phosx/tree/b556f59c39f099b5f3fcb574a8a70856c3fdc82c)와 [LICENSE](https://github.com/alussana/phosx/blob/b556f59c39f099b5f3fcb574a8a70856c3fdc82c/LICENSE)를 확인했다. 설치 배포는 해당 HDF5를 포함하며 Apache-2.0을 선언한다. 이 배포에 근거해 로컬 계산과 수치 파생 결과를 사용했다. 별도 atlas 원문·`kinase_pssms` 전체 자원을 재허가했다고 해석하지 않는다. 원본 재배포는 보수적으로 `not_packaged_pending_upstream_atlas_redistribution_review`로 두어 ZIP에서 행렬/background를 제외했다. Manifest는 각각의 권한·근거·hash를 별도로 기록한다. 동일 hash의 외부 자원 없이는 완전한 수치 replay라고 하지 않는다.

## 실제 입력 및 분모

기존 study design에서 가장 이른 target인 **1 min vs Control** (`contrast_aea4869f398c5584`)을 선택했다. 좋은 결과를 보고 시점을 고르지 않았다. 다른 5개 contrast의 native method는 `not_requested`다. 기존 정량 22표와 정규화 민감도 cache, source pin, 문헌 선택 pin 및 비교 pin을 사용하고, network/재정량/문헌 collect를 실행 중 guard로 차단했다.

원래 localization report가 없는 상태는 그대로다. 서열 점수는 FASTA 기반 specificity 예측이며 실제 phosphosite localization posterior가 아니다. 기술 반복은 biological n=3으로 바뀌지 않는다.

실제 수치·산출물 및 검증 완료 상태는 아래 실행 결과 절과 `ROUND09_RESULTS.json`에 기록한다.

### 발견한 두 전달 결함

1. 평가 불가 Tyr score 행이 마지막에 올 때, 앞서 연결한 assay label의 candidate ID가 `None`으로 덮어써졌다. 실제 canonical checkpoint에서 이전 loop는 0개, 수정 loop는 303개 연결을 유지했다. 이 비교는 입력 경계 재현이며 이전 native method 전체 실행 결과라고 부르지 않는다.
2. 독립 공식 실행과 비교하면서 `measurement_c75a362784a5ebb25742`의 Q5XIU9 Y204/T205 form이 같은 그룹이라는 것을 확인했다. S/T 자원에서 Y204는 미평가인데도 기존 native 입력 median에 섞여 T205의 A `-0.541177573451165` 대신 `-0.26004095514120884`가 들어갔다. 실제 점수화된 form/site만 native ranking에 연결하도록 수정했다. 원 정량·measurement group·site ID를 바꾸지 않았고 Y204를 별도 S/T 기질로 만들지 않았다. 수정 후 ranked 입력 353행의 SHA는 독립 공식 입력과 동일한 `2bbf528ea51c9ad5d3a0733db348fad89e264f60a5a5657d68531885e10b2ddd`다.

두 번째 결함을 발견한 중간 run `g0-b93af6b8382e4d8cb42a5eba90415804`는 보존하지만 최종 parity 통과 패키지로 제시하지 않는다. 최종 run은 아래 결과에 명시한다. 최초 candidate binding 점검 중 중단한 `g0-114fda3b933d49cea48cc348f1f087a0`도 성공으로 집계하지 않는다. 이전 회차의 성공 ZIP과 pin은 변경하지 않았다. 실패·중단·비교 실패를 통과로 집계하지 않는다.

### 측정·입력 분모

| 범위 | 수 | 의미 |
|---|---:|---|
| 원 form | 2,824 | charge collapsed quantitative form |
| site identity audit 행 | 11,614 | 복수 accession/좌표 mapping 포함 |
| 고유 site ID | 9,987 | 독립 실험 phosphosite 수가 아님 |
| 전체 measurement group | 2,633 | 의존 측정 묶음 |
| 1분 contrast included joint A form | 2,276 | 실제 joint 관측을 가진 원 비교 |
| site 귀속 부적격 audit 행 | 11,171 | 원본 audit의 사유 보존 |
| 귀속 적격이나 선택 contrast의 joint A 없음 | 43 | 다른 시간을 끌어와 채우지 않음 |
| scorer 입력 form/site | 400 | 원 identity와 비교의 교집합 |
| S/T 점수화 form/site | 390 | 고유 site ID 350, measurement group 369 |
| Tyr 입력 | 10 | S/T 자원 적용 불가 |
| 실제 scored site×assay 행 | 118,170 | 390 × 303; 독립 기질 수 아님 |
| 미평가 site×assay 행 | 3,030 | 10 × 303, unsupported_center_residue |
| 공식 selected score/edge | 1,769 | min quantile 0.95 및 top 5, 동률 정책은 공식 함수 |
| descriptive specificity contribution | 1,576 | native rank enrichment와 별도 집계 |
| native ranked measurement group | 353 | 369 중 복수 window 10, A=0 6 제외 |
| native 결과 | 303 | 평가 가능 153, coverage 부족 150 |
| native membership 행 | 106,959 | 353 × 303; 선정 1,595 |

Scorer에 들어간 S/T 관측의 substrate taxon은 rat 10116이다. 전체 audit의 human P06213 Y1185/Y1190 mapping은 species/mapping·parent 적격성 제한을 유지하며 S/T input으로 승격하지 않는다. hIRc-B라는 설명으로 human construct 고유 site를 확정하지 않았다. Native 353개 중 여러 form이 있는 그룹의 기존 median A input policy를 유지하되, 해당 자원에서 실제 score가 있는 form만 사용한다. 이 경계는 원 PTM 정량의 재평균이나 estimator 변경이 아니다.

## 검증 해석과 남은 범위

- 수치 parity는 기존 공식 `pssm_scoring`, `quantile_scaling`, `binarise_pssm_scores`, `compute_kinase_activities`를 독립적으로 호출해 비교한다. 기대값은 기준 패키지의 원 FASTA·site audit·joint A에서 만들었으며 플랫폼 점수 출력을 정답으로 다시 읽지 않았다. 같은 float64 함수이므로 `atol=rtol=1e-12`를 사전 사용했다. PhosX 2024 논문 당시 release 전체 또는 upstream activation 단계와의 동등성을 주장하지 않는다.
- 기본 resource 없는 실행, 입력 scope 생략, 재배포 허용/제한, 일반 percentile gate와 공식 membership의 충돌, 마지막 미평가 행, 공유 S/T–Y 측정 그룹을 작은 fixture로 검사한다. Fixture의 100 permutations는 연결 테스트만이다. 실제 HIRc-B, 독립 공식 비교, 조건부 method replay는 모두 10,000 permutations·seed 1729다.
- `reproducibility/data_dictionary.json`은 행별 의미·PK/FK/nullable 계약을 유지한다. CSV의 nullable method p/q가 mixed-method 표에서 object dtype으로 기록된 경우 검증 스크립트는 명시적 숫자 열만 변환해 비교한다. ID·문자열을 수치로 변환하거나 NA를 0으로 채우지 않는다.
- 이 run의 matrix/background는 ZIP에 포함하지 않는다. `scripts/replay_phosx_evidence.py`는 패키지 자체 코드, 보존된 정량 표와 동일 hash 외부 manifest/HDF5로 specificity와 native method만 재계산한다. `scripts/replay_astra_reader.py`는 외부 자원 없이 저장 결과·문헌 pin에서 reader만 재구성한다. 두 replay의 범위를 구분한다. 환경은 [ROUND09_ENVIRONMENT.lock](ROUND09_ENVIRONMENT.lock)에 고정하며, 새 빈 환경 설치까지 검증했다는 뜻은 아니다.
- 패키지 생성 중 `official_parity_status`는 공식 함수 호출 사실과 per-run 독립 검증 미수행을 구분한다. 외부 검증 결과는 이 문서와 `ROUND09_RESULTS.json`이 최종 archive hash에 연결한다. 완료된 ZIP의 JSON을 뒤늦게 바꿔 통과 상태를 삽입하지 않는다.
- 이전 성공 archive와 input bytes는 보존한다. 최종 실행은 독립 출력 디렉터리에서 수행한다. corrupted literature pin fixture에서는 기존 current pointer가 그대로 유지된다. 운영 주문의 current pointer·환경·flag는 이번 검증 대상이 아니다.

이번 결과는 소프트웨어 연결·공식 수치 재현 검증이다. Localization은 여전히 미측정이며, enzyme accession/rat orthology를 확정하지 않았다. Calibration artifact와 독립 perturbation 실험은 추가되지 않았다. 생물학적 정확도 개선, rat 효소 활성, 직접 kinase–site 인과 또는 Astra 보고서 우월성을 입증한 결과로 확대하지 않는다.

### 재현 명령과 검증 범위

실행 환경의 Python은 `/tmp/ptm-official-methods-20261005-venv/bin/python`이다. 다음 도구는 원본 ZIP이나 완료된 run 내부를 수정하지 않고 별도 `--output`에 기록한다.

```sh
# 1. 기준 FASTA/site/A에서 공식 기대값 생성 (실제 10,000 permutations)
PYTHONPATH=. python scripts/validate_phosx_parity.py \
  --source <baseline-package-directory> --manifest <specificity.json> \
  --contrast contrast_aea4869f398c5584 --output <official-reference-directory>
# 2. 이미 생성한 공식 기대값과 새 패키지 비교: 공식 실행을 반복하지 않음
python scripts/validate_phosx_parity.py --compare-only \
  --output <official-reference-directory> --actual <new-package-directory>
# 3. 패키지 자체 코드 + 동일 외부 자원으로 방법 단계만 재계산
python scripts/replay_phosx_evidence.py --package <new-package-directory> \
  --specificity-manifest <specificity.json> --output <conditional-method-directory>
# 4. 외부 자원·네트워크·LLM 없이 저장 결과 reader 재구성
python scripts/replay_astra_reader.py --package <new-package-directory> \
  --output <reader-replay-directory>
```

완료된 패키지에 포함된 `reproducibility/requirements.txt`는 기존 최소 replay 의존성 목록이며, 이번 검증은 전체 `ROUND09_ENVIRONMENT.lock` 환경에서 수행했다. 완전한 raw-input 재정량 replay를 새로 수행했다고 하지 않는다. 이 회차는 frozen quant 22표에서 specificity·native method를 재계산하고, 별도로 reader를 재구성하는 검증이다.

### Astra가 따라갈 표 연결

| 단계 | 기존 표 / 키 | 연결 의미 |
|---|---|---|
| 원 관측과 좌표 | `quant/summary.form_id`, `science/site_identity_audit.(form_id,site_id)` | 원 accession·position·sequence/FASTA hash, taxon, measurement group |
| 실제 비교 | `quant/comparisons.(form_id,contrast_id)` | `U_joint`, `P_joint`, `A`, reference/target joint run IDs; U_all/P_all과 별개 |
| 공식 서열 점수 | `science/specificity_scores.specificity_id` | actual window, matrix/background hash, raw score, percentile, selected 및 제외 사유 |
| 후보 연결 | `kinase/kinase_candidate_edges.edge_id` | `specificity_id`, 원 form/site/group, assay taxon과 미확정 enzyme taxon 분리 |
| 탐색적 기여도 | `kinase/substrate_contributions.contribution_id` | edge IDs·form IDs와 `specificity_A`; 여러 form/site가 요약된 값은 단일 form A와 같다고 하지 않음 |
| 공식 방법 입력 | `kinase/method_membership.method_membership_id` | candidate/contrast/group, 사용한 form/site 목록, native A rank, selected |
| 공식 방법 결과 | `kinase/method_scores.method_result_id` | membership IDs, Activity Score, method p/q, 충분/부족 coverage 상태 |
| 실행·해석 범위 | `kinase/method_executions`, `methods/method_registry.json`, `science/resource_registry.json` | 한 contrast 실행, 다른 contrast 미요청, 자원 및 입력 hash·null·parameters |
| 별도 최종 판정 | `science/inference_results`, `science/calibrated_calls` | exploratory method와 calibrated call을 분리; 기존 policy 유지 |

`reader/READ_ME.md`에서 위 resource → score → contribution → native membership → method 결과로 이동한다. `START_HERE_ASTRA.md`에는 실제 실행한 contrast, 평가 가능한 결과 수와 upstream activation 미실행을 표시한다. 선정되지 않은 점수와 적용 불가 Tyr 행도 원 점수 표에 남는다. 해당 행에 기여도 ID를 만들어 채우지 않는다.

## 최종 실제 실행 결과

최종 run: **`g0-cd1bc357e03640608c3fefcf444aa120`**. 패키지는 `codex-inputs/round09-20261009/execution/output/astra_analysis_package_g0-cd1bc357e03640608c3fefcf444aa120.zip`이다. 221개 manifest file, 79개 과학 표의 package validation이 통과했다. 전체 v6 실행 1,887.315초, temporal stage 1,239.294초다. Native 함수의 별도 runtime과 stage별 peak memory는 `ROUND09_RESULTS.json`에 기록한다. 이 시간은 합격 목표나 생물학적 정보 증가의 지표가 아니다.

실제 최종 패키지와 독립 공식 함수의 raw score·percentile 118,170행, native Activity Score/p/q 303행 및 membership 106,959행을 대조했다. 최대 절대 차이는 각각 **0**, 공식 selected mask와 native membership도 정확히 일치했다. 10,000 permutations·seed 1729이며 공식 모듈 미설치로 skip된 검사는 없다. 평가 가능 방법 결과 153개, coverage 부족 150개다. 확정 kinase call 수가 아니다. `calibrated_calls`는 0행, 기존 policy의 11,538개 call 행은 모두 no_call이다.

### 대표 연결: 선정·미선정·적용 불가

1. **선정된 Q32PX6 후보 T138 → assay label P38B**: `form_002ba74002edd12d` / `site_identity_8a2e375b06295a358288` / `measurement_634a69cc74b333473ee4`. 실제 window `GQAPITPQQG`, raw score `45.469129952909896`, percentile `97.76`, 공식 selected=true. `official_specificity_7b6b0a15fe9e0a37fc67` → `edge_3c8ad6aa48fc84443549` → `contribution_06a60bcc095b775225e2` → `native_membership_e9f735a49365b706dfdc` → `method_result_058c594cd6b0516bdcdd`. U_joint `0.16071049798753378`, P_joint `0.09975055329097415`, A 및 이 행의 contribution `0.06095994469656141` log2 단위다. Native result score `0.73311`, method p `0.18488`, q `0.37716`. 해당 결과는 여러 기질의 ranked enrichment이며 이 한 site로 계산한 enzyme activity가 아니다.
2. **같은 form/window의 미선정 AAK1 score**: `official_specificity_ceab8f6cd939980c53bc`, percentile `84.36`, selected=false, `official_percentile_or_rank_below_policy`. 원 score와 candidate edge는 보존하지만 이 행을 footprint contribution으로 승격하지 않았다. 기질 미선정은 AAK1 비활성의 증거가 아니다.
3. **Q5XIU9 후보 Y204**: `form_4d626ee8beb45f3f`, `site_identity_8bebbc82080e017ced0b`, `measurement_c75a362784a5ebb25742`. S/T 자원의 `unsupported_center_residue`이며 303개 미평가 score 행에 사유를 남겼다. 이 form은 S/T native rank·contribution에 들어가지 않는다. 같은 group의 T205(`form_fe4d7a2be8d9ec57`)는 실제 S/T form A `-0.541177573451165`로 연결된다. T205→ACVR2B의 `official_specificity_1c652e5c191c0b5fda3b` / `edge_08e4c3b6a6ecfe2a6824` / `native_membership_9bc914fb25175e355bb6`에서 이를 확인할 수 있다. Raw score `30.34400929969445`, percentile `99.63`. 별도 footprint `contribution_eb73359a09aaecde7dbb`는 T205를 공유하는 두 form/group의 기존 집계값 `-0.21653490297739553`이고, 단일 form A와 같다고 표시하지 않는다.

모든 사례에서 substrate taxon은 rat, assay taxon은 human이며 inferred enzyme taxon은 unknown이다. Localization은 unresolved다. 정확한 reference/target injection ID와 전체 row 대응은 `ROUND09_RESULTS.json`의 representative_lineage 및 로컬 `codex-inputs/round09-20261009/LINEAGE.csv` 1,769행으로 추적한다. 대표 선정은 안정 ID 순서와 경계 오류 확인 목적이며 insulin 경로를 우선한 결과 선정이 아니다.

### 보존과 의도된 차이

- 정량 **22개 CSV가 byte-identical**이며 form/site/contrast identity·값·NA·joint masks를 보존했다. 원 site identity audit와 15개 finding ID·순서·cards, 문헌 선택 pin·비교 pin·검색/출처/비교 표도 보존했다. 15개 중 이번 scope에서 점수화 가능한 form은 3개이며 다른 finding으로 교체하지 않았다.
- 79개 표 중 54개가 의미상 동일하다. 기존 338개 후보 profile 28,392행의 수치·NA·identity는 보존했고, 범위 밖 5개 contrast의 specificity 상태 1,690행만 `not_requested`로 명확히 했다.
- Assay label 303개 추가로 candidate 338→641, edge 50,568→168,738, contribution 11,832→13,408, profile 28,392→53,844로 바뀌었다. 신규 profile에는 미요청·결측 행이 포함되므로 이 행 수를 활성 kinase 수로 쓰지 않는다. Kinase temporal/fixed-membership/기질 제외 및 dependency 표는 새 후보를 반영한다. Emergence의 검출·수치는 보존되고 candidate 연결만 늘어난다. Coverage count, resource provenance와 reader metadata도 새 실행을 반영한다.
- 그림 코드와 회차 02·03 규칙은 변경하지 않았다. 기존 그림 관련 25개 파일 중 19개는 byte 동일하다. Coverage SVG/CSV는 새 근거 분모, kinase source/selection은 새 후보와 제외 행, detection source는 candidate 연결, legend는 source hash 변경을 반영한다. PTM·detection heatmap과 kinase/protein curve SVG·그린 point·시간 열 metadata는 그대로다.
- START_HERE와 READ_ME의 상대 링크 **65개**를 검사했다. 전체 원본 표는 계속 남으며 새 결과 링크는 기존 reader 자료에서 접근할 수 있다.

### 최종 검증 결과

| 검사 | 실제 결과 |
|---|---|
| 공식 adapter·scope·공유 S/T–Y 경계 회귀 | 9 passed, 0 skipped (27.54초) |
| 정량 fingerprint·membership 소비 및 회차 02·03 그림 회귀 | 15 passed (2.25초) |
| frozen 문헌 pin 재사용·손상 pin 거절·실패 시 current pointer 보존 | 1 passed (9.76초) |
| 실제 최종 패키지 official raw/percentile/selection/native p/q/member parity | passed, 최대 차이 0, `atol=rtol=1e-12` |
| 동일 외부 manifest/HDF5 + 패키지 자체 코드로 method replay | passed; 121,200 score rows, 303 native results, 106,959 membership rows; 10,000 permutations |
| 패키지 자체 코드의 frozen reader/literature replay | 15개 파일 byte-identical; network/LLM 0 |
| Reader 원본 연결 | source rows 16,944 / cards 14,658 / findings 15 검증 통과 |
| 정량·문헌·그림 보존 및 package schema/FK/hash | 통과; 의도된 변화는 위 표와 JSON에 분리 |

관련 pytest 최종 합계는 **25 passed**다. Pandas의 empty/all-NA concat 및 None/NaN equality 관련 FutureWarning이 있으나 수치 NA mask를 별도로 정확 비교했다. 공식 모듈 미설치 skip을 parity 통과로 세지 않았다. 이 결과는 전체 저장소 테스트나 운영 API/배포 검증이 아니다.

실제 archive hash, 코드 pin, 환경 pin, 전체 table 변화, 대표 row 연결, stage/runtime은 [ROUND09_RESULTS.json](ROUND09_RESULTS.json)에 있다. 실행 로그·전체 lineage·원본 자원은 로컬 `codex-inputs/round09-20261009/`에 보존하며 Git에는 코드·테스트·검증 스크립트·문서·환경 lock만 반영한다. 기존 입력 ZIP/PDF/DB/비밀 설정은 추가하지 않는다.
