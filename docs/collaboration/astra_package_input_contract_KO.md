# 입력 → Astra 전달 계약과 migration

## 입력 인벤토리

`Order` 전체를 serialize하지 않는다. `astra_inputs.RESEARCH_FIELDS`는 project_name, order_code, species, organism_code, ptm_type, sample_config, analysis_context, analysis_options, report_options, rag_collections, secondary_ptm_type, secondary_sample_config를 포함한다. 파일 필드는 PR/PG/FASTA/config/secondary 파일의 basename·존재 상태를 전달한다. 업로드 시 원래 filename을 context에 별도 보존한다.

| 입력 위치 | API/저장/worker | 패키지 |
|---|---|---|
| 프로젝트명·주문 코드 | Order의 개별 필드 → dispatch snapshot | user_input_snapshot, STUDY_BRIEF, provenance |
| sample_config file/condition/group/Rep | 원문 + canonical resolver | 원문 snapshot + study_design injections/materials/conditions/contrasts |
| analysis_context | 원문 및 structured provenance를 승계 | study_context + snapshot + field manifest |
| biological_question·special_conditions·time_points·cell_type·treatment | 요약으로 대체하지 않음 | 전체 원문 + canonical 해석 + brief |
| report_options.research_questions | report mode와 무관하게 저장 | 전체 질문과 작성 선호; legacy report 실행으로 표기하지 않음 |
| analysis_options·secondary 설정 | 요청값 보존, 실제 적용 상태를 plan에서 설명 | raw-only 포함, 미지원 처리 완료로 표시하지 않음 |
| rag_collections null / IDs / [] | all-active의 실제 목록 / 명시 목록 / 미선택 구분 | literature_pin: ID/name/version/docs/content_status |
| 선택 문헌 원문 | 기록된 재배포 허용과 실제 파일 확인 후 고정 | full_text_included / metadata_only / unavailable |
| 참고 논문·연구 자료 업로드 | 선택 파일을 주문별 upload scope에 저장, checksum 고정; Copy는 자료와 pin 승계 | references/documents에 실제 bytes 포함; provided_not_compared, 서버 stored_path 제외 |
| 업로드 config·단백질 목록 | 계산에 사용되지 않아도 보조 연구 입력으로 고정 | study/supporting_inputs + content hash/role |

새 nested 연구 필드는 안전한 원문 extensions로 보존한다. 새 `Order` column에는 allowlist 또는 명시 exclusion 분류가 필요하며 schema drift test가 이를 검사한다. 인증/계정/진행 상태/운영 설정은 연구 입력 목록에서 제외한다. secret key는 값 없이 제외 사유만 기록한다. 서버 파일 경로를 원문 실험 사실로 노출하지 않는다.

## 세 층과 누락 검사

1. `study/user_input_snapshot.json`: run 시작 시점의 연구 입력, 원 field 경로, 원 record ID. 0/false/null/[]/Unicode/줄바꿈을 구별한다.
2. `study/study_context.json`, `study/study_design.json`: 실제 해석과 계산 관계, 단위/출처/미확정 사항.
3. `study/STUDY_BRIEF.md`: 전체 질문·맥락·조건·대조군·문헌 포함 상태. Results 미리보기도 이 동일 serializer 결과를 사용한다.

`input_field_manifest.csv`에서 각 leaf는 canonical_and_raw/raw_only/excluded 중 하나의 disposition을 가진다. 입력값을 canonical로 해석하지 못한 경우도 원문은 보존한다. `input_transfer_validation.json`은 누락 수와 disposition을 검증한다. 이 검사는 선언된 연구 allowlist의 완전성을 검사하며 원래 저장되지 않은 과거 질문을 복원했다고 주장하지 않는다. 과거 미저장 질문은 `not_persisted_in_source_order`다.

## 불변 결과와 Copy/Rerun

완료 package의 snapshot/source/normalization은 현재 form으로 다시 그리지 않는다. Copy는 canonical design·질문·문헌 pin·source pin을 승계한다. 문헌 선택이나 첨부 checksum을 바꾸면 기존 pin을 그대로 적용하지 않는다. 참조 갱신은 고급 설정의 명시적 새 실행이며 기존 pin을 덮어쓰지 않는다.

정량 cache는 input bytes, numeric design, estimator, normalization, 관련 code fingerprint에 의존한다. 질문만 바꾸는 재실행은 정량을 재사용하고 새 context revision/run/package를 만든다. Annotation/temporal 변경은 각 fingerprint에 반영한다. 현재 discovery/temporal는 새 run에서 재계산하며 정량 stage의 reuse만 보장한다. cache metadata에 원 계산 run을 보존하고 현재 설정으로 과거 계산을 다시 설명하지 않는다.

v2/v3 결과는 기존 adapter로 읽고 실행한다. v4는 `quant/` 아래의 기존 22개 CSV와 추가 typed/scientific 표를 `v3_migration.json`으로 연결한다. 다운그레이드 시 새 run 생성만 중단하고 이미 완료된 ZIP을 그대로 보관한다. v4 source cache나 run directory를 오래된 v3 result로 덮어쓰지 않는다.
