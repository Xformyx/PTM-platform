# Analysis universe: full_eligible_precursor.v1

기본 TMM의 입력은 서버의 immutable preprocessing snapshot이다. Top N, checkbox, viewport, RAG 문헌 예산은 입력이나 cache signature에 포함하지 않는다. API와 RAG 자동 분석은 `analysis_jobs.submit_analysis → production_tmm_executor → production_temporal_analysis`를 공통으로 사용한다. 브라우저의 `ptms`/`kinase_modules`는 기본 분석 모집단을 정의하지 않는다.

## 입력과 원장

`publish_analysis_input`은 기존 vector/condition comparison/site quantitation/protein trajectory, observation inventory/import audit/Quick manifest를 hash와 함께 복사한다. sample manifest, 실험 context, 정규화/시간 계약, Quick 설정, parent pipeline generation을 pin한다. 원본 경로와 과거 revision은 삭제하지 않는다. source credentials/provider 설정은 snapshot whitelist에서 제외한다.

`prepare_analysis`는 전체 vector를 정규화하고 full with-motifs 파일을 canonical precursor ID로 연결한다. normalized 파일에 motif 열이 없다고 후보가 사라지지 않는다. P0 feature provenance → P1 mapping → P2 relation의 기존 adapters를 사용한다. 검증된 curated site candidate와 `modified_residue_anchor.v1` motif candidate를 구분하며 RAG/LLM subset을 모집단으로 쓰지 않는다. source bundle unavailable은 미귀속/평가 제한으로 기록한다.

전체 inventory에는 identified, axis eligible/not_evaluable, mapped/unassigned, candidate IDs가 있다. source rows, identity unresolved와 quarantine count는 별도 집계다. 모든 feature가 모델 적격 또는 kinase에 매핑된다는 뜻으로 “전체 입력”을 사용하지 않는다. U가 있고 protein denominator가 없으면 A는 보류되며 U는 유지된다. partial time series는 complete series와 함께 있어도 유지한다. sample/biological unit을 값 일치만으로 deduplicate하지 않는다.

PR/PG malformed TSV는 `tabular_import`가 원래 위치/record/reason을 quarantine JSONL에 보존하고 count audit을 남긴다. CSV 구조 파싱 실패는 전체 성공으로 처리하지 않는다. raw 파일 자체는 계속 보존한다. preprocessing observation inventory는 실제 원본 physical line을 사용한다.

## Full, Quick, subset

`full_eligible`은 **고정된 입력 revision 안의** 전체 적격 분석이다. Quick에서 생성한 입력이면 원래 Full 데이터 분석으로 승격되지 않는다. Quick 설정과 subset 정규화 한계를 study frame/report packet에 전달한다. provenance가 없는 과거 run은 legacy_unknown으로 남는다. Full 실패를 Quick로 자동 전환하지 않는다.

`explicit_subset`은 canonical feature IDs + subset_reason을 필수로 받는다. 자체 input signature/job/result revision으로 저장하며 full 분석의 requested/current pointer와 DB compatibility pointer를 변경하지 않는다. 유효 subset이 아닌 ID는 오류다. 같은 subset 요청은 같은 signature로 idempotent하게 처리한다.

full 분석은 source/reference/config/identity/solver/RNG/sample design이 바뀌면 새 signature다. 표시 설정만 바꾸면 같은 job/result를 사용한다. synthetic API→worker 시험에서 N=20/50/500, 체크 목록, RAG budget을 바꾸어도 job ID/result revision/score가 같았다. 이는 수정 전의 잘못 좁은 입력과 수정 후 전체 입력의 점수가 같다는 주장이 아니다.

## Report handoff

report task는 `resolve_analysis_artifacts`로 DB의 pinned job/revision을 검증하고 immutable source vector와 전체 evidence inventory를 읽는다. integrity 실패 시 현재 폴더의 비슷한 파일로 대체하지 않는다. stage/track 상태, eligible/mapped/unassigned/individual-no-call count와 shared group evaluation count, Quick scope, evidence artifact hashes/paths를 `analysis_evidence_inventory`로 전달한다. study frame의 `analysis_scope_contract`는 section packet compaction 후에도 남는다.

전체 inventory는 sidecar로 유지한다. 모든 ID/행을 매번 prompt에 펼치는 대신 원장 binding과 counts를 전달한다. 기존 writer 전체를 새 프레임워크로 교체하지 않는다. 실제 모델/provider를 호출한 원고 품질 평가나 독립 생물학 검증은 이 구현의 synthetic handoff 시험과 별개다.

## Legacy compatibility

`legacy_explicit_subset`은 기존 benchmark adapter 등 명시적 호출에만 남긴다. 새 full revision이 있는 주문을 legacy 계산으로 덮으려 하면 409다. legacy cache도 전체 요청/source/reference/runtime signature로 바꾸었다. benchmark truth/baseline/preregistration은 수정하지 않았고 production 입력에 넣지 않는다.

기존 private RAG legacy 구현은 호환/비교용으로 남아 있지만 기본 자동 실행은 공통 durable service로 연결했다. 현재 코드에서 기존 DB 결과를 새 full revision으로 자동 backfill하거나 final-ready로 승격하지 않는다.
