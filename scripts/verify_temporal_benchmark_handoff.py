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
import re

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
    parser.add_argument("--figures-dir")
    parser.add_argument("--expect-sites", type=int, default=2447)
    parser.add_argument("--expect-waves", type=int, default=8)
    parser.add_argument("--expect-tmm-profiles", type=int, default=55)
    parser.add_argument("--expect-contribution-sites", type=int, default=2243)
    parser.add_argument("--expect-occupancy-contribution-sites", type=int, default=768)
    parser.add_argument("--expect-cascade-timepoints", type=int, default=6)
    args = parser.parse_args()

    artifact = _read(args.artifact)
    temporal = artifact.get("temporal_wave_contract") or {}
    provenance = temporal.get("threshold_provenance") or {}
    tmm = artifact.get("tmm_full_temporal") or {}
    tmm_config = tmm.get("tmm_config") or {}
    cascade = tmm.get("tmm_weighted_temporal_cascade") or {}
    consensus = temporal.get("consensus_membership") or {}
    relative_matrix = tmm.get("relative_site_contribution_matrix") or {}
    occupancy_matrix = tmm.get("occupancy_site_contribution_matrix") or {}
    uncertainty = tmm.get("relative_tmm_uncertainty_summary") or {}
    directionality_gate = tmm.get("tmm_directionality_evidence_gate") or {}
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
        "consensus_wave_computed": consensus.get("status") == "computed",
        "consensus_wave_repeats": consensus.get("bootstrap_repeats") == WAVE_CONFIG["bootstrap_repeats"],
        "consensus_wave_probabilities_present": bool(consensus.get("site_membership_probabilities")),
        "wave_replicate_stability_present": all(
            ((row.get("evidence_profile") or {}).get("replicate_stability") is not None)
            for row in temporal.get("waves") or []
        ),
        "all_sites_sequence_isoform_species_mapped": all(
            (row.get("mapping_evidence") or {}).get("method") == "sequence_isoform_species"
            for row in artifact.get("site_availability") or []
        ),
        "tmm_profiles": profile_count == args.expect_tmm_profiles,
        "contribution_sites": len(relative_matrix) == args.expect_contribution_sites,
        "occupancy_contribution_sites": len(occupancy_matrix) == args.expect_occupancy_contribution_sites,
        "canonical_contribution_keys": all(
            " " not in str(key) and re.search(r"_[STY]\d+$", str(key))
            for key in relative_matrix
        ),
        "adaptive_uncertainty_present": (
            uncertainty.get("contract_version") == "adaptive_tmm_uncertainty.v1"
            and int(uncertainty.get("evaluated_unique_sites") or 0) > 0
            and int(uncertainty.get("resolved_unique_sites") or 0) > 0
        ),
        "directionality_evidence_gate_present": (
            directionality_gate.get("contract_version") == "evidence_gated_tmm_directionality.v1"
        ),
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
            "secondary_evaluation_separate": bool(locked.get("secondary_evaluation")),
        })

    if args.figures_dir:
        figures_dir = Path(args.figures_dir)
        for number in (1, 2, 3, 4):
            figure_path = figures_dir / f"Fig{number}.svg"
            payload = figure_path.read_text(encoding="utf-8") if figure_path.is_file() else ""
            checks[f"fig{number}_path_outlined"] = bool(payload) and "<text" not in payload and "<path" in payload

    report = {
        "schema_version": "temporal_benchmark_handoff_verification.v2",
        "passed": all(checks.values()),
        "checks": checks,
        "observed": {
            "runtime_config_sha256": CONFIG_SHA256,
            "selection_record_sha256": SELECTION_RECORD_SHA256,
            "sites": len(artifact.get("site_availability") or []),
            "waves": len(temporal.get("waves") or []),
            "kinase_scores": len(tmm.get("kinase_scores") or []),
            "tmm_profiles": profile_count,
            "relative_contribution_sites": len(relative_matrix),
            "occupancy_contribution_sites": len(occupancy_matrix),
            "cascade_timepoints": len(cascade.get("timepoints") or []),
            "directionality_edges": len(tmm.get("tmm_kinase_pair_directionality") or []),
            "directionality_candidates": len(tmm.get("tmm_kinase_pair_directionality_candidates") or []),
            "uncertainty_evaluated_sites": uncertainty.get("evaluated_unique_sites"),
            "uncertainty_resolved_sites": uncertainty.get("resolved_unique_sites"),
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
