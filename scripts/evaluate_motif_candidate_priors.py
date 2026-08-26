#!/usr/bin/env python3
"""Truth-free grouped-replicate selection of motif-candidate prior strength."""

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


def _candidate_maps(modules):
    weights: dict[str, dict[str, float]] = {}
    hierarchy: dict[str, str] = {}
    for module in modules:
        canonical = str(module.get("canonical") or module.get("kinase") or "").upper()
        if not canonical:
            continue
        for member in module.get("members") or []:
            key = str(member.get("key") or "")
            if not key:
                continue
            probability = member.get("candidate_probability")
            if probability is not None:
                try:
                    weights.setdefault(key, {})[canonical] = max(0.0, float(probability))
                except (TypeError, ValueError):
                    pass
            hierarchy.setdefault(canonical, str(member.get("hierarchy_family") or canonical).upper())
    return weights, hierarchy


def _entries(scores):
    return [
        {
            "kinase": kinase,
            "canonical": kinase,
            "tmm_weighted_up_sums": value.get("weighted_up_sums") or {},
            "tmm_weighted_down_sums": value.get("weighted_down_sums") or {},
            "tmm_weighted_up_counts": value.get("weighted_up_counts") or {},
            "tmm_weighted_down_counts": value.get("weighted_down_counts") or {},
            "tmm_profile_type": value.get("profile_type"),
            "tmm_evidence": value.get("tmm_evidence") or {},
        }
        for kinase, value in scores.items()
    ]


def _number(value):
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _fold_metric(train_cascade, test_cascade, conditions):
    train_profiles = train_cascade.get("kinase_profiles") or {}
    test_profiles = test_cascade.get("kinase_profiles") or {}
    common = sorted(set(train_profiles) & set(test_profiles))
    rank_correlations = []
    top10_jaccards = []
    size_correlations = []
    empirical_top10 = 0
    top10_total = 0
    train_by_time = {row["timepoint"]: row for row in train_cascade.get("timepoints") or []}
    test_by_time = {row["timepoint"]: row for row in test_cascade.get("timepoints") or []}
    for condition in conditions:
        train_values = [_number(train_profiles[name].get(condition)) for name in common]
        test_values = [_number(test_profiles[name].get(condition)) for name in common]
        if len(common) >= 3 and np.std(train_values) > 0 and np.std(test_values) > 0:
            value = float(spearmanr(train_values, test_values).statistic)
            if math.isfinite(value):
                rank_correlations.append(value)
        train_rows = list((train_by_time.get(condition) or {}).get("active_kinases") or [])
        test_rows = list((test_by_time.get(condition) or {}).get("active_kinases") or [])
        train_top = {row["kinase"] for row in train_rows[:10]}
        test_top = {row["kinase"] for row in test_rows[:10]}
        union = train_top | test_top
        top10_jaccards.append(len(train_top & test_top) / len(union) if union else 1.0)
        for row in test_rows[:10]:
            top10_total += 1
            if (row.get("tmm_evidence") or {}).get("confidence_tier") == "tmm_data_anchored":
                empirical_top10 += 1
        activities = [abs(_number(row.get("selected_activity"))) for row in test_rows]
        support = [_number(row.get("evidence_mass")) for row in test_rows]
        if len(test_rows) >= 3 and np.std(activities) > 0 and np.std(support) > 0:
            value = float(spearmanr(activities, support).statistic)
            if math.isfinite(value):
                size_correlations.append(abs(value))
    return {
        "rank_correlation_mean": float(np.mean(rank_correlations)) if rank_correlations else 0.0,
        "top10_jaccard_mean": float(np.mean(top10_jaccards)) if top10_jaccards else 0.0,
        "absolute_size_correlation_median": float(np.median(size_correlations)) if size_correlations else 0.0,
        "empirical_profile_top10_fraction": empirical_top10 / top10_total if top10_total else 0.0,
    }


def _objective(folds):
    rank = float(np.mean([row["rank_correlation_mean"] for row in folds]))
    top10 = float(np.mean([row["top10_jaccard_mean"] for row in folds]))
    size_bias = float(np.mean([row["absolute_size_correlation_median"] for row in folds]))
    empirical = float(np.mean([row["empirical_profile_top10_fraction"] for row in folds]))
    return {
        "score": 0.35 * rank + 0.25 * top10 + 0.25 * (1.0 - min(1.0, size_bias)) + 0.15 * empirical,
        "rank_correlation_mean": rank,
        "top10_jaccard_mean": top10,
        "absolute_size_correlation_mean": size_bias,
        "empirical_profile_top10_fraction_mean": empirical,
        "formula": "0.35*rank + 0.25*top10_jaccard + 0.25*(1-abs_size_correlation) + 0.15*empirical_profile_fraction",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--site-level", required=True)
    parser.add_argument("--vector", required=True)
    parser.add_argument("--replay", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--strengths", default="0,0.25,0.5,1,2,5,10")
    args = parser.parse_args()

    from app.services.temporal_kinase_scoring import compute_weighted_kinase_scores

    strengths = [float(value) for value in args.strengths.split(",")]
    modules = load_candidate_modules(args.replay)
    ptm_to_kinases = build_ptm_to_kinases(modules)
    weights, hierarchy = _candidate_maps(modules)
    abundance, conditions, replicate_count = load_replicate_abundance(
        args.site_level, args.vector, aggregation="median"
    )
    folds = [
        fold_series_from_abundance(
            abundance, conditions,
            held_out_replicate=index,
            replicate_count=replicate_count,
        )
        for index in range(replicate_count)
    ]
    evaluations = []
    for strength in strengths:
        fold_metrics = []
        for fold_index, (train, test) in enumerate(folds):
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
                "candidate_prior_strength": strength,
            }
            train_scores = compute_weighted_kinase_scores(ptm_timeseries=train, **kwargs)
            test_scores = compute_weighted_kinase_scores(ptm_timeseries=test, **kwargs)
            train_cascade = build_tmm_weighted_temporal_cascade(
                _entries(train_scores), conditions,
                activity_metric="shrunken_mean", shrinkage_prior_support=10.0,
            )
            test_cascade = build_tmm_weighted_temporal_cascade(
                _entries(test_scores), conditions,
                activity_metric="shrunken_mean", shrinkage_prior_support=10.0,
            )
            fold_metrics.append({
                "fold": fold_index,
                **_fold_metric(train_cascade, test_cascade, conditions),
            })
        evaluations.append({
            "candidate_prior_strength": strength,
            "fold_metrics": fold_metrics,
            "objective": _objective(fold_metrics),
        })
    evaluations.sort(key=lambda row: row["objective"]["score"], reverse=True)
    payload = {
        "schema_version": "truth_free_motif_candidate_prior_holdout.v1",
        "candidate_calibration_contract": "motif_candidate_likelihood.v1",
        "replicate_folds": replicate_count,
        "weighted_site_count": len(weights),
        "hierarchy_kinase_count": len(hierarchy),
        "evaluations": evaluations,
        "selected": evaluations[0],
        "truth_used_for_selection": False,
    }
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
