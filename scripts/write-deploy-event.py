#!/usr/bin/env python3
"""Write data/.last-dev-deploy.json for the admin sidebar runtime banner."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def write_git_date(repo_root: Path) -> str:
    """Record the deploy wall clock, not the commit object's clock."""
    stamp = datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")
    (repo_root / "GIT_DATE").write_text(stamp, encoding="utf-8")
    return stamp


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--kind", default="dev-deploy")
    parser.add_argument("--version", default="")
    parser.add_argument("--commit", default="")
    parser.add_argument("--built", default="")
    parser.add_argument("--restarted", default="")
    parser.add_argument("--stamp-only", action="store_true")
    args = parser.parse_args()
    repo_root = Path(args.repo_root)
    if args.stamp_only:
        print(write_git_date(repo_root))
        return

    def split_services(raw: str) -> list[str]:
        return [part for part in raw.replace(",", " ").split() if part]

    stamp = write_git_date(repo_root)
    payload = {
        "schema": "dev_deploy_event.v1",
        "at": stamp,
        "kind": args.kind,
        "version": args.version,
        "commit": args.commit,
        "built": split_services(args.built),
        "restarted": split_services(args.restarted),
    }
    out = Path(args.repo_root) / "data" / ".last-dev-deploy.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
