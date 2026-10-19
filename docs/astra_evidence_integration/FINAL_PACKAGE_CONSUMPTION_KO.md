# 최종 패키지 소비 검증 메모

2026-10-19. 회차04는 기존 로컬 완료 상태로 유지한다. **대표 네 경로는 ZIP 내부 자료만으로 추적 가능하다. 문헌 상태·실행 출처의 일부 잔존 표기는 아래 주의사항을 적용해 읽어야 한다.** 전체 근거 접근 가능성과 전체 검토 완료는 다르며, 이번 점검은 외부 Astra 새 세션의 보고서 작성·의미 승인 시험이 아니다.

## 대상과 검증 범위

- 착수: `main`, `0f4df653b44edc324f3cdb332b5b1a825597036f`. 기존 미커밋 `codex-inputs/` 보존. 적용 AGENTS.md 없음.
- ZIP: `codex-inputs/g11-followup-04/delivery/G11_R04_LOCAL/astra_analysis_package_g3-173714b8042a41afa0248b88dc49d4c3.zip`
- 실제 크기 **384,205,219 bytes**, SHA-256 **`862be7cbefcd42c24769ea0a6530bc6ba2b1f0fb2f4fa22931d1886e727f19af`**. 지정값과 일치하며 내부 run은 `g3-173714b8042a41afa0248b88dc49d4c3`이다.
- [회차04 보고서](G11_FOLLOWUP_04_KO.md)·[결과 JSON](G11_FOLLOWUP_04_RESULTS.json)의 manifest 257파일, 보존113파일(정량22 CSV 포함), 고유40개 reader 산출물의 자체 코드 offline replay 일치를 재사용했다. 이번에 그 검사를 다시 수행했다고 집계하지 않는다.
- 회차04의 실제 로컬 API/ORM·Redis·Celery·builder·발행·HTTP 다운로드와 과학/정량/annotation/그림 **archive stage 대역**을 구분한다. 운영 UI·배포·로그인/실사용자 권한·전체 과학 재계산은 미확인/미수행이다. ZIP의 `provenance.json → stage_reuse.quant/normalization_sensitivity`에도 `validated_archive_stage_double`, `calculation_executed=false`가 있다.

이번에는 표준 Python `zipfile`/`csv`/`json`으로 필요한 member를 스트리밍하고 대상 행만 작은 임시 JSON에 보관했다. 원 프로젝트 DB·개발 폴더의 과학 자료를 근거로 사용하지 않았다. ZIP 전체 복사/압축 해제, replay, 외부 검색, RAG/모델 호출, 정량/PhosX 계산, 삭제를 하지 않았다. 생산 코드·기존 문서·ZIP 변경 없이 이 문서만 로컬 커밋한다. push·배포·flag 변경도 없다.

## 읽기 및 원본 접근

패키지 상대 경로로 `START_HERE_ASTRA.md → reader/FULL_EVIDENCE.md / READ_ME.md → EVIDENCE_ACCESS.md → evidence_catalog.json / evidence_index.csv`를 따른다. 인덱스의 `source_table`과 `source_key_json`으로 정확한 원본 행을 읽는다. 문헌은 `literature_review_subjects.csv`의 대상 계획과 `literature_subject_execution.csv`의 실제 실행을 분리하고, 실행표의 `review_subject_id → literature_subject_links.csv → references/literature_subject_execution_pin.json`으로 출처를 확인한다. 계획의 `not_requested`가 실제 실행표를 덮어쓰지 않는다.

현재 catalog ID는 `f0e81360579948b76934dd645bf9008992788805bc77933e41f67c0cb45c11ef`다. 인용에는 이 ID와 run, evidence ID, source table/key를 함께 남긴다. 인덱스175,537행은 겹치는 표현이며 독립 관측 수가 아니다. 전체2,824 forms/16,944 form×contrast, 카드14,658개, 보류3,990행, 요약15개라는 분모를 섞지 않는다. 요약 밖 자료·보류·no-call을 기본 조회에서 제외하지 않는 계약이 명시돼 있다.

