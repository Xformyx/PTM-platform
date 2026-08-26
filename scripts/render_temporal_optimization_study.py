#!/usr/bin/env python3
"""Render manuscript-ready supplementary panels for temporal optimization.

This renderer is intentionally separate from the strict-primary Figure 1–4
bundle. It visualizes truth-free configuration selection and the later one-time
locked evaluation without exposing anchor identities.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def _read_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--robustness", required=True)
    parser.add_argument("--locked-score", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    robustness = _read_json(args.robustness)
    locked = _read_json(args.locked_score)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)

    wave_rows = robustness["wave_full_data_rankings"]
    tmm_rows = robustness["tmm_independent_subset_rankings"]
    locked_metrics = locked["metrics"]
    denominators = locked.get("metric_denominators") or {}

    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "axes.titlesize": 11,
        "axes.labelsize": 9,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
    })
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    fig.subplots_adjust(left=0.13, right=0.98, top=0.89, bottom=0.12, hspace=0.42, wspace=0.52)

    wave_labels = [row["label"].replace("_", " ") for row in reversed(wave_rows)]
    wave_values = [row["objective"] for row in reversed(wave_rows)]
    wave_colors = ["#0f766e" if row["label"] == "selected_median" else "#94a3b8" for row in reversed(wave_rows)]
    axes[0, 0].barh(wave_labels, wave_values, color=wave_colors)
    axes[0, 0].set_title("A. Full-data Wave objective")
    axes[0, 0].set_xlabel("Truth-free stability/structure objective")
    axes[0, 0].set_xlim(0.35, max(wave_values) + 0.02)

    tmm_labels = [row["label"].replace("_", " ") for row in reversed(tmm_rows)]
    tmm_values = [row["objective_mean"] for row in reversed(tmm_rows)]
    tmm_colors = ["#7c3aed" if row["label"] == "selected" else "#c4b5fd" for row in reversed(tmm_rows)]
    axes[0, 1].barh(tmm_labels, tmm_values, color=tmm_colors)
    axes[0, 1].set_title("B. TMM objective across 3 independent subsets")
    axes[0, 1].set_xlabel("Truth-free holdout objective")
    axes[0, 1].set_xlim(0.25, max(tmm_values) + 0.03)

    residual_values = [row["holdout_residual_mean"] for row in reversed(tmm_rows)]
    axes[1, 0].barh(tmm_labels, residual_values, color=tmm_colors)
    axes[1, 0].set_title("C. Replicate-holdout TMM residual")
    axes[1, 0].set_xlabel("Median residual (lower is better)")
    axes[1, 0].set_xlim(0, max(residual_values) + 0.08)

    metric_order = [
        "detectable_anchor_recall",
        "regulated_anchor_recall",
        "direction_accuracy",
        "peak_window_accuracy",
        "chain_completeness",
        "canonical_weighted_score",
    ]
    metric_labels = [label.replace("_", " ") for label in metric_order]
    metric_values = [float(locked_metrics.get(label, 0.0)) for label in metric_order]
    colors = ["#2563eb" if label != "canonical_weighted_score" else "#ea580c" for label in metric_order]
    bars = axes[1, 1].barh(metric_labels, metric_values, color=colors)
    axes[1, 1].set_title("D. One-time locked benchmark evaluation")
    axes[1, 1].set_xlabel("Score")
    axes[1, 1].set_xlim(0, 1.08)
    for bar, label, value in zip(bars, metric_order, metric_values):
        denominator = denominators.get(label)
        suffix = f"  n={int(denominator)}" if denominator is not None else ""
        axes[1, 1].text(value + 0.015, bar.get_y() + bar.get_height() / 2, f"{value:.3f}{suffix}", va="center", fontsize=8)

    fig.suptitle(
        "Truth-free temporal configuration selection and locked insulin benchmark",
        fontsize=15,
        fontweight="bold",
    )
    fig.text(
        0.5,
        0.025,
        "Selection used replicate holdouts only; workbook truth was accessed after configuration freeze.",
        ha="center",
        fontsize=9,
        color="#475569",
    )

    svg_path = output / "Optimization_S1_parameter_selection.svg"
    png_path = output / "Optimization_S1_parameter_selection.png"
    fig.savefig(svg_path, bbox_inches="tight", pad_inches=0.24)
    fig.savefig(png_path, dpi=220, bbox_inches="tight", pad_inches=0.24)
    plt.close(fig)

    source_path = output / "Optimization_S1_source_data.tsv"
    with source_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["panel", "label", "value", "detail"])
        for row in wave_rows:
            writer.writerow(["A", row["label"], row["objective"], row["site_aggregation"]])
        for row in tmm_rows:
            writer.writerow(["B", row["label"], row["objective_mean"], f"min={row['objective_min']:.8f}"])
            writer.writerow(["C", row["label"], row["holdout_residual_mean"], "lower_is_better"])
        for label, value in zip(metric_order, metric_values):
            writer.writerow(["D", label, value, f"denominator={denominators.get(label, 'NA')}"])

    print(json.dumps({
        "svg": str(svg_path),
        "png": str(png_path),
        "source_tsv": str(source_path),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
