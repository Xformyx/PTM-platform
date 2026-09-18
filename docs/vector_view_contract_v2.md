# Vector view v2

구현 기준: `b150a010fc6374239eec0a2b1d88922d6b871c27`, 2026-09-18 명령서. 이 문서는 구현된 계약을 설명한다. 운영 배포/실데이터 검증 결과는 [검증 기록](implementation/vector-tmm-validation.md)에 별도로 구분한다.

## 측정, 연결, 선택

`vector_projection → vector_plot → plot_selection → services/vector_view → GET /orders/{id}/vector-plot-data`가 기본 경로다. 기존 `precursor_identity.v2`를 유지한다. 표시 이름을 고치려고 ID를 재생성하지 않는다. `source_gene_label`, 원본 record, source row lineage와 정량 축을 보존한다. metadata 차이만으로 quantitative conflict를 만들지 않으며, observation unit 또는 통계/정량 차이는 conflict로 보류한다.

`annotation_context.v1`은 matching에만 gene의 공백/대소문자를 정규화한다. residue+position만 정규화하며 숫자 위치에 residue를 추정하지 않는다. taxon, accession/protein group, isoform, 좌표계가 다르거나 불완전하면 direct site match를 만들지 않는다. 같은 annotation identity의 서로 다른 assertion을 덮어쓰지 않는다. 원본 label, annotation ID/source assertion, match status/method/scope/reason을 독립적으로 보존한다. gene-only context는 `rag_only`의 선정 근거가 아니다. 검증된 alias crosswalk의 신규 연결은 이 변경에 포함하지 않는다.

기본 선택은 RAG와 독립적인 `per_condition_top_n`이다. 최초 N은 주문의 기존 `report_options.top_n_ptms`, 없으면 공통 기본값 50이다. 이후 표시 설정은 주문별 `vector-view.v2:{orderId}` localStorage에 저장하며 report/RAG 설정을 변경하지 않는다.

| mode | n | 선택 |
|---|---|---|
| per_condition_top_n | 양의 정수 | 조건별 modified precursor Top N의 합집합 |
| global_top_n | 양의 정수 | feature별 최대 abs(effect)의 전체 Top N |
| all_observed | null | 선택 축의 유효 관측을 하나 이상 가진 모든 feature |
| rag_only | null | 검증된 feature/site_context annotation match |

기본 ranking은 선택 canonical axis의 `abs_effect`, 동점은 `feature_id` 오름차순이다. q/FC 문턱을 표시 적격성에 새로 넣지 않는다. `legacy_ranking_score`는 별도 명시적 모드다. 선택된 feature의 모든 조건을 회수하며 숫자 시간과 단위를 사용한다. 없는 값은 null, 0은 측정값이다. de novo/LOD/intensity를 conventional FC와 섞어 ranking하지 않는다. legacy 9999는 저장된 초기 설정의 migration에서만 All로 해석하고 새 계약에는 사용하지 않는다.

기본 세 mode는 annotation missing/empty/partial/failed에도 같은 측정 목록을 반환한다. rag_only의 source missing/failed는 unavailable, 유효하지만 matching 0개는 empty_selection이다. fallback으로 전체 목록을 반환하지 않는다.

## 응답과 coverage

`VectorViewResponse`는 `vector_view.v2`, measurement revision, selection hash, sources, coverage, features, observations를 검증한다. 호환 `vector_data`와 `top_n_ptms`는 동일 결과의 alias다. source revision은 vector 파일의 SHA-256에 고정되며 annotation revision만 바뀌어도 기본 selection hash/정량은 변하지 않는다.

coverage의 source_rows/identity_unresolved_rows는 원본 행 단위다. selected/identified/annotation partition은 feature 단위이며 finite_observations는 feature-condition 단위다. annotation matched + unmatched + ambiguous = selected가 성립한다. annotation 미연결은 기본 보기의 제외 사유가 아니다. conflict/missing denominator/nonfinite/outside_top_n 등을 단계별로 구분한다. UI의 checked/visible/rendered points는 별도 상태다.

평균 abs(effect)+2 population SD 기반 Suggested 수는 전체 축 적격 분포의 참고값이며 자동으로 N을 바꾸지 않는다. 한 점만 있는 feature와 null gap을 실제 chart에서 검증한다. canonical null을 Scatter에서 0으로 바꾸지 않는다.

## 대규모 보기

전처리 publication은 원래 TSV와 별도로 `vector_columnar.v2` Parquet를 만든다. DuckDB 의존성은 API/worker에 선언했다. float64, null, canonical ID, 원본 record/lineage를 보존하며 streaming row groups와 제한된 ingest memory/spill을 사용한다. source 변경 검사 후 버전 파일을 atomic publication하고 file lock으로 동시 publication을 직렬화한다. 원본/과거 Parquet는 삭제하지 않는다. v1 index는 incompatible이며 재구축한다.

`POST /orders/{id}/vector-view/{operation}`:

- manifest: 작은 revision/count/condition 응답.
- features: cursor 목록, 최대 1,000 IDs/요청. UI는 100개씩 검색/pin한다.
- trajectories: 지정 feature의 전체 실제 시점, 최대 1,000 IDs/요청.
- density/distribution: 전체 적격 관측의 결정적 bin/count/extrema.
- diagnostics: unresolved/malformed/conflicting 원본 행의 cursor와 전체 count.
- annotations: feature cursor별 left-joined annotation status/source/span/provenance.
- coordinates: 원래 float64 좌표와 ID의 cursor 조회. rectangle 또는 polygon lasso를 원좌표로 평가한다. 3~4,096 finite 꼭짓점만 허용하며 예산 초과는 오류다.
- prepare/preparation_status: 기존 주문의 additive index 준비를 durable queue에 요청/조회.

`GET .../vector-view/export?measurement_revision=...`는 원본 row record를 NDJSON으로 모두 제공한다. 인증과 revision 일치를 확인한 뒤 immutable 파일 connection을 고정하고 streaming한다. 불일치는 HTTP 409다. 기본 v2 응답이 10,000 features를 넘으면 명시적 pagination 요구 오류를 반환한다. 조용히 clamp하지 않는다.

admin/user Scatter는 전체 Canvas density와 정확한 drilldown을 공유한다. 전체 time-series는 분포 + paginated exact curves, Top N은 가상 checkbox 목록 + 명시적 100곡선 viewport를 사용한다. 큰 kinase Heatmap은 행/열 viewport를 가상화하며 큰 kinase Line Chart는 전체 정확한 궤적을 Canvas로 그린다. CrossTalk의 기존 single-linkage **표시 정렬**은 별도 browser worker와 입력 객체별 cache로 이동했다. 그 정렬을 scientific wave membership으로 사용하지 않는다.

## 호환성과 제한

선택/label 변화로 양, p/q, estimator 또는 canonical ID를 바꾸지 않는다. 기존 GET의 무거운 receptor 재계산은 명시적 write-authorized POST `receptor-inference-refresh`로 분리했다. 기본 조회는 이를 실행하지 않는다.

Parquet 최적화는 conventional U/A/P에 적용한다. rag_only/다른 representation의 상세 selection은 TSV 경로를 사용하며 대규모 비용이 남아 있다. FullTrajectoryBrowser 검색은 현재 canonical ID 기준이다. 주석 상세는 전체 관측 browser에서 열 때 cursor API로 조회한다. 이 데이터의 해석과 원본 측정의 평가를 분리한다. UI 선택과 TMM 입력을 연결하지 않는다.
