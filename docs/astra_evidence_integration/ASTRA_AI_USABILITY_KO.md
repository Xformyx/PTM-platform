# Astra AI 활용성 개선 — 통합 검증

작업일: 2026-11-13~14 KST. 저장소 `Xformyx/PTM-platform`.
시작 HEAD/main/origin/main은 `fe11ff8472642fd896620b0027acf9a8e0bcae92`였으며
`codex/astra-ai-usability`에서 작업했다. 초기 tracked 변경은 없었고 기존 untracked
`codex-inputs/`를 보존했다. 적용할 AGENTS.md는 저장소와 상위 경로에서 발견되지 않았다.
과거 SHA로 reset하지 않았다. 사용자 확인 없이 회차를 연속 진행했다.

## 회차와 로컬 커밋

| 회차 | 로컬 SHA | 구현·검증 |
|---|---|---|
| AI01 | `81f89ac411ab00ee8e9f15360547d97db86fc592` | canonical effect scope/index/filter/숫자 시간순, 실제 저장 행 citation |
| AI02 | `563eec980f4dccd23b829df141532d23bdc8f5d7` | matched 주 효과와 post-reference quantity 분리, eligibility·cache |
| AI03-A | `c6e5f4879bbb553d9af2c3ee5485eb617904d287` | column/method별 semantics와 unknown 계약 |
| AI03-B | `6d70b27ccf481f064672d1fbb63fd5c53ad64775` | frozen 문헌 실행의 현재 상태 projection |
| AI04 | `91618dce2d77441cf6b6737b82a9e464d9419655` | archive 자체 reader-only entrypoint/replay |
| AI05 | `31d884422e7d1e4e37c71d12b2323c1ed2b47a8f` | native child의 신뢰된 bundled adapter bootstrap |
| AI06-A | `1034ce52059cc244f11d054cf540b5bdb0dace08` | bounded bundle/continuation/동일 세션 source validation |
| AI06-B | `dd079bf34b921161166edeb2acb3e80de87b536b` | structured claim anchor/value/scope/restriction 검사 |
| 통합 호환 수정 | `e02b8650626d503bea3296fdc9131d8a1472a298` | M4 guide 산출물, pre-C03 설명/코드 snapshot, 실제 reader revision |

통합 수정은 위 회차에 이어 별도 커밋했다. 이 문서를 포함하는 최종 보고 커밋은
`git log -1 --format=%H -- docs/astra_evidence_integration/ASTRA_AI_USABILITY_KO.md`로 확인한다.
자기 자신의 SHA를 파일에 넣기 위해 커밋을 반복하지 않는다.

## 구현 자산과 변경 경계

- `astra_evidence_catalog`: 기존 index/source/evidence ID를 유지하며 실행 snapshot의
  `effect_series.resolve_series`를 연결했다. v2 catalog/cursor는 새 scope/정렬에 결합된다.
- `contrast_quantification.detection_by_arm`: 기존 ContrastEstimator와 실제 mask/unit을 재사용한다.
  independent target units가 확인된 범위만 post-reference를 제공한다. Control-target paired를
  cross-time pair로 바꾸지 않는다. unknown/unsupported는 부가 track null+이유다.
- `astra_plan`: detection의 effect_scope/code 의존성을 quant fingerprint에 포함한다.
  주 U/P/A 추정량을 새 엔진으로 바꾸지 않았다.
- `quantitative_fields`, `astra_execution_status`: writer/reader/bundle/claim의 공통 정의와
  현재 상태를 제공한다. 과거 실행 비용·출처와 이번 frozen reuse 비용0을 구분한다.
- `astra_reader_replay`, 기존 repository CLI, `seal_archive`, `astra_reader_revision`:
  새 reader entrypoint와 immutable 발행 경로를 공유한다. 원본 archive를 수정하지 않는다.
- `official_method_tracks.adapter_command`: 현재 모듈의 __file__ 기반 신뢰 code root,
  -I/-B bootstrap과 구조화한 argv를 사용한다. method version/seed/permutations 유지.
