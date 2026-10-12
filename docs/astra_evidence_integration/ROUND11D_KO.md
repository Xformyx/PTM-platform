# 11-D — 최종 로컬 UI 다운로드와 소비 인수 범위

## 판정

11-A/B/C의 구현과 **로컬 일반 UI → v6 → Results 다운로드**를 확인했다. 운영 서버에 배포하거나 운영 flag를 변경하지 않았다. 운영 Order 89 DB/API 프로세스/worker release는 접근하지 못했으며, 실제 Astra 새 세션의 소비 검증도 미수행이다. 따라서 사용자 정의의 전체 종료 조건은 아직 모두 통과하지 않았다. 이 문서는 로컬 완료를 운영·Astra 완료로 대체하지 않는다. 새 방법이나 추가 개발 회차는 시작하지 않는다.

## 실제 경로와 release

검증한 main 기준 `a1b876d0e310bd39495b0e57e9bc374427fb58d0` 및 아래 D 경계 수정(최종 package code hash와 커밋 파일 일치 검사)(11-A `d535e34`, 11-B `c6d1452`, 11-C `a1b876d`). 기존 격리 API/worker/frontend를 사용했다. API localhost:8019, frontend localhost:5179, 전용 로컬 DB/Redis queue, 기존 Chroma/Ollama다. 운영 서비스와 다른 worker를 중단하지 않았다.

Order 89의 원 ZIP에서 PR/PG/FASTA·design·질문·source pin을 고정하고 로컬 Order 73을 생성했다. 파일 보관/Order 생성은 기존 API, 분석 시작과 이번 동일 pin 재실행·다운로드는 일반 UI 버튼으로 수행했다. 모든 업로드 필드를 UI에서 직접 조작한 검사와는 구별한다. 화면이 보낸 v5 요청 → 로컬 flag=1의 API 저장/dispatch v6 → worker v6 → context/plan/provenance/replay v6를 검증했다. 기대 profile은 결과에서 역추정하지 않고 v6로 고정했다.

최종 run `g8-35a51d79d6d64b3fb94bfc9327da5af3`.
ZIP SHA-256 `9b49ddb1911384b09e42425caea8536c738c4b7704b56855cfd6fdbf0635bb28`.

실제 Results의 ZIP 다운로드는 성공 pointer SHA와 일치했고 `Astra 전달 지침` 다운로드는 ZIP 내부 START_HERE bytes와 같다. 화면에서 15 findings, PhosX 6 contrast, 문헌 비교 실행 15/15·고유 구간 25·의미 검토 승인 0, 참조 부분 완료·localization 입력 없음을 직접 확인했다. Browser page error 0.

운영 공개 version endpoint에서 확인한 marker는 df0e98a / 2.6.0이다. 공개 marker는 실행 중인 API/worker 코드나 flag/주문 상태를 확정하는 증거가 아니다. 로컬 native API는 `/app/GIT_HASH`가 없는 환경이므로 저장 패키지 code hashes와 검사한 workspace commit을 release 증거로 사용했다.

## 결과와 보존

- Manifest 무결성 및 과학 표 79개 검증. 원 PR/PG/FASTA SHA, design, 원 source pin 유지.
- 11-B 대비 reader/packet 외 dictionary 표 78개 byte 동일. 정량 22개, PhosX·temporal 과학 표, findings ID/순서/관측, 문헌 검색·source·comparison CSV 보존.
- Source selection pin, literature selection pin, finding literature pin 모두 byte 동일. 문헌 결과 pin은 `904baece848c067fa3745f01d9a2e3df58293c007fdce2185f1b4e7495c2f916`이다.
- 이번 재실행의 정량/normalization/identity/discovery/quant audit/temporal/native augment 모두 유효 cache 재사용. 문헌은 hash로 결속된 이전 코드의 실행 로직 동등성을 확인한 frozen pin 재사용, 새 query/model call 0. 6 native runtime은 `reused`, 이번 계산시간 0, 원 실행시간은 별도 보존.
- 총 단계 시간 약 150.23초. 이 시간은 새 PhosX/문헌 분석 시간이 아니라 저장 결과 검증·reader/그림 생성·봉인 시간이다. 실제 방법/문헌 실행은 11-B에 기록했다.
- 전체 2,824 forms / 16,944 form×contrast. 카드 가능 2,159 forms / 수치 12,499행, 결측 grid 455행, 보류 665 forms / 3,990행. 선정 15개(90 grid rows), 미선정 16,854 원본 행 유지. 보류 사유는 서로 겹칠 수 있으며 복수 precursor·종 ambiguity를 가짜 identity로 대체하지 않았다.
- 원문 질문 BQ-001은 `partially_answerable`, 15 finding 연결. 전체 source rows와 시간 근거로 답할 범위를 제공하고 문헌의 직접 지지 관계·생물학적 유의성·인과·확정 활성은 답변 불가로 유지한다.
- 패키지 자체 코드의 offline reader replay: 21 파일 byte 동일, 네트워크 0, 과학 재계산 0. 상대 링크 110개 누락 0. Reader replay는 method 재계산이나 문헌 의미 검증이 아니다.
- 실제 180분 공식 parity는 11-B의 동일 조건 검증을 재사용. 여기서 method replay/공식 비교를 재실행하지 않았다. 원 HDF5는 ZIP에 없으므로 전체 method 재계산에는 동일 hash 외부 자원과 고정 환경이 필요하다.

