# AI06-A — budgeted evidence bundle

기준 AI05 `31d8844`, branch `codex/astra-ai-usability`; 로컬 SHA는 최종 통합 표 참조.

`EvidenceCatalog.bundle` / `astra_evidence_bundle.bundle`은 기존 query filter와 source resolver를
같은 session에서 사용한다. 새 검색 DB/embedding/RAG 엔진은 없다.

```sh
PYTHONPATH=reproducibility/code python -m ptm_shared.astra_evidence_catalog --package . bundle --request '{"scope":{"effect_series_id":"<saved-id>"},"row_budget":100,"byte_budget":262144}'
```

요청: catalog_id(일치 검사), scope(entity/effect_series_id/method_id 등 기존 filter + question_id),
source_roles, row_budget, byte_budget, continuation. 응답 `astra_evidence_bundle.v1`에는 requested/applied
scope, total/returned/remaining count, next_cursor, truncation/limit_reason, 원본 typed ref, 실제 저장 값,
필드 정의 및 현재 문헌 실행 상태가 있다. count 단위는 source row representation이며 biological n이 아니다.
별도 scoring/검토/문헌 비교를 실행하지 않는다.

기본 응답은 budget 안의 source 행만 가져온다. 전체 표를 JSON으로 한 번에 복제하지 않는다.
정의는 응답 안에서 참조 ID로 공유한다. byte 계산은 실제 UTF-8 직렬화 전체를 기준으로 한다.
첫 행 자체가 budget보다 크면 행을 건너뛰지 않고 returned0, 같은 offset의 cursor,
`byte_budget_requires_larger_response`와 minimum_required_bytes를 반환한다.
budget을 늘려 이어 받을 수 있다. cursor는 catalog/run/provenance/filter/역할/정렬 계약에 결합한다.

질문/반대 관측/parent/method/문헌 관계는 기존 full_question_links의 정확한 FK만 사용한다.
catalog-only context에는 임의 scalar effect scope를 만들지 않는다. 명시적 source_table 요청은
등록된 원본의 전체 canonical key population에 page를 적용하므로 문헌 구간/미검토 기록도 회수할 수 있다.
exact question binding이 없는 문헌 구간은 additional_context_access로 별도 접근과 한계를 표시한다.
모든 원문을 해당 주장에 연결된 근거처럼 취급하지 않는다. 미연결 질문 역할도 count/원본 접근을 남긴다.

## 무결성·성능

기존 session 파일 변경 감지/hash 검증을 유지한다. 한 source의 모든 canonical key와 row count를
먼저 검증한 뒤에만 필요한 행을 찾고 scan을 종료할 수 있다. 요청 뒤쪽의 중복 key도 거부한다.
작은 source는 session 내 최대32MiB LRU로 재사용하고 큰 표는 검증된 streaming을 사용한다.
source bytes가 달라지면 continuation과 resolve가 실패한다. 무조건적인 hash 생략은 없다.

수정 전 bundle API는 없었고 regression은 AttributeError였다.
수정 후 budget/page1/5/전체의 모든 evidence ID·순서·source key·값/NA가 같고,
mixed pairing 시계열, 미선정/보류/no-call, 큰 행 재개, 다른 scope/catalog cursor 거부,
source 변조 및 요청하지 않은 뒤쪽 duplicate key 거부, 질문/역할/저장 문헌 구간을 검증했다.
AI06A.xml **17 passed**(새4 + AI01/catalog 기존13), 마지막 경계 수정 후 새4 재검증 통과.
skip 없음. 일반 writer와 bundled module snapshot에도 연결했다.

실제 G11 저장 quant 행6개를 기준 commit의 원 모듈(query 후 행별 resolve)과
현재 session bundle(응답당2행)로 읽었다. 실제 값/NA/ID/key가 같았다.
한 번의 로컬 측정이며 일반 성능 향상을 보증하지 않는다.

| 측정 | 기존 | bundle |
|---|---:|---:|
| session open 초 | 2.569 | 2.544 |
| 조회/resolve workflow 초 | 1.157 | 0.771 |
| source read 함수 호출 | 6 | 6 |
| hash read 호출 | 19 | 17 |
| source root 파일 open audit event | 25 | 27 |
| 직렬화 응답 bytes | 16,364 | 87,423 |

bundle은 정의/상태를 추가하므로 출력이 더 크고 file open 감소도 관측되지 않았다.
토큰 절감이나 미측정 성능 수치는 주장하지 않는다. 결과 `codex-inputs/astra-ai-20261113/bundle_benchmark.json`.
comparisons/method_scores/manifest/기존 pointer hash는 실제 읽기 전후 불변이다.
실제 과학 재계산/PhosX/외부 검색/LLM 신규 호출0. 실제 matched 검증은 합성 범위다.
