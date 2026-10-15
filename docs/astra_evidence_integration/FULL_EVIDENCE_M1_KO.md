# 전체 근거 접근 M1 — 구현·실제 g10 검증

검증일: 2026-10-15–16 KST. **M1만 완료.** 전체 질문·시간·작성 경로 확장(M2), 문헌 대상 계획(M3), 신규 실제 문헌 비교(M4)는 수행하지 않았다. 전체 접근 가능성을 전체 검토 완료로 표시하지 않는다.

## 작업 기준과 코드 조사

- 착수 브랜치 `main`, HEAD `085ffe096bb53ad8f459e77fd608c8d74254ce96`. 적용되는 AGENTS.md는 발견되지 않았다. 착수 시 미커밋 항목은 `codex-inputs/`뿐이며 보존했다.
- 실제 파일: `/Users/josephk/Downloads/astra_analysis_package_g10-5c171c84a6e34d14b6d83b203c8aa99a.zip`.
- ZIP SHA-256: `5c3ee029751df25adbc7d284f7f28a6a91d1e89ebdd1ac469fda98fad47f6566` — 지시서와 일치한다. `(1)` 없는 파일명의 실제 bytes를 검사했다.
- 원 run `g10-5c171c84a6e34d14b6d83b203c8aa99a`, archive provenance의 Order 89, `astra_analysis.v6`. 운영 DB의 현재 Order 상태를 조회한 것은 아니다.
- g10의 `research_questions.py`, `reader_authoring.py`, `astra_reader_temporal.py`는 checkout과 동일했다. `astra_reader.py`, `astra_literature.py`, `finding_literature.py`, `astra_package.py`는 달랐다. g10에는 추가 읽기 안내와 문헌 단계 변경이 있다. checkout을 snapshot으로 되돌리거나 해당 기능을 다시 구현하지 않았다.
- g10의 v6 엔진도 현재 checkout과 달랐으며 그대로 보존했다. 기존 질문 매칭은 전체 observation을 이미 사용한다. 이번 변경은 질문 매칭을 고치는 작업이 아니다. 기존 `maximum=15`도 유지했다.

## 최소 연결과 재사용

| 기존 자산 | 현재 호출과 원인 | M1 변경 |
| --- | --- | --- |
| `astra_evidence_v6.augment → project_card_inputs → build_reader_tables` | 전체 카드/adapter가 있으나 packet은 선정 preview | packet에 전체 catalog 계약을 추가 |
| `write_tables`, data dictionary의 `unique_key`/dtype/단위 | 원본 키 등록은 있으나 전체 조회 인터페이스 없음 | 등록 키를 재사용하여 저장 bytes 기준 catalog/index/link 생성 |
| `astra_card_inputs` identity, `stable_id`, `source_row` | ID·표시명·NA 의미가 이미 정의됨 | ID/표시명을 재사용. 새 ID는 source+canonical key만 사용 |
| `ContrastEstimator.metadata`가 저장한 대비 metadata | 숫자 시간/arm/reference/pairing이 이미 존재 | 해당 필드를 투영하고 scope→숫자 시간→stable ID로 정렬. 새 시간 parser 없음 |
| `astra_reader.write_reader → write_artifacts → seal_archive` | 정상 v6 발행 경계 | 저장 CSV와 dictionary가 준비된 뒤 전체 인덱스를 생성·검증 |
| `read_tables`, `revise_temporal`, `_copy_package`, `seal_archive` | immutable reader 개정과 atomic pointer 교체가 존재 | `access_only=True`로 기존 해석·문헌·그림을 다시 쓰지 않는 M1 개정 |
| `replay_astra_reader.py` | 패키지 자체 코드, 네트워크 금지 | 정상 reader replay와 M1 저장표 투영 replay를 구분 |

새 helper `astra_evidence_catalog.py`가 필요한 이유는 기존 카드 엔진이나 temporal projector에 없는 **전체 원본 locator·pagination·키/hash 검증**을 분리하기 위해서다. 새 DB/cache/scheduler/정량/선정 엔진은 없다. 과학 augmentation cache가 엔진 파일 hash를 쓰므로 엔진 파일은 수정하지 않고, helper를 패키지의 `READER_CODE_FILES`와 별도 reader code dependency에 등록했다. 표시용 helper 등록이 과학 cache를 무효화하지 않으며, 기존 augmentation 재사용/실제 정책 변경 시 무효화 회귀도 통과했다. 기존 CSV round-trip 로더를 column/chunk projection으로 확장하여 `read_tables`와 공유한다.

