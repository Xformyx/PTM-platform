#!/usr/bin/env python3
"""Verify a completed optimized temporal benchmark artifact on a target server.

The verifier reads only the truth-free artifact and an optional already-created
locked score result. It never opens the runner-only reference workbook.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import re

from ptm_shared.temporal_optimization_config import (
    ADDITIVE_V2_CONFIG_SHA256,
    ADDITIVE_V2_CONTRACT_VERSION,
    CONFIG_SHA256,
    CONTRACT_VERSION,
    CROSS_LAYER_CONFIG,
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
    parser.add_argument("--additive-score")
    parser.add_argument("--output")
    parser.add_argument("--figures-dir")
    parser.add_argument("--source-data-dir")
    parser.add_argument("--require-additive-v2", action="store_true")
    parser.add_argument("--expect-sites", type=int, default=2447)
    parser.add_argument("--expect-waves", type=int, default=8)
    parser.add_argument("--expect-tmm-profiles", type=int, default=55)
    parser.add_argument("--expect-contribution-sites", type=int, default=2243)
    parser.add_argument("--expect-occupancy-contribution-sites", type=int, default=768)
    parser.add_argument("--expect-cascade-timepoints", type=int, default=6)
    parser.add_argument("--expect-proteins", type=int, default=8905)
    parser.add_argument("--expect-ptm-protein-pairs", type=int, default=2447)
    parser.add_argument("--expect-cross-layer-edges", type=int, default=1600)
    parser.add_argument("--expect-eligible-cross-layer-edges", type=int, default=1154)
    parser.add_argument("--expect-mechanism-chains", type=int, default=8000)
    parser.add_argument("--expect-direct-evidence-rows", type=int, default=47)
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
    sidecar = artifact.get("v2_extensions") or {}

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

    additive_summary = None
    if args.require_additive_v2:
        sidecar_provenance = sidecar.get("provenance") or {}
        cross_provenance = sidecar_provenance.get("cross_layer") or {}
        frozen = sidecar_provenance.get("frozen_config") or {}
        timing_provenance = sidecar_provenance.get("kinase_timing") or {}
        direct_audit = sidecar_provenance.get("direct_evidence_audit") or {}
        direct_linkage = sidecar_provenance.get("direct_evidence_to_tmm_linkage") or {}
        edges = list(sidecar.get("cross_layer_edges") or [])
        timing_predictions = list(sidecar.get("kinase_timing_predictions") or [])
        checks.update(
            {
                "additive_v2_schema": sidecar.get("schema_version") == "enrichment_free_temporal_mechanism.v2.sidecar",
                "additive_v2_proteins": len(sidecar.get("protein_time_series") or []) == args.expect_proteins,
                "additive_v2_ptm_protein_pairs": len(sidecar.get("ptm_protein_pairs") or []) == args.expect_ptm_protein_pairs,
                "additive_v2_cross_layer_edges": len(edges) == args.expect_cross_layer_edges,
                "additive_v2_eligible_cross_layer_edges": sum(
                    bool(row.get("eligible_for_mechanism_chain")) for row in edges
                )
                == args.expect_eligible_cross_layer_edges,
                "additive_v2_mechanism_chains": len(sidecar.get("mechanism_chains") or []) == args.expect_mechanism_chains,
                "additive_v2_counterevidence": len(sidecar.get("mechanism_counterevidence") or []) == args.expect_mechanism_chains,
                "additive_v2_direct_evidence_rows": len(sidecar.get("kinase_direct_evidence") or []) == args.expect_direct_evidence_rows,
                "additive_v2_data_anchored_timing_zero": sum(
                    bool(row.get("data_anchored")) for row in timing_predictions
                )
                == 0,
                "additive_v2_timing_not_evaluable": timing_provenance.get("data_anchored_timing_status") == "not_evaluable",
                "additive_v2_direct_linkage_not_evaluable": (
                    direct_linkage.get("timing_anchor_eligible_row_count") == 0
                    and direct_linkage.get("timing_status") == "not_evaluable"
                ),
                "additive_v2_frozen_contract": frozen.get("contract_version") == ADDITIVE_V2_CONTRACT_VERSION,
                "additive_v2_frozen_config_sha256": frozen.get("config_sha256") == ADDITIVE_V2_CONFIG_SHA256,
                "additive_v2_frozen_config_selected": frozen.get("selected_config_applied") is True,
                "additive_v2_cross_layer_config": all(
                    _close((cross_provenance.get("config") or {}).get(key), value)
                    if isinstance(value, (int, float))
                    else (cross_provenance.get("config") or {}).get(key) == value
                    for key, value in CROSS_LAYER_CONFIG.items()
                ),
                "additive_v2_truth_free_selection": (
                    sidecar_provenance.get("benchmark_truth_used") is False
                    and sidecar_provenance.get("rag_used") is False
                    and sidecar_provenance.get("llm_used") is False
                ),
                "additive_v2_protein_replicate_boundary": (
                    (sidecar_provenance.get("protein_time_series") or {}).get("replicate_values_persisted") is False
                    and cross_provenance.get("replicate_stability_status") == "unavailable_for_protein_layer"
                ),
                "additive_v2_causality_not_tested": all(
                    row.get("causality_status") == "not_tested" for row in edges
                )
                and all(
                    row.get("causality_status") == "not_tested"
                    for row in (sidecar.get("mechanism_chains") or [])
                ),
                "additive_v2_direct_source_audit_recorded": bool(direct_audit.get("evidence_summary")),
            }
        )

    if args.additive_score:
        additive = _read(args.additive_score)
        kinase_v2 = additive.get("kinase_evidence_v2") or {}
        checks.update(
            {
                "additive_score_primary_v1_unchanged": (additive.get("score_isolation") or {}).get("primary_v1_unchanged") is True,
                "additive_score_no_combined_weight": (additive.get("score_isolation") or {}).get("combined_weighted_score") is None,
                "additive_score_timing_not_evaluable": kinase_v2.get("timing_status") == "not_evaluable",
                "additive_score_timing_denominator_zero": (kinase_v2.get("metric_denominators") or {}).get("timing_accuracy_data_anchored") == 0,
                "additive_score_timing_accuracy_null": (kinase_v2.get("metrics") or {}).get("timing_accuracy_data_anchored") is None,
                "additive_score_cross_layer_missing_truth_not_failure": (additive.get("cross_layer_v2") or {}).get("status") == "not_evaluable_missing_locked_cross_layer_reference",
            }
        )
        additive_summary = {
            "kinase_evidence_v2": kinase_v2,
            "cross_layer_status": (additive.get("cross_layer_v2") or {}).get("status"),
            "mechanism_status": (additive.get("mechanism_v2") or {}).get("status"),
            "refutation_status": (additive.get("refutation_v2") or {}).get("status"),
            "score_isolation": additive.get("score_isolation"),
        }

    if args.figures_dir:
        figures_dir = Path(args.figures_dir)
        for number in (1, 2, 3, 4):
            figure_path = figures_dir / f"Fig{number}.svg"
            payload = figure_path.read_text(encoding="utf-8") if figure_path.is_file() else ""
            checks[f"fig{number}_path_outlined"] = bool(payload) and "<text" not in payload and "<path" in payload

    if args.source_data_dir and args.require_additive_v2:
        source_path = Path(args.source_data_dir) / "Fig4_source_data.tsv"
        section_counts: dict[str, int] = {}
        if source_path.is_file():
            with source_path.open("r", encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle, delimiter="\t"):
                    section = str(row.get("section") or "")
                    section_counts[section] = section_counts.get(section, 0) + 1
        checks.update(
            {
                "fig4_source_protein_time_series": section_counts.get("protein_time_series") == args.expect_proteins,
                "fig4_source_ptm_protein_pairs": section_counts.get("ptm_protein_pair") == args.expect_ptm_protein_pairs,
                "fig4_source_cross_layer_edges": section_counts.get("cross_layer_edge") == args.expect_cross_layer_edges,
                "fig4_source_direct_evidence": section_counts.get("kinase_direct_evidence") == args.expect_direct_evidence_rows,
                "fig4_source_timing_predictions": section_counts.get("kinase_timing") == len(sidecar.get("kinase_timing_predictions") or []),
                "fig4_source_mechanism_chains": section_counts.get("mechanism_chain") == args.expect_mechanism_chains,
                "fig4_source_counterevidence": section_counts.get("mechanism_counterevidence") == args.expect_mechanism_chains,
            }
        )

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
        "additive_score": additive_summary,
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
