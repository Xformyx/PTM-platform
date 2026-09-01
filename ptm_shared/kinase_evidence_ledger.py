"""Feature-provenance and no-call contract for kinase-attribution outputs.

The ledger intentionally keeps analytical feature identity separate from the
gene--position aggregate used by the temporal Wave engine.  It never queries a
known-relation registry, benchmark truth, RAG, or an LLM.  A missing
feature-level mapping/curated-edge record is represented as a direct-kinase
``no_call`` rather than a guessed kinase assignment.

Full ledgers remain inside the production sidecar.  Only :func:`compact_summary`
is suitable for DB/API/RAG/Report handoff; it contains aggregate counts and no
modified sequences, accessions, candidate kinase names, or quantitative values.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from typing import Any, Iterable, Mapping, Sequence


CONTRACT_VERSION = "ptm_kinase_feature_provenance.v4"
DIRECT_NO_CALL_TIER = "E_direct_kinase_no_call"
TEMPORAL_ASSOCIATION_TIER = "D_temporal_aggregate_context"
UNRESOLVED_PRIMARY_REASON = "not_assigned_without_approved_f1_f8_priority_policy"
MAPPING_LEDGER_STATUS = "not_computable_feature_level_exact_mapping_and_curated_edge_provenance_absent"
CLASS_I_LOCALIZATION_THRESHOLD = 0.75


def _text(record: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = record.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _finite(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _site_key(record: Mapping[str, Any]) -> str:
    gene = _text(record, "gene", "Gene.Name").upper()
    position = _text(record, "position", "PTM_Position").upper()
    return f"{gene}_{position}" if gene and position else ""


def _residue_count(modified_sequence: str) -> int:
    """Count explicit phospho-like modifications conservatively.

    DIA-NN exports can encode modifications as UniMod IDs or as names.  This
    function purposefully reports a mask, not localization confidence or a
    claimed residue identity.
    """
    if not modified_sequence:
        return 0
    named = len(re.findall(r"(?:phospho|phosphoryl)", modified_sequence, flags=re.IGNORECASE))
    unimod = len(re.findall(r"UniMod:(?:21|259|267)\b", modified_sequence, flags=re.IGNORECASE))
    return max(named, unimod)


def _accession_tokens(protein_group: str) -> list[str]:
    """Extract accession-like tokens without claiming canonical protein identity."""
    tokens: list[str] = []
    for candidate in re.split(r"[;,]", protein_group or ""):
        item = candidate.strip()
        if not item:
            continue
        pipe_parts = [part.strip() for part in item.split("|")]
        if len(pipe_parts) >= 2 and pipe_parts[0].lower() in {"sp", "tr"}:
            item = pipe_parts[1]
        tokens.append(item)
    return sorted(set(tokens))


def _protein_group_ambiguous(protein_group: str) -> bool:
    return len(_accession_tokens(protein_group)) != 1


def _position_tokens(record: Mapping[str, Any]) -> list[str]:
    raw = _text(
        record,
        "all_reported_ptm_positions",
        "PTM_Positions",
        "PTM_Sites",
        "PTM_Position",
        "position",
    )
    return sorted({item.strip().upper() for item in re.split(r"[;,|/]", raw) if item.strip()})


def _localization_status(value: float | None) -> str:
    if value is None:
        return "not_recorded"
    if value >= CLASS_I_LOCALIZATION_THRESHOLD:
        return "recorded_class_I_or_higher"
    return "recorded_below_class_I_threshold"


def _feature_id(record: Mapping[str, Any], site_key: str) -> str:
    protein_group = _text(record, "protein_group", "Protein.Group", "Protein.Ids", "protein_accession", "UniProt_ID")
    modified_sequence = _text(record, "modified_sequence", "Modified.Sequence", "ModifiedSequence")
    charge = _text(record, "precursor_charge", "Precursor.Charge", "PrecursorCharge")
    precursor = _text(record, "precursor_id", "Precursor.Id", "PrecursorId")
    raw = "|".join((site_key, protein_group, modified_sequence, charge, precursor))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"feature_{digest}"


def _empty_reason_masks() -> dict[str, str]:
    return {
        "F1_protein_accession_or_group_ambiguous": "not_assessed",
        "F2_multi_phosphorylated_or_localization_ambiguous": "not_assessed",
        "F3_rat_to_human_exact_sequence_site_mapping_failure": "not_assessed_feature_level_mapping_ledger_absent",
        "F4_exact_mapping_success_but_no_curated_kinase_edge": "not_assessed_feature_level_mapping_ledger_absent",
        "F5_quantitative_time_data_insufficient": "not_assessed",
        "F6_direct_edge_but_tmm_gate_not_passed": "not_assessed_feature_level_edge_tmm_ledger_absent",
        "F7_multiple_candidate_kinases_prevent_single_attribution": "not_assessed_feature_level_candidate_ledger_absent",
        "F8_direct_match_success": "not_assessed_feature_level_mapping_edge_ledger_absent",
    }


def _record_from_rows(site_key: str, rows: Sequence[Mapping[str, Any]], conditions: Sequence[str]) -> dict[str, Any]:
    first = rows[0]
    protein_group = _text(first, "protein_group", "Protein.Group", "Protein.Ids", "protein_accession", "UniProt_ID")
    modified_sequence = _text(first, "modified_sequence", "Modified.Sequence", "ModifiedSequence")
    precursor_charge = _text(first, "precursor_charge", "Precursor.Charge", "PrecursorCharge")
    precursor_id = _text(first, "precursor_id", "Precursor.Id", "PrecursorId")
    localization = _text(first, "localization_probability", "Localization.Probability", "PTM_Probability")
    localization_value = _finite(localization)
    accessions = _accession_tokens(protein_group)
    reported_positions = _position_tokens(first)
    fasta_taxonomy_id = _text(first, "fasta_taxonomy_id", "FASTA_Taxonomy_ID", "Annotation_Species_Taxonomy_ID")
    fasta_organism = _text(first, "fasta_organism", "FASTA_Organism", "Annotation_Organism")
    source_export_schema = _text(first, "source_export_schema", "Source_Export_Schema")
    source_feature_key = _text(first, "source_feature_key", "Source_Feature_Key")
    observed_conditions = {
        _text(row, "condition", "Condition")
        for row in rows
        if _text(row, "condition", "Condition") and _finite(row.get("log2fc")) is not None
    }
    masks = _empty_reason_masks()
    protein_ambiguous = _protein_group_ambiguous(protein_group)
    multi_phospho = max(_residue_count(modified_sequence), len(reported_positions)) > 1
    localization_state = _localization_status(localization_value)
    localization_recorded = localization_value is not None
    incomplete_grid = any(condition not in observed_conditions for condition in conditions)
    masks["F1_protein_accession_or_group_ambiguous"] = "flagged" if protein_ambiguous else "passed"
    if multi_phospho and not localization_recorded:
        masks["F2_multi_phosphorylated_or_localization_ambiguous"] = "flagged_multi_phosphorylated_and_localization_not_recorded"
    elif multi_phospho:
        masks["F2_multi_phosphorylated_or_localization_ambiguous"] = "flagged_multi_phosphorylated"
    elif not localization_recorded:
        masks["F2_multi_phosphorylated_or_localization_ambiguous"] = "flagged_localization_not_recorded"
    elif localization_value < CLASS_I_LOCALIZATION_THRESHOLD:
        masks["F2_multi_phosphorylated_or_localization_ambiguous"] = "flagged_localization_below_class_I_threshold"
    else:
        masks["F2_multi_phosphorylated_or_localization_ambiguous"] = "passed"
    masks["F5_quantitative_time_data_insufficient"] = "flagged" if incomplete_grid else "passed"
    direct_no_call_reasons = []
    if protein_ambiguous:
        direct_no_call_reasons.append("protein_group_or_accession_ambiguous")
    if multi_phospho:
        direct_no_call_reasons.append("multi_phosphorylated_precursor")
    if not localization_recorded:
        direct_no_call_reasons.append("localization_probability_not_recorded")
    elif localization_value < CLASS_I_LOCALIZATION_THRESHOLD:
        direct_no_call_reasons.append("localization_probability_below_class_I_threshold")
    direct_no_call_reasons.append("feature_level_exact_mapping_and_curated_edge_provenance_absent")
    return {
        "feature_id": _feature_id(first, site_key),
        "feature_unit": "modified_precursor_feature_collapsed_across_declared_conditions",
        "nominal_aggregate_key": site_key,
        "identity_provenance": {
            "protein_group": protein_group or None,
            "protein_accession_tokens": accessions,
            "protein_accession_status": (
                "single_accession_observed" if len(accessions) == 1
                else "multiple_or_missing_accessions"
            ),
            "modified_sequence": modified_sequence or None,
            "precursor_charge": precursor_charge or None,
            "precursor_id": precursor_id or None,
            "all_reported_ptm_positions": reported_positions,
            "reported_ptm_position_count": len(reported_positions),
            "localization_probability": localization_value,
            "source_export_schema": source_export_schema or None,
            "source_feature_key": source_feature_key or None,
            "fasta_taxonomy_id": fasta_taxonomy_id or None,
            "fasta_organism": fasta_organism or None,
            "protein_group_status": "ambiguous_or_missing" if protein_ambiguous else "single_group_observed",
            "phosphorylation_form_status": "multi_phosphorylated" if multi_phospho else "single_or_unspecified_modification",
            "localization_status": localization_state,
            "identity_claim_boundary": (
                "Feature identity is export provenance only; it does not establish "
                "a residue-exact species/isoform mapping or direct kinase relation."
            ),
        },
        "quantification_provenance": {
            "declared_timepoint_count": len(conditions),
            "observed_timepoint_count": len(observed_conditions),
            "missing_timepoint_count": len(set(conditions) - observed_conditions),
            "missing_value_policy": "missing_is_not_zero_and_does_not_create_a_dynamic_endpoint_state",
        },
        "unmatched_reason_masks": masks,
        "unmatched_reason_primary": UNRESOLVED_PRIMARY_REASON,
        "unmatched_reason_ledger_status": MAPPING_LEDGER_STATUS,
        "mapping_evidence": {
            "feature_level_exact_mapping_status": "not_assessed_no_versioned_mapping_ledger",
            "curated_kinase_edge_status": "not_assessed_no_versioned_feature_edge_ledger",
            "orthology_transfer_status": "not_assessed_no_versioned_orthology_ledger",
        },
        "direct_kinase_attribution": {
            "evidence_tier": DIRECT_NO_CALL_TIER,
            "status": "no_call",
            "reasons": direct_no_call_reasons,
            "promotion_guard": "tmm_rag_llm_cannot_promote_direct_kinase_evidence_tier",
        },
        "temporal_evidence": {
            "evidence_tier": "not_assessed_no_wave_contract",
            "status": "not_assessed",
            "claim_boundary": "temporal association does not establish direct kinase regulation or causality",
        },
        "tmm_candidate_context": {
            "status": "not_assessed_no_feature_level_contribution_ledger",
            "claim_boundary": "candidate or contribution context is not a curated direct kinase edge",
        },
    }


def build_feature_provenance_ledger(
    feature_rows: Iterable[Mapping[str, Any]],
    declared_conditions: Sequence[str],
) -> dict[str, Any]:
    """Build a full sidecar-only ledger without raw quantitative values.

    Rows may contain multiple exported forms/conditions for an aggregate.  They
    are grouped by a stable feature descriptor before the aggregate relationship
    is recorded.  No F1--F8 primary root-cause classification is emitted until
    a versioned mapping/edge/TMM candidate ledger is available.
    """
    conditions = [str(item) for item in declared_conditions]
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in feature_rows:
        site_key = _site_key(row)
        if not site_key:
            continue
        feature_key = _feature_id(row, site_key)
        grouped[(site_key, feature_key)].append(row)
    records = [
        _record_from_rows(site_key, rows, conditions)
        for (site_key, _), rows in sorted(grouped.items())
        if rows
    ]
    ledger = {
        "contract_version": CONTRACT_VERSION,
        "analysis_boundary": {
            "benchmark_truth_used": False,
            "known_relation_registry_used": False,
            "rag_used": False,
            "llm_used": False,
            "raw_quantitative_values_persisted": False,
        },
        "feature_records": records,
        "summary": {},
    }
    ledger["summary"] = compact_summary(ledger)
    return ledger


def attach_temporal_context(
    ledger: Mapping[str, Any], wave_contract: Mapping[str, Any] | None,
    tmm_contribution_matrix: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Annotate aggregate-level temporal/TMM context without tier promotion."""
    result = {key: value for key, value in dict(ledger).items() if key != "feature_records"}
    members = {
        str(site_key)
        for wave in (wave_contract or {}).get("waves", [])
        if isinstance(wave, Mapping)
        for site_key in (wave.get("members") or [])
    }
    contribution_keys = {str(key) for key in (tmm_contribution_matrix or {})}
    records = []
    for raw_record in ledger.get("feature_records") or []:
        record = dict(raw_record)
        temporal = dict(record.get("temporal_evidence") or {})
        tmm_context = dict(record.get("tmm_candidate_context") or {})
        aggregate = str(record.get("nominal_aggregate_key") or "")
        if aggregate in members:
            temporal.update({
                "evidence_tier": TEMPORAL_ASSOCIATION_TIER,
                "status": "static_wave_member_observational_context",
                "claim_boundary": "same-static-Wave membership is observational temporal context, not direct kinase regulation or causality",
            })
        else:
            temporal.update({
                "evidence_tier": "not_wave_member_or_not_evaluable",
                "status": "not_qualified_for_static_wave_context",
            })
        if aggregate in contribution_keys:
            tmm_context.update({
                "status": "aggregate_present_in_candidate_contribution_matrix",
                "claim_boundary": "TMM candidate contribution is conditional attribution context and cannot promote direct kinase evidence tier",
            })
        record["temporal_evidence"] = temporal
        record["tmm_candidate_context"] = tmm_context
        records.append(record)
    result["feature_records"] = records
    result["summary"] = compact_summary(result)
    return result


