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

from .svg_text_to_path import convert_svg_text_to_paths
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from .figure2_source import build_figure2_source, write_figure2_tsvs


FIGURE_SCOPE = {
    "included": ["Fig1", "Fig2", "Fig3", "Fig4"],
    "excluded": ["Fig5_and_later"],
    "reason": "strict_primary_has_no_inhibitor_or_perturbation_dataset",
}

# SVGs are viewed outside the runner container, often by an OS previewer with
# a narrower font set than a browser.  Force a portable Latin scientific stack
# for publication figures; Korean operational copy remains in the web UI.
SVG_FONT_STACK = "'DejaVu Sans', 'Liberation Sans', sans-serif"


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
        convert_svg_text_to_paths(svg_path)
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
    input_provenance = dict(tmm.get("tmm_input_kinase_provenance") or {})
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
                "input_evidence_tier": (row.get("tmm_input_evidence") or input_provenance.get(kinase, {})).get("evidence_tier"),
                "input_sources_json": json.dumps((row.get("tmm_input_evidence") or input_provenance.get(kinase, {})).get("sources", []), sort_keys=True),
                "tmm_evidence_json": json.dumps(evidence, sort_keys=True),
            }
        )
    contributions: list[dict[str, Any]] = []
    track_matrices = {
        "relative": dict(
            tmm.get("relative_site_contribution_matrix")
            or tmm.get("tmm_site_contribution_matrix")
            or {}
        ),
        "occupancy": dict(tmm.get("occupancy_site_contribution_matrix") or {}),
    }
    for track, matrix in track_matrices.items():
        for site, mixture in matrix.items():
            if isinstance(mixture, Mapping):
                for kinase, contribution in mixture.items():
                    contributions.append({
                        "site": site,
                        "kinase": kinase,
                        "fractional_contribution": contribution,
                        "quantification_track": track,
                    })
    return {
        "schema_version": "ptm_benchmark_figure3.v3",
        "profiles": profiles,
        "confidence": confidence,
        "contributions": contributions,
        "site_contribution_track_provenance": dict(tmm.get("site_contribution_track_provenance") or {}),
        "relative_uncertainty": dict(tmm.get("relative_tmm_uncertainty_summary") or {}),
        "occupancy_uncertainty": dict(tmm.get("occupancy_tmm_uncertainty_summary") or {}),
        "dual_track_evidence": dict(tmm.get("dual_track_evidence_contract") or {}),
        "tmm_config": dict(tmm.get("tmm_config") or {}),
        "limitations": ["No locked kinase-rank recovery metric is calculated in strict-primary v1."],
    }


