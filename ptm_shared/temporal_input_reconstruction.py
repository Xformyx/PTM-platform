"""Reconstruct canonical PTM time-series inputs without losing RAG trajectories.

RAG operates on one representative record per gene/site.  Its representative
top-level ``Condition`` is intentionally only one condition, while the observed
time course is preserved in ``condition_data``.  Temporal consumers must never
mistake the representative row for a one-timepoint measurement.

This module is numeric-input only.  It never reads benchmark truth, locked
scores, RAG prose, literature fields, or LLM output.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from statistics import median
from typing import Any, Iterable, Mapping


CONTRACT_VERSION = "temporal_input_reconstruction.v1"
_SOURCE_PRIORITY = {
    "condition_data": 0,
    "trajectory": 1,
    "site_aggregation": 2,
    "top_level_row": 3,
}


def _optional_finite_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _site_key(row: Mapping[str, Any]) -> str | None:
    gene = str(row.get("gene") or row.get("Gene.Name") or "").strip().upper()
    position = str(row.get("position") or row.get("PTM_Position") or "").strip()
    return f"{gene}_{position}" if gene and position else None


def _append_candidate(
    candidates: dict[str, dict[str, dict[str, list[float]]]],
    *,
    site_key: str,
    condition: Any,
    value: Any,
    source: str,
) -> None:
    label = str(condition or "").strip()
    number = _optional_finite_float(value)
    if not label or number is None:
        return
    candidates[site_key][label][source].append(number)


def reconstruct_ptm_timeseries(
    rows: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, dict[str, float]], dict[str, Any]]:
    """Return a deterministic per-site numeric vector and reconstruction provenance.

    Source priority is per site/timepoint rather than row order.  Values from
    duplicate peptide forms at the selected source level are combined by median;
    a missing value remains missing and is never converted to zero.  This lets a
    later complete-case Wave projection make the eligibility decision explicitly.
    """

    candidates: dict[str, dict[str, dict[str, list[float]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    input_rows = 0
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        input_rows += 1
        site_key = _site_key(row)
        if not site_key:
            continue

        # Preferred source for collapsed RAG rows: all observed condition values.
        for entry in row.get("condition_data") or []:
            if isinstance(entry, Mapping):
                _append_candidate(
                    candidates,
                    site_key=site_key,
                    condition=entry.get("condition") or entry.get("Condition"),
                    value=(
                        entry.get("ptm_relative_log2fc")
                        if entry.get("ptm_relative_log2fc") is not None
                        else entry.get("PTM_Relative_Log2FC")
                    ),
                    source="condition_data",
                )

        # A retained trajectory is a defensible fallback when condition_data was
        # not retained by an older RAG artifact.
        trajectory = row.get("trajectory") or ((row.get("rag_enrichment") or {}).get("trajectory") or {})
        if isinstance(trajectory, Mapping):
            for point in trajectory.get("timepoints") or []:
                if isinstance(point, Mapping):
                    _append_candidate(
                        candidates,
                        site_key=site_key,
                        condition=point.get("timeLabel") or point.get("condition"),
                        value=(
                            point.get("ptmLog2FC")
                            if point.get("ptmLog2FC") is not None
                            else point.get("ptm_relative_log2fc")
                        ),
                        source="trajectory",
                    )

        # Explicit site-form median is preserved for legacy records that retain
        # aggregation but no condition_data/trajectory list.
        aggregation = row.get("site_aggregation") or {}
        if isinstance(aggregation, Mapping):
            for point in aggregation.get("timepoints") or []:
                if isinstance(point, Mapping):
                    _append_candidate(
                        candidates,
                        site_key=site_key,
                        condition=point.get("timeLabel") or point.get("condition"),
                        value=(
                            point.get("ptmLog2FC")
                            if point.get("ptmLog2FC") is not None
                            else point.get("ptm_relative_log2fc")
                        ),
                        source="site_aggregation",
                    )

        # Uncollapsed preprocessing rows have their one measured condition at
        # top level.  It is intentionally lowest priority for collapsed records.
        _append_candidate(
            candidates,
            site_key=site_key,
            condition=row.get("condition") or row.get("Condition"),
            value=(
                row.get("ptm_relative_log2fc")
                if row.get("ptm_relative_log2fc") is not None
                else row.get("PTM_Relative_Log2FC")
            ),
            source="top_level_row",
        )

    vectors: dict[str, dict[str, float]] = {}
    source_counts: Counter[str] = Counter()
    duplicate_aggregations = 0
    for site_key in sorted(candidates):
        vector: dict[str, float] = {}
        for condition in sorted(candidates[site_key]):
            source_values = candidates[site_key][condition]
            chosen_source = min(source_values, key=lambda source: _SOURCE_PRIORITY[source])
            values = source_values[chosen_source]
            if len(values) > 1:
                duplicate_aggregations += 1
            vector[condition] = float(median(values))
            source_counts[chosen_source] += 1
        if vector:
            vectors[site_key] = vector

    key_value_rows = [
        (site_key, condition, value)
        for site_key, vector in vectors.items()
        for condition, value in vector.items()
    ]
    input_sha256 = hashlib.sha256(
        json.dumps(key_value_rows, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    provenance = {
        "contract_version": CONTRACT_VERSION,
        "source_priority": list(_SOURCE_PRIORITY),
        "input_row_count": input_rows,
        "site_count": len(vectors),
        "condition_count": len({condition for vector in vectors.values() for condition in vector}),
        "site_timepoint_source_counts": dict(sorted(source_counts.items())),
        "duplicate_site_timepoint_aggregations": duplicate_aggregations,
        "aggregation": "median_within_selected_source_per_site_timepoint",
        "missing_value_policy": "preserve_missing_no_zero_imputation",
        "input_sha256": input_sha256,
        "excluded_inputs": ["benchmark_truth", "locked_score", "rag_prose", "llm_output"],
    }
    return vectors, provenance


def build_temporal_input_bundle(
    rows: Iterable[Mapping[str, Any]],
    *,
    declared_conditions: Iterable[Any],
) -> dict[str, Any]:
    """Build an artifact-safe numeric bundle for temporal consumers and reruns."""

    vectors, provenance = reconstruct_ptm_timeseries(rows)
    conditions = [str(value) for value in declared_conditions if str(value).strip()]
    return {
        "contract_version": "temporal_input_bundle.v1",
        "declared_conditions": conditions,
        "ptm_timeseries": vectors,
        "provenance": provenance,
        "interpretation_boundary": (
            "Numeric observed PTM-relative values only. This bundle defines temporal input coverage; "
            "it contains no benchmark truth, locked evaluation, RAG prose, literature, or LLM output."
        ),
    }
