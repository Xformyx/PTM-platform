# g11 후속 회차 03 — 최대 두 대상의 실제 문헌 진단

## 결과와 범위

회차 02 기준 `main / ad201405c6c42f96c19781ca6c8f7d55e08c18a9`에서 **새 진단 두 대상, 실제 모델 호출 총 2회**를 수행했다. 두 응답은 정상 종료된 빈 `comparisons`였다. 이번 실행에서는 인용문 변형·잘못된 source index·플랫폼의 source/response 연결 오류가 재현되지 않았다. 승인 수를 늘리기 위한 prompt·schema·validator 수정은 하지 않았다.

**A의 검색은 부분 실행이다.** 진단 스크립트의 입력 일치 검사 때문에 direct-site 단계가 RAG 호출 전에 중단됐다. 이 문제만 오프라인으로 재현·수정했으며 추가 모델 호출은 하지 않았다. B는 사전 지정한 검색 4단계와 모델 1회를 완료했다. 따라서 A까지 정상 검색을 완료했다고 보고하지 않는다.

과거 71건의 원인은 계속 미확정이다. 회차 02의 정확 재구성 0 / 원문만 부분 복구 3 / trace 부재 68을 유지했고, 과거 자료 탐색을 반복하지 않았다. 새 빈 응답을 과거 실패의 재현·해결이나 데이터와 문헌의 불일치로 해석하지 않는다.

시작 시 미커밋 자료는 `codex-inputs/`뿐이었고 보존했다. 저장소와 상위 경로에서 적용 AGENTS.md는 발견되지 않았다. 이번 로컬 커밋 대상은 이 보고서와 결과 JSON이다. **Production 파일 변경은 0개**다. 운영 UI·DB·배포·flag를 확인하거나 변경하지 않았다.

## 고정 입력과 사전 계획

- 기준 run: `g0-82d7ec9317cf4d8794bff1828dfb63b0`.
- 기준 ZIP SHA256: `16fd11483872d5b94a0d0f44cdc421129de67de25bea3669ced2413c65fad243`.
- 새 진단 ID: `g11-r03-diagnostic-02faa9470a5543b5b83a7836140ec5a6`. ZIP run이 아닌 별도 진단 실행 ID다.
- 계획은 실행 전에 `codex-inputs/g11-followup-03/PREDECLARED_REQUEST.json`에 고정했다. 대상·원본 key/value hash·실제 query 문자열·층별 quota·예산·모델·문헌 pin hash를 포함한다.
- 총 예산: 대상 2개, 검색 단계 최대 8회, 모델 최대 2회, 자동 재시도 0회. 대상별 최대 4개 query / 모델 1회 / prompt 100,000 bytes다. 이는 이번 실행 예산이며 생산 코드의 제한으로 추가하지 않았다.
- 기존 검색층과 quota를 유지했다: background 8, gene context 4, direct site 4, counterevidence 4. quota는 각 검색의 반환 상한이며 독립 관측 수가 아니다.

| 대상 | 기존 ID와 원본 연결 | 선정 이유 |
|---|---|---|
| A — TRIP10 후보 S296 | `finding_a0f138f34e259e65da05` → `reader_card_44d8af5514248a891c6b` → `form_77aa7fcf6b0f78ec` | 기존 선정 순서에서 제외 기록이 있는 첫 관측. 과거 제외 6건이 있지만 새 결과와 섞지 않음. |
| B — 미선정 MAPK1 후보 T183;Y185 | `review_subject_55b247e34a7048934295` → `reader_card_01c224da2d74475143c2` → `form_97aa4b58cee5c391` | M1 catalog에서 미선정 observation임을 확인하고 M3 plan의 적격 typed subject로 해석. finding alias는 `finding_567c62cae3b0da09455d`. |

두 원본은 `reader/cards.csv`의 정확한 `card_id`로 해석했다. 원본 값 hash는 각각 `d3857ca44990a61b7de8d2c1f3065c2dd315fd85ed2bf81673d95fc45790fb4a`, `b9fb221575710190b9a93841888261ff613ed1e8d98429661d54bd27b9c29952`다. 새 dose·starvation 시간·localization 확률·taxon을 채우지 않았다.