- `astra_evidence_bundle`, `astra_claim_check`: 기존 catalog/session/typed citation과 field
  contract를 재사용한다. 새 검색 DB·LLM·자연어 의미 승인 엔진은 없다.

## 통합 중 발견한 연결 오류와 수정

1. M4 revision에서 현재 상태로 바뀐 `LITERATURE.md`가 writer 반환 artifact 목록에 없었다.
   실제 실패 assertion을 확인하고 변경된 guide를 명시적으로 기록했다. 별도 replay 출력에서는
   원 guide를 가져와 같은 marked status block을 투영한다. START_HERE도 과거 안내를 복사하는
   대신 해당 revision의 readiness/current execution을 표시한다.
2. 실제 G11 원본의 temporal validator 실패를 저장 행으로 비교했다. 차이는
   `interpretation_limits[4]`의 pre-C03 공통 reference 설명 문장 **1개**뿐이었다.
   그 정확한 구형 문구를 matched/effect-extension이 없는 archive에서만 허용한다.
   다른 문구·수치/row count 변조는 계속 거부한다. 숫자 허용오차를 넓히지 않았다.
3. v1→v2 catalog scope/order로 다시 생성되는 typed literature **계획표**를 고정된 실행 결과로
   취급하던 revision 보존 검사를 수정했다. 계획표는 writer의 reader 산출물로 기록하고
   실행 pin·검토 결과·승인 상태는 보존한다.
4. pre-C03 실제 code snapshot에 effect_series/control_comparison/display helper가 없었다.
   reader revision은 필요한 누락 모듈만 추가하고 기존 scientific module snapshot은 보존한다.
   구형 모듈 배치의 별도 작은 fixture와 외부 cwd import/replay로 검증했다.

실제 자료의 첫 실패는 복사 전에 발생했다. 이후 실패 후보는 성공 pointer로 노출하지 않았다.
대형 원본을 반복 복사하지 않기 위해 task가 만든 미발행 후보 하나를 재사용했다.
검증 harness가 `_copy_package` 부분만 그 후보로 연결하고 원 manifest의 보호 파일을 재검증했다.
새 consumer_run_id만 바뀐 문헌 binding은 별도로 확인했다. 재시도 시 task 복사본의 작은 code
파일만 원 snapshot으로 복원했다. resolver/reader/validator/seal/ZIP/pointer는 production 함수다.
원 source/archive/pointer/실제 과학 계산을 대역으로 바꾸지 않았다.
검증 harness의 후보 경로가 상대 경로였던 탓에 한 번은 ZIP sealing 후 pointer 작성에서
실패했다. production 함수의 absolute-root 계약에 맞춰 수정하고 미발행 후보의 작은 생성
metadata/code만 복원해 다시 실행했다. 이 과정에서 후보 ZIP을 다시 seal했으며 원본 대형
입력/패키지를 다시 복사하지 않았다. 해당 harness 오류와 production 연결 오류를 구분한다.

## 검증 수준과 보존 계약

합성: reference ID 사전순과 시간을 뒤섞은 matched scope, 다른 시간 grid, mixed pairing,
tie/null/arm/family, page/byte budget, tamper/duplicate key, unselected/withheld/no-call 접근,
값·부호·NA·단위·시간·Control·method/biological q 제한을 production 함수로 검증했다.
예시 log fixture의 matched A=1,2와 지원되는 target-post track=0,2를 구분했다.
새 통계 검정이나 matched interval interaction을 구현하지 않았다.

실제 저장 자료: G11 공통 Control archive를 사용했다. actual time-matched 자료, 운영 UI/API/DB/queue,
새 scientific run은 검증하지 않았다. 기술 주입·biological unit·pair 선언은 원 snapshot 그대로다.
새 reader는 과거 detection을 재계산하지 않으며 버전 없는 post-reference 필드는 legacy unknown이다.