## 대표 원본 행

세 행 모두 `quant/comparisons.csv`, `contrast_id=contrast_eb2f813f825c4ccb`, target 15분 vs Control이다. 단위는 log2 fold change, A=U_joint−P_joint이며 동일 joint mask다. 아래 후보 site 표시는 measured localization이 아니다.

| form / 후보 | U_joint | P_joint | A |
| --- | ---: | ---: | ---: |
| DOCK7 / form_5f6b1591279b085d / 후보 S1423 | 0.49515296216959115 | -0.04959100753146828 | 0.5447439697010603 |
| SIK3 / form_0307f4dc0d707fd5 / 후보 S779 | 0.9645604844502706 | -0.014212329592009354 | 0.9787728140422836 |
| RBM26 / form_927c72b605b8f2bd / 후보 S127 | 0.33496754417533126 | -0.009584073981681485 | 0.34455161815701163 |

이 세 예시만 맞는 것으로 전체 주장 감사를 대체하지 않는다. 최종 보조 AI 응답의 모든 구조화 수치 주장과 전체 본문은 아래 별도 결과로 평가한다.

## 인수 체크리스트

| 종료 항목 | 확인 상태 |
| --- | --- |
| 실제 운영 일반 UI→v6→Results | 미확인. 격리 로컬 UI는 통과 |
| adapter·선정/보류·authoring packet·질문 범위 | 로컬 실제 ZIP 통과 |
| 여섯 PhosX contrast·실제 자원/실행 상태 | 11-B 실제 실행, 최종 ZIP 동일 결과 재사용 통과 |
| 선택 문헌 실제 검색·접근·비교 | 6편/25구간/15비교 실행. 직접 지지 제안·의미 승인 0 |
| finding별 시간·기여·문헌의 원본 연결 | 15/15 시간 연결, 존재하는 원본 ID만 사용. 문헌 no-support 보존 |
| 정량·ID·NA·시간·입력 제한 | 통과 |
| 그림 0·단위·표시명·시간·NA | 실제 PNG/UI 검토 및 보존 검사 통과 |
| ZIP·상대경로·row link·offline reader replay | 통과 |
| 실제 Astra 새 세션 보고서 및 모든 핵심 주장 감사 | 미수행. 로컬 다른 모델의 보조 점검과 구분 |
| Git/release/운영/자원/조건부 replay 범위 구분 | 이 문서 및 각 회차 결과에 기록 |

## 남은 접근 조건

운영에는 검증된 release, API v6 전환 설정, 같은 manifest/hash 및 공유 mount, PhosX optional dependency image, 기존 Chroma collection과 사용 모델 접근이 필요하다. 운영 권한과 실제 runtime 확인 없이 배포를 수행하지 않았다. 원 g3가 v5인 직접 원인이 운영 flag/오래된 API/download pointer 중 무엇인지는 미귀속이다.

Astra 사용 환경에는 최종 ZIP과 그 START_HERE만 제공하는 새 세션이 필요하다. 실제 Astra 접근이 없어 이 검증을 대신했다고 쓰지 않는다. raw-only 대비 우월성, 확정 kinase activity, biological significance, 인과·독립 실험 검증은 주장하지 않는다.

최종 산출물: `codex-inputs/round11-20261010/D/astra_analysis_package_g8-35a51d79d6d64b3fb94bfc9327da5af3.zip`, 같은 폴더의 `START_HERE_ASTRA.md`, `offline-reader-replay-g8/READER_REPLAY_VALIDATION.json`, UI 캡처와 보존 검사. 입력·ZIP·PDF·비밀 설정은 커밋하지 않는다.

