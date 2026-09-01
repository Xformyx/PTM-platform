"""P3 conservation-first bookkeeping for P2 exact curated candidate sets.

The module is intentionally a pure, local ledger transform. Equal fractional
mass represents unresolved symmetry among valid P2 candidates; it is never a
kinase probability, kinase score, direct attribution, causal edge, or
perturbation result. Candidate identity remains full-sidecar-only.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any, Iterable, Mapping


ALLOCATION_CONTRACT_VERSION = "ptm_kinase_candidate_allocation.v1"
P3_NO_CANDIDATE_SET = "not_evaluable_or_no_candidate_set"
P3_INVALID_CANDIDATE_SET = "invalid_candidate_set_no_allocation"
P3_FRACTIONAL_ALLOCATION = "fractional_candidate_set_allocation_pending_interpretation"
_EDGE_FIELDS = (
    "edge_id", "kinase_accession", "kinase_taxonomy_id", "substrate_accession",
    "substrate_taxonomy_id", "residue", "position",
    "substrate_isoform_or_sequence_id", "source_identity_scope",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _edge_key(edge: Mapping[str, Any]) -> tuple[str, int, str, int, str, int, str, str, str] | None:
    """Return complete P2 candidate identity or None without repairing it."""

    if not isinstance(edge, Mapping) or any(not _text(edge.get(field)) for field in _EDGE_FIELDS):
        return None
    kinase_taxonomy = _positive_int(edge.get("kinase_taxonomy_id"))
    substrate_taxonomy = _positive_int(edge.get("substrate_taxonomy_id"))
    position = _positive_int(edge.get("position"))
    if not kinase_taxonomy or not substrate_taxonomy or not position:
        return None
    residue = _text(edge.get("residue")).upper()
    if residue not in {"S", "T", "Y"}:
        return None
    return (
        _text(edge.get("edge_id")),
        kinase_taxonomy,
        _text(edge.get("kinase_accession")).upper(),
        substrate_taxonomy,
        _text(edge.get("substrate_accession")).upper(),
        position,
        residue,
        _text(edge.get("substrate_isoform_or_sequence_id")),
        _text(edge.get("source_identity_scope")),
    )


def _candidate_set(record: Mapping[str, Any]) -> tuple[list[dict[str, Any]] | None, str | None]:
    relation = record.get("relation_evidence") or {}
    if relation.get("relation_class_code") != "R3":
        return None, "p2_relation_is_not_R3_exact_candidate_set"
    candidates = relation.get("candidate_edges")
    if not isinstance(candidates, list) or not candidates:
        return None, "p2_R3_candidate_edges_missing_or_empty"
    keyed: list[tuple[tuple[str, int, str, int, str, int, str, str, str], dict[str, Any]]] = []
    for candidate in candidates:
        key = _edge_key(candidate)
        if key is None:
            return None, "p2_candidate_edge_identity_missing_or_invalid"
        keyed.append((key, dict(candidate)))
    if len({key for key, _ in keyed}) != len(keyed):
        return None, "p2_candidate_edge_identity_duplicate"
    kinase_identities = {(key[1], key[2]) for key, _ in keyed}
    if len(kinase_identities) != len(keyed):
        return None, "p2_candidate_kinase_identity_duplicate"
    return [candidate for _, candidate in sorted(keyed, key=lambda item: item[0])], None


def _allocation_record(record: Mapping[str, Any], candidates: list[dict[str, Any]] | None, reason: str | None) -> dict[str, Any]:
    relation = record.get("relation_evidence") or {}
    if not candidates:
        return {
            "allocation_contract_version": ALLOCATION_CONTRACT_VERSION,
            "allocation_status": P3_INVALID_CANDIDATE_SET if relation.get("relation_class_code") == "R3" else P3_NO_CANDIDATE_SET,
            "allocation_reason": reason,
            "eligible_candidate_count": 0,
            "feature_evidence_mass": 0.0,
            "total_allocated_mass": 0.0,
            "candidate_ambiguity_entropy_nats": None,
            "mass_conserved": False,
            "claim_boundary": "No P3 allocation exists; direct kinase attribution remains no_call.",
        }
    candidate_count = len(candidates)
    mass = 1.0 / candidate_count
    allocations = [
        {**candidate, "fractional_feature_evidence_mass": mass, "candidate_ordinal": ordinal}
        for ordinal, candidate in enumerate(candidates, start=1)
    ]
    total = math.fsum(item["fractional_feature_evidence_mass"] for item in allocations)
    return {
        "allocation_contract_version": ALLOCATION_CONTRACT_VERSION,
        "allocation_status": P3_FRACTIONAL_ALLOCATION,
        "allocation_reason": "equal_mass_symmetry_convention_for_unresolved_exact_candidate_set",
        "eligible_candidate_count": candidate_count,
        "feature_evidence_mass": 1.0,
        "total_allocated_mass": total,
        "candidate_ambiguity_entropy_nats": math.log(candidate_count),
        "mass_conserved": math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-12),
        "allocated_candidate_edges": allocations,
        "claim_boundary": (
            "Equal fractional mass is candidate-set bookkeeping, not a kinase probability, ranking, activity score, "
            "direct regulation, causality, or perturbation result."
        ),
    }


def allocate_candidate_sets(ledger: Mapping[str, Any]) -> dict[str, Any]:
    """Create P3 allocations from already-attached P2 feature evidence only."""

    feature_allocations: dict[str, dict[str, Any]] = {}
    for record in ledger.get("feature_records") or []:
        if not isinstance(record, Mapping) or not record.get("feature_id"):
            continue
        candidates, reason = _candidate_set(record)
        feature_allocations[str(record["feature_id"])] = _allocation_record(record, candidates, reason)
    eligible_count = sum(
        allocation.get("allocation_status") == P3_FRACTIONAL_ALLOCATION
        for allocation in feature_allocations.values()
    )
    return {
        "allocation_contract_version": ALLOCATION_CONTRACT_VERSION,
        "allocation_status": "computed" if eligible_count else "computed_no_eligible_R3_candidate_sets",
        "feature_allocations": feature_allocations,
        "claim_boundary": "P3 preserves candidate ambiguity and cannot make a single-kinase or causal claim.",
    }


def compact_allocation_summary(allocation_context: Mapping[str, Any], feature_records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Return P3 aggregates allowed in compact Report/RAG payloads only."""

    allocations = [
        row.get("allocation_evidence") or {}
        for row in feature_records
        if isinstance(row, Mapping)
    ]
    eligible = [row for row in allocations if row.get("allocation_status") == P3_FRACTIONAL_ALLOCATION]
    candidate_counts = Counter(int(row.get("eligible_candidate_count") or 0) for row in eligible)
    entropies = [float(row["candidate_ambiguity_entropy_nats"]) for row in eligible if row.get("candidate_ambiguity_entropy_nats") is not None]
    total_feature_mass = math.fsum(float(row.get("feature_evidence_mass") or 0.0) for row in eligible)
    total_allocated_mass = math.fsum(float(row.get("total_allocated_mass") or 0.0) for row in eligible)
    return {
        "allocation_contract_version": ALLOCATION_CONTRACT_VERSION,
        "allocation_status": allocation_context.get("allocation_status", "not_evaluable"),
        "eligible_feature_count": len(eligible),
        "total_feature_evidence_mass": total_feature_mass,
        "total_allocated_candidate_mass": total_allocated_mass,
        "mass_conservation_status": "passed" if math.isclose(total_feature_mass, total_allocated_mass, rel_tol=0.0, abs_tol=1e-12) else "not_evaluable_or_failed",
        "candidate_count_histogram": {str(count): candidate_counts[count] for count in sorted(candidate_counts)},
        "mean_candidate_ambiguity_entropy_nats": (math.fsum(entropies) / len(entropies)) if entropies else None,
        "max_candidate_ambiguity_entropy_nats": max(entropies) if entropies else None,
        "direct_kinase_attribution_status": "no_call_fractional_candidate_bookkeeping_is_not_single_kinase_attribution",
        "claim_boundary": "Aggregate P3 counts quantify unresolved candidate-set bookkeeping only; they do not identify, rank, or activate a kinase or support direct/causal/perturbation claims.",
        "excluded_fields": ["feature_id", "candidate_kinase", "accession", "site", "sequence", "peptide", "coordinate", "isoform", "edge_id", "reference_id", "source_label", "fractional_mass_by_named_kinase"],
    }


