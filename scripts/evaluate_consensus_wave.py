#!/usr/bin/env python3
"""Strict-blind grouped-replicate evaluation of consensus Temporal Waves."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

from benchmarking.optimization_study import (
    adjusted_rand_index,
    fold_series_from_abundance,
    load_replicate_abundance,
)
from ptm_shared.temporal_wave_engine import analyze_temporal_waves


def _assignment(contract):
    return {
        member: wave["wave_id"]
        for wave in contract.get("waves") or []
        for member in wave.get("members") or []
    }


def _train_replicate_series(abundance, conditions, held_out, replicate_count):
    train_indices = [index for index in range(replicate_count) if index != held_out]
    result = {}
    for site, by_condition in abundance.items():
        controls = by_condition.get("Control") or by_condition.get("control") or {}
        by_time = {}
        for condition in conditions:
            observed = by_condition.get(condition) or {}
            values = []
            for index in train_indices:
                control = controls.get(index)
                value = observed.get(index)
                if control and value and control > 0 and value > 0:
                    values.append(math.log2(float(value) / float(control)))
            if values:
                by_time[condition] = values
        if len(by_time) == len(conditions):
            result[site] = by_time
    return result


def _fold_metric(train_contract, test_contract, threshold):
    train_assignment = _assignment(train_contract)
    test_assignment = _assignment(test_contract)
    hard_ari = adjusted_rand_index(train_assignment, test_assignment)
    probabilities = (train_contract.get("consensus_membership") or {}).get("site_membership_probabilities") or {}
    stable = {
        site for site, wave_id in train_assignment.items()
        if float((probabilities.get(site) or {}).get(wave_id, 0.0)) >= threshold
    }
    common = set(train_assignment) & set(test_assignment)
    stable_common = stable & common
    stable_train = {site: train_assignment[site] for site in stable_common}
    stable_test = {site: test_assignment[site] for site in stable_common}
    stable_ari = adjusted_rand_index(stable_train, stable_test) if len(stable_common) >= 2 else 0.0
    membership_values = [
        float((probabilities.get(site) or {}).get(wave_id, 0.0))
        for site, wave_id in train_assignment.items()
    ]
    consensus = train_contract.get("consensus_membership") or {}
    eligible = max(int(train_contract.get("summary", {}).get("eligible_sites") or 0), 1)
    return {
        "hard_wave_ari": hard_ari,
        "stable_core_ari": stable_ari,
        "stable_core_count": len(stable),
        "stable_core_common_count": len(stable_common),
        "stable_core_fraction": len(stable) / eligible,
        "median_hard_membership_probability": float(np.median(membership_values)) if membership_values else 0.0,
        "soft_cross_wave_rate": float(consensus.get("soft_cross_wave_member_count") or 0) / eligible,
        "usable_replicate_site_count": int(consensus.get("usable_replicate_site_count") or 0),
    }


def _objective(folds, repeats):
    stable_ari = float(np.mean([row["stable_core_ari"] for row in folds]))
    hard_ari = float(np.mean([row["hard_wave_ari"] for row in folds]))
    coverage = float(np.mean([row["stable_core_fraction"] for row in folds]))
    membership = float(np.mean([row["median_hard_membership_probability"] for row in folds]))
    overlap = float(np.mean([row["soft_cross_wave_rate"] for row in folds]))
    cost = repeats / 1000.0
    return {
        "score": 0.35 * stable_ari * math.sqrt(max(coverage, 0.0)) + 0.20 * hard_ari + 0.20 * coverage + 0.20 * membership - 0.03 * overlap - 0.02 * cost,
        "stable_core_ari_mean": stable_ari,
        "hard_wave_ari_mean": hard_ari,
        "stable_core_fraction_mean": coverage,
        "median_membership_probability_mean": membership,
        "soft_cross_wave_rate_mean": overlap,
        "bootstrap_cost_term": cost,
        "formula": "0.35*stable_ari*sqrt(coverage)+0.20*hard_ari+0.20*coverage+0.20*membership-0.03*soft_overlap-0.02*(repeats/1000)",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--site-level", required=True)
    parser.add_argument("--vector", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--repeats", type=int, required=True)
    parser.add_argument("--soft-threshold", type=float, required=True)
    args = parser.parse_args()

    abundance, conditions, replicate_count = load_replicate_abundance(args.site_level, args.vector, aggregation="median")
    fold_metrics = []
    for held_out in range(replicate_count):
        train, test = fold_series_from_abundance(
            abundance,
            conditions,
            held_out_replicate=held_out,
            replicate_count=replicate_count,
        )
        replicate_series = _train_replicate_series(abundance, conditions, held_out, replicate_count)
        config = {
            "correlation_threshold": 0.70,
            "minimum_variance": 0.30,
            "minimum_amplitude": 0.40,
            "minimum_cluster_size": 2,
            "maximum_waves": 8,
            "compute_directionality": False,
            "bootstrap_repeats": args.repeats,
            "bootstrap_seed": 1729 + held_out,
            "soft_membership_threshold": args.soft_threshold,
            "threshold_source": "strict_blind_consensus_wave_holdout.v1",
        }
        train_contract = analyze_temporal_waves(
            train,
            conditions,
            config=config,
            replicate_time_series=replicate_series,
        )
        test_contract = analyze_temporal_waves(
            test,
            conditions,
            config={**config, "bootstrap_repeats": 0},
        )
        fold_metrics.append({
            "fold": held_out,
            **_fold_metric(train_contract, test_contract, args.soft_threshold),
        })
    payload = {
        "schema_version": "truth_free_consensus_wave_holdout.v1",
        "bootstrap_repeats": args.repeats,
        "soft_membership_threshold": args.soft_threshold,
        "replicate_folds": replicate_count,
        "fold_metrics": fold_metrics,
        "objective": _objective(fold_metrics, args.repeats),
        "truth_used_for_selection": False,
        "directionality_used_for_selection": False,
    }
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
