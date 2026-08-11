#!/usr/bin/env bash
# PTM Platform Deploy Script (SemVer)
# - Platform version: Major.Minor.Patch (e.g. 2.1.1)
# - Version bumps only when explicitly requested (--bump / --set)
# - All component images share the same platform version tag
# Usage:
#   ./scripts/deploy.sh                  # rebuild changed components, keep VERSION
#   ./scripts/deploy.sh --all            # rebuild all, keep VERSION
#   ./scripts/deploy.sh --bump major     # 1.2.3 → 2.0.0, then rebuild all
#   ./scripts/deploy.sh --bump minor     # 1.2.3 → 1.3.0, then rebuild all
#   ./scripts/deploy.sh --bump patch     # 1.2.3 → 1.2.4, then rebuild all
#   ./scripts/deploy.sh --set 2.1.1      # set exact version, then rebuild all

set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

VERSION_FILE="$REPO_ROOT/VERSION"
LAST_DEPLOY_FILE="$REPO_ROOT/.last-deploy"

read_version() {
  local v
  v=$(cat "$VERSION_FILE" 2>/dev/null | tr -d ' \n\r' || echo "0.0.0")
  # Legacy 4-part AAA.BBB.CCC.DDD → collapse to MAJOR.MINOR.PATCH
  # Prefer first three numeric fields; ignore a 4th component-image field.
  local major minor patch rest
  IFS='.' read -r major minor patch rest <<< "$v"
  major=$(printf "%d" $((10#${major//[^0-9]/:-0})))
  minor=$(printf "%d" $((10#${minor//[^0-9]/:-0})))
  patch=$(printf "%d" $((10#${patch//[^0-9]/:-0})))
  echo "${major}.${minor}.${patch}"
}

write_version() {
  echo "$1" > "$VERSION_FILE"
}

export_image_tags() {
  # All services share one platform SemVer tag
  export VERSION="$1"
  export VERSION_API="$1"
  export VERSION_MCP="$1"
  export VERSION_FRONTEND="$1"
  export VERSION_WORKERS="$1"
}

bump_semver() {
  local current="$1" kind="$2"
  local major minor patch
  IFS='.' read -r major minor patch <<< "$current"
  case "$kind" in
    major) echo "$((major + 1)).0.0" ;;
    minor) echo "${major}.$((minor + 1)).0" ;;
    patch) echo "${major}.${minor}.$((patch + 1))" ;;
    *)
      echo "Unknown bump kind: $kind (use major|minor|patch)" >&2
      exit 1
      ;;
  esac
}

get_changed_components() {
  local diff_files

  if [[ -f "$LAST_DEPLOY_FILE" ]]; then
    diff_files=$(git diff --name-only "$(cat "$LAST_DEPLOY_FILE")" HEAD 2>/dev/null || true)
  else
    diff_files=$(git diff --name-only HEAD 2>/dev/null || true)
    diff_files+=$'\n'$(git diff --name-only --cached HEAD 2>/dev/null || true)
  fi
  # Also include uncommitted worktree changes so local edits are deployed
  diff_files+=$'\n'$(git diff --name-only HEAD 2>/dev/null || true)
  diff_files+=$'\n'$(git diff --name-only --cached HEAD 2>/dev/null || true)

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

FORCE_ALL=false
BUMP_KIND=""
SET_VERSION=""
args=("$@")
for ((i=0; i<${#args[@]}; i++)); do
  case "${args[$i]}" in
    --all) FORCE_ALL=true ;;
    --bump)
      BUMP_KIND="${args[$((i+1))]:-}"
      if [[ "$BUMP_KIND" != "major" && "$BUMP_KIND" != "minor" && "$BUMP_KIND" != "patch" ]]; then
        echo "Usage: --bump major|minor|patch" >&2
        exit 1
      fi
      ((i++))
      ;;
    --set)
      SET_VERSION="${args[$((i+1))]:-}"
      if [[ ! "$SET_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        echo "Usage: --set MAJOR.MINOR.PATCH  (e.g. --set 2.1.1)" >&2
        exit 1
      fi
      ((i++))
      ;;
  esac
done

echo "=== PTM Platform Deploy (SemVer) ==="

CURRENT=$(read_version)
NEW_VERSION="$CURRENT"
VERSION_CHANGED=false

if [[ -n "$SET_VERSION" ]]; then
  NEW_VERSION="$SET_VERSION"
  VERSION_CHANGED=true
elif [[ -n "$BUMP_KIND" ]]; then
  NEW_VERSION=$(bump_semver "$CURRENT" "$BUMP_KIND")
  VERSION_CHANGED=true
fi

if $VERSION_CHANGED; then
  write_version "$NEW_VERSION"
  echo "Version: $CURRENT -> $NEW_VERSION"
  # Shared tag means all images must exist at the new version
  FORCE_ALL=true
else
  echo "Version: $NEW_VERSION (unchanged — use --bump/--set for SemVer release)"
fi

export_image_tags "$NEW_VERSION"

if $FORCE_ALL; then
  CHANGED=("api-server" "mcp-server" "frontend" "workers")
  echo "Building all components"
else
  CHANGED=($(get_changed_components))
  if [[ ${#CHANGED[@]} -eq 0 ]]; then
    if [[ ! -f "$LAST_DEPLOY_FILE" ]]; then
      CHANGED=("api-server" "mcp-server" "frontend" "workers")
      echo "First deploy: building all components"
    else
      echo "No component changes detected. Use --all to force rebuild, or --bump/--set to release."
      exit 0
    fi
  else
    echo "Changed components: ${CHANGED[*]}"
  fi
fi

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

echo "Building: ${BUILD_SERVICES[*]} (tag ${NEW_VERSION})"
for svc in "${BUILD_SERVICES[@]}"; do
  docker compose build --build-arg VERSION="$NEW_VERSION" "$svc"
done

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

git rev-parse HEAD > "$LAST_DEPLOY_FILE"
git rev-parse --short HEAD > "$REPO_ROOT/GIT_HASH" 2>/dev/null || true
git log -1 --format="%ci" HEAD 2>/dev/null | sed 's/ +[0-9]*//' | tr -d '\n' > "$REPO_ROOT/GIT_DATE" || true

echo "Deploy complete. Version $NEW_VERSION is live."
