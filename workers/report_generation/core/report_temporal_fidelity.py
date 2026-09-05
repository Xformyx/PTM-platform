"""Deterministic fidelity checks for temporal numerical evidence in Report drafts."""

from __future__ import annotations

import re
from typing import Any, Mapping


_DATA_LABEL_PATTERN = re.compile(
    r"\[?(DATA-(?:TEMPORAL-SUMMARY|KINASE-ATTRIBUTION-READINESS|TEMPORAL-PRECEDENCE|DYNAMIC-SUMMARY|DYNAMIC-WAVE-\d+|TMM-KINASE-\d+|TMM-UNCERTAINTY|CROSS-LAYER-\d+|COUNTEREVIDENCE-\d+))\]?"
)
_DIRECT_EDGE_CLAIM = re.compile(
    r"\b(?:directly activates?|direct regulation|autophosphorylation|direct biochemical evidence|"
    r"direct kinase(?:[- ]substrate)?(?: relationship| regulation| attribution)?|"
    r"regulates? downstream (?:substrates?|targets?))\b",
    flags=re.IGNORECASE,
)
_CAUSAL_ORDER_CLAIM = re.compile(
    r"\b(?:causes?|drives?|proves?|kinase switching|causal propagation|signal propagation|"
    r"feedback loop|phosphatase activation|dominant kinase|structured signal flow)\b",
    flags=re.IGNORECASE,
)
_LITERATURE_CONTEXT_QUALIFIER = re.compile(
    r"\b(?:literature|published|previously reported|canonical|established context|prior work)\b",
    flags=re.IGNORECASE,
)


def audit_report_temporal_fidelity(
    draft_text: str,
    packet: Mapping[str, Any] | None,
    *,
    section_type: str = "general",
) -> dict:
    """Audit a draft against the deterministic temporal evidence packet.

    The audit does not score biological truth. It determines whether an LLM draft
    traced temporal claims to supplied numerical records and whether it used
    prohibited causal language near those records.
    """
    packet = dict(packet or {})
    valid_ids = {
        str(record.get("evidence_id"))
        for record in (packet.get("records") or [])
        if isinstance(record, Mapping) and record.get("evidence_id")
    }
    cited_ids = _DATA_LABEL_PATTERN.findall(draft_text or "")
    unique_cited_ids = sorted(set(cited_ids))
    unsupported_ids = sorted(set(unique_cited_ids) - valid_ids)

    section_plan = dict(packet.get("section_plan") or {})
    mechanism_context_allowed = bool(section_plan.get("mechanism_context_allowed"))
    observation_only_claim_ceiling = bool(section_plan.get("observation_only_claim_ceiling", False))
    unsafe_claims: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", draft_text or ""):
        has_direct_edge_claim = bool(_DIRECT_EDGE_CLAIM.search(sentence))
        has_causal_order_claim = bool(_CAUSAL_ORDER_CLAIM.search(sentence))
        has_explicit_negation = bool(re.search(r"\b(?:not|no|without|does not|did not)\b", sentence, flags=re.IGNORECASE))
        literature_context_only = bool(_LITERATURE_CONTEXT_QUALIFIER.search(sentence))
        if has_direct_edge_claim and not has_explicit_negation and (
            _DATA_LABEL_PATTERN.search(sentence)
            or not mechanism_context_allowed
            or observation_only_claim_ceiling
        ):
            unsafe_claims.append(sentence.strip()[:500])
        elif has_causal_order_claim and not has_explicit_negation and not literature_context_only and (
            _DATA_LABEL_PATTERN.search(sentence)
            or not mechanism_context_allowed
            or observation_only_claim_ceiling
        ):
            unsafe_claims.append(sentence.strip()[:500])

    cited_dynamic = [identifier for identifier in unique_cited_ids if identifier.startswith("DATA-DYNAMIC")]
    cited_precedence = [identifier for identifier in unique_cited_ids if identifier == "DATA-TEMPORAL-PRECEDENCE"]
    cited_tmm = [identifier for identifier in unique_cited_ids if identifier.startswith("DATA-TMM")]
    cited_cross_layer = [identifier for identifier in unique_cited_ids if identifier.startswith("DATA-CROSS-LAYER")]
    cited_counterevidence = [identifier for identifier in unique_cited_ids if identifier.startswith("DATA-COUNTEREVIDENCE")]
    available_groups = {
        "temporal_precedence": "DATA-TEMPORAL-PRECEDENCE" in valid_ids,
        "dynamic": any(identifier.startswith("DATA-DYNAMIC") for identifier in valid_ids),
        "tmm": any(identifier.startswith("DATA-TMM-KINASE") for identifier in valid_ids),
        "cross_layer": any(identifier.startswith("DATA-CROSS-LAYER") for identifier in valid_ids),
        "counterevidence": any(identifier.startswith("DATA-COUNTEREVIDENCE") for identifier in valid_ids),
    }
    cited_groups = {
        "temporal_precedence": bool(cited_precedence),
        "dynamic": bool(cited_dynamic),
        "tmm": bool(cited_tmm),
        "cross_layer": bool(cited_cross_layer),
        "counterevidence": bool(cited_counterevidence),
    }
    mandatory_groups = (
        "temporal_precedence", "dynamic", "tmm", "cross_layer", "counterevidence"
    ) if section_type in {"results", "discussion"} else ()
    missing_required_groups = [
        group for group in mandatory_groups if available_groups[group] and not cited_groups[group]
    ]
    status = "pass"
    if unsupported_ids or unsafe_claims or missing_required_groups:
        status = "review_required"
    elif packet.get("status") == "available" and not unique_cited_ids:
        status = "untraced"

    return {
        "contract_version": "report_temporal_fidelity.v6",
        "section_type": section_type,
        "status": status,
        "packet_status": packet.get("status", "unavailable"),
        "available_record_count": len(valid_ids),
        "cited_record_count": len(unique_cited_ids),
        "cited_record_ids": unique_cited_ids,
        "cited_dynamic_record_count": len(cited_dynamic),
        "available_temporal_precedence_record_count": int(available_groups["temporal_precedence"]),
        "cited_temporal_precedence_record_count": len(cited_precedence),
        "temporal_precedence_trace_status": (
            "cited" if cited_precedence else "untraced" if available_groups["temporal_precedence"] else "unavailable"
        ),
        "cited_tmm_record_count": len(cited_tmm),
        "cited_cross_layer_record_count": len(cited_cross_layer),
        "cited_counterevidence_record_count": len(cited_counterevidence),
        "available_evidence_groups": available_groups,
        "missing_required_groups": missing_required_groups,
        "unsupported_record_ids": unsupported_ids,
        "unsafe_temporal_claim_count": len(unsafe_claims),
        "unsafe_temporal_claim_examples": unsafe_claims,
        "mechanism_context_allowed": mechanism_context_allowed,
        "observation_only_claim_ceiling": observation_only_claim_ceiling,
        "recommended_action": (
            "constrained_rewrite_required" if unsafe_claims or missing_required_groups
            else "release_candidate"
        ),
        "claim_boundary": "Audit measures evidence-traceability and wording, not biological correctness or causality.",
    }


def strip_internal_data_labels(text: str) -> str:
    """Remove internal DATA labels after the draft has been audited."""
    return _DATA_LABEL_PATTERN.sub("", text or "").replace("  ", " ")