## 기존 자원과 실제 호출 경로

기존 M4의 로컬 Collection `ptm_project_round08b_insulin_signaling_20261008`을 사용했다. 442개 chunk의 ID/text/metadata/vector hash는 기존 `8feb2aed15b1be487a940a20033c8b8df233601a73ff09301e5a91b9ba6382f6`과 같고 실행 후에도 동일하다. 원 g11의 collection39/document96–102와 로컬 ID의 대응은 기존 M4의 7개 PDF SHA256 매핑을 재사용했다. 전역 ID를 하드코딩하거나 새 corpus를 수집하지 않았다.

모델은 기존 M4의 Ollama `ptm-round08b-qwen3-14b-40k:latest`, digest `7e08dfe65c515a6e24f64a68cb4664b1ded3dbd75de3d2de88870b74e94ce58b`다. model template·parameters도 이전 pin과 대조했다. 과거 g11의 `gemma3:27b` 실행을 재현한 것이 아니다. 실제 요청은 temperature 0, max tokens 4096, 기존 strict JSON schema, context 설정 40960을 사용했다. Python은 기존 3.11.13 runtime이며 embedding도 기존 offline PubMedBERT 자원이다.

재사용 경로:

- A: 저장 packet → `cards_for_selected_findings` / `astra_literature.inputs` → `retrieve_finding_literature` → 기존 `RAGRetriever` / `LLMClient` → `capture_generation` / `parse_model_json` → 기존 gate / `_export_result`.
- B: `EvidenceCatalog.query/resolve` → M3 plan / `resolve_subjects` → `execute_review` → 동일 retrieval·model·gate·export → 기존 per-subject stage cache와 실행 pin.
- 진단: 회차 02의 `_source_map`, `comparison_diagnostics`, `persist_generation_trace`를 그대로 사용했다. 외부 검증 harness는 실제 Chroma 반환과 기존 retriever 반환을 관찰·기록할 뿐 순위·선정·본문을 변경하지 않는다.
- 오프라인: 새 trace의 prompt/source/transport/parse를 대조하고 B는 기존 `replay_review → project_review`를 사용했다. 새 검색·모델·과학 계산을 호출하지 않았다.

## 실제 실행과 원인 판별

| 항목 | A: TRIP10 | B: MAPK1 |
|---|---:|---:|
| 검색 단계 시도 | 4 | 4 |
| 실제 RAG / Chroma query | 3 | 4 |
| RAG 전 진단 검사 중단 | 1, direct-site | 0 |
| 반환 없음 | gene context 1단계 | 0 |
| 층별 반환 구간 합계 | 11 | 16 |
| 중복 제거 후 prompt 구간 | 10 | 15 |
| 실제 모델 호출 | 1 | 1 |
| provider 종료 | stop | stop |
| prompt / 생성 token 수 | 25,086 / 9 | 31,290 / 7 |
| parse / comparisons | 성공 / 빈 배열 | 성공 / 빈 배열 |
| 새 제안·anchor 통과·검증 거부·의미 승인 | 모두 0 | 모두 0 |
| 요청 범위 상태 | partial | completed |
| 전체 근거 검토 상태 | partial | partial |
| 실행 시간 | 133.168초 | 137.325초 |

총 실제 모델 호출은 2회다. 생산 함수의 cost는 검색 시도 8회로 기록하지만, 그 중 1회는 harness 검사에서 중단돼 실제 검색은 7회다. 이를 모두 검색 성공으로 합산하지 않았다. A에는 `partial_retrieval_failure=True`와 `AssertionError`가 남는다. raw record의 `not_explained_by_retrieved_evidence`만 떼어 A를 성공/no-hit으로 설명해서는 안 된다. B의 기존 cache 상태는 `computed`, 재사용은 0회다.

고유 prompt 구간은 합계 17개이며, 외부 논문 4편과 사용자 방법 메모 1개에서 반환됐다. 이는 논문 전체를 읽었거나 17개 독립 근거를 확보했다는 뜻이 아니다. source_index는 각 요청의 0부터 시작하는 위치이며, collection/version/source_id/content hash와 함께 추적했다. 실제 HTTP는 harness 내부 localhost 6회(생성 2회 포함), 별도 초기 모델 목록 확인 1회다. 첫 sandbox 연결 실패 1회는 성공 HTTP로 세지 않았다. 외부 HTTP·새 corpus 수집은 0회다.

