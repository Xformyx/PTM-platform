# 회차 08-B — 원래 문헌 접근 복구와 명시적 문헌 선택 개정

기준 main: `287b9d4c87d8fc1deeab96d5fad40d9ccca7e590`. 작업 브랜치: `codex/astra-round08b-literature-access`. 기존 미커밋 `codex-inputs/`와 원본 패키지·성공 pointer를 보존했다. 저장소 및 상위 경로에서 적용할 AGENTS.md는 발견되지 않았다. 운영 배포, v6 flag 변경, reference 전체 수집, 정량 재계산, 회차 09는 하지 않았다.

## 선택 차이의 원인

원본 g1 `g1-da89accad9bd4319868ecc868dedf685`의 pin은 explicit `[39]`, **Insulin Signaling**, 문서 96–102의 7개였다. SHA-256은 `5bd457114a356a32b50b2ac259d7ea77579f4b16369f70312fff1d2dc8a219fd`다. 원본 pin에 PDF bytes/hash와 완전한 서지정보는 없었다.

반면 회차 08 기준 `g0-cf46abffea214f55ac6c8612ec03cf15`는 all_active/null/collections=[]였다. 원인은 다음 두 경계로 확인했다.

1. 회차 01 검증 스크립트 `scripts/validate_astra_activation.py`는 별도 검증 Order를 만들 때 `rag_collections='[]'`를 명시했다. 원본 g1의 `[39]`를 승계한 테스트가 아니었다. 회차 01 v5 ZIP에서도 explicit []를 확인했다.
2. 기존 `RerunOptionsModal`은 비어 있지 않은 배열만 명시적 선택으로 복원하고 나머지는 all_active로 바꿨다. 따라서 []가 null로 바뀌었다. 회차 01 v6 ZIP의 all_active/null과 일치한다. API JSON parser 자체는 []를 보존한다.

이번 수정은 빈 선택·명시적 선택·all_active를 그대로 복원한다. 원본 `[39]`를 모든 환경의 기본값으로 넣지 않는다. 회차 08 당시 로컬 DB의 빈 catalog 검사 자체는 맞지만, 그것으로 원래 사용자의 문헌 파일 접근 불가까지 결론 내릴 수는 없었다.

검사한 DB는 기존 격리 검증 MySQL이다. Order **70 / Round01_HIRcB_52030d7a**의 rag_collections는 JSON null이며 이번에도 변경하지 않았다. 로컬 Order 88은 없다. **운영 Order 88의 현재 값·파일·색인·배포 상태는 확인하지 않았다.**

## 실제 문서와 접근 경로

원래 7개 파일명 모두 `~/Downloads`에서 찾았다. 파일별 SHA-256, PDF 첫 페이지, 기존 parser 결과를 확인했다. 원본 pin에는 hash가 없으므로 원본 서버 bytes와 동일하다고 확정할 수 없다. 대응 근거는 **동일 파일명과 확인한 내용·서지정보**다.

기존 API `create_collection` / `upload_document`와 `DocumentIndexer.index_document` / `parse_document`, 기존 embedding registry를 사용했다. API 함수를 실제 SQL 세션·파일 업로드 객체로 호출하고 기존 색인기를 동기 실행했다. HTTP→Celery queue 통합 검증으로 표현하지 않는다. 새 검색 엔진이나 문서 parser는 만들지 않았다.

