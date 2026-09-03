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


BIOLOGICAL_SYNTHESIS_CONTRACT = "biological_synthesis_packet.v2"
CANDIDATE_DISCOVERY_PACKET_CONTRACT = "candidate_discovery_packet.v1"
DEFAULT_CANDIDATE_BUCKET_QUOTAS = {
    "canonical_context_anchor": 6,
    "annotation_negative_discovery": 10,
    "special_discovery": 4,
}
DEFAULT_PTM_PROTEIN_DECOUPLING_THRESHOLD = 0.75


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


def _feature_key(gene: Any, position: Any) -> str:
    return f"{str(gene or '').strip().upper()}_{str(position or '').strip().upper()}"


def _annotation_context_index(global_kinase_modules: Mapping[str, Any] | None) -> dict[str, str]:
    """Return legacy annotation context without treating it as a P2 direct edge."""
    statuses: dict[str, str] = {}
    for module in (dict(global_kinase_modules or {}).get("kinase_modules") or []):
        if not isinstance(module, Mapping):
            continue
        for member in (module.get("members") or []):
            if not isinstance(member, Mapping):
                continue
            key = str(member.get("key") or _feature_key(member.get("gene"), member.get("position"))).strip()
            if not key or key == "_":
                continue
            membership = str(member.get("membership") or "").strip().lower()
            if membership == "confirmed":
                statuses[key] = "known_annotation_context"
            elif membership == "inferred" and key not in statuses:
                statuses[key] = "motif_context_only"
    return statuses


def _multisite_divergent_feature_keys(records: Sequence[Mapping[str, Any]] | None) -> set[str]:
    """Extract site keys from canonical divergence pairs; no new divergence is inferred here."""
    keys: set[str] = set()
    for row in records or []:
        if not isinstance(row, Mapping):
            continue
        if row.get("is_divergent") is False:
            continue
        gene = row.get("gene") or row.get("Gene.Name")
        for field in ("siteA", "siteB", "source_site", "target_site"):
            site = row.get(field)
            if isinstance(site, Mapping):
                key = str(site.get("key") or _feature_key(gene, site.get("position") or site.get("site"))).strip()
                if key and key != "_":
                    keys.add(key)
            elif site:
                keys.add(_feature_key(gene, site))
        for field in ("site_a_key", "site_b_key", "feature_key", "key"):
            key = str(row.get(field) or "").strip()
            if key:
                keys.add(key)
    return keys


def _row_temporal_labels(row: Mapping[str, Any]) -> list[str]:
    labels: list[str] = []
    for source, label in (
        (row.get("static_wave_id") or row.get("wave_id"), "static_wave"),
        (row.get("dynamic_transition_status") or row.get("dynamic_co_wave_status"), "dynamic_context"),
        (row.get("replicate_count") or row.get("n_replicates"), "replicate_context"),
    ):
        text = str(source or "").strip()
        if text and text.lower() not in {"none", "nan", "not_evaluable", "not_recorded"}:
            labels.append(label)
    return sorted(set(labels))


def _card_sort_key(card: Mapping[str, Any]) -> tuple:
    components = dict(card.get("selection_components") or {})
    best_q = components.get("best_q_value")
    best_q_key = float(best_q) if isinstance(best_q, (int, float)) and math.isfinite(best_q) else float("inf")
    return (
        -int(components.get("finite_condition_count") or 0),
        -float(components.get("max_abs_ptm_log2fc") or 0.0),
        -int(components.get("finite_q_value_count") or 0),
        best_q_key,
        -float(components.get("max_abs_ptm_protein_contrast") or 0.0),
        -int(components.get("temporal_context_count") or 0),
        str(card.get("gene") or ""),
        str(card.get("position") or ""),
    )


