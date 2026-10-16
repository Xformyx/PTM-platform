# 전체 근거 접근 M2 — 질문·시간·작성 경로

## 범위와 기준

2026-10-16, 착수 `main` / `694b4e3c13852995df9ae161a6767661dc364589` (M1). 적용 AGENTS.md는 저장소와 확인한 상위 경로에 없었다. 착수 미커밋 자료는 `codex-inputs/`이며 그대로 보존했다. 새 DB, 분석 엔진, 질문 matcher, 문헌 검색, LLM 보고서 생성은 추가하지 않았다. M3/M4, push, 배포, 운영 flag 변경은 수행하지 않는다.

실제 입력은 M1의 g10 기반 reader 개정 `g0-1cc3b1ebab05499d95f7f8f3cc42bbb0`이다. 원 g10 run은 `g10-5c171c84a6e34d14b6d83b203c8aa99a`; 다른 run을 원 g10으로 표시하지 않는다. M1 ZIP SHA-256은 `206384f8399e0af38ff01fc644e8b8bd7844a943cbdda46a206784cb80be21d2`이다. 운영 DB/UI는 이번 검사 대상이 아니다.

## 확인한 원인과 기존 자산 재사용

| 경계 | 기존 동작 | M2 변경·재사용 |
| --- | --- | --- |
| 질문 매칭 | `build_question_map(questions, observations)`가 이미 전체 observation 사용 | 그대로 유지. 원문 질문·기존 매칭·문헌 판단을 다시 만들지 않음 |
| comparison 질문 | 선정 observation의 같은 consumer state에서만 상속 | 전체 observation에서 상속. card/finding ID와 수치는 그대로 |
| 모듈 | 기존 packet 모듈은 요약 관측 범위 | `build_module_evidence_index`를 전체 observation에 적용한 별도 membership CSV. 기술적 패턴 그룹이지 kinase family가 아님 |
| 시간 | `project_temporal`이 findings/preview cards에서 대상 결정 | 같은 projector에 명시적인 subjects와 links-only 출력 추가. 동일 key/scope/track/시간 검증 재사용. 전체 카드 및 raw-only form+scope에 적용 |
| 단백질·방법 | 선정 PTM에 연결된 context만 요약에서 보임 | 원래 protein contrast 및 native method result 키로 직접 series 연결. Native 방법에 새 onset/peak를 계산하지 않음 |
| 전체 접근 | M1 catalog, query, resolver, CSV loader, source key registry | 그대로 사용. `evidence_id_for`로 기존 ID 규칙을 공통화. 양적 값은 원본에 유지 |
| 작성·인용 | preview card 중심 지침 | 전체 분모→질문별 연결/미연결→필요 원본→요약→시간/방법/문헌 순서. run/catalog/table/key/typed ID를 검증하는 CLI |
| 발행·재현 | `revise_temporal`, `write_reader`, `seal_archive`, reader replay | `whole_only` 개정으로 실제 표를 보존하고 새 run 생성. 새 helper를 `READER_CODE_FILES`에 등록; 과학 augmentation cache 코드와 분리 |

`astra_reader_full.py`는 기존 함수 사이의 얇은 투영·직렬화 경계가 필요하여 추가했다. 수치 배열/card JSON을 전체 인덱스에 복제하지 않는다. 같은 질문·원본 key·역할은 하나의 연결로 저장하고 `subject_evidence_ids_json`으로 N:M 관측 관계를 보존한다. 요약 개수나 표시명이 ID의 재료가 되지 않는다.

실제 호출 경로:

- 일반 v6: 기존 `augment → project_card_inputs → build_reader_tables → attach_full → write_reader → M1 write_evidence_access → write_full`.
- 실제 저장 패키지 개정: `revise_temporal(whole_only=True) → read_tables → attach_full → validate_reader → write_tables → write_reader → seal_archive → atomic pointer`.
- Offline: 패키지 자체 `reproducibility/code`만 import, 저장 원본/card/질문으로 새 full_* 투영 재구성. full_* 결과를 입력으로 되읽어 정답으로 쓰지 않는다. 네트워크 차단. 과학 계산 replay와 구분한다.

## 산출물과 의미

