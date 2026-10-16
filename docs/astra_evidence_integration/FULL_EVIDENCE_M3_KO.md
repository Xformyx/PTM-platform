# 전체 근거 M3 완료 보고

기준 HEAD: `4a29b769a106c513a6e39a33aaab948f9369699a` (main, M1 포함).
착수 미커밋 항목은 `codex-inputs/`뿐이며 보존했다. 적용 가능한 AGENTS.md는 발견되지 않았다.
이번 범위는 **전체 문헌 검토 대상 계획·typed 입력·명시적 실행 경계**다. 새 실제 문헌 검색/LLM 비교와 M4는 수행하지 않았다.

## 원인과 변경

기존 `astra_literature.inputs`는 `reader/findings`의 ID로 packet preview 카드만 선택했다.
M1 catalog/resolver와 M2 전체 질문/시간/인용 기능은 이미 있어 재구현하지 않았다.
새 `astra_literature_review.py`는 전체 인덱스의 원본 키를 문헌 대상 ID로 연결한다.
기존에 독립적인 문헌 대상 계획/typed readout/대상별 실행 cache 계약이 없어 이 경계만 추가했다.
전체 카드 JSON·수치 배열은 계획에 복제하지 않는다. 조회할 때 M1 resolver로 읽는다.

- `review_subject_id`는 원본 table+canonical key+schema로 결정하며 선정 순위/label/행 번호를 사용하지 않는다.
- observation은 실제 기존 카드를 `astra_literature.inputs(observation_cards=...)`에 전달한다.
- raw/withheld, protein, detection/emergence, method, inference는 원본 행과 과학적 제한을 가진 typed 입력이다. 가짜 observation/precursor/site/taxon을 만들지 않는다.
- 기존 finding ID는 observation alias다. `selected_finding_ids` pin의 의미·내용은 유지하고 새로운 실행은 `literature_subject_execution.v1.requested_subject_ids`를 사용한다.
- 요청 없으면 `not_requested`. 명시적 실행은 `not_searched`, `budget_deferred`, `retrieval_failed`, `no_hit`, `retrieved`, 비교 상태, 의미 검토 상태를 분리한다.
- `max_subjects`는 실행량만 제한한다. 기존 layer quota/top-k 및 query/model budget과 구분한다. 부분 검색 실패/예산 미완료는 비교가 끝나도 재개 목록에 남긴다.
- cache는 원본 값/scope/질문·문헌 pin·model/prompt/code/실행 계약에 묶인 대상별 기존 `cached_stage`다. summary 표시와 기존 15개 aggregate cache를 사용하지 않는다.

## 재사용과 실제 호출

일반 v6 `augment → project_card_inputs → build_reader_tables → attach_review_plan → write_reader → write_review_plan`.
저장 결과 개정은 `revise_temporal(review_plan_only=True) → read_tables → 기존 manifest 복사 → write_reader → seal_archive`.
M2 질문 링크를 계획에 참조하고, 기존 시간/인용 안내와 source key를 유지한다. 신규 질문/시간 분석을 만들지 않는다.
실행 요청은 M1 `EvidenceCatalog.resolve/source_rows` → 기존 `astra_literature.inputs` 또는 typed 원본 →
`retrieve_finding_literature` → 기존 RAGRetriever/LLMClient 경계·quote/context 검증 → `_export_result` → 기존 cache를 사용한다.
M3는 실제 실행을 요청하지 않는다. fixture만 이 전체 검색/비교 경계를 호출했다.
M2 `validate_citations`로 실제 대표 원본 anchor 3건을 검증했다. 인용 유효성은 의미 승인과 다르다.

Production 변경: `ptm_shared/astra_literature_review.py, ptm_shared/astra_literature.py, ptm_shared/finding_literature.py, ptm_shared/astra_reader.py, ptm_shared/astra_package.py, ptm_shared/astra_reader_revision.py`.
보조 변경: `scripts/replay_astra_reader.py`, `scripts/validate_full_evidence_m3.py`, 관련 회귀 tests.
새 reader helper는 `READER_CODE_FILES`, dictionary key, manifest와 code provenance에 등록했다.

## 실제 패키지와 분모

직접 사용한 기준은 g10에서 파생된 **M2 run `g0-24d53aad7f924819bde2389b8316c241`**다. 다른 run을 g10으로 보고하지 않는다.
기준 ZIP SHA-256: `c98a9e2b7b756c93efa3b8d6eb579b69599ccc9d10301707298c2423383a90aa`.
운영 Order/DB/UI를 새로 조회하지 않았다.

신규 run: `g0-d09c6d03835a46248e5bdb6fe9e07e8c`

ZIP: `codex-inputs/full-evidence-m3/final/revision/astra_analysis_package_g0-d09c6d03835a46248e5bdb6fe9e07e8c.zip`

SHA-256: `ac6d13fc0ee02959833929c2257bf928d4aa375b7742eb39c6cf9b26870b10d3`

원본 카드 14,658개 전체와 필수 원본을 연결해 158,593개 대상 표현을 만들었다.
이들은 N:M 원본/카드 표현이며 독립 관측 수가 아니다. disposition 중복 행은 M1 관계로 접근한다.