| 원본 문서 ID → 로컬 ID | 확인된 문서 | catalog / 파일 / index | 해당 문서의 실제 검색 hit | 패키지 포함 |
| --- | --- | --- | --- | --- |
| 96 → 1 | PTM-platform Methods 강화 검토 | 모두 존재, 8 chunks | 8 | metadata, 외부 학술논문 아님 |
| 97 → 2 | Temporal phosphoproteomics… (2025), DOI 10.1038/s41467-025-56335-6 | 모두 존재, 59 chunks | 7 | metadata; excerpt export 허가 미확정 |
| 98 → 3 | Phosphoproteomics reveals rewiring… (2023), DOI 10.1038/s41467-023-36549-2 | 모두 존재, 71 chunks | 8 | 확인한 CC BY 4.0 조건에 따라 근거 excerpt 허용 |
| 99 → 4 | …Protein Phosphatase 1 Regulatory Subunit 12A (2014), DOI 10.1016/j.jprot.2014.06.010 | 모두 존재, 28 chunks | 6 | metadata; excerpt export 허가 미확정 |
| 100 → 5 | Global Phosphoproteomic Analysis… Rat Hepatocytes (2017), DOI 10.1021/acs.jproteome.7b00140 | 모두 존재, 29 chunks | 8 | metadata; excerpt export 허가 미확정 |
| 101 → 6 | Dissection of the insulin signaling pathway… (2008), DOI 10.1073/pnas.0711713105 | 모두 존재, 26 chunks | 3 | metadata; excerpt export 허가 미확정 |
| 102 → 7 | Mechanisms of Insulin Action and Insulin Resistance (2018), DOI 10.1152/physrev.00063.2017 | 모두 존재, 221 chunks | 8 | metadata; excerpt export 허가 미확정 |

검색 hit은 문서 제목을 사용한 접근 검사(`n_results=8`)에서 자기 문서가 반환된 chunk 수다. 현재 findings를 직접 뒷받침하는 근거 수가 아니다. 총 442 chunks, 외부 논문 6개, 사용자 방법 검토 문서 1개다. 같은 실험의 기존 `HIRcB_Insulin_Full_Article (2).docx`는 8번째 첨부로 보존하지만 외부 문헌 또는 독립 검증으로 세지 않는다. 기존 parser의 DOCX 색인 미지원도 그대로다.

초기 검증 설정의 Chroma 18002 / Ollama 18003은 응답하지 않았다. 기존 로컬 Ollama 11434는 접근 가능했다. 격리된 기존 Chroma 서버를 localhost:18012와 `/tmp/ptm-round08b-20261008/chroma`에 구동하고, 로컬 collection `ptm_project_round08b_insulin_signaling_20261008`을 만들었다. 로컬 DB collection ID 1과 원본 39는 위 문서 대응표로만 연결했다. ID 숫자는 실행 코드에 하드코딩하지 않았다.

실제 index bytes/metadata/vectors의 고정 hash: `9550b7143d9d58e481873316fd7dd6dd466e5713a59e384b32cb7a45aaec5753`. 기존 `NeuML/pubmedbert-base-embeddings`, 768차원, cosine/normalized 계약을 index와 query에 동일하게 사용했다. catalog의 과거 indexed 문자열만으로 검색 성공을 인정하지 않고 각 문서의 실제 반환 source ID/hash를 `document_search_checks.json`에 기록했다.

## 변경 코드와 재사용

| 변경 파일 | 최소 변경 |
| --- | --- |
| `frontend/src/lib/analysisContext.ts`, `RerunOptionsModal.tsx` | 기존 재실행 UI의 [] / null 복원 구분 |
| `astra_reader_revision.py`, `scripts/revise_astra_literature.py` | 기본은 원 pin 유지. `literature_pin`과 명시적 `refresh_reason`이 함께 있을 때만 문헌 선택 개정 |
| `finding_literature.py` | 동일한 canonical design이 두 필드에 중복된 경우 prompt에서 하나를 참조로 표시. 질문·관측·근거 내용은 자르지 않음. 비교 실제 실행/실패, 모델·prompt version·input/output hash·usage 기록 |
| `astra_literature.py` | 본문 검색 문서 수, 비교 실행 수, 비교 실패 수를 인용문 검증·의미 검토와 별도로 집계 |
| 기존 관련 테스트 2개 파일 | 선택 구분·명시 갱신·cache·실패 pointer·replay·prompt 정보 보존 검증 |

실제 호출은 `prepare_astra_inputs` → 명시적인 local literature pin → `revise_literature` → `astra_literature.collect` → 기존 `cards_for_selected_findings` / `retrieve_finding_literature` → 기존 `RAGRetriever.query_for_purpose` / `LLMClient.generate` → 기존 `apply`, reference cards, `write_reader`, `seal_archive`다. 기존 `cached_stage`와 검색 cache를 사용했다.

