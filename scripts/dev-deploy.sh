#!/usr/bin/env bash
# PTM Platform - Dev Deploy (커밋 없이 수정된 것만 빌드 & 재시작)
# - 작업 중인 변경(uncommitted + staged)을 감지
# - 버전은 올리지 않음
# Usage: ./scripts/dev-deploy.sh [--all]

set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

VERSION_FILE="$REPO_ROOT/VERSION"
LAST_DEV_BUILD="$REPO_ROOT/.last-dev-build"

# 수정된 컴포넌트 감지: 마지막 빌드 이후 실제로 변경된 파일만
# (.last-dev-build 보다 mtime이 최신인 파일이 있는 디렉터리)
get_changed_components() {
  local result=()
  local marker="$LAST_DEV_BUILD"

  for dir in api-server mcp-server frontend workers; do
    [[ ! -d "$REPO_ROOT/$dir" ]] && continue
    if [[ ! -f "$marker" ]]; then
      result+=("$dir")
    else
      # 해당 디렉터리에 marker보다 최신인 파일이 있으면 변경됨
      if find "$REPO_ROOT/$dir" -type f -newer "$marker" 2>/dev/null | grep -q .; then
        result+=("$dir")
      fi
    fi
  done

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
  CHANGED=("api-server" "mcp-server" "frontend" "workers")
  echo "Building all (--all)"
else
  CHANGED=($(get_changed_components))
  if [[ ${#CHANGED[@]} -eq 0 ]]; then
    echo "수정된 파일이 없습니다. --all 로 전체 빌드."
    exit 0
  fi
  echo "Changed: ${CHANGED[*]}"
fi

# VERSION 파일에서 현재 버전 읽기 (올리지 않음)
VERSION=$(cat "$VERSION_FILE" 2>/dev/null | tr -d ' \n\r' || echo "00.00.00.00")
export VERSION

# Build
BUILD_SERVICES=()
for c in "${CHANGED[@]}"; do
  case "$c" in
    api-server) BUILD_SERVICES+=(api-server) ;;
    mcp-server) BUILD_SERVICES+=(mcp-server) ;;
    frontend)   BUILD_SERVICES+=(frontend) ;;
    workers)    BUILD_SERVICES+=(celery-worker-preprocessing) ;;
  esac
done
BUILD_SERVICES=($(printf '%s\n' "${BUILD_SERVICES[@]}" | sort -u))

echo "Building: ${BUILD_SERVICES[*]}"
docker compose build "${BUILD_SERVICES[@]}"

# Restart
RESTART_SERVICES=()
for c in "${CHANGED[@]}"; do
  case "$c" in
    api-server) RESTART_SERVICES+=(api-server) ;;
    mcp-server) RESTART_SERVICES+=(mcp-server) ;;
    frontend)   RESTART_SERVICES+=(frontend) ;;
    workers)    RESTART_SERVICES+=(celery-worker-preprocessing celery-worker-rag celery-worker-report) ;;
  esac
done
RESTART_SERVICES=($(printf '%s\n' "${RESTART_SERVICES[@]}" | sort -u))

echo "Restarting: ${RESTART_SERVICES[*]}"
docker compose up -d "${RESTART_SERVICES[@]}"

touch "$LAST_DEV_BUILD"
# Update git hash for display
git rev-parse --short HEAD > "$REPO_ROOT/GIT_HASH" 2>/dev/null || true
echo "Done. (Version: $VERSION)"
