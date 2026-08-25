"""Truth-safe Figure 1–4 and source-data bundle generation for strict benchmarks.

The module receives only an already archived blind artifact, locked-score result,
and neutral run metadata.  It never reads a workbook or creates inhibitor panels.
"""

from __future__ import annotations

import csv
import html
import json
import math
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from .figure2_source import build_figure2_source, write_figure2_tsvs


FIGURE_SCOPE = {
    "included": ["Fig1", "Fig2", "Fig3", "Fig4"],
    "excluded": ["Fig5_and_later"],
    "reason": "strict_primary_has_no_inhibitor_or_perturbation_dataset",
}


def build_publication_sources(
    score_result: Mapping[str, Any],
    artifact: Mapping[str, Any],
    run_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build paper-ready source tables using only archived strict-run evidence."""

    metadata = dict(run_metadata or {})
    figure2 = score_result.get("figure2") or build_figure2_source(score_result)
    return {
        "schema_version": "ptm_benchmark_publication_bundle.v1",
        "scope": FIGURE_SCOPE,
        "figure1": _figure1_source(artifact, metadata),
        "figure2": figure2,
        "figure3": _figure3_source(artifact),
        "figure4": _figure4_source(artifact),
    }


def write_publication_bundle(output_dir: str | Path, publication: Mapping[str, Any]) -> dict[str, str]:
    """Persist separate SVG figures, TSV source sheets, and a ZIP of source sheets."""

    root = Path(output_dir)
    figures_dir = root / "figures"
    source_dir = root / "source_data"
    figures_dir.mkdir(parents=True, exist_ok=True)
    source_dir.mkdir(parents=True, exist_ok=True)

    written: dict[str, str] = {}
    figure_rows: list[dict[str, Any]] = []
    for number in (1, 2, 3, 4):
        key = f"figure{number}"
        figure = dict(publication.get(key) or {})
        source_path = source_dir / f"Fig{number}_source_data.tsv"
        _write_rows(source_path, _rows_for_figure(number, figure))
        svg_path = figures_dir / f"Fig{number}.svg"
        _write_svg(svg_path, number, figure)
        written[f"fig{number}_svg"] = str(svg_path)
        written[f"fig{number}_source_tsv"] = str(source_path)
        figure_rows.append(
            {
                "figure": f"Fig{number}",
                "svg": str(svg_path.relative_to(root)),
                "source_data": str(source_path.relative_to(root)),
                "scope": "strict_primary",
            }
        )

    # Preserve the Figure 2 panel-specific sheets for exact numeric re-use.
    figure2_paths = write_figure2_tsvs(source_dir / "Fig2_panels", dict(publication.get("figure2") or {}))
    written.update({f"fig2_{key}": value for key, value in figure2_paths.items()})
    manifest_path = root / "figure_manifest.tsv"
    _write_rows(manifest_path, figure_rows)
    written["figure_manifest"] = str(manifest_path)

    zip_path = root / "benchmark_source_data.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_dir.rglob("*.tsv")):
            archive.write(path, path.relative_to(root))
        archive.write(manifest_path, manifest_path.relative_to(root))
    written["source_data_zip"] = str(zip_path)
    return written


def _figure1_source(artifact: Mapping[str, Any], metadata: Mapping[str, Any]) -> dict[str, Any]:
    provenance = dict(artifact.get("provenance") or {})
    availability = list(artifact.get("site_availability") or [])
    mapping_counts = Counter(
        str((row.get("mapping_evidence") or {}).get("method") or "unresolved")
        for row in availability if isinstance(row, Mapping)
    )
    timepoints = list(provenance.get("timepoints") or [])
    return {
        "schema_version": "ptm_benchmark_figure1.v1",
        "timepoints": timepoints,
        "sample_count": (metadata.get("source_snapshot") or {}).get("sample_count"),
        "blind_barrier": {
            "masked": ["treatment", "source_cell_line", "transgene", "research_question", "rag", "llm"],
            "preserved": ["matrix_values", "time_axis", "replicate_structure", "fasta", "lineage_class"],
            "truth_access": "offline_scorer_only",
        },
        "analysis_flow": ["normalized_ptm", "canonical_wave", "tmm_full_temporal", "directionality_divergence", "locked_score"],
        "mapping_counts": dict(sorted(mapping_counts.items())),
        "production_contract": dict(metadata.get("production_contract") or provenance.get("production_contract") or {}),
    }


def _figure3_source(artifact: Mapping[str, Any]) -> dict[str, Any]:
    tmm = dict(artifact.get("tmm_full_temporal") or {})
    conditions = list(tmm.get("conditions") or [])
    kinase_scores = [row for row in (tmm.get("kinase_scores") or []) if isinstance(row, Mapping)]
    profiles: list[dict[str, Any]] = []
    confidence: list[dict[str, Any]] = []
    for row in kinase_scores:
        kinase = str(row.get("canonical") or row.get("kinase") or "")
        if not kinase:
            continue
        evidence = dict(row.get("tmm_evidence") or {})
        for condition in conditions:
            profiles.append(
                {
                    "kinase": kinase,
                    "condition": condition,
                    "raw_score": _number((row.get("up_sums") or {}).get(condition)) - _number((row.get("down_sums") or {}).get(condition)),
                    "tmm_weighted_score": _number((row.get("tmm_weighted_up_sums") or {}).get(condition)) - _number((row.get("tmm_weighted_down_sums") or {}).get(condition)),
                }
            )
        confidence.append(
            {
                "kinase": kinase,
                "profile_type": row.get("tmm_profile_type"),
                "n_exclusive": row.get("tmm_n_exclusive"),
                "n_shared": row.get("tmm_n_shared"),
                "tmm_evidence_json": json.dumps(evidence, sort_keys=True),
            }
        )
    contributions: list[dict[str, Any]] = []
    for site, mixture in dict(tmm.get("tmm_site_contribution_matrix") or {}).items():
        if isinstance(mixture, Mapping):
            for kinase, contribution in mixture.items():
                contributions.append({"site": site, "kinase": kinase, "fractional_contribution": contribution})
    return {
        "schema_version": "ptm_benchmark_figure3.v1",
        "profiles": profiles,
        "confidence": confidence,
        "contributions": contributions,
        "limitations": ["No locked kinase-rank recovery metric is calculated in strict-primary v1."],
    }


def _figure4_source(artifact: Mapping[str, Any]) -> dict[str, Any]:
    waves = dict(artifact.get("temporal_wave_contract") or {})
    tmm = dict(artifact.get("tmm_full_temporal") or {})
    cascade = dict(tmm.get("tmm_weighted_temporal_cascade") or {})
    directionality = list(tmm.get("tmm_kinase_pair_directionality") or [])
    wave_rows: list[dict[str, Any]] = []
    for wave in waves.get("waves") or []:
        if not isinstance(wave, Mapping):
            continue
        for site in wave.get("members") or []:
            wave_rows.append(
                {
                    "wave_id": wave.get("wave_id"),
                    "peak_timepoint": wave.get("peak_timepoint"),
                    "site": site,
                    "threshold_provenance": (waves.get("evidence_profile") or {}).get("threshold_source"),
                }
            )
    cascade_rows: list[dict[str, Any]] = []
    for timepoint in cascade.get("timepoints") or []:
        if not isinstance(timepoint, Mapping):
            continue
        for kinase in timepoint.get("active_kinases") or []:
            if isinstance(kinase, Mapping):
                cascade_rows.append({"timepoint": timepoint.get("timepoint"), **dict(kinase)})
    return {
        "schema_version": "ptm_benchmark_figure4.v1",
        "waves": wave_rows,
        "cascade": cascade_rows,
        "directionality": directionality,
        "multisite_divergence": [],
        "interpretation_boundary": "Observed temporal precedence and TMM-weighted cascade; not causal evidence.",
    }


def _rows_for_figure(number: int, figure: Mapping[str, Any]) -> list[dict[str, Any]]:
    if number == 1:
        rows = [{"section": "timepoint", "value": value} for value in figure.get("timepoints") or []]
        rows.extend({"section": "mapping_method", "value": key, "count": value} for key, value in dict(figure.get("mapping_counts") or {}).items())
        rows.extend({"section": "analysis_flow", "value": value} for value in figure.get("analysis_flow") or [])
        return rows
    if number == 2:
        return list(figure.get("panel_2a_metrics") or []) + list(figure.get("panel_2b_branches") or []) + list(figure.get("panel_2c_anchors") or [])
    if number == 3:
        return list(figure.get("profiles") or []) + list(figure.get("confidence") or []) + list(figure.get("contributions") or [])
    return list(figure.get("waves") or []) + list(figure.get("cascade") or []) + list(figure.get("directionality") or [])


def _write_rows(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    headers: list[str] = []
    for row in rows:
        for key in row:
            if key not in headers:
                headers.append(str(key))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_svg(path: Path, number: int, figure: Mapping[str, Any]) -> None:
    title = {
        1: "Figure 1 · Blind study design and temporal analysis contract",
        2: "Figure 2 · Blind anchor recovery and temporal fidelity",
        3: "Figure 3 · TMM multi-kinase attribution",
        4: "Figure 4 · Observed temporal cascade and directionality",
    }[number]
    rows = _rows_for_figure(number, figure)
    width, height = 1280, max(420, 170 + min(18, len(rows)) * 22)
    text_lines = [title, f"Strict-primary source rows: {len(rows)}", "Source data: see source_data/Fig%d_source_data.tsv" % number]
    for row in rows[:14]:
        label = " | ".join(f"{key}={value}" for key, value in row.items() if value not in (None, ""))
        text_lines.append(label[:150])
    if len(rows) > 14:
        text_lines.append(f"… {len(rows) - 14} additional rows in the source-data sheet")
    texts = "\n".join(
        f'<text x="48" y="{72 + index * 24}" font-family="Arial, sans-serif" font-size="{24 if index == 0 else 15}" fill="#172033">{html.escape(line)}</text>'
        for index, line in enumerate(text_lines)
    )
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="100%" height="100%" fill="#ffffff"/>
  <rect x="28" y="28" width="{width - 56}" height="{height - 56}" rx="12" fill="#f7fafc" stroke="#cbd5e1"/>
  {texts}
  <text x="48" y="{height - 48}" font-family="Arial, sans-serif" font-size="13" fill="#475569">Generated from immutable strict-primary artifact. No inhibitor or perturbation figure is included.</text>
</svg>'''
    path.write_text(svg, encoding="utf-8")


def _number(value: Any) -> float:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else 0.0
    except (TypeError, ValueError):
        return 0.0