| 대상 유형 | 계획 행 수 |
| --- | ---: |
| comparison | 12,499 |
| detection | 16,944 |
| emergence | 19,768 |
| form | 2,824 |
| inference | 11,502 |
| method_result | 1,859 |
| observation | 2,159 |
| protein | 57,150 |
| ptm_contrast | 16,944 |
| raw_ptm | 16,944 |

모든 새 대상의 이번 실행 상태는 `not_requested`다. 기존 15개 문헌 실행은 기존 pin/search 파일이 authority이며 초기화하지 않았다.
실제 자료에서는 새로운 외부 문헌 읽음/검색/LLM 비교/의미 승인 모두 **0회**다.

| 사례 | review subject ID | 원본 evidence ID | 입력 유형 |
| --- | --- | --- | --- |
| MAPK1 | `review_subject_55b247e34a7048934295` | `reader_card_01c224da2d74475143c2` | observation |
| GSK3A | `review_subject_093b33f4f8cff43355e7` | `reader_card_ce90380fcc2732632381` | observation |
| MAPK3 | `review_subject_70c0a0b67f80c422c6c9` | `card_row_b629b5bc0c2130c8eb41` | raw_ptm |
| IRS1 | `review_subject_7816d0ceaf8bb04a1b92` | `card_row_9d13f4de43c56271bba7` | raw_ptm |
| INSR_shared | `review_subject_15a9fc7b8339338e7097` | `card_row_e854465540ed84dda6cf` | raw_ptm |

MAPK1/GSK3A는 미선정 관측으로도 BQ-001 및 원본 trajectory에 접근한다.
MAPK3 다중 gene mapping의 withheld/included=false, IRS1 baseline 미검출, INSR 공유 mapping 제한을 유지한다.
Protein·detection·method·no-call 대표 입력도 실제 원본 값을 해석했다. 값은 `RESOLVED_EXAMPLES.json`에 감사용으로 저장했다(미커밋).

## 보존과 replay

기존 manifest 250개 중 **232개 byte-identical**, 의도된 변경 18개, 신규 4개.
정량 **22개 CSV**, science/kinase/temporal 원본, 그림, M2 전체 연결, cards/findings와 질문, 문헌 선택·비교 pin/결과가 보존됐다.
Packet에서는 M3 계획 참조와 작성 규칙 두 확장만 바뀌었다. 숫자/NA/mask/ID/과학적 상태를 재계산하지 않았다.
허용 변경 파일·before/after hash 전수 목록은 `FULL_EVIDENCE_M3_RESULTS.json`에 있다.

- summary maximum 5/15/50/empty 표시를 바꿔도 계획 키/분모/eligibility/질문/priority hash 동일.
- 새 패키지 자체 코드로 **10개 reader 산출물 byte-identical**. 네트워크/LLM/과학 재계산 0회.
- 구 M2 패키지 자체 코드 reader replay **15개 byte-identical**.
- 상대 링크 89개 검사. package-local CLI로 미선정 MAPK1 typed 입력 조회 성공.
- 실제 개정·검증 시간 308.95초. 이전 개발 검증 시간을 합산하지 않았다.
- 과학 계산/PhosX method replay는 이번에 수행하지 않았다. 이번 결과는 reader/계획 재구성 검증이다.

실행한 CLI는 다음 형식이며 `PACKAGE`에는 위 ZIP을 푼 경로를 사용한다.

```sh
PYTHONPATH=PACKAGE/reproducibility/code python -m ptm_shared.astra_literature_review --package PACKAGE --evidence-id reader_card_01c224da2d74475143c2
```

## 테스트 결과

최종 경계 전체 49 passed / 0 failed / 0 skipped (81.40초).
부분 검색 재개 수정 후 M3 tests 8 passed / 0 failed / 0 skipped (8.22초), 이 중 7개는 앞 suite와 중복이다.
따라서 고유 통과 **50개**이며 57개로 합산하지 않는다. pandas의 기존 empty/all-NA concat FutureWarning은 남아 있다.
실제 서비스 대신 주입한 fixture에서 미선정 검색·counterevidence·본문 anchor·비교·동결 replay,
protein→site 승격 금지, 누락 gene guard, 실패/no-hit/예산·재개·cache 격리·export 권한·실패 pointer 보존을 검증했다.
실제 문헌 비교 성공이나 생물학적 정확도 검증으로 확대하지 않는다.

## 남는 범위와 Git

M4의 실제 RAG/문헌 비교는 미구현·미실행이다. 운영 배포/flag 변경/UI 실행도 이번 범위가 아니다.
계획에 접근 가능하다는 것은 해당 원문을 읽었다거나 semantic approval을 받았다는 뜻이 아니다.
Localization 미측정, technical 반복, calibration/no-call 제한은 그대로다.
기존 문헌 실행의 과거 scope는 보존되며 신규 subject 실행 결과로 자동 대체하지 않는다.
새 실제 검색을 수행하려면 기존 검색 가능한 pin/환경과 명시적 대상·사유·예산이 필요하다.

요청대로 현재 main 작업 기반에 **로컬 커밋만** 남긴다. 원격 fetch/통합/push, 배포, flag 변경 없음.
이 보고서를 포함한 커밋 SHA는 최종 응답 및 미커밋 `codex-inputs/full-evidence-m3/LOCAL_COMMIT.json`에 기록한다.
입력 ZIP/PDF/DB/임시 산출물은 커밋하지 않는다.
