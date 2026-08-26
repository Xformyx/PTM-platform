#!/usr/bin/env python3
"""Run the truth-free insulin raw-data optimization study.

The script name identifies the supplied dataset adapter; the objective and
algorithms remain generic and do not read the locked workbook.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmarking.optimization_study import (
    config_sha256,
    deterministic_site_sample,
    evaluate_tmm_configuration,
    evaluate_wave_configuration,
    fold_series_from_abundance,
    load_candidate_modules,
    load_condition_series,
    load_replicate_abundance,
    tmm_search_space,
    wave_search_space,
    write_json,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vector", required=True)
    parser.add_argument("--site-level", required=True)
    parser.add_argument("--replay", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--wave-random-count", type=int, default=32)
    parser.add_argument("--wave-site-limit", type=int, default=800)
    parser.add_argument("--tmm-site-limit", type=int, default=300)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    modules = load_candidate_modules(args.replay)
    all_results = {"schema_version": "ptm_parameter_optimization.v1", "truth_used_for_selection": False}

    aggregation_results = {}
    wave_results = []
    fold_pairs_by_aggregation = {}
    full_series_by_aggregation = {}
    conditions = None
    replicate_count = 0
    for aggregation in ("legacy_last", "mean", "median"):
        full_series, current_conditions = load_condition_series(args.vector, aggregation=aggregation)
        full_series_by_aggregation[aggregation] = full_series
        abundance, replicate_conditions, replicate_count = load_replicate_abundance(
            args.site_level,
            args.vector,
            aggregation="median" if aggregation == "legacy_last" else aggregation,
        )
        if current_conditions != replicate_conditions:
            raise ValueError(f"condition mismatch: {current_conditions} vs {replicate_conditions}")
        conditions = current_conditions
        fold_pairs = [
            fold_series_from_abundance(
                abundance,
                conditions,
                held_out_replicate=fold,
                replicate_count=replicate_count,
            )
            for fold in range(replicate_count)
        ]
        fold_pairs_by_aggregation[aggregation] = fold_pairs
        wave_keys = deterministic_site_sample(
            set(full_series).intersection(*(set(train) & set(test) for train, test in fold_pairs)),
            limit=args.wave_site_limit,
        )
        wave_series = {key: full_series[key] for key in wave_keys}
        wave_fold_pairs = [
            (
                {key: train[key] for key in wave_keys if key in train},
                {key: test[key] for key in wave_keys if key in test},
            )
            for train, test in fold_pairs
        ]
        aggregation_results[aggregation] = {
            "full_sites": len(full_series),
            "wave_search_sites": len(wave_keys),
            "fold_train_sites": [len(train) for train, _ in fold_pairs],
            "fold_test_sites": [len(test) for _, test in fold_pairs],
        }
        search_space = wave_search_space(random_count=args.wave_random_count)
        print(
            f"[optimization] aggregation={aggregation} wave_configs={len(search_space)} "
            f"search_sites={len(wave_keys)}",
            flush=True,
        )
        for index, config in enumerate(search_space, start=1):
            result = evaluate_wave_configuration(wave_series, wave_fold_pairs, conditions, config)
            result["site_aggregation"] = aggregation
            result["evaluation_scope"] = "deterministic_search_subset"
            result["config_sha256"] = config_sha256({**config, "site_aggregation": aggregation})
            wave_results.append(result)
            if index % 10 == 0 or index == len(search_space):
                print(
                    f"[optimization] aggregation={aggregation} wave_progress={index}/{len(search_space)}",
                    flush=True,
                )

    wave_results.sort(key=lambda item: (item["objective"], item["replicate_adjusted_rand"], item["assigned_fraction"]), reverse=True)
    best_wave = wave_results[0]
    selected_aggregation = best_wave["site_aggregation"]
    confirmation_wave_config = {
        **best_wave["config"],
        "compute_directionality": True,
        "threshold_source": "optimization_study.v1_full_confirmation",
    }
    full_wave_confirmation = evaluate_wave_configuration(
        full_series_by_aggregation[selected_aggregation],
        fold_pairs_by_aggregation[selected_aggregation],
        conditions or [],
        confirmation_wave_config,
    )
    full_wave_confirmation["site_aggregation"] = selected_aggregation
    full_wave_confirmation["evaluation_scope"] = "full_data_confirmation"
    print(
        f"[optimization] selected_wave_aggregation={selected_aggregation} "
        f"full_objective={full_wave_confirmation['objective']}",
        flush=True,
    )

    tmm_results = []
    fold_pairs = fold_pairs_by_aggregation[selected_aggregation]
    tmm_space = tmm_search_space()
    for index, config in enumerate(tmm_space, start=1):
        result = evaluate_tmm_configuration(
            modules,
            fold_pairs,
            conditions or [],
            config,
            site_limit=args.tmm_site_limit,
        )
        result["site_aggregation"] = selected_aggregation
        result["config_sha256"] = config_sha256({**config, "site_aggregation": selected_aggregation})
        tmm_results.append(result)
        if index % 10 == 0 or index == len(tmm_space):
            print(f"[optimization] tmm_progress={index}/{len(tmm_space)}", flush=True)
    tmm_results.sort(key=lambda item: (item["objective"], item["profile_correlation"], -item["median_holdout_residual"]), reverse=True)
    best_tmm = tmm_results[0]

    selected = {
        "schema_version": "ptm_selected_temporal_config.v1",
        "selection_objective": "truth_free_nested_replicate_stability_and_reconstruction",
        "truth_used_for_selection": False,
        "replicate_outer_folds": replicate_count,
        "site_aggregation": selected_aggregation,
        "wave": confirmation_wave_config,
        "tmm": best_tmm["config"],
    }
    selected["config_sha256"] = config_sha256(selected)
    all_results.update({
        "conditions": conditions,
        "replicate_count": replicate_count,
        "candidate_modules": len(modules),
        "aggregation_inventory": aggregation_results,
        "wave_results": wave_results,
        "full_wave_confirmation": full_wave_confirmation,
        "tmm_results": tmm_results,
        "selected_config": selected,
    })
    write_json(output_dir / "optimization_results.json", all_results)
    write_json(output_dir / "selected_config.json", selected)
    print(json.dumps({
        "selected_config": selected,
        "best_wave_metrics": {key: best_wave[key] for key in ("objective", "replicate_adjusted_rand", "weighted_within_wave_correlation", "assigned_fraction", "num_waves")},
        "best_tmm_metrics": {key: best_tmm[key] for key in ("objective", "median_holdout_residual", "median_equal_weight_residual", "residual_improvement", "top1_stability", "profile_correlation", "data_driven_fraction")},
        "output_dir": str(output_dir),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
