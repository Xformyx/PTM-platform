#!/usr/bin/env python3
"""Select a cascade activity metric from grouped replicate holdouts only."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

from benchmarking.optimization_study import (
    build_ptm_to_kinases,
    fold_series_from_abundance,
    load_candidate_modules,
    load_replicate_abundance,
)
from ptm_shared.tmm_multikinase_integration import build_tmm_weighted_temporal_cascade


def _number(value):
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _jaccard(left, right):
    union = set(left) | set(right)
    return len(set(left) & set(right)) / len(union) if union else 1.0


def _fold_metric(train_cascade, test_cascade, conditions):
    train_profiles = train_cascade.get("kinase_profiles") or {}
    test_profiles = test_cascade.get("kinase_profiles") or {}
    common = sorted(set(train_profiles) & set(test_profiles))
    rank_correlations = []
    top10_jaccards = []
    size_correlations = []
    data_anchored_top10 = 0
    top10_total = 0
    train_by_time = {row["timepoint"]: row for row in train_cascade.get("timepoints") or []}
    test_by_time = {row["timepoint"]: row for row in test_cascade.get("timepoints") or []}
    for condition in conditions:
        train_values = [_number(train_profiles[name].get(condition)) for name in common]
        test_values = [_number(test_profiles[name].get(condition)) for name in common]
        if len(common) >= 3 and np.std(train_values) > 0 and np.std(test_values) > 0:
            corr = spearmanr(train_values, test_values).statistic
            if math.isfinite(corr):
                rank_correlations.append(float(corr))
        train_active = list((train_by_time.get(condition) or {}).get("active_kinases") or [])
        test_active = list((test_by_time.get(condition) or {}).get("active_kinases") or [])
        train_top = [row["kinase"] for row in train_active[:10]]
        test_top = [row["kinase"] for row in test_active[:10]]
        top10_jaccards.append(_jaccard(train_top, test_top))
        for row in test_active[:10]:
            top10_total += 1
            if (row.get("tmm_evidence") or {}).get("confidence_tier") == "tmm_data_anchored":
                data_anchored_top10 += 1
        activities = [abs(_number(row.get("selected_activity"))) for row in test_active]
        support = [_number(row.get("evidence_mass")) for row in test_active]
        if len(test_active) >= 3 and np.std(activities) > 0 and np.std(support) > 0:
            corr = spearmanr(activities, support).statistic
            if math.isfinite(corr):
                size_correlations.append(float(corr))
    return {
        "rank_correlation_mean": float(np.mean(rank_correlations)) if rank_correlations else 0.0,
        "top10_jaccard_mean": float(np.mean(top10_jaccards)) if top10_jaccards else 0.0,
        "absolute_size_correlation_median": float(np.median(np.abs(size_correlations))) if size_correlations else 0.0,
        "data_anchored_top10_fraction": data_anchored_top10 / top10_total if top10_total else 0.0,
    }


def _objective(folds):
    rank = float(np.mean([row["rank_correlation_mean"] for row in folds]))
    top10 = float(np.mean([row["top10_jaccard_mean"] for row in folds]))
    size_bias = float(np.mean([row["absolute_size_correlation_median"] for row in folds]))
    anchored = float(np.mean([row["data_anchored_top10_fraction"] for row in folds]))
    score = 0.35 * rank + 0.25 * top10 + 0.25 * (1.0 - min(1.0, size_bias)) + 0.15 * anchored
    return {
        "score": score,
        "rank_correlation_mean": rank,
        "top10_jaccard_mean": top10,
        "absolute_size_correlation_mean": size_bias,
        "data_anchored_top10_fraction_mean": anchored,
        "formula": "0.35*rank_correlation + 0.25*top10_jaccard + 0.25*(1-abs_size_correlation) + 0.15*data_anchored_top10_fraction",
    }


def _cascade_entries(scores):
    entries = []
    for kinase, value in scores.items():
        entries.append({
            "kinase": kinase,
            "canonical": kinase,
            "tmm_weighted_up_sums": value.get("weighted_up_sums") or {},
            "tmm_weighted_down_sums": value.get("weighted_down_sums") or {},
            "tmm_weighted_up_counts": value.get("weighted_up_counts") or {},
            "tmm_weighted_down_counts": value.get("weighted_down_counts") or {},
            "tmm_profile_type": value.get("profile_type"),
            "tmm_n_exclusive": value.get("n_exclusive"),
            "tmm_n_shared": value.get("n_shared"),
            "tmm_evidence": value.get("tmm_evidence") or {},
        })
    return entries


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--site-level", required=True)
    parser.add_argument("--vector", required=True)
    parser.add_argument("--replay", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    from app.services.temporal_kinase_scoring import compute_weighted_kinase_scores

    modules = load_candidate_modules(args.replay)
    ptm_to_kinases = build_ptm_to_kinases(modules)
    abundance, conditions, replicate_count = load_replicate_abundance(
        args.site_level, args.vector, aggregation="median"
    )
    fold_pairs = [
        fold_series_from_abundance(
            abundance,
            conditions,
            held_out_replicate=fold,
            replicate_count=replicate_count,
        )
        for fold in range(replicate_count)
    ]
    fold_input_counts = [
        {"fold": index, "train_sites": len(train), "test_sites": len(test)}
        for index, (train, test) in enumerate(fold_pairs)
    ]
    score_pairs = []
    for train, test in fold_pairs:
        score_pairs.append((
            compute_weighted_kinase_scores(
                modules, train, ptm_to_kinases, conditions,
                fc_threshold=0.3, q_threshold=1.0,
                profile_min_exclusive=5, gaussian_sigma_log=0.8,
                target_transform="magnitude",
            ),
            compute_weighted_kinase_scores(
                modules, test, ptm_to_kinases, conditions,
                fc_threshold=0.3, q_threshold=1.0,
                profile_min_exclusive=5, gaussian_sigma_log=0.8,
                target_transform="magnitude",
            ),
        ))
    fold_score_counts = [
        {"fold": index, "train_kinases": len(train), "test_kinases": len(test)}
        for index, (train, test) in enumerate(score_pairs)
    ]

    configurations = [
        ("weighted_sum", 5.0),
        ("weighted_mean", 5.0),
        ("shrunken_mean", 1.0),
        ("shrunken_mean", 2.5),
        ("shrunken_mean", 5.0),
        ("shrunken_mean", 10.0),
        ("shrunken_mean", 20.0),
    ]
    evaluations = []
    for metric, prior in configurations:
        folds = []
        for fold_index, (train_scores, test_scores) in enumerate(score_pairs):
            train_cascade = build_tmm_weighted_temporal_cascade(
                _cascade_entries(train_scores),
                conditions,
                activity_metric=metric,
                shrinkage_prior_support=prior,
            )
            test_cascade = build_tmm_weighted_temporal_cascade(
                _cascade_entries(test_scores),
                conditions,
                activity_metric=metric,
                shrinkage_prior_support=prior,
            )
            folds.append({"fold": fold_index, **_fold_metric(train_cascade, test_cascade, conditions)})
        evaluations.append({
            "activity_metric": metric,
            "shrinkage_prior_support": prior,
            "fold_metrics": folds,
            "objective": _objective(folds),
        })
    evaluations.sort(key=lambda row: row["objective"]["score"], reverse=True)
    payload = {
        "schema_version": "truth_free_tmm_activity_replicate_holdout.v1",
        "replicate_folds": replicate_count,
        "conditions": conditions,
        "candidate_modules": len(modules),
        "ptm_to_kinases_sites": len(ptm_to_kinases),
        "fold_input_counts": fold_input_counts,
        "fold_score_counts": fold_score_counts,
        "objective_declared_before_selection": True,
        "evaluations": evaluations,
        "selected": evaluations[0],
        "truth_used_for_selection": False,
    }
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
