# PTM Analysis Platform — Configuration Guide

## 환경변수 파일 (.env)

프로젝트 루트의 `.env` 파일에서 전체 플랫폼 설정을 관리합니다.
`.env.example`을 복사하여 사용하세요.

```bash
cp .env.example .env
```

## 전체 환경변수 목록

### General

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `APP_ENV` | `development` | 실행 환경 (development / production) |
| `DEBUG` | `true` | 디버그 모드 (SQL 로깅 등 포함) |

### Authentication

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `AUTH_ENABLED` | `false` | `false`: 인증 비활성화 (내부용), `true`: JWT 인증 활성화 |
| `JWT_SECRET` | `dev-secret-change-me` | JWT 서명 키 (운영 시 반드시 변경) |
| `JWT_ALGORITHM` | `HS256` | JWT 알고리즘 |
| `JWT_EXPIRE_MINUTES` | `1440` | JWT 토큰 만료 시간 (분, 기본 24시간) |

> `AUTH_ENABLED=false`이면 모든 API 요청이 `InternalUser (admin)` 권한으로 처리됩니다.

### MySQL

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `MYSQL_ROOT_PASSWORD` | `ptm_root_password_change_me` | MySQL root 비밀번호 |
| `MYSQL_DATABASE` | `ptm_platform` | 데이터베이스 이름 |
| `MYSQL_USER` | `ptm_user` | 앱에서 사용할 MySQL 계정 |
| `MYSQL_PASSWORD` | `ptm_password_change_me` | MySQL 계정 비밀번호 |

> `DATABASE_URL`은 docker-compose.yml에서 위 변수들을 조합하여 자동 생성됩니다.

### Redis

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `REDIS_HOST` | `redis` | Redis 호스트 (Docker 내부) |
| `REDIS_PORT` | `6379` | Redis 포트 |

> Redis URL은 docker-compose.yml에서 서비스별로 DB 번호를 다르게 설정합니다.

### ChromaDB

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `CHROMADB_HOST` | `chromadb` | ChromaDB 호스트 |
| `CHROMADB_PORT` | `8000` | ChromaDB 포트 |

### LLM (Ollama)

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `OLLAMA_HOST` | `host.docker.internal` | Ollama 호스트 (Docker 컨테이너 → 호스트) |
| `OLLAMA_PORT` | `11434` | Ollama 포트 |
| `LLM_MODEL` | `qwen2.5:7b` | 기본 LLM 모델 |

### Cloud LLM (선택)

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `GEMINI_API_KEY` | (비어있음) | Google Gemini API 키 |
| `OPENAI_API_KEY` | (비어있음) | OpenAI API 키 |
| `ANTHROPIC_API_KEY` | (비어있음) | Anthropic API 키 |

> Cloud LLM 키가 설정되면 LLM Models 관리 페이지에서 해당 provider를 선택하여 사용 가능.

### External API Keys

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `NCBI_EMAIL` | `user@example.com` | NCBI E-utilities 필수 이메일 |
| `NCBI_API_KEY` | (비어있음) | NCBI API 키 (rate limit 완화, 선택) |
| `STRINGDB_API_KEY` | (비어있음) | STRING-DB API 키 (선택) |

### Cytoscape

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `CYTOSCAPE_PORT` | `1234` | Cytoscape Desktop REST API 포트 |

> Cytoscape는 호스트 머신에서 직접 실행. 미실행 시 텍스트 기반 fallback.

### Worker Concurrency

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `PREPROCESSING_CONCURRENCY` | `2` | Preprocessing 워커 동시 처리 수 |
| `RAG_ENRICHMENT_CONCURRENCY` | `3` | RAG Enrichment 워커 동시 처리 수 |
| `REPORT_GENERATION_CONCURRENCY` | `2` | Report Generation 워커 동시 처리 수 |

> 동시 처리 수를 높이면 여러 Order를 병렬 처리할 수 있지만 메모리 사용량이 증가합니다.

## 운영 환경 설정 체크리스트

```ini
# 1. 인증 활성화
AUTH_ENABLED=true
JWT_SECRET=<64자 이상 랜덤 문자열>

# 2. MySQL 비밀번호 변경
MYSQL_ROOT_PASSWORD=<강력한 비밀번호>
MYSQL_PASSWORD=<강력한 비밀번호>

# 3. 디버그 비활성화
APP_ENV=production
DEBUG=false

# 4. NCBI 이메일 설정 (필수)
NCBI_EMAIL=your-real-email@company.com

# 5. LLM 모델 (고품질)
LLM_MODEL=qwen2.5:32b
```

## 데이터 저장 경로

| 경로 (컨테이너) | 호스트 매핑 | 내용 |
|----------------|-----------|------|
| `/app/data/inputs` | `./data/inputs` | Order별 입력 파일 (pr, pg) |
| `/app/data/reference` | `./data/reference` | Species별 Reference FASTA |
| `/app/data/outputs` | `./data/outputs` | 분석 결과 (TSV, MD, JSON) |
| `/app/storage/reports` | `./storage/reports` | 최종 리포트 |
| `/app/storage/logs` | `./storage/logs` | 앱 로그 |
| `/var/lib/mysql` | `./storage/mysql` | MySQL 데이터 |
| `/data` | `./storage/redis` | Redis AOF 데이터 |
| `/chroma/chroma` | `./storage/chromadb` | ChromaDB 벡터 데이터 |
