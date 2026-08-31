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


def build_feature_provenance_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    declared_conditions: Iterable[Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Recover only explicit feature identity fields for the P0/P1 full ledger.

    RAG-enriched records may represent an aggregate. This helper never invents a
    precursor, modified sequence, accession or localization value from a
    gene/site label. Records without explicit source feature identity are
    excluded and counted, allowing P1 to remain M0/no-call rather than silently
    treating a collapsed gene/site aggregate as a feature-level mapping proof.
    """

    conditions = [str(value) for value in declared_conditions if str(value).strip()]
    feature_rows: list[dict[str, Any]] = []
    input_count = 0
    identity_complete_count = 0
    excluded_count = 0
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        input_count += 1
        gene = str(raw.get("gene") or raw.get("Gene.Name") or "").strip()
        position = str(raw.get("position") or raw.get("PTM_Position") or "").strip()
        protein_group = str(raw.get("protein_group") or raw.get("Protein.Group") or raw.get("Protein.Ids") or raw.get("UniProt_ID") or "").strip()
        modified_sequence = str(raw.get("modified_sequence") or raw.get("Modified.Sequence") or raw.get("ModifiedSequence") or "").strip()
        precursor_id = str(raw.get("precursor_id") or raw.get("Precursor.Id") or raw.get("PrecursorId") or "").strip()
        if not (gene and position and protein_group and modified_sequence and precursor_id):
            excluded_count += 1
            continue
        identity_complete_count += 1
        base = {
            "gene": gene,
            "position": position,
            "protein_group": protein_group,
            "protein_accession": raw.get("protein_accession") or raw.get("UniProt_ID"),
            "modified_sequence": modified_sequence,
            "precursor_charge": raw.get("precursor_charge") or raw.get("Precursor.Charge") or raw.get("PrecursorCharge"),
            "precursor_id": precursor_id,
            "all_reported_ptm_positions": raw.get("all_reported_ptm_positions") or raw.get("PTM_Positions") or raw.get("PTM_Sites") or position,
            "localization_probability": raw.get("localization_probability") or raw.get("Localization.Probability") or raw.get("PTM_Probability"),
            "fasta_taxonomy_id": raw.get("fasta_taxonomy_id") or raw.get("FASTA_Taxonomy_ID"),
            "fasta_organism": raw.get("fasta_organism") or raw.get("FASTA_Organism"),
            "source_export_schema": raw.get("source_export_schema") or raw.get("Source_Export_Schema") or "enriched_ptm_record",
            "source_feature_key": raw.get("source_feature_key") or raw.get("Source_Feature_Key") or precursor_id,
        }
        condition_rows = raw.get("condition_data") or []
        emitted_conditions: set[str] = set()
        for point in condition_rows:
            if not isinstance(point, Mapping):
                continue
            condition = str(point.get("condition") or point.get("Condition") or "").strip()
            value = point.get("ptm_relative_log2fc") if point.get("ptm_relative_log2fc") is not None else point.get("PTM_Relative_Log2FC")
            if condition and _optional_finite_float(value) is not None:
                feature_rows.append({**base, "condition": condition, "log2fc": value})
                emitted_conditions.add(condition)
        if emitted_conditions:
            continue
        condition = str(raw.get("condition") or raw.get("Condition") or "").strip()
        value = raw.get("ptm_relative_log2fc") if raw.get("ptm_relative_log2fc") is not None else raw.get("PTM_Relative_Log2FC")
        if condition and _optional_finite_float(value) is not None:
            feature_rows.append({**base, "condition": condition, "log2fc": value})

    return feature_rows, {
        "contract_version": "feature_provenance_input_reconstruction.v1",
        "input_row_count": input_count,
        "explicit_feature_identity_row_count": identity_complete_count,
        "emitted_feature_condition_row_count": len(feature_rows),
        "excluded_missing_explicit_feature_identity_count": excluded_count,
        "declared_condition_count": len(conditions),
        "identity_fallback_policy": "no_gene_or_site_label_fallback",
        "excluded_inputs": ["benchmark_truth", "locked_score", "rag_prose", "llm_output"],
    }
