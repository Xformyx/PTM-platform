"""Deterministic data-grounded biological synthesis inputs for Report writing.

This module does not perform LLM inference, use RAG prose as data, or infer
kinase-to-site edges.  It turns already computed Order measurements into a
small, traceable packet that a section writer can use to ask a biologically
useful question of the selected RAG collections.
"""

from __future__ import annotations

from collections import defaultdict
import math
import re
from typing import Any, Mapping, Sequence


BIOLOGICAL_SYNTHESIS_CONTRACT = "biological_synthesis_packet.v1"


def _as_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _time_sort_key(label: Any) -> tuple[float, str]:
    text = str(label or "")
    match = re.search(r"(\d+(?:\.\d+)?)\s*(min|m|h|hr|hour)?", text, re.IGNORECASE)
    if not match:
        return (float("inf"), text)
    value = float(match.group(1))
    unit = (match.group(2) or "").lower()
    if unit in {"h", "hr", "hour"}:
        value *= 60
    return (value, text)


def _profile_label(points: Sequence[Mapping[str, Any]]) -> str:
    values = [point.get("ptm_relative_log2fc") for point in points]
    finite = [value for value in values if isinstance(value, (int, float)) and math.isfinite(value)]
    if len(finite) < 2:
        return "single-observation"
    peak_index = max(range(len(finite)), key=lambda index: abs(finite[index]))
    if peak_index == 0:
        return "early-maximal"
    if peak_index == len(finite) - 1:
        return "late-maximal"
    if abs(finite[peak_index]) >= abs(finite[0]) + 0.4 and abs(finite[peak_index]) >= abs(finite[-1]) + 0.4:
        return "transient-intermediate"
    if finite[-1] > finite[0] + 0.4:
        return "progressive-increase"
    if finite[-1] < finite[0] - 0.4:
        return "progressive-decrease"
    return "distributed-or-stable"


def _candidate_cards(vector_rows: Sequence[Mapping[str, Any]], *, limit: int) -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in vector_rows or []:
        if not isinstance(row, Mapping):
            continue
        gene = str(row.get("gene") or row.get("Gene.Name") or "").strip()
        position = str(row.get("position") or row.get("PTM_Position") or "").strip()
        if not gene or gene.lower() in {"unknown", "nan"}:
            continue
        ptm_value = _as_float(row.get("ptm_relative_log2fc", row.get("PTM_Relative_Log2FC")))
        protein_value = _as_float(row.get("protein_log2fc", row.get("Protein_Log2FC")))
        grouped[(gene, position)].append({
            "condition": str(row.get("condition") or row.get("Condition") or "unspecified"),
            "ptm_relative_log2fc": ptm_value,
            "protein_log2fc": protein_value,
            "q_value": _as_float(row.get("q_value", row.get("Q_Value"))),
        })

    cards: list[dict] = []
    for (gene, position), points in grouped.items():
        points = sorted(points, key=lambda point: _time_sort_key(point.get("condition")))
        finite_ptm = [abs(point["ptm_relative_log2fc"]) for point in points if point["ptm_relative_log2fc"] is not None]
        if not finite_ptm:
            continue
        max_index = max(
            range(len(points)),
            key=lambda index: abs(points[index]["ptm_relative_log2fc"] or 0.0),
        )
        cards.append({
            "gene": gene,
            "position": position or "site_not_specified",
            "trajectory": points,
            "profile_label": _profile_label(points),
            "peak_condition": points[max_index]["condition"],
            "max_abs_ptm_log2fc": round(max(finite_ptm), 4),
            "source": "vector_plot_raw_data",
        })
    return sorted(
        cards,
        key=lambda card: (-card["max_abs_ptm_log2fc"], card["gene"], card["position"]),
    )[:max(1, int(limit))]


def _pathway_anchors(network_analysis: Mapping[str, Any] | None, *, limit: int) -> list[dict]:
    network_analysis = dict(network_analysis or {})
    expansion = network_analysis.get("pathway_expansion") or {}
    summaries = expansion.get("summaries") or []
    anchors: list[dict] = []
    if isinstance(summaries, list):
        for row in summaries:
            if not isinstance(row, Mapping) or not row.get("pathway"):
                continue
            anchors.append({
                "pathway": str(row.get("pathway")),
                "term": str(row.get("term") or "modulated"),
                "peak_nes": _as_float(row.get("peak_nes")),
                "peak_q": _as_float(row.get("peak_q")),
                "n_direct": row.get("n_direct"),
            })
    if not anchors:
        for name in network_analysis.get("fig1_pathway_names") or []:
            anchors.append({"pathway": str(name), "term": "pathway annotation", "peak_nes": None, "peak_q": None, "n_direct": None})
    return anchors[:max(1, int(limit))]


