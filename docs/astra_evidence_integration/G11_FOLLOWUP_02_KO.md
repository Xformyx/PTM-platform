# g11 후속 회차 02 — 과거 제외 기록 감사와 다음 실행의 진단

## 범위와 기준

회차 02만 수행했다. 착수 HEAD는 `main`의 `5cb693eaff74698acd4d51986ddae4f1d8c87f15`이다. M4 커밋 `4d4b834b401848aca07104acab9e8fcbfe5b6a99`가 포함되어 있다. 기존 미커밋 `codex-inputs/`, 성공 ZIP, pin, source/cache는 보존했다. 저장소·상위 경로에서 적용 AGENTS.md는 발견되지 않았다. 작업은 2026-10-18에 시작하여 10-19에 검증했다.

원본 g11은 `g11-9d1d38e402834cabb8a423e9233df19d`, ZIP SHA256은 `58ab453b60b31d033b6f87cda23847c141a986520a5ec76476a83b203a743de4`이다. 회차 01의 일반 발행 run `g0-b992dc7f962f445f8536c4d8da876292` 및 SHA `5406f564b091c8b8b9cdb2e2f66f45552c4d574a79472a4675f8e5258f5e8ce0`를 비교했다. 실제 운영 Order/DB/UI/큐나 서버 내부 trace는 직접 확인하지 않았다.

이번에 신규 실제 RAG 검색, LLM 호출, 정량·PhosX 재계산, reference 수집, 외부 corpus 수집, push·배포·flag 변경은 하지 않았다. 합성 retriever/model/HTTP 응답은 실제 실행 수에 포함하지 않는다. 과거 frozen 결과의 발행·replay는 새 문헌 판단 검증과 별개다.

## 71개 과거 기록의 회계와 재구성 범위

감사 대상은 **기존 선정 findings 문헌 pin** `references/finding_literature_pin.json`이다. 별도 M4 `literature_subject_execution_pin.json`의 5개 typed 실행은 섞지 않았다.

| 항목 | 실제 확인 |
|---|---:|
| finding 수 | 15 |
| 제외 기록 | 71 |
| quote_not_in_retrieved_chunk | 68 |
| scope_identifier_absent_from_quote | 3 |
| 고유 source content hash | 28 |
| 정확히 재구성 가능 | 0 |
| 일부 단계 재구성 가능 | 3 |
| 과거 trace 부재로 판별 불가 | 68 |
| 실패 원인을 확정한 항목 | 0 |

`G11_FOLLOWUP_02_EXCLUSION_AUDIT.csv`에는 finding_id, 0부터 시작하는 기존 exclusion ordinal, source_index, 최초 사유, 원 실행 request/input/output hash와 저장 coverage 대응을 71행 모두 남겼다. locator는 감사용 경로이며 과거 proposal ID가 아니다. 저장되지 않은 quote/proposal/hash는 채우지 않았다. source_index는 요청별 위치이며 영구 출처 ID가 아니다. coverage와 index의 대응은 원 코드/저장 순서에 근거하지만, 최종 prompt 원문이 없으므로 prompt 순서까지 직접 검증했다고 하지 않는다.

원 pin semantic SHA: `da2df0842e16a222717fd2416909de5ff1e594d5a3dbddfb297808017d076f39`.
원 stage request SHA: `dcab5f7cc58de8ccc61e775e07cfa5527cad28bf043e79bebf4ac9376596003b`.
당시 모델은 Ollama `gemma3:27b`, prompt `finding_comparison.v6.2`다. 이 실행의 cache 상태는 `not_cached / index_version_not_immutable`이다. 이전 M4 검증의 Qwen 모델 결과와 혼동하지 않았다.

접근 가능한 `codex-inputs`의 JSON/log·stage cache와 기존 내부 index snapshot을 request/input/output hash로 조사했다. 관련 `/private/tmp/ptm-round11-20261010` 및 회차 01 검증 로그도 대조했으며 동일 과거 raw trace는 찾지 못했다. 조사 경로/파일 hash는 결과 JSON에 남겼다. 모든 운영 저장소에 trace가 없다는 결론으로 확대하지 않는다.

`finding_852f4b96ec652776a5b8`의 ordinal 0/1/2는 본문 SHA `c7324e4af73ab5b38d4c7615011164a6aef43c5e1d6ab2037f57d3f15f703189`에 연결된다. 기존 로컬 snapshot에서 **본문 bytes hash가 같은 한 구간**을 찾았다. DB/collection ID가 동일하다는 뜻은 아니다. 최종 prompt·provider output·proposal이 없으므로 이 세 건도 scope 거절 원인을 재판정하지 않았다. 나머지 68건은 대응 원문까지 복구되지 않았다. 새로운 검색은 수행하지 않았다.

