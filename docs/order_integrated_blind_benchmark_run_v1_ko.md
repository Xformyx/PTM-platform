# Order-Integrated Blind BenchmarkRun v1

## 목적과 경계

`BenchmarkRun`은 기존 Order를 바꾸지 않고, 해당 Order의 matrix·timepoint·replicate·FASTA만을 별도 snapshot으로 복사해 strict primary benchmark를 실행한다. Source Order에 보존된 treatment, 정확한 cell-line, transgene, disease model, project/order/file 이름, biological question, special condition, RAG collection 및 Co-Scientist context는 child Order와 offline scorer에 전달되지 않는다.

이 기능의 primary contract는 `tmm_full_temporal.v1`이다. 즉 0층 preprocessing을 완료한 뒤 1층의 canonical Wave, full global kinase module, TMM temporal heatmap을 실행하며, RAG·report generation·LLM·Representation Learning은 canonical benchmark score에서 제외한다.

## 사용자 흐름

완료된 Order Detail에서 **Benchmark Evaluation**을 열고 `Start Blind Benchmark`를 선택한다. Preflight가 time-course, PR/PG matrix, FASTA, phosphorylation PTM type을 확인한다. 사용자는 exact cell-line이 아닌 controlled lineage class만 선택한다. Snapshot이 시작되면 source input의 sample header는 `S001`, `S002` 등으로 치환되고, treatment condition은 `Treatment A`의 time axis만 남긴 neutral label로 바뀐다.

0층 child preprocessing이 끝나면 같은 Benchmark tab에서 **Run TMM + locked score**를 선택한다. 이 단계는 production global kinase module 및 TMM heatmap 코드 경로를 child Order에 적용한다. Generic site observation artifact가 archive된 뒤에만 전용 `benchmark-runner`가 dataset-specific locked truth를 열어 canonical score bundle을 생성한다.

## 서버 구성

| 구성 요소 | 위치 | 역할 | Locked truth 접근 |
|---|---|---|---|
| API | `api-server` | BenchmarkRun registration, preflight, child snapshot, temporal orchestration | 없음 |
| Ordinary preprocessing worker | `workers` | 0층 preprocessing of sanitized child Order | 없음 |
| Production API temporal path | `orders.py` | full global kinase module + TMM heatmap | 없음 |
| Offline scorer | `benchmark-runner` | archived artifact와 manifest로 Tier 1/2 score | 전용 read-only mount만 허용 |

`docker-compose.yml`의 `benchmark-runner`만 `./benchmarks:/opt/benchmarks:ro`를 mount한다. API와 ordinary worker Dockerfile에는 `benchmarking` 또는 locked truth copy가 금지된다. `benchmarking/tests/test_runtime_boundary.py`가 이 분리를 회귀 검사한다.

## 상태 전이

```text
registered
  → preprocessing            (sanitized child Order, 0층)
  → temporal_analysis        (canonical Wave + global module + full TMM)
  → scoring_queued → scoring (offline locked scorer)
  → completed | failed
```

`BenchmarkRun`은 source Order ID와 child Order ID, immutable manifest SHA-256, sanitized input hash, production contract, blind policy 및 score bundle path를 별도로 기록한다. 기존 Order의 status, report, RAG output, rerun configuration에는 쓰지 않는다.

## 현재 구현 범위와 다음 단계

현재 구현은 strict-primary run registration, sanitized snapshot, 0층 preprocessing dispatch, 1층 TMM orchestration, offline canonical scorer, Order Detail status/metric panel을 포함한다. score bundle은 JSON/TSV와 provenance를 생성한다.

다음 확장은 publication figure renderer, bootstrap/permutation confidence interval, branch/anchor heatmap, discovery calibration panel, inhibitor `2×2` perturbation run type이다. 이들은 strict-primary result와 별도 bundle로 추가해야 하며, baseline primary score 규칙을 변경해서는 안 된다.