새 선택은 replay_config, snapshot rag_collections, context literature_context, input transfer manifest/brief, provenance, cache key, reader pin에 함께 반영한다. 원 선택과 snapshot은 `study/literature_selection_revision.json`에 보존한다. 정량/source pin과 문헌 pin은 별개다. 새 PDF 원본은 package에 복사하지 않으며, 이미 검증된 package에 없는 새 바이너리를 full_text_included로 위장하면 거부한다.

## 비교 실행과 의미 검토

첫 DOCK7 pilot에서 4개 검색 층을 실제 호출해 5개 본문 chunk를 읽었다. 모델은 비교 가능한 근거가 없다는 빈 comparisons 배열을 반환했다. 모델/검색 실패가 아니다. 기존 counterevidence 경로도 사용하며 검색 부재를 반대 결과로 처리하지 않는다.

첫 prompt는 기존 100,000-byte 예산을 넘어서 모델 미실행이었다. 원인을 기록한 뒤 **동일 canonical design의 중복 표현만 제거**했다. 수정 후 원문 질문·전체 관측·마스크·문헌을 보존한 84,807 bytes / 입력 31,279 model tokens의 pilot이 실행됐다. 모델은 기존 로컬 qwen3:14b의 동일 weights를 쓰며 별도 검증 alias에 native context 40,960을 설정했다. 기존 서비스/운영 flag는 바꾸지 않았다. temperature=0, 출력 상한=4,096, prompt=`finding_comparison.v6.1`; 모델 digest와 환경 lock은 검증 자료에 있다. token 예산을 넘는 입력은 조용히 자르지 않고 실패하도록 검사했다.

15개 전체 실행과 보존·replay의 최종 수치는 아래 검증 결과 파일에 기록한다. 실행·인용 span 검증·의미 검토는 독립 상태다. `proposed_relationship`은 제안이며 source anchor가 있다고 `claim_support_status=verified`로 바꾸지 않는다. 현재 localization 미측정, 기술 반복, kinase activation 제한도 그대로다.

대표 SIK3 검사: 논문 DOI 10.1038/s41467-023-36549-2의 실제 PDF **7쪽**을 열어 `Sik3 S493`이 DEX 모델의 PKA substrate dephosphorylation 문맥에 나오는 것을 확인했다. 현재 HIRc-B 후보 S779와 다른 site이며, 3T3-L1 adipocyte/insulin-resistance 맥락을 rat fibroblast 시간 반응의 직접 일치나 반대로 바꾸지 않는다. SIK3 단백질의 PTM 관측도 SIK3 효소 활성 측정은 아니다.

## 검증 범위와 실행 명령

다음 검사들은 문헌 선택·검색·직렬화 경계에 한정했다. 문헌 존재 여부에 맞춰 선정 finding을 바꾸거나 full 전처리를 반복하지 않았다.

```sh
PYTHONPATH=api-server:workers:workers/tests:. python -m pytest -q \
  ptm_shared/tests/test_astra_literature.py \
  workers/tests/test_flow_finding_retrieval.py \
  api-server/tests/test_astra_input_capture.py
PYTHONPATH=workers:. python -m pytest -q ptm_shared/tests/test_astra_figures.py
PYTHONPATH=workers:. python -m pytest -q ptm_shared/tests/test_astra_curves.py
# frontend: node 기반 기존 analysisContext 테스트 및 npm run build
```