Production 변경 파일은 `astra_evidence_catalog.py`, `astra_reader.py`, `astra_reader_revision.py`, `astra_package.py`다. 기존 writer에서 reader-only 테이블을 쓸 때 `unique_key`가 빠지는 경계도 기존 v6 key registry를 사용하도록 수정했다. 조회/개정 코드 외의 specificity·정량·temporal·문헌 판단 코드는 변경하지 않았다.

## 전체 접근 계약과 실제 분모

`reader/evidence_catalog.json`은 기존 79개 CSV의 경로·hash·열/dtype·키·단위·행 수를 등록한다. 아래 10개 source는 전 행을 `evidence_index.csv`로 조회할 수 있다. 나머지 source는 catalog의 정확한 key로 `source` 명령/`source_rows`에서 읽는다. 원본 카드 JSON이나 수치 배열은 인덱스에 복제하지 않는다.

| 인덱스 source | 행 수 = 고유 key 수 |
| --- | ---: |
| reader/cards | 14,658 |
| reader/coverage | 16,944 |
| reader_adapter/form_contrasts | 16,944 |
| quant/summary | 2,824 |
| quant/comparisons | 16,944 |
| quant/protein_contrasts | 57,150 |
| quant/detection | 16,944 |
| evidence/emergence_evidence | 19,768 |
| kinase/method_scores | 1,859 |
| science/inference_results | 11,502 |

총 **175,537개 표현 레코드**, **205,885개 저장 관계**. 카드와 원본 등 같은 관측의 여러 표현을 포함하므로 독립 관측 수로 더하지 않는다. 필수 source의 누락·중복 key·빠진 인덱스 key는 0이다. catalog 전체 source의 기술적 key 중복도 검사했다.

실제 회계: 2,824 forms, observation 카드 2,159개, comparison 카드 12,499개. **12,499 + 455 결측 시점 + 3,990 보류 행 = 16,944**. 카드가 없는 보류 form 665개. primary A 13,704행, 카드 grid 12,954행과 다른 분모다. method 1,859행은 PhosX 1,818행과 repository z-score 41행이다.

`selected_for_summary`는 기존 선정 표시만 반영한다. 기본 조회는 미선정/withheld/no-call을 숨기지 않는다. 모든 항목의 `review_status=not_recorded`다. 이는 기존 문헌 비교 상태를 초기화하는 필드가 아니라 **이 접근 기능을 이용한 검토 실행이 기록되지 않았음**을 뜻한다. 원래 문헌 상태는 packet/원본에 그대로 남는다.

관계는 card→adapter→원본 대비, form 표현, 동일 실험 PG parent, 실제 precursor membership, 저장된 substrate contribution을 구분한다. `resolved`는 원본 키가 해석됐다는 뜻이며 site localization이나 인과 관계를 확정한다는 뜻이 아니다. 생물학적 다중 mapping은 원본 identity/mapping과 제한을 유지한다.

## 실제 조회 사례

| 사례 | 확인 결과 |
| --- | --- |
| 미선정 MAPK1 `form_97aa4b58cee5c391` | 5분 A `2.9447374937251847`; 60분 U/P/A는 모두 NA, included=false |
| 미선정 GSK3A `form_6618452f34b3cbbc` | 30분 A `1.352604309210987`; 자체 PTM을 kinase 활성으로 연결하지 않음 |
| PTPRK `form_92f581e44d9b44cf` | 180분 U `-0.3642186006815482`, P `-0.39749589284251385`, A `0.033277292160964755`; 정확한 PG×contrast parent 링크 |
| TAOK1 `form_09766dc39811d4c7` | 저장 contribution 후보 9개와 precursor membership 1개를 다른 관계로 반환 |
| IRS1 `form_9951a8944f668c17` | baseline 미검출, 원래 대비 U/P/A NA 및 별도 5분 post-reference 필드 보존 |
| MAPK3 `form_eeaed22a5119b2f5` | 일부 유한 A가 있어도 included=false 및 다중 gene mapping 제외 사유 보존 |
| INSR 공유 form `form_d4f68593541e8e86` | 공유 mapping/미검출 및 NA 보존. human transgene 단독 관측으로 바꾸지 않음 |
| AKT1/2/3 assay 결과 | 각 6개 contrast 모두 `insufficient_coverage`; 기존 p/q·score·no-call 의미 유지 |

