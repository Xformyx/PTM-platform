#!/usr/bin/env bash
# Start PTM Platform with version from VERSION file
# Usage: ./scripts/up.sh [docker compose args...]

set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# Parse VERSION (AAA.BBB.CCC.DDD) -> per-component tags
_v=$(cat "$REPO_ROOT/VERSION" 2>/dev/null | tr -d ' \n\r' || echo "001.001.001.001")
IFS='.' read -r _a _b _c _d _ <<< "$_v"
_a=$(printf "%03d" $((10#${_a//[^0-9]/:-0})))
_b=$(printf "%03d" $((10#${_b//[^0-9]/:-0})))
_c=$(printf "%03d" $((10#${_c//[^0-9]/:-0})))
_d=$(printf "%03d" $((10#${_d//[^0-9]/:-0})))
export VERSION_API="${_a}"
export VERSION_MCP="${_b}"
export VERSION_FRONTEND="${_c}"
export VERSION_WORKERS="${_d}"

# Ensure GIT_HASH exists for api-server mount
touch "$REPO_ROOT/GIT_HASH" 2>/dev/null || true
git rev-parse --short HEAD > "$REPO_ROOT/GIT_HASH" 2>/dev/null || true

exec docker compose up -d "$@"