- Python 문헌/API/legacy 경계: **20 passed, 25.97 s**.
- 회차 02 heatmap: **5 passed, 1.18 s**; 회차 03 curves: **8 passed, 2.86 s**.
- frontend context: **5 passed**, production build 성공. 기존 큰 bundle 경고는 남아 있다.
- 새 선택을 주지 않으면 기존 pin bytes 유지. 명시적 선택+사유가 있어야만 갱신. 이전 빈 선택의 cache 재사용 거부, retrieval 실제 호출 확인.
- 갱신 중 예외를 주입하면 이전 current pointer bytes가 동일함을 검사. 실패 폴더를 정상 package로 게시하지 않음.
- 새 pin과 snapshot/context/provenance의 일관성, source row/FK, restricted excerpt 비포함, 일치/상이/context difference 제안의 의미 검토 경계, 다른 taxa/reference/중간 NA 보존을 합성 fixture로 검사.
- 동일 canonical design만 prompt에서 참조로 바꾸며, 서로 다른 design 기록은 둘 다 남김. 원문 질문과 관측 JSON 값 그대로임을 검사.
- 합성 새 선택 package의 reader 재구성은 별도 interpreter에서 archive 코드만 로드하고 network 차단하여 검증했다. 실제 package 결과는 별도 수치로 아래 기록한다.

일반 문헌 전용 실행은 다음 기존 CLI의 확장으로 수행할 수 있다.

```sh
# 기본: archived 문헌 선택 유지
PYTHONPATH=workers:. python scripts/revise_astra_literature.py \
  --package <validated-v6-package-directory> --output <new-output-directory>
# 명시적 갱신: 기존 prepare_astra_inputs로 만든 환경별 pin과 이유
PYTHONPATH=workers:. python scripts/revise_astra_literature.py \
  --package <validated-v6-package-directory> --output <new-output-directory> \
  --literature-pin <captured-pin.json> --refresh-reason '<selection-change-reason>'
# 고정 검색/비교 결과와 reader의 offline 재구성
python scripts/replay_astra_reader.py --package <revised-package-directory> \
  --output <new-offline-directory>
```

실제 실행 script·로그·환경 lock·private source 텍스트는 `codex-inputs/round08b-20261008/`에 보존하고 커밋하지 않는다. 문서 본문, PDF, DB 파일, credentials를 Git에 넣지 않는다. 코드·테스트·이 보고서와 원문을 포함하지 않는 검증 요약만 반영한다.

접근과 검색 coverage도 다르다. SIK3 S493 문장은 실제 index의 `a4ead14f5dc379d5c34d7d356eb1ae97_24` / Results chunk 19에 있다. 별도 `Sik3 S493 dephosphorylation DEX insulin resistance` 질의의 상위 5개는 같은 논문의 다른 구간을 반환했고 S493 문장을 포함하지 않았다. 이를 자동 검색이 정확한 S493 근거를 찾았다고 보고하지 않는다. PDF 7쪽과 index 원문을 별도로 확인한 결과이며, 이번 회차에서는 검색 ranking/threshold를 변경하지 않았다. 검색 실패나 no-hit과도 다른 **상위 결과 coverage 제한**이다. 현재 S779의 직접 근거가 확보됐다는 뜻은 어느 경로에서도 아니다.

조건 대조의 현재 연구 쪽 출처는 snapshot이다: `cell_type=HIRc-B rat fibroblast; human INSR overexpression`, `treatment=insulin`, `pre_treatment=serum starvation / 12 h / user_declaration_2026-09-26`, `acquisition_metadata.insulin_concentration=100 nM`. 이 값들은 이번 검색을 위해 추정한 값이 아니다. 현재 관측 grid는 Control 대비 1/5/15/30/60/180 min이고 U_joint/P_joint/A는 모두 log2 contrast다. 2023년 논문에서 검색된 basal/insulin 10 min 및 adipocyte/insulin-resistance 모델과는 실험 모델·시간 비교 범위가 다르다. 2018년 리뷰의 여러 조직·동물·임상 맥락을 하나의 동일 조건 phosphosite 실험으로 취급하지 않는다.

## 최종 실제 실행 결과

**소프트웨어 연결·실제 검색·15개 비교 실행·패키지/replay 검증을 완료했다. 직접 비교 가능한 문헌 관계의 승인은 0건이다.** 접근 불가 때문에 빈 입력을 재실행한 결과가 아니다. 현재 검색 범위와 비교 결과의 한계를 그대로 남겼다.