## 보조 AI 소비 점검 — 실패를 보존

실제 Astra 접근 대신, g6 패키지에서만 만든 105,032-byte 발췌를 기존 로컬 Qwen 14B의 새로운 단일 요청에 제공했다. 개발 이력은 넣지 않았다. START_HERE/READ_ME/LITERATURE·질문·상태·여섯 방법 요약·대표 세 행·저장 temporal 근거가 입력이다. 자동 ZIP 탐색도 실제 Astra도 아니다. `finding_comparison` 문헌 모델 호출을 반복한 것이 아니라 별도 보조 보고서 요청이다.

모델 `ptm-round08b-qwen3-14b-40k:latest`, 입력 38,597 tokens / 출력 2,286 tokens / 약 286.09초, max output 4096. 최초 보조 호출은 LLMClient JSON schema 형식 오류로 전송 전에 종료돼 생성 횟수에 포함하지 않았다. 성공적으로 생성된 보조 응답은 한 개이며 숨기거나 정답 보고서로 교체하지 않았다.

**주장 감사 실패**: 수치 주장 18개 전수 조회에서 2개만 원본과 일치했다. 16개 값/귀속 오류, 요청한 대표 세 form의 9개 U/P/A 누락, row_key 객체 대신 문자열 18개, 인용 경로 5개 중 2개 부재. Exact form/contrast 문자열은 감사 목적으로만 해석했으며 원 보고서는 수정하지 않았다. 전체 본문도 검토해 확정 kinase 활성 과장, PhosX native score와 U/P/A 혼동, 문헌 비교 미실행 오기, 시간 패턴의 원본 행 연결 부족을 확인했다. 기술 반복/localization/같은 실험 parent의 제한 문장은 맞지만 과장된 앞 문장과 모순된다.

확인된 패키지 표시 문제는 하나였다. 원 카드 생성 당시의 “문헌 비교 미실행” 제한이 현재 완료된 검색·비교 상태와 함께 READ_ME에 반복됐다. `write_reader`의 표시 문구와 `apply`의 authoring authority만 수정해 finding별 실제 검색 상태를 우선하도록 했다. 원본 카드 CSV·15 finding·관측·pin은 보존했다. 합성 경계 최초 4개 통과(신규 표시 검사 1개 포함); 처음 신규 fixture의 출력 폴더 누락을 고친 재시도는 중복 집계하지 않았다. 이 수정 때문에 과학/PhosX/RAG/문헌 LLM을 다시 실행하지 않는다.

보조 보고서의 다른 수치/해석 오류를 패키지 계산 오류로 간주해 값을 바꾸지 않았다. 수정 후 모델 소비 재검증은 미수행이며, 실패 응답을 통과로 승격하지 않는다. 원 응답과 전수 감사는 `ROUND11D_AUX_REPORT.json`, `ROUND11D_AUX_CLAIM_AUDIT.json`에 있다. 실제 Astra 새 세션 인수는 여전히 남는다.

연속 동일-pin 재실행 중 g7에서 원 실행 코드 증명의 전달 누락도 발견했다. g6는 원 g5 문헌 pin을 그대로 재사용했지만 자기 archive에는 변경된 reader 코드만 보관해, 다음 재사용에서 원 pin의 code hash를 확인할 수 없었다. g7은 문헌 수집 재진입을 확인하고 취소했으며 g6 성공 pointer/SHA는 그대로였다. 취소된 단계의 부분 query/model 호출 수는 확정하지 못했으므로 0이나 완료로 기록하지 않는다.

`finding_execution_code`는 해당 Order archive에서 pin의 정확한 code hash에 맞는 원본만 찾고, 새 ZIP의 `references/finding_literature_execution.py`로 보존한다. 코드를 실행하거나 pin을 새로 쓰지 않는다. 이후에는 중간 archive 하나만으로도 기존 입력·설정·실행 로직의 동등성을 검증한다. 원본이 없거나 hash가 다르면 재사용을 거절한다. 연속 두 번 재사용/원 archive 제거/증명 오염 fixture를 추가했다. D 변경 경계의 고유 테스트는 총 5개 통과하며 이전 회차 테스트와 합산하지 않는다.

보조 모델의 2/18 일치는 이 단일 제한된 요청의 감사 결과이며, 모델 일반 성능이나 패키지의 raw-only 대비 우월성 지표가 아니다.
