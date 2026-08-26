#!/usr/bin/env python3
"""Evaluate cascade activity metrics without benchmark truth or identity labels."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

from ptm_shared.tmm_multikinase_integration import (
    build_tmm_kinase_pair_directionality,
    build_tmm_weighted_temporal_cascade,
)


def number(value):
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else 0.0
    except (TypeError, ValueError):
        return 0.0


def jaccard(left, right):
    union = set(left) | set(right)
    return len(set(left) & set(right)) / len(union) if union else 1.0


def evaluate(scores, conditions, metric, prior_support, threshold):
    cascade = build_tmm_weighted_temporal_cascade(
        scores,
        conditions,
        activity_metric=metric,
        shrinkage_prior_support=prior_support,
        activity_threshold=threshold,
    )
    top10_by_time = []
    active_counts = []
    size_correlations = []
    data_anchored_top10 = 0
    top10_total = 0
    for timepoint in cascade["timepoints"]:
        active = list(timepoint.get("active_kinases") or [])
        active_counts.append(len(active))
        top = active[:10]
        top10_by_time.append([row["kinase"] for row in top])
        data_anchored_top10 += sum(
            1 for row in top
            if (row.get("tmm_evidence") or {}).get("confidence_tier") == "tmm_data_anchored"
        )
        top10_total += len(top)
        activities = [abs(number(row.get("selected_activity"))) for row in active]
        support = [number(row.get("evidence_mass")) for row in active]
        if len(active) >= 3 and np.std(activities) > 0 and np.std(support) > 0:
            correlation = spearmanr(activities, support).statistic
            if math.isfinite(correlation):
                size_correlations.append(float(correlation))

    adjacent_jaccard = [jaccard(left, right) for left, right in zip(top10_by_time, top10_by_time[1:])]
    directionality = build_tmm_kinase_pair_directionality(cascade, conditions)
    return {
        "activity_metric": metric,
        "shrinkage_prior_support": prior_support,
        "activity_threshold": threshold,
        "active_counts": active_counts,
        "median_active_kinases": float(np.median(active_counts)) if active_counts else 0.0,
        "top10_distinct_kinases": len({kinase for row in top10_by_time for kinase in row}),
        "adjacent_top10_jaccard_mean": float(np.mean(adjacent_jaccard)) if adjacent_jaccard else 0.0,
        "absolute_size_correlation_median": float(np.median(np.abs(size_correlations))) if size_correlations else 0.0,
        "signed_size_correlation_median": float(np.median(size_correlations)) if size_correlations else 0.0,
        "data_anchored_top10_fraction": data_anchored_top10 / top10_total if top10_total else 0.0,
        "directionality_edge_count_exploratory": len(directionality),
        "top10_by_time": dict(zip(conditions, top10_by_time)),
        "selection_boundary": "Truth-free diagnostic only; locked metrics and identities are unavailable.",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--threshold", type=float, default=0.3)
    args = parser.parse_args()
    replay = json.loads(Path(args.replay).read_text(encoding="utf-8"))
    tmm = replay["tmm"]
    conditions = list(tmm.get("conditions") or [])
    scores = list(tmm.get("kinase_scores") or [])
    configurations = [
        ("weighted_sum", 5.0),
        ("weighted_mean", 5.0),
        ("shrunken_mean", 1.0),
        ("shrunken_mean", 2.5),
        ("shrunken_mean", 5.0),
        ("shrunken_mean", 10.0),
        ("shrunken_mean", 20.0),
    ]
    payload = {
        "schema_version": "truth_free_tmm_activity_ablation.v1",
        "conditions": conditions,
        "evaluations": [
            evaluate(scores, conditions, metric, prior, args.threshold)
            for metric, prior in configurations
        ],
    }
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
