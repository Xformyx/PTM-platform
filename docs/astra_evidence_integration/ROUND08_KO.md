# 회차 08 — 기존 finding 문헌 검색을 Astra reader에 연결

기준 main은 `bd3fe6cc263d4263273fa65ac6471ad7fbc25abc`, 작업 브랜치는 `codex/astra-round08-literature`다. 시작 시 tracked 변경은 없었으며 미커밋 `codex-inputs/` 9,322개 파일을 보존했다. 저장소와 상위 경로에서 적용할 AGENTS.md는 발견되지 않았다. 운영 배포·flag 변경·회차 09는 수행하지 않았다.

**연결 구현과 합성 비교·패키지/replay 검증은 완료했다. 실제 독립 문헌 비교는 0건이다.** 기준 run의 고정 컬렉션과 접근 가능한 로컬 DB 모두 문헌 컬렉션이 비어 있다. 이를 정상 검색의 no-hit, 생물학적 반대 결과, 문헌 비교 완료로 표시하지 않는다.

## 실제 입력과 접근 범위

기준 run: `g0-8e634f6ca5c847a08726cb69bf91f9a2`.

- `references/literature_pin.json`: selection=`all_active`, requested_ids=`null`, 실제 고정 collections=`[]`. 빈 목록을 현재 활성 컬렉션으로 다시 해석하지 않았다.
- 기존 로컬 검증 MySQL의 Order **70 / Round01_HIRcB_52030d7a**를 SELECT만으로 대조했다. rag_collections는 null, RAG collection/document 테이블은 각각 0행이다. 운영 Order 88 DB를 확인한 것이 아니다.
- 실행 중인 로컬 Docker는 기존 MySQL/Redis였고 Chroma 검색 컨테이너는 없었다. 운영 서버의 RAG 서비스 접근 여부는 미확인이다.
- 첨부 `HIRcB_Insulin_Full_Article (2).docx`는 실제 package bytes가 있다. SHA-256: `976d148ce4117fcd3f99c277fd9b35e3a06a2f19deb1afaa37e84b043460b353`.
- 해당 문서는 **같은 HIRc-B 실험의 원고**다. 제목·초록·본문 텍스트·참고문헌 목록을 확인하고 30쪽으로 렌더링해 첫 페이지를 직접 확인했다. 이 접근 확인은 RAG 자동 비교와 구분한다. 본문의 과거 해석을 이번 결과의 독립 검증으로 사용하지 않았다.
- 참고문헌 항목 40개가 원고에 나열되어 있지만 그 외부 논문의 본문/초록을 읽은 것이 아니다. 논문 40편을 읽었다고 세지 않았다. 자동 finding 단계가 실제 읽은 외부 논문·초록·본문은 모두 0개다.
- 기존 `common.document_indexer.parse_document`의 입력은 PDF/MD/TXT/CSV이며 DOCX는 지원하지 않는다. 첨부를 새 DB에 자동 등록하거나 별도 검색 엔진을 만들지 않았다. 원본 DOCX는 기존 허용 상태 그대로 새 package에 보존한다.

[실제 접근 감사](../../codex-inputs/round08-20261008/ACCESS_AUDIT.json)에 local Order 검사, archive 검사, 수동 첨부 확인을 구분했다. 원문 PDF와 비밀 설정은 커밋하지 않는다.

## 수정 경계와 기존 함수 재사용