| 항목 | 실제 결과 |
| --- | --- |
| 대상 / 순서 | 기존 15개 finding 그대로 |
| 접근 확인 | 원래 파일명 7개 모두 catalog·파일·index·실제 검색 확인; 외부 논문 6개 + 방법 검토 문서 1개 |
| finding 검색에서 읽은 외부 논문 | **4편**, DOI `10.1038/s41467-023-36549-2`, `10.1021/acs.jproteome.7b00140`, `10.1073/pnas.0711713105`, `10.1152/physrev.00063.2017` |
| 읽은 범위 | 서로 다른 본문 chunk 12개. 전체 논문 완독 또는 supplement 전수 검사 아님 |
| 검색 | 60개 layer 실행 중 fresh query 46, query cache 재사용 14; hit layer 30, 정상 no-hit layer 30; 실패·예산 미실행 0 |
| 비교 실행 | 기존 LLMClient 실제 호출 **15**, 실행 실패 0 |
| 결과 | 14건 `not_explained_by_retrieved_evidence`; ULK1 1건 제안 거부 후 `retrieved_comparison_pending` |
| 승인된 인용 비교 / 검증된 문헌 일치 | **0 / 0** |
| 별도 의미 점검 | 요청한 대표 3개 finding의 source/site/context 제한을 Codex가 확인. 별도 ULK1 거부 사유도 확인. 독립 전문가 승인·생물학적 검증은 0 |
| 실행 시간 | **2,786.43초**. 문헌 검색/비교 및 package 복사·검증·압축 포함; 정량 재계산 없음 |

내부 reference 배열에는 같은 chunk가 finding마다 반복되어 90개 읽기 인스턴스가 있다. 기존 summary의 `read_scope_counts=90`, `export_restricted_chunks=74`는 이 반복 인스턴스 수다. 독립 문헌 90편이나 고유 chunk 74개라는 의미가 아니다. 독립 identity 집계는 **문서 4 / chunk 12**를 사용한다. 새 PDF 원본은 ZIP에 포함하지 않았다. 문헌의 metadata-only 상태를 내부 미검색으로 바꾸지 않았다.

### 요청한 대표 세 사례의 추적

| 관측 / finding | 실제 검색 → 원본 관측 → 판단 |
| --- | --- |
| DOCK7 후보 S1423 / `finding_cf8f4249c4fa5bd2be47` | 5개 chunk. 2023년 논문 Results chunk 4 (`1bb0bace52ed4cc44778d2b608a8aaef_9`)와 2018년 리뷰의 일반 insulin/대사 문맥. DOCK7/S1423 직접 언급 없음. `form_5f6b1591279b085d`, 첫 원본 `card_row_685dc80d3ecf3536e4bc`부터 6개 contrast로 연결. 비교 실행 완료, 직접 지지·반대 근거 없음 |
| SIK3 후보 S779 / `finding_8d461aa65e3c36763221` | 6개 chunk, 위 문헌과 2008년 논문 Methods chunk 2 (`fa7eb3eebacf23d7aede2bc8b561bdd4_22`). 자동 검색 구간에서 SIK3/S779 직접 근거 없음. `form_0307f4dc0d707fd5`, 첫 원본 `card_row_2e1811455baf1b937afa`. 별도 PDF 7쪽/Results chunk 19의 Sik3 S493은 다른 site·실험 맥락이며 S779로 이전하지 않음 |
| RBM26 후보 S127 / `finding_ac77a2145e4e726099e4` | 6개 chunk의 일반 insulin/방법 문맥. RBM26/S127 직접 언급 없음. `form_927c72b605b8f2bd`, 첫 원본 `card_row_71c6b4fac6c4b8832391`부터 6개 contrast로 연결. 비교 실행 완료, 현재 site 반응 설명 불가 |

