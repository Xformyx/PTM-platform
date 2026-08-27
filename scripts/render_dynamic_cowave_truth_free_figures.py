"""Render truth-free dynamic co-wave transition figures from frozen numeric artifacts.

This CLI intentionally accepts only the truth-free candidate evaluation and the
final numeric analysis artifact.  It does not accept a workbook, score, RAG,
LLM output, stimulus label, or biological reference.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from PIL import Image


PALETTE = {
    "ink": "#15253d",
    "blue": "#1976a3",
    "teal": "#238d8d",
    "gold": "#c7901e",
    "coral": "#c85d46",
    "grey": "#8391a2",
    "pale": "#e9eff4",
}
EVENT_COLORS = {
    "persistence": "#6986a6",
    "split": "#c85d46",
    "merge": "#238d8d",
    "recruitment": "#c7901e",
    "exit": "#8d6f9e",
    "unknown": "#8391a2",
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_tsv(path: Path, rows: Iterable[Mapping[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _save_figure(fig: plt.Figure, path: Path, pdf: PdfPages) -> None:
    fig.savefig(path.with_suffix(".png"), dpi=220, facecolor="white", bbox_inches="tight")
    fig.savefig(path.with_suffix(".pdf"), facecolor="white", bbox_inches="tight")
    pdf.savefig(fig, facecolor="white", bbox_inches="tight")
    plt.close(fig)


def _figure_style(fig: plt.Figure, title: str, subtitle: str) -> None:
    fig.patch.set_facecolor("white")
    fig.suptitle(title, fontsize=18, fontweight="bold", color=PALETTE["ink"], x=0.02, ha="left", y=0.985)
    fig.text(0.02, 0.915, subtitle, fontsize=9.5, color="#4d6175", ha="left")


def _axis_style(axis: plt.Axes) -> None:
    axis.spines[["top", "right"]].set_visible(False)
    axis.spines[["left", "bottom"]].set_color("#b9c4cf")
    axis.tick_params(colors="#3b5064", labelsize=9)
    axis.grid(axis="y", color="#dce4eb", linewidth=0.7, zorder=0)
    axis.set_axisbelow(True)


def _nonempty_fraction(path: Path) -> float:
    image = Image.open(path).convert("RGB")
    pixels = list(image.getdata())
    nonwhite = sum(1 for red, green, blue in pixels if min(red, green, blue) < 248)
    return nonwhite / len(pixels) if pixels else 0.0


def render(*, evaluation: Mapping[str, Any], artifact: Mapping[str, Any], output_dir: Path) -> dict[str, Any]:
    figures = output_dir / "figures"
    sources = output_dir / "source_data"
    figures.mkdir(parents=True, exist_ok=True)
    sources.mkdir(parents=True, exist_ok=True)

    result_rows = list(evaluation.get("results") or [])
    selected = str(evaluation.get("selected_trial") or "")
    result_rows.sort(key=lambda row: float((row.get("candidate_config") or {}).get("activity_threshold_fc", 0.0)))
    candidate_rows = []
    for row in result_rows:
        metrics = dict(row.get("metrics") or {})
        config = dict(row.get("candidate_config") or {})
        candidate_rows.append(
            {
                "trial_id": row.get("trial_id"),
                "selected": str(row.get("trial_id")) == selected,
                "activity_threshold_fc": config.get("activity_threshold_fc"),
                **metrics,
                "adoption_passed": (row.get("adoption_gate") or {}).get("passed"),
            }
        )
    _write_tsv(
        sources / "TF1_candidate_comparison.tsv",
        candidate_rows,
        [
            "trial_id", "selected", "activity_threshold_fc", "objective", "mean_pair_loto_jaccard",
            "mean_site_loto_jaccard", "local_active_pair_coverage", "transition_resolution",
            "transition_supported_wave_count", "cross_layer_temporal_alignment_count",
            "cross_layer_temporal_alignment_fraction", "full_pair_transition_count", "adoption_passed",
        ],
    )

    dynamic = dict((artifact.get("v2_extensions") or {}).get("dynamic_co_wave_transition") or {})
    summary = dict(dynamic.get("summary") or {})
    lotto = dict(dynamic.get("lotto") or {})
    folds = list(lotto.get("folds") or [])
    _write_tsv(
        sources / "TF2_loto_stability.tsv",
        folds,
        ["dropped_timepoint", "comparable_pair_transition_count", "comparable_site_transition_count", "pair_transition_jaccard", "site_transition_jaccard"],
    )
    wave_rows = list(dynamic.get("per_wave_summary") or [])
    event_types = sorted(
        {
            event_type
            for row in wave_rows
            for event_type in dict(row.get("pair_transition_type_counts") or {})
        }
    )
    wave_source_rows = []
    for row in wave_rows:
        for event_type in event_types:
            wave_source_rows.append(
                {
                    "static_wave_id": row.get("static_wave_id"),
                    "transition_type": event_type,
                    "pair_transition_count": (row.get("pair_transition_type_counts") or {}).get(event_type, 0),
                    "site_transition_count": (row.get("site_transition_type_counts") or {}).get(event_type, 0),
                    "nonpersistence_pair_transition_count": row.get("nonpersistence_pair_transition_count"),
                }
            )
    _write_tsv(
        sources / "TF3_wave_transition_composition.tsv",
        wave_source_rows,
        ["static_wave_id", "transition_type", "pair_transition_count", "site_transition_count", "nonpersistence_pair_transition_count"],
    )
    global_rows = [
        {"metric": "static_wave_member_count", "value": summary.get("static_wave_member_count"), "unit": "sites"},
        {"metric": "local_window_count", "value": summary.get("local_window_count"), "unit": "adjacent intervals"},
        {"metric": "local_active_pair_coverage", "value": summary.get("local_active_pair_coverage"), "unit": "fraction"},
        {"metric": "transition_resolution", "value": summary.get("transition_resolution"), "unit": "fraction"},
        {"metric": "transition_supported_wave_count", "value": summary.get("transition_supported_wave_count"), "unit": "Waves"},
        {"metric": "mean_pair_loto_jaccard", "value": lotto.get("mean_pair_transition_jaccard"), "unit": "fraction"},
        {"metric": "mean_site_loto_jaccard", "value": lotto.get("mean_site_transition_jaccard"), "unit": "fraction"},
    ]
    _write_tsv(sources / "TF4_truth_free_summary.tsv", global_rows, ["metric", "value", "unit"])

    labels = [f"{row['activity_threshold_fc']:.2f}" for row in candidate_rows]
    selected_index = next(index for index, row in enumerate(candidate_rows) if row["selected"])
    bar_colors = [PALETTE["gold"] if row["selected"] else PALETTE["blue"] for row in candidate_rows]
    combined_pdf_path = output_dir / "dynamic_cowave_truth_free_figures.pdf"
    with PdfPages(combined_pdf_path) as pdf:
        fig, axes = plt.subplots(2, 2, figsize=(12, 8))
        _figure_style(fig, "TF1 | Preregistered dynamic co-wave candidate comparison", "Truth-free numeric evaluation; selected threshold is highlighted. Objective uses prespecified weights.")
        plots = [
            ("Objective", "objective", (0, 0.75)),
            ("LOTO pair Jaccard", "mean_pair_loto_jaccard", (0, 1.05)),
            ("Local active-pair coverage", "local_active_pair_coverage", (0, 0.45)),
            ("Transition resolution", "transition_resolution", (0, 1.05)),
        ]
        for axis, (title, key, limits) in zip(axes.flat, plots):
            values = [float(row[key]) for row in candidate_rows]
            axis.bar(labels, values, color=bar_colors, width=0.58, zorder=3)
            axis.set_title(title, loc="left", fontsize=11, fontweight="bold", color=PALETTE["ink"])
            axis.set_xlabel("Activity threshold |log2FC|", fontsize=9)
            axis.set_ylim(*limits)
            _axis_style(axis)
            for index, value in enumerate(values):
                axis.text(index, value + (limits[1] * 0.025), f"{value:.3f}", ha="center", va="bottom", fontsize=8, color=PALETTE["ink"])
        axes.flat[0].text(selected_index, 0.03, "selected", ha="center", va="bottom", fontsize=8, fontweight="bold", color=PALETTE["gold"])
        fig.tight_layout(rect=(0, 0, 1, 0.87))
        _save_figure(fig, figures / "TF1_candidate_comparison", pdf)

        fig, axis = plt.subplots(figsize=(12, 6))
        _figure_style(fig, "TF2 | Leave-one-timepoint-out stability of selected transition annotation", "Jaccard overlap is computed only on comparable event identities after the indicated timepoint is omitted.")
        fold_labels = [str(row.get("dropped_timepoint")) for row in folds]
        pair_values = [float(row.get("pair_transition_jaccard") or 0.0) for row in folds]
        site_values = [float(row.get("site_transition_jaccard") or 0.0) for row in folds]
        axis.plot(fold_labels, pair_values, marker="o", linewidth=2.6, color=PALETTE["blue"], label="Pair-transition Jaccard")
        axis.plot(fold_labels, site_values, marker="o", linewidth=2.6, color=PALETTE["teal"], label="Site-transition Jaccard")
        axis.axhline(float(lotto.get("mean_pair_transition_jaccard") or 0), color=PALETTE["blue"], linestyle="--", linewidth=1.2, alpha=0.8)
        axis.axhline(float(lotto.get("mean_site_transition_jaccard") or 0), color=PALETTE["teal"], linestyle="--", linewidth=1.2, alpha=0.8)
        axis.set_ylim(0, 1.05)
        axis.set_xlabel("Omitted timepoint", fontsize=10)
        axis.set_ylabel("Comparable-event Jaccard overlap", fontsize=10)
        axis.legend(frameon=False, loc="lower left")
        _axis_style(axis)
        axis.text(0.99, 0.08, f"mean pair = {lotto.get('mean_pair_transition_jaccard', 0):.3f}\nmean site = {lotto.get('mean_site_transition_jaccard', 0):.3f}", transform=axis.transAxes, ha="right", va="bottom", fontsize=9, color=PALETTE["ink"])
        fig.tight_layout(rect=(0, 0, 1, 0.87))
        _save_figure(fig, figures / "TF2_loto_stability", pdf)

        fig, axis = plt.subplots(figsize=(12, 7))
        _figure_style(fig, "TF3 | Within-static-Wave local co-movement transition composition", "Complete pair-transition aggregates are shown; no pair-level examples are used for these counts.")
        wave_labels = [str(row.get("static_wave_id")) for row in wave_rows]
        bottoms = [0] * len(wave_rows)
        for event_type in event_types:
            values = [int((row.get("pair_transition_type_counts") or {}).get(event_type, 0)) for row in wave_rows]
            axis.barh(wave_labels, values, left=bottoms, color=EVENT_COLORS.get(event_type, EVENT_COLORS["unknown"]), label=event_type.replace("_", " "), height=0.65)
            bottoms = [left + value for left, value in zip(bottoms, values)]
        axis.set_xlabel("Complete pair-transition count", fontsize=10)
        axis.set_ylabel("Immutable static Wave", fontsize=10)
        axis.legend(ncol=max(1, min(5, len(event_types))), frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.12))
        _axis_style(axis)
        fig.tight_layout(rect=(0, 0.05, 1, 0.87))
        _save_figure(fig, figures / "TF3_wave_transition_composition", pdf)

        fig, axes = plt.subplots(1, 2, figsize=(12, 6))
        _figure_style(fig, "TF4 | Truth-free evidence scale and retained observational scope", "Dynamic transitions prioritize time-resolved hypotheses; they do not constitute kinase attribution or causal proof.")
        fraction_metrics = [
            ("Pair\nLOTO", float(lotto.get("mean_pair_transition_jaccard") or 0), PALETTE["blue"]),
            ("Site\nLOTO", float(lotto.get("mean_site_transition_jaccard") or 0), PALETTE["teal"]),
            ("Active-pair\ncoverage", float(summary.get("local_active_pair_coverage") or 0), PALETTE["gold"]),
            ("Transition\nresolution", float(summary.get("transition_resolution") or 0), PALETTE["coral"]),
            ("Cross-layer\nalignment", float(candidate_rows[selected_index]["cross_layer_temporal_alignment_fraction"] or 0), "#8d6f9e"),
        ]
        axes[0].bar([item[0] for item in fraction_metrics], [item[1] for item in fraction_metrics], color=[item[2] for item in fraction_metrics], zorder=3)
        axes[0].set_ylim(0, 1.05)
        axes[0].set_ylabel("Fraction", fontsize=10)
        axes[0].set_title("Predefined truth-free metrics", loc="left", fontsize=11, fontweight="bold", color=PALETTE["ink"])
        _axis_style(axes[0])
        for index, (_, value, _) in enumerate(fraction_metrics):
            axes[0].text(index, value + 0.025, f"{value:.3f}", ha="center", va="bottom", fontsize=8)
        count_labels = ["Static\nWave members", "Local\nwindows", "Transition\nWaves", "Pair\ntransitions", "Site\ntransitions"]
        count_values = [
            int(summary.get("static_wave_member_count") or 0),
            int(summary.get("local_window_count") or 0),
            int(summary.get("transition_supported_wave_count") or 0),
            int(summary.get("pair_transition_count") or 0),
            int(summary.get("site_transition_count") or 0),
        ]
        axes[1].bar(count_labels, count_values, color=[PALETTE["grey"], PALETTE["grey"], PALETTE["teal"], PALETTE["blue"], PALETTE["coral"]], zorder=3)
        axes[1].set_yscale("log")
        axes[1].set_ylabel("Count (log scale)", fontsize=10)
        axes[1].set_title("Complete numerical evidence scale", loc="left", fontsize=11, fontweight="bold", color=PALETTE["ink"])
        _axis_style(axes[1])
        for index, value in enumerate(count_values):
            axes[1].text(index, value * 1.25, f"{value:,}", ha="center", va="bottom", fontsize=8)
        fig.tight_layout(rect=(0, 0, 1, 0.87))
        _save_figure(fig, figures / "TF4_truth_free_evidence_scale", pdf)

    png_paths = sorted(figures.glob("*.png"))
    qc = {
        "schema_version": "dynamic_cowave_truth_free_figure_qc.v1",
        "truth_free_inputs_only": True,
        "figures": [
            {
                "file": path.name,
                "pixel_dimensions": list(Image.open(path).size),
                "nonwhite_pixel_fraction": _nonempty_fraction(path),
                "passed_nonempty": _nonempty_fraction(path) >= 0.01,
            }
            for path in png_paths
        ],
        "combined_pdf": combined_pdf_path.name,
    }
    qc["passed"] = all(row["passed_nonempty"] for row in qc["figures"])
    (output_dir / "figure_raster_qc.json").write_text(json.dumps(qc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    metadata = {
        "schema_version": "dynamic_cowave_truth_free_publication_bundle.v1",
        "selection_boundary": evaluation.get("preregistration", {}).get("selection_boundary"),
        "selected_trial": selected,
        "figure_count": len(png_paths),
        "source_tables": sorted(path.name for path in sources.glob("*.tsv")),
        "raster_qc_passed": qc["passed"],
    }
    (output_dir / "bundle_manifest.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", required=True, help="Truth-free dynamic candidate evaluation JSON.")
    parser.add_argument("--artifact", required=True, help="Truth-free final dynamic analysis artifact JSON.")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    result = render(
        evaluation=_load_json(Path(args.evaluation)),
        artifact=_load_json(Path(args.artifact)),
        output_dir=Path(args.output_dir),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