아래 모든 정량 대비의 scope는 `arm_8ac02a113972dcb9`, reference `condition_32d7e82082479b8c`(Control, 0분), pairing `unknown`이다. `study/study_design.json`의 target condition `time.minutes`와 `quant/comparisons.csv.time_min`을 대조했다. 해시 문자열 순서가 아닌 실제 숫자 시간 순서는 다음과 같다. Control 대비 표에 새 Control 점을 만들지 않았다.

|분|contrast_id|
|---:|---|
|1|`contrast_aea4869f398c5584`|
|5|`contrast_4147ebd64e7ecf80`|
|15|`contrast_eb2f813f825c4ccb`|
|30|`contrast_c15817d77868a59a`|
|60|`contrast_fd5240cdb335e779`|
|180|`contrast_d6757f4b8563521f`|

## 대표 원본 추적

**1. 미선정 MAPK1 후보 T183/Y185**

`evidence_id = card_id = reader_card_01c224da2d74475143c2`, `form_97aa4b58cee5c391`. `reader/evidence_index.csv`의 `selected_for_summary=False`, `reader/cards.csv`의 `selected=False`이며 `reader/findings.csv` 15개에 없다. 따라서 대체 미선정 사례를 추가할 필요가 없었다.

원본은 `reader/cards.csv`의 정확한 `card_id` → `card_json.source_bindings[]` → `quant/comparisons.csv`의 **(form_id, contrast_id)**다. 5분은 `U_joint=2.8406757312349136`, `P_joint=-0.104061762490268`, `A=2.9447374937251847`(log2), `included=True`. 60분은 세 값 모두 CSV 빈 필드/카드 `null`, `included=False`, `exclusion_reasons=target_joint_unobserved`다. 0이나 보간값이 아니다. 나머지 시간도 카드와 원본이 일치한다. taxon10116, `single_gene_isoform_coordinates`, localization `missing_input`이므로 후보 좌표를 MS localization이나 MAPK1 활성으로 바꾸지 않는다.

문헌 대상은 `review_subject_55b247e34a7048934295`: 검색15구간, 모델 비교 `completed`, 빈 comparisons, 의미 `review_required`. 카드 생성 단계의 `not_performed`를 이 별도 실행의 미실행으로 읽으면 안 된다. `evidence_links.csv`의 `evidence_link_f91e59c3130c7a5d4a33`은 `precursor_member_of`: `reader_adapter/precursor_membership.csv`의 `membership_id=card_member_70c83d44495b1e4bc511` → 해당 form이다. 이것은 kinase–substrate 기여 관계가 아니다.

**2. AKT1 방법 결과와 no-call**

`kinase/method_scores.csv`의 단일키 `method_result_id=method_result_e128e34506b2f1818851`이 동일 evidence ID로 인덱싱돼 있다. candidate는 `specificity_candidate_a215b771b4be54ff8a44`, 방법은 `PhosX_native_functions / 0.23.1`, 1분 vs Control이다. `eligible_site_count=0`, `universe_count=353`, `membership_ids` 빈 값, `status=insufficient_coverage`; `score/method_p/method_q/biological_p_value`는 NA다. 공식 원출력 `native_score=0.0`은 보존돼 있지만 평가 가능한 activity 0이나 비활성 판정으로 해석하지 않는다. 여섯 시간의 해당 candidate 결과 모두 coverage 부족이며 reader도 NA로 표시하도록 설명한다. Native Activity Score는 log2 A가 아니다.

같은 **candidate + contrast + track**으로 `science/inference_results.csv`를 연결하면 1분 `specificity_A`의 `call_id=call_v2_88e71cce421dd9fde19a`가 있다. `proposed_entity_id`가 위 candidate와 같고 `resolution=no_call`, 이유는 `insufficient_measurements;membership_turnover;species_mapping_ambiguous;uncalibrated_policy;unresolved_site`다. 이는 native method row 자체의 p/q나 activity를 대신하지 않는다. 같은 candidate의 6시간×3track 18행도 no-call이다. assay 이름을 rat ortholog/검증된 enzyme accession으로 바꾸지 않는다.

문헌 대상 `review_subject_6f2b7a781153897eb7b2`는 method readout이며 site 비교 금지 조건을 유지한다. 검색10구간, 모델 정상 빈 comparisons, 의미 `review_required`다. 문헌 실행으로 coverage/no-call 제한이 해소되지 않는다.

**3. TRIP10 문헌 실행과 정상 빈 비교**

