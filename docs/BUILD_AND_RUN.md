# PTM Platform - 빌드 및 서비스 실행 가이드

수정한 케이스별로 필요한 빌드와 서비스 Up 명령어입니다.

---

## 사전 준비

모든 명령어는 **프로젝트 루트**에서 실행합니다.

```bash
cd /Users/ken_studio/Documents/Work/PTM/ptm-platform
```

---

## 1. Frontend만 수정한 경우

React/TypeScript UI 변경 시. Frontend는 Docker 이미지 안에서 빌드되므로 **이미지 재빌드**가 필요합니다.

```bash
# Frontend 이미지 재빌드 및 컨테이너 재시작
docker compose up -d --build frontend

# Gateway가 frontend에 의존하므로, 변경사항 반영을 위해 Gateway도 재시작
docker compose restart gateway
```

또는 한 번에:

```bash
docker compose up -d --build frontend && docker compose restart gateway
```

---

## 2. API Server만 수정한 경우

`api-server/app/` Python 코드 변경 시. app 디렉터리가 volume으로 마운트되어 있어 보통 재시작만 하면 됩니다.

```bash
docker compose restart api-server
```

`api-server/pyproject.toml` 등 **의존성**을 변경한 경우에는 이미지 재빌드가 필요합니다.

```bash
docker compose up -d --build api-server
```

---

## 3. Workers만 수정한 경우

`workers/` (preprocessing, RAG, report) Python 코드 변경 시.

```bash
docker compose restart celery-worker-preprocessing celery-worker-rag celery-worker-report
```

`workers/`의 **의존성**(requirements 등) 변경 시:

```bash
docker compose up -d --build celery-worker-preprocessing celery-worker-rag celery-worker-report
```

---

## 4. MCP Server만 수정한 경우

`mcp-server/app/` Python 코드 변경 시.

```bash
docker compose restart mcp-server
```

의존성 변경 시:

```bash
docker compose up -d --build mcp-server
```

---

## 5. Gateway 설정만 수정한 경우

`gateway/nginx.conf` 또는 `gateway/ssl/` 변경 시.

```bash
docker compose restart gateway
```

---

## 6. 전체 처음부터 올리기

모든 서비스를 새로 빌드하고 기동합니다.

```bash
docker compose up -d --build
```

---

## 7. 이미지 재빌드 없이 서비스만 재시작

이미지는 그대로 두고 컨테이너만 재시작합니다.

```bash
docker compose restart
```

---

## 8. 로컬에서 Frontend만 개발 모드로 실행 (선택)

Docker 없이 로컬에서 Vite 개발 서버로 확인할 때.

```bash
cd frontend
npm install   # 최초 1회
npm run dev
```

`http://localhost:5173` 접속. API는 Docker의 api-server를 사용하려면 프록시 설정이 필요할 수 있습니다.

---

## 서비스 목록 참고

| 서비스 | 포트 | 설명 |
|--------|------|------|
| gateway | 80, 443 | Nginx (진입점) |
| api-server | 8000 (내부) | FastAPI |
| mcp-server | 8001 (내부) | MCP Server |
| mysql | 3306 | MySQL |
| redis | 6379 | Redis |
| chromadb | 8000 | ChromaDB |
| celery-worker-* | - | Celery workers |
| frontend | 80 (내부) | React 빌드 결과물 |

**접속 URL:** `http://localhost` 또는 `https://localhost`
