"""Immutable JSON/TSV result-bundle writer for offline benchmark scoring."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .contracts import sha256_file
from .figure2_source import build_figure2_source, write_figure2_tsvs


def write_score_bundle(
    output_dir: str | Path,
    result: Mapping[str, Any],
    *,
    analysis_artifact_path: str | Path,
) -> dict[str, str]:
    """Persist score JSON, anchor-level TSV, and content-hash provenance."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    artifact_path = Path(analysis_artifact_path)
    enriched = dict(result)
    if "figure2" not in enriched:
        enriched["figure2"] = build_figure2_source(result)
    provenance = dict(enriched.get("provenance") or {})
    provenance.update(
        {
            "analysis_artifact_path": str(artifact_path),
            "analysis_artifact_sha256": sha256_file(artifact_path),
            "scored_at_utc": datetime.now(timezone.utc).isoformat(),
        }
    )
    enriched["provenance"] = provenance
    score_path = destination / "locked_score_result.json"
    score_path.write_text(json.dumps(enriched, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    rows = list(enriched.get("anchor_results") or [])
    tsv_path = destination / "anchor_score_table.tsv"
    headers = sorted({key for row in rows if isinstance(row, Mapping) for key in row})
    with tsv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    figure_paths = write_figure2_tsvs(destination, enriched["figure2"])
    return {"score_json": str(score_path), "anchor_tsv": str(tsv_path), **figure_paths}
