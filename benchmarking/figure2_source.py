"""Display-only Figure 2 source tables from an already-scored locked result.

구현 대상: docs/insulin_blind_benchmark_manuscript_output_spec_v1_ko.md §2 Figure 2, §4 source-data
사전등록: 해당 없음 (점수 공식 변경 아님. 기존 metrics/anchor_results만 재배열)
해석 한계: bootstrap CI·partial window·kinase rank는 이 모듈이 만들지 않는다.
주장 금지: 이 표로 kinase 귀속 정확도나 하류 개선을 논하지 않는다.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Mapping

FIGURE2_SCHEMA = "ptm_benchmark_figure2.v1"

_METRIC_ORDER = (
    "detectable_anchor_recall",
    "regulated_anchor_recall",
    "direction_accuracy",
    "peak_window_accuracy",
    "chain_completeness",
    "canonical_weighted_score",
)

_METRIC_LABELS = {
    "detectable_anchor_recall": "Detectable recall",
    "regulated_anchor_recall": "Regulated recall",
    "direction_accuracy": "Direction accuracy",
    "peak_window_accuracy": "Peak-window accuracy",
    "chain_completeness": "Chain completeness",
    "canonical_weighted_score": "Weighted composite",
}


def _as_bool(value: Any) -> bool:
    return value is True or str(value).strip().lower() in {"true", "1", "yes"}


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def _window_status(row: Mapping[str, Any]) -> str:
    if not _as_bool(row.get("is_measurable")):
        return "not_evaluable"
    if not _as_bool(row.get("regulated")):
        return "not_evaluable"
    if row.get("peak_window_correct") is True:
        return "match"
    if row.get("peak_window_correct") is False:
        return "miss"
    return "not_evaluable"


def _regulation_status(row: Mapping[str, Any]) -> str:
    if not _as_bool(row.get("is_measurable")):
        return "not_measurable"
    if not _as_bool(row.get("detected")):
        return "measurable_not_detected"
    if not _as_bool(row.get("regulated")):
        return "detected_not_regulated"
    return "correct_regulation"


def build_figure2_source(score_result: Mapping[str, Any]) -> dict[str, Any]:
    """Rearrange locked score rows into Figure 2 source tables.

    Does not recompute canonical metrics. Branch rates are unweighted counts
    for display; primary score stays the scorer's tier-weighted ratios.
    """

    metrics = dict(score_result.get("metrics") or {})
    numerators = dict(score_result.get("metric_numerators") or {})
    denominators = dict(score_result.get("metric_denominators") or {})
    anchors = [row for row in (score_result.get("anchor_results") or []) if isinstance(row, Mapping)]

    panel_2a = []
    for key in _METRIC_ORDER:
        if key not in metrics:
            continue
        panel_2a.append(
            {
                "key": key,
                "label": _METRIC_LABELS.get(key, key),
                "estimate": metrics.get(key),
                "numerator": numerators.get(key),
                "denominator": denominators.get(key),
                "ci95": None,
            }
        )

    branches: dict[str, list[Mapping[str, Any]]] = {}
    for row in anchors:
        branch = str(row.get("branch") or "Unspecified")
        branches.setdefault(branch, []).append(row)

    panel_2b = []
    for branch, rows in sorted(branches.items()):
        measurable = [row for row in rows if _as_bool(row.get("is_measurable"))]
        detected = [row for row in measurable if _as_bool(row.get("detected"))]
        regulated = [row for row in detected if _as_bool(row.get("regulated"))]
        direction_ok = sum(1 for row in regulated if row.get("direction_correct") is True)
        peak_ok = sum(1 for row in regulated if row.get("peak_window_correct") is True)
        panel_2b.append(
            {
                "branch": branch,
                "n_evaluable": len(measurable),
                "detectable_anchor_recall": _ratio(len(detected), len(measurable)),
                "regulated_anchor_recall": _ratio(len(regulated), len(measurable)),
                "direction_accuracy": _ratio(direction_ok, len(regulated)),
                "peak_window_accuracy": _ratio(peak_ok, len(regulated)),
            }
        )

    panel_2c = [
        {
            "anchor_id": row.get("anchor_id"),
            "tier": row.get("tier"),
            "branch": row.get("branch"),
            "is_measurable": _as_bool(row.get("is_measurable")),
            "detected": _as_bool(row.get("detected")),
            "regulated": _as_bool(row.get("regulated")),
            "direction_correct": row.get("direction_correct"),
            "peak_window_correct": row.get("peak_window_correct"),
            "window_status": _window_status(row),
            "regulation_status": _regulation_status(row),
        }
        for row in anchors
    ]

    status_counts = {
        "not_measurable": 0,
        "measurable_not_detected": 0,
        "detected_not_regulated": 0,
        "correct_regulation": 0,
    }
    for row in panel_2c:
        status_counts[str(row["regulation_status"])] += 1

    return {
        "schema_version": FIGURE2_SCHEMA,
        "primary_score_unchanged": True,
        "ci_available": False,
        "partial_window_available": False,
        "panel_2a_metrics": panel_2a,
        "panel_2b_branches": panel_2b,
        "panel_2c_anchors": panel_2c,
        "panel_2d_status": status_counts,
    }


def write_figure2_tsvs(output_dir: str | Path, figure2: Mapping[str, Any]) -> dict[str, str]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    paths = {
        "metrics_summary": destination / "metrics_summary.tsv",
        "branch_metrics": destination / "branch_metrics.tsv",
        "anchor_scores": destination / "anchor_scores.tsv",
        "anchor_status_counts": destination / "anchor_status_counts.tsv",
    }
    _write_rows(paths["metrics_summary"], list(figure2.get("panel_2a_metrics") or []))
    _write_rows(paths["branch_metrics"], list(figure2.get("panel_2b_branches") or []))
    _write_rows(paths["anchor_scores"], list(figure2.get("panel_2c_anchors") or []))
    status = figure2.get("panel_2d_status") or {}
    _write_rows(
        paths["anchor_status_counts"],
        [{"status": key, "count": value} for key, value in status.items()],
    )
    return {key: str(path) for key, path in paths.items()}


def _write_rows(path: Path, rows: list[Mapping[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    headers: list[str] = []
    for row in rows:
        for key in row:
            if key not in headers:
                headers.append(str(key))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
