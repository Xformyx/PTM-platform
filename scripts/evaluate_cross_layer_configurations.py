#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from statistics import median
from typing import Any, Mapping

from ptm_shared.enrichment_free_temporal_sidecar import build_cross_layer_edges


AMPLITUDES = (0.30, 0.40, 0.50)
STABILITIES = (0.60, 0.75, 0.90)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


def _evaluate(task: tuple[str, float, float]) -> dict[str, Any]:
    artifact_path, amplitude, stability = task
    artifact = json.loads(Path(artifact_path).read_text(encoding="utf-8"))
    sidecar = dict(artifact.get("v2_extensions") or {})
    edges, provenance = build_cross_layer_edges(
        artifact.get("temporal_wave_contract") or {},
        sidecar.get("protein_time_series") or [],
        config={
            "minimum_absolute_change": amplitude,
            "minimum_loto_stability": stability,
            "minimum_lag_aware_similarity": 0.40,
            "maximum_candidates_per_wave": 200,
            "bootstrap_iterations": 0,
            "permutation_iterations": 0,
            "random_seed": 20260827,
        },
    )
    eligible = [row for row in edges if row.get("eligible_for_mechanism_chain")]
    loto = [
        _number((row.get("evidence_profile") or {}).get("leave_one_timepoint_stability"), float("nan"))
        for row in eligible
    ]
    loto = [value for value in loto if math.isfinite(value)]
    similarities = [
        abs(_number((row.get("lag_aware_similarity") or {}).get("best_similarity"), float("nan")))
        for row in eligible
    ]
    similarities = [value for value in similarities if math.isfinite(value)]
    non_ptm_total = sum(
        row.get("has_measured_ptm") is False
        for row in sidecar.get("protein_time_series") or []
    )
    candidate_coverage = _number(provenance.get("protein_candidate_count")) / max(1, non_ptm_total)
    eligible_fraction = len(eligible) / max(1, len(edges))
    median_loto = median(loto) if loto else 0.0
    median_similarity = median(similarities) if similarities else 0.0
    overclaim_rate = sum(row.get("causality_status") != "not_tested" for row in edges) / max(1, len(edges))
    objective = (
        0.40 * median_loto
        + 0.25 * eligible_fraction
        + 0.20 * median_similarity
        + 0.15 * candidate_coverage
        - 0.50 * overclaim_rate
    )
    return {
        "config": {
            "minimum_absolute_change": amplitude,
            "minimum_loto_stability": stability,
            "minimum_lag_aware_similarity": 0.40,
        },
        "objective": round(objective, 8),
        "retained_edge_count": len(edges),
        "mechanism_eligible_count": len(eligible),
        "eligible_fraction": round(eligible_fraction, 8),
        "median_loto_stability": round(median_loto, 8),
        "median_abs_lag_aware_similarity": round(median_similarity, 8),
        "protein_candidate_count": int(provenance.get("protein_candidate_count") or 0),
        "non_ptm_protein_count": non_ptm_total,
        "candidate_coverage": round(candidate_coverage, 8),
        "causal_overclaim_rate": round(overclaim_rate, 8),
        "replicate_stability_status": provenance.get("replicate_stability_status"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    tasks = [(args.artifact, amplitude, stability) for amplitude in AMPLITUDES for stability in STABILITIES]
    with ProcessPoolExecutor(max_workers=max(1, args.workers)) as pool:
        evaluations = list(pool.map(_evaluate, tasks))
    evaluations.sort(
        key=lambda row: (
            -row["objective"],
            row["config"]["minimum_absolute_change"],
            row["config"]["minimum_loto_stability"],
        )
    )
    payload = {
        "schema_version": "cross_layer_truth_free_optimization.v1",
        "artifact_path": str(Path(args.artifact).resolve()),
        "selection_boundary": "No workbook truth, RAG, stimulus identity, or expected mechanism labels were used.",
        "objective_definition": "0.40*median_LOTO + 0.25*eligible_fraction + 0.20*median_abs_similarity + 0.15*candidate_coverage - 0.50*causal_overclaim_rate",
        "occupancy_limitation": "Protein trajectories are condition-level in the preprocessing output; replicate-level protein stability is unavailable and must not be inferred.",
        "selected": evaluations[0] if evaluations else None,
        "evaluations": evaluations,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload["selected"], ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