실제 패키지 자체 Python 모듈로 실행한 명령(패키지 루트, pandas 설치 환경):

```sh
PYTHONPATH=reproducibility/code python -m ptm_shared.astra_evidence_catalog --package . query --filters '{"entity":"MAPK1"}' --page-size 5
PYTHONPATH=reproducibility/code python -m ptm_shared.astra_evidence_catalog --package . query --filters '{"form_id":"form_97aa4b58cee5c391","source_table":"quant/comparisons.csv"}'
```

첫 조회는 전체 표현 107개 중 5개와 다음 cursor를 반환한다. 두 번째는 시간순 6개 원본 대비를 반환한다. 반환된 실제 evidence ID 6개로 `resolve`도 실행했다. 시간/값/NA는 원본 CSV와 동일하다. `source TABLE --key JSON`, `links ID` 사용법은 패키지 `reader/EVIDENCE_ACCESS.md`에 있다. cursor는 catalog와 filter에 묶이며, query session 도중 원본 파일이 변해도 hash 불일치를 검출한다.

## 발행·replay·보존

- 실제 새 run: **`g0-1cc3b1ebab05499d95f7f8f3cc42bbb0`**.
- ZIP: `codex-inputs/full-evidence-m1/revision/astra_analysis_package_g0-1cc3b1ebab05499d95f7f8f3cc42bbb0.zip`.
- SHA-256: **`206384f8399e0af38ff01fc644e8b8bd7844a943cbdda46a206784cb80be21d2`**.
- manifest 대상 243개, dictionary CSV 81개(기존 79 + index/links). 개정 처리 약 192.3초. 과학 계산 시간이 아니다.
- 실제 경로: 검증된 g10 → `revise_temporal(access_only=True)` → 기존 manifest 복사 → 저장 packet에 access 계약 → `write_reader`/`write_evidence_access` → FK/hash 검사 → `seal_archive` → 별도 로컬 output root의 성공 pointer.
- `compute_science`, `astra_literature.collect`, socket 연결을 예외로 막고 실행했다. 정량·PhosX·permutation·temporal 계산·reference 갱신·신규 문헌 검색은 **0회**다.
- 정상 v6 발행 경로는 기존 합성 PR/PG/FASTA fixture로 `engine.run → augment → build_reader_tables → write_artifacts`에서 실제 생성되었음을 spy와 패키지 검사로 검증했다. 실제 g10은 저장표 reader 개정이며 새 운영/UI 실행이 아니다.
- 정량 22 CSV, 기존 science/kinase/temporal 원본, 카드/선정/coverage/문헌 원본과 source/reference pins, 그림 관련 **31파일**을 보존했다. 주요 보존 집합 **117파일**의 양쪽 hash가 일치한다. 전체 baseline manifest 파일 diff도 허용 목록 이외 변화가 없음을 검사했다. 원본 ZIP과 입력 bytes는 유지했다.
- 의도된 기존 변경: `reader/packet.csv`, `reader/authoring_packet.json`, `reader/READ_ME.md`, START_HERE/evidence_report 진입 링크, provenance/plan/dictionary 및 3개 reader 관련 코드 snapshot. 새 파일은 access artifact 4개, helper 코드, 개정 provenance/ledger 3개다. 원래 질문/선정/문헌/temporal 해석을 다시 생성하지 않았다. 새 reader용 경계 코드 4개 외 g10의 실행 코드는 유지했다. 특히 g10의 v6 엔진 snapshot은 byte-identical이다.
- **신규 offline reader replay:** 최종 패키지 자체 코드로 index/catalog/links/guide/packet 등 7파일 byte-identical. M1 투영 재구성 검사이며 과거 문헌 판단의 재검증이나 과학 계산 replay가 아니다. READ_ME의 기존 본문은 보존 후 access 안내의 멱등성을 검사한다.
- **구형 g10 reader replay:** 자체 코드로 기존 21파일 byte-identical, 16,944 source 행/14,658 카드/15 findings 값·NA·mask·ID 검사 통과. catalog 없는 패키지는 자동 변경하지 않으며 새 helper에서 `catalog_available=false`로 안내한다.
- START_HERE/READ_ME/access 안내에서 실제 상대 링크 82개를 확인했다. 원본 키 기반 조회에서 invalid ID/key/hash/path와 duplicate/FK 실패를 정상 빈 결과로 숨기지 않는다.

