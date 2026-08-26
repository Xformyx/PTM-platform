#!/usr/bin/env python3
"""Append one validated trial to a strict-blind optimization ledger."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from benchmarking.blind_trial_ledger import append_trial, verify_ledger


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--trial-id", required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--config-json", required=True)
    parser.add_argument("--objective-json", required=True)
    parser.add_argument("--fold-metrics-json")
    parser.add_argument("--decision", choices=["continue", "reject", "select", "freeze"], required=True)
    parser.add_argument("--decision-reason", required=True)
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    return parser.parse_args()


def read_json(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> None:
    args = parse_args()
    existing = verify_ledger(args.ledger)
    if not existing:
        raise SystemExit("baseline record is required before appending trials")
    previous = existing[-1]
    fold_metrics = read_json(args.fold_metrics_json) if args.fold_metrics_json else []
    record = append_trial(
        args.ledger,
        trial_id=args.trial_id,
        phase=args.phase,
        code_commit=subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=args.repo, text=True
        ).strip(),
        input_hashes=previous["input_hashes"],
        variable_config=read_json(args.config_json),
        objective=read_json(args.objective_json),
        fold_metrics=fold_metrics,
        decision=args.decision,
        decision_reason=args.decision_reason,
        parent_config_sha256=previous["config_sha256"],
    )
    print(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
