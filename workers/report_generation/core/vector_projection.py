"""Lossless, reader-safe projection of a PTM Vector TSV row for Report state.

The Report may simplify numerical presentation, but it must never collapse distinct
modified precursors merely because they share a gene and candidate residue annotation.
This module preserves identity and Phase 0--1 quantitation provenance while retaining
the legacy lower-case aliases consumed by existing Report nodes.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

from ptm_shared.de_novo_representation import conventional_quantitation_eligibility
from ptm_shared.evidence_contracts import build_measurement_provenance
from .quantitative_fields import project_axis_fields, QUANTITATIVE_SCHEMA_VERSION


REPORT_VECTOR_PROJECTION_VERSION = "report_vector_projection.v1"


def _text(row: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if value is not None:
            text = str(value).strip()
            if text and text.lower() not in {"nan", "none", "null", "na"}:
                return text
    return None


def _optional_float(row: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = row.get(key)
        if value is None or str(value).strip().lower() in {"", "nan", "none", "null", "na"}:
            continue
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(parsed):
            return round(parsed, 6)
    return None


def _optional_bool(row: Mapping[str, Any], *keys: str) -> bool | None:
    for key in keys:
        value = row.get(key)
        if value is None or str(value).strip() == "":
            continue
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    return None


def project_report_vector_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Return an additive Report-state projection without inventing zero values.

    `identity_complete_for_reader_cards` requires a modified-precursor identifier or
    modified sequence.  Rows without either remain available to legacy aggregate
    renderers, but reader feature cards must withhold them instead of grouping them
    by gene plus candidate residue alone.
    """
    source_feature_id = _text(row, "Precursor.Id", "PrecursorId", "precursor_id", "source_feature_id")
    modified_sequence = _text(row, "Modified.Sequence", "ModifiedSequence", "modified_sequence")
    gene = _text(row, "Gene.Name", "gene", "gene_name") or ""
    position = _text(row, "PTM_Position", "position", "site") or ""
    conventional_na = _optional_bool(
        row,
        "PTM_Unadjusted_Conventional_Log2FC_NA",
        "Conventional_Log2FC_NA",
        "ptm_unadjusted_conventional_log2fc_na",
    )
    projected = {
        "report_vector_projection_version": REPORT_VECTOR_PROJECTION_VERSION,
        # Existing aliases used across legacy Report nodes.
        "gene": gene,
        "position": position,
        "condition": _text(row, "Condition", "condition", "Comparison") or "",
        "ptm_relative_log2fc": _optional_float(row, "PTM_Relative_Log2FC", "ptm_relative_log2fc"),
        # Independent axes and their statistics are projected by the shared schema below.
        "ptm_unadjusted_conventional_log2fc_na": conventional_na,
        "ptm_unadjusted_calculation_mode": _text(row, "PTM_Unadjusted_Calculation_Mode", "ptm_unadjusted_calculation_mode") or None,
        "ptm_unadjusted_estimator_id": _text(row, "PTM_Unadjusted_Estimator_ID", "ptm_unadjusted_estimator_id") or None,
        "ptm_protein_adjusted_estimator_id": _text(row, "PTM_ProteinAdjusted_Estimator_ID", "ptm_protein_adjusted_estimator_id") or None,
        "ptm_protein_adjusted_missing_reason": _text(row, "PTM_ProteinAdjusted_Missing_Reason", "ptm_protein_adjusted_missing_reason") or None,
        "ptm_protein_adjusted_conventional_log2fc_na": _optional_bool(row, "PTM_ProteinAdjusted_Conventional_Log2FC_NA", "ptm_protein_adjusted_conventional_log2fc_na"),
        "ptm_protein_adjusted_aggregation_order": _text(row, "PTM_ProteinAdjusted_Aggregation_Order", "ptm_protein_adjusted_aggregation_order") or None,
        "linked_protein_estimator_id": _text(row, "Linked_Protein_Estimator_ID", "linked_protein_estimator_id") or None,
        "ptm_reconstructed_estimator_id": _text(row, "PTM_Reconstructed_Estimator_ID", "ptm_reconstructed_estimator_id") or None,
        "quantitation_estimator_contract_version": _text(row, "Quantitation_Estimator_Contract_Version", "quantitation_estimator_contract_version") or None,
        "ptm_unadjusted_input_scale": _text(row, "PTM_Unadjusted_Input_Scale", "ptm_unadjusted_input_scale"),
        "ptm_unadjusted_pseudocount_used": _optional_bool(
            row, "PTM_Unadjusted_Pseudocount_Used", "ptm_unadjusted_pseudocount_used"
        ),
        "ptm_reconstructed_calculation_mode": _text(
            row, "PTM_Reconstructed_Calculation_Mode", "ptm_reconstructed_calculation_mode"
        ),
        # Source identity and measurement provenance.
        "Precursor.Id": source_feature_id,
        "precursor_id": source_feature_id,
        "Modified.Sequence": modified_sequence,
        "modified_sequence": modified_sequence,
        "Protein.Group": _text(row, "Protein.Group", "protein_group", "Protein.Ids"),
        "protein_group": _text(row, "Protein.Group", "protein_group", "Protein.Ids"),
        "localization_probability": _optional_float(
            row, "Localization.Probability", "localization_probability", "PTM_Probability"
        ),
        "all_reported_ptm_positions": _text(row, "PTM_Positions", "PTM_Sites", "all_reported_ptm_positions"),
        "fasta_taxonomy_id": _text(row, "FASTA_Taxonomy_ID", "fasta_taxonomy_id", "Annotation_Species_Taxonomy_ID"),
        "identity_complete_for_reader_cards": bool(source_feature_id or modified_sequence),
        "identity_withheld_reason": (
            None if (source_feature_id or modified_sequence) else "modified_precursor_identity_unavailable_in_vector_projection"
        ),
    }
    projected.update(project_axis_fields(row))
    projected["quantitative_schema_version"] = QUANTITATIVE_SCHEMA_VERSION
    projected["measurement_provenance"] = dict(row.get("measurement_provenance") or build_measurement_provenance(row))
    eligibility = conventional_quantitation_eligibility(projected)
    projected.update({
        "independent_conventional_eligible": eligibility["eligible"],
        "detection_context_only": not eligibility["eligible"] and bool(conventional_na),
        "conventional_eligibility_reason_codes": eligibility["reason_codes"],
        "figure1_axis_contract": "protein_adjusted_relative_ptm_contrast_with_independent_conventional_eligibility",
    })
    return projected