원본 g11과 회차 01의 `literature_pin`, `finding_literature_pin`, literature search/source/comparison CSV는 byte-identical이다. 승인 0건은 원래 상태로 유지하며, 과학적 불일치나 모델 환각을 입증하지 않는다.

## 재사용과 최소 변경

| 기존 경로 | 회차 02 변경 |
|---|---|
| `run_astra_analysis → collect → retrieve_finding_literature` | 실제 run/stage request를 진단 context에 전달. 기존 카드/adapter 키와 M1 `evidence_id_for`를 사용. |
| `run_requested_review → execute_review → retrieve_finding_literature` | 기존 typed subject/evidence/source key를 동일 진단 계약으로 전달. frozen reuse는 이 함수를 실행하지 않음. |
| `_prompt_observation`·기존 source dedup | 기존 prompt와 순서를 유지하고 prompt 직전 source map/hash를 고정. 응답 해석 후 source 재정렬 없음. |
| `capture_generation / record_generation_event`·`LLMClient` | 실제 전송 body와 transport attempt, 응답, finish/usage를 기록. header·API key·endpoint 설정은 기록하지 않음. |
| `parse_model_json` | 동일 parser 사용. raw output hash, parse 성공/실패, schema 실패, 빈 comparisons를 구분. |
| 기존 approval 표현식·`quote_binding_failure` | 승인 표현식 그대로 유지. 모든 gate의 설명과 typed site 금지/빈 gene 사유를 추가. |
| `_export_result` | 기존 source 반출 정책 유지. 새 진단의 외부 표현을 명시적 allowlist로 제한. |
| 기존 stage cache / generation trace | 실패 비교는 complete cache에 남지 않을 수 있어 내부 trace의 별도 immutable 저장을 기존 cache 디렉터리에 연결. 실행 cache나 검색 엔진을 새로 만들지 않음. |

Production 변경은 `ptm_shared/finding_literature.py`, `astra_literature.py`, `astra_literature_review.py`, `astra_package.py`, `astra_reader_revision.py`, `workers/common/generation_trace.py`, `workers/common/llm_client.py`다. 추가 감사 script와 focused tests는 이 경계 검증용이다. 새 diagnostic schema는 `finding_comparison_diagnostics.v1`이며 prompt/승인 정책 버전은 그대로다. 관련 코드 hash도 진단에 기록한다. 새 실행의 문헌 code fingerprint는 달라지지만 정량·PhosX 설정을 바꾸지 않는다. 과거 pin은 원 contract로 frozen 재현한다.

## 다음 실행의 추적·반출 계약

각 record의 `comparison_diagnostics`는 run/stage/request, 독립 attempt ID, finding/typed subject, 실제 source row refs, source_index→collection/version/source_id/content hash, prompt/output hash, model/provider/prompt/code provenance, parse와 proposal ordinal/hash, 첫 거절 사유 및 전체 gate 결과를 연결한다. 본문 길이/위치, exact span offset, 다른 prompt source에서만 발견된 인용 여부도 내부에 남긴다. 다른 source의 일치는 진단일 뿐 자동 출처 수정/승인에 쓰지 않는다.

최종 provider request body와 validator prompt의 hash를 비교해 transport 차이를 표시한다. provider finish reason이 length/max_tokens이면 truncation observed, 알려진 정상 종료이면 provider가 잘림을 보고하지 않았다는 상태, transport가 없으면 unknown이다. 이를 원문이 완전하다는 독립 증거로 쓰지 않는다. JSON 실패, 빈 배열, 검증 거부를 같은 상태로 합치지 않는다. exact anchor 통과 후에도 `source_anchored_semantic_review_required`/`not_verified`를 유지한다.

내부 저장 위치는 **해당 Order output의 `.astra_stage_cache/generation_traces/<SHA256>.json`**이다. 호출자가 제공한 기존 cache root만 사용하며 API에 임의 trace 경로를 추가하지 않았다. 디렉터리는 0700, 새 파일은 0600으로 생성하고 기존 객체를 덮어쓰지 않는다. 비교 실패/parse 실패도 저장한다. 저장소가 없거나 쓰기 실패이면 not_persisted/failed를 기록하며 성공 저장이라고 하지 않는다. 외부 pin에는 path 대신 trace ID/hash/status만 남긴다. 내부 원문·payload·raw generation은 Git/ZIP 산출물로 등록하지 않는다.

