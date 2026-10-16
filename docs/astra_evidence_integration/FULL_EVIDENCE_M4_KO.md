# 전체 근거 접근 M4 — 실제 문헌 실행과 불변 reader 개정

착수 HEAD: `86314db33e6b0827b1670e280942fa36db11eed1` (main). 사용자 미커밋 `codex-inputs/`는 보존했다. 운영 DB·배포·flag를 변경하지 않았고 push하지 않는다. 실제 접근 복구, 명시적 대상 실행과 reader 개정을 분리해 기록한다.

## 기존 경로와 최소 연결

M1 `EvidenceCatalog.resolve/source_rows`, M2 `validate_citations`와 기존 질문·시간 연결, M3 `resolve_subjects → execute_review → retrieve_finding_literature → RAGRetriever/LLMClient → _export_result → cached_stage`를 재사용한다. 새 검색 엔진·문서 parser·과학 추정기는 없다.

M3에는 실행 함수가 있었으나 typed 실행 pin을 새 reader/ZIP에 고정하는 경로가 없었다. 같은 모듈에 frozen projection/writer/validator를 추가하고 기존 `revise_temporal → write_reader → seal_archive`에 선택적 `review_execution` 인자를 연결했다. writer/replay는 retrieval/LLM을 호출하지 않는다. 요청 범위가 미완료이면 발행을 거절해 기존 성공 pointer를 보존한다. 전체 eligibility 계획은 그대로 유지하고 실행표는 명시적 요청 대상만 기록한다.

Production 변경: `astra_literature_review.py`, `astra_reader.py`, `astra_reader_revision.py`, `astra_package.py`. 기존 replay CLI와 좁은 검증 스크립트·fixture를 확장했다. 새 DB 설계나 scheduler는 없다.

## 실제 자원 접근과 복구

기준은 실제 M3 package `g0-d09c6d03835a46248e5bdb6fe9e07e8c`, ZIP SHA256 `ac6d13fc0ee02959833929c2257bf928d4aa375b7742eb39c6cf9b26870b10d3`이다. g10/Order89 유래 archive 검사이며 현재 운영 Order DB를 확인한 결과가 아니다.

원 문헌 선택은 collection39, 문서96–102이다. 이전 검증용 local collection1/doc1–7과의 대응은 PDF SHA256 7개 일치로 확인했다. ID를 전역 하드코딩하지 않았다. 외부 논문6개와 사용자 방법 검토문서1개이며 별도 동실험 원고를 추가하지 않았다.

기존 localhost Chroma의 heartbeat는 응답했지만 `/tmp`의 SQLite가 비어 `no such table: tenants`로 조회가 실패했다. 기존 index snapshot과 workspace PDF 백업은 남아 있었다. 기존 Chroma API로 격리된 `codex-inputs/full-evidence-m4/restored_chroma`에 동일 442개 chunk/text/metadata/vector를 복원했다. 새 문서나 embedding을 생성하지 않았다. 원본/이전 Collection 프로세스는 변경하지 않았다.

원 snapshot hash `9550b7143d9d58e481873316fd7dd6dd466e5713a59e384b32cb7a45aaec5753`. Chroma vector 재저장 최대 차이는 `1.115512847371658e-08`이며 chunk ID·text·metadata는 정확히 같다. 실제 복원 index hash는 `8feb2aed15b1be487a940a20033c8b8df233601a73ff09301e5a91b9ba6382f6`으로 별도 고정해 이전 실행 cache와 구분했다.

첫 실제 질의는 임베딩 임시 캐시의 누락으로 실패했다. failed pin/log를 보존했다. 기존 `NeuML/pubmedbert-base-embeddings` revision `b79526d6ef3645e0df4530322e266f24c829f5ef`를 공식 배포처에서 복원했다. model.safetensors SHA256은 기존 blob과 같은 `929ddc16369bb4ff6f8e92a6ee9f5e0748f2bef33989b5617533dd50beebe4ef`다. 이후 동일 registry·768차원·normalized cosine을 사용한다. 색인/모델 복구는 로컬 검증 환경 작업이며 운영 서비스 배포가 아니다.

기존 Ollama alias `ptm-round08b-qwen3-14b-40k:latest`, digest `7e08dfe65c515a6e24f64a68cb4664b1ded3dbd75de3d2de88870b74e94ce58b`, context40960, 실제 호출 temperature0/max_tokens4096. 모델을 새로 선택하거나 학습하지 않았다. 원 snapshot의 gemma3:27b는 현재 로컬에 없으므로 이전 문헌 검증에 쓰던 실제 설치 모델을 명시적으로 사용했다.

## 사전 고정 범위와 판정

`codex-inputs/full-evidence-m4/PREDECLARED_REQUEST.json`에 5개 대상, 사유, 예산(max_queries24/max_model_calls5/max_prompt_bytes100000), 모델·자원과 발행 정책을 고정했다. 전체 검토는 partial이며 요청 범위만 completed가 될 수 있다. 실패/예산 미완료가 남으면 성공 pointer를 교체하지 않는다. MAPK1 한 건을 먼저 실행하고 같은 hash의 per-subject cache로 재사용한다.