### 확인된 문제: 진단 harness의 JSON 왕복

사전 계획은 기존 adapter가 만든 `observed_grid`의 필드 순서로 query를 기록했다. A harness는 `sort_keys=True`로 저장한 JSON 감사본을 다시 입력으로 사용했다. 값은 같지만 query에 직렬화된 object key 순서가 바뀌어 direct-site query 문자열 검사에서 실패했다. RAG가 검색을 거부한 것도, 모델이 source를 바꾼 것도 아니다.

수정은 **진단 harness가 감사용 JSON을 입력으로 쓰지 않고 기존 `cards_for_selected_findings → inputs`의 결과를 직접 소비하도록 한 것**뿐이다. 수정 전 실행 파일은 `run_diagnostics.executed.py`로 보존했다. 원본 입력을 이용한 오프라인 재현에서 수정 전에는 direct-site 한 층이 달랐고, 수정 후 네 query가 사전 계획과 정확히 같았다. 값·NA·identity는 두 경로에서 동일했다. 검사를 완화하거나 query를 임의 보정하지 않았다.

총 모델 2회 예산을 소진했으므로 수정 후 실제 재시도는 하지 않았다. A의 원 trace·결과·partial 상태는 그대로 남긴다. 이 harness 실패를 과거 71건 또는 플랫폼 생산 버그의 원인으로 일반화하지 않는다.

### 미확정 및 정당한 해석 제한

두 prompt와 실제 provider body의 원문·source 순서·schema·설정이 일치했다. validator source map과도 같다. 파싱 실패와 provider가 보고한 출력 잘림은 없었다. 다만 서버의 token count/stop만으로 모든 내부 처리의 완전성을 독립 입증했다고 하지 않는다.

모델이 제안을 반환하지 않았으므로 이번 실제 자료에서 quote·scope·context gate의 승인/거부 경계는 **미평가**다. 자동 gate 실행 0건을 “71건 실패 해결”이나 새 positive parity로 세지 않았다. 모델 내부에서 빈 배열을 선택한 원인 전체도 확정할 수 없다.

원문 구간 세 건을 제한적으로 직접 확인했다. 자동 의미 승인을 추가하지 않았다.

| 진단 source | 직접 확인한 범위와 제한 |
|---|---|
| A index0, `76a7804e26c35b59cb3c41d48304ae3a_76`, DOI `10.1152/physrev.00063.2017` | INSR 양·신호 전달과 insulin dose-response의 일반 배경이다. TRIP10 S296나 현재 시간 반응을 직접 다루는 구간이 아니다. |
| B index5, `e4b02ca2eb855ecc8888ff3337540712_8`, 같은 DOI | INSR와 MAPK 경로의 일반 설명이다. 현재 rat form의 후보 T183/Y185, 실제 localization, 처리 시간의 직접 검증으로 사용할 수 없다. |
| B index14, `6f3b9fc28099aa9cc98ca9dd84a7f0dd_18`, DOI `10.1038/s41467-023-36549-2` | 그림/기능 범주·다른 조건의 결과를 포함한다. MAPK 범주 언급만으로 같은 site·조건·시간의 일치가 되지 않는다. |

이 확인은 전체 문헌에서 비교 근거가 없다는 전수 결론이 아니다. A는 direct-site 검색도 미실행이므로 근거 부재 판단이 더 제한된다. 새 자료에서 정당한 scope 거절이나 잘못된 인용문이 실제 발생했다고 만들어 기록하지 않았다.

## 검증·보존·반출