반출 제한 구간이 포함된 비교에서는 후보 quote/claim/context, parsed output, prompt_sources, resolved prompt, raw generation, provider payload를 외부 진단에 포함하지 않는다. ID/hash·허용된 위치·gate/사유/상태만 내보낸다. 반출이 명시적으로 허용된 source의 후보 구간/offset은 허용하되 원문 anchor나 의미 승인으로 격상하지 않는다. 입력이 허용되었다는 이유로 HTTP 인증정보를 trace에 넣지 않는다.

## 검증과 남는 범위

원본 g11 함수와 현재 함수에 같은 **20개 합성 사례**를 주입하여 prompt bytes, 승인/거부, 실행 상태가 같음을 비교했다. 달라진 것은 기존에 unclassified였던 typed site 금지의 설명이다. 자료를 새로 검색하거나 실패 인용문을 자동 보정하지 않았다.

집중 fixture는 정상 인용, 잘못된 index, 다른 source에만 존재하는 인용, paraphrase/번역/비연속 결합, gene/site/context 누락, typed site 금지, parse/잘림/빈 comparisons, 반출 허용/제한, 최종 provider payload의 인증정보 제외를 검사한다. 기존 M4의 요청/전체 partial 구분·오류 시 pointer 보존·일반 replay 전달·구형 미요청 경로도 유지한다. 실제 과학 자료 검증과 이 합성 입력 검증은 별개다.

실제 패키지 검증은 회차 01의 `validate_g11_subject_delivery.py`를 그대로 재사용한다. 저장된 g11 과학/adapter 표를 기존 계산 경계의 double로 공급하고, 실제 일반 builder·seal·Results FileResponse·패키지 자체 코드의 reader replay를 실행한다. DB/auth/queue는 double이므로 운영 UI E2E가 아니다. 최종 run/hash와 보존 결과는 아래 및 `G11_FOLLOWUP_02_RESULTS.json`에 기록한다.

회차 03의 인용 실패 원인 수정·새 시도, 회차 04의 실제 RAG/모델 통합은 수행하지 않았다. 과거 71건의 정확한 원인 판별에는 해당 실행의 hash와 맞는 prompt/provider raw output/validator trace가 추가로 필요하다. 로컬 commit SHA는 최종 응답과 로컬 `LOCAL_COMMIT.json`에 남기며 main push·운영 배포·flag 변경은 하지 않는다.

## 고유 테스트 결과와 실제 일반 발행

- 최종 집중 suite: **78 passed, 4 deselected, skip 0**. 이어서 호출부 run/request/evidence key assertions를 보강한 기존 4개 사례도 통과했다. 같은 사례의 반복 실행을 78개에 더하지 않는다. 초기 선택에서 추가로 기존 synthetic publication fixture 1개를 실행했으나 실제 입력의 과학 재계산과 구분하며 최종 suite 수에 합산하지 않았다.
- 문헌 미요청 경로에 worker import를 새로 강제하는 개발 중 회귀를 발견했다. trace import를 실제 모델 요청 시점으로 옮겨 관련 테스트를 통과했다. prompt/승인 기준에는 영향이 없다.
- 고정 실행 전달 run: `g0-d1a3184e488a4a368ce326087a34ebdc`.
- ZIP: `codex-inputs/g11-followup-02/integration/order/astra_analysis_package_g0-d1a3184e488a4a368ce326087a34ebdc.zip`.
- ZIP/실제 FileResponse body SHA256: `9a1fda4c892688d8a64726414e1a975f4b5680ff6cbf6f9c1817dc52e2959ade`, **384,142,451 bytes**. 성공 pointer와 일치했다. 실행 시간 559.801초는 저장 표 staging·검증·봉인·다운로드·reader replay 시간이며 새 연구 계산 시간이 아니다.
- 일반 발행의 고정 보존 파일 **113개**, 정량 **22 CSV**, 그림/원자료 **31개**, 기존 findings·문헌 pin/결과가 byte-identical. 자체 코드 offline reader replay의 **40개 고유 산출물**도 byte-identical이다.
- 이 격리 Order는 M4 source archive만 등록하는 회차 01 harness를 그대로 사용했다. 원 g11 manifest 251개 중 219개 동일, 31개 의도적 변경, 새 M4 6개 추가, `references/finding_literature_execution.py` 1개 미포함이다. 문헌 실행 코드가 바뀌면서 현재 코드로 과거 hash를 대신할 수 없고, 이 격리 Order에 과거 g11 코드 archive가 등록되지 않았기 때문이다. 과학/문헌 결과의 누락은 아니다. 원 g11·회차 01의 해당 파일은 그대로 보존했고, 최종 reader 보존본은 **그 파일이 실제 존재하며 pin hash에 일치하는 회차 01 패키지**에서 생성한다. 생산 resolver나 승인 조건을 우회하지 않았다.
- 일반 발행 검사 후의 lazy-import 수정까지 포함한 최신 reader 코드는 별도 불변 reader revision과 자체 코드 replay로 확인한다. 기존 일반 builder 검증을 reader revision 하나로 대체하지 않는다.

