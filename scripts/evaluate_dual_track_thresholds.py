#!/usr/bin/env python3
"""Select dual-track evidence thresholds without benchmark truth.

The current preprocessing artifact persists occupancy estimates at condition
level, not replicate level.  Therefore this evaluator uses leave-one-timepoint-
out stability and records that limitation explicitly rather than fabricating
replicate occupancy values.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path

import numpy as np

from ptm_shared.dual_track_evidence import build_dual_track_evidence


def _score_map(payload, field):
    value = payload.get(field) or {}
    def normalize(item):
        copied = dict(item)
        if not copied.get("weighted_up_sums") and copied.get("tmm_weighted_up_sums"):
            copied["weighted_up_sums"] = dict(copied.get("tmm_weighted_up_sums") or {})
        if not copied.get("weighted_down_sums") and copied.get("tmm_weighted_down_sums"):
            copied["weighted_down_sums"] = dict(copied.get("tmm_weighted_down_sums") or {})
        if not copied.get("contribution_details") and copied.get("tmm_top_contributions"):
            copied["contribution_details"] = list(copied.get("tmm_top_contributions") or [])
        return copied

    if isinstance(value, dict):
        return {str(key).upper(): normalize(item) for key, item in value.items() if isinstance(item, dict)}
    result = {}
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        kinase = str(item.get("canonical") or item.get("kinase") or "").upper()
        if kinase:
            result[kinase] = normalize(item)
    return result


def _drop_condition(scores, condition):
    result = {}
    for kinase, score in scores.items():
        copied = dict(score)
        for field in ("weighted_up_sums", "weighted_down_sums"):
            copied[field] = {
                key: value for key, value in (score.get(field) or {}).items()
                if key != condition
            }
        result[kinase] = copied
    return result


def _entropy(labels):
    counts = Counter(labels)
    total = sum(counts.values())
    if total <= 1:
        return 0.0
    value = -sum((count / total) * math.log(count / total) for count in counts.values())
    return value / math.log(max(len(counts), 2))


def evaluate(relative, occupancy, conditions, correlation, tolerance):
    full = build_dual_track_evidence(
        relative,
        occupancy,
        conditions,
        correlation_threshold=correlation,
        peak_index_tolerance=tolerance,
        magnitude_log2_ratio_threshold=1.0,
    )
    full_labels = {
        kinase: item["classification"]
        for kinase, item in full["by_kinase"].items()
        if item["classification"] not in {"relative_only", "occupancy_only", "dual_track_unavailable"}
    }
    per_kinase_matches = Counter()
    per_kinase_total = Counter()
    loto_summaries = []
    for omitted in conditions:
        retained = [condition for condition in conditions if condition != omitted]
        contract = build_dual_track_evidence(
            _drop_condition(relative, omitted),
            _drop_condition(occupancy, omitted),
            retained,
            correlation_threshold=correlation,
            peak_index_tolerance=tolerance,
            magnitude_log2_ratio_threshold=1.0,
        )
        matched = 0
        compared = 0
        for kinase, label in full_labels.items():
            candidate = (contract["by_kinase"].get(kinase) or {}).get("classification")
            if candidate is None:
                continue
            per_kinase_total[kinase] += 1
            compared += 1
            if candidate == label:
                per_kinase_matches[kinase] += 1
                matched += 1
        loto_summaries.append({
            "omitted_condition": omitted,
            "compared_kinases": compared,
            "classification_stability": matched / compared if compared else 0.0,
        })
    stability_values = [
        per_kinase_matches[kinase] / per_kinase_total[kinase]
        for kinase in per_kinase_total if per_kinase_total[kinase]
    ]
    labels = list(full_labels.values())
    dual_count = len(labels)
    stable_fraction = float(np.mean(stability_values)) if stability_values else 0.0
    high_stability_fraction = (
        sum(value >= 0.8 for value in stability_values) / len(stability_values)
        if stability_values else 0.0
    )
    concordant_fraction = labels.count("dual_track_concordant") / dual_count if dual_count else 0.0
    class_entropy = _entropy(labels)
    occupancy_coverage = dual_count / max(len(relative), 1)
    score = (
        0.50 * stable_fraction
        + 0.20 * high_stability_fraction
        + 0.15 * occupancy_coverage
        + 0.10 * class_entropy
        + 0.05 * (1.0 - abs(concordant_fraction - 0.5))
    )
    return {
        "correlation_threshold": correlation,
        "peak_index_tolerance": tolerance,
        "objective": {
            "score": score,
            "classification_stability_mean": stable_fraction,
            "high_stability_fraction": high_stability_fraction,
            "occupancy_coverage": occupancy_coverage,
            "class_entropy": class_entropy,
            "concordant_fraction": concordant_fraction,
            "formula": "0.50*mean_loto_stability+0.20*high_stability+0.15*occupancy_coverage+0.10*class_entropy+0.05*(1-|concordant_fraction-0.5|)",
        },
        "full_contract_summary": full["summary"],
        "loto_summaries": loto_summaries,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    payload = json.loads(Path(args.replay).read_text(encoding="utf-8"))
    tmm = payload.get("tmm") or payload
    relative = _score_map(tmm, "kinase_scores")
    occupancy = _score_map(tmm, "occupancy_tmm_scores")
    conditions = list(tmm.get("conditions") or [])
    evaluations = [
        evaluate(relative, occupancy, conditions, correlation, tolerance)
        for correlation in (0.30, 0.50, 0.70)
        for tolerance in (1, 2, 3)
    ]
    evaluations.sort(key=lambda row: row["objective"]["score"], reverse=True)
    output = {
        "schema_version": "truth_free_dual_track_threshold_selection.v1",
        "input_relative_kinases": len(relative),
        "input_occupancy_kinases": len(occupancy),
        "conditions": conditions,
        "evaluation_mode": "leave_one_timepoint_out",
        "replicate_limitation": "occupancy estimates are condition-level in the current preprocessing artifact; no replicate occupancy was fabricated",
        "evaluations": evaluations,
        "selected": evaluations[0],
        "truth_used_for_selection": False,
        "directionality_used_for_selection": False,
    }
    Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
