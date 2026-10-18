# g11 후속 회차 01 — 고정 M4 결과의 일반 발행 연결

## 범위와 기준선

회차 01만 구현했다. 신규 실제 RAG/LLM 실행, 정량·PhosX·temporal 재계산, reference 수집, 인용 validator 변경과 회차 02 이후 작업은 하지 않았다. 운영 Order 89·운영 DB·UI·Celery를 직접 검증한 결과로 확대하지 않는다.

착수: `main`, `ceaf1eb7027baa81ecf3df1e24ae05020d70552f`. M4 커밋 `4d4b834b401848aca07104acab9e8fcbfe5b6a99` 포함을 확인했다. 기존 미커밋 `codex-inputs/`와 입력·성공 ZIP은 보존했다. 적용 범위의 AGENTS.md는 발견되지 않았다. 원격 fetch/push, 배포, flag 변경은 수행하지 않았다. 로컬 완료 커밋 SHA는 최종 응답과 `codex-inputs/g11-followup-01/LOCAL_COMMIT.json`에 기록한다.

실제 기준 ZIP은 Downloads의 `astra_analysis_package_g11-9d1d38e402834cabb8a423e9233df19d.zip`이며 SHA256은 `58ab453b60b31d033b6f87cda23847c141a986520a5ec76476a83b203a743de4`이다. 251개 manifest 대상의 bytes/hash를 검증한 후 별도 폴더에 풀었다. 조사한 핵심 9개 ptm_shared 파일은 g11과 착수 HEAD가 byte-identical이었다. 현재 소스를 g11로 되돌리지 않았다.

M4 원 실행 패키지 `g0-febc02fcaa0b43c0ac9cd973730a7a3b`와 고정 pin이 실제 존재한다. 원 ZIP SHA는 `b48fc46c4f8fd62193b14068ddd80cd6ccf8f1aa4c334ec6cc735275e2a0e1eb`, pin의 semantic SHA는 `cc40cc142efb241631a94f85af7b5ef93da23fbf349402cb59be60046cbc540c`다. M4 코드 부재가 아니라 일반 builder/replay에 pin 전달이 빠졌던 문제였다.

## 기존 함수와 최소 변경

| 기존 자산 / 경로 | 확인된 경계와 이번 연결 |
|---|---|
| Order JSON → `_updated_analysis_context` → `prepare_astra_inputs` → `_attach_enrichment_free_profile` | 기존 analysis_context에 명시적 요청을 저장/전달. 새로운 DB·서버 경로 입력은 추가하지 않음. |
| `run_primary_analysis` → v6 `run` → `run_astra_analysis` | 원래 엔진 dispatcher 유지. 기본 catalog 준비 뒤 별도 문헌 단계에서 요청을 처리. |
| `EvidenceCatalog`, `resolve_subjects`, `replay_review`, `project_review` | stable subject/source key와 실제 사용 원본값·study/question을 대조. 요약 findings로 fallback하지 않음. |
| `execute_review`, 기존 `cached_stage` / `_runtime` / `_export_result` | 명시적 실행 모드만 기존 계산 함수를 호출. 이번 실제 검증은 전부 frozen reuse; 이 계산 경계는 fixture로만 검사. |
| `attach_review_execution`, `write_review_execution`, `write_reader` | packet, 실행표, 링크, summary, 안내, dictionary/catalog를 동일 투영으로 갱신. writer는 검색하지 않음. |
| `validate_package` → `seal_archive` → current pointer | 요청 시 필수 산출물·packet/binding·완료 범위 검증. 실패는 pointer 교체 전에 예외 처리. |
| `recorded_run` → `get_enrichment_free_evidence` → `FileResponse` | 기존 Results 핸들러와 hash 검증 사용. 별도 다운로드 API 없음. |
| `revise_temporal`, `revise_literature`, `replay_package`, `replay_astra_reader.py` | 기존 M4를 누락시키지 않고 frozen 투영 복구. revision은 소비 run provenance만 변경. 문헌 선택 변경으로 기존 실행을 새 corpus 결과로 조용히 바꾸는 경로는 차단. |

