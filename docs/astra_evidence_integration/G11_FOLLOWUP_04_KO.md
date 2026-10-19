# g11 후속 회차 04 — 실제 문헌 결과의 일반 발행·다운로드

## 범위와 변경

시작 기준은 `main / 6612415781396d99dd48bd434f6949b86f5baf1c`다. 기존 미커밋 자료, 원본 ZIP, 성공 pointer, pin·trace·cache를 보존했다. 운영 환경에 배포하거나 flag를 변경하지 않았다. 적용 AGENTS.md는 발견되지 않았다.

TRIP10과 AKT1의 새 실제 검색·모델 실행 결과, 회차 03의 완료된 미선정 MAPK1 결과를 **명시적 고정 pin 재사용 요청**으로 일반 발행 경로에 전달했다. 이 실행을 운영 UI 검증이나 전체 과학 계산 replay로 확대하지 않는다. 최종 재생성 및 reader replay 결과는 아래 최종 검증 절에 기록한다.

Production 변경은 `ptm_shared/astra_literature_review.py` 한 파일이다. `combine_review_executions`는 기존 `validate_frozen_request → replay_review`로 각각의 원본 값·typed 입력·연구 조건·문헌 선택·실행 계약을 검증한 완료 scope만 결합한다. 원 pin을 `component_executions`에 그대로 유지하고 원 기록·request hash·model/code/budget을 보존한다. 중첩/중복 대상, 미완료 요청, 다른 문헌 선택, 변조된 계약·원본·결과는 거절한다. 과거 결과를 현재 모델 호출 또는 현재 검색 cache 적중으로 바꾸지 않는다. 통합 pin의 계약은 원 계약들의 hash와 합산 예산을 명시한다.

새 검색 엔진·cache·scheduler·정량·kinase 방법은 추가하지 않았다. prompt/schema/quote·scope·context·typed gate 및 export 정책 변경은 없다. 기존 `test_g11_subject_delivery.py`에 고정 scope 결합·원 기록/계약 변조 검사를 추가했다.

## 실행 대상과 실제 문헌 단계

실행 전 `codex-inputs/g11-followup-04/PREDECLARED_REQUEST.json`에 대상·정확한 key/value hash·query 계획·이유·예산을 고정했다. 진단 실행 ID는 `g11-r04-6e30058d47a249b984ba28f44cf28063`이며 archive run ID와 다르다. 대상은 3개로 최대 5개 예산 안이다. 생산 코드의 대상 제한은 변경하지 않았다.

|대상|subject / 원본 evidence|선정 이유와 제한|이번 실행|
|---|---|---|---|
|TRIP10 후보 S296|`review_subject_d82539f93c7ec7d3deaa` / `reader_card_44d8af5514248a891c6b` / `form_77aa7fcf6b0f78ec`|이전 부분 검색의 미완료 범위 처리. 관측 U_joint/P_joint/A, localization 미측정 유지.|4개 검색층 완료, 모델 1회|
|미선정 MAPK1 후보 T183/Y185|`review_subject_55b247e34a7048934295` / `reader_card_01c224da2d74475143c2` / `form_97aa4b58cee5c391`|요약 밖 관측의 전달. 기존 완료 결과의 값·범위·study·문헌·입력 hash 검증.|회차 03 frozen 결과 재사용, 새 검색/모델 0회|
|AKT1 PhosX method result|`review_subject_6f2b7a781153897eb7b2` / `method_result_e128e34506b2f1818851`|기존 1분 결과의 insufficient_coverage·method readout을 유지. `allow_site_comparison=false`.|3개 검색층 완료, 모델 1회|

원본 키는 observation의 `reader/cards.csv:card_id`, method의 `kinase/method_scores.csv:method_result_id`를 사용했다. 전체 정확한 key와 hash는 결과 JSON 및 pin의 `subject_evidence`에 있다. selected findings는 대상 필터로 사용하지 않았다.

기존 Collection `ptm_project_round08b_insulin_signaling_20261008`의 442 chunk, immutable index hash `8feb2aed15b1be487a940a20033c8b8df233601a73ff09301e5a91b9ba6382f6`을 실행 전후 확인했다. 원 collection39/doc96–102와 로컬 선택의 대응은 기존 7개 PDF SHA 매핑이다. 최신 운영 인덱스와 같다는 추정은 하지 않았다.

모델은 기존 Ollama `ptm-round08b-qwen3-14b-40k:latest`, digest `7e08dfe65c515a6e24f64a68cb4664b1ded3dbd75de3d2de88870b74e94ce58b`다. temperature0, max tokens4096, 기존 strict JSON schema·context40960·prompt `finding_comparison.v6.2`를 유지했다. 신규 모델 호출 **2회**, 자동 재시도 **0회**다. 신규 corpus 수집·외부 HTTP는 0회다.

