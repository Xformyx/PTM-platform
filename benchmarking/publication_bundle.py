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
    renderers = {1: _figure1_svg, 2: _figure2_svg, 3: _figure3_svg, 4: _figure4_svg}
    path.write_text(renderers[number](figure), encoding="utf-8")


def _svg_document(title: str, body: str, *, height: int = 720) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="{height}" viewBox="0 0 1280 {height}">
  <rect width="100%" height="100%" fill="#ffffff"/>
  <text x="48" y="58" font-family="Arial, sans-serif" font-size="27" font-weight="700" fill="#172033">{html.escape(title)}</text>
  <line x1="48" y1="80" x2="1232" y2="80" stroke="#cbd5e1"/>
  {body}
  <text x="48" y="{height - 28}" font-family="Arial, sans-serif" font-size="13" fill="#475569">Strict-primary blind artifact; Figure 5+ perturbation panels are intentionally excluded.</text>
</svg>'''


def _figure1_svg(figure: Mapping[str, Any]) -> str:
    timepoints = list(figure.get("timepoints") or [])
    flow = list(figure.get("analysis_flow") or [])
    x_positions = [90 + index * (1050 / max(1, len(timepoints) - 1)) for index in range(len(timepoints))]
    time_strip = "".join(f'<circle cx="{x:.1f}" cy="160" r="16" fill="#0ea5e9"/><text x="{x:.1f}" y="198" text-anchor="middle" font-family="Arial" font-size="14" fill="#172033">{html.escape(str(label))}</text>' for x, label in zip(x_positions, timepoints))
    time_line = '<line x1="90" y1="160" x2="1140" y2="160" stroke="#7dd3fc" stroke-width="4"/>' if timepoints else ""
    flow_boxes = "".join(
        f'<rect x="{48 + index * 228}" y="290" width="196" height="78" rx="10" fill="#ecfeff" stroke="#0891b2"/><text x="{146 + index * 228}" y="334" text-anchor="middle" font-family="Arial" font-size="14" fill="#0f172a">{html.escape(str(label).replace("_", " "))}</text>'
        for index, label in enumerate(flow[:5])
    )
    mapping = dict(figure.get("mapping_counts") or {})
    map_label = " · ".join(f"{key}: {value}" for key, value in mapping.items()) or "mapping audit pending"
    body = f'''
      <text x="48" y="120" font-family="Arial" font-size="17" font-weight="600" fill="#0f172a">1A · Preserved temporal axis</text>
      {time_line}{time_strip}
      <rect x="48" y="230" width="1184" height="32" rx="6" fill="#f0fdf4"/><text x="64" y="251" font-family="Arial" font-size="14" fill="#166534">Masked: treatment, exact cell line, transgene, question, RAG/LLM  |  Preserved: quantitative matrix, time, replicates, FASTA, lineage</text>
      <text x="48" y="278" font-family="Arial" font-size="17" font-weight="600" fill="#0f172a">1B–1C · Information barrier and analysis contract</text>
      {flow_boxes}
      <text x="48" y="420" font-family="Arial" font-size="17" font-weight="600" fill="#0f172a">1D · Sequence-aware mapping provenance</text>
      <rect x="48" y="440" width="1184" height="58" rx="8" fill="#f8fafc" stroke="#cbd5e1"/><text x="68" y="475" font-family="Arial" font-size="15" fill="#334155">{html.escape(map_label)}</text>
      <text x="48" y="535" font-family="Arial" font-size="14" fill="#475569">Source data: source_data/Fig1_source_data.tsv</text>'''
    return _svg_document("Figure 1 · Blind study design and temporal analysis contract", body, height=620)


def _figure2_svg(figure: Mapping[str, Any]) -> str:
    metrics = list(figure.get("panel_2a_metrics") or [])
    bars = []
    for index, row in enumerate(metrics[:6]):
        value = _number(row.get("estimate"))
        y = 145 + index * 60
        bars.append(f'<text x="58" y="{y + 16}" font-family="Arial" font-size="14" fill="#334155">{html.escape(str(row.get("label") or row.get("key")))}</text><rect x="330" y="{y}" width="700" height="24" rx="4" fill="#e2e8f0"/><rect x="330" y="{y}" width="{700 * max(0.0, min(1.0, value)):.1f}" height="24" rx="4" fill="#0ea5e9"/><text x="1050" y="{y + 17}" font-family="Arial" font-size="14" fill="#0f172a">{value:.3f}</text>')
    branches = list(figure.get("panel_2b_branches") or [])
    branch_labels = " · ".join(f"{row.get('branch')}: n={row.get('n_evaluable')}" for row in branches[:6]) or "No evaluable branch rows"
    body = f'''<text x="48" y="120" font-family="Arial" font-size="17" font-weight="600" fill="#0f172a">2A · Canonical component recovery</text>{''.join(bars)}
      <text x="48" y="540" font-family="Arial" font-size="17" font-weight="600" fill="#0f172a">2B–2D · Branch and anchor audit</text>
      <rect x="48" y="560" width="1184" height="58" rx="8" fill="#f8fafc" stroke="#cbd5e1"/><text x="68" y="595" font-family="Arial" font-size="14" fill="#334155">{html.escape(branch_labels[:175])}</text>
      <text x="48" y="660" font-family="Arial" font-size="14" fill="#475569">Source data: source_data/Fig2_source_data.tsv and source_data/Fig2_panels/*.tsv</text>'''
    return _svg_document("Figure 2 · Blind anchor recovery and temporal fidelity", body, height=720)


def _figure3_svg(figure: Mapping[str, Any]) -> str:
    profiles = list(figure.get("profiles") or [])
    aggregate: dict[str, list[float]] = {}
    for row in profiles:
        kinase = str(row.get("kinase") or "")
        aggregate.setdefault(kinase, []).append(abs(_number(row.get("tmm_weighted_score"))))
    ranked = sorted(((name, sum(values) / max(1, len(values))) for name, values in aggregate.items()), key=lambda item: item[1], reverse=True)[:8]
    maximum = max((value for _, value in ranked), default=1.0) or 1.0
    bars = "".join(f'<text x="58" y="{150 + index * 48}" font-family="Arial" font-size="14" fill="#334155">{html.escape(name)}</text><rect x="240" y="{132 + index * 48}" width="680" height="22" rx="4" fill="#e2e8f0"/><rect x="240" y="{132 + index * 48}" width="{680 * value / maximum:.1f}" height="22" rx="4" fill="#7c3aed"/><text x="940" y="{150 + index * 48}" font-family="Arial" font-size="14" fill="#0f172a">{value:.3f}</text>' for index, (name, value) in enumerate(ranked))
    contributions = list(figure.get("contributions") or [])
    body = f'''<text x="48" y="120" font-family="Arial" font-size="17" font-weight="600" fill="#0f172a">3A–3B · TMM-weighted kinase activity by observed profile</text>{bars}
      <text x="48" y="555" font-family="Arial" font-size="17" font-weight="600" fill="#0f172a">3C–3D · Shared-site fractional attribution</text>
      <rect x="48" y="575" width="1184" height="56" rx="8" fill="#faf5ff" stroke="#c4b5fd"/><text x="68" y="609" font-family="Arial" font-size="14" fill="#4c1d95">Observed contribution records: {len(contributions)} · confidence and residual details are retained in Fig3 source data.</text>
      <text x="48" y="670" font-family="Arial" font-size="14" fill="#475569">Source data: source_data/Fig3_source_data.tsv</text>'''
    return _svg_document("Figure 3 · TMM multi-kinase attribution", body, height=730)


def _figure4_svg(figure: Mapping[str, Any]) -> str:
    cascade = list(figure.get("cascade") or [])
    by_time: dict[str, list[str]] = {}
    for row in cascade:
        by_time.setdefault(str(row.get("timepoint") or "unknown"), []).append(str(row.get("kinase") or row.get("canonical") or ""))
    timepoints = list(by_time.items())
    boxes = "".join(
        f'<rect x="{58 + index * 230}" y="145" width="190" height="110" rx="10" fill="#ecfeff" stroke="#0891b2"/>'
        f'<text x="{153 + index * 230}" y="172" text-anchor="middle" font-family="Arial" font-size="15" font-weight="600" fill="#0f172a">{html.escape(timepoint)}</text>'
        f'<text x="{153 + index * 230}" y="205" text-anchor="middle" font-family="Arial" font-size="13" fill="#334155">'
        f'{html.escape(", ".join(items[:3]) or "no active kinase")}</text>'
        for index, (timepoint, items) in enumerate(timepoints[:5])
    )
    directional = list(figure.get("directionality") or [])
    body = f'''<text x="48" y="120" font-family="Arial" font-size="17" font-weight="600" fill="#0f172a">4A · Contribution-weighted observed cascade</text>{boxes}
      <text x="48" y="330" font-family="Arial" font-size="17" font-weight="600" fill="#0f172a">4B–4D · Evidence-aware temporal directionality</text>
      <rect x="48" y="350" width="1184" height="64" rx="8" fill="#f8fafc" stroke="#cbd5e1"/><text x="68" y="389" font-family="Arial" font-size="14" fill="#334155">Observed directionality relationships: {len(directional)} · multisite divergence is retained only when the artifact contains eligible pairs.</text>
      <text x="48" y="462" font-family="Arial" font-size="14" fill="#475569">Interpretation boundary: temporal precedence is observational, not causal. Source data: source_data/Fig4_source_data.tsv</text>'''
    return _svg_document("Figure 4 · Observed temporal cascade and directionality", body, height=540)


def _number(value: Any) -> float:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else 0.0
    except (TypeError, ValueError):
        return 0.0
