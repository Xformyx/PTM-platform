#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmarking.v2_truth_adapter import build_additive_v2_truth


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v1-truth", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    v1_truth = json.loads(Path(args.v1_truth).read_text(encoding="utf-8"))
    payload = build_additive_v2_truth(v1_truth)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "truth_sha256": payload["truth_sha256"], "evaluability": payload["evaluability"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