| 대상 | 원본/읽기 의미 | review_subject_id |
|---|---|---|
| MAPK1 | 미선정 observation, 후보 T183/Y185; localization 미측정 | review_subject_55b247e34a7048934295 |
| GSK3A | 미선정 observation; 자체 PTM은 효소 활성 아님 | review_subject_093b33f4f8cff43355e7 |
| MAPK3 | 1분 raw-only/excluded 원본 | review_subject_70c0a0b67f80c422c6c9 |
| PTPRK | A0ABK0LP24, 180분 단백질 abundance contrast | review_subject_9aaa70207efe64e6c61a |
| AKT1 | PhosX 1분 insufficient_coverage 방법 결과 | review_subject_6f2b7a781153897eb7b2 |

접근 가능 분모는 전체 표현 수이며 독립 관측 수가 아니다. 새 실행 요청·실제 검색·본문 반환·비교 호출·source anchor·의미 승인을 구분한다. 원문 anchor가 있어도 claim_support_status는 not_verified이고 외부 Astra review_status는 not_recorded다. 내부 검색과 원문 재배포 권한도 구분한다. 기존 CC BY4.0 근거가 있는 2023년 문헌 구간만 허용된 export 경로를 사용하고 나머지는 metadata/hash/위치만 export한다.

## 검증 결과

실제 5개 대상 모두 retrieved/comparison completed, model 제안 목록은 모두 빈 배열이었다. 직접 비교 승인 0건이다. 대상별 반환 구간 수는 MAPK1 15, GSK3A 15, MAPK3 10, PTPRK 11, AKT1 10이며 이를 더해 고유 근거 수로 보고하지 않는다. 고유 chunk21개, 문서6개 중 외부 논문5개·방법 메모1개다. 전체158,593개 표현 중5개 실행, 나머지158,588개 not_requested이므로 **전체 검토는 partial**이다.

성공 경로의 RAG layer 호출17회, 모델 비교5회. full 단계 자체는 queries13/model_calls4이고 파일럿 queries4/model_calls1은 정확한 per-subject cache로 재사용했다. 실제 처리 시간은 파일럿144.95초, 나머지322.04초이다. 앞선 임베딩 실패4회와 진단 질의 실패1회를 성공 집계에 넣지 않았다. 요청 층별 호출 수이며 Chroma의 물리 질의·내부 cache hit 수나 HTTP 요청 수와 같지 않다. 기존 retriever의 서지 확인 HTTP 세부 횟수는 별도 계측하지 않았다. 문헌 코퍼스를 추가하지 않았다.

| 로컬 doc / 원 doc | 파일·색인 확인 | 이번 반환 고유 chunk | 구분 |
|---|---|---:|---|
| 1 / 96 | hash 일치,8 chunks | 3 | 사용자 방법 메모; 외부 검증 아님 |
| 2 / 97 | hash 일치,59 chunks | 1 | 외부 논문 |
| 3 / 98 | hash 일치,71 chunks | 7 | 외부 논문; 기록된 CC BY4.0 export |
| 4 / 99 | hash 일치,28 chunks | 1 | 외부 논문 |
| 5 / 100 | hash 일치,29 chunks | 0 | 이번 subset 반환 없음; 미접근/반대 결과 아님 |
| 6 / 101 | hash 일치,26 chunks | 1 | 외부 논문 |
| 7 / 102 | hash 일치,221 chunks | 8 | 외부 리뷰 |

대표 원문 구간3건을 Codex가 제한적으로 점검했다. 자동 의미 승인을 추가하지 않았고 외부 Astra review는 not_recorded다.

- MAPK1 `reader_card_01c224da2d74475143c2` → review subject → `e4b02ca2eb855ecc8888ff3337540712_8`, DOI10.1152/physrev.00063.2017, introduction/chunk6. 일반 INSR–MAPK 배경이며 현재 rat HIRc-B T183/Y185 localization이나 시간 반응을 직접 검증하지 않는다.
- GSK3A `reader_card_ce90380fcc2732632381` → `3469efc50c314354d2e094c1d62f1240_41`, DOI10.1038/s41467-023-36549-2, discussion/chunk4. 연구 자체가 male mouse/adipose/3T3-L1 범위를 밝힌다. 현재 form의 자체 PTM과 효소 활성을 동일시할 수 없다.
- AKT1 `method_result_e128e34506b2f1818851` → `c1d404600a55579e5826ce704b79070c_89`, DOI10.1152/physrev.00063.2017, indexed introduction/chunk87. AKT 조절 site와 substrate specificity의 일반 가설·제한을 설명한다. 현재 PhosX insufficient_coverage를 positive activity 또는 inactivity로 대체하지 않는다.

위 결과는 새 비교를 강제로 생성하지 않고 실제 빈 제안 목록과 source scope를 점검한 것이다. 원문 구간의 위치/hash 및 사유는 `SEMANTIC_SCOPE_AUDIT.json`, 실행 상태·출력 hash는 `ACTUAL_EXECUTION_AUDIT.json`에 남겼다. 합성 fixture와 실제 사용자 문헌 실행을 합산해 과학적 성능으로 해석하지 않는다.