모든 source ID·chunk hash·DOI·원본 row ID는 [ROUND08B_RESULTS.json](ROUND08B_RESULTS.json)의 `representative_source_trace`에 있다. `section`은 기존 parser label이며 정확한 원문 절 제목을 항상 보장하지 않는다. PDF에서 직접 확인한 페이지와 구분한다. 본문/상위 검색에서 찾지 못한 것은 supplementary data 전체의 부재나 생물학적 음성을 뜻하지 않는다.

ULK1의 추가 점검은 기존 가드가 필요한 실제 사례다. 모델은 2023년 논문의 일반 insulin 데이터/그림 구간을 인용하며 ULK1 S450에 관한 해석을 제안했다. quote 자체는 원문에 존재했지만, quote에는 ULK1/S450 및 모델이 문헌 조건으로 넣은 현재 실험의 species·cell_type·100 nM이 없었다. 기존 검증이 `unbound_quote_context_or_scope`로 거부했다. **source anchor 존재만으로 의미가 검증되지 않는다**는 경계를 유지했다. 이 제안을 확정 비교 표에 넣거나 kinase call에 반영하지 않았다.

ULK1이 검토 대기이므로 전체 문헌 단계의 완료 cache는 `not_cached / incomplete_retryable_result`다. 이를 완전한 persistent cache hit으로 보고하지 않는다. query cache 재사용 14건은 실제 확인했다. 완료 fixture의 persistent cache 재사용, 새 선택에서 빈 선택 cache 재사용 방지, 기본 pin 유지, 실패 pointer 보호는 별도 테스트로 통과했다. 실제 결과는 package pin에 고정되어 **offline 재구성은 가능**하며, 불완전한 비교를 성공 cache로 승격하지 않는다.

## 보존 검사와 산출물

- 정량 **22개 표를 포함한 기존 보존 대상 74개 표 byte-identical**. 변경 대상은 문헌 표 3개, reader/packet, 문헌 선택에 따른 study/input_field_manifest다.
- 기존 finding 15개 ID·순서, 관측 카드·원문 질문 그대로. **source row 16,944개 / 카드 14,658개**의 숫자·시간·NA·마스크·ID 검사 통과.
- 그림 관련 **25개 파일 byte-identical**. 그림 재생성 없음.
- source/reference pin bytes 그대로. 문헌 pin만 명시적으로 개정했다. 원본 package manifest와 ZIP hash 그대로.
- 새 manifest **223 files / 표 79개**, FK·hash·CRC·code provenance·상대 링크 검사 통과.
- archive 코드만 사용하는 별도 interpreter에서 네트워크 차단 후 reader/문헌 **15개 파일 byte-identical**. 실제 검색 성공, replay 일치, 문헌 의미 검토는 서로 다른 결과다.
- 원본 모델 입출력·PDF·DB는 커밋하지 않는다. 본문 포함 허가가 확인되지 않은 자료의 원문 prompt/output도 package에서 제외하며 실행 상태·hash·usage는 보존한다.

새 run: **`g0-cebc9961d46d4fb28c35e1eb2e8d87dd`**.

- [새 Astra ZIP](../../codex-inputs/round08b-20261008/execution/output/astra_analysis_package_g0-cebc9961d46d4fb28c35e1eb2e8d87dd.zip)
- [START_HERE_ASTRA](../../codex-inputs/round08b-20261008/execution/output/enrichment_free_runs/g0-cebc9961d46d4fb28c35e1eb2e8d87dd/START_HERE_ASTRA.md)
- [실제 reader 문헌 상태](../../codex-inputs/round08b-20261008/execution/output/enrichment_free_runs/g0-cebc9961d46d4fb28c35e1eb2e8d87dd/reader/LITERATURE.md)
- [검증 요약](ROUND08B_RESULTS.json)

ZIP SHA-256: `dae95a2346c390c49960c290f4ee8fa470f69108b14d424241d622c880f5221f`, 208,402,961 bytes. 해당 경로는 로컬 검증 산출물이며 운영 다운로드 URL이 아니다. 실제 실행·자료 보존 검증과 별개로 운영 Order 88의 현재 선택·서비스 상태는 여전히 미확인이다.