| 경계 | 수정 및 재사용 |
| --- | --- |
| API 입력 동결 | `prepare_astra_inputs`: 표시 이름과 별개인 `chromadb_name`을 pin에 포함. 읽을 수 있는 문서는 원본 export 허가가 없어도 hash를 기록. 내부 색인 상태와 export 허가를 분리. 과거 pin/empty selection을 임의 변경하지 않음 |
| 기존 검색·비교 | `finding_literature`를 shared 위치로 이동하고 legacy 경로는 같은 module을 참조. `cards_for_selected_findings`에 명시적 finding_id 키/기존 순서 지원. 기존 4개 검색 층과 quota, strict RAG query, JSON 비교·인용 검사를 재사용 |
| 관측 입력 | 기존 카드의 실제 identity, 수정 서열, taxon, source_bindings, 전체 trajectory, joint mask·U_joint/P_joint/A·U_all/P_all, localization 제한, 원문 질문을 전달. 별도의 수치 계산 없음 |
| 검색 provenance | 같은 DOI의 다른 chunk를 삭제하지 않음. 동일 chunk가 여러 검색 층에 나타나면 검색 역할은 모두 보존. 원 검색/비교 모델의 provider/model/prompt version·prompt hash·실제 입출력과 실패 상태 유지 |
| 문헌 카드 | 기존 `_literature_cards`, `is_traceable_reference`, `_stable_reference_id` 및 helper 7개를 shared로 이동. 기존/이동 후 함수 AST는 모두 동일. legacy authoring도 같은 함수를 사용 |
| runtime | 기존 `RAGRetriever`와 `LLMClient`를 직접 호출. core 패키지의 report graph import만 지연하여 검색을 위해 writer/graph 전체를 초기화하지 않음 |
| reader | `astra_literature.collect/apply/write/validate`: 기존 결과를 finding/source/비교 표로 연결. `reader/packet`의 문헌 근거·질문별 상태·reference cards와 Markdown 링크 추가 |
| package/replay | 실제 `run_astra_analysis`의 v6 단계에 연결. 기존 `cached_stage`, `write_tables`, `validate_package` 및 manifest/CRC/atomic publish를 재사용. 기존 publish 코드를 `seal_archive`로 추출하여 정상 실행과 문헌 전용 개정이 공유 |
| 기존 결과 재사용 | `astra_reader_revision.revise_literature`: 검증된 package의 manifest 파일만 복사하고 reader 문헌 산출물만 개정. 새 run/context revision에 원 analysis run·코드 hash를 연결. 과거 성공 package와 원 ZIP 불변 |

호출 경로는 다음과 같다.

```text
prepare_astra_inputs → task_config.literature_pin
→ 기존 preprocessing primary 분기 → v6 → run_astra_analysis
→ 기존 science/adapter/reader 결과
→ astra_literature.collect
→ cards_for_selected_findings(key=finding_id)
→ retrieve_finding_literature
→ 기존 RAGRetriever.query_for_purpose + LLMClient.generate
→ astra_literature.apply → 기존 write_reader / _literature_cards
→ schema/FK/hash/CRC 검사 → archive
```

실제 HIRc-B 검증은 위 공통 collect/apply/write/publish를 쓰는 **문헌 전용 package 개정 경로**다. 새 운영 queue 실행이라고 표시하지 않는다. 정상 v6 생성 경로 호출은 합성 package 통합 테스트에서 별도 검증했다.

## 근거·정책 경계

기존 비교기는 일치/상이 등의 모델 제안을 `proposed_relationship`으로 보존하지만, 인용문이 원문에 있다는 사실만으로 생물학적 판단을 승인하지 않는다. 원문 span/offset/hash와 source context를 검증한 뒤 실제 `relationship=literature_background`, `claim_support_status=not_verified`, `source_anchored_semantic_review_required`를 유지한다. 이번 회차에 이 가드를 해제하지 않았다.

같은 gene, 후보 residue 또는 시간 문자열의 일치만으로 현재 site·반응의 일치를 판정하지 않는다. 현재 site localization 부재·기술 반복·parent 보정의 의미가 검색 입력과 reader에 남는다. 문자열로 다른 연구 조건은 기록하되 그것을 생물학적 disagreement로 간주하지 않는다. Counterevidence는 기존 별도 검색 층을 실행하며 없으면 생성하지 않는다.

PDF 원본의 포함 여부와 내부 검색은 독립이다. export 허가가 확인되지 않은 검색 자료도 검색/내부 비교 수행 상태와 hash·식별자를 남기지만 원문 chunk·모델 prompt/output의 원문 인용은 package에서 제외한다. `internal_comparison_performed_export_restricted`를 비교 미실행과 구분한다. 기존 색인기의 `doc_id`와 inventory의 `document_id`를 같은 문서에 연결하고, 두 키가 충돌하면 export 허가를 추정하지 않는다. 허용된 근거의 chunk/page/section, 인용 위치·원문 hash, 문헌 식별자와 finding/source row 연결을 export한다.

