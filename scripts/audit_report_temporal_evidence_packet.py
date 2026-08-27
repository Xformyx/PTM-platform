#!/usr/bin/env python3
"""Audit the deterministic temporal numerical packet supplied to Report LLMs.

This command reads only a production/benchmark temporal artifact and never reads
the locked workbook truth, score results, RAG context, or LLM output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ptm_shared.enrichment_free_temporal_sidecar import summarize_temporal_ptm_protein_analysis
from report_generation.core.dynamic_prompt_generator import (
    build_temporal_evidence_packet,
    format_temporal_evidence_packet_for_llm,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _packet_heatmap_from_artifact(artifact: dict) -> dict:
    """Project only persisted TMM fields used by the production Report packet."""
    tmm = artifact.get("tmm_full_temporal") or artifact
    if not isinstance(tmm, dict):
        return {}
    return {
        key: tmm[key]
        for key in ("tmm_weighted_temporal_cascade", "relative_tmm_uncertainty_summary")
        if key in tmm
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    artifact = json.loads(args.artifact.read_text(encoding="utf-8"))
    sidecar = artifact.get("v2_extensions") if isinstance(artifact, dict) else None
    if not isinstance(sidecar, dict):
        sidecar = artifact if isinstance(artifact, dict) else {}
    summary = summarize_temporal_ptm_protein_analysis(
        sidecar,
        artifact_path=args.artifact.name,
    )
    heatmap = _packet_heatmap_from_artifact(artifact)
    packet = build_temporal_evidence_packet(summary, kinase_activity_heatmap=heatmap)
    formatted = format_temporal_evidence_packet_for_llm(packet, section_type="results")
    evidence_ids = [str(row.get("evidence_id")) for row in packet.get("records") or [] if isinstance(row, dict)]
    evidence_classes = {
        "dynamic": any(identifier.startswith("DATA-DYNAMIC") for identifier in evidence_ids),
        "tmm_candidate": any(identifier.startswith("DATA-TMM-KINASE") for identifier in evidence_ids),
        "tmm_uncertainty": "DATA-TMM-UNCERTAINTY" in evidence_ids,
        "cross_layer": any(identifier.startswith("DATA-CROSS-LAYER") for identifier in evidence_ids),
        "counterevidence": any(identifier.startswith("DATA-COUNTEREVIDENCE") for identifier in evidence_ids),
    }
    output = {
        "schema_version": "report_temporal_evidence_packet_audit.v2",
        "source_artifact": str(args.artifact),
        "source_artifact_sha256": _sha256(args.artifact),
        "packet": packet,
        "persisted_tmm_input": {
            "cascade_present": "tmm_weighted_temporal_cascade" in heatmap,
            "uncertainty_present": "relative_tmm_uncertainty_summary" in heatmap,
        },
        "available_evidence_classes": evidence_classes,
        "formatted_prompt_char_count": len(formatted),
        "formatted_prompt_sha256": hashlib.sha256(formatted.encode("utf-8")).hexdigest(),
        "truth_boundary": {
            "locked_workbook_read": False,
            "locked_score_read": False,
            "rag_read": False,
            "llm_called": False,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "packet_status": packet.get("status"),
        "record_count": packet.get("record_count", 0),
        "available_evidence_classes": evidence_classes,
        "formatted_prompt_char_count": len(formatted),
        "output": str(args.output),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