새 실행의 논리 검색 7회 중 2회는 immutable index와 exact query 계약이 일치하는 기존 검색 cache였다. 실제 Chroma query는 **5회**다. MAPK1의 과거 4개 검색/모델1회는 이 숫자에 더하지 않는다. 원 MAPK1 pin semantic SHA는 `1e9af627cfa579a602e15e92b20fc34271ac74b97d47597d5b7561b8867de691`이며 이번 새 검색 cache 적중으로 표시하지 않는다.

TRIP10은 이전의 3/4 검색층·10개 prompt 구간인 partial 기록을 보존하고, 정확한 typed 입력으로 4/4 검색층·14개 prompt 구간을 얻었다. 최종 입력 hash가 달라 이전 모델 응답은 재사용하지 않았다. 이번 입력 SHA는 `6bf0fe6c194e2552df58596df777349854ed99b01fd32496767a618c22746f81`이다. 진단 스크립트의 JSON 필드 순서 문제를 생산 오류나 과거 71건의 원인으로 확대하지 않았다.

|대상|층별 반환 / 중복 제거 후 prompt 구간|패키지 본문 허용 / metadata-only|생성·인용·의미 상태|
|---|---:|---:|---|
|TRIP10|15 / 14|2 / 12|stop, parsed, empty comparisons; 제안·anchor 승인·거부·의미 승인 모두 0|
|MAPK1 (과거 고정)|16 / 15|3 / 12|동일한 과거 정상 빈 결과. 새 모델 호출 0|
|AKT1|11 / 10|1 / 9|stop, parsed, empty comparisons; site 비교 금지·coverage 부족 유지|

세 대상의 고유 prompt 구간은 17개, 문서는 외부 논문 4편과 사용자 방법 메모 1개다. 논문 전체를 읽었거나 독립 검증한 수가 아니다. 빈 comparisons를 인용 실패·문헌 불일치·no_hit으로 바꾸지 않았다. 제안이 없어 실제 새 자료의 literal gate는 not_applicable이며, 의미 상태는 not_verified/review_required다. 이번 응답으로 과거 71건의 원인을 설명하지 않는다. 과거 정확 복구0/원문만 부분복구3/trace 부재68은 회차02의 결과로 유지한다.

`TRACE_AUDIT.json`은 source 순서/중복 제거 → prompt source map → 실제 provider body/schema/options → raw output → parse를 hash와 원문으로 대조했다. provider는 stop을 보고했고 client truncation은 없었다. provider 내부 잘림의 완전한 부재까지 독립 입증한 것은 아니다. 반출 제한 원문·prompt·raw generation·후보 quote는 패키지와 Git에 넣지 않았다. 내부 trace는 기존 0600 저장 경로에 남는다.

## 실제 경로와 대역의 경계

- 실제 로컬 FastAPI orders router의 PATCH/POST start, MySQL ORM 저장·dispatch claim, Redis 큐, Celery `preprocessing.tasks.run_preprocessing`, worker dispatcher `run_primary_analysis → v6 run → run_astra_analysis`를 사용했다.
- MySQL은 기존 로컬 컨테이너의 별도 schema `ptm_g11_round04_20261019`, Order1 `G11_R04_LOCAL`이다. Redis는 전용 DB12/11/15, worker는 solo/concurrency1이다. 기존 운영 DB/Order를 변경하지 않았다.
- 인증은 기존 `AUTH_ENABLED=false`의 InternalUser 경로다. 권한 함수는 실행했지만 로그인·실사용자별 허용/거부 검증은 아니다. 전체 FastAPI lifespan과 브라우저 UI, 운영 배포 경로는 미확인이다.
- 과학 계산·annotation·그림 경계는 검증된 archive 표/파일을 공급하는 **test double**이다. 값을 정확 비교한 뒤 원 CSV bytes를 유지했다. 이는 실제 quant cache hit 또는 수치 분석 재실행이 아니다. 문헌 runtime·execute_review·PhosX·specificity·quant 함수의 신규 호출은 실패하도록 차단했다.
- 기존 `run_requested_review → registered_execution → validate_frozen_request → attach_review_execution → write_reader → validate_package → seal_archive → current pointer`는 실제 함수다. Results `get_enrichment_free_evidence → recorded_run → FileResponse`의 실제 HTTP body를 끝까지 받아 hash를 계산했다. 공간 절약을 위해 별도 DOWNLOADED.zip은 만들지 않고 원 발행 ZIP을 보존했다.

