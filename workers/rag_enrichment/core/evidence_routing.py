"""Deterministic evidence routing for RAG Enrichment.

The routing contract deliberately separates curated structured evidence from
literature escalation. It never classifies a non-detected literature match as
biological absence or novelty.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable


DB_ONLY = "db_only"
ABSTRACT_TARGETED = "abstract_targeted"
FULLTEXT_ESCALATED = "fulltext_escalated"
VALID_ROUTES = {DB_ONLY, ABSTRACT_TARGETED, FULLTEXT_ESCALATED}


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def build_phase_a_source_summary(
    phase_a_results: Dict[str, Any],
) -> list[Dict[str, Any]]:
    """Return UI-safe provenance for every structured database source in Phase A.

    ``_phase_a_state`` is supplied by the caller so cache hits, species skips and
    failures remain distinguishable from a successful query with no records.
    """
    config = (
        ("iptmnet", "iPTMnet", "sites_found", "sites"),
        ("uniprot", "UniProt", "uniprot_info", "records"),
        ("kegg", "KEGG", "kegg_pathways", "pathways"),
        ("reactome", "Reactome", "reactome_data", "pathways"),
        ("stringdb", "STRING", "interactions", "interactions"),
        ("biogrid", "BioGRID", "biogrid_data", "interactions"),
        ("hpa", "HPA", "hpa_data", "records"),
        ("gtex", "GTEx", "gtex_data", "records"),
    )
    summary: list[Dict[str, Any]] = []
    for key, label, field, unit in config:
        result = phase_a_results.get(key) or {}
        state = str(result.get("_phase_a_state") or "done")
        value = result.get(field)
        if key == "iptmnet":
            count = int(value or 0)
        elif key == "reactome":
            count = int((value or {}).get("total_count") or 0) if isinstance(value, dict) else 0
        elif key == "biogrid":
            if isinstance(value, dict):
                count = len(_as_list(value.get("interactions"))) or int(value.get("total_count") or 0)
            else:
                count = len(_as_list(value))
        elif isinstance(value, list):
            count = len(value)
        else:
            count = 1 if value else 0
        status = state
        if status == "done" and count == 0:
            status = "empty"
        summary.append({
            "key": key,
            "label": label,
            "status": status,  # done | cache_hit | empty | skip | error
            "count": count,
            "unit": unit,
        })
    return summary


def format_phase_a_source_summary(summary: Iterable[Dict[str, Any]]) -> str:
    """Create a compact legacy-progress suffix while structured metadata remains canonical."""
    tokens: list[str] = []
    for source in summary:
        label = str(source.get("label") or source.get("key") or "DB")
        status = str(source.get("status") or "")
        count = int(source.get("count") or 0)
        if status == "skip":
            token = f"{label}:skip"
        elif status == "cache_hit":
            token = f"{label}:{count}↻"
        elif status == "error":
            token = f"{label}:error"
        elif status == "empty":
            token = f"{label}:0"
        else:
            token = f"{label}:{count}"
        tokens.append(token)
    return "; ".join(tokens)


def build_structured_database_packet(
    *,
    gene: str,
    position: str,
    species: str,
    iptmnet_data: Dict[str, Any] | None,
    uniprot_info: Dict[str, Any] | None,
    kegg_pathways: Iterable[Any] | None,
    reactome_data: Dict[str, Any] | None,
    interactions: Iterable[Any] | None,
) -> Dict[str, Any]:
    """Create a compact, provenance-first structured evidence packet."""
    iptmnet_data = iptmnet_data or {}
    uniprot_info = uniprot_info or {}
    reactome_data = reactome_data or {}
    pathways = _as_list(kegg_pathways)
    interaction_list = _as_list(interactions)
    novelty = iptmnet_data.get("novelty") or {}
    sites_found = int(iptmnet_data.get("sites_found") or 0)
    exact_site_known = sites_found > 0 and str(novelty.get("status", "")).upper() != "NOVEL"

    return {
        "packet_version": "database_first_v1",
        "gene": gene,
        "position": position,
        "species": species,
        "iptmnet": {
            "sites_found": sites_found,
            "novelty_status": novelty.get("status", ""),
            "pmids": _as_list(novelty.get("pmids"))[:5],
            "exact_site_known": exact_site_known,
        },
        "uniprot": {
            "available": bool(uniprot_info),
            "function_summary": str(uniprot_info.get("function_summary") or "")[:500],
            "subcellular_location": _as_list(uniprot_info.get("subcellular_location")),
        },
        "pathway_context": {
            "kegg_pathway_count": len(pathways),
            "reactome_signaling_count": int(reactome_data.get("signaling_count") or 0),
        },
        "interaction_context": {"string_interaction_count": len(interaction_list)},
    }


def decide_evidence_route(
    *,
    ptm: Dict[str, Any],
    classification: Dict[str, Any],
    structured_packet: Dict[str, Any],
    context: Dict[str, Any] | None,
) -> Dict[str, Any]:
    """Route a site to structured-only or selectively escalated evidence.

    Existing classification labels are used rather than introducing new numeric
    thresholds. A caller may explicitly request a route through
    ``evidence_route_override`` or ``requires_fulltext``.
    """
    context = context or {}
    override = str(ptm.get("evidence_route_override") or "").strip().lower()
    if override in VALID_ROUTES:
        return {
            "route": override,
            "reason_codes": ["explicit_override"],
            "structured_packet_complete": True,
            "literature_required": override != DB_ONLY,
        }

    if bool(ptm.get("requires_fulltext") or ptm.get("fulltext_escalated")):
        return {
            "route": FULLTEXT_ESCALATED,
            "reason_codes": ["explicit_fulltext_request"],
            "structured_packet_complete": True,
            "literature_required": True,
        }

    reasons: list[str] = []
    iptmnet = structured_packet.get("iptmnet") or {}
    pathway_context = structured_packet.get("pathway_context") or {}
    exact_site_known = bool(iptmnet.get("exact_site_known"))
    significance = str(classification.get("significance") or "").lower()
    has_context = any(
        context.get(key)
        for key in ("treatment", "cell_type", "tissue", "biological_question", "special_conditions")
    )
    explicit_literature_request = bool(
        ptm.get("requires_literature")
        or ptm.get("requires_literature_validation")
        or ptm.get("literature_escalated")
    )
    selection_mode = str(ptm.get("rag_selection_mode") or "").strip().lower()
    broad_annotation_mode = selection_mode in {"all", "minor"}

    if broad_annotation_mode:
        reasons.append("broad_annotation_mode_database_first")

    if not exact_site_known:
        reasons.append("exact_site_not_curated")
    if significance == "high":
        reasons.append("high_signal_priority")
    special_reference_context = bool(
        ptm.get("is_receptor") or ptm.get("is_transgene") or ptm.get("mixed_species_reference")
    )
    if special_reference_context:
        reasons.append("reference_or_receptor_context")
    if not pathway_context.get("kegg_pathway_count") and not pathway_context.get("reactome_signaling_count"):
        reasons.append("limited_curated_pathway_context")

    # An uncurated site or order-level experiment context alone is not enough:
    # a dense time-course order normally provides a treatment/context for every
    # row. Using that global context as a trigger would recreate the old
    # PubMed-first fan-out. Literature is reserved for a high observed signal,
    # explicit per-site request, or transgene/receptor reference complication.
    evidence_gap_needs_context = not exact_site_known and (
        (significance == "high" and not broad_annotation_mode)
        or explicit_literature_request
        or special_reference_context
    )
    high_context_claim = (
        exact_site_known
        and significance == "high"
        and has_context
        and not broad_annotation_mode
    )
    if (
        evidence_gap_needs_context
        or high_context_claim
        or special_reference_context
        or explicit_literature_request
    ):
        if explicit_literature_request:
            reasons.append("explicit_literature_request")
        return {
            "route": ABSTRACT_TARGETED,
            "reason_codes": reasons,
            "structured_packet_complete": False,
            "literature_required": True,
        }

    return {
        "route": DB_ONLY,
        "reason_codes": reasons or ["curated_site_and_context_sufficient"],
        "structured_packet_complete": True,
        "literature_required": False,
    }
