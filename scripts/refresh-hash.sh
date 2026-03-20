#!/usr/bin/env bash
# GIT_HASH만 갱신 (버전·빌드 없이 push된 커밋 표시용)
# Usage: ./scripts/refresh-hash.sh

set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

HASH=$(git rev-parse --short HEAD 2>/dev/null || echo "")
echo "$HASH" > "$REPO_ROOT/GIT_HASH"
echo "GIT_HASH updated: $HASH"
