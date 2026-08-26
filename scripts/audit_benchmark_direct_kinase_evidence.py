#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from benchmarking.direct_evidence_audit import run_audit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--ptm-type", default="phosphorylation")
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--batch-delay-seconds", type=float, default=0.3)
    args = parser.parse_args()

    result = asyncio.run(
        run_audit(
            artifact_path=Path(args.artifact),
            ptm_type=args.ptm_type,
            batch_size=max(1, args.batch_size),
            batch_delay_seconds=max(0.0, args.batch_delay_seconds),
        )
    )
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(target),
                "query_summary": result["query_summary"],
                "source_status": result["source_status"],
                "evidence_summary": result["evidence_summary"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
