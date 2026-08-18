"""Rank representation arms on a task none of them can game.

Loads an order's L1 Quantitative PTM Feature Vector, builds the L3 multi-view
input exactly as Step 1c does, then runs the held-out timepoint probe: one
timepoint is blanked across every view, each arm builds its representation from
what remains, and a ridge probe predicts the withheld Track 2 value on sites it
never trained on.

Run inside the preprocessing worker, which has scipy and the shared package:

    docker exec -i ptm-worker-preprocessing env PYTHONPATH=/app:/opt python - \
        --order-code Insulin_Signaling_Phosphoproteomics_HIRc-B \
        < scripts/run_representation_fair_probe.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Mapping

sys.path[:0] = ["/app", "/opt"]


def load_multiview(vector_path: Path, *, key_level: str = "site_form"):
    import pandas as pd

    from ptm_shared.representation import build_multiview_input, validate_multiview_input

    frame = pd.read_csv(vector_path, sep="\t", low_memory=False)
    if frame.empty:
        raise RuntimeError(f"{vector_path} is empty")
    multiview = build_multiview_input(
        frame.to_dict("records"),
        config={"key_level": key_level, "minimum_observed_timepoints": 3},
    )
    errors = validate_multiview_input(multiview)
    if errors:
        raise RuntimeError(f"L3 input contract violations: {errors}")
    return multiview


def print_report(report: Mapping[str, Any]) -> None:
    if report.get("status") != "evaluated":
        print(f"  status={report.get('status')} — {json.dumps(dict(report))[:300]}")
        return

    print(
        f"  task={report['task']} | sites={report['n_sites']}"
        f" timepoints={report['n_timepoints']}"
    )
    print()
    header = (
        f"  {'arm':>4} {'dim':>5} {'folds':>6} {'mean R2':>9} {'sd':>8}"
        f" {'null R2':>9} {'beats null':>11} {'alpha':>8}"
    )
    print(header)
    for arm, summary in sorted(report["per_arm"].items()):
        def number(key: str, width: int = 9) -> str:
            value = summary.get(key)
            return f"{value:>{width}.4f}" if isinstance(value, (int, float)) else f"{'n/a':>{width}}"

        print(
            f"  {arm:>4} {summary['embedding_dim']:>5} {summary['n_folds']:>6}"
            f"{number('mean_r2')}{number('sd_r2', 8)}{number('mean_null_r2')}"
            f"{number('fraction_beating_null_at_0.05', 11)}"
            f"{summary['median_alpha']:>8.2f}"
        )

    comparisons = report.get("comparisons") or {}
    baseline = comparisons.get("baseline_arm")
    print(f"\n  paired against arm {baseline} (same hidden timepoint, same probe rows)")
    for arm, entry in sorted((comparisons.get("arms") or {}).items()):
        if "mean_r2_difference" not in entry:
            print(f"  {arm:>4} {entry.get('status')}")
            continue
        print(
            f"  {arm:>4} dR2={entry['mean_r2_difference']:+.4f}"
            f" | better in {entry['fraction_of_folds_better']*100:5.1f}% of"
            f" {entry['n_paired_folds']} folds"
            f" | p={entry['sign_flip_p_value']:.4f}"
            f" | {entry['verdict']}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--order-code", required=True)
    parser.add_argument("--outputs-root", default="/app/data/outputs")
    parser.add_argument("--file-suffix", default="_phospho")
    parser.add_argument("--arms", default="A,B,D,E")
    parser.add_argument("--baseline-arm", default="B")
    parser.add_argument("--encoder-seeds", type=int, default=5)
    parser.add_argument("--probe-splits", type=int, default=4)
    parser.add_argument("--permutations", type=int, default=100)
    parser.add_argument("--epochs", type=int, default=300)
    args = parser.parse_args()

    from ptm_shared.representation import run_heldout_timepoint_probe

    order_dir = Path(args.outputs_root) / args.order_code
    vector_path = order_dir / f"ptm_vector_data_normalized{args.file_suffix}.tsv"
    print(f"order {args.order_code}")
    print(f"  L1 vector: {vector_path}")

    multiview = load_multiview(vector_path)
    print(f"  timepoints: {multiview.timepoints}")

    report = run_heldout_timepoint_probe(
        multiview,
        encoder_config={"epochs": args.epochs, "n_perturbations": 0},
        config={
            "arms": tuple(token for token in args.arms.split(",") if token),
            "baseline_arm": args.baseline_arm,
            "n_encoder_seeds": args.encoder_seeds,
            "n_probe_splits": args.probe_splits,
            "n_permutations": args.permutations,
        },
    )
    print_report(report)

    destination = order_dir / f"ptm_representation_fair_probe{args.file_suffix}.json"
    with open(destination, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    print(f"\n  written: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
