#!/usr/bin/env bash
# PTM Platform - Dev Deploy (변경된 것만 빌드 & 재시작, 버전 변경 없음)
# - git pull / commit: 마지막 dev-deploy 커밋 대비 git diff
# - 로컬 편집: 마지막 dev-deploy 이후 파일 mtime (uncommitted)
# - 감지 범위: api-server, mcp-server, frontend, workers, gateway, docker-compose*.yml, .env
# Usage: ./scripts/dev-deploy.sh [--all]

set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

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
  gateway
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

# 경로 → 컴포넌트 이름
_add_component_for_path() {
  local f="$1"
  local -n _out=$2
  [[ -z "$f" ]] && return
  case "$f" in
    api-server/*)     _out+=("api-server") ;;
    mcp-server/*)     _out+=("mcp-server") ;;
    frontend/*)       _out+=("frontend") ;;
    workers/*)        _out+=("workers") ;;
    gateway/*)        _out+=("gateway") ;;
    docker-compose.yml|docker-compose.override.yml|docker-compose.gpu.yml)
      _out+=("compose-file") ;;
    .env)             _out+=("dotenv") ;;
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
    _add_component_for_path "$f" result
  done <<< "$diff_files"

  printf '%s\n' "${result[@]}" | sort -u
}

# mtime: 마지막 dev-deploy 이후 디스크에서 수정된 파일 (로컬 편집용)
# Windows에서 git pull 후 mtime이 안 바뀌는 경우가 있어 git 감지와 병행
get_changed_components_mtime() {
  local result=()
  local marker="$LAST_DEV_BUILD"

  for dir in api-server mcp-server frontend workers gateway; do
    [[ ! -d "$REPO_ROOT/$dir" ]] && continue
    if [[ ! -f "$marker" ]]; then
      result+=("$dir")
    else
      if find "$REPO_ROOT/$dir" -type f -newer "$marker" "${FIND_EXCLUDE[@]}" 2>/dev/null | grep -q .; then
        result+=("$dir")
      fi
    fi
  done

  if [[ -f "$marker" ]]; then
    local root_files=(docker-compose.yml docker-compose.gpu.yml .env)
    [[ -f "$REPO_ROOT/docker-compose.override.yml" ]] && root_files+=(docker-compose.override.yml)
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

# Main
FORCE_ALL=false
for arg in "$@"; do
  [[ "$arg" == "--all" ]] && FORCE_ALL=true
done

echo "=== PTM Platform Dev Deploy (버전 변경 없음) ==="

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

# VERSION 파일에서 현재 버전 읽기 (올리지 않음), per-component로 export
_v=$(cat "$VERSION_FILE" 2>/dev/null | tr -d ' \n\r' || echo "001.001.001.001")
IFS='.' read -r _a _b _c _d _ <<< "$_v"
_a=$(printf "%03d" $((10#${_a//[^0-9]/:-0})))
_b=$(printf "%03d" $((10#${_b//[^0-9]/:-0})))
_c=$(printf "%03d" $((10#${_c//[^0-9]/:-0})))
_d=$(printf "%03d" $((10#${_d//[^0-9]/:-0})))
export VERSION_API="$_a"
export VERSION_MCP="$_b"
export VERSION_FRONTEND="$_c"
export VERSION_WORKERS="$_d"

# GIT_HASH / GIT_DATE 를 빌드 전에 미리 기록 (docker bind mount가 파일을 필요로 함)
git rev-parse --short HEAD > "$REPO_ROOT/GIT_HASH" 2>/dev/null || true
git log -1 --format="%ci" HEAD 2>/dev/null | sed 's/ +[0-9]*//' | tr -d '\n' > "$REPO_ROOT/GIT_DATE" || true

# Build
BUILD_SERVICES=()
for c in "${CHANGED[@]}"; do
  case "$c" in
    api-server)    BUILD_SERVICES+=(api-server) ;;
    mcp-server)    BUILD_SERVICES+=(mcp-server) ;;
    frontend)      BUILD_SERVICES+=(frontend) ;;
    workers)       BUILD_SERVICES+=(celery-worker-preprocessing) ;;
    gateway)       ;;
    dotenv)        ;;
    compose-file)  BUILD_SERVICES+=(api-server mcp-server frontend celery-worker-preprocessing) ;;
  esac
done
BUILD_SERVICES=($(printf '%s\n' "${BUILD_SERVICES[@]}" | sort -u))

# GPU overlay 자동 감지 (docker-compose.gpu.yml 존재하면 항상 포함)
COMPOSE_CMD=(docker compose)
if [[ -f "$REPO_ROOT/docker-compose.gpu.yml" ]]; then
  COMPOSE_CMD+=(--file docker-compose.yml --file docker-compose.gpu.yml)
fi

if [[ ${#BUILD_SERVICES[@]} -eq 0 ]]; then
  echo "Build: (skip — no image rebuild needed)"
else
  echo "Building: ${BUILD_SERVICES[*]}"
  "${COMPOSE_CMD[@]}" build "${BUILD_SERVICES[@]}"
fi

# Restart
RESTART_SERVICES=()
for c in "${CHANGED[@]}"; do
  case "$c" in
    api-server)   RESTART_SERVICES+=(api-server) ;;
    mcp-server)   RESTART_SERVICES+=(mcp-server) ;;
    frontend)     RESTART_SERVICES+=(frontend) ;;
    workers)      RESTART_SERVICES+=(celery-worker-preprocessing celery-worker-rag celery-worker-report) ;;
    gateway)      RESTART_SERVICES+=(gateway) ;;
    dotenv)       RESTART_SERVICES+=("${APP_STACK_SERVICES[@]}") ;;
    compose-file) RESTART_SERVICES+=("${APP_STACK_SERVICES[@]}") ;;
  esac
done
RESTART_SERVICES=($(printf '%s\n' "${RESTART_SERVICES[@]}" | sort -u))

if [[ ${#RESTART_SERVICES[@]} -eq 0 ]]; then
  echo "Warning: nothing to restart."
else
  echo "Restarting: ${RESTART_SERVICES[*]}"
  "${COMPOSE_CMD[@]}" up -d "${RESTART_SERVICES[@]}"
fi

touch "$LAST_DEV_BUILD"
git rev-parse HEAD > "$LAST_DEV_COMMIT" 2>/dev/null || true
git rev-parse --short HEAD > "$REPO_ROOT/GIT_HASH" 2>/dev/null || true
# 빌드 시점의 commit 날짜/시각 기록 (Web UI 표시용)
git log -1 --format="%ci" HEAD 2>/dev/null | sed 's/ +[0-9]*//' | tr -d '\n' > "$REPO_ROOT/GIT_DATE" || true
echo "Done. (Version: $_a.$_b.$_c.$_d, Hash: $(cat "$REPO_ROOT/GIT_HASH"), Date: $(cat "$REPO_ROOT/GIT_DATE"))"
