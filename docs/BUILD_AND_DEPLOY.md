# PTM Platform — 빌드 & 배포 가이드

## 1. 전체 명령어

```bash
# 전체 빌드 + 기동
docker compose build && docker compose up -d

# 전체 재시작 (빌드 없이)
docker compose restart

# 전체 중지
docker compose down
```

---

## 2. 서비스별 명령어

| 서비스 | 빌드 | 기동 | 재시작 |
|--------|------|------|--------|
| **api-server** | `docker compose build api-server` | `docker compose up -d api-server` | `docker compose restart api-server` |
| **mcp-server** | `docker compose build mcp-server` | `docker compose up -d mcp-server` | `docker compose restart mcp-server` |
| **frontend** | `docker compose build frontend` | `docker compose up -d frontend` | `docker compose restart frontend` |
| **celery-worker-preprocessing** | `docker compose build celery-worker-preprocessing` | `docker compose up -d celery-worker-preprocessing` | `docker compose restart celery-worker-preprocessing` |
| **celery-worker-rag** | `docker compose build celery-worker-rag` | `docker compose up -d celery-worker-rag` | `docker compose restart celery-worker-rag` |
| **celery-worker-report** | `docker compose build celery-worker-report` | `docker compose up -d celery-worker-report` | `docker compose restart celery-worker-report` |
| **production-tmm-worker** | API 이미지와 동일 Dockerfile. 태그 없으면 `ptm-api-server:$VERSION`에서 tag | `docker compose up -d production-tmm-worker` | `docker compose up -d production-tmm-worker` (실행 중 job을 끊지 않으려면 restart 금지) |
| **gateway** | (이미지 사용, 빌드 없음) | `docker compose up -d gateway` | `docker compose restart gateway` |
| **mysql** | (이미지 사용) | `docker compose up -d mysql` | `docker compose restart mysql` |
| **redis** | (이미지 사용) | `docker compose up -d redis` | `docker compose restart redis` |
| **chromadb** | (이미지 사용) | `docker compose up -d chromadb` | `docker compose restart chromadb` |

> **Workers**는 동일한 `./workers` 이미지를 사용하므로, 한 번 빌드하면 세 worker 모두 공유합니다:
> ```bash
> docker compose build celery-worker-preprocessing
> docker compose up -d celery-worker-preprocessing celery-worker-rag celery-worker-report
> ```

---

## 3. 수정 디렉터리별 빌드/재시작 가이드

### 빌드 필요 (이미지 재생성)

| 수정 경로 | 필요한 빌드 | 비고 |
|-----------|-------------|------|
| `frontend/**` | `docker compose build frontend` | React/Vite 빌드 결과가 이미지에 포함됨 |
| `api-server/pyproject.toml` | `docker compose build api-server` | 의존성 변경 시 |
| `api-server/Dockerfile` | `docker compose build api-server` | |
| `workers/pyproject.toml` 또는 `workers/requirements*.txt` | `docker compose build celery-worker-preprocessing` | 의존성 변경 시 |
| `workers/Dockerfile` | `docker compose build celery-worker-preprocessing` | |
| `mcp-server/**` (Dockerfile, 의존성) | `docker compose build mcp-server` | 의존성 변경 시 |

### 빌드 불필요 (재시작만)

아래 경로는 **볼륨 마운트**로 컨테이너에 반영되므로, **빌드 없이 재시작**만 하면 됩니다.

| 수정 경로 | 재시작할 서비스 |
|-----------|-----------------|
| `api-server/app/**` | `docker compose restart api-server` |
| `workers/**` (Python 코드) | `docker compose restart celery-worker-preprocessing celery-worker-rag celery-worker-report` |
| `mcp-server/app/**` | `docker compose restart mcp-server` |
| `gateway/nginx.conf` | `docker compose restart gateway` |
| `.env` | `docker compose up -d api-server celery-worker-rag celery-worker-report` (재생성 권장) |

---

## 4. 수정 경로별 — 복붙용 명령어

