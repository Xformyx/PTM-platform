# PTM Platform - 배포 스크립트 사용법

## 스크립트 요약

| 스크립트 | 용도 |
|----------|------|
| `dev-deploy.sh` | 개발 중 수정 반영 (빌드 + 재시작, **버전 변경 없음**) |
| `refresh-hash.sh` | push 후 hash만 갱신 (빌드 없음) |
| `deploy.sh` | 공식 배포 (필요 시 SemVer 증가 + 빌드 + 재시작) |
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

### 3. 버전 올리기 — 큰 변화가 있을 때만

플랫폼 버전은 **Major.Minor.Patch** (예: `2.1.1`)입니다.  
일상적인 수정은 버전을 올리지 말고, 의미 있는 릴리스일 때만 올립니다.

```bash
# 버전 유지한 채 변경분 배포
./scripts/deploy.sh

# SemVer 릴리스 (버전 변경 시 전체 이미지 재빌드)
./scripts/deploy.sh --bump patch    # 2.1.1 → 2.1.2  (버그픽스)
./scripts/deploy.sh --bump minor    # 2.1.1 → 2.2.0  (기능 추가)
./scripts/deploy.sh --bump major    # 2.1.1 → 3.0.0  (호환 깨지는 큰 변화)
./scripts/deploy.sh --set 2.1.1     # 정확한 버전으로 지정
```

---

### 4. 서비스 기동

```bash
./scripts/up.sh
```

- VERSION 파일 기준으로 전체 서비스 기동

---

## 버전 형식

`Version : 2.1.1 (3fa4c71)`

| 자리 | 의미 | 올릴 때 |
|------|------|---------|
| **Major** | 호환이 깨지거나 플랫폼 급 큰 변화 | `--bump major` |
| **Minor** | 기능 추가 (예: Co-Scientist 연동) | `--bump minor` |
| **Patch** | 버그픽스·작은 개선 | `--bump patch` |

- **이미지 태그**: 모든 컴포넌트가 동일 SemVer 사용 (예: `ptm-frontend:2.1.1`, `ptm-api-server:2.1.1`)
- **(3fa4c71)**: 현재 표시 중인 git commit hash
- `dev-deploy.sh`는 버전을 올리지 않습니다. 큰 변화가 있을 때만 `deploy.sh --bump/--set`을 사용하세요.

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

**메시지 포맷**: `[order_code] Step - Status` (한 줄)
