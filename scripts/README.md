# PTM Platform - 배포 스크립트 사용법

## 스크립트 요약

| 스크립트 | 용도 |
|----------|------|
| `dev-deploy.sh` | 개발 중 수정 반영 (빌드 + 재시작, 버전 변경 없음) |
| `refresh-hash.sh` | push 후 hash만 갱신 (빌드 없음) |
| `deploy.sh` | 공식 배포 (버전 증가 + 빌드 + 재시작) |
| `up.sh` | 전체 서비스 기동 |

---

## 사용 시나리오

### 1. 개발 중 — 소스 수정 후 반영

```bash
./scripts/dev-deploy.sh
```

- 마지막 빌드 이후 **실제로 수정된** 컴포넌트만 빌드 & 재시작
- 버전 변경 없음
- 전체 빌드가 필요하면: `./scripts/dev-deploy.sh --all`

---

### 2. Commit & Push — hash만 갱신

```bash
git add .
git commit -m "메시지"
git push
./scripts/refresh-hash.sh
```

- push 후 웹에 표시되는 hash를 최신 커밋으로 갱신
- 빌드·재시작 없음
- 의미: "버전은 그대로, push된 커밋은 최신" 표시

---

### 3. 버전 올리기 — 공식 배포

```bash
git add .
git commit -m "메시지"
./scripts/deploy.sh
```

- 마지막 deploy 이후 **변경된** 컴포넌트에 맞춰 버전(AAA.BBB.CCC.DDD) 증가
- 해당 컴포넌트만 빌드 & 재시작
- 전체 배포: `./scripts/deploy.sh --all`

---

### 4. 서비스 기동

```bash
./scripts/up.sh
```

- VERSION 파일 기준으로 전체 서비스 기동

---

## 버전 형식

`Version : 1.1.1.1 (3fa4c71)`

- **1.1.1.1**: api-server, mcp-server, frontend, workers 순 (내부 저장: 001.001.001.001, 표시 시 앞의 0 생략)
- **(3fa4c71)**: 현재 표시 중인 git commit hash
- **이미지 태그**: 각 컴포넌트는 자기 버전만 사용 (예: ptm-frontend:001, ptm-api-server:001)

---

## Webhook (Order 이벤트)

`.env`에 `WEBHOOK_URL`을 설정하면 주문 상태 변경 시 해당 URL로 POST 요청을 보냅니다.
여러 URL은 쉼표로 구분 (예: `http://localhost:3000/hook,https://hooks.slack.com/...`).

**Step**: `preprocessing` | `rag_enrichment` | `report_generation`  
**Status**: `started` | `completed` | `failed` | `cancelled`

**Payload 예시**:
```json
{
  "order_id": 123,
  "order_code": "Universe_AF",
  "step": "preprocessing",
  "status": "completed",
  "error_message": null,
  "timestamp": "2025-02-21T12:00:00.000000+00:00"
}
```

**OpenClaw 포맷**: `[order_code] Step : Status`