Production 변경: `api-server/app/api/orders.py`, `ptm_shared/astra_literature_review.py`, `astra_package.py`, `astra_reader.py`, `astra_reader_revision.py`. 기존 replay CLI를 확장하고 `test_g11_subject_delivery.py`, `validate_g11_subject_delivery.py`를 추가했다. 새 과학/검색 엔진이나 cache/scheduler는 만들지 않았다. generation trace·quote/scope/context validator·export policy는 유지했다.

## 요청·재사용 계약

`analysis_context.literature_subject_review`는 `not_requested`(기본), `reuse_frozen`, `execute`를 구분한다. 실행/재사용은 `requested_subject_ids`, `request_reason`, `max_subjects`, `budget.max_queries/max_model_calls/max_prompt_bytes`가 필요하다. 재사용 참조는 `pin_ref.run_id/sha256`뿐이며 임의 파일 경로를 받지 않는다. 기존 권한 확인 후 같은 Order의 `enrichment_free_runs` 아래 등록된 manifest/pin을 해석한다.

pin hash/schema, 요청 대상, source FK/value hash, 원 source archive와 현재 typed input·연구 조건·질문, 문헌 선택/corpus, 원 실행 model/prompt/code provenance와 예산을 검사한다. 과거 frozen 재현은 현재 모델을 사용하는 새 계산 cache 적합성과 다르다. 원본값이나 명시된 immutable corpus가 달라지면 거절한다. M4 설정은 문헌 단계 fingerprint에만 들어가며 기존 과학 fingerprint는 유지한다. 자기 manifest를 fingerprint에 넣지 않는다.

g11은 collection39/doc96–102의 카탈로그이고 M4는 local collection1/doc1–7의 immutable index이다. **7개 문서 SHA가 모두 같지만 DB ID와 corpus 식별자는 다르다.** 명시적 frozen reuse에서만 정확한 문서 bytes 대응을 기록하고, 원 pin의 immutable corpus/model/export provenance를 유지한다. `current_index_verified=false`, `new_execution_cache_compatible=false`다. 운영 index를 검색했다거나 현재 권한을 새로 확인했다고 표시하지 않는다. 원 corpus hash는 `8feb2aed15b1be487a940a20033c8b8df233601a73ff09301e5a91b9ba6382f6`이다. 원 실행 contract의 세 코드 hash와 adapter hash는 원 M4 archive 코드와 일치함을 별도로 확인했다.

`references/literature_subject_binding.json`에 요청/실제 mode, source/consumer run, pin·선택·계약 hash, 문서 대응, 현재 호출 비용과 요청/전체 상태를 기록한다. 기존 pin은 변경하지 않는다. 요청 5개가 완료돼도 전체 158,593개 표현 중 일부이므로 전체 상태는 partial이다. 계획 CSV의 not_requested는 자격 계획 상태이며 M4 실행표가 실제 실행 상태의 권위다.

## 실제 재사용 대상과 의미

| 대상 / subject ID | 원본 의미와 요청 사유 |
|---|---|
| MAPK1 / `review_subject_55b247e34a7048934295` | 미선정 observation; 요약 밖의 원본→문헌 연결 전달 확인 |
| GSK3A / `review_subject_093b33f4f8cff43355e7` | 미선정 observation; 자체 PTM을 효소 활성으로 바꾸지 않음 |
| MAPK3 / `review_subject_70c0a0b67f80c422c6c9` | raw-only/primary 제외; 원본 제한 유지 |
| PTPRK / `review_subject_9aaa70207efe64e6c61a` | protein abundance; PTM/activity와 구분 |
| AKT1 / `review_subject_6f2b7a781153897eb7b2` | PhosX insufficient_coverage; no-call 제한 유지 |

