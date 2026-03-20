#!/usr/bin/env bash
# PTM Platform Deploy Script
# - Detects which components changed (api-server, mcp-server, frontend, workers)
# - Bumps version (AAA.BBB.CCC.DDD) for changed components
# - Builds only changed images
# - Restarts only changed services
# Usage: ./scripts/deploy.sh [--all]

set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

VERSION_FILE="$REPO_ROOT/VERSION"
LAST_DEPLOY_FILE="$REPO_ROOT/.last-deploy"

# AA=api-server, BB=mcp-server, CC=frontend, DD=workers
# Format: AAA.BBB.CCC.DDD (3 digits each, 000-999). Display: leading zeros omitted (e.g. 1.1.1.1)

# Bump field (000-999 decimal)
bump_dec() {
  local val="${1//[^0-9]/}"
  val="${val:-0}"
  local num=$((10#$val + 1))
  num=$((num % 1000))
  printf "%03d" $num
}

# Parse VERSION file (AAA.BBB.CCC.DDD), normalize to 3-digit segments
read_version() {
  local v
  v=$(cat "$VERSION_FILE" 2>/dev/null | tr -d ' \n\r' || echo "001.001.001.001")
  local aa bb cc dd
  IFS='.' read -r aa bb cc dd _ <<< "$v"
  aa=$(printf "%03d" $((10#${aa//[^0-9]/:-0})))
  bb=$(printf "%03d" $((10#${bb//[^0-9]/:-0})))
  cc=$(printf "%03d" $((10#${cc//[^0-9]/:-0})))
  dd=$(printf "%03d" $((10#${dd//[^0-9]/:-0})))
  echo "${aa}.${bb}.${cc}.${dd}"
}

# Write VERSION file
write_version() {
  echo "$1" > "$VERSION_FILE"
}

# Get changed components since last deploy
get_changed_components() {
  local diff_files

  if [[ -f "$LAST_DEPLOY_FILE" ]]; then
    diff_files=$(git diff --name-only "$(cat "$LAST_DEPLOY_FILE")" HEAD 2>/dev/null || true)
  else
    diff_files=$(git diff --name-only HEAD 2>/dev/null || true)
    diff_files+=$'\n'$(git diff --name-only --cached HEAD 2>/dev/null || true)
  fi

  local result=()
  while IFS= read -r f; do
    [[ -z "$f" ]] && continue
    [[ "$f" == api-server/* ]] && result+=("api-server")
    [[ "$f" == mcp-server/* ]] && result+=("mcp-server")
    [[ "$f" == frontend/* ]] && result+=("frontend")
    [[ "$f" == workers/* ]] && result+=("workers")
  done <<< "$diff_files"

  printf '%s\n' "${result[@]}" | sort -u
}

# Main
FORCE_ALL=false
for arg in "$@"; do
  [[ "$arg" == "--all" ]] && FORCE_ALL=true
done

echo "=== PTM Platform Deploy ==="

# Read current version (normalized to 001.001.001.001)
CURRENT=$(read_version)
IFS='.' read -r AA BB CC DD _ <<< "$CURRENT"
AA="${AA//[^0-9]/}"; AA="${AA:-000}"
BB="${BB//[^0-9]/}"; BB="${BB:-000}"
CC="${CC//[^0-9]/}"; CC="${CC:-000}"
DD="${DD//[^0-9]/}"; DD="${DD:-000}"

# Determine what to build
if $FORCE_ALL; then
  CHANGED=("api-server" "mcp-server" "frontend" "workers")
  echo "Building all components (--all)"
else
  CHANGED=($(get_changed_components))
  if [[ ${#CHANGED[@]} -eq 0 ]]; then
    if [[ ! -f "$LAST_DEPLOY_FILE" ]]; then
      CHANGED=("api-server" "mcp-server" "frontend" "workers")
      echo "First deploy: building all components"
    else
      echo "No changes detected. Use --all to force full rebuild."
      exit 0
    fi
  else
    echo "Changed components: ${CHANGED[*]}"
  fi
fi

# Bump version for changed components
for c in "${CHANGED[@]}"; do
  case "$c" in
    api-server) AA=$(bump_dec "$AA") ;;
    mcp-server) BB=$(bump_dec "$BB") ;;
    frontend)   CC=$(bump_dec "$CC") ;;
    workers)    DD=$(bump_dec "$DD") ;;
  esac
done

NEW_VERSION="${AA}.${BB}.${CC}.${DD}"
write_version "$NEW_VERSION"
echo "Version: $CURRENT -> $NEW_VERSION"

# Export per-component tags for docker-compose
export VERSION_API="$AA"
export VERSION_MCP="$BB"
export VERSION_FRONTEND="$CC"
export VERSION_WORKERS="$DD"

# Build changed services (each with its own version tag)
BUILD_SERVICES=()
for c in "${CHANGED[@]}"; do
  case "$c" in
    api-server) BUILD_SERVICES+=(api-server) ;;
    mcp-server) BUILD_SERVICES+=(mcp-server) ;;
    frontend)   BUILD_SERVICES+=(frontend) ;;
    workers)    BUILD_SERVICES+=(celery-worker-preprocessing) ;;  # one worker builds the image
  esac
done

# Deduplicate (workers share image, building one builds all)
BUILD_SERVICES=($(printf '%s\n' "${BUILD_SERVICES[@]}" | sort -u))

echo "Building: ${BUILD_SERVICES[*]}"
for svc in "${BUILD_SERVICES[@]}"; do
  case "$svc" in
    api-server)  arg="$AA" ;;
    mcp-server)  arg="$BB" ;;
    frontend)    arg="$CC" ;;
    celery-worker-preprocessing) arg="$DD" ;;
    *) arg="001" ;;
  esac
  docker compose build --build-arg VERSION="$arg" "$svc"
done

# Restart changed services
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

# Save deploy commit
git rev-parse HEAD > "$LAST_DEPLOY_FILE"
# Update git hash for display
git rev-parse --short HEAD > "$REPO_ROOT/GIT_HASH" 2>/dev/null || true
echo "Deploy complete. Version $NEW_VERSION is live."
