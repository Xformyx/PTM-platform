"""Deterministic fidelity checks for temporal numerical evidence in Report drafts."""

from __future__ import annotations

import re
from typing import Any, Mapping


_DATA_LABEL_PATTERN = re.compile(r"\[?(DATA-(?:TEMPORAL-SUMMARY|DYNAMIC-SUMMARY|DYNAMIC-WAVE-\d+|CROSS-LAYER-\d+))\]?")
_UNSAFE_TEMPORAL_CLAIM = re.compile(
    r"\b(?:causes?|drives?|directly activates?|proves?|kinase switching|causal propagation)\b",
    flags=re.IGNORECASE,
)


def audit_report_temporal_fidelity(
    draft_text: str,
    packet: Mapping[str, Any] | None,
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

    unsafe_claims: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", draft_text or ""):
        if _DATA_LABEL_PATTERN.search(sentence) and _UNSAFE_TEMPORAL_CLAIM.search(sentence):
            unsafe_claims.append(sentence.strip()[:500])

    cited_dynamic = [identifier for identifier in unique_cited_ids if identifier.startswith("DATA-DYNAMIC")]
    cited_cross_layer = [identifier for identifier in unique_cited_ids if identifier.startswith("DATA-CROSS-LAYER")]
    status = "pass"
    if unsupported_ids or unsafe_claims:
        status = "review_required"
    elif packet.get("status") == "available" and not unique_cited_ids:
        status = "untraced"

    return {
        "contract_version": "report_temporal_fidelity.v1",
        "status": status,
        "packet_status": packet.get("status", "unavailable"),
        "available_record_count": len(valid_ids),
        "cited_record_count": len(unique_cited_ids),
        "cited_record_ids": unique_cited_ids,
        "cited_dynamic_record_count": len(cited_dynamic),
        "cited_cross_layer_record_count": len(cited_cross_layer),
        "unsupported_record_ids": unsupported_ids,
        "unsafe_temporal_claim_count": len(unsafe_claims),
        "unsafe_temporal_claim_examples": unsafe_claims,
        "claim_boundary": "Audit measures evidence-traceability and wording, not biological correctness or causality.",
    }


def strip_internal_data_labels(text: str) -> str:
    """Remove internal DATA labels after the draft has been audited."""
    return _DATA_LABEL_PATTERN.sub("", text or "").replace("  ", " ")
