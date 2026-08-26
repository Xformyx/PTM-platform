"""Create a runner-only eligibility audit from a locked benchmark score result."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmarking.truth_development_audit import build_truth_development_audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--score-result", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--minimum-measurable-anchors", type=int, default=None)
    parser.add_argument("--minimum-regulated-anchors", type=int, default=None)
    parser.add_argument("--minimum-temporal-evaluable-anchors", type=int, default=None)
    parser.add_argument("--minimum-measurable-branches", type=int, default=None)
    parser.add_argument("--minimum-holdout-measurable-anchors", type=int, default=None)
    args = parser.parse_args()
    overrides = {
        key: value
        for key, value in {
            "minimum_measurable_anchors": args.minimum_measurable_anchors,
            "minimum_regulated_anchors": args.minimum_regulated_anchors,
            "minimum_temporal_evaluable_anchors": args.minimum_temporal_evaluable_anchors,
            "minimum_measurable_branches": args.minimum_measurable_branches,
            "minimum_holdout_measurable_anchors": args.minimum_holdout_measurable_anchors,
        }.items()
        if value is not None
    }
    score_result = json.loads(Path(args.score_result).read_text(encoding="utf-8"))
    report = build_truth_development_audit(score_result, policy=overrides)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