def _select_candidate_cards(
    cards: Sequence[Mapping[str, Any]], *, limit: int, bucket_quotas: Mapping[str, int] | None,
) -> tuple[list[dict], dict]:
    quotas = {**DEFAULT_CANDIDATE_BUCKET_QUOTAS, **dict(bucket_quotas or {})}
    limit = max(1, int(limit))
    cards_by_bucket: dict[str, list[dict]] = defaultdict(list)
    for card in cards:
        cards_by_bucket[str(card.get("primary_bucket") or "annotation_negative_discovery")].append(dict(card))
    for bucket in cards_by_bucket:
        cards_by_bucket[bucket].sort(key=_card_sort_key)

    selected: list[dict] = []
    selected_keys: set[str] = set()
    requested = {
        "canonical_context_anchor": max(0, int(quotas.get("canonical_context_anchor") or 0)),
        "annotation_negative_discovery": max(0, int(quotas.get("annotation_negative_discovery") or 0)),
        "special_discovery": max(0, int(quotas.get("special_discovery") or 0)),
    }
    bucket_groups = {
        "canonical_context_anchor": ["canonical_context_anchor"],
        "annotation_negative_discovery": ["annotation_negative_discovery"],
        "special_discovery": ["multi_site_divergent", "ptm_protein_decoupled"],
    }
    selected_by_quota: dict[str, int] = {}
    for quota_bucket, source_buckets in bucket_groups.items():
        picked = 0
        pool = sorted(
            (card for source in source_buckets for card in cards_by_bucket.get(source, [])),
            key=_card_sort_key,
        )
        for card in pool:
            if len(selected) >= limit or picked >= requested[quota_bucket]:
                break
            key = _feature_key(card.get("gene"), card.get("position"))
            if key in selected_keys:
                continue
            selected.append(card)
            selected_keys.add(key)
            picked += 1
        selected_by_quota[quota_bucket] = picked

    all_cards = sorted((dict(card) for card in cards), key=_card_sort_key)
    before_backfill = len(selected)
    for card in all_cards:
        if len(selected) >= limit:
            break
        key = _feature_key(card.get("gene"), card.get("position"))
        if key in selected_keys:
            continue
        selected.append(card)
        selected_keys.add(key)

    selected.sort(key=_card_sort_key)
    return selected, {
        "candidate_capacity": limit,
        "requested_bucket_quotas": requested,
        "selected_by_quota": selected_by_quota,
        "backfill_count": len(selected) - before_backfill,
        "selected_by_primary_bucket": {
            bucket: sum(1 for card in selected if card.get("primary_bucket") == bucket)
            for bucket in sorted({str(card.get("primary_bucket")) for card in selected})
        },
    }