캐시는 기존 `evidence_stage_cache.cached_stage`다. finding·관측·원문 질문·선택 문헌·검색/모델 설정·코드 hash가 key에 들어간다. **catalog updated_at을 불변 검색 index version으로 간주하지 않는다.** 불변 index snapshot이 명시된 경우만 지속 캐시를 재사용하며, 실패/부분 검색/모델 미실행은 영구 no-hit으로 캐시하지 않는다. query 내 재사용은 기존 retriever 경로를 따른다. Package replay는 저장된 결과 pin을 검증·투영하며 검색·LLM을 호출하지 않는다.

원래 `reader/cards.csv`는 회차 07의 관측 카드로 보존한다. 그 안의 과거 문헌 상태는 카드 생성 시점의 기록이다. 최신 상태의 canonical 위치는 `reader/literature_search.csv`이며 packet에 `status_authority`를 명시했다. 기존 finding 순서·카드 적격성·점수는 바뀌지 않는다.

## 실제 실행 결과와 대표 세 사례

먼저 DOCK7 한 개의 입력→finding→원본 6시점→검색 계획을 확인했다. 고정 컬렉션 부재를 확인한 뒤 같은 경로로 15개에 확대했다. 선정 결과를 문헌 유무에 따라 교체하지 않았다.

| 항목 | 실제 결과 |
| --- | --- |
| 검색 대상 | 기존 선정 순서의 15 findings |
| 검색 가능한 고정 컬렉션 | 0 |
| 실제 검색 / 모델 호출 | 0 / 0 |
| 실제 읽은 외부 문헌 / 비교 가능한 finding | 0 / 0 |
| 실패·미실행 상태 | 15건 모두 `not_searched`, 사유 `no_active_collections_in_frozen_selection` |
| 검색 계획 | 각 finding의 background / gene context / direct site / counterevidence 4층, 모두 미실행으로 기록 |
| 첨부 내용 확인 | 사용자 원고 1개를 별도 수동 검사. 외부 문헌 비교 수에 포함하지 않음 |

**실제 비교 3개를 만들어 보고할 수는 없다.** 다음은 원본까지 연결된 대표 비교 불가 사례 3개다. 각 경우에 문헌 ID/인용/반대 결과를 만들어 넣지 않았다.

| 관측 | finding ID / 원본 form | 실제 비교 상태 |
| --- | --- | --- |
| DOCK7 후보 S1423 | `finding_cf8f4249c4fa5bd2be47` / `form_5f6b1591279b085d` | 미검색. Control 대비 1/5/15/30/60/180분 원본 행 6개 유지. source pin에 검색 컬렉션 없음 |
| SIK3 후보 S779 | `finding_8d461aa65e3c36763221` / `form_0307f4dc0d707fd5` | 미검색. 이 단백질의 PTM 관측을 kinase 활성 또는 문헌 일치로 승격하지 않음 |
| RBM26 후보 S127 | `finding_ac77a2145e4e726099e4` / `form_927c72b605b8f2bd` | 미검색. localization 미측정을 유지하고 서열상 후보 좌표만 전달 |

세 사례의 전체 source row IDs는 [ROUND08_RESULTS.json](ROUND08_RESULTS.json)의 representative_cases 및 package `reader/LITERATURE.md`에 있다. 현재 원고에서 이들 이름을 검색하지 못한 사실도 반대 결과의 근거가 아니다.

## 보존과 검증

