# AI03 — 필드 의미와 현재 문헌 실행 상태

기준 회차 AI02 `563eec9`, branch `codex/astra-ai-usability`.
AI03-A와 AI03-B는 별도 로컬 commit이며 SHA는 최종 통합 표에 기록한다.

## AI03-A: column-level dictionary

수정 전 실제 `write_tables` 반환에는 `field_semantics`가 없어 회귀 fixture가 KeyError로 실패했다.
기존 `quantitative_fields.py`에 `field_semantics`, `table_field_semantics` 공통 projection을 추가했다.
writer, reader 안내, 후속 batch/claim은 같은 계약을 사용한다. `astra_field_semantics.v1`이다.
모든 열에 field path/meaning/scale/unit/allowed range/nullable/null status binding/statistical unit/FK를 제공한다.
`observed_null_count`는 실제 null 수이며 null 허용 계약과 구분한다. 미등록 열은 descriptor 자체를
생략하지 않고 `status=unknown`, `unknown_reason=unregistered_or_legacy_field`로 기록한다.

| 필드 | 구분 |
|---|---|
| A/U_joint/P_joint | 같은 주입 joint mask의 log2 상대 효과, absolute occupancy 아님 |
| U_all/P_all | 각자의 관측 mask를 사용한 상대 효과 |
| ptm/parent_intensity | 제공 intensity, upstream 정규화 추정 없음 |
| native Activity Score | PhosX 0.23.1의 native score, PTM log2 변화량 아님 |
| repository z_score | 실제 measured-gene universe의 표준화된 기술적 enrichment |
| activity_magnitude | 기존 substrate footprint, 확정 kinase activity 아님 |
| method_p/q | 기록된 method null model/family/statistical unit, biological p/q 아님 |
| biological_p/q | biological unit/pair 계약, 기존 null 그대로 |
| localization_probability | 제공한 confidence만; 미측정 null을 승격하지 않음 |
| joint/observed n vs biological n | injection 관측 수와 biological unit 수 구분 |
| time / boolean / ID | minutes / mask / locator, score와 구분 |

method contract는 `(method_id, method_version, score_name)`과 row의 direction_semantics,
null_model, multiple_testing_family, statistical_unit으로 세분한다. 의미가 미기록인 임의 score나
percentile은 log2 또는 probability로 추측하지 않는다. PhosX adapter/evidence_methods의
기존 정의를 확인했으며 null model/family는 상수 복제 대신 실제 row에서 읽는다.

`astra_package.write_tables`의 row count/key/dtype/CSV 직렬화는 유지한다. `reader/FIELD_SEMANTICS.md`와
packet dictionary 링크를 추가했고 일반/reader code snapshot에 quantitative_fields.py를 포함한다.
변경 대상은 dictionary/index descriptor/reader 안내다. 숫자·NA·p/q/CI를 채우는 코드가 없다.

AI03-A 테스트: 최초 10 passed(새 semantics 2 + 기존 catalog 8), 추가 score 구분을 포함한
semantics 3 passed. **고유 11개**, skip 없음. `AI03A.xml` 및 후속 test 기록.
fixture CSV는 `frame.to_csv` bytes와 동일하다. 일반 작은 package 생성/기존 reader replay,
pointer 보존 및 source-key 회귀도 통과했다. 실제 과학 재계산/native/RAG/LLM 신규 호출 0회.

## AI03-B

AI03-A SHA: `c6e5f48`. AI03-B는 `astra_execution_status`의 작은 공통 projection을 추가한다.
`attach_current_status/project_current_status`가 validated frozen packet의 selected-finding 기록과
typed subject summary/binding을 각각 읽는다. 기존 M2 미수행 설명은 historical_origin으로 보존하고
whole_evidence/question/access의 현재 표시는 `reader/EXECUTION_STATUS.json`을 가리킨다.
검색·모델 비교·anchor·의미 검토·export·외부 검토를 분리한다. 요청 범위 completed와 전체 partial을
동시에 유지한다. 정상 빈 모델 비교는 completed/제안0이며 unknown trace는 임의로 미수행/실패로 바꾸지 않는다.
검색 no_hit와 미요청은 구분한다. 검색 실패가 섞인 finding 기록은 partial이다.
query 비용·문헌 구간·문서·독립 외부 논문·승인 수는 서로 대체하지 않는다.

`astra_literature.apply`, `attach_full`, `attach_review_execution`이 같은 projection을 연결한다.
`write_reader`, 문헌 guide, FULL_EVIDENCE, authoring_packet, readiness와 START_HERE는 공통 현재 상태를
노출한다. 기존 write_review_plan의 실제 실행 분기는 유지한다. 원 pin/원 execution summary를 수정하지 않는다.
projection 자체의 호출 비용 0과 원 실행 비용/이번 frozen consumer 비용은 별도 필드다.
`revise_temporal/revise_literature`에서도 새 revision의 readiness를 갱신한다.

실제 G11 저장 packet의 과거 whole_evidence는 `unchanged; M3/M4 not performed`였지만,
검증된 M4 기록은 요청3/모델비교3, 요청 completed/전체 partial, 고유 구간17/문서5/독립 외부논문4,
export anchor 제안0/승인0, frozen consumer query/model0이었다. 새 projection이 이를 보존한다.
`codex-inputs/astra-ai-20261113/actual_current_status.json`에 상태와 불변 source packet hash를 기록했다.
실제 원본은 쓰지 않았다. 실제 M4를 새로 실행한 검증이 아니다.

AI03-B regression은 `PYTHONPATH=.:workers:ptm_shared/tests`의 기존 runtime으로 실행했다.
초기 실행은 workers/common import 경로 누락으로 실패하여 경로를 수정했고, reader 산출물 두 개가
추가된 계약에 맞춰 기존 replay 기대 파일 수를 31→33으로 갱신하고 파일명을 함께 검증했다.
`test_ai_execution_status`, 기존 literature/review/full-reader 회귀 **33 passed**, skip 없음.
새 실제 writer 상태 일치 assertion과 semantics 경계(분당 log2 변화율은 minute 자체가 아님)를 추가한
최종 부분 재검증 **10 passed** (`AI03B_final.xml`); 기존 33 및 AI03-A와 중복되는 테스트다.
fixture retrieval/model은 대역이며 실제 외부 검색/LLM 호출 0회다. 반복 테스트 수는 합산하지 않는다.
현재 상태 projection은 승인 정책을 바꾸지 않으며 biological p/q·문헌 결과·source/pin·기존 pointer를 보존한다.
