#!/usr/bin/env bash
# PTM Platform - Dev Deploy (커밋 없이 수정된 것만 빌드 & 재시작)
# - 작업 중인 변경(uncommitted + staged)을 감지
# - 감지 범위: api-server, mcp-server, frontend, workers, gateway, docker-compose.yml,
#   docker-compose.override.yml(있을 때), .env
# - 버전은 올리지 않음
# Usage: ./scripts/dev-deploy.sh [--all]

set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

VERSION_FILE="$REPO_ROOT/VERSION"
LAST_DEV_BUILD="$REPO_ROOT/.last-dev-build"

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

# 수정된 컴포넌트 감지: 마지막 빌드 이후 실제로 변경된 소스 파일만
# (node_modules, __pycache__ 등 제외 — npm install/실행 시 불필요 빌드 방지)
get_changed_components() {
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

  # 루트 compose / env (마커가 있을 때만 — 최초 실행은 위 디렉터리들로 전체 빌드가 이미 잡힘)
  if [[ -f "$marker" ]]; then
    local root_files=(docker-compose.yml .env)
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
    echo "수정된 파일이 없습니다. --all 로 전체 빌드."
    exit 0
  fi
  echo "Changed: ${CHANGED[*]}"
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

if [[ ${#BUILD_SERVICES[@]} -eq 0 ]]; then
  echo "Build: (skip — no image rebuild needed)"
else
  echo "Building: ${BUILD_SERVICES[*]}"
  docker compose build "${BUILD_SERVICES[@]}"
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
  docker compose up -d "${RESTART_SERVICES[@]}"
fi

touch "$LAST_DEV_BUILD"
# Update git hash for display
git rev-parse --short HEAD > "$REPO_ROOT/GIT_HASH" 2>/dev/null || true
echo "Done. (Version: $_a.$_b.$_c.$_d)"