고정 pin 등록용 reader revision은 준비 단계일 뿐 일반 경로 검증을 대신하지 않는다. 등록 run은 `g0-985e38092ff745288309d2dbcd606140`이다. 기존 M4가 있는 archive를 다른 pin으로 덮으려던 첫 등록 시도는 guard로 실패했고 그 staging도 보존했다. 이후 기존 g11 M3-only 원본의 값·study·source 계약을 확인해 별도 등록했다.

첫 API 검증 시 저장 과학 결과 대역이 과거 M4 packet을 새 요청 단계 이전에 공급해 `Reader execution packet requires frozen pin`으로 차단됐다. 검증 harness에서 과거 M4 packet/표만 과학 단계 입력에서 제거하고 새 요청을 기존 문헌 단계에서 연결하도록 수정했다. 생산 guard는 유지했고 실패 run `g1-422c5253fdf14af0b76b7923092b93bf`와 성공 pointer 보존을 확인했다. 로컬 API bootstrap의 중복 prefix도 요청 전 수정했다. 두 문제는 검증 환경 문제이며 인용 validator 오류가 아니다.

## 보존·정리

과거 기준 manifest·ZIP·pointer를 포함한 **265개** hash가 그대로다. 첫 성공 일반 ZIP은 원본 정량22 CSV, science·kinase·temporal, 그림·원자료31, 카드/15 findings/coverage, 기존 literature pin/비교 결과를 포함한 **113개 지정 파일**이 byte-identical이다. 기존 71개 제외 기록은 quote_not_in_retrieved_chunk68 / scope_identifier_absent_from_quote3이다. M4의 과거5대상 결과와 이번3대상 결과는 다른 run/pin으로 보존한다.

디스크 정리는 별도 승인된 네 downloaded 복사본만 재검증했다. g8 236개, g6 235개, g5/g1 각각229개 파일이 대응 원본과 path/size/SHA가 같았고, 후보 고유·불일치·symlink·특수·열린 파일 및 현재 로컬 실행·설정·38개 pointer의 의존은 없었다. 운영 DB의 모든 과거 참조를 전수 확인했다는 뜻은 아니다. 원본에만 `platform_run.json`, `stage_checkpoint.json`이 존재하는 것은 허용했다.

아래 두 경로만 순차 영구 삭제했다. 각 보존 원본은 `codex-inputs/round11-20261010/output/Round11_Order89_fixed_inputs/enrichment_free_runs/<해당 run>`이다.

- `codex-inputs/round11-20261010/D/downloaded-g8-35a51d79d6d64b3fb94bfc9327da5af3`
- `codex-inputs/round11-20261010/D/downloaded-g6-31c24418139f4a8f8ef16782764d9e28`

실제 회수량 **5.080921 GiB**, 직후 여유 **14.077557 GiB**로 보수적 재개 예산13.19GiB를 충족해 삭제를 중단했다. g5·g1은 남겼다. 이전 완료 정리(중복 ZIP3·reader8, 실제6.137474GiB)는 반복하지 않았다. 원본/과거 감사 기록은 수정하지 않았고 새 `COPY_SUBSET_CLEANUP_KO.md`, 전수 hash `COPY_SUBSET_PRECHECK.json`, 실제 공간 `COPY_SUBSET_ACTIONS.json`에 대응표를 남겼다. 대용량 단계는 순차 실행했고 단계마다 공간을 검사했다.

## 검증 결과와 남는 제한

고유 pytest **18 passed, skip0**: `test_g11_subject_delivery.py`10, `test_astra_literature_review.py`8. 합성 fixture의 작은 계산은 실제 HIRc-B 정량/PhosX 재계산과 구분한다. pandas FutureWarning1건이 있다. 개발 중 신규 fixture의 replay config/full-question-link 누락 및 메모리 alias를 파일 변조와 혼동한 assertion은 기존 frozen fixture와 JSON 왕복으로 수정했으며 실패를 통과 수에 더하지 않았다.

기존 summary0/5/15/50 독립성, 미요청 호환, FK/hash/source mismatch, 요청 미완료의 pointer 보존, 일반 writer/replay 전달, 문헌 설정의 과학 fingerprint 독립성을 재사용했다. 실제 결과의 anchor 승인 건수를 늘리는 변경은 없다.

과학적 제한은 localization 미측정, technical_per_condition, method p/q와 생물학적 유의성의 구분, no-call·insufficient_coverage·mapping ambiguity다. 새 reader/문헌 연결로 해소하지 않았다. 전체 numerical/method replay, 운영 UI·release·로그인 권한, 외부 Astra 소비/의미 승인은 미수행이다. 신규 외부 corpus 수집·push·배포·flag 변경은 없다. 로컬 커밋 SHA는 완료 응답과 내부 LOCAL_COMMIT 기록에 남긴다.

