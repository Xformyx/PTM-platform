from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _output_tokens(value: Any) -> list[str]:
    tokens = re.findall(r"\b[A-Z][A-Z0-9-]{1,15}\b", str(value or "").upper())
    excluded = {"NO", "AND", "OR", "USE", "HIGH", "MEDIUM", "LOW", "PIP3"}
    return sorted({token for token in tokens if token not in excluded})


def _field(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in row and row.get(name) not in (None, ""):
            return row.get(name)
    return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _normalize_protein_effectors(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "effector_id": _field(row, "Effector_ID", "effector_id"),
            "gene": str(_field(row, "Gene", "gene") or "").upper(),
            "expected_peak": _field(row, "Expected_peak", "Expected_time", "expected_peak"),
            "expected_direction": _field(row, "Expected_direction", "expected_direction"),
            "evidence_tier": _field(row, "Evidence_tier", "evidence_tier"),
            "reference": _field(row, "Reference", "reference"),
            "notes": _field(row, "Notes", "notes"),
        }
        for row in rows
        if str(_field(row, "Gene", "gene") or "").strip()
    ]


def _normalize_cross_layer(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "relation_id": _field(row, "Relation_ID", "relation_id"),
            "source_wave_id": _field(row, "Source_wave_ID", "source_wave_id"),
            "target_gene": str(_field(row, "Target_gene", "target_gene") or "").upper(),
            "expected_direction": _field(row, "Expected_direction", "expected_direction"),
            "minimum_peak_lag_minutes": _float_or_none(
                _field(row, "Minimum_peak_lag_minutes", "minimum_peak_lag_minutes")
            ),
            "maximum_peak_lag_minutes": _float_or_none(
                _field(row, "Maximum_peak_lag_minutes", "maximum_peak_lag_minutes")
            ),
            "evidence_tier": _field(row, "Evidence_tier", "evidence_tier"),
            "reference": _field(row, "Reference", "reference"),
            "notes": _field(row, "Notes", "notes"),
        }
        for row in rows
        if str(_field(row, "Target_gene", "target_gene") or "").strip()
    ]


def _normalize_mechanism_chains(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        kinase_label = _field(row, "Kinase_or_complex", "kinase_label", "Kinase")
        target = _field(row, "Target_gene", "target_gene")
        if not kinase_label:
            continue
        required = _output_tokens(_field(row, "Required_output_tokens", "required_output_tokens"))
        if target:
            required = sorted(set(required) | {str(target).upper()})
        normalized.append(
            {
                "chain_id": _field(row, "Chain_ID", "chain_id"),
                "kinase_id": _field(row, "Kinase_ID", "kinase_id"),
                "kinase_label": kinase_label,
                "wave_id": _field(row, "Wave_ID", "wave_id"),
                "target_gene": str(target or "").upper() or None,
                "required_output_tokens": required,
                "expected_direction": _field(row, "Expected_direction", "expected_direction"),
                "expected_time": _field(row, "Expected_time", "expected_time"),
                "evidence_tier": _field(row, "Evidence_tier", "evidence_tier"),
                "reference": _field(row, "Reference", "reference"),
                "notes": _field(row, "Notes", "notes"),
                "reference_origin": "optional_v2_mechanism_chains",
            }
        )
    return normalized


def _normalize_counterexamples(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "counterexample_id": _field(row, "Counterexample_ID", "counterexample_id"),
            "chain_id": _field(row, "Chain_ID", "chain_id"),
            "kinase_label": _field(row, "Kinase_or_complex", "kinase_label"),
            "target_gene": str(_field(row, "Target_gene", "target_gene") or "").upper() or None,
            "expected_status": _field(row, "Expected_status", "expected_status"),
            "exclusion_reason": _field(row, "Exclusion_reason", "exclusion_reason"),
            "reference": _field(row, "Reference", "reference"),
            "notes": _field(row, "Notes", "notes"),
            "reference_origin": "optional_v2_counterexamples",
        }
        for row in rows
        if _field(row, "Counterexample_ID", "counterexample_id")
    ]


def build_additive_v2_truth(v1_truth: Mapping[str, Any]) -> dict[str, Any]:
    optional = dict(v1_truth.get("additive_v2_reference") or {})
    kinase_reference = [dict(row) for row in (v1_truth.get("kinase_reference") or []) if isinstance(row, Mapping)]
    mechanism_reference = [
        {
            "kinase_id": row.get("Kinase_ID"),
            "kinase_label": row.get("Kinase_or_complex"),
            "expected_direction": row.get("Expected_activity_direction"),
            "expected_time": row.get("Expected_time"),
            "layer": row.get("Layer"),
            "required_output_tokens": _output_tokens(row.get("Direct_or_preferred_outputs")),
            "reference_origin": "v1_kinase_reference",
        }
        for row in kinase_reference
    ]
    protein_effectors = _normalize_protein_effectors(list(optional.get("protein_effectors") or []))
    cross_layer = _normalize_cross_layer(list(optional.get("cross_layer_relations") or []))
    explicit_chains = _normalize_mechanism_chains(list(optional.get("mechanism_chains") or []))
    counterexamples = _normalize_counterexamples(list(optional.get("counterexamples") or []))
    if not counterexamples:
        counterexamples = [
            {**dict(row), "reference_origin": "v1_ambiguous_sites"}
            for row in (v1_truth.get("ambiguous_sites") or [])
            if isinstance(row, Mapping)
        ]
    payload = {
        "schema_version": "ptm_benchmark_additive_v2_truth.v1",
        "dataset_id": v1_truth.get("dataset_id"),
        "parent_v1_truth_sha256": _canonical_sha256(v1_truth),
        "source_workbook_sha256": v1_truth.get("source_workbook_sha256"),
        "kinase_timing_reference": kinase_reference,
        "temporal_layer_reference": list(v1_truth.get("temporal_layers") or []),
        "protein_effector_reference": protein_effectors,
        "cross_layer_reference": cross_layer,
        "mechanism_reference": explicit_chains or mechanism_reference,
        "counterexample_reference": counterexamples,
        "evaluability": {
            "kinase_timing": "reference_available" if kinase_reference else "not_evaluable",
            "protein_effectors": "reference_available" if protein_effectors else "not_evaluable_missing_optional_sheet",
            "cross_layer": "reference_available" if cross_layer else "not_evaluable_missing_optional_sheet",
            "mechanism": "explicit_reference_available" if explicit_chains else "v1_kinase_output_tokens_only",
            "refutation": "explicit_reference_available" if optional.get("counterexamples") else "ambiguous_site_policy_only",
        },
        "selection_boundary": "Runner-only post-freeze truth. This payload must never enter analysis, RAG, report, or LLM runtime.",
    }
    payload["truth_sha256"] = _canonical_sha256(payload)
    return payload
