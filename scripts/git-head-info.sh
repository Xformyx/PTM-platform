#!/usr/bin/env bash
# 로컬 HEAD 짧은 해시와 최신 커밋 메시지 출력
# - 루트 VERSION 파일, git describe, HEAD 태그는 커밋 제목과 별개(워킹트리/태그 기준)
# Usage: ./scripts/git-head-info.sh

set -e
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Error: not a git repository: $REPO_ROOT" >&2
  exit 1
fi

short=$(git rev-parse --short HEAD)
full=$(git rev-parse HEAD)
branch=$(git branch --show-current 2>/dev/null || echo "?")

echo "branch:  $branch"
echo "HEAD:    $short ($full)"

# 워킹트리의 VERSION 파일 (Docker/표시용 — 커밋 제목의 v9.x와 다를 수 있음)
if [[ -f "$REPO_ROOT/VERSION" ]]; then
  ver_file=$(tr -d ' \n\r' < "$REPO_ROOT/VERSION")
  echo "VERSION 파일: $ver_file"
else
  echo "VERSION 파일: (없음)"
fi

# 가장 가까운 태그 + 앞섬 커밋 수 (태그 없으면 짧은 해시만)
if desc=$(git describe --tags --always --dirty 2>/dev/null); then
  echo "git describe: $desc"
fi

# 이 커밋에 붙은 태그(있으면)
tags=$(git tag --points-at HEAD 2>/dev/null | tr '\n' ',' | sed 's/,$//')
if [[ -n "$tags" ]]; then
  echo "HEAD 태그:   $tags"
else
  echo "HEAD 태그:   (없음)"
fi

echo ""
echo "커밋 메시지:"
git --no-pager log -1 --pretty=format:"%s%n%n%b"
echo ""
