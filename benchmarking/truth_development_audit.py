"""Runner-only safeguards for truth-based benchmark development.

This module accepts a *post-freeze locked-score result* only.  It never reads
raw matrices, analysis configuration, or a workbook, and it cannot be imported
by production analysis.  Its purpose is to prevent apparently improved scores
from being selected on an insufficient development denominator.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping


DEFAULT_ELIGIBILITY_POLICY: dict[str, int] = {
    "minimum_measurable_anchors": 8,
    "minimum_regulated_anchors": 4,
    "minimum_temporal_evaluable_anchors": 4,
    "minimum_measurable_branches": 3,
    "minimum_holdout_measurable_anchors": 2,
}


def _as_bool(value: Any) -> bool:
    return value is True or str(value).strip().lower() in {"true", "1", "yes"}


def _anchor_results(score_result: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = score_result.get("anchor_results") or []
    return [row for row in rows if isinstance(row, Mapping)]


def build_truth_development_audit(
    score_result: Mapping[str, Any],
    *,
    policy: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Summarize development eligibility from locked scoring output.

    The decision is deliberately conservative.  A score result with fewer than
    the declared measurable/regulation/temporal denominators is useful for a
    coverage diagnosis, but it is not eligible for parameter selection or a
    statistically meaningful development/holdout split.
    """

    merged_policy = {**DEFAULT_ELIGIBILITY_POLICY, **dict(policy or {})}
    rows = _anchor_results(score_result)
    measurable = [row for row in rows if _as_bool(row.get("is_measurable"))]
    regulated = [row for row in measurable if _as_bool(row.get("regulated"))]
    temporal_evaluable = [
        row
        for row in regulated
        if row.get("direction_correct") is not None or row.get("peak_window_correct") is not None
    ]
    measurable_branches = sorted(
        {
            str(row.get("branch") or "Unspecified")
            for row in measurable
        }
    )
    exclusions = Counter(
        str(row.get("exclusion_reason") or "not_excluded")
        for row in rows
        if not _as_bool(row.get("is_measurable"))
    )
    failed_requirements: list[str] = []
    if len(measurable) < merged_policy["minimum_measurable_anchors"]:
        failed_requirements.append("minimum_measurable_anchors")
    if len(regulated) < merged_policy["minimum_regulated_anchors"]:
        failed_requirements.append("minimum_regulated_anchors")
    if len(temporal_evaluable) < merged_policy["minimum_temporal_evaluable_anchors"]:
        failed_requirements.append("minimum_temporal_evaluable_anchors")
    if len(measurable_branches) < merged_policy["minimum_measurable_branches"]:
        failed_requirements.append("minimum_measurable_branches")
    holdout_eligible = (
        len(measurable) >= (
            merged_policy["minimum_measurable_anchors"]
            + merged_policy["minimum_holdout_measurable_anchors"]
        )
        and len(regulated) >= merged_policy["minimum_regulated_anchors"]
        and len(temporal_evaluable) >= merged_policy["minimum_temporal_evaluable_anchors"]
    )
    if not holdout_eligible:
        failed_requirements.append("minimum_independent_holdout")

    eligible_for_parameter_selection = not failed_requirements
    return {
        "schema_version": "ptm_truth_development_eligibility.v1",
        "boundary": {
            "truth_access": "runner_only_post_freeze_score_result",
            "analysis_access": "forbidden",
            "parameter_selection": "forbidden_when_eligibility_fails",
        },
        "policy": merged_policy,
        "counts": {
            "tier_1_2_anchor_rows": len(rows),
            "measurable_anchors": len(measurable),
            "regulated_anchors": len(regulated),
            "temporal_evaluable_anchors": len(temporal_evaluable),
            "measurable_branches": len(measurable_branches),
            "excluded_anchor_rows": len(rows) - len(measurable),
            "exclusion_reasons": dict(sorted(exclusions.items())),
        },
        "development_eligibility": {
            "eligible_for_parameter_selection": eligible_for_parameter_selection,
            "failed_requirements": failed_requirements,
            "decision": (
                "eligible_for_preregistered_development_grid"
                if eligible_for_parameter_selection
                else "coverage_diagnosis_only_no_parameter_tuning"
            ),
        },
        "holdout_eligibility": {
            "eligible": holdout_eligible,
            "minimum_independent_holdout_measurable_anchors": merged_policy[
                "minimum_holdout_measurable_anchors"
            ],
            "decision": (
                "eligible_for_one_time_holdout"
                if holdout_eligible
                else "insufficient_evaluable_denominator_no_holdout_claim"
            ),
        },
        "recommended_next_step": (
            "Run only truth-free coverage and mapping diagnostics; do not tune thresholds against this truth result."
            if not eligible_for_parameter_selection
            else "Freeze a preregistered finite grid, score development truth runner-only, then reserve holdout for one evaluation."
        ),
    }
