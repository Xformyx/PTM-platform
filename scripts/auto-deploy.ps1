# =============================================================================
# PTM Platform Auto-Deploy (PowerShell) — Production Server (RTX 4000)
#
# - Windows git 으로 fetch/reset (SSH 키 문제 없음)
# - 분석 중인 오더 있으면 스킵
# - WSL bash 로 dev-deploy.sh 호출
#
# Task Scheduler 등록 (관리자 PowerShell):
#   $action = New-ScheduledTaskAction `
#       -Execute "powershell.exe" `
#       -Argument "-NonInteractive -ExecutionPolicy Bypass -File C:\Users\admin\ptm-platform\scripts\auto-deploy.ps1"
#   $trigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 30) -Once -At (Get-Date)
#   $settings = New-ScheduledTaskSettingsSet -RunOnlyIfNetworkAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
#   Register-ScheduledTask -TaskName "PTM-AutoDeploy" -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest -Force
# =============================================================================

$REPO_DIR  = "C:\Users\admin\ptm-platform"
$DB_ROOT_PW = "ptm_root_pass_2026"
$DB_NAME   = "ptm_platform"
$BRANCH    = "main"
$LOG_FILE  = "$REPO_DIR\logs\auto-deploy.log"
$LOCK_FILE = "$env:TEMP\ptm-auto-deploy.lock"

# ── 로그 디렉토리 ─────────────────────────────────────────────────────────────
New-Item -ItemType Directory -Force -Path "$REPO_DIR\logs" | Out-Null

function Write-Log {
    param([string]$msg)
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg"
    Write-Host $line
    Add-Content -Path $LOG_FILE -Value $line -Encoding UTF8
}

# 로그 크기 관리 (2000줄 초과 시 절반 유지)
if (Test-Path $LOG_FILE) {
    $lines = Get-Content $LOG_FILE
    if ($lines.Count -gt 2000) {
        $lines | Select-Object -Last 1000 | Set-Content $LOG_FILE -Encoding UTF8
    }
}

# ── 중복 실행 방지 ────────────────────────────────────────────────────────────
if (Test-Path $LOCK_FILE) {
    $age = (Get-Date) - (Get-Item $LOCK_FILE).LastWriteTime
    if ($age.TotalSeconds -lt 900) {
        Write-Log "[SKIP] Already running (lock age: $([int]$age.TotalSeconds)s)"
        exit 0
    }
    Write-Log "[WARN] Stale lock ($([int]$age.TotalSeconds)s), removing"
    Remove-Item $LOCK_FILE -Force
}
"lock" | Set-Content $LOCK_FILE -Encoding UTF8

try {
    # ── repo 확인 ─────────────────────────────────────────────────────────────
    if (-not (Test-Path "$REPO_DIR\.git")) {
        Write-Log "[ERROR] $REPO_DIR is not a git repository"
        exit 1
    }

    Set-Location $REPO_DIR

    # ── git fetch ─────────────────────────────────────────────────────────────
    git fetch origin $BRANCH 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Log "[ERROR] git fetch failed"
        exit 1
    }

    $local  = git rev-parse HEAD
    $remote = git rev-parse "origin/$BRANCH"

    if ($local -eq $remote) {
        Write-Log "[OK] Up-to-date ($($local.Substring(0,12)))"
        exit 0
    }

    Write-Log "[UPDATE] $($local.Substring(0,12)) → $($remote.Substring(0,12))"

    # ── 분석 중인 오더 확인 ───────────────────────────────────────────────────
    $running = 0
    $containers = docker ps --format "{{.Names}}" 2>$null
    if ($containers -match "ptm-mysql") {
        $result = docker exec ptm-mysql mysql -u root -p"$DB_ROOT_PW" $DB_NAME `
            -se "SELECT COUNT(*) FROM orders WHERE status IN ('preprocessing','rag_enrichment','report_generation');" 2>$null
        if ($result -match '^\d+$') { $running = [int]$result }
    }

    if ($running -gt 0) {
        Write-Log "[DEFER] $running order(s) running — will retry next cycle"
        exit 0
    }

    # ── Pull ──────────────────────────────────────────────────────────────────
    Write-Log "[DEPLOY] Applying changes..."
    git reset --hard "origin/$BRANCH" | Out-Null

    # ── PTMQuant 업데이트 확인 ────────────────────────────────────────────────
    $PTMQUANT_DIR = "C:\Users\admin\PTMQuant"
    if (Test-Path "$PTMQUANT_DIR\.git") {
        Set-Location $PTMQUANT_DIR
        git fetch origin $BRANCH 2>&1 | Out-Null
        $pqLocal  = git rev-parse HEAD
        $pqRemote = git rev-parse "origin/$BRANCH"
        if ($pqLocal -ne $pqRemote) {
            Write-Log "[PTMQUANT] Update: $($pqLocal.Substring(0,12)) → $($pqRemote.Substring(0,12))"
            git reset --hard "origin/$BRANCH" | Out-Null
            Write-Log "[PTMQUANT] Building docker image..."
            docker build -t ptmquant:latest . 2>&1 | Out-Null
            Write-Log "[PTMQUANT] Build complete"
        } else {
            Write-Log "[PTMQUANT] Up-to-date ($($pqLocal.Substring(0,12)))"
        }
        Set-Location $REPO_DIR
    } else {
        Write-Log "[PTMQUANT] Skipped — $PTMQUANT_DIR not found"
    }

    # ── dev-deploy.sh (WSL) ───────────────────────────────────────────────────
    Write-Log "[DEPLOY] Running dev-deploy.sh via WSL..."
    wsl bash /mnt/c/Users/admin/ptm-platform/scripts/dev-deploy.sh 2>&1 | ForEach-Object {
        Add-Content -Path $LOG_FILE -Value $_ -Encoding UTF8
    }

    Write-Log "[DONE] Deployed to $($remote.Substring(0,12))"

} finally {
    Remove-Item $LOCK_FILE -Force -ErrorAction SilentlyContinue
}
