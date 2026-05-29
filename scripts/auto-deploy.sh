#!/usr/bin/env bash
# =============================================================================
# PTM Platform Auto-Deploy — Production Server (RTX 4000)
#
# - git fetch 로 새 commit 감지 (30분마다 Windows Task Scheduler 호출)
# - 분석 중인 오더 있으면 해당 사이클 스킵
# - git reset --hard origin/main 으로 CRLF 잔재 자동 해소
# - dev-deploy.sh 로 변경된 컴포넌트만 빌드 & 재시작
# - PTMQuant 변경 감지 시 docker image 재빌드
#
# 설치:
#   1. 이 파일을 4000 서버 ptm-platform/scripts/ 에 배치
#   2. REPO_DIR, PTMQUANT_DIR, DB_ROOT_PW 를 실제 값으로 수정
#   3. Windows Task Scheduler 등록 (아래 PowerShell 참고)
#
# Task Scheduler 등록 (관리자 PowerShell):
#   $action = New-ScheduledTaskAction `
#       -Execute "C:\Windows\System32\wsl.exe" `
#       -Argument "bash /mnt/c/Users/admin/ptm-platform/scripts/auto-deploy.sh"
#   $trigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 30) -Once -At "00:00"
#   $settings = New-ScheduledTaskSettingsSet -RunOnlyIfNetworkAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
#   Register-ScheduledTask -TaskName "PTM-AutoDeploy" -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest -Force
# =============================================================================

set -e

# ── 설정 (실제 환경에 맞게 수정) ──────────────────────────────────────────────
REPO_DIR="/mnt/c/Users/admin/ptm-platform"   # WSL 경로 (C:\Users\admin\ptm-platform)
PTMQUANT_DIR="/mnt/c/Users/admin/PTMQuant"   # WSL 경로 (C:\Users\admin\PTMQuant)
DB_ROOT_PW="ptm_root_pass_2026"              # .env 의 MYSQL_ROOT_PASSWORD
DB_NAME="ptm_platform"
REMOTE="origin"
BRANCH="main"
LOG_DIR="$REPO_DIR/logs"
LOG_FILE="$LOG_DIR/auto-deploy.log"
LOCK_FILE="/tmp/ptm-auto-deploy.lock"
MAX_LOG_LINES=2000                           # 로그 파일 최대 줄 수 (자동 순환)
# ─────────────────────────────────────────────────────────────────────────────

mkdir -p "$LOG_DIR"

_log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG_FILE"
}

# 로그 파일 크기 관리 (너무 커지면 뒷부분만 유지)
if [ -f "$LOG_FILE" ] && [ "$(wc -l < "$LOG_FILE")" -gt "$MAX_LOG_LINES" ]; then
    tail -n $((MAX_LOG_LINES / 2)) "$LOG_FILE" > "$LOG_FILE.tmp" && mv "$LOG_FILE.tmp" "$LOG_FILE"
fi

# ── 중복 실행 방지 ────────────────────────────────────────────────────────────
if [ -f "$LOCK_FILE" ]; then
    LOCK_AGE=$(( $(date +%s) - $(stat -c %Y "$LOCK_FILE" 2>/dev/null || echo 0) ))
    if [ "$LOCK_AGE" -lt 900 ]; then   # 15분 이내 lock이면 스킵
        _log "[SKIP] Already running (lock age: ${LOCK_AGE}s)"
        exit 0
    else
        _log "[WARN] Stale lock found (${LOCK_AGE}s), removing"
        rm -f "$LOCK_FILE"
    fi
fi
touch "$LOCK_FILE"
trap "rm -f $LOCK_FILE" EXIT

# ── repo 디렉토리 확인 ────────────────────────────────────────────────────────
if [ ! -d "$REPO_DIR/.git" ]; then
    _log "[ERROR] $REPO_DIR is not a git repository"
    exit 1
fi

cd "$REPO_DIR"

# ── git 설정 (CRLF 문제 방지) ─────────────────────────────────────────────────
git config core.autocrlf false 2>/dev/null || true

# ── 원격 변경 확인 ────────────────────────────────────────────────────────────
git fetch "$REMOTE" "$BRANCH" 2>> "$LOG_FILE"

LOCAL=$(git rev-parse HEAD)
REMOTE_SHA=$(git rev-parse "$REMOTE/$BRANCH")

if [ "$LOCAL" = "$REMOTE_SHA" ]; then
    _log "[OK] Up-to-date (${LOCAL:0:12})"
    exit 0
fi

_log "[UPDATE] ${LOCAL:0:12} → ${REMOTE_SHA:0:12}"

# ── 분석 중인 오더 확인 ───────────────────────────────────────────────────────
RUNNING=0
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "ptm-mysql"; then
    RUNNING=$(docker exec ptm-mysql mysql -u root -p"$DB_ROOT_PW" "$DB_NAME" \
        -se "SELECT COUNT(*) FROM orders WHERE status IN ('preprocessing','rag_enrichment','report_generation');" \
        2>/dev/null || echo "0")
    RUNNING=$(echo "$RUNNING" | tr -d '[:space:]')
fi

if [ "$RUNNING" -gt 0 ]; then
    _log "[DEFER] $RUNNING order(s) running — will retry next cycle"
    exit 0
fi

# ── PTMQuant 업데이트 확인 & 빌드 ────────────────────────────────────────────
PTMQUANT_UPDATED=0
if [ -d "$PTMQUANT_DIR/.git" ]; then
    cd "$PTMQUANT_DIR"
    git config core.autocrlf false 2>/dev/null || true
    git fetch "$REMOTE" "$BRANCH" 2>> "$LOG_FILE"
    PQ_LOCAL=$(git rev-parse HEAD)
    PQ_REMOTE=$(git rev-parse "$REMOTE/$BRANCH")
    if [ "$PQ_LOCAL" != "$PQ_REMOTE" ]; then
        _log "[PTMQUANT] Update detected: ${PQ_LOCAL:0:12} → ${PQ_REMOTE:0:12}"
        git reset --hard "$REMOTE/$BRANCH" >> "$LOG_FILE" 2>&1
        _log "[PTMQUANT] Building docker image..."
        docker build -t ptmquant:latest . >> "$LOG_FILE" 2>&1
        PTMQUANT_UPDATED=1
        _log "[PTMQUANT] Build complete"
    else
        _log "[PTMQUANT] Up-to-date (${PQ_LOCAL:0:12})"
    fi
    cd "$REPO_DIR"
else
    _log "[PTMQUANT] Skipped — $PTMQUANT_DIR not found"
fi

# ── ptm-platform Pull & Deploy ────────────────────────────────────────────────
_log "[DEPLOY] Applying ptm-platform changes..."

# CRLF 잔재까지 완전히 초기화
git reset --hard "$REMOTE/$BRANCH" >> "$LOG_FILE" 2>&1

# 변경된 컴포넌트만 빌드 & 재시작
if [ -x "$REPO_DIR/scripts/dev-deploy.sh" ]; then
    bash "$REPO_DIR/scripts/dev-deploy.sh" >> "$LOG_FILE" 2>&1
else
    _log "[WARN] dev-deploy.sh not found or not executable — running full deploy"
    docker compose build >> "$LOG_FILE" 2>&1
    docker compose up -d >> "$LOG_FILE" 2>&1
fi

_log "[DONE] Deployed ptm-platform to ${REMOTE_SHA:0:12}$([ $PTMQUANT_UPDATED -eq 1 ] && echo ', PTMQuant rebuilt' || echo '')"