def build_biological_synthesis_packet(
    *,
    experimental_context: Mapping[str, Any] | None,
    vector_plot_raw_data: Sequence[Mapping[str, Any]] | None,
    parsed_ptms: Sequence[Mapping[str, Any]] | None,
    network_analysis: Mapping[str, Any] | None,
    temporal_evidence_packet: Mapping[str, Any] | None,
    candidate_limit: int = 20,
    pathway_limit: int = 8,
) -> dict:
    """Build a compact, quantitative packet for biological narrative synthesis.

    The packet intentionally preserves measured genes/sites and quantitative values
    already available to the Report writer, but excludes P0–P3 full-ledger identity
    and candidate-edge records.  Direct kinase evidence is represented only by the
    compact readiness note in ``temporal_evidence_packet``.
    """
    context = dict(experimental_context or {})
    vector_rows = list(vector_plot_raw_data or [])
    candidates = _candidate_cards(vector_rows, limit=candidate_limit)
    pathways = _pathway_anchors(network_analysis, limit=pathway_limit)
    valid_identity_rows = [
        row for row in vector_rows
        if isinstance(row, Mapping)
        and str(row.get("gene") or row.get("Gene.Name") or "").strip().lower() not in {"", "unknown", "nan"}
    ]
    genes = {str(row.get("gene") or row.get("Gene.Name") or "").strip() for row in valid_identity_rows}
    sites = {
        (str(row.get("gene") or row.get("Gene.Name") or "").strip(), str(row.get("position") or row.get("PTM_Position") or "").strip())
        for row in valid_identity_rows
    }

    finite_ptm = [
        _as_float(row.get("ptm_relative_log2fc", row.get("PTM_Relative_Log2FC")))
        for row in vector_rows if isinstance(row, Mapping)
    ]
    finite_ptm = [value for value in finite_ptm if value is not None]
    temporal = dict(temporal_evidence_packet or {})
    section_plan = dict(temporal.get("section_plan") or {})
    return {
        "contract_version": BIOLOGICAL_SYNTHESIS_CONTRACT,
        "study_frame": {
            "cell_model": context.get("tissue") or context.get("cell_type") or "not specified",
            "organism": context.get("organism") or "not specified",
            "treatment": context.get("treatment") or "not specified",
            "timepoints": list(context.get("timepoints") or context.get("conditions") or []),
            "biological_question": context.get("biological_question") or "",
            "special_conditions": context.get("special_conditions") or "",
        },
        "quantitative_landscape": {
            "vector_row_count": len(vector_rows),
            "unique_site_count": len(sites),
            "unique_gene_count": len(genes),
            "parsed_ptm_count": len(list(parsed_ptms or [])),
            "maximum_absolute_ptm_log2fc": round(max((abs(value) for value in finite_ptm), default=0.0), 4),
        },
        "candidate_observation_cards": candidates,
        "pathway_anchors": pathways,
        "temporal_context": {
            "packet_status": temporal.get("status", "unavailable"),
            "dynamic_context_allowed": bool(section_plan.get("dynamic_context_allowed")),
            "directed_temporal_context_allowed": bool(section_plan.get("directed_temporal_context_allowed")),
            "mechanism_context_allowed": bool(section_plan.get("mechanism_context_allowed")),
        },
        "scope": {
            "direct_kinase_attribution": "Use only the compact P0–P3 readiness note; do not infer a direct kinase–site edge from this packet.",
            "literature_role": "Literature may explain, compare, support, or challenge a biological model; it does not convert a literature edge into an Order-specific observation.",
        },
    }