def _figure4_source(artifact: Mapping[str, Any]) -> dict[str, Any]:
    waves = dict(artifact.get("temporal_wave_contract") or {})
    tmm = dict(artifact.get("tmm_full_temporal") or {})
    cascade = dict(tmm.get("tmm_weighted_temporal_cascade") or {})
    directionality = list(tmm.get("tmm_kinase_pair_directionality") or [])
    directionality_candidates = list(tmm.get("tmm_kinase_pair_directionality_candidates") or [])
    directionality_gate = dict(tmm.get("tmm_directionality_evidence_gate") or {})
    consensus = dict(waves.get("consensus_membership") or {})
    sidecar = dict(artifact.get("v2_extensions") or {})
    site_probabilities = dict(consensus.get("site_membership_probabilities") or {})
    soft_threshold = _number(consensus.get("soft_membership_threshold"))
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
                    "wave_replicate_stability": (wave.get("evidence_profile") or {}).get("replicate_stability"),
                    "consensus_membership_probability": (site_probabilities.get(site) or {}).get(wave.get("wave_id")),
                    "consensus_soft_threshold": soft_threshold,
                    "consensus_member": site in set(wave.get("consensus_members") or []),
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
        "schema_version": "ptm_benchmark_figure4.v2",
        "waves": wave_rows,
        "cascade": cascade_rows,
        "directionality": directionality,
        "directionality_candidates": directionality_candidates,
        "directionality_evidence_gate": directionality_gate,
        "protein_time_series": list(sidecar.get("protein_time_series") or []),
        "ptm_protein_pairs": list(sidecar.get("ptm_protein_pairs") or []),
        "cross_layer_edges": list(sidecar.get("cross_layer_edges") or []),
        "kinase_direct_evidence": list(sidecar.get("kinase_direct_evidence") or []),
        "kinase_timing_predictions": list(sidecar.get("kinase_timing_predictions") or []),
        "mechanism_chains": list(sidecar.get("mechanism_chains") or []),
        "mechanism_counterevidence": list(sidecar.get("mechanism_counterevidence") or []),
        "v2_provenance": dict(sidecar.get("provenance") or {}),
        "consensus_membership": {
            key: value for key, value in consensus.items()
            if key != "site_membership_probabilities"
        },
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
        rows = list(figure.get("profiles") or []) + list(figure.get("confidence") or []) + list(figure.get("contributions") or [])
        rows.append({"section": "relative_uncertainty", **dict(figure.get("relative_uncertainty") or {})})
        rows.append({"section": "occupancy_uncertainty", **dict(figure.get("occupancy_uncertainty") or {})})
        rows.extend(
            {"section": "dual_track", "kinase": kinase, **dict(record)}
            for kinase, record in dict((figure.get("dual_track_evidence") or {}).get("by_kinase") or {}).items()
            if isinstance(record, Mapping)
        )
        return rows
    rows = (
        list(figure.get("waves") or [])
        + list(figure.get("cascade") or [])
        + list(figure.get("directionality") or [])
        + list(figure.get("directionality_candidates") or [])
    )
    rows.extend(
        {"section": "protein_time_series", **dict(row)}
        for row in figure.get("protein_time_series") or []
        if isinstance(row, Mapping)
    )
    rows.extend(
        {"section": "ptm_protein_pair", **dict(row)}
        for row in figure.get("ptm_protein_pairs") or []
        if isinstance(row, Mapping)
    )
    rows.extend(
        {"section": "cross_layer_edge", **dict(row)}
        for row in figure.get("cross_layer_edges") or []
        if isinstance(row, Mapping)
    )
    rows.extend(
        {"section": "kinase_direct_evidence", **dict(row)}
        for row in figure.get("kinase_direct_evidence") or []
        if isinstance(row, Mapping)
    )
    rows.extend(
        {"section": "kinase_timing", **dict(row)}
        for row in figure.get("kinase_timing_predictions") or []
        if isinstance(row, Mapping)
    )
    rows.extend(
        {"section": "mechanism_chain", **dict(row)}
        for row in figure.get("mechanism_chains") or []
        if isinstance(row, Mapping)
    )
    rows.extend(
        {"section": "mechanism_counterevidence", **dict(row)}
        for row in figure.get("mechanism_counterevidence") or []
        if isinstance(row, Mapping)
    )
    return rows


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
  <style>text{{font-family:{SVG_FONT_STACK} !important;}}</style>
  <rect width="100%" height="100%" fill="#ffffff"/>
  <text x="48" y="58" font-size="27" font-weight="700" fill="#172033">{html.escape(title)}</text>
  <line x1="48" y1="80" x2="1232" y2="80" stroke="#cbd5e1"/>
  {body}
  <text x="48" y="{height - 28}" font-size="13" fill="#475569">Strict-blind unified temporal PTM–protein artifact; Figure 5+ perturbation panels are intentionally excluded.</text>
