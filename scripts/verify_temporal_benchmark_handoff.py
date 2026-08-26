#!/usr/bin/env python3
"""Verify a completed optimized temporal benchmark artifact on a target server.

The verifier reads only the truth-free artifact and an optional already-created
locked score result. It never opens the runner-only reference workbook.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from ptm_shared.temporal_optimization_config import (
    CONFIG_SHA256,
    CONTRACT_VERSION,
    SELECTION_RECORD_SHA256,
    TMM_CONFIG,
    WAVE_CONFIG,
)


def _read(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _close(left: object, right: object, tolerance: float = 1e-9) -> bool:
    try:
        return math.isclose(float(left), float(right), abs_tol=tolerance, rel_tol=tolerance)
    except (TypeError, ValueError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--locked-score")
    parser.add_argument("--output")
    parser.add_argument("--expect-sites", type=int, default=2447)
    parser.add_argument("--expect-waves", type=int, default=8)
    parser.add_argument("--expect-tmm-profiles", type=int, default=55)
    parser.add_argument("--expect-contribution-sites", type=int, default=4486)
    parser.add_argument("--expect-cascade-timepoints", type=int, default=6)
    args = parser.parse_args()

    artifact = _read(args.artifact)
    temporal = artifact.get("temporal_wave_contract") or {}
    provenance = temporal.get("threshold_provenance") or {}
    tmm = artifact.get("tmm_full_temporal") or {}
    tmm_config = tmm.get("tmm_config") or {}
    cascade = tmm.get("tmm_weighted_temporal_cascade") or {}
    profile_count = sum(
        1 for row in tmm.get("kinase_scores") or []
        if row.get("tmm_profile_type")
    )

    checks = {
        "contract_version": provenance.get("threshold_source") == CONTRACT_VERSION,
        "wave_correlation_threshold": _close(provenance.get("correlation_threshold"), WAVE_CONFIG["correlation_threshold"]),
        "wave_minimum_amplitude": _close(provenance.get("minimum_amplitude"), WAVE_CONFIG["minimum_amplitude"]),
        "tmm_config": all(
            _close(tmm_config.get(key), value) if isinstance(value, (int, float)) else tmm_config.get(key) == value
            for key, value in TMM_CONFIG.items()
        ),
        "site_count": len(artifact.get("site_availability") or []) == args.expect_sites,
        "wave_count": len(temporal.get("waves") or []) == args.expect_waves,
        "all_sites_sequence_isoform_species_mapped": all(
            (row.get("mapping_evidence") or {}).get("method") == "sequence_isoform_species"
            for row in artifact.get("site_availability") or []
        ),
        "tmm_profiles": profile_count == args.expect_tmm_profiles,
        "contribution_sites": len(tmm.get("tmm_site_contribution_matrix") or {}) == args.expect_contribution_sites,
        "cascade_timepoints": len(cascade.get("timepoints") or []) == args.expect_cascade_timepoints,
    }

    locked_summary = None
    if args.locked_score:
        locked = _read(args.locked_score)
        metrics = locked.get("metrics") or {}
        denominators = locked.get("metric_denominators") or {}
        locked_summary = {"metrics": metrics, "metric_denominators": denominators}
        checks.update({
            "locked_canonical_weighted_score": _close(metrics.get("canonical_weighted_score"), 0.7333333333333334),
            "locked_detectable_denominator": _close(denominators.get("detectable_anchor_recall"), 3.0),
            "locked_regulated_denominator": _close(denominators.get("regulated_anchor_recall"), 3.0),
        })

    report = {
        "schema_version": "temporal_benchmark_handoff_verification.v1",
        "passed": all(checks.values()),
        "checks": checks,
        "observed": {
            "runtime_config_sha256": CONFIG_SHA256,
            "selection_record_sha256": SELECTION_RECORD_SHA256,
            "sites": len(artifact.get("site_availability") or []),
            "waves": len(temporal.get("waves") or []),
            "kinase_scores": len(tmm.get("kinase_scores") or []),
            "tmm_profiles": profile_count,
            "contribution_sites": len(tmm.get("tmm_site_contribution_matrix") or {}),
            "cascade_timepoints": len(cascade.get("timepoints") or []),
            "directionality_edges": len(tmm.get("tmm_kinase_pair_directionality") or []),
        },
        "locked_score": locked_summary,
        "directionality_note": (
            "Zero eligible directionality edges is accepted for this frozen run; "
            "the populated cascade is verified separately and must not be interpreted causally."
        ),
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
