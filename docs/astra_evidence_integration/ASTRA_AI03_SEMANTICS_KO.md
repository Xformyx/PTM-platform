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

현재 실행 상태 projection과 검증 결과는 다음 별도 commit에서 이어 기록한다.
