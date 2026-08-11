#!/usr/bin/env bash
# Start PTM Platform with SemVer from VERSION file (Major.Minor.Patch)
# Usage: ./scripts/up.sh [docker compose args...]

set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

_v=$(cat "$REPO_ROOT/VERSION" 2>/dev/null | tr -d ' \n\r' || echo "0.0.0")
IFS='.' read -r _major _minor _patch _ <<< "$_v"
_major=$(printf "%d" $((10#${_major//[^0-9]/:-0})))
_minor=$(printf "%d" $((10#${_minor//[^0-9]/:-0})))
_patch=$(printf "%d" $((10#${_patch//[^0-9]/:-0})))
_v="${_major}.${_minor}.${_patch}"

# All component images share the platform SemVer tag
export VERSION="$_v"
export VERSION_API="$_v"
export VERSION_MCP="$_v"
export VERSION_FRONTEND="$_v"
export VERSION_WORKERS="$_v"

# Ensure GIT_HASH exists for api-server mount
touch "$REPO_ROOT/GIT_HASH" 2>/dev/null || true
git rev-parse --short HEAD > "$REPO_ROOT/GIT_HASH" 2>/dev/null || true

exec docker compose up -d "$@"
