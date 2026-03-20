#!/usr/bin/env bash
# Start PTM Platform with version from VERSION file
# Usage: ./scripts/up.sh [docker compose args...]

set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

VERSION=$(cat "$REPO_ROOT/VERSION" 2>/dev/null | tr -d ' \n\r' || echo "001.001.001.001")
export VERSION

# Ensure GIT_HASH exists for api-server mount
touch "$REPO_ROOT/GIT_HASH" 2>/dev/null || true
git rev-parse --short HEAD > "$REPO_ROOT/GIT_HASH" 2>/dev/null || true

exec docker compose up -d "$@"
