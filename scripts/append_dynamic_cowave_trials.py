"""Append all preregistered dynamic co-wave candidate decisions to blind ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from benchmarking.blind_trial_ledger import append_trial


def _sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--comparison", required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--candidate-grid", required=True)
    parser.add_argument("--engine-source", required=True)
    args = parser.parse_args()
    comparison = json.loads(Path(args.comparison).read_text(encoding="utf-8"))
    selected = comparison.get("selected_trial")
    if not selected:
        raise ValueError("comparison has no selected trial")
    input_hashes = {
        "analysis_artifact": _sha256(args.artifact),
        "candidate_grid": _sha256(args.candidate_grid),
        "dynamic_engine_source": _sha256(args.engine_source),
    }
    records = []
    for result in comparison.get("results") or []:
        config = result.get("candidate_config") or {}
        metrics = result.get("metrics") or {}
        folds = ((result.get("dynamic_transition") or {}).get("lotto") or {}).get("folds") or []
        trial_id = str(result.get("trial_id"))
        decision = "select" if trial_id == selected else "reject"
        reason = (
            "Highest preregistered objective with every adoption gate satisfied."
            if decision == "select"
            else "Lower preregistered objective than selected eligible candidate."
        )
        records.append(
            append_trial(
                args.ledger,
                trial_id=trial_id,
                phase="dynamic_cowave_truth_free",
                code_commit=_git_head(),
                input_hashes=input_hashes,
                variable_config={
                    "dynamic_cowave.activity_threshold_fc": float(config["activity_threshold_fc"]),
                    "dynamic_cowave.minimum_observed_timepoints": int(config["minimum_observed_timepoints"]),
                },
                objective={
                    "objective": metrics.get("objective"),
                    "mean_pair_loto_jaccard": metrics.get("mean_pair_loto_jaccard"),
                    "mean_site_loto_jaccard": metrics.get("mean_site_loto_jaccard"),
                    "local_active_pair_coverage": metrics.get("local_active_pair_coverage"),
                    "transition_resolution": metrics.get("transition_resolution"),
                },
                fold_metrics=folds,
                decision=decision,
                decision_reason=reason,
            )
        )
    print(json.dumps({"record_count": len(records), "selected_trial": selected, "record_sha256": [record["record_sha256"] for record in records]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