## 최종 발행·재생성·reader replay 결과

|구분|run|실제 Results ZIP SHA-256|
|---|---|---|
|첫 성공 일반 요청|`g2-5b795f98b5054ce0a59e7e1f9bb45f7c`|`bf4cac2df6a86163de2dec55753460cf36a9cd0e5f363ea68d020e6b2d514b4f`|
|같은 입력/요청/pin 재생성, 최종|`g3-173714b8042a41afa0248b88dc49d4c3`|`862be7cbefcd42c24769ea0a6530bc6ba2b1f0fb2f4fa22931d1886e727f19af`|

최종 ZIP은 `codex-inputs/g11-followup-04/delivery/G11_R04_LOCAL/astra_analysis_package_g3-173714b8042a41afa0248b88dc49d4c3.zip`이다. 실제 HTTP 200 응답 **384,205,219 bytes**의 hash, ZIP 내부 provenance의 run, manifest, 파일 시스템 성공 pointer, 완료 Order가 같은 실행을 가리킨다. 첫/재생성 Celery task는 각각 `cad4e0ad-65c1-46d4-a121-1be73bb83ded`, `f0574f1d-5096-470b-9e2d-3995a5a47a74`이며 실제 worker 시간은 약388.216초/391.603초다. 등록용 revision172.741초는 별도로 기록한다.

두 ZIP 각각 manifest **257개** 파일의 실제 bytes/크기/SHA를 검증했다. 지정 보존 **113개**, 정량 **22 CSV**, 그림·원자료 **31개**, 기존 findings와 문헌 결과가 모두 동일하다. PR/PG/FASTA hash도 기준과 같다. 기존 literature 제외 기록은68/3으로 보존됐다. 원본 g11/회차02 성공 결과와 기존 M4 실행을 수정하지 않았다.

두 API dispatch의 저장 context·입력 snapshot·문헌 선택은 같고 문헌 fingerprint도 같다. 고정 M4 pin·실행표·source links·summary는 byte-identical이다. consumer run/binding/provenance/시각과 이를 표시하는 안내문 차이만 의도했다. 두 소비 실행의 신규 query/model은 **0/0**이며 이번 회차 누적 신규 모델 호출은 기존 완료분을 포함해 **2회**다.

요청3개는 completed, 전체158,593개 표현은 partial이며 158,590개는 미요청이다. `START_HERE_ASTRA → READ_ME → LITERATURE_SUBJECT_REVIEW` 및 전체 근거·계획 안내의 상대 링크 **112개**를 확인했다. 최종 MAPK1은 요약 findings에 포함되지 않으며 source key로 해석된다. AKT1의 원 method row는 insufficient_coverage이며 typed site 비교 금지는 유지된다. 세 결과의 제안·anchor 승인/거부·의미 승인은 모두0이다.

최종 ZIP 자체 코드로 네트워크를 차단한 `scripts/replay_astra_reader.py`를 실행했다. **고유40개 산출물 byte-identical**(반환 목록42개에는 중복2개 포함)이며, 16,944 원본 행·14,658 카드·15 findings의 값·시간·NA mask·ID 검사를 통과했다. M4 pin/실행표/링크/summary/guide와 packet 연결도 포함한다. repo 코드를 대신 읽거나 새 문헌/모델을 호출하지 않았으며 과학 numerical replay가 아니다.

검증 결과: `G11_FOLLOWUP_04_RESULTS.json`. 내부 근거: `TRACE_AUDIT.json`, `first-success_VERIFICATION.json`, `final_VERIFICATION.json`, `*_HTTP_DOWNLOAD.json`, `DISPATCH_2/3.json`, `offline-reader-final/READER_REPLAY_VALIDATION.json`, `COPY_SUBSET_*`, 기존 model pin/trace. credentials·DB 자료·원문·ZIP은 커밋하지 않는다. 검증용 API와 worker는 작업 완료 후 정상 종료했고 MySQL/Redis 데이터 및 결과는 보존했다.

최종 reader replay 후 여유 공간은 약 **7.44 GiB**다. 이번 추가 정리 실제5.080921GiB, 앞서 완료된 정리6.137474GiB를 별도로 기록한다. 승인된 두 복사본 외 추가 삭제는 없었다. `PAUSED_FOR_DISK`는 검증 완료 상태로 갱신한다. **회차04의 로컬 고정 결과 일반 발행·다운로드·reader replay를 완료했다. 운영 UI/권한·배포와 독립 과학/의미 검증 완료는 주장하지 않는다.**