과학 표가 동일한 경우 value/NA/ID/mask뿐 아니라 원 CSV bytes/hash를 비교한다.
변경 허용 대상은 catalog/index/reader packet·guide·계획 projection/dictionary/code snapshot/
revision provenance 및 새 consumer binding이다. source/literature pin과 기존 성공 ZIP/pointer는 불변이다.
new catalog_id는 새로운 reader lineage이며 과거 citation을 현 run/catalog로 소급 변환하지 않는다.

원 G11 ZIP hash: `862be7cbefcd42c24769ea0a6530bc6ba2b1f0fb2f4fa22931d1886e727f19af`.
원 성공 pointer hash: `a8ef7ab4d97a47b731ed7d88797b71c34534103c2a7d746715df2d506dcff7ef`.
원 comparisons hash: `0936a28fab025b60255290ce4652a1f7274279740a536824b7802dadfa3b3875`.
원 method_scores hash: `bac9ec3ce979ced99aee840471afef057cefda197f5c9a8076e3c71045359ccd`.

## 실행 경계

실제 신규 과학/PhosX 계산 0회, 실제 신규 검색/RAG/LLM 호출 0회.
합성 테스트는 기존 작은 과학 함수를 실행하고 검색/모델은 fixture 대역을 사용했다.
합성 함수 호출 누적 횟수는 계측하지 않았으며 테스트 수와 호출 수를 혼동하지 않는다.
native 가짜 adapter 검증은 bootstrap 검증이다. 실제 restricted 자원의 PhosX 수치 parity나
full scientific replay를 검증했다고 주장하지 않는다. 실제 reader revision은 원 scientific code를
유지하므로 full replay가 현재 native bootstrap으로 업그레이드되었다고 주장하지 않는다.

별도 서비스·worker·queue를 시작하지 않았다. push/merge/배포/flag 변경 없음.
기존 caffeinate PID 2450/5292는 이번 작업 이전 프로세스이며 변경하지 않았다.

## 상세 보고서와 측정 자료

- [AI01 catalog](ASTRA_AI01_CATALOG_KO.md)
- [AI02 detection](ASTRA_AI02_DETECTION_KO.md)
- [AI03 semantics/status](ASTRA_AI03_SEMANTICS_KO.md)
- [AI04 reader replay](ASTRA_AI04_READER_REPLAY_KO.md)
- [AI05 native bootstrap](ASTRA_AI05_NATIVE_REPLAY_KO.md)
- [AI06-A bundle](ASTRA_AI06A_BATCH_ACCESS_KO.md)
- [AI06-B claims](ASTRA_AI06B_CLAIM_CHECK_KO.md)

측정 로그/실제 산출물은 `codex-inputs/astra-ai-20261113/`에 분리했다.
전후 benchmark는 동일 실제 저장 6행이다. bundle은 정의/상태를 포함해 출력 bytes가 증가했다.
읽기 횟수·토큰 절감·연구 성능 개선을 추정해서 보고하지 않는다.

## 실제 저장 자료의 통합 결과

새 revision: `g0-68d1310ef31a4f32bd164725daac1a1d`.
경로: `codex-inputs/astra-ai-20261113/actual reader revision/`.
새 ZIP: `astra_analysis_package_g0-68d1310ef31a4f32bd164725daac1a1d.zip` (381,082,051 bytes).
SHA-256: `f834248142d9dfe2933dea117d9414d7e2f35926e0ca6153bbf571f4ec2e6827`.
별도 출력 root의 새 pointer와 ZIP hash가 일치한다. 기존 G11 pointer는 그대로다.
273개 manifest 파일의 ZIP 내용을 추출하지 않고 stream hash로 모두 검증했다.
과학 표·그림·pin 101개는 원본 hash와 동일하다. 기존 CSV bytes가 같으므로 value/NA/ID/mask도 같다.
PR/PG/FASTA 로컬 원본 hash도 원 provenance와 각각 일치했다 (`actual_input_hashes.json`).

