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
    packet = build_temporal_evidence_packet(summary)
    formatted = format_temporal_evidence_packet_for_llm(packet)
    output = {
        "schema_version": "report_temporal_evidence_packet_audit.v1",
        "source_artifact": str(args.artifact),
        "source_artifact_sha256": _sha256(args.artifact),
        "packet": packet,
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
        "formatted_prompt_char_count": len(formatted),
        "output": str(args.output),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
