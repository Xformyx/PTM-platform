# PTM Analysis Platform — Build & Run Guide

## 사전 요구사항

| 항목 | 최소 버전 | 비고 |
|------|----------|------|
| Docker Desktop | 4.x+ | Compose V2 포함 |
| Ollama | 0.3+ | 호스트 머신에 직접 설치 |
| Node.js | 20+ | 프론트엔드 로컬 개발 시에만 |
| Python | 3.11+ | 워커 로컬 디버깅 시에만 |

## 빠른 시작 (전체 플랫폼)

```bash
cd ptm-platform

# 1. 환경 설정
cp .env.example .env
# .env 편집: 비밀번호, API 키 등 수정

# 2. 전체 빌드
docker compose build

# 3. 전체 기동
docker compose up -d

# 4. 상태 확인
docker compose ps

# 5. 헬스체크
curl http://localhost/api/health/detailed
```

## 개별 서비스 빌드

```bash
# 프론트엔드만
docker compose build frontend

# API 서버만
docker compose build api-server

# MCP 서버만
docker compose build mcp-server

# 워커 전체 (3개 워커가 같은 이미지 공유)
docker compose build celery-worker-preprocessing celery-worker-rag celery-worker-report
```

## 개별 서비스 재시작

```bash
# 코드 변경 후 재시작 (volume mount로 코드 반영됨)
docker compose restart api-server
docker compose restart mcp-server
docker compose restart celery-worker-preprocessing celery-worker-rag celery-worker-report

# 이미지 재빌드가 필요한 경우 (의존성 변경 등)
docker compose up -d --build api-server
```

## Volume Mount 구조 (개발 모드)

개발 편의를 위해 소스 코드가 volume mount로 연결되어 있어서
**코드 수정 → `docker compose restart` 만으로 반영 가능** (재빌드 불필요).

| 서비스 | Volume Mount | 용도 |
|--------|-------------|------|
| api-server | `./api-server/app:/app/app` | API 소스 코드 |
| mcp-server | `./mcp-server/app:/app/app` | MCP 소스 코드 |
| workers (x3) | `./workers:/app` | 워커 전체 소스 |

> **주의**: `pyproject.toml`의 dependencies가 변경되면 이미지 재빌드(`docker compose build`)가 필요합니다.

## 로그 확인

```bash
# 특정 서비스 로그
docker logs ptm-api-server
docker logs ptm-worker-preprocessing
docker logs ptm-worker-rag
docker logs ptm-worker-report
docker logs ptm-mcp-server
docker logs ptm-gateway

# 실시간 로그 (follow)
docker logs -f ptm-worker-preprocessing

# 전체 서비스 로그 (최근 100줄)
docker compose logs --tail=100

# 특정 서비스만
docker compose logs -f celery-worker-preprocessing
```

## 서비스 중지

```bash
# 전체 중지 (데이터 유지)
docker compose down

# 전체 중지 + 볼륨 삭제 (데이터 초기화)
docker compose down -v
```

## Ollama 설정

Ollama는 호스트 머신에 직접 설치하고 실행해야 합니다.

```bash
# 설치 (macOS)
brew install ollama

# 서비스 시작
ollama serve

# 모델 다운로드
ollama pull qwen2.5:7b
ollama pull qwen2.5:32b    # 더 높은 품질이 필요한 경우

# 사용 가능한 모델 확인
ollama list
```

Docker 컨테이너에서 호스트의 Ollama에 접근하는 주소: `http://host.docker.internal:11434`

## Cytoscape 설정 (선택)

네트워크 시각화를 위해 Cytoscape Desktop을 호스트에 설치합니다.

1. [Cytoscape 다운로드](https://cytoscape.org/download.html) 후 설치
2. Cytoscape 실행 (기본 포트: 1234)
3. Docker 컨테이너에서 `host.docker.internal:1234`로 접근
4. Cytoscape 미실행 시에는 텍스트 기반 fallback 사용

## 프론트엔드 로컬 개발

```bash
cd frontend
npm install
npm run dev     # http://localhost:5173 (Vite dev server)
                # API 요청은 localhost:8000으로 프록시됨
```

## 유용한 명령어

```bash
# 전체 이미지 확인
docker images | grep ptm-platform

# 컨테이너 리소스 사용량
docker stats --no-stream

# MySQL 접속
docker exec -it ptm-mysql mysql -u ptm_user -p ptm_platform

# Redis CLI
docker exec -it ptm-redis redis-cli

# Celery 워커 상태 확인
docker exec ptm-worker-preprocessing celery -A celery_app inspect active
docker exec ptm-worker-preprocessing celery -A celery_app inspect reserved
```

## 외부 접속 (Cloudflare Tunnel)

`ptm.xformyx.com`은 Cloudflare Tunnel을 통해 `localhost:80`에 연결되어 있습니다.

```bash
# 터널 상태 확인
ps aux | grep cloudflared

# 터널 설정 변경
# → Cloudflare Zero Trust Dashboard
# → Networks > Tunnels > 해당 터널 > Public Hostname
```

터널은 시스템 부팅 시 자동 실행됩니다 (launchd 등록).