def _candidate_cards(
    vector_rows: Sequence[Mapping[str, Any]], *, limit: int,
    global_kinase_modules: Mapping[str, Any] | None = None,
    multisite_divergence: Sequence[Mapping[str, Any]] | None = None,
    bucket_quotas: Mapping[str, int] | None = None,
    ptm_protein_decoupling_threshold: float = DEFAULT_PTM_PROTEIN_DECOUPLING_THRESHOLD,
) -> tuple[list[dict], dict]:
    annotation_index = _annotation_context_index(global_kinase_modules)
    divergent_keys = _multisite_divergent_feature_keys(multisite_divergence)
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
            "temporal_labels": _row_temporal_labels(row),
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
        finite_q_values = [point["q_value"] for point in points if point["q_value"] is not None]
        finite_contrasts = [
            abs(point["ptm_relative_log2fc"] - point["protein_log2fc"])
            for point in points
            if point["ptm_relative_log2fc"] is not None and point["protein_log2fc"] is not None
        ]
        feature_key = _feature_key(gene, position)
        annotation_context = annotation_index.get(feature_key, "annotation_negative")
        temporal_labels = sorted({label for point in points for label in point.get("temporal_labels", [])})
        is_divergent = feature_key in divergent_keys
        max_contrast = max(finite_contrasts, default=0.0)
        is_decoupled = bool(finite_contrasts) and max_contrast >= ptm_protein_decoupling_threshold
        if is_divergent:
            primary_bucket = "multi_site_divergent"
            primary_rationale = "computed within-gene multi-site divergence"
        elif is_decoupled:
            primary_bucket = "ptm_protein_decoupled"
            primary_rationale = "measured PTM–protein contrast meets the declared discovery threshold"
        elif annotation_context == "annotation_negative":
            primary_bucket = "annotation_negative_discovery"
            primary_rationale = "no known or motif-context kinase annotation was supplied by the legacy annotation module"
        else:
            primary_bucket = "canonical_context_anchor"
            primary_rationale = "known or motif-context annotation is available as biological context, not direct edge proof"
        discovery_reasons = [primary_rationale]
        if annotation_context == "annotation_negative" and primary_bucket != "annotation_negative_discovery":
            discovery_reasons.append("annotation-negative kinase context")
        cards.append({
            "gene": gene,
            "position": position or "site_not_specified",
            "trajectory": points,
            "profile_label": _profile_label(points),
            "peak_condition": points[max_index]["condition"],
            "max_abs_ptm_log2fc": round(max(finite_ptm), 4),
            "source": "vector_plot_raw_data",
            "primary_bucket": primary_bucket,
            "annotation_context": annotation_context,
            "discovery_rationale": discovery_reasons,
            "selection_components": {
                "finite_condition_count": len(finite_ptm),
                "max_abs_ptm_log2fc": round(max(finite_ptm), 4),
                "finite_q_value_count": len(finite_q_values),
                "best_q_value": round(min(finite_q_values), 8) if finite_q_values else None,
                "max_abs_ptm_protein_contrast": round(max_contrast, 4),
                "temporal_context_count": len(temporal_labels),
                "temporal_context_labels": temporal_labels,
                "multisite_divergent": is_divergent,
                "ptm_protein_decoupled": is_decoupled,
                "ptm_protein_decoupling_threshold": ptm_protein_decoupling_threshold,
            },
        })
    return _select_candidate_cards(cards, limit=limit, bucket_quotas=bucket_quotas)


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
    global_kinase_modules: Mapping[str, Any] | None = None,
    multisite_divergence: Sequence[Mapping[str, Any]] | None = None,
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
    candidates, candidate_selection = _candidate_cards(
        vector_rows,
        limit=candidate_limit,
        global_kinase_modules=global_kinase_modules,
        multisite_divergence=multisite_divergence,
    )
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
        "candidate_discovery_packet": {
            "contract_version": CANDIDATE_DISCOVERY_PACKET_CONTRACT,
            "selection_summary": candidate_selection,
            "selected_cards": candidates,
            "boundary": "Observed feature prioritization only. Buckets and selection components are not direct kinase, causal, or perturbation evidence.",
        },
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
        for anchor in (packet.get("pathway_anchors") or [])[:3]:
            pathway = str(anchor.get("pathway") or "").strip()
            if pathway:
                queries.append({
                    "role": "pathway_comparison",
                    "query": " ".join(part for part in [treatment, pathway, "phosphorylation temporal response"] if part)[:500],
                    "anchor": pathway,
                })
        discovery = dict(packet.get("candidate_discovery_packet") or {})
        selected_cards = list(discovery.get("selected_cards") or packet.get("candidate_observation_cards") or [])
        canonical_cards = [card for card in selected_cards if card.get("primary_bucket") == "canonical_context_anchor"]
        discovery_cards = [card for card in selected_cards if card.get("primary_bucket") != "canonical_context_anchor"]
        for candidate in canonical_cards[:3]:
            gene = str(candidate.get("gene") or "").strip()
            if gene:
                queries.append({
                    "role": "canonical_anchor_biology",
                    "query": " ".join(part for part in [gene, treatment, "phosphorylation temporal profile"] if part)[:500],
                    "anchor": gene,
                    "selection_bucket": "canonical_context_anchor",
                })
        for candidate in discovery_cards[:5]:
            gene = str(candidate.get("gene") or "").strip()
            if gene:
                queries.append({
                    "role": "discovery_candidate_biology",
                    "query": " ".join(part for part in [gene, treatment, "phosphorylation temporal profile"] if part)[:500],
                    "anchor": gene,
                    "selection_bucket": str(candidate.get("primary_bucket") or "annotation_negative_discovery"),
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
        "Data-prioritized candidate discovery cards (observed trajectories; not direct kinase assignments):",
    ]
    for card in (packet.get("candidate_observation_cards") or [])[:20]:
        trajectory = "; ".join(
            f"{point.get('condition')}: PTM={point.get('ptm_relative_log2fc') if point.get('ptm_relative_log2fc') is not None else 'NA'}, protein={point.get('protein_log2fc') if point.get('protein_log2fc') is not None else 'NA'}"
            for point in card.get("trajectory") or []
        )
        components = dict(card.get("selection_components") or {})
        q_text = (
            f"q coverage={components.get('finite_q_value_count')}; best q={components.get('best_q_value')}"
            if components.get("finite_q_value_count") else "q coverage=0; best q=not recorded"
        )
        reasons = "; ".join(map(str, card.get("discovery_rationale") or [])) or "observed trajectory"
        lines.append(
            f"- {card.get('gene')} {card.get('position')}: bucket={card.get('primary_bucket')}; "
            f"annotation context={card.get('annotation_context')}; rationale={reasons}; "
            f"profile={card.get('profile_label')}; peak={card.get('peak_condition')}; "
            f"max |PTM|={components.get('max_abs_ptm_log2fc')}; "
            f"max |PTM-protein contrast|={components.get('max_abs_ptm_protein_contrast')}; {q_text}; {trajectory}"
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
        "For discovery buckets, state why the measured feature was data-prioritized, compare literature agreement/disagreement, and propose a specific next measurement. Do not call it a confirmed novel substrate.",
        "Do not turn a literature relationship, motif score, Wave co-membership, lag, or pathway diagram into an Order-specific direct kinase–site or causal edge.",
        "=== END DATA-GROUNDED BIOLOGICAL SYNTHESIS PACKET ===",
    ])
    return "\n".join(lines)
