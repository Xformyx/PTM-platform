#!/usr/bin/env bash
# PTM Platform - Dev Deploy (변경된 것만 빌드 & 재시작, 버전 변경 없음)
#
# Telegram Agent / 외부 호출은 이 명령 하나만 쓰면 된다.
# 마운트된 Python은 이미지 빌드 없이 해당 프로세스만 재시작하고,
# 이미지에 구워지는 입력(frontend, Dockerfile, pyproject)만 빌드한다.
#
# Usage:
#   ./scripts/dev-deploy.sh
#   ./scripts/dev-deploy.sh --all
#   ./scripts/dev-deploy.sh --dry-run
#   ./scripts/dev-deploy.sh --classify path [path...]

set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# COMPOSE_GPU from .env: true | false | auto (default auto = Docker NVIDIA runtime 감지)
if [[ -f "$REPO_ROOT/.env" ]]; then
  _cg=$(grep -E '^COMPOSE_GPU=' "$REPO_ROOT/.env" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d ' "\r' || true)
  [[ -n "$_cg" ]] && COMPOSE_GPU="$_cg"
fi

# GPU compose overlay: Mac(Apple Silicon) 등 NVIDIA 없는 환경에서는 사용하지 않음
_use_gpu_compose() {
  local mode="${COMPOSE_GPU:-auto}"
  mode=$(echo "$mode" | tr '[:upper:]' '[:lower:]')
  case "$mode" in
    1|true|yes|on) return 0 ;;
    0|false|no|off) return 1 ;;
    auto)
      docker info 2>/dev/null | grep -qi nvidia && return 0
      return 1
      ;;
    *) return 1 ;;
  esac
}

VERSION_FILE="$REPO_ROOT/VERSION"
LAST_DEV_BUILD="$REPO_ROOT/.last-dev-build"
LAST_DEV_COMMIT="$REPO_ROOT/.last-dev-build-commit"

# compose / .env 변경 시 컨테이너를 다시 만들어줄 앱 스택 (이미지 빌드는 별도 플래그)
APP_STACK_SERVICES=(
  api-server
  mcp-server
  frontend
  celery-worker-preprocessing
  celery-worker-rag
  celery-worker-report
  benchmark-tmm-runner
  benchmark-runner
  gateway
)

WORKER_SERVICES=(
  celery-worker-preprocessing
  celery-worker-rag
  celery-worker-report
)

# 제외할 경로 (node_modules, __pycache__ 등은 소스 변경 아님)
FIND_EXCLUDE=(
  -not -path "*/node_modules/*"
  -not -path "*/__pycache__/*"
  -not -path "*/.git/*"
  -not -path "*/dist/*"
  -not -path "*/build/*"
  -not -path "*/.next/*"
  -not -path "*/.venv/*"
  -not -path "*/venv/*"
  -not -name "*.pyc"
)

