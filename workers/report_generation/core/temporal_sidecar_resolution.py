"""Resolve the production temporal PTM–protein sidecar for Report generation.

This module intentionally handles only user-data-derived production artifacts.
It never reads benchmark workbooks, locked benchmark scores, RAG prose, or LLM
output.  The resolver closes the DB read-after-write race between automatic RAG
analysis and the chained Report task, while also supporting report-only reruns.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from ptm_shared.temporal_sidecar_freshness import (
    compact_dynamic_is_current,
    full_dynamic_is_current,
    load_sidecar_json,
)


def _compact_sidecar(container: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a copied compact sidecar from one persisted/config container."""
    if not isinstance(container, Mapping):
        return {}
    candidate = container.get("temporal_ptm_protein_analysis")
    return dict(candidate) if isinstance(candidate, Mapping) and candidate else {}


def resolve_report_temporal_sidecar(
    *,
    db_kinase_analysis_data: Mapping[str, Any] | None,
    db_kinase_activity_heatmap: Mapping[str, Any] | None,
    config_kinase_analysis_data: Mapping[str, Any] | None,
    config_kinase_activity_heatmap: Mapping[str, Any] | None,
    artifact_paths: Iterable[Path],
) -> tuple[dict[str, Any], str, list[str]]:
    """Resolve compact temporal evidence with DB → chained config → artifact precedence.

    The chain task receives auto-analysis results in ``config`` before database
    persistence may be visible across worker connections.  A report-only rerun
    has neither such config nor necessarily a current DB projection, so it may
    recover the compact projection from the canonical full artifact.
    """
    candidates = (
        ("orders.kinase_analysis_data", db_kinase_analysis_data),
        ("orders.kinase_activity_heatmap", db_kinase_activity_heatmap),
        ("chained_report_config.kinase_analysis_data", config_kinase_analysis_data),
        ("chained_report_config.kinase_activity_heatmap", config_kinase_activity_heatmap),
    )
    diagnostics: list[str] = []
    for source, container in candidates:
        compact = _compact_sidecar(container)
        if compact and compact_dynamic_is_current(compact):
            return compact, source, diagnostics
        if compact:
            diagnostics.append(f"{source}: stale Within-Cluster Trajectory Concordance contract or config")

    seen_paths: set[Path] = set()
    for path in artifact_paths:
        if path in seen_paths:
            continue
        seen_paths.add(path)
        if not path.exists():
            continue
        try:
            full_sidecar = load_sidecar_json(path)
            if not isinstance(full_sidecar, Mapping):
                raise ValueError("full sidecar artifact must contain a JSON object")
            if not full_dynamic_is_current(full_sidecar):
                diagnostics.append(f"{path}: stale Within-Cluster Trajectory Concordance contract or config")
                continue
            from ptm_shared.enrichment_free_temporal_sidecar import (
                summarize_temporal_ptm_protein_analysis,
            )

            compact = summarize_temporal_ptm_protein_analysis(
                full_sidecar,
                artifact_path=path.name,
            )
            return compact, f"production_artifact:{path.name}", diagnostics
        except Exception as error:  # non-fatal: another source may still be valid
            diagnostics.append(f"{path}: {error}")
    return {}, "", diagnostics


def select_report_heatmap(
    *,
    db_kinase_activity_heatmap: Mapping[str, Any] | None,
    config_kinase_activity_heatmap: Mapping[str, Any] | None,
    sidecar_source: str,
) -> dict[str, Any]:
    """Select a heatmap paired with the resolved sidecar whenever possible."""
    prefer_config = sidecar_source.startswith("chained_report_config.") or sidecar_source.startswith(
        "production_artifact:"
    )
    if (
        prefer_config
        and isinstance(config_kinase_activity_heatmap, Mapping)
        and config_kinase_activity_heatmap
    ):
        return dict(config_kinase_activity_heatmap)
    if isinstance(db_kinase_activity_heatmap, Mapping) and db_kinase_activity_heatmap:
        return dict(db_kinase_activity_heatmap)
    if isinstance(config_kinase_activity_heatmap, Mapping):
        return dict(config_kinase_activity_heatmap)
    return {}