```bash
# frontend/ 수정 시
docker compose build frontend && docker compose up -d frontend

# api-server/app/ 수정 시 (빌드 없음)
docker compose restart api-server

# api-server/pyproject.toml 또는 Dockerfile 수정 시
docker compose build api-server && docker compose up -d api-server

# workers/ Python 코드 수정 시 (빌드 없음)
docker compose restart celery-worker-preprocessing celery-worker-rag celery-worker-report

# workers/ Dockerfile 또는 pyproject.toml 수정 시
docker compose build celery-worker-preprocessing && docker compose up -d celery-worker-preprocessing celery-worker-rag celery-worker-report

# mcp-server/app/ 수정 시 (빌드 없음)
docker compose restart mcp-server

# gateway/nginx.conf 수정 시
docker compose restart gateway

# .env 수정 시
docker compose up -d api-server celery-worker-rag celery-worker-report --force-recreate

# 전체 수정 후
docker compose build && docker compose up -d
```

> 실행 전 `cd ptm-platform` (또는 docker-compose.yml 있는 디렉터리)로 이동하세요.

---

## 5. production-tmm-worker 필수 (2026-09-21 선언)

RAG → Report 사이에 canonical temporal sidecar를 만드는 큐는 `production_tmm`이다.
이 워커가 없으면 RAG는 결과를 최대 6시간 기다리며 워치독이 Halted로 오인한다.
측정 상수가 아니다. TMM 점수·τ를 바꾸지 않는다.

| 이름 | 값 | 역할 |
|------|----|------|
| `CONSUMER_WAIT_SECONDS` | 30 | `production_tmm` consumer가 이 시간 동안 없으면 즉시 실패. enqueue 전에 검사하고, 대기 중 사라지면 같은 창으로 실패. |
| `HEARTBEAT_SECONDS` | 120 | TMM 대기 중 `order_logs`에 running 한 줄을 남긴다. `WATCHDOG_NO_PROGRESS_STALL_MINUTES`(60)보다 짧아야 한다. |
| `JOIN_TIMEOUT_SECONDS` | 21780 | 기존 join 상한. production TMM `time_limit`(21720)과 맞춤. |

배포 규칙:

- `./scripts/dev-deploy.sh`와 `./scripts/deploy.sh`는 소스 변경이 없어도 `docker compose up -d production-tmm-worker`를 실행한다.
- 이미 떠 있는 워커는 재시작하지 않는다. 실행 중 analysis job을 끊지 않기 위함이다.
- 이미지 `ptm-production-tmm-worker:$VERSION`이 없으면 같은 Dockerfile인 `ptm-api-server:$VERSION`을 tag한다.

### 5.1 TMM `parent_generation`과 Explorer DuckDB (2026-09-21)

`order_run_gen`은 preprocessing / RAG / Report 재실행마다 증가한다.
분석 입력 스냅샷의 `parent_generation`은 **전처리 publish 시점**이다.
TMM job은 스냅샷 값이 아니라 **submit 시점의 `order_run_gen`**을 `parent_generation`으로 기록한다.
그래야 RAG-only 재실행이 같은 input revision에서 즉시 `superseded` 되지 않는다.
이후 새 start가 `order_run_gen`을 다시 올리면 기존 TMM은 여전히 superseded다.

Explorer parquet는 jsonl을 **한 줄씩** observation으로 펼친 뒤 `COPY`한다.
`ORDER BY`와 `json_each` 전체 정렬은 작성 단계에서 쓰지 않는다. 페이지 조회가 `record_id`로 정렬한다.
records jsonl이 32MB(`EXPLORER_JSONL_CHUNK_BYTES`)를 넘으면 `explorer_records-part-*.parquet`로 나눈다.
부분 파일을 DuckDB로 다시 합치지 않는다. `record_json` VARCHAR 전체를 한 번에 올리면 512MB에서 OOM이다.
페이지 조회는 그 glob을 256MB로 읽는다. TMM NNLS·τ를 바꾸지 않는다.
