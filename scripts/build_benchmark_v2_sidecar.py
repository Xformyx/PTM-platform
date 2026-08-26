from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.benchmark_artifact import attach_v2_extensions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v1-artifact", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--ptm-type", default="phosphorylation")
    parser.add_argument("--direct-evidence-audit")
    parser.add_argument("--direct-evidence-linkage")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    artifact = json.loads(Path(args.v1_artifact).read_text(encoding="utf-8"))
    augmented = attach_v2_extensions(
        artifact,
        output_dir=Path(args.output_dir),
        ptm_type=args.ptm_type,
    )
    sidecar = augmented.get("v2_extensions") or {}
    if args.direct_evidence_audit:
        audit = json.loads(Path(args.direct_evidence_audit).read_text(encoding="utf-8"))
        sidecar["kinase_direct_evidence"] = list(audit.get("exact_site_evidence") or [])
        sidecar.setdefault("provenance", {})["direct_evidence_audit"] = {
            "schema_version": audit.get("schema_version"),
            "input": audit.get("input"),
            "query_summary": audit.get("query_summary"),
            "source_status": audit.get("source_status"),
            "evidence_summary": audit.get("evidence_summary"),
            "selection_boundary": audit.get("selection_boundary"),
        }
    if args.direct_evidence_linkage:
        linkage = json.loads(Path(args.direct_evidence_linkage).read_text(encoding="utf-8"))
        sidecar.setdefault("provenance", {})["direct_evidence_to_tmm_linkage"] = {
            key: value for key, value in linkage.items() if key != "rows"
        }
        if linkage.get("timing_anchor_eligible_row_count", 0) == 0:
            timing = sidecar.setdefault("provenance", {}).setdefault("kinase_timing", {})
            timing["external_direct_evidence_linkage_status"] = "not_evaluable"
            timing["external_direct_evidence_linkage_reason"] = linkage.get(
                "not_evaluable_reason"
            )
    augmented["v2_extensions"] = sidecar
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(augmented, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(target),
                "protein_time_series": len(sidecar.get("protein_time_series") or []),
                "ptm_protein_pairs": len(sidecar.get("ptm_protein_pairs") or []),
                "kinase_direct_evidence": len(sidecar.get("kinase_direct_evidence") or []),
                "data_anchored_timing_predictions": sum(
                    bool(row.get("data_anchored"))
                    for row in (sidecar.get("kinase_timing_predictions") or [])
                ),
                "v1_site_observations": len(augmented.get("site_observations") or []),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
