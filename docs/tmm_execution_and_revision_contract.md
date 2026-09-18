# Production TMM execution and immutable revisions

TMM은 Temporal Mixture Modeling이다. `temporal_analysis_input.v1`과 `temporal_analysis_revision.v1`은 기존 report revision의 atomic/hash primitives를 재사용한다. 새 `analysis_jobs`, `analysis_heads`는 SQLAlchemy 모델 등록과 기존 `Base.metadata.create_all` 경로로 additive 생성한다. 과거 Order JSON/파일은 그대로 읽을 수 있으며 새 job 결과는 파일 registry pointer를 저장한다.

## 접수/조회

- `POST /orders/{id}/analysis-jobs`: write-authorized submit, 동일 완료 결과면 200, queued/running이면 202 + job_id/status_url/result_url.
- `GET /orders/{id}/analysis-jobs/{job}`: 주문 접근 권한과 job 주문 scope 검사.
- `GET .../{job}/result`: required stage/checksum 검증 후 결과와 revision manifest 반환.
- `GET .../{job}/artifacts/{artifact_name}`: 해당 revision registry에 등록된 artifact만 다운로드. revision/sha256 header 제공.
- `GET .../{job}/inventory`: full feature/unassigned/member 원장의 bounded cursor. 기본 결과는 작은 candidate summary이며 대량 원장을 반복 전송하지 않는다.
- `POST .../{job}/retry`: 같은 signature의 완료 stage를 재사용하며 실제 실행 lock이 비어 있어야 한다.
- `POST .../{job}/cancel`: 명시적 취소. browser disconnect는 취소가 아니다.

기존 global-kinase-modules/heatmap POST는 기본 full_eligible submit의 adapter다. global cache probe는 이전 성공 revision과 요청 중인 job/stale 여부를 함께 반환한다. source/reference/runtime 변경도 stale로 표시한다. 차트 refresh로 parent pipeline generation을 올리지 않는다.

접수는 이미 publication된 작은 manifest를 읽는다. TSV 전체 읽기/후보 생성/TMM/diagnostics는 API event loop에서 하지 않는다. hash에는 전체 candidate를 결정하는 measurement/reference/context/config, canonical schema, 모든 공유 계산 코드, solver dependency, RNG policy를 포함한다. UI/RAG 예산은 포함하지 않는다. runtime code fingerprint는 process lifetime 동안 cache하므로 배포 시 API/worker를 재시작한다.

## 실행과 fencing

기존 Celery/Redis를 사용하며 `production_tmm` queue와 실제 소비 worker를 compose에 추가했다. API image에서 `app.tasks.production_tmm:celery_app`을 실행한다. broker에는 job ID 또는 주문 ID/config만 보낸다. benchmark worker 권한/입력 경로를 사용하지 않는다. 기존 late ack/prefetch 정책 자체를 새 개선으로 간주하지 않는다. production worker에도 BLAS 1-thread 설정을 전달한다.

required stages: input_validation → candidates → score → trajectory_diagnostics → temporal_diagnostics → result. score 완료는 전체 completed가 아니다. relative/occupancy track의 평가 가능성도 따로 저장한다. 완료 stage는 JSON/auxiliary checksum과 signature가 맞을 때만 redelivery에서 재사용한다. 실패한 partial rows를 정상 점수로 publish하지 않는다.

DB에 queued/running/completed/failed/timed_out/cancelled/superseded와 evaluation_status/failure_reason/stage elapsed/peak process RSS를 보존한다. 각 attempt UUID 디렉터리에 artifact를 만들고 validate 후 current pointer를 갱신한다. generation/attempt/input revision/parent generation이 일치해야 publish한다. 새 실패/cancel/superseded 결과는 과거 성공 pointer를 바꾸지 않는다. explicit_subset은 full head와 독립적이다.

Order row lock이 admission/publish/cancel을 직렬화한다. active_key unique constraint는 같은 signature의 활성 job 중복을 막는다. 동일 job의 실제 실행은 공유 POSIX volume의 `flock`으로 보호하며 process 종료 전에 슬롯을 반환하지 않는다. lock 파일을 삭제해서 작업을 재개하지 않는다. API의 legacy bounded_compute는 process-local 보호일 뿐 multi-process 전역 admission이 아니다. await 취소 후에도 실제 thread가 끝날 때까지 local slot을 유지한다.

명시적 cancel은 queued job을 즉시 취소하고 running job은 stage 경계에서 확인한다. CPU stage를 중간에 안전하게 interrupt하는 기능은 제공하지 않는다. soft limit 21,600초, hard limit 21,720초, Redis visibility 43,200초다. 이 값은 처리 성능 보장이 아니다. worker는 별도 DB connection에서 30초 heartbeat를 기록한다. API lifespan의 watchdog는 120초 lease를 관찰하되 실제 flock을 획득할 수 있을 때만 죽은 attempt를 fence하고 재접수한다. 만료 시간만으로 CPU 슬롯을 반환하지 않는다. 자동/수동 복구는 job당 3회 한도이며 API/UI에 단계·취소·재시도 상태를 제공한다. nullable heartbeat_at/recovery_count의 additive startup migration을 포함한다. broker 재전달/운영 재시도는 verified completed stages만 재사용한다.

## Migration/rollback/운영 검증

API와 production worker에 동일 shared code/reference bundle과 read/write output volume을 배포한다. DuckDB dependency를 설치하고 신규 테이블 생성을 확인한다. index가 없는 과거 주문은 prepare operation으로 raw/TSV 보존 상태에서 additive index/input snapshot을 생성한다. provenance가 불완전한 과거 분석을 재계산 완료로 표시하지 않는다. Quick provenance도 유지한다.

rollback은 이전 코드/config와 검증된 full head/Order pointer를 함께 선택하는 운영 migration이다. 새 immutable artifact와 감사 이력을 삭제하지 않는다. 자동 rollback endpoint는 추가하지 않았다. 새 schema를 모르는 reader는 임의 해석하지 않아야 한다.

SQLite 실제 route→executor→artifact 시험에서 취소, stage failure, simulated disk error, verified redelivery, generation fencing, checksum tamper, subset/full pointer 분리를 검증했다. 이것은 MySQL lock/Redis/Celery kill/restart/race 검증을 대체하지 않는다. Docker daemon이 없어 해당 staging 시험과 heavy-job login/health latency 측정은 미완료다. 기존 성공 revision이 없는 경우 failed 작업을 빈 성공/0점으로 반환하지 않는다.

artifact checksum은 최초 접근에 검증하고 inode/size/mtime/ctime가 같은 immutable 파일에 한해 재사용한다. 파일 변경·교체 시 다시 검증한다.

큰 contribution/diagnostic 원장은 DB JSON 대신 파일에 저장한다. candidate summary와 Parquet member/feature cursor를 worker가 publication하며 UI는 module/member 목록을 페이지로 조회한다. 대규모 production TMM의 메모리/SLO를 검증하기 전 지원 규모를 단정하지 않는다.