</svg>'''


def _unavailable_panel(title: str, detail: str, *, y: int, tint: str = "#f8fafc", stroke: str = "#cbd5e1") -> str:
    """Render an honest panel when the archived artifact has no eligible data."""

    return f'''<rect x="48" y="{y}" width="1184" height="86" rx="8" fill="{tint}" stroke="{stroke}"/>
      <text x="68" y="{y + 33}" font-size="16" font-weight="600" fill="#334155">{html.escape(title)}</text>
      <text x="68" y="{y + 61}" font-size="14" fill="#475569">{html.escape(detail)}</text>'''


def _figure1_svg(figure: Mapping[str, Any]) -> str:
    timepoints = list(figure.get("timepoints") or [])
    flow = list(figure.get("analysis_flow") or [])
    x_positions = [90 + index * (1050 / max(1, len(timepoints) - 1)) for index in range(len(timepoints))]
    time_strip = "".join(f'<circle cx="{x:.1f}" cy="160" r="16" fill="#0ea5e9"/><text x="{x:.1f}" y="198" text-anchor="middle" font-size="14" fill="#172033">{html.escape(str(label))}</text>' for x, label in zip(x_positions, timepoints))
    time_line = '<line x1="90" y1="160" x2="1140" y2="160" stroke="#7dd3fc" stroke-width="4"/>' if timepoints else ""
    flow_boxes = "".join(
        f'<rect x="{48 + index * 228}" y="290" width="196" height="78" rx="10" fill="#ecfeff" stroke="#0891b2"/><text x="{146 + index * 228}" y="334" text-anchor="middle" font-size="14" fill="#0f172a">{html.escape(str(label).replace("_", " "))}</text>'
        for index, label in enumerate(flow[:5])
    )
    mapping = dict(figure.get("mapping_counts") or {})
    map_label = " · ".join(f"{key}: {value}" for key, value in mapping.items()) or "mapping audit pending"
    body = f'''
      <text x="48" y="120" font-size="17" font-weight="600" fill="#0f172a">1A · Preserved temporal axis</text>
      {time_line}{time_strip}
      <rect x="48" y="230" width="1184" height="32" rx="6" fill="#f0fdf4"/><text x="64" y="251" font-size="14" fill="#166534">Masked: treatment, exact cell line, transgene, question, RAG/LLM  |  Preserved: quantitative matrix, time, replicates, FASTA, lineage</text>
      <text x="48" y="278" font-size="17" font-weight="600" fill="#0f172a">1B–1C · Information barrier and analysis contract</text>
      {flow_boxes}
      <text x="48" y="420" font-size="17" font-weight="600" fill="#0f172a">1D · Sequence-aware mapping provenance</text>
      <rect x="48" y="440" width="1184" height="58" rx="8" fill="#f8fafc" stroke="#cbd5e1"/><text x="68" y="475" font-size="15" fill="#334155">{html.escape(map_label)}</text>
      <text x="48" y="535" font-size="14" fill="#475569">Source data: source_data/Fig1_source_data.tsv</text>'''
    return _svg_document("Figure 1 · Strict-blind integrated temporal analysis contract", body, height=620)


def _figure2_svg(figure: Mapping[str, Any]) -> str:
    metrics = list(figure.get("panel_2a_metrics") or [])
    bars = []
    for index, row in enumerate(metrics[:6]):
        value = _number(row.get("estimate"))
        y = 145 + index * 60
        bars.append(f'<text x="58" y="{y + 16}" font-size="14" fill="#334155">{html.escape(str(row.get("label") or row.get("key")))}</text><rect x="330" y="{y}" width="700" height="24" rx="4" fill="#e2e8f0"/><rect x="330" y="{y}" width="{700 * max(0.0, min(1.0, value)):.1f}" height="24" rx="4" fill="#0ea5e9"/><text x="1050" y="{y + 17}" font-size="14" fill="#0f172a">{value:.3f}</text>')
    branches = list(figure.get("panel_2b_branches") or [])
    branch_labels = " · ".join(f"{row.get('branch')}: n={row.get('n_evaluable')}" for row in branches[:6]) or "No evaluable branch rows"
    metric_panel = ''.join(bars) or _unavailable_panel("No evaluable canonical metric", "The locked scorer did not emit numeric components for this run.", y=145)
    body = f'''<text x="48" y="120" font-size="17" font-weight="600" fill="#0f172a">2A · Canonical component recovery</text>{metric_panel}
      <text x="48" y="540" font-size="17" font-weight="600" fill="#0f172a">2B–2D · Branch and anchor audit</text>
      <rect x="48" y="560" width="1184" height="58" rx="8" fill="#f8fafc" stroke="#cbd5e1"/><text x="68" y="595" font-size="14" fill="#334155">{html.escape(branch_labels[:175])}</text>
      <text x="48" y="660" font-size="14" fill="#475569">Source data: source_data/Fig2_source_data.tsv and source_data/Fig2_panels/*.tsv</text>'''
    return _svg_document("Figure 2 · Integrated blind benchmark performance", body, height=720)


def _figure3_svg(figure: Mapping[str, Any]) -> str:
    profiles = list(figure.get("profiles") or [])
    aggregate: dict[str, list[float]] = {}
    for row in profiles:
        kinase = str(row.get("kinase") or "")
        aggregate.setdefault(kinase, []).append(abs(_number(row.get("tmm_weighted_score"))))
    ranked = sorted(((name, sum(values) / max(1, len(values))) for name, values in aggregate.items()), key=lambda item: item[1], reverse=True)[:8]
    maximum = max((value for _, value in ranked), default=1.0) or 1.0
    bars = "".join(f'<text x="58" y="{150 + index * 48}" font-size="14" fill="#334155">{html.escape(name)}</text><rect x="240" y="{132 + index * 48}" width="680" height="22" rx="4" fill="#e2e8f0"/><rect x="240" y="{132 + index * 48}" width="{680 * value / maximum:.1f}" height="22" rx="4" fill="#7c3aed"/><text x="940" y="{150 + index * 48}" font-size="14" fill="#0f172a">{value:.3f}</text>' for index, (name, value) in enumerate(ranked))
    contributions = list(figure.get("contributions") or [])
    profile_panel = bars or _unavailable_panel("No eligible TMM kinase profile", "The archived strict-blind artifact has no persisted TMM kinase-score rows.", y=145, tint="#faf5ff", stroke="#c4b5fd")
    contribution_panel = (
        f'<rect x="48" y="575" width="1184" height="56" rx="8" fill="#faf5ff" stroke="#c4b5fd"/><text x="68" y="609" font-size="14" fill="#4c1d95">Observed contribution records: {len(contributions)} · confidence and residual details are retained in Fig3 source data.</text>'
        if contributions else _unavailable_panel("No shared-site TMM contribution records", "This run produced no persisted shared-site fractional attribution matrix.", y=575, tint="#faf5ff", stroke="#c4b5fd")
    )
    body = f'''<text x="48" y="120" font-size="17" font-weight="600" fill="#0f172a">3A–3B · TMM-weighted kinase activity by observed profile</text>{profile_panel}
      <text x="48" y="555" font-size="17" font-weight="600" fill="#0f172a">3C–3D · Shared-site fractional attribution</text>
      {contribution_panel}
      <text x="48" y="670" font-size="14" fill="#475569">Source data: source_data/Fig3_source_data.tsv</text>'''
    return _svg_document("Figure 3 · TMM multi-kinase attribution", body, height=730)


def _figure4_svg(figure: Mapping[str, Any]) -> str:
    cascade = list(figure.get("cascade") or [])
    by_time: dict[str, list[str]] = {}
    for row in cascade:
        by_time.setdefault(str(row.get("timepoint") or "unknown"), []).append(str(row.get("kinase") or row.get("canonical") or ""))
    timepoints = list(by_time.items())
    boxes = "".join(
        f'<rect x="{58 + index * 230}" y="145" width="190" height="110" rx="10" fill="#ecfeff" stroke="#0891b2"/>'
        f'<text x="{153 + index * 230}" y="172" text-anchor="middle" font-size="15" font-weight="600" fill="#0f172a">{html.escape(timepoint)}</text>'
        f'<text x="{153 + index * 230}" y="205" text-anchor="middle" font-size="13" fill="#334155">'
        f'{html.escape(", ".join(items[:3]) or "no active kinase")}</text>'
        for index, (timepoint, items) in enumerate(timepoints[:5])
    )
    directional = list(figure.get("directionality") or [])
    cascade_panel = boxes or _unavailable_panel("No eligible contribution-weighted cascade", "The archived artifact does not contain persisted active-kinase cascade timepoints.", y=145)
    directionality_panel = (
        f'<rect x="48" y="350" width="1184" height="64" rx="8" fill="#f8fafc" stroke="#cbd5e1"/><text x="68" y="389" font-size="14" fill="#334155">Observed directionality relationships: {len(directional)} · multisite divergence is retained only when the artifact contains eligible pairs.</text>'
        if directional else _unavailable_panel("No eligible temporal directionality relationship", "No stable kinase-pair directionality edge was persisted for this strict-blind run.", y=350)
    )
    protein_count = len(figure.get("protein_time_series") or [])
    pair_count = len(figure.get("ptm_protein_pairs") or [])
    cross_edges = list(figure.get("cross_layer_edges") or [])
    eligible_cross = sum(bool(row.get("eligible_for_mechanism_chain")) for row in cross_edges)
    mechanism_chains = list(figure.get("mechanism_chains") or [])
    supported_mechanisms = sum(
        row.get("mechanism_status") == "evidence_supported_mechanism_candidate"
        for row in mechanism_chains
    )
    timing = dict((figure.get("v2_provenance") or {}).get("kinase_timing") or {})
    timing_status = str(timing.get("data_anchored_timing_status") or "not_available")
    integrated_panel = (
        f'<rect x="48" y="500" width="1184" height="112" rx="8" fill="#f0fdf4" stroke="#16a34a"/>'
        f'<text x="68" y="530" font-size="14" font-weight="600" fill="#14532d">Integrated enrichment-free temporal evidence</text>'
        f'<text x="68" y="558" font-size="13" fill="#166534">Protein trajectories: {protein_count} · same-gene PTM–protein pairs: {pair_count} · retained cross-layer edges: {len(cross_edges)} · temporally eligible: {eligible_cross}</text>'
        f'<text x="68" y="584" font-size="13" fill="#166534">Mechanism candidates: {len(mechanism_chains)} · evidence-supported: {supported_mechanisms} · data-anchored kinase timing: {html.escape(timing_status)}</text>'
        f'<text x="68" y="604" font-size="12" fill="#475569">Evaluation components are isolated after artifact freeze; observational precedence is not causality.</text>'
        if protein_count or cross_edges or mechanism_chains
        else _unavailable_panel("No integrated enrichment-free PTM–protein evidence", "The archived artifact does not contain a persisted PTM–protein temporal extension.", y=500, tint="#f0fdf4", stroke="#16a34a")
    )
    body = f'''<text x="48" y="120" font-size="17" font-weight="600" fill="#0f172a">4A · Contribution-weighted observed cascade</text>{cascade_panel}
      <text x="48" y="330" font-size="17" font-weight="600" fill="#0f172a">4B–4D · Evidence-aware temporal directionality</text>
      {directionality_panel}
      <text x="48" y="462" font-size="14" fill="#475569">Interpretation boundary: temporal precedence is observational, not causal. Source data: source_data/Fig4_source_data.tsv</text>
      <text x="48" y="486" font-size="17" font-weight="600" fill="#0f172a">4E · Integrated PTM→protein temporal evidence</text>
      {integrated_panel}'''
    return _svg_document("Figure 4 · Integrated temporal cascade and PTM→protein evidence", body, height=670)


def _number(value: Any) -> float:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else 0.0
    except (TypeError, ValueError):
        return 0.0
