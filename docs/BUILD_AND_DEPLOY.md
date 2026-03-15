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
