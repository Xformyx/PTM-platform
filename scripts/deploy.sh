#!/usr/bin/env bash
# PTM Platform Deploy Script
# - Detects which components changed (api-server, mcp-server, frontend, workers)
# - Bumps version (AA.BB.CC.DD) for changed components
# - Builds only changed images
# - Restarts only changed services
# Usage: ./scripts/deploy.sh [--all]

set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

VERSION_FILE="$REPO_ROOT/VERSION"
LAST_DEPLOY_FILE="$REPO_ROOT/.last-deploy"

# AA=api-server, BB=mcp-server, CC=frontend, DD=workers

# Bump field (00-FF hex)
bump_hex() {
  local val="${1//[^0-9a-fA-F]/}"
  val="${val:-0}"
  local num
  num=$(printf '%d' "0x${val}") 2>/dev/null || num=0
  num=$(( (num + 1) % 256 ))
  printf "%02x" $num
}

# Parse VERSION file (AA.BB.CC.DD)
read_version() {
  local v
  v=$(cat "$VERSION_FILE" 2>/dev/null | tr -d ' \n\r' || echo "00.00.00.00")
  echo "$v"
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

# Read current version
CURRENT=$(read_version)
IFS='.' read -r AA BB CC DD _ <<< "$CURRENT"
AA="${AA//[^0-9a-fA-F]/}"; AA="${AA:-00}"
BB="${BB//[^0-9a-fA-F]/}"; BB="${BB:-00}"
CC="${CC//[^0-9a-fA-F]/}"; CC="${CC:-00}"
DD="${DD//[^0-9a-fA-F]/}"; DD="${DD:-00}"

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
    api-server) AA=$(bump_hex "$AA") ;;
    mcp-server) BB=$(bump_hex "$BB") ;;
    frontend)   CC=$(bump_hex "$CC") ;;
    workers)    DD=$(bump_hex "$DD") ;;
  esac
done

NEW_VERSION="${AA}.${BB}.${CC}.${DD}"
write_version "$NEW_VERSION"
echo "Version: $CURRENT -> $NEW_VERSION"

# Export for docker-compose
export VERSION="$NEW_VERSION"

# Build changed services
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
docker compose build --build-arg VERSION="$NEW_VERSION" "${BUILD_SERVICES[@]}"

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