## 테스트 결과와 범위

최종 고유 **38 tests passed**, skip 0 (155.37초). 중간 재실행 횟수는 합산하지 않았다. 기존 pandas 경고 11건은 테스트 실패나 skip이 아니다.

실행: `test_astra_evidence_catalog.py`, `test_astra_reader.py`, `test_reader_reading_guidance.py`, `test_astra_reader_temporal.py`, `test_astra_literature.py`, `test_astra_augmentation_cache.py`.

| 요구 | 결과와 검증 종류 |
| --- | --- |
| M1-T1 전수 회계 | 실제 g10 필수 key 집합 완전 일치, 79 source 기술키 검사 |
| M1-T2 요약 독립성 | 합성 maximum 5/15/50/empty: ID·source refs·분모·관계 동일, 표시 플래그만 변화 |
| M1-T3 페이지 독립성 | 합성 1/7/10000, 실제 전체 701/10000: 동일 전체 ID 순서·개수, 중복/누락 0 |
| M1-T4 미선정 조회 | 실제 MAPK1/GSK3A와 package CLI 확인 |
| M1-T5 보류 접근 | 실제 3,990행과 baseline 미검출 사례, 합성 raw-only/mixed/parent 결측 |
| M1-T6 방법 의미 | 실제 AKT 18행의 insufficient_coverage, 원래 no-call/track/status 유지 |
| M1-T7 무결성 | invalid ID/key/hash/path/cursor, 중복 key, broken FK 거부. N:M와 동일 이름의 종/form 분리 |
| M1-T8 정렬 | 합성 비등간격/동시점/다른 arm·reference/섞인 행과 실제 숫자 시간 검사 |
| M1-T9 보존 | 117개 주요 파일 및 전체 manifest 허용 diff, 과학 fingerprint 불변 검사 |
| M1-T10 발행/replay | 합성 일반 v6 발행, 실제 immutable 개정, 신·구 reader replay; 일반 발행/개정 실패 시 기존 성공 pointer 보존 |

검사 중 reader-only dictionary의 key 누락을 실제 발견하여 공통 writer에서 수정했다. 기존 테스트의 stale 문서 link label, 새 artifact 수, 부분 unit fixture의 누락 metadata도 현재 계약에 맞췄다. 문헌 unit 테스트는 mock retriever/model이며 신규 외부 검색이 아니다. 전체 전처리/운영 배포/실제 과학 method replay는 실행하지 않았다.

## 남은 범위와 Git 상태

M2의 전체 comparison 질문 상속·module/temporal 투영·typed citation 검증, M3/M4의 미선정 문헌 대상/실행은 미구현이다. 기존 downstream 일부는 계속 선정 findings에 의존한다. 접근 가능해진 근거가 자동으로 문헌 비교되거나 실제 AI에게 검토되었다고 표시하지 않는다. Localization 미측정, 기술 반복, mapping ambiguity, calibration 부재/no-call은 그대로다.

이 문서와 결과 JSON을 포함한 **M1 관련 변경만 로컬 커밋**한다. 커밋 SHA는 완료 응답과 `git log -1 --format=%H -- docs/astra_evidence_integration/FULL_EVIDENCE_M1_KO.md`로 확인할 수 있다. 별도 main 통합/fetch/push, 운영 배포, flag 변경은 하지 않았다. 미커밋 입력·ZIP·검증 출력은 커밋에서 제외했다.
