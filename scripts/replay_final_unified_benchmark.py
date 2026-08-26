"""Rebuild the final unified benchmark artifact from blinded numeric outputs.

The command intentionally accepts a previously frozen raw TMM result because the
durable benchmark worker owns annotation and TMM execution.  It recomputes the
raw-vector site observations and canonical Wave contract with the current code,
then attaches the same production/benchmark PTM–protein sidecar.  Workbook
truth is neither accepted nor read by this command.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from app.services.benchmark_artifact import build_score_artifact
from ptm_shared.temporal_optimization_config import (
    ADDITIVE_V2_CONFIG_SHA256,
    CONFIG_SHA256,
    CROSS_LAYER_CONFIG,
    SITE_AGGREGATION,
    WAVE_CONFIG,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _commit(repo: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--normalized-output-dir", required=True)
    parser.add_argument("--fasta", required=True)
    parser.add_argument(
        "--frozen-tmm-artifact",
        required=True,
        help="Truth-free benchmark artifact containing raw full TMM output; workbook truth is not read.",
    )
    parser.add_argument("--ptm-type", default="phosphorylation")
    parser.add_argument("--direct-evidence-audit")
    parser.add_argument("--direct-evidence-linkage")
    parser.add_argument("--output", required=True)
    parser.add_argument("--manifest-output", required=True)
    args = parser.parse_args()

    output_dir = Path(args.normalized_output_dir).resolve()
    fasta_path = Path(args.fasta).resolve()
    frozen_tmm_path = Path(args.frozen_tmm_artifact).resolve()
    result_path = Path(args.output).resolve()
    manifest_path = Path(args.manifest_output).resolve()
    source = json.loads(frozen_tmm_path.read_text(encoding="utf-8"))
    tmm_result: dict[str, Any] = dict(source.get("tmm_full_temporal") or source.get("tmm") or {})
    if not tmm_result:
        raise ValueError("frozen TMM artifact does not contain tmm_full_temporal or tmm")

    repo = Path(__file__).resolve().parents[1]
    artifact = build_score_artifact(
        output_dir=output_dir,
        fasta_path=fasta_path,
        ptm_type=args.ptm_type,
        production_contract={
            "contract": "tmm_full_temporal.v1",
            "code_commit": _commit(repo),
            "truth_workbook_read": False,
            "tmm_input": "frozen_raw_full_tmm_output",
            "analysis_input": "normalized_PR_PG_numeric_output",
        },
        tmm_result=tmm_result,
        wave_config=WAVE_CONFIG,
        site_aggregation=SITE_AGGREGATION,
        include_v2_extensions=True,
        cross_layer_config=CROSS_LAYER_CONFIG,
    )
    sidecar = artifact.get("v2_extensions") or {}
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
            timing["external_direct_evidence_linkage_reason"] = linkage.get("not_evaluable_reason")
    artifact["v2_extensions"] = sidecar
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    vector_path = output_dir / ("ptm_vector_data_normalized_phospho.tsv" if args.ptm_type == "phosphorylation" else "ptm_vector_data_normalized_ubi.tsv")
    protein_path = output_dir / "all_protein_level_changes_normalized_phospho.tsv"
    manifest = {
        "schema_version": "unified_benchmark_raw_vector_replay.v1",
        "truth_workbook_read": False,
        "code_commit": _commit(repo),
        "inputs": {
            "normalized_vector_sha256": _sha256(vector_path),
            "normalized_protein_sha256": _sha256(protein_path) if protein_path.is_file() else None,
            "fasta_sha256": _sha256(fasta_path),
            "frozen_tmm_artifact_sha256": _sha256(frozen_tmm_path),
        },
        "frozen_configuration": {
            "v1_config_sha256": CONFIG_SHA256,
            "additive_v2_config_sha256": ADDITIVE_V2_CONFIG_SHA256,
            "cross_layer_config": CROSS_LAYER_CONFIG,
        },
        "output_artifact_sha256": _sha256(result_path),
        "counts": {
            "site_observations": len(artifact.get("site_observations") or []),
            "waves": len((artifact.get("temporal_wave_contract") or {}).get("waves") or []),
            "protein_time_series": len((artifact.get("v2_extensions") or {}).get("protein_time_series") or []),
            "cross_layer_edges": len((artifact.get("v2_extensions") or {}).get("cross_layer_edges") or []),
            "exact_site_direct_evidence": len((artifact.get("v2_extensions") or {}).get("kinase_direct_evidence") or []),
        },
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"artifact": str(result_path), "manifest": str(manifest_path), **manifest["counts"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