재현 명령(같은 output을 덮어쓰지 않으므로 새 output 경로 사용):

```sh
codex-inputs/round11-20261010/runtime/bin/python scripts/audit_g11_literature_exclusions.py \
  --source codex-inputs/g11-followup-01/baseline \
  --consumer codex-inputs/g11-followup-01/integration-final/order/enrichment_free_runs/g0-b992dc7f962f445f8536c4d8da876292 \
  --search-root codex-inputs \
  --snapshot codex-inputs/full-evidence-m4/index_snapshot_private.json \
  --snapshot codex-inputs/round08b-20261008/index_snapshot.json \
  --output /tmp/g11-round02-new-audit
```

최종 테스트 XML은 `codex-inputs/g11-followup-02/TEST_RESULTS_FINAL.xml`, 추가 호출부 검사는 `CALLER_TRACE_TESTS.xml`, 원 코드와의 prompt/승인 대조는 `APPROVAL_PARITY.json`에 있다. 재현 가능한 내부 **합성** trace 4개는 `codex-inputs/g11-followup-02/fixture-traces/`에 보관했다. 실제 g11 trace로 표시하지 않으며 Git에는 넣지 않는다.

## 최종 보존 패키지

- 원본: 회차 01 `g0-b992dc7f962f445f8536c4d8da876292`. 기존 `revise_temporal(review_plan_only=True) → read_tables/write_reader → restore_execution → seal_archive`를 사용했다. 문헌 collect나 과학 계산은 호출하지 않았다.
- 최종 run: **`g0-82d7ec9317cf4d8794bff1828dfb63b0`**.
- ZIP: `codex-inputs/g11-followup-02/final-preserved/order/astra_analysis_package_g0-82d7ec9317cf4d8794bff1828dfb63b0.zip`.
- ZIP/Results 응답 SHA256: **`16fd11483872d5b94a0d0f44cdc421129de67de25bea3669ced2413c65fad243`**, 384,177,469 bytes. 현재 pointer와 실제 FileResponse body가 일치한다. 이 경로도 DB/auth는 로컬 double이다.
- 명시적 보존 대상 109개 및 원 manifest 257개 중 변경 대상 17개를 제외한 **240개**가 동일하다. 정량 22 CSV, science·kinase·temporal·그림, 카드/findings/coverage, 기존 문헌 pin/결과, M4 pin/실행표/링크/summary, 과거 문헌 실행 코드가 보존됐다. 원 성공 pointer도 변경하지 않았다.
- 의도적 변경 17개는 run/binding/readiness·reader packet/catalog/안내·5개 ptm_shared 코드 snapshot·계획/provenance다. 추가 3개는 부모 provenance와 reader revision/stage 기록이다. 전체 목록과 각 hash는 결과 JSON에 있다.
- 최종 ZIP 자체 코드의 offline reader replay: **16개 고유 산출물 byte-identical**. 신규 검색/모델/네트워크/과학 계산 0회. 이 결과는 위 일반 builder의 40개 reader 재구성과 별도이며, 과학 numerical replay나 인용 의미 재검증이 아니다.
- 처리 시간 304.203초. 중간 최신-code reader 검사 run `g0-0542264fdfbb430cbd28069a7964617f`도 보존했지만 최종 전달본은 위 회차 01 기반 보존 패키지다.

회차 02의 감사·진단 구현과 로컬 검증을 완료했다. 과거 71건의 원인 확정은 미완료이며 자료 부재를 모델 환각으로 분류하지 않았다. 운영 확인, 신규 실제 문헌 비교, 회차 03 이후, 원격 push·배포·flag 변경은 수행하지 않았다.