- **새 실제 trace 2개**를 네트워크 차단 상태에서 대조했다. 검색 반환 순서 → 중복 제거 → prompt source map → 최종 provider 요청 → raw output → parse가 hash와 원문 기준으로 일치했다. 모델 요청은 각 1회이며 strict schema가 실제 body에 있다.
- **실제 반출 검사**: A의 1개, B의 3개 구간만 기존 문서 허용 정책에 따라 본문을 유지하고, 각각 나머지 9개/12개는 metadata/hash로 제한했다. 이 수는 대상별 표현 수다. 제한된 prompt·raw generation·본문·후보 인용을 새 진단 필드로 내보내지 않았다. 원문·인증정보는 Git에 넣지 않는다.
- A의 새 결과를 `_export_result`로 다시 투영하면 저장한 안전 출력과 일치한다. B의 `replay_review/project_review` 재구성은 실행표 1행, source link 15행 및 summary가 두 번의 독립 로드에서 동일하다. requested scope는 completed, 전체 범위는 partial이다. 이는 **고정 문헌 투영 검사**이며 전체 reader replay·새 ZIP 발행·수치 replay가 아니다.
- **265개 보존 항목 변경 0개**: 기준 manifest 260개, manifest 자체, 기준 ZIP, 원 g11 ZIP 및 성공 pointer 2개를 전후 hash로 비교했다. 정량 22, science 17, kinase 12, temporal 9, 그림·원자료 31개와 기존 PhosX·15 findings·legacy literature pin/71개 제외 기록·M4 pin/결과를 보존했다.
- 생산 코드가 바뀌지 않아 회차 02의 동일 78개 pytest suite를 반복하지 않았다. 해당 결과를 이번 신규 테스트 수로 합산하지 않는다. 새 검증은 실제 trace·export·frozen projection 및 harness 실패의 오프라인 재현에 집중했다. 새 합성 인용 실패 사례나 검증 완화는 추가하지 않았다.

내부 자료는 `codex-inputs/g11-followup-03/`에 있다. 디렉터리 접근은 0700, generation trace는 0600이며 외부 ZIP에 등록하지 않았다. 주요 파일:

- `PREDECLARED_REQUEST.json`, `RUNTIME_PREFLIGHT.json`
- `A_INPUT_PRIVATE.json`, `B_INPUT_PRIVATE.json`, `A_RETRIEVAL_PRIVATE.json`, `B_RETRIEVAL_PRIVATE.json`
- `private_cache/generation_traces/3db83990e1197d2d23024c434d6ed4ee46b638f9776bb9f596de3293c10ce6a9.json`
- `private_cache/generation_traces/f52c2c8dd73de7a22c0b0b17d17d8d4b05aa826b81875dbe233c9a14f374eafd.json`
- `A_EXECUTION_PIN.json` — 진단 전용 legacy 결과 wrapper, 일반 발행 pin을 대신하지 않음.
- `B_EXECUTION_PIN.json` — 기존 M4 실행 schema의 새 pin, 기존 성공 pin과 별도.
- `TRACE_AUDIT.json`, `HARNESS_FIX_VALIDATION.json`, `FROZEN_PROJECTION_VALIDATION.json`, `PRESERVATION_BASELINE.json`.

`TRACE_AUDIT`의 zero-proposal gate 반복은 검증할 제안이 0개였다는 뜻이다. 완료 보고/결과 JSON에서는 이를 명시적으로 not_applicable로 기록한다. 공개 결과에는 원문 대신 실제 ID·hash·위치·상태만 남겼다.

## 회차 04로 남긴 항목과 Git 상태

회차 03의 제한된 진단은 마쳤으나, A의 완전한 실제 검색과 신규 nonempty proposal에 대한 원인 관찰은 미완료다. 이후 별도 승인된 예산에서 수정한 입력 연결로 A를 실행할 수 있다. 현재 두 응답에서 빈 배열이 나왔다는 이유로 다른 문헌·모델·대상을 추가해 승인 사례를 만들지 않았다.

일반 API/worker/atomic publish/Results 다운로드의 최종 통합, 제한이 있는 method/no-call/raw typed 대상, 새 패키지 전체 reader replay 및 실패 시 pointer 보존은 회차 04에 남긴다. 기존 로컬 DB·권한·큐 double의 검증을 운영 확인으로 바꾸지 않는다.

신규 ZIP 생성, 정량·PhosX·temporal 재계산, reference 전체 수집, 원격 push, 운영 배포, flag 변경은 모두 미수행이다. 보고서·결과 JSON만 **로컬 커밋**하며 SHA는 완료 응답과 내부 `LOCAL_COMMIT.json`에 기록한다. 생산 승인 기준과 기존 성공 자료는 그대로다.