# 경로 → 배포 단위. 테스트/문서만 바뀌면 skip.
# bash 3.2 호환 — local -n 미사용.
_component_for_path() {
  local f="$1"
  f="${f#./}"
  [[ -z "$f" ]] && return 0
  case "$f" in
    workers/tests/*|workers/scripts/*|api-server/tests/*|ptm_shared/tests/*|frontend/e2e/*)
      echo "skip" ;;
    *.md|docs/*)
      echo "skip" ;;
    workers/Dockerfile|workers/pyproject.toml|workers/requirements*.txt)
      echo "workers-image" ;;
    workers/report_generation/*|workers/pptx_generation/*)
      echo "worker-report" ;;
    workers/preprocessing/*)
      echo "worker-preprocessing" ;;
    workers/rag_enrichment/*)
      echo "worker-rag" ;;
    workers/common/*|workers/celery_app.py|workers/*)
      echo "workers-shared" ;;
    ptm_shared/*)
      echo "ptm-shared" ;;
    api-server/Dockerfile|api-server/pyproject.toml|api-server/entrypoint.sh)
      echo "api-server" ;;
    api-server/*)
      echo "api-server" ;;
    mcp-server/*)
      echo "mcp-server" ;;
    frontend/*)
      echo "frontend" ;;
    benchmarking/Dockerfile)
      echo "benchmarking" ;;
    benchmarking/*)
      echo "benchmarking" ;;
    gateway/*)
      echo "gateway" ;;
    docker-compose.yml|docker-compose.override.yml|docker-compose.gpu.yml)
      echo "compose-file" ;;
    .env)
      echo "dotenv" ;;
    *)
      echo "skip" ;;
  esac
}

_is_worker_component() {
  case "$1" in
    worker-report|worker-preprocessing|worker-rag|workers-shared|workers-image|workers) return 0 ;;
    *) return 1 ;;
  esac
}

# git: 마지막 dev-deploy 커밋 이후 + 워킹트리/스테이징 변경
get_changed_components_git() {
  local result=()
  local old_commit=""
  local diff_files=""

  if [[ -f "$LAST_DEV_COMMIT" ]]; then
    old_commit=$(tr -d ' \n\r' < "$LAST_DEV_COMMIT")
  elif [[ -f "$REPO_ROOT/GIT_HASH" ]]; then
    # 이전 dev-deploy 스크립트는 커밋 파일이 없었음 — GIT_HASH로 한 번 추정
    local short_hash
    short_hash=$(tr -d ' \n\r' < "$REPO_ROOT/GIT_HASH")
    old_commit=$(git rev-parse "$short_hash" 2>/dev/null || true)
    [[ -n "$old_commit" ]] && echo "  (no .last-dev-build-commit; diff since GIT_HASH $short_hash)" >&2
  fi

  if [[ -n "$old_commit" ]]; then
    diff_files=$(git diff --name-only "$old_commit" HEAD 2>/dev/null || true)
  fi
  diff_files+=$'\n'$(git diff --name-only HEAD 2>/dev/null || true)
  diff_files+=$'\n'$(git diff --name-only --cached HEAD 2>/dev/null || true)

  while IFS= read -r f; do
    local c
    c=$(_component_for_path "$f")
    [[ -n "$c" && "$c" != "skip" ]] && result+=("$c")
  done <<< "$diff_files"

  printf '%s\n' "${result[@]}" | sort -u
}

# mtime: 마지막 dev-deploy 이후 디스크에서 수정된 파일 (로컬 편집용)
# Windows에서 git pull 후 mtime이 안 바뀌는 경우가 있어 git 감지와 병행
get_changed_components_mtime() {
  local result=()
  local marker="$LAST_DEV_BUILD"
  local dir rel c

  for dir in api-server mcp-server frontend workers benchmarking gateway ptm_shared; do
    [[ ! -d "$REPO_ROOT/$dir" ]] && continue
    if [[ ! -f "$marker" ]]; then
      case "$dir" in
        workers) result+=("workers-shared") ;;
        ptm_shared) result+=("ptm-shared") ;;
        *) result+=("$dir") ;;
      esac
      continue
    fi
    while IFS= read -r rel; do
      [[ -z "$rel" ]] && continue
      c=$(_component_for_path "$rel")
      [[ -n "$c" && "$c" != "skip" ]] && result+=("$c")
    done < <(find "$REPO_ROOT/$dir" -type f -newer "$marker" "${FIND_EXCLUDE[@]}" 2>/dev/null | sed "s|^$REPO_ROOT/||")
  done

  if [[ -f "$marker" ]]; then
    local root_files=(docker-compose.yml docker-compose.gpu.yml .env)
    [[ -f "$REPO_ROOT/docker-compose.override.yml" ]] && root_files+=(docker-compose.override.yml)
    local f
    for f in "${root_files[@]}"; do
      [[ -f "$REPO_ROOT/$f" ]] || continue
      if [[ "$REPO_ROOT/$f" -nt "$marker" ]]; then
        if [[ "$f" == ".env" ]]; then
          result+=("dotenv")
        else
          result+=("compose-file")
        fi
      fi
    done
  fi

  printf '%s\n' "${result[@]}" | sort -u
}

get_changed_components() {
  local git_changed mtime_changed
  git_changed=$(get_changed_components_git)
  mtime_changed=$(get_changed_components_mtime)

  if [[ -z "$git_changed" && -z "$mtime_changed" ]]; then
    return
  fi
  printf '%s\n' $git_changed $mtime_changed | sort -u
}

# Image layers change only for Dockerfiles and install specs. Bind-mounted
# Python (api-server/app, workers/, ptm_shared) is picked up by restart.
_image_input_changed() {
  local component="$1"
  local paths=()
  case "$component" in
    api-server) paths=(api-server/Dockerfile api-server/pyproject.toml api-server/entrypoint.sh) ;;
    worker-report|worker-preprocessing|worker-rag|workers-shared|workers-image|workers)
      paths=(workers/Dockerfile workers/pyproject.toml) ;;
    mcp-server) paths=(mcp-server/Dockerfile mcp-server/pyproject.toml) ;;
    frontend) return 0 ;;
    benchmarking) paths=(benchmarking/Dockerfile workers/pyproject.toml) ;;
    compose-file) return 0 ;;
    ptm-shared|gateway|dotenv) return 1 ;;
    *) return 1 ;;
  esac
  local marker="$LAST_DEV_BUILD"
  local old_commit=""
  [[ -f "$LAST_DEV_COMMIT" ]] && old_commit=$(tr -d ' \n\r' < "$LAST_DEV_COMMIT")
  local p
  for p in "${paths[@]}"; do
    [[ -f "$REPO_ROOT/$p" ]] || continue
    if [[ -n "$old_commit" ]] && git diff --name-only "$old_commit" HEAD -- "$p" 2>/dev/null | grep -q .; then
      return 0
    fi
    if git diff --name-only HEAD -- "$p" 2>/dev/null | grep -q .; then
      return 0
    fi
    if git diff --name-only --cached HEAD -- "$p" 2>/dev/null | grep -q .; then
      return 0
    fi
    if [[ -f "$marker" && "$REPO_ROOT/$p" -nt "$marker" ]]; then
      return 0
    fi
  done
  return 1
}

_build_services_for() {
  local component="$1"
  case "$component" in
    api-server)    echo "api-server benchmark-tmm-runner" ;;
    mcp-server)    echo "mcp-server" ;;
    frontend)      echo "frontend" ;;
    workers-image|workers) echo "celery-worker-preprocessing" ;;
    worker-report|worker-preprocessing|worker-rag|workers-shared)
      ;;
    benchmarking)  echo "benchmark-runner" ;;
    compose-file)  echo "api-server mcp-server frontend celery-worker-preprocessing benchmark-runner" ;;
  esac
}

_restart_services_for() {
  local component="$1"
  case "$component" in
    api-server)            echo "api-server benchmark-tmm-runner" ;;
    mcp-server)            echo "mcp-server" ;;
    frontend)              echo "frontend" ;;
    worker-report)         echo "celery-worker-report" ;;
    worker-preprocessing)  echo "celery-worker-preprocessing" ;;
    worker-rag)            echo "celery-worker-rag" ;;
    workers-shared|workers-image|workers)
      echo "${WORKER_SERVICES[*]}" ;;
    ptm-shared)
      echo "api-server ${WORKER_SERVICES[*]} benchmark-tmm-runner" ;;
    benchmarking)          echo "benchmark-runner" ;;
    gateway)               echo "gateway" ;;
    dotenv|compose-file)   echo "${APP_STACK_SERVICES[*]}" ;;
  esac
}

# Main
FORCE_ALL=false
DRY_RUN=false
CLASSIFY_ONLY=false
CLASSIFY_PATHS=()
for arg in "$@"; do
  case "$arg" in
    --all) FORCE_ALL=true ;;
    --dry-run) DRY_RUN=true ;;
    --classify) CLASSIFY_ONLY=true ;;
    --help|-h)
      cat <<'EOF'
Usage: ./scripts/dev-deploy.sh [--all] [--dry-run] [--classify path...]

Bind-mounted Python (workers, ptm_shared, api-server/app) is restarted
without an image rebuild. Frontend and Dockerfile/pyproject changes build.

Worker trees restart only their queue:
  workers/report_generation/**  -> celery-worker-report
  workers/preprocessing/**      -> celery-worker-preprocessing
  workers/rag_enrichment/**     -> celery-worker-rag
  workers/common/**             -> all three report/rag/preprocessing workers
  ptm_shared/**                 -> API + the three workers + benchmark-tmm
EOF
      exit 0
      ;;
    *)
      if $CLASSIFY_ONLY; then
        CLASSIFY_PATHS+=("$arg")
      else
        echo "Unknown argument: $arg" >&2
        exit 1
      fi
      ;;
  esac
done

if $CLASSIFY_ONLY; then
  if [[ ${#CLASSIFY_PATHS[@]} -eq 0 ]]; then
    echo "Usage: ./scripts/dev-deploy.sh --classify path [path...]" >&2
    exit 1
  fi
  for p in "${CLASSIFY_PATHS[@]}"; do
    printf '%s\t%s\n' "$p" "$(_component_for_path "$p")"
  done
  exit 0
fi

echo "=== PTM Platform Dev Deploy (버전 변경 없음) ==="
$DRY_RUN && echo "Mode: dry-run (no build, restart, or marker update)"

# 변경된 컴포넌트
if $FORCE_ALL; then
  # 이미지 4종 전체 빌드 + 게이트웨이까지 스택 재기동
  CHANGED=("api-server" "mcp-server" "frontend" "workers" "gateway")
  echo "Building all (--all)"
else
  CHANGED=($(get_changed_components))
  if [[ ${#CHANGED[@]} -eq 0 ]]; then
    echo "변경 없음 (git/mtime). git pull 직후라면: ./scripts/dev-deploy.sh --all"
    if [[ -f "$LAST_DEV_COMMIT" ]]; then
      echo "  Last dev-deploy commit: $(cat "$LAST_DEV_COMMIT")"
    fi
    echo "  Current HEAD: $(git rev-parse --short HEAD 2>/dev/null || echo '?')"
    exit 0
  fi
  echo "Changed: ${CHANGED[*]}"
  if [[ -f "$LAST_DEV_COMMIT" ]]; then
    echo "  Since commit: $(cat "$LAST_DEV_COMMIT" | tr -d ' \n\r' | cut -c1-12)"
  fi
  echo "  Current HEAD: $(git rev-parse --short HEAD 2>/dev/null || echo '?')"
fi

# VERSION 파일에서 플랫폼 SemVer 읽기 (올리지 않음). 모든 이미지가 동일 태그 사용.
_v=$(cat "$VERSION_FILE" 2>/dev/null | tr -d ' \n\r' || echo "0.0.0")
IFS='.' read -r _major _minor _patch _ <<< "$_v"
_major=$(printf "%d" $((10#${_major//[^0-9]/:-0})))
_minor=$(printf "%d" $((10#${_minor//[^0-9]/:-0})))
_patch=$(printf "%d" $((10#${_patch//[^0-9]/:-0})))
_v="${_major}.${_minor}.${_patch}"
export VERSION="$_v"
export VERSION_API="$_v"
export VERSION_MCP="$_v"
export VERSION_FRONTEND="$_v"
export VERSION_WORKERS="$_v"

# GIT_HASH / GIT_DATE 를 빌드 전에 미리 기록 (docker bind mount가 파일을 필요로 함)
if ! $DRY_RUN; then
  git rev-parse --short HEAD > "$REPO_ROOT/GIT_HASH" 2>/dev/null || true
  python3 "$REPO_ROOT/scripts/write-deploy-event.py" --repo-root "$REPO_ROOT" --stamp-only >/dev/null 2>&1 || true
fi

# Build
BUILD_SERVICES=()
for c in "${CHANGED[@]}"; do
  if ! $FORCE_ALL && ! _image_input_changed "$c"; then
    echo "Build skip $c (bind-mounted source; restart is enough)"
    continue
  fi
  # shellcheck disable=SC2206
  BUILD_SERVICES+=($(_build_services_for "$c"))
done
BUILD_SERVICES=($(printf '%s\n' "${BUILD_SERVICES[@]}" | awk 'NF && !seen[$0]++'))

COMPOSE_CMD=(docker compose)
if [[ -f "$REPO_ROOT/docker-compose.gpu.yml" ]] && _use_gpu_compose; then
  COMPOSE_CMD+=(--file docker-compose.yml --file docker-compose.gpu.yml)
  echo "Compose: GPU overlay (NVIDIA)"
elif [[ -f "$REPO_ROOT/docker-compose.gpu.yml" ]]; then
  echo "Compose: base only (no NVIDIA — set COMPOSE_GPU=true on GPU servers)"
fi

if [[ ${#BUILD_SERVICES[@]} -eq 0 ]]; then
  echo "Build: (skip — no image rebuild needed)"
else
  echo "Building: ${BUILD_SERVICES[*]}"
  if ! $DRY_RUN; then
    "${COMPOSE_CMD[@]}" build "${BUILD_SERVICES[@]}"
  fi
fi

# Restart
RESTART_SERVICES=()
for c in "${CHANGED[@]}"; do
  # shellcheck disable=SC2206
  RESTART_SERVICES+=($(_restart_services_for "$c"))
done
RESTART_SERVICES=($(printf '%s\n' "${RESTART_SERVICES[@]}" | awk 'NF && !seen[$0]++'))

if [[ ${#RESTART_SERVICES[@]} -eq 0 ]]; then
  echo "Warning: nothing to restart."
else
  echo "Restarting: ${RESTART_SERVICES[*]}"
  if ! $DRY_RUN; then
    "${COMPOSE_CMD[@]}" up -d "${RESTART_SERVICES[@]}"
  fi
fi

if $DRY_RUN; then
  echo "Dry-run complete. (Version: $_v)"
  exit 0
fi

touch "$LAST_DEV_BUILD"
git rev-parse HEAD > "$LAST_DEV_COMMIT" 2>/dev/null || true
git rev-parse --short HEAD > "$REPO_ROOT/GIT_HASH" 2>/dev/null || true
# 배포가 끝난 지금 시각을 기록한다. 커밋 시각이 아님.
python3 "$REPO_ROOT/scripts/write-deploy-event.py" \
  --repo-root "$REPO_ROOT" \
  --kind "dev-deploy" \
  --version "$_v" \
  --commit "$(cat "$REPO_ROOT/GIT_HASH")" \
  --built "${BUILD_SERVICES[*]}" \
  --restarted "${RESTART_SERVICES[*]}" \
  2>/dev/null || true
echo "Done. (Version: $_v, Hash: $(cat "$REPO_ROOT/GIT_HASH"), Date: $(cat "$REPO_ROOT/GIT_DATE"))"