def compact_summary(ledger: Mapping[str, Any]) -> dict[str, Any]:
    """Return the only ledger projection permitted in RAG/Report contexts."""
    records = [row for row in ledger.get("feature_records") or [] if isinstance(row, Mapping)]
    direct_counts = Counter(
        str((row.get("direct_kinase_attribution") or {}).get("evidence_tier") or "unknown")
        for row in records
    )
    temporal_counts = Counter(
        str((row.get("temporal_evidence") or {}).get("evidence_tier") or "unknown")
        for row in records
    )
    reason_masks = {
        "protein_group_or_accession_ambiguous": sum(
            (row.get("unmatched_reason_masks") or {}).get("F1_protein_accession_or_group_ambiguous") == "flagged"
            for row in records
        ),
        "multi_phosphorylated_or_localization_not_confirmed": sum(
            str((row.get("unmatched_reason_masks") or {}).get("F2_multi_phosphorylated_or_localization_ambiguous") or "").startswith("flagged")
            for row in records
        ),
        "incomplete_declared_time_grid": sum(
            (row.get("unmatched_reason_masks") or {}).get("F5_quantitative_time_data_insufficient") == "flagged"
            for row in records
        ),
    }
    localization_counts = Counter(
        str((row.get("identity_provenance") or {}).get("localization_status") or "unknown")
        for row in records
    )
    accession_counts = Counter(
        str((row.get("identity_provenance") or {}).get("protein_accession_status") or "unknown")
        for row in records
    )
    mapping_counts = Counter(
        str((row.get("mapping_evidence") or {}).get("mapping_class_code") or "not_assessed")
        for row in records
    )
    mapping_importer = dict(ledger.get("mapping_importer") or {})
    mapping_importer_summary = dict(mapping_importer.get("compact_summary") or {})
    relation_importer = dict(ledger.get("relation_importer") or {})
    relation_importer_summary = dict(relation_importer.get("compact_summary") or {})
    relation_counts = Counter(
        str((row.get("relation_evidence") or {}).get("relation_class_code") or "not_assessed")
        for row in records
    )
    aggregate_count = len({str(row.get("nominal_aggregate_key") or "") for row in records if row.get("nominal_aggregate_key")})
    return {
        "contract_version": CONTRACT_VERSION,
        "release_scope": "aggregate_only_report_rag_safe_summary",
        "feature_record_count": len(records),
        "nominal_aggregate_count": aggregate_count,
        "direct_kinase_evidence_tier_counts": dict(sorted(direct_counts.items())),
        "temporal_evidence_tier_counts": dict(sorted(temporal_counts.items())),
        "reason_mask_counts": reason_masks,
        "identity_readiness_counts": {
            "localization_status": dict(sorted(localization_counts.items())),
            "protein_accession_status": dict(sorted(accession_counts.items())),
            "class_I_localization_threshold": CLASS_I_LOCALIZATION_THRESHOLD,
        },
        "mapping_readiness": {
            "mapping_importer_contract_version": mapping_importer_summary.get("mapping_importer_contract_version"),
            "mapping_bundle_status": mapping_importer_summary.get("mapping_bundle_status", "not_assessed"),
            "mapping_bundle_error_code": mapping_importer_summary.get("mapping_bundle_error_code"),
            "mapping_class_counts": (
                mapping_importer_summary.get("mapping_class_counts")
                or {code: mapping_counts.get(code, 0) for code in ("M0", "M1", "M2", "M3", "M4")}
            ),
            "claim_boundary": "Mapping readiness is aggregate-only provenance; it does not create a direct kinase relation.",
        },
        "relation_readiness": {
            "relation_importer_contract_version": relation_importer_summary.get("relation_importer_contract_version"),
            "relation_bundle_status": relation_importer_summary.get("relation_bundle_status", "not_assessed"),
            "relation_bundle_error_code": relation_importer_summary.get("relation_bundle_error_code"),
            "relation_class_counts": (
                relation_importer_summary.get("relation_class_counts")
                or {code: relation_counts.get(code, 0) for code in ("R0", "R1", "R2", "R3", "R4")}
            ),
            "claim_boundary": "Curated relation readiness is aggregate-only provenance; it does not identify one kinase or establish direct regulation.",
        },
        "mutually_exclusive_f1_f8_ledger_status": MAPPING_LEDGER_STATUS,
        "unmatched_reason_primary_policy": UNRESOLVED_PRIMARY_REASON,
        "direct_kinase_attribution_status": "no_call_without_p3_candidate_allocation_and_required_feature_mapping_localization_relation_provenance",
        "claim_boundary": (
            "Counts describe provenance readiness and direct-kinase no-call status only. "
            "They do not identify a kinase, establish a direct kinase-substrate relation, "
            "or support causal/perturbation claims."
        ),
        "excluded_fields": [
            "modified_sequence", "precursor_id", "protein_group", "protein_accession_tokens",
            "all_reported_ptm_positions", "localization_probability", "source_feature_key",
            "fasta_taxonomy_id", "fasta_organism", "mapping_accession", "mapping_sequence",
            "mapping_peptide", "mapping_coordinate", "orthology_identifier", "mapping_source_file_path",
            "candidate_kinase_names", "relation_candidate_edges", "relation_edge_id", "relation_reference_id",
            "relation_license_text", "relation_source_file_path", "relation_isoform_or_sequence_id",
            "raw_log2fc", "raw_intensity", "q_value", "benchmark_truth", "known_relation_registry",
        ],
    }


__all__ = [
    "CONTRACT_VERSION",
    "CLASS_I_LOCALIZATION_THRESHOLD",
    "DIRECT_NO_CALL_TIER",
    "TEMPORAL_ASSOCIATION_TIER",
    "attach_temporal_context",
    "build_feature_provenance_ledger",
    "compact_summary",
]
