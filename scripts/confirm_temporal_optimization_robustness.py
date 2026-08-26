#!/usr/bin/env python3
"""Confirm a truth-free selected temporal configuration on independent subsets.

The script never reads locked benchmark truth.  It compares the selected Wave
configuration with current defaults on all available sites and compares TMM
settings on multiple deterministic shared-site subsets.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from benchmarking.optimization_study import (
    evaluate_tmm_configuration,
    evaluate_wave_configuration,
    fold_series_from_abundance,
    load_candidate_modules,
    load_condition_series,
    load_replicate_abundance,
    write_json,
)


def fold_pairs(vector, site_level, aggregation):
    full, conditions = load_condition_series(vector, aggregation=aggregation)
    abundance, replicate_conditions, replicate_count = load_replicate_abundance(
        site_level,
        vector,
        aggregation="median" if aggregation == "legacy_last" else aggregation,
    )
    if conditions != replicate_conditions:
        raise ValueError(f"condition mismatch: {conditions} vs {replicate_conditions}")
    folds = [
        fold_series_from_abundance(
            abundance,
            conditions,
            held_out_replicate=index,
            replicate_count=replicate_count,
        )
        for index in range(replicate_count)
    ]
    return full, conditions, folds


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vector", required=True)
    parser.add_argument("--site-level", required=True)
    parser.add_argument("--replay", required=True)
    parser.add_argument("--selected-config", required=True)
    parser.add_argument("--pilot-results", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--tmm-site-limit", type=int, default=300)
    args = parser.parse_args()

    selected = json.loads(Path(args.selected_config).read_text(encoding="utf-8"))
    pilot = json.loads(Path(args.pilot_results).read_text(encoding="utf-8"))
    modules = load_candidate_modules(args.replay)

    selected_wave = dict(selected["wave"])
    selected_wave["compute_directionality"] = False
    selected_wave["threshold_source"] = "optimization_robustness.v1"
    default_wave = {
        "correlation_threshold": 0.70,
        "minimum_variance": 0.30,
        "minimum_amplitude": 0.80,
        "minimum_cluster_size": 2,
        "maximum_waves": 8,
        "compute_directionality": False,
        "threshold_source": "optimization_robustness.v1_default",
    }

    wave_candidates = [
        ("selected_median", "median", selected_wave),
        ("default_median", "median", default_wave),
        ("current_legacy_default", "legacy_last", default_wave),
    ]
    seen = {json.dumps(candidate, sort_keys=True) for _, _, candidate in wave_candidates}
    for index, row in enumerate(pilot.get("wave_results") or []):
        candidate = dict(row["config"])
        candidate["compute_directionality"] = False
        candidate["threshold_source"] = "optimization_robustness.v1_top_candidate"
        marker = json.dumps(candidate, sort_keys=True)
        if marker in seen:
            continue
        seen.add(marker)
        wave_candidates.append((f"pilot_top_{index + 1}", row["site_aggregation"], candidate))
        if len(wave_candidates) >= 6:
            break

    wave_results = []
    cache = {}
    for label, aggregation, config in wave_candidates:
        if aggregation not in cache:
            cache[aggregation] = fold_pairs(args.vector, args.site_level, aggregation)
        full, conditions, folds = cache[aggregation]
        result = evaluate_wave_configuration(full, folds, conditions, config)
        result.update({"label": label, "site_aggregation": aggregation, "evaluation_scope": "full_data"})
        wave_results.append(result)
        print(f"[robustness] wave={label} objective={result['objective']}", flush=True)
    wave_results.sort(key=lambda row: row["objective"], reverse=True)

    selected_tmm = dict(selected["tmm"])
    tmm_candidates = [
        ("selected", selected_tmm),
        ("current_default", {"profile_min_exclusive": 3, "gaussian_sigma_log": 0.6, "target_transform": "signed"}),
        ("target_transform_only", {"profile_min_exclusive": 3, "gaussian_sigma_log": 0.6, "target_transform": "magnitude"}),
        ("selected_shape_signed", {**selected_tmm, "target_transform": "signed"}),
        ("lower_exclusive_selected_shape", {**selected_tmm, "profile_min_exclusive": 3}),
    ]
    _, conditions, folds = cache.get("median") or fold_pairs(args.vector, args.site_level, "median")
    salts = ["robustness_A", "robustness_B", "robustness_C"]
    tmm_results = []
    for label, config in tmm_candidates:
        subset_results = []
        for salt in salts:
            result = evaluate_tmm_configuration(
                modules,
                folds,
                conditions,
                config,
                site_limit=args.tmm_site_limit,
                site_salt=salt,
            )
            subset_results.append(result)
        summary = {
            "label": label,
            "config": config,
            "objective_mean": float(np.mean([row["objective"] for row in subset_results])),
            "objective_min": float(np.min([row["objective"] for row in subset_results])),
            "holdout_residual_mean": float(np.mean([row["median_holdout_residual"] for row in subset_results])),
            "top1_stability_mean": float(np.mean([row["top1_stability"] for row in subset_results])),
            "profile_correlation_mean": float(np.mean([row["profile_correlation"] for row in subset_results])),
            "subset_results": subset_results,
        }
        tmm_results.append(summary)
        print(f"[robustness] tmm={label} objective_mean={summary['objective_mean']:.6f}", flush=True)
    tmm_results.sort(key=lambda row: (row["objective_mean"], row["objective_min"]), reverse=True)

    result = {
        "schema_version": "ptm_temporal_optimization_robustness.v1",
        "truth_used": False,
        "selected_config": selected,
        "wave_full_data_rankings": wave_results,
        "tmm_independent_subset_rankings": tmm_results,
        "selected_wave_rank": next(index + 1 for index, row in enumerate(wave_results) if row["label"] == "selected_median"),
        "selected_tmm_rank": next(index + 1 for index, row in enumerate(tmm_results) if row["label"] == "selected"),
    }
    write_json(args.output, result)
    print(json.dumps({
        "selected_wave_rank": result["selected_wave_rank"],
        "selected_tmm_rank": result["selected_tmm_rank"],
        "best_wave": wave_results[0]["label"],
        "best_tmm": tmm_results[0]["label"],
        "output": args.output,
    }, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