catalog 표현 **175,537개 evidence ID 전체**가 보존됐다. 이는 독립 관측 수가 아니다.
구 catalog_id `f0e81360579948b76934dd645bf9008992788805bc77933e41f67c0cb45c11ef` →
새 catalog_id `fbc6543bc6fe8fcc7229f6833fb16c6b6a21c184d1d1a80a510782427db82a29`.
대표 form `form_c856a65cb819ac45`, series `series_8bcf2a244a036b564b4c`의 6행은
실제 metadata에서 읽은 1/5/15/30/60/180분 순서로 조회·bundle·resolve됐으며 원 값/NA/key와 같다.
이는 실제 공통 Control 자료의 관측 시간이다. production 시간 목록을 하드코딩하지 않았다.
반올림을 선언한 A 주장 6개가 통과했고, 잘못된 Control과 과거 catalog anchor의 소급 사용은 거부됐다.
기계적 통과 후 의미 검토는 not_performed다. 원 v1 catalog에서도 기존 run 소속의 실제 A 인용이 통과했다.

비선정 행과 실제 no-call에 접근했다. 대표 질문 `BQ-001`의 범위는 57개 표현이며,
한 응답에서 5개만 전달하고 continuation으로 나머지를 남겼다. 이 제한은 전체 분석 범위가 아니다.
bundle/reader/readiness/START_HERE의 현재 문헌 상태가 같다. M4 요청3·비교3·전체partial,
17구간/5문서/독립 외부논문4, 제안0·승인0과 이번 frozen consumer query/model0을 유지한다.
selected-finding scope는 별도로 15개 비교·28구간·6문서와 원 실행 비용을 보존한다.
선정 문헌의 별도 consumer 비용이 미기록이면 null을 유지하고, 이번 reader projection 비용0과 구분한다.

구 archive 자체 replay는 257개 manifest 파일을 검증했고 고유 reader 파일40개가 byte-identical이었다.
새 revision은 저장소 밖 `/tmp` cwd, PYTHONPATH 없이 `-I -B`의 새 interpreter로
archive 자체 `reader_replay.py --output <new-directory>`를 실행했다.
273개 manifest 파일의 hash/size와 source 파일 목록이 전후 동일하며, 해당 revision의
고유 reader 파일 **27개 모두 byte-identical**이다. 원 archive의 40개와는 revision별 재생성 범위가 다르다.
실제 import한 reader 경로는 새 archive의 `reproducibility/code/ptm_shared/astra_reader.py`였다.
M4 frozen 복원 true, repository_code_used false, 과학·network·model 신규 호출0이다.
결과: `codex-inputs/astra-ai-20261113/actual revision replay/READER_REPLAY_VALIDATION.json`.

고유 테스트는 **117개**, 각 test ID의 최종 실행 상태는 모두 passed, skip 0이다.
중간 실패를 숨기지 않았으며 원인 수정 후 같은 경계가 통과했다. XML을 반복 합산하지 않았다.
`TEST_RESULTS.json`에 고유 ID와 단계별 XML을 기록했다. 전체 과학/native/대규모 offline suite와
frontend build는 실행하지 않았다. frontend 변경이 없으며 실제 과학 재계산은 범위 밖이다.

최종 측정 여유 공간 **24,300,998,656 bytes (약 22.63GiB)**, 이번 task의 logical 파일 크기
**5,448,584,261 bytes (약 5.07GiB)**로, 시작 시 정한 20GiB reserve / 추가 6GiB 예산 안이다.
실제 원본과 ZIP을 삭제하지 않았고 새 산출물/실패 로그/검증 scratch는 task 폴더 안에 분리했다.
작업 Python/replay 프로세스는 모두 종료했다. 기존 caffeinate 두 개만 유지했다.

최종 결과 요약: [ASTRA_AI_USABILITY_RESULTS.json](ASTRA_AI_USABILITY_RESULTS.json).
AI01–AI06-B의 로컬 구현·가능한 합성/저장 표/오프라인 검증을 완료했다.
실제 matched 자료, 운영 end-to-end, actual native scientific parity는 미검증이다.
이는 자료/범위의 한계이며 필수 테스트 실패를 숨긴 상태가 아니다. push/배포/flag 변경은 수행하지 않았다.
