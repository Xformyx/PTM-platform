"""Evaluate a preregistered dynamic co-wave candidate list without locked truth."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmarking.dynamic_cowave_evaluation import evaluate_dynamic_candidate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--candidate-grid", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    artifact = json.loads(Path(args.artifact).read_text(encoding="utf-8"))
    grid = json.loads(Path(args.candidate_grid).read_text(encoding="utf-8"))
    candidates = list(grid.get("candidate_input_list") or [])
    if not candidates:
        raise ValueError("candidate_input_list is empty")
    results = []
    for candidate in candidates:
        config = {
            "activity_threshold_fc": candidate["activity_threshold_fc"],
            "minimum_observed_timepoints": candidate["minimum_observed_timepoints"],
            "membership_universe": candidate["membership_universe"],
            "lotto": candidate["lotto"],
        }
        result = evaluate_dynamic_candidate(artifact, config=config, adoption_gate=grid["adoption_gate"])
        result["trial_id"] = candidate["trial_id"]
        results.append(result)
    ranked = sorted(
        results,
        key=lambda row: (not bool(row["adoption_gate"]["passed"]), -(row["metrics"]["objective"] or -1.0), row["trial_id"]),
    )
    payload = {
        "schema_version": "dynamic_cowave_truth_free_candidate_comparison.v1",
        "preregistration": {
            "candidate_count": len(candidates),
            "candidate_input_list": candidates,
            "adoption_gate": grid["adoption_gate"],
            "selection_boundary": grid.get("selection_boundary"),
        },
        "results": results,
        "ranking": [
            {
                "rank": index + 1,
                "trial_id": row["trial_id"],
                "objective": row["metrics"]["objective"],
                "adoption_passed": row["adoption_gate"]["passed"],
            }
            for index, row in enumerate(ranked)
        ],
        "selected_trial": next((row["trial_id"] for row in ranked if row["adoption_gate"]["passed"]), None),
        "decision": "adopt_additive_annotation" if any(row["adoption_gate"]["passed"] for row in ranked) else "do_not_adopt_default_keep_experimental",
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"decision": payload["decision"], "ranking": payload["ranking"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