`finding_a0f138f34e259e65da05` → `reader_card_44d8af5514248a891c6b` → `form_77aa7fcf6b0f78ec`. 후보 S296, taxon10116, localization 미측정. 15분 원본 키는 `(form_77aa7fcf6b0f78ec, contrast_eb2f813f825c4ccb)`이며 `U_joint=0.07245389778037747`, `P_joint=-0.011611873068364531`, `A=0.08406577084874378`(log2). 카드의 여섯 시간은 모두 finite이고 원본과 일치한다.

`reader/literature_subject_execution.csv`의 `review_subject_d82539f93c7ec7d3deaa`는 retrieved/completed/review_required다. `record_json.record`에서 14구간, `partial_retrieval_failure=false`, 모델 `comparison_execution.status=completed`, transport `finish_reason=stop`, diagnostics `parse_status=parsed`, `comparisons_status=empty`, `comparisons=[]`, `excluded_comparisons=[]`를 확인했다. 정상 빈 제안이므로 인용 검증 실패·no_hit·문헌 불일치가 아니다. 실제 원문/응답을 다시 실행하거나 의미 검토한 것이 아니라 저장된 상태를 확인했다.

실행 input SHA는 `6bf0fe6c194e2552df58596df777349854ed99b01fd32496767a618c22746f81`, output SHA는 `7954bd9d7a6ececbfcc52ad7cc7f0bf3cd1e58a2982fe42b6fbac1c4cb95d77e`다. 원 모델 기록은 `g11-r04-6e30058d47a249b984ba28f44cf28063`. 기존 legacy `reader/literature_search.csv`의 같은 finding에는 다른 과거 input hash와 제외6개가 남아 있다. 이를 새 M4의 빈 제안과 합산하거나 덮어쓰지 않는다.

출처 예: `literature_subject_links.csv`의 `review_link_c36bdee655d4d066b6b1` → source key `lit_source_92be33f95fe44673ce2f`. pin의 `retrieval.references[]`에서 collection/version + source_id `76a7804e26c35b59cb3c41d48304ae3a_76` + content SHA `593f897b8480fda407ceac45907cf4b0e7d5b081d555f688693dfa7ef1900caa`로 대응한다. 저장 서지는 *Mechanisms of Insulin Action and Insulin Resistance*, 2018, DOI `10.1152/physrev.00063.2017`, 위치 introduction/chunk_index74다. PMID는 빈 값이다. `metadata_only_export_permission_unconfirmed`이므로 이 ZIP 소비자는 원문을 직접 읽거나 TRIP10을 지지한다고 주장할 수 없다. MAPK1/AKT1의 source 연결도 같은 방식으로 확인했다.

**4. 보류된 MAPK3 표시 feature**

`form_eeaed22a5119b2f5`, 5분. raw evidence ID `card_row_2345c104f0802d1b833d` → `reader_adapter/form_contrasts.csv`의 `adapter_row_id`; 같은 키의 `reader/coverage.csv`는 `card_status=withheld`, `summary_disposition=raw_only`, `card_ids_json=[]`다. `quant/comparisons.csv`의 `(form_id, contrast_4147ebd64e7ecf80)`에 `U_joint=2.0073083988186013`, `P_joint=-0.2578735317128924`, `A=2.265181930531497`이 남아 있어도 `included=False`, `mapping_ineligible;parent_ineligible`이다. raw 조회 가능성을 primary 적격성으로 승격하지 않는다.

`reader_adapter/form_identity.csv`의 해당 form은 `mapping_status=multiple_genes`, `mapped_genes=ENSRNOG00000067941;MAPK3`, `parent_gene_concordant=false`. accession/isoform별 T203/Y205, T178/Y180, T180/Y182 후보를 하나의 확정 site로 줄이지 않는다. 6개 대비 모두 카드 보류이며 60분 U/P/A는 NA와 `target_joint_unobserved`를 유지한다. 문헌 계획의 `review_subject_f1b5f97795925726636b`는 raw_ptm, `not_requested/not_performed/not_reviewed`이고 실제 M4 실행표에 없다. 이는 검색 실패나 반대 문헌이 아니다.

## 상태 해석과 발견한 표시상 문제