이번 요청 사유는 기존 결과의 일반 발행 전달 검증이다. 원 실행 대상별 request_reason은 pin/실행표에 그대로 남고 새 소비 요청 사유는 binding에 따로 남는다.

고정 기록에는 5개 comparison 실행, 고유 문서 6개(외부 논문 5개와 방법 메모 1개), 고유 반환 구간 21개가 있다. 제안/anchor 승인/의미 승인은 0이다. 원 full 단계의 current_cost는 queries13/model4이며 앞선 파일럿 한 대상을 cache로 재사용했던 과거 기록이다. 이번 소비의 신규 실제 검색·모델·외부 네트워크는 각각 0이다. 논문 전체를 읽음, 독립 검증 또는 현재 실행의 새 비교 성공으로 해석하지 않는다. 모델 입력 구간 수는 이번에 재계측하지 않았다.

g11의 기존 15개 findings·28개 문헌 구간·71개 제외 기록은 원 파일 bytes로 보존한다. **71개 과거 trace의 정확/부분/불가 재구성 감사는 이번 회차에 수행하지 않았으며 0건 해결했다고도 주장하지 않는다.** 회차 02의 별도 범위다.

## 검증 범위와 재현 명령

`validate_g11_subject_delivery.py`는 실제 g11 저장 표를 기존 계산/cache 경계의 test double로 공급한다. 과학 재계산이나 새로운 cache-hit 성능 측정이 아니다. API dispatch attachment, JSON queue 형태, 실제 worker 엔진 dispatcher, 일반 builder, seal/pointer, 실제 Results 다운로드 핸들러를 실행한다. DB record·권한·Celery 운송은 격리된 double이므로 운영 UI E2E와 구분한다. 다운로드는 경로 확인에 더해 실제 FileResponse의 ASGI body를 파일로 받아 ZIP SHA/크기를 대조한다.

원본 과학/adapter 표를 다시 직렬화하는 test double은 원 DataFrame과 값·NA·순서의 정확 일치를 확인한 뒤 원 CSV bytes를 보존한다. 원 ZIP과 성공 결과는 수정하지 않는다. 신규 결과만 별도 output root에 생성한다. 과학 표·그림·원 pin의 파일별 hash는 결과 JSON에 기록한다.

```sh
PYTHONPATH=.:workers:api-server MPLCONFIGDIR=/tmp/ptm-g11-mpl \
codex-inputs/round11-20261010/runtime/bin/python scripts/validate_g11_subject_delivery.py \
  --source codex-inputs/g11-followup-01/baseline \
  --pin-package codex-inputs/full-evidence-m4/final/revision/enrichment_free_runs/g0-febc02fcaa0b43c0ac9cd973730a7a3b \
  --output codex-inputs/g11-followup-01/integration-final
```

기존 output을 덮어쓰지 않으므로 재실행에는 새 output 경로를 사용한다. 새 패키지의 자체 코드로 `scripts/replay_astra_reader.py`를 실행한다. 네트워크를 차단하고 저장 표·고정 pin에서 reader를 재구성하며 scientific/method numerical replay와 구분한다. 일반 `replay_package`의 M4 전달은 과학 계산 double을 사용한 좁은 fixture로 검사한다.

관련 suite는 **고유 42 passed, 4 deselected, skip 0**이다. 4개는 과학 전체 실행을 포함하는 테스트여서 의도적으로 제외했다. 반복 실행 횟수를 합산하지 않았다. 요약 0/5/15/50, 신규 실행과 frozen reuse 분리, 미요청 호환, pin/source/FK/선택 오류, 필수 산출물·context binding 누락, 불완전 요청의 이전 pointer 보존, writer/일반 replay 전달, 기존 full-reader/temporal/문헌 export 경계를 포함한다. 실제 검색은 fixture 결과와 구분한다.