- `reader/full_question_links.csv`: 원래 질문 matcher의 전체 observation 관계, comparison 및 확인 가능한 parent/detection/method/제한/반대 방향 관측/기존 문헌 context. Raw-only는 가짜 카드 대신 실제 form key에 `unresolved` 관계를 남긴다.
- `reader/full_temporal_links.csv`, `full_temporal_subjects.csv`: form/card, series, track, source key로 연결. 원본 feature·interval·cowave·membership·contribution의 수치는 resolver로 읽는다.
- `reader/full_module_membership.csv`: 기존 패턴 grouping의 전체 2,159 observation membership.
- `reader/full_evidence_summary.json`, `FULL_EVIDENCE.md`: 분모, 연결·미연결 범위, 제한과 조회/인용 안내.
- Authoring packet과 question map에는 이 경로 및 필터를 넣는다. 기존 `finding_ids`, preview module, 선정 15개와 문헌 상태는 유지한다.

Native method membership에서 `selected=true`이며 결과의 `membership_ids`와 `input_universe_hash`가 일치하는 실제 연결만 method 결과 context로 연결한다. 미선정 membership은 원본/catalog에 전부 보존하며 기여도로 취급하지 않는다. Scope 밖의 gene 이름·assay label로 관계를 추정하지 않는다. 연결 가능하다는 사실은 읽음·검토·독립 검증 또는 calibration 완료가 아니다.

## 검증 계약

- 실제 개정: quant 22 CSV 및 기존 science/kinase/temporal/figures/reference/adapter 보존. 전체 manifest의 변경은 reader·작성 지침·코드 snapshot·revision provenance 허용 목록으로 제한.
- 14,658 카드의 ID·값·NA·scope를 대조. 허용 변화는 comparison `question_ids`; findings의 ID·순서와 원 질문·문헌 결과 보존.
- 실제 기존 selection 함수로 maximum 5/15/50/0을 적용. Preview 카드도 빈 경우를 포함하여 전체 질문·시간·모듈 투영 hash가 같아야 함.
- 신규 source FK 전수 검사. Typed citation은 타 run, 타 catalog, 틀린 ID·key·hash를 거절. 출처 검증은 문장 의미 승인과 별개.
- 작은 fixture: 복수 reference/track, 불규칙 시간, 동명 다른 form/taxon, 결측, ambiguous series, 선정/미선정 native membership, empty-selected, 실패 pointer 보호.
- 관련 회귀의 최종 고유 결과: **42 passed, 11 warnings, skip 0**. 경고는 기존 pandas 빈/all-NA concat FutureWarning. 개발 중 발견한 문헌-only 개정의 M1 scope 문구 복귀를 수정해 해당 replay 회귀도 포함했다. 중간 실패·중단·반복 실행은 통과 수에 합산하지 않는다.
- 실제 scientific recalculation, PhosX/permutation 재실행, reference 갱신, 외부 신규 검색은 0회. 합성 기존 v6 생성/과학 replay 회귀는 실제 HIRc-B 재계산과 구분한다.

## 실행 명령

아래 Python은 이번 검증에 사용한 기존 환경이다. 실제 경로·결과·SHA는 함께 있는 `FULL_EVIDENCE_M2_RESULTS.json`에 고정한다.

```sh
PYTHONPATH=. MPLCONFIGDIR=/tmp/ptm-m1-mpl codex-inputs/round11-20261010/runtime/bin/python scripts/validate_full_evidence_m2.py --source codex-inputs/full-evidence-m1/revision/enrichment_free_runs/g0-1cc3b1ebab05499d95f7f8f3cc42bbb0 --output codex-inputs/full-evidence-m2/verified --selection-sweep
```

패키지의 `reader/EVIDENCE_ACCESS.md`에 있는 기존 query/resolve/source CLI와 `reader/FULL_EVIDENCE.md`의 typed citation CLI를 이용한다. 큰 source pin 전체를 먼저 읽을 필요는 없다. 분모와 미연결 범위를 확인한 뒤 필요한 원본 행을 조회한다.

## 남은 범위

M2는 요약과 무관한 질문·시간·module 접근과 typed 인용을 제공한다. 기존 question matcher의 의미 판정 능력을 확장하지 않았다. 카드로 표현할 수 없는 raw-only form의 질문 관련성은 미해결로 유지한다. 직접 키로 연결되지 않은 방법/문헌 관계도 생성하지 않는다.

기존 문헌 실행/비교 결과만 보존한다. 미선정 관측의 문헌 review subject 계획과 신규 실제 RAG/비교는 M3/M4이며 수행하지 않았다. `review_status=not_recorded`이고 외부 Astra의 전체 읽기·생물학적 검토를 주장하지 않는다. Localization 미측정, technical replication, no-call/uncalibrated, mapping ambiguity 및 parent/missingness 제한은 그대로다.