def attach_candidate_allocation(ledger: Mapping[str, Any], allocation_context: Mapping[str, Any]) -> dict[str, Any]:
    """Attach P3 full-ledger allocations without promoting direct kinase evidence."""

    result = {key: value for key, value in dict(ledger).items() if key not in {"feature_records", "summary"}}
    by_feature = allocation_context.get("feature_allocations") or {}
    records: list[dict[str, Any]] = []
    for raw_record in ledger.get("feature_records") or []:
        record = dict(raw_record)
        allocation = dict(by_feature.get(str(record.get("feature_id"))) or _allocation_record(record, None, "allocation_result_missing"))
        record["allocation_evidence"] = allocation
        masks = dict(record.get("unmatched_reason_masks") or {})
        masks["F7_multiple_candidate_kinases_prevent_single_attribution"] = (
            "p3_fractional_candidate_set_accounted_no_single_attribution"
            if allocation.get("allocation_status") == P3_FRACTIONAL_ALLOCATION
            else "not_assessed_or_no_valid_R3_candidate_set"
        )
        masks["F8_direct_match_success"] = "not_assessed_p3_fractional_allocation_cannot_create_direct_single_kinase_call"
        record["unmatched_reason_masks"] = masks
        direct = dict(record.get("direct_kinase_attribution") or {})
        reasons = [reason for reason in direct.get("reasons") or [] if reason != "curated_kinase_candidate_set_requires_p3_allocation_policy"]
        reasons.append(
            "fractional_curated_candidate_bookkeeping_not_a_direct_single_kinase_attribution"
            if allocation.get("allocation_status") == P3_FRACTIONAL_ALLOCATION
            else "no_valid_R3_curated_candidate_set_for_fractional_allocation"
        )
        direct["status"] = "no_call"
        direct["evidence_tier"] = "E_direct_kinase_no_call"
        direct["reasons"] = sorted(set(reasons))
        direct["promotion_guard"] = "p0_p1_p2_p3_tmm_rag_llm_cannot_promote_direct_kinase_evidence_tier_without_orthogonal_validation"
        record["direct_kinase_attribution"] = direct
        records.append(record)
    result["feature_records"] = records
    result["candidate_allocation"] = {
        key: value for key, value in allocation_context.items() if key != "feature_allocations"
    }
    result["candidate_allocation"]["compact_summary"] = compact_allocation_summary(allocation_context, records)
    from ptm_shared.kinase_evidence_ledger import compact_summary

    result["summary"] = compact_summary(result)
    return result


__all__ = [
    "ALLOCATION_CONTRACT_VERSION", "P3_FRACTIONAL_ALLOCATION", "P3_INVALID_CANDIDATE_SET", "P3_NO_CANDIDATE_SET",
    "allocate_candidate_sets", "attach_candidate_allocation", "compact_allocation_summary",
]