최종 run/ZIP SHA, 실제 다운로드·replay와 보존 파일 수는 아래 최종 검증 절 및 `G11_FOLLOWUP_01_RESULTS.json`에 기록한다. 원시 데이터·PDF·DB·내부 원문 trace·ZIP은 커밋하지 않는다.

## 남는 범위

운영 release·Order89 저장값·실제 UI→DB→Celery 경로는 미확인이다. 실제 RAG/LLM의 일반 경로 실행은 회차 04, 71개 제외 원인 감사와 진단/최소 수정은 회차 02–03에 남긴다. 현재 corpus 접근 성공이나 의미 검토·kinase 활성·localization·독립 생물학적 검증을 이번 frozen 전달로 입증하지 않는다. 문헌 선택을 바꾸면서 기존 whole-subject 결과를 유지하려면 별도의 명시적 subject review 요청이 필요하다.

## 최종 검증 기록

- 일반 builder run: `g0-b992dc7f962f445f8536c4d8da876292`.
- ZIP SHA256: `5406f564b091c8b8b9cdb2e2f66f45552c4d574a79472a4675f8e5258f5e8ce0`. 실제 FileResponse body **384,149,393 bytes**와 pointer의 archive hash가 동일하다.
- ZIP: `/Users/josephk/Projects/PTM-platform/codex-inputs/g11-followup-01/integration-final/order/astra_analysis_package_g0-b992dc7f962f445f8536c4d8da876292.zip`.
- reader: `/Users/josephk/Projects/PTM-platform/codex-inputs/g11-followup-01/integration-final/order/enrichment_free_runs/g0-b992dc7f962f445f8536c4d8da876292/reader/LITERATURE_SUBJECT_REVIEW.md`.
- 처리 시간: 551.724초. 과학 계산이 아닌 저장 표 staging/검증/봉인/다운로드/reader replay 시간이다.
- 기존 manifest 251개 중 **222개 byte-identical, 29개 의도적 변경, 6개 추가, 삭제 0**. 기존 과학·adapter·그림·문헌 pin/결과의 지정 보존 파일 **113개**, 정량 **22 CSV**, 그림·원자료 **31개**의 hash가 같다. 원 g11 ZIP과 원 M4 ZIP hash도 재확인했다.
- 변경 허용 파일은 reader packet/catalog/안내, 새 M4 5개 산출물과 binding, 실행 context/snapshot/계획/전달 manifest, 코드·환경·stage provenance/readiness이다. 전체 파일별 diff는 결과 JSON에 있으며 과학 표·기존 문헌 결과·선정 결과는 변경하지 않았다. `methods/software_versions.json` 차이는 로컬 검증 환경 기록이며 방법 재실행이 아니다.
- 새 ZIP의 자체 코드 reader replay: **고유 40개 산출물 byte-identical**, 14,658 카드·15 findings·16,944 원본 행의 값/NA/시간/ID 검증 통과. 상대 링크 **112개**가 패키지 내부 실제 파일로 연결된다.
- 기존 `revise_temporal(review_plan_only=True)`를 통한 고정 재생성 run: `g0-7b1846d72384411eb63f741e872473d2`. M4 pin·표·과학 결과를 유지하고 소비 run binding을 갱신했다. 새 검색/모델/과학 호출 0회. 이 재생성본의 자체 코드 replay **16개 고유 산출물 byte-identical**. 일반 builder 검증을 이 revision 결과로 대체하지 않았다.
- 첫 개발 검증 run `g0-d142671b054b4a1da997b2c933a8b674`도 별도 보존했다. 이후 context binding 누락 검사와 provenance/안내 보강, 실제 응답 body 검사를 포함한 위 최종 run을 기준으로 삼는다.

회차 01의 구현과 로컬 고정 전달 검증을 완료했다. 실제 운영 UI/DB/Celery 및 새 RAG·모델 일반 실행은 미확인이다. 회차 02 이후로 진행하지 않았다.