현재 M4는 **요청3개 completed / 전체158,593개 표현 partial / 미요청158,590개**다. 세 대상의 제안·anchor 통과/거부·의미 승인은 모두0이며 의미 상태는 review_required다. 고유17구간/문서5개(외부 논문4편·방법 메모1개)는 읽은 논문 전문 수나 독립 검증 수가 아니다. 현 발행은 고정 결과 소비라 `current_cost`가 query/model 0/0이다. 이것을 과거 검색·모델 실행 자체가 없었다는 뜻으로 읽지 않는다. `authoring_packet.json.literature_subject_execution.summary`와 summary 파일은 일치한다.

|재현 경로 / 관찰|영향받는 서술과 안전한 읽기|향후 최소 수정 위치 — 이번에는 수정하지 않음|
|---|---|---|
|`READ_ME.md`의 TRIP10 제한은 legacy `retrieved_comparison_pending`; 원 card의 `literature_comparison_status=not_performed`. 반면 legacy 내부 `comparison_execution.status`와 새 M4 비교는 completed. `EVIDENCE_ACCESS.md` 끝에도 “deferred to M3/M4”가 남아 있음.|“문헌 실행을 아직 하지 않았다”는 오독 가능. 원 card 생성 단계, 과거 legacy 검증 상태, 현재 typed 실행·제안·의미 상태를 분리하고 M4 실행표를 우선 참조한다. 전체 안내와 packet에는 올바른 M4 링크가 있으므로 데이터 접근이 막히지는 않는다.|ZIP 코드 `astra_reader.py::write_reader` 약644행의 legacy 단일 status 표기, `astra_reader_full.py::write_full` 약289행의 고정 미래형 안내. 원 pin/card를 덮어쓰지 않고 표시층에서 범위·실행/검증 상태를 명시하는 경계.|
|`LITERATURE_SUBJECT_REVIEW.md`의 “원 실행 run”은 `g0-985e38092ff745288309d2dbcd606140`; 실제 대상 diagnostics의 실행은 TRIP10/AKT1의 g11-r04와 MAPK1의 g11-r03이다. 같은 문장에서 `summary.current_cost`를 원 실행 기록으로 설명함.|g0는 등록/frozen pin 출처 archive, g3는 소비 archive, diagnostics.run_id는 실제 비교 실행이다. 0/0은 이번 소비 비용이며 원 모델 실행 횟수가 아니다. pin의 component 원 기록과 diagnostics를 사용한다.|`astra_literature_review.py::write_review_execution` 약727–729행의 run/cost 설명. binding·pin 값은 그대로 두고 등록 archive/실제 실행/소비 비용의 명칭을 구분하는 위치.|

나머지 점검에서는 summary를 전체 범위로 제한하거나 precursor를 kinase 관계로 바꾸는 안내, coverage/no-call을 비활성으로 선언하는 안내를 발견하지 못했다. `PHOSX_TIME_COURSE.md`는 native score/방법 p·q/NA를 구분하며, localization 미측정·기술 반복·calibration 부재를 유지한다. 문헌 상태의 위 표기 혼동을 피해 보고서를 작성할 수 있지만, 이를 “모든 표현에 문제가 없음” 또는 생물학적 타당성 승인으로 보고하지 않는다.

## 이번 확인 결과와 종료

ZIP 직접 읽기로 대표 관련 canonical key80개를 원 행에 해석했고, 두 관측 카드의 6시점×U/P/A **36개 값/NA**, AKT1 방법6행·동일 candidate no-call18행, 보류6행, subject→구간39개 연결을 확인했다. 읽은 안내6개의 상대 링크116개도 ZIP member로 연결된다(링크 출현 수이며 독립 근거 수 아님). 이것은 전체 원본 전수 재검증이 아니다. 기존 replay/보존 결과와 중복 합산하지 않는다.

회차04 완료 상태와 성공 패키지를 유지한다. 이 메모의 재현 위치·주의사항만 남기며 새 기능 개발이나 다음 회차를 시작하지 않는다. 전체 접근 가능성은 확인했지만 전체 표현을 읽거나 문헌 비교·과학 검토를 완료한 것은 아니다. 최종 패키지 소비 검증은 **대표 경로 접근 확인, 표시상 주의사항 있음**으로 종료한다.