def build_data_anchored_rag_queries(packet: Mapping[str, Any] | None, *, section_type: str) -> list[dict]:
    """Return deduplicated, role-labelled RAG queries derived only from packet data."""
    packet = dict(packet or {})
    frame = dict(packet.get("study_frame") or {})
    treatment = str(frame.get("treatment") or "").strip()
    cell_model = str(frame.get("cell_model") or "").strip()
    question = str(frame.get("biological_question") or "").strip()
    ptm_label = "phosphoproteomics"
    queries: list[dict] = []
    if treatment or cell_model or question:
        queries.append({
            "role": "study_context",
            "query": " ".join(part for part in [cell_model, treatment, ptm_label, question] if part)[:500],
        })
    if section_type in {"results", "discussion", "conclusion", "abstract"}:
        for anchor in (packet.get("pathway_anchors") or [])[:5]:
            pathway = str(anchor.get("pathway") or "").strip()
            if pathway:
                queries.append({
                    "role": "pathway_comparison",
                    "query": " ".join(part for part in [treatment, pathway, "phosphorylation temporal response"] if part)[:500],
                    "anchor": pathway,
                })
        for candidate in (packet.get("candidate_observation_cards") or [])[:6]:
            gene = str(candidate.get("gene") or "").strip()
            if gene:
                queries.append({
                    "role": "candidate_biology",
                    "query": " ".join(part for part in [gene, treatment, "phosphorylation"] if part)[:500],
                    "anchor": gene,
                })
        if len(frame.get("timepoints") or []) > 1:
            queries.append({
                "role": "temporal_programme",
                "query": " ".join(part for part in [treatment, cell_model, "time-course phosphoproteomics temporal response"] if part)[:500],
            })

    seen: set[str] = set()
    unique: list[dict] = []
    for row in queries:
        query = str(row.get("query") or "").strip()
        if not query:
            continue
        key = query.lower()
        if key not in seen:
            seen.add(key)
            unique.append({**row, "query": query})
    return unique


def format_biological_synthesis_packet_for_llm(packet: Mapping[str, Any] | None, *, section_type: str) -> str:
    """Format a human-readable packet for Results/Discussion/Abstract writers."""
    packet = dict(packet or {})
    if not packet:
        return ""
    frame = dict(packet.get("study_frame") or {})
    landscape = dict(packet.get("quantitative_landscape") or {})
    lines = [
        "=== DATA-GROUNDED BIOLOGICAL SYNTHESIS PACKET ===",
        "Use this packet as the primary bridge from measured PTM data to biological interpretation.",
        "Write a substantive model of the actual study system. Separate measured observations, computed annotations, literature comparison, and testable hypotheses.",
        f"Study frame: cell model={frame.get('cell_model')}; organism={frame.get('organism')}; treatment={frame.get('treatment')}; timepoints={', '.join(map(str, frame.get('timepoints') or [])) or 'not specified'}.",
        f"Biological question: {frame.get('biological_question') or 'not specified'}",
        f"Quantitative landscape: vector rows={landscape.get('vector_row_count', 0)}; unique sites={landscape.get('unique_site_count', 0)}; unique genes={landscape.get('unique_gene_count', 0)}; max |PTM log2FC|={landscape.get('maximum_absolute_ptm_log2fc', 0)}.",
        "",
        "Observed candidate trajectories (ranked by measured |PTM log2FC|; these are not direct kinase assignments):",
    ]
    for card in (packet.get("candidate_observation_cards") or [])[:20]:
        trajectory = "; ".join(
            f"{point.get('condition')}: PTM={point.get('ptm_relative_log2fc') if point.get('ptm_relative_log2fc') is not None else 'NA'}, protein={point.get('protein_log2fc') if point.get('protein_log2fc') is not None else 'NA'}"
            for point in card.get("trajectory") or []
        )
        lines.append(
            f"- {card.get('gene')} {card.get('position')}: profile={card.get('profile_label')}; peak={card.get('peak_condition')}; {trajectory}"
        )
    lines.append("")
    lines.append("Pathway anchors from the measured enrichment output:")
    for anchor in (packet.get("pathway_anchors") or [])[:8]:
        text = f"- {anchor.get('pathway')}: term={anchor.get('term')}"
        if anchor.get("peak_nes") is not None:
            text += f"; peak NES={anchor.get('peak_nes')}"
        if anchor.get("peak_q") is not None:
            text += f"; q={anchor.get('peak_q')}"
        if anchor.get("n_direct") is not None:
            text += f"; direct-site support={anchor.get('n_direct')}"
        lines.append(text)
    lines.extend([
        "",
        "Required synthesis pattern for every major biological paragraph:",
        "measured observation → pathway/candidate context → cited literature comparison → biological model or alternative explanation → discriminating follow-up measurement.",
        "Use strong but calibrated terms such as 'defines an early programme', 'is consistent with', 'aligns with', 'contrasts with', 'prioritizes', or 'generates a testable model'.",
        "Do not turn a literature relationship, motif score, Wave co-membership, lag, or pathway diagram into an Order-specific direct kinase–site or causal edge.",
        "=== END DATA-GROUNDED BIOLOGICAL SYNTHESIS PACKET ===",
    ])
    return "\n".join(lines)