- 기준선 76개 표 중 **reader/packet을 제외한 75개 표가 byte-identical**. 정량 22개 표의 ID·값·NA와 기존 scientific 수치 모두 그대로다.
- 기존 15개 finding의 ID·순서, 선정 카드의 숫자·NA·시간·단위·원문 질문 그대로다. 카드 14,658개와 source row 16,944개의 역추적 검사 통과.
- 그림과 source CSV/legend 파일은 재생성하지 않고 byte 그대로 보존. 회차 02·03 시간축·곡선 회귀 통과.
- source pin bytes/hash 그대로, PR/PG/FASTA 정량·reference 수집·discovery·그림 생성·finding 재선정을 호출하면 실패하도록 막은 실제 실행이 통과했다. 문헌 전용 개정 76.62초.
- 새 package: manifest 222 files / tables 79. CSV/FK/해시·ZIP CRC 검사 통과. 포함 코드 62개 hash가 작업 소스와 일치.
- package의 코드만 로드한 별도 interpreter에서 네트워크를 차단하고 reader/문헌 **15개 파일 byte-identical** 재구성. 이는 문헌 판단의 과학적 검증이 아니다.
- 관련 회귀 **41 passed (29.08 s)**. 최종 상태·뷰 연결 변경 후 해당 경계 **7 passed (15.90 s)**, 기존 색인 `doc_id` 연결을 보완한 최종 경계 **8 passed (9.42 s)**를 추가 확인했다. 중복을 합산한 고유 테스트 수로 표시하지 않는다.
- 합성 사례: agreement/disagreement/context_difference 제안, 인용 조작 거부, 동일 gene의 다른 taxon/reference, 중간 NA, counterevidence 검색, 실패/무검색/허가 제한, cache 재사용, 잘못된 pin/원본 연결 거부, 정상 v6 생성 호출, 문헌 전용 개정, 오프라인 reader replay, 실패 시 이전 pointer 보존.
- 기존 순수 reference 함수 7개 AST 동일. 새 합성 v6 full replay도 79개 과학 표와 8개 reader view가 동일하다. 실자료 전체 재정량 replay는 반복하지 않았다.

검증 명령과 상세 결과는 `codex-inputs/round08-20261008/tests-final.log`, `tests-boundary.log`, `tests-docid.log`, `ROUND08_VALIDATION.json`, `READER_REPLAY_VALIDATION.json` 및 [ROUND08_RESULTS.json](ROUND08_RESULTS.json)에 보존했다. 초기 fixture 필드명, 공용화한 private regex import, fresh replay 폴더 생성, 반복 개정의 제한 문구 중복에서 발견한 오류는 수정 후 통과했다.

## 산출물과 실행 방법

새 run: **`g0-cf46abffea214f55ac6c8612ec03cf15`**.

- [Astra ZIP](../../codex-inputs/round08-20261008/execution/output/astra_analysis_package_g0-cf46abffea214f55ac6c8612ec03cf15.zip)
- [문헌 비교/접근 상태](../../codex-inputs/round08-20261008/execution/output/enrichment_free_runs/g0-cf46abffea214f55ac6c8612ec03cf15/reader/LITERATURE.md)
- [Astra 시작 지침](../../codex-inputs/round08-20261008/execution/output/enrichment_free_runs/g0-cf46abffea214f55ac6c8612ec03cf15/START_HERE_ASTRA.md)

ZIP SHA-256: `2a7b41a9bd67c3bab5b73e9183340307224b1aaa35998f40cf8f181bc1b73247`.

```sh
PYTHONPATH=workers:. python scripts/revise_astra_literature.py \
  --package <validated-v6-run-directory> --output <new-output-directory>
python scripts/replay_astra_reader.py --package <revised-run-directory> \
  --output <new-offline-directory>
```

새 기본 package 생성은 기존 worker의 v6 경로에서 문헌 단계가 자동 호출된다. 위 CLI는 완료된 package의 수치를 건드리지 않는 개정 경로다. RAG 검색에 필요한 런타임은 기존 worker dependency/embedding contract를 그대로 사용한다. Offline 재구성에는 RAG/LLM 런타임이 필요하지 않다.

실제 외부 문헌 비교를 완료하려면 해당 연구가 선택한 **실제 문서가 색인된 기존 RAG collection과 접근 가능한 Chroma runtime**, 필요한 경우 기존 LLM 비교 runtime이 있어야 한다. 과거 pin에 검색명이 없으면 이를 임의 추정하지 않고 `pinned_collection_search_name_missing`으로 남긴다. 새 capture에서는 정확한 검색명을 보존한다. DOCX의 인용 목록만으로 인용 논문 내용이 확보됐다고 간주하지 않는다. 이 제한은 회차 09 수행이나 운영 배포를 자동 승인하는 조건이 아니다.