검증 suite는 M3 8개, M4 신규4개, 기존 literature/full-reader/figure 경계28개로 고유40개 passed, skip0이다. 기존 pandas FutureWarning은 남는다. 실패·부분 실행 차단, source/FK 오류, runtime digest cache 구분, 원본 보존, 실제 frozen 발행 경로를 포함한다. 원래 M3 패키지의10개 reader artifact offline replay도 byte-identical, network/model0으로 통과했다.

## 재현과 남는 범위

실제 RAG Collection/본문과 Ollama 모델이 필요했던 실행은 고정 pin에 저장한다. Offline reader replay는 그 결과를 재구성하고 hash/FK/source anchor를 확인한다. 새로운 검색 성공이나 의미 판단 재검증이 아니다. 정량·PhosX·temporal 계산 replay는 수행하지 않는다.

전체 158,593개 표현에 대한 문헌 검토가 완료된 것은 아니다. 사전 지정 대상 이외는 not_requested, 과학적 보류/localization/calibration 제한은 유지한다. 운영 UI·배포·외부 Astra의 실제 보고서 작성/검토는 이번 검증 범위 밖이다.

## 최종 패키지와 보존 검증

- Run `g0-febc02fcaa0b43c0ac9cd973730a7a3b`; ZIP SHA256 `b48fc46c4f8fd62193b14068ddd80cd6ccf8f1aa4c334ec6cc735275e2a0e1eb`.
- ZIP: `/Users/josephk/Projects/PTM-platform/codex-inputs/full-evidence-m4/final/revision/astra_analysis_package_g0-febc02fcaa0b43c0ac9cd973730a7a3b.zip`.
- 읽기 진입점: `/Users/josephk/Projects/PTM-platform/codex-inputs/full-evidence-m4/final/revision/enrichment_free_runs/g0-febc02fcaa0b43c0ac9cd973730a7a3b/reader/LITERATURE_SUBJECT_REVIEW.md`.
- 기존254개 manifest 파일 중 236개 byte-identical, 18개 의도적 변경, 5개 추가. 정량22CSV, 과학 science 17 / kinase 12 / temporal 9 파일, 그림 31개, 기존 문헌/source pin·결과, 15개 findings와 카드·질문·M2 연결 보존. 전체 파일별 hash/diff는 RESULTS.json과 실제 검증 JSON에 기록.
- 허용한 변경은 reader packet/안내/catalog, M3 계획의 M4 실행 안내, provenance/분석계획/코드 snapshot이다. 계획 CSV·선정·과학 결과는 바꾸지 않았다. 추가는 M4 execution/link CSV, summary/guide, 별도 실행 pin의5개다.
- 새 패키지 자체 코드 offline reader replay 15개 byte-identical. 네트워크·모델0, 과학 계산0. 상대 링크 99개와 typed source citation 5개 검증. 원 M3 replay10개도 통과했다.
- 첫 검증의 fresh references 폴더 누락은 replay CLI에서 수정했다. 최종 실행에서는 기존 checkpoint로 replay를 먼저 통과한 뒤 성공 pointer를 기록했다. 초기 임시 검증 ZIP과 로그도 남겼으며 원 M3 성공 패키지는 수정하지 않았다. 실패·부분 실행·seal·발행 직전 중단의 pointer 보존은 fixture로 확인했다.

실행한 발행 검증 명령:

```sh
PYTHONPATH=.:workers MPLCONFIGDIR=/tmp/ptm-m1-mpl codex-inputs/round11-20261010/runtime/bin/python scripts/validate_full_evidence_m4.py --source codex-inputs/full-evidence-m3/final/revision/enrichment_free_runs/g0-d09c6d03835a46248e5bdb6fe9e07e8c --pin codex-inputs/full-evidence-m4/full_execution_pin.json --output codex-inputs/full-evidence-m4/final
```

이 명령은 저장된 pin을 발행·replay하며 새 검색을 수행하지 않는다. 실제 검색은 기존 `execute_review`를 사용했고 입력 선택/환경/사전 예산/원 호출 기록은 `codex-inputs/full-evidence-m4`에 보존했다. 이전 cache와 summary 선정에 관계없이 명시적 subject ID를 사용했다.

## Git 및 종료 범위

관련 코드·fixture·검증 CLI·이 보고서만 main 작업 트리에 로컬 커밋한다. 실제 SHA는 완료 응답과 git HEAD 및 `codex-inputs/full-evidence-m4/LOCAL_COMMIT.json`에 기록한다. 원시 PDF·DB·모델·실행 출력은 커밋하지 않는다. 원격 push, 운영 배포, flag 변경은 수행하지 않았다. M4의 요청 범위 연결·실행·재현 검증을 마쳤으며 전체 표현의 문헌 검토나 생물학적 검증 완료로 확대하지 않는다.
