#!/usr/bin/env python3
"""Strict-blind grouped-replicate selection of iterative TMM profiles."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

from app.services.temporal_kinase_scoring import compute_weighted_kinase_scores
from benchmarking.optimization_study import (
    build_ptm_to_kinases,
    fold_series_from_abundance,
    load_candidate_modules,
    load_replicate_abundance,
)
from scripts.evaluate_motif_candidate_priors import _candidate_maps, _entries, _fold_metric
from ptm_shared.tmm_multikinase_integration import build_tmm_weighted_temporal_cascade


def _safe_spearman(left, right):
    if len(left) < 3 or np.std(left) == 0 or np.std(right) == 0:
        return None
    value = float(spearmanr(left, right).statistic)
    return value if math.isfinite(value) else None


def _profile_stability(train_scores, test_scores, conditions):
    values = []
    for kinase in sorted(set(train_scores) & set(test_scores)):
        train = train_scores[kinase]
        test = test_scores[kinase]
        if train.get("profile_type") == "gaussian_fallback" or test.get("profile_type") == "gaussian_fallback":
            continue
        left = [float((train.get("profile_values") or {}).get(condition, 0.0)) for condition in conditions]
        right = [float((test.get("profile_values") or {}).get(condition, 0.0)) for condition in conditions]
        correlation = _safe_spearman(left, right)
        if correlation is not None:
            values.append(correlation)
    return {
        "profile_correlation_mean": float(np.mean(values)) if values else 0.0,
        "profile_correlation_count": len(values),
    }


def _reconstruction_residual(scores, series, conditions):
    by_site: dict[str, dict[str, float]] = {}
    profiles = {}
    for kinase, score in scores.items():
        profiles[kinase] = np.asarray([
            float((score.get("profile_values") or {}).get(condition, 0.0))
            for condition in conditions
        ])
        for detail in score.get("contribution_details") or []:
            ratio = detail.get("contribution_ratio")
            site = str(detail.get("ptm_key") or "")
            if site and ratio is not None:
                by_site.setdefault(site, {})[kinase] = max(0.0, float(ratio))
    residuals = []
    for site, ratios in by_site.items():
        if len(ratios) < 2 or site not in series:
            continue
        target = np.abs(np.asarray([float(series[site].get(condition, 0.0)) for condition in conditions]))
        scale = float(target.max())
        if scale <= 0:
            continue
        target = target / scale
        estimate = np.zeros(len(conditions), dtype=float)
        total = sum(ratios.values())
        if total <= 0:
            continue
        for kinase, ratio in ratios.items():
            estimate += profiles.get(kinase, np.zeros(len(conditions))) * ratio / total
        residuals.append(float(np.linalg.norm(estimate - target) / max(np.linalg.norm(target), 1e-12)))
    return {
        "reconstruction_residual_median": float(np.median(residuals)) if residuals else 1.0,
        "reconstruction_site_count": len(residuals),
    }


def _iteration_summary(scores):
    iterative = sum(1 for value in scores.values() if value.get("profile_type") == "iterative_data_assisted")
    gaussian = sum(1 for value in scores.values() if value.get("profile_type") == "gaussian_fallback")
    provenance = next(
        (value.get("iterative_profile_provenance") for value in scores.values() if value.get("iterative_profile_provenance")),
        {},
    )
    rounds = list((provenance or {}).get("rounds") or [])
    return {
        "iterative_profile_count": iterative,
        "gaussian_profile_count": gaussian,
        "gaussian_profile_fraction": gaussian / max(len(scores), 1),
        "eligible_shared_sites_last_round": int((rounds[-1] if rounds else {}).get("eligible_shared_sites") or 0),
        "completed_rounds": int((provenance or {}).get("completed_rounds") or 0),
        "stop_reason": (provenance or {}).get("stop_reason"),
    }


def _objective(folds):
    def mean(key):
        return float(np.mean([float(row[key]) for row in folds]))
    rank = mean("rank_correlation_mean")
    top10 = mean("top10_jaccard_mean")
    profile = mean("profile_correlation_mean")
    residual = mean("reconstruction_residual_median")
    size_bias = mean("absolute_size_correlation_median")
    empirical = mean("empirical_profile_top10_fraction")
    return {
        "score": 0.25 * rank + 0.15 * top10 + 0.20 * profile + 0.20 * (1.0 - min(1.0, residual)) + 0.10 * (1.0 - min(1.0, size_bias)) + 0.10 * empirical,
        "rank_correlation_mean": rank,
        "top10_jaccard_mean": top10,
        "profile_correlation_mean": profile,
        "reconstruction_residual_mean": residual,
        "absolute_size_correlation_mean": size_bias,
        "empirical_profile_top10_fraction_mean": empirical,
        "formula": "0.25*rank + 0.15*top10 + 0.20*profile_stability + 0.20*(1-residual) + 0.10*(1-size_bias) + 0.10*empirical_profile_fraction",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--site-level", required=True)
    parser.add_argument("--vector", required=True)
    parser.add_argument("--replay", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--rounds", default="0,1,2,3,5")
    parser.add_argument("--top1", default="0.7,0.8,0.9")
    args = parser.parse_args()

    rounds_values = [int(value) for value in args.rounds.split(",")]
    top1_values = [float(value) for value in args.top1.split(",")]
    modules = load_candidate_modules(args.replay)
    ptm_to_kinases = build_ptm_to_kinases(modules)
    weights, hierarchy = _candidate_maps(modules)
    abundance, conditions, replicate_count = load_replicate_abundance(args.site_level, args.vector, aggregation="median")
    replicate_folds = [
        fold_series_from_abundance(abundance, conditions, held_out_replicate=index, replicate_count=replicate_count)
        for index in range(replicate_count)
    ]
    evaluations = []
    for rounds in rounds_values:
        for top1 in top1_values:
            fold_metrics = []
            for fold_index, (train, test) in enumerate(replicate_folds):
                kwargs = {
                    "kinase_modules": modules,
                    "ptm_to_kinases": ptm_to_kinases,
                    "conditions_sorted": conditions,
                    "fc_threshold": 0.3,
                    "q_threshold": 1.0,
                    "profile_min_exclusive": 5,
                    "gaussian_sigma_log": 0.8,
                    "target_transform": "magnitude",
                    "ptm_candidate_weights": weights,
                    "kinase_hierarchy": hierarchy,
                    "candidate_prior_strength": 5.0,
                    "iterative_profile_rounds": rounds,
                    "iterative_min_top1_probability": top1,
                    "iterative_min_shared_support": 3,
                    "iterative_profile_blend": 0.5,
                }
                train_scores = compute_weighted_kinase_scores(ptm_timeseries=train, **kwargs)
                test_scores = compute_weighted_kinase_scores(ptm_timeseries=test, **kwargs)
                train_cascade = build_tmm_weighted_temporal_cascade(_entries(train_scores), conditions, activity_metric="shrunken_mean", shrinkage_prior_support=10.0)
                test_cascade = build_tmm_weighted_temporal_cascade(_entries(test_scores), conditions, activity_metric="shrunken_mean", shrinkage_prior_support=10.0)
                fold_metrics.append({
                    "fold": fold_index,
                    **_fold_metric(train_cascade, test_cascade, conditions),
                    **_profile_stability(train_scores, test_scores, conditions),
                    **_reconstruction_residual(test_scores, test, conditions),
                    **{f"train_{key}": value for key, value in _iteration_summary(train_scores).items()},
                    **{f"test_{key}": value for key, value in _iteration_summary(test_scores).items()},
                })
            evaluations.append({
                "iterative_profile_rounds": rounds,
                "minimum_top1_probability": top1,
                "fold_metrics": fold_metrics,
                "objective": _objective(fold_metrics),
            })
    evaluations.sort(key=lambda row: row["objective"]["score"], reverse=True)
    payload = {
        "schema_version": "truth_free_iterative_profile_holdout.v1",
        "candidate_prior_strength": 5.0,
        "replicate_folds": replicate_count,
        "configuration_count": len(evaluations),
        "evaluations": evaluations,
        "selected": evaluations[0],
        "truth_used_for_selection": False,
        "directionality_used_for_selection": False,
    }
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