이번 변경은 로컬 커밋으로 종료한다. 커밋 SHA는 `git log -1 --format=%H -- docs/astra_evidence_integration/FULL_EVIDENCE_M2_KO.md` 및 최종 응답에서 확인할 수 있다. main 원격 통합/push, 서비스 배포, flag 변경은 별도 실행하지 않았다.

## 최종 실제 실행 결과

- 새 run: `g0-24d53aad7f924819bde2389b8316c241` / 부모: `g0-1cc3b1ebab05499d95f7f8f3cc42bbb0`.
- ZIP: `codex-inputs/full-evidence-m2/verified/revision/astra_analysis_package_g0-24d53aad7f924819bde2389b8316c241.zip`.
- ZIP SHA-256: `c98a9e2b7b756c93efa3b8d6eb579b69599ccc9d10301707298c2423383a90aa` (377,344,330 bytes).
- Reader 진입: `codex-inputs/full-evidence-m2/verified/revision/enrichment_free_runs/g0-24d53aad7f924819bde2389b8316c241/reader/FULL_EVIDENCE.md`.
- 정량 **22 CSV** 및 과학·그림·reference·adapter 등 감사 대상 **111파일 byte-identical**. 이 목록 밖의 원 manifest 파일도 변경 허용 목록과 전수 대조했으며 예상 외 변경 0. 허용 변경 파일 목록·hash는 RESULTS.json에 기록.
- **14,658 카드**의 수치/NA/ID/scope 보존. comparison **12,413개**의 질문 상속만 변경. 기존 15 findings의 ID/순서·원 질문·문헌 pin/결과 및 기존 요약 temporal JSON 보존.
- 전체 observation **2,159개**, comparison **12,499개**; 전체 module **30개 / 2,159 membership**.
- 시간 subject **61,833개**: observation 2,159, raw-only form scope 665, protein contrast 57,150, method result 1,859. 서로 다른 grain의 표현 수이지 독립 생물학적 관측 수가 아님.
- 전체 질문 연결 **161,342행**, 시간 연결 **354,221행**. 665 raw-only form의 질문 관련성은 unresolved. 현재 원 질문 BQ-001은 기존 matcher에서 observation 2,159개와 연결되며, 이 의미 판정을 M2가 개선했다고 주장하지 않음.
- Native membership 원본 **642,360행**, selected **9,571행**. 미선정 원본은 catalog에 유지하고 기여도 관계로 승격하지 않음.
- 실제 selection sweep의 5/15/50/0 선택 결과에서 네 전체 투영의 hash가 모두 동일. 빈 preview/legacy finding_ids도 시험함.
- 신규 offline reader replay **15파일 byte-identical**, package code만 사용, 네트워크 0회. 기존 M1 access replay도 **7파일 byte-identical**. 실제 과학 계산/PhosX replay를 다시 수행한 것은 아님.
- 패키지 자체 query CLI 및 typed citation CLI 통과. 상대 링크 **97개** 존재 확인. 새 코드 snapshot 6파일은 checkout bytes와 일치.
- 최종 실제 생성·보존·selection sweep·reader replay 포함 538.95초. 실행 로그는 `codex-inputs/full-evidence-m2/verified-validation.log`.

### 대표 미선정/원본 추적

| 사례 | 원본 key / 보존 값 | 추가 접근 |
| --- | --- | --- |
| MAPK1 | `form_97aa4b58cee5c391`, 5분 A 2.9447374937251847; 60분 NA | 미선정 observation card → full 질문/모듈/temporal feature·interval → 원본 contrast. NA를 보간하지 않음 |
| GSK3A | `form_6618452f34b3cbbc`, 30분 A 1.352604309210987 | 미선정 카드와 전체 시간 근거 인용. 자체 PTM을 kinase activity로 바꾸지 않음 |
| PTPRK | `form_92f581e44d9b44cf`, 180분 U_joint −0.3642186006815482 / P_joint −0.39749589284251385 / A 0.033277292160964755 | 원래 joint 값과 별도 PG parent 시간 context를 구분해 원본 key로 조회 |
| MAPK3 / IRS1 | `form_eeaed22a5119b2f5` / `form_9951a8944f668c17` | mapping 제외·baseline 미검출·NA·post-reference 원본 상태 유지; card 생성이나 baseline FC를 강제하지 않음 |

실제 card/feature/interval key와 원본 vector/NA mask는 RESULTS.json의 `cli_and_links.examples` 및 `examples`에 있다. Typed citation의 `source_anchor_validated`는 문헌/기전 의미 승인 상태가 아니다. 이번 실제 문헌 context에 새로운 승인 비교가 없으므로 unresolved를 유지하며, 기존 검색·비교 실행 상태 자체는 packet에 보존했다.
