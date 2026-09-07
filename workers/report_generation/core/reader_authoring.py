"""Reader-facing, evidence-guided scientific authoring helpers.

This module is intentionally one-way: it translates the compact, provenance-rich
Report state into bounded reader-ready evidence cards.  Internal readiness codes,
raw diagnostic dictionaries, and legacy temporal identifiers never enter the
model-visible packet.  Their full detail is retained in a separate technical
audit rendered by :func:`render_evidence_reproducibility_audit`.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable, Mapping


AUTHORING_PACKET_VERSION = "reader_authoring_packet.v1"
VALID_CLAIM_TIERS = {"O1", "O2", "C1", "L1", "H1", "D1"}

_INTERNAL_TERM_RE = re.compile(
    r"\b(?:P[0-5]|M[0-4]|R[0-4]|TW-\d+|wave_[\w-]+|cowave_[\w-]+|"
    r"DATA-[A-Z0-9_-]+|computed_no_eligible_[\w-]+|not_recorded|"
    r"packet unavailable|n_eff|LOTO|p=None)\b",
    flags=re.IGNORECASE,
)
_EVIDENCE_MARKER_RE = re.compile(r"\s*\[EVID:([A-Za-z0-9_.:-]+)\]")
_REFERENCE_MARKER_RE = re.compile(r"\[REF:(pmid:[^\]]+|doi:[^\]]+|title:[^\]]+)\]", re.IGNORECASE)
_DIRECT_OR_CAUSAL_RE = re.compile(
    r"\b(?:direct(?:ly)?|causes?|drives?|proves?|establishes?|"
    r"activates?|activation loop|catalytic activity|causal propagation|"
    r"signal propagation|feedback loop|autophosphorylation|"
    r"kinase[- ]substrate(?: relationship| regulation| attribution)?|"
    r"isoform[- ]specific)\b",
    flags=re.IGNORECASE,
)
_LITERATURE_SIGNAL_RE = re.compile(
    r"\b(?:literature|published|previously reported|prior work|canonical|"
    r"established biology|known pathway)\b",
    flags=re.IGNORECASE,
)
_DENOVO_AXIS_RE = re.compile(
    r"\bde novo\b.*\b(?:log2fc|fold[- ]?change|magnitude|rank(?:ed|ing)?)\b|"
    r"\b(?:log2fc|fold[- ]?change|magnitude|rank(?:ed|ing)?)\b.*\bde novo\b",
    flags=re.IGNORECASE,
)
_OCCUPANCY_RE = re.compile(r"\b(?:absolute occupancy|occupancy|stoichiometry)\b", re.IGNORECASE)


def _as_mapping(value: Any) -> dict:
    return dict(value) if isinstance(value, Mapping) else {}


def _clean_text(value: Any) -> str:
    """Return compact reader-facing text without transport or diagnostic labels."""
    text = str(value or "").strip()
    text = re.sub(r"\[?DATA-[A-Z0-9_-]+\]?", "", text, flags=re.IGNORECASE)
    text = _INTERNAL_TERM_RE.sub("", text)
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    return text.strip(" -;,")


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _stable_reference_id(reference: Mapping[str, Any]) -> str:
    pmid = str(reference.get("pmid") or "").strip().lower()
    if pmid:
        return f"pmid:{pmid}"
    doi = str(reference.get("doi") or "").strip().lower()
    if doi:
        return f"doi:{doi}"
    title = re.sub(r"[^a-z0-9]", "", str(reference.get("title") or "").lower())[:120]
    return f"title:{title}" if title else ""


def _record_card(record: Mapping[str, Any], index: int) -> dict | None:
    evidence_id = str(record.get("evidence_id") or "").strip()
    text = _clean_text(record.get("reader_summary") or record.get("text"))
    if not evidence_id or not text:
        return None
    lowered = evidence_id.lower()
    if any(token in lowered for token in ("kinase", "footprint", "attribution")):
        tier, category = "C1", "kinase_context"
    elif any(token in lowered for token in ("dynamic", "temporal", "concordance", "cross-layer")):
        tier, category = "O2", "temporal_profile"
    else:
        tier, category = "O1", "quantitative_observation"
    return {
        "card_id": f"record.{index}",
        "category": category,
        "reader_summary": text,
        "claim_tier": tier,
        "evidence_ids": [evidence_id],
        "citation_ids": [],
        "allowed_verbs": ["observed", "summarized", "was consistent with"],
        "forbidden_interpretations": ["caused", "activated", "directly regulates"],
        "counterevidence": _clean_text(record.get("counterevidence")),
    }


def _study_frame_card(state: Mapping[str, Any], synthesis: Mapping[str, Any]) -> dict:
    context = _as_mapping(state.get("experimental_context"))
    frame = _as_mapping(synthesis.get("study_frame"))
    cell_model = str(frame.get("cell_model") or context.get("cell_type") or context.get("cell_line") or "the recorded experimental system").strip()
    treatment = str(frame.get("treatment") or context.get("treatment") or context.get("compound") or "the recorded perturbation context").strip()
    timepoints = frame.get("timepoints") or context.get("timepoints") or context.get("conditions") or []
    if isinstance(timepoints, str):
        timepoints = [timepoints]
    time_text = ", ".join(str(item) for item in timepoints if str(item).strip()) or "the recorded sampled conditions"
    ptm_type = str(state.get("ptm_type") or "PTM").strip()
    return {
        "card_id": "study.frame",
        "category": "study_frame",
        "reader_summary": (
            f"The study measured {ptm_type} features and linked total-protein abundance in {cell_model} "
            f"under {treatment} across {time_text}."
        ),
        "claim_tier": "O1",
        "evidence_ids": ["study.frame"],
        "citation_ids": [],
        "allowed_verbs": ["measured", "evaluated", "summarized"],
        "forbidden_interpretations": ["caused", "activated", "directly regulates"],
        "counterevidence": "Study-frame metadata define experimental scope rather than a mechanistic conclusion.",
    }


def _quantitative_cards(synthesis: Mapping[str, Any]) -> list[dict]:
    landscape = _as_mapping(synthesis.get("quantitative_landscape"))
    cards: list[dict] = []
    sites = _number(landscape.get("unique_site_count"))
    rows = _number(landscape.get("vector_row_count"))
    genes = _number(landscape.get("unique_gene_count"))
    if any(value is not None for value in (sites, rows, genes)):
        fragments = []
        if rows is not None:
            fragments.append(f"{rows:,} quantitative vector rows")
        if sites is not None:
            fragments.append(f"{sites:,} unique quantitative feature aggregates")
        if genes is not None:
            fragments.append(f"{genes:,} gene labels")
        cards.append({
            "card_id": "quantitative.landscape",
            "category": "quantitative_landscape",
            "reader_summary": "The quantitative landscape comprised " + ", ".join(fragments) + ".",
            "claim_tier": "O1",
            "evidence_ids": ["quantitative.landscape"],
            "citation_ids": [],
            "allowed_verbs": ["measured", "contained", "summarized"],
            "forbidden_interpretations": ["prioritized", "proved", "activated"],
            "counterevidence": "Magnitude alone was not treated as biological priority or direct regulatory strength.",
        })
    denovo = _number(landscape.get("de_novo_vector_row_count"))
    if denovo is not None:
        cards.append({
            "card_id": "quantitative.de_novo",
            "category": "quantitative_provenance",
            "reader_summary": (
                f"{denovo:,} control-undetected PTM rows were retained as detection/LOD context and were not used "
                "on conventional quantitative axes or magnitude rankings."
            ),
            "claim_tier": "O1",
            "evidence_ids": ["quantitative.de_novo"],
            "citation_ids": [],
            "allowed_verbs": ["retained", "represented", "excluded"],
            "forbidden_interpretations": ["ranked", "prioritized", "proved"],
            "counterevidence": "Detection/LOD context is not a conventional fold-change measurement.",
        })
    return cards


def _normalization_card(state: Mapping[str, Any]) -> dict:
    pipeline = _as_mapping(state.get("pipeline_statistics"))
    metadata = _as_mapping(pipeline.get("metadata"))
    normalization = _as_mapping(pipeline.get("normalization")) or _as_mapping(metadata.get("normalization"))
    method = str(normalization.get("normalization_method") or normalization.get("method") or metadata.get("normalization_method") or "").strip()
    sample_scaling = str(normalization.get("sample_scaling_status") or "").strip()
    ratio_track = str(normalization.get("ratio_track_interpretation") or "").strip()
    if method:
        summary = f"Recorded preprocessing used {method}"
        if sample_scaling:
            summary += f" with {sample_scaling}"
        summary += "."
    else:
        summary = "The report preserves only recorded preprocessing provenance and does not infer an unrecorded correction model."
    if ratio_track:
        summary += f" The linked PTM/protein track is interpreted as {ratio_track}."
    summary += " It is a protein-abundance-adjusted relative PTM ratio, not calibrated absolute occupancy or kinase activity."
    return {
        "card_id": "quantitation.provenance",
        "category": "quantitation_provenance",
        "reader_summary": summary,
        "claim_tier": "O1",
        "evidence_ids": ["quantitation.provenance"],
        "citation_ids": [],
        "allowed_verbs": ["used", "recorded", "interpreted"],
        "forbidden_interpretations": ["occupancy", "stoichiometry", "kinase activity"],
        "counterevidence": "No unrecorded batch, drift, or upstream quantity-scale correction is inferred.",
    }


def _literature_cards(references: Iterable[Mapping[str, Any]]) -> list[dict]:
    cards: list[dict] = []
    for index, reference in enumerate(references or [], 1):
        ref = _as_mapping(reference)
        stable_id = _stable_reference_id(ref)
        title = _clean_text(ref.get("title"))
        if not stable_id or not title:
            continue
        authors = _clean_text(ref.get("authors"))
        year = _clean_text(ref.get("year") or ref.get("pub_date"))[:4]
        identity = ", ".join(value for value in (authors, year) if value)
        cards.append({
            "card_id": f"literature.{index}",
            "category": "traceable_literature",
            "reader_summary": (
                f"Selected literature provides external context through {title}" +
                (f" ({identity})." if identity else ".")
            ),
            "claim_tier": "L1",
            "evidence_ids": [f"literature.{stable_id}"],
            "citation_ids": [stable_id],
            "allowed_verbs": ["reported", "described", "provided context for", "was consistent with"],
            "forbidden_interpretations": ["proved the current observation", "established a current direct relationship"],
            "counterevidence": "Literature context does not convert a prior relationship into a current-order observation.",
        })
    return cards[:8]


def _kinase_context_cards(state: Mapping[str, Any]) -> list[dict]:
    """Build bounded family-level kinase candidate context without raw diagnostics."""
    heatmap = _as_mapping(state.get("kinase_activity_heatmap")) or _as_mapping(state.get("frontend_kinase_analysis"))
    scores = [
        _as_mapping(row) for row in heatmap.get("kinase_scores") or []
        if isinstance(row, Mapping) and not row.get("is_sub_pattern")
    ]
    if not scores:
        return []
    computed = [
        row for row in scores
        if str(_as_mapping(row.get("footprint_diagnostics")).get("status") or "not_evaluable") == "computed"
    ]
    if not computed:
        return [{
            "card_id": "kinase.context_availability",
            "category": "kinase_context",
            "reader_summary": "The current data did not support a stable evaluation of kinase footprint candidate context.",
            "claim_tier": "O1",
            "evidence_ids": ["kinase.context_availability"],
            "citation_ids": [],
            "allowed_verbs": ["did not support", "was not evaluated"],
            "forbidden_interpretations": ["kinase absence", "kinase inactivity", "kinase rank"],
            "counterevidence": "A non-evaluable footprint is not evidence that a kinase is absent or inactive.",
        }]

    def sort_key(row: Mapping[str, Any]) -> tuple[float, str]:
        try:
            magnitude = abs(float(row.get("peak_score") or 0.0))
        except (TypeError, ValueError):
            magnitude = 0.0
        return (-magnitude, str(row.get("canonical") or row.get("kinase") or ""))

    cards: list[dict] = []
    emitted: set[str] = set()
    for row in sorted(computed, key=sort_key):
        equivalence = _as_mapping(row.get("footprint_equivalence"))
        members = [str(member).strip() for member in equivalence.get("members") or [] if str(member).strip()]
        candidate = str(row.get("canonical") or row.get("kinase") or "candidate kinase").strip()
        group_id = str(equivalence.get("equivalence_group_id") or candidate).strip()
        if group_id in emitted:
            continue
        emitted.add(group_id)
        family_label = " / ".join(members) + " family" if len(members) >= 2 else f"{candidate} family"
        cards.append({
            "card_id": f"kinase.{len(cards) + 1}",
            "category": "kinase_context",
            "reader_summary": (
                f"A contribution-weighted {family_label} footprint provided kinase-family candidate context across "
                "the sampled conditions."
            ),
            "claim_tier": "C1",
            "evidence_ids": [f"kinase.footprint.{group_id}"],
            "citation_ids": [],
            "allowed_verbs": ["provided candidate context", "was consistent with", "prioritized for testing"],
            "forbidden_interpretations": ["kinase activation", "direct kinase–site attribution", "isoform-specific activity"],
            "counterevidence": (
                "Shared substrate support and family equivalence are retained as robustness context; direct kinase–site "
                "attribution and isoform-specific activity are not made from this dataset."
            ),
        })
        if len(cards) >= 3:
            break
    return cards


def build_authoring_packet(
    state: Mapping[str, Any],
    *,
    temporal_evidence_packet: Mapping[str, Any] | None = None,
    biological_synthesis_packet: Mapping[str, Any] | None = None,
    references: Iterable[Mapping[str, Any]] | None = None,
) -> dict:
    """Build the sole model-visible reader-ready evidence packet.

    The function deliberately serializes only short cards.  Full provenance,
    P-layer readiness data, relation snapshots, and raw diagnostic payloads stay
    in the technical audit inputs and are never copied into ``reader_summary``.
    """
    temporal = _as_mapping(temporal_evidence_packet or state.get("temporal_report_evidence_packet"))
    synthesis = _as_mapping(biological_synthesis_packet or state.get("biological_synthesis_packet"))
    cards = [_study_frame_card(state, synthesis), *_quantitative_cards(synthesis), _normalization_card(state)]
    for index, record in enumerate(temporal.get("records") or [], 1):
        if len([card for card in cards if card["category"] == "temporal_profile"]) >= 5:
            break
        if isinstance(record, Mapping):
            card = _record_card(record, index)
            if card and card["category"] == "temporal_profile":
                cards.append(card)
    cards.extend(_kinase_context_cards(state))

    candidate_packet = _as_mapping(synthesis.get("candidate_discovery_packet"))
    selection_summary = _as_mapping(candidate_packet.get("selection_summary"))
    candidate_cards = candidate_packet.get("candidate_cards") or candidate_packet.get("cards") or []
    for index, candidate in enumerate(candidate_cards[:5], 1):
        candidate = _as_mapping(candidate)
        summary = _clean_text(candidate.get("reader_summary") or candidate.get("summary") or candidate.get("selection_rationale"))
        if not summary:
            continue
        cards.append({
            "card_id": f"candidate.{index}",
            "category": "candidate_discovery",
            "reader_summary": summary,
            "claim_tier": "H1",
            "evidence_ids": [str(candidate.get("evidence_id") or f"candidate.{index}")],
            "citation_ids": [],
            "allowed_verbs": ["prioritized", "nominated", "proposed for testing"],
            "forbidden_interpretations": ["confirmed substrate", "direct target", "validated mechanism"],
            "counterevidence": _clean_text(candidate.get("counterevidence")),
        })
    if selection_summary and not candidate_cards:
        cards.append({
            "card_id": "candidate.availability",
            "category": "candidate_discovery",
            "reader_summary": "A pre-specified discovery candidate summary was not generated for this analysis run.",
            "claim_tier": "O1",
            "evidence_ids": ["candidate.availability"],
            "citation_ids": [],
            "allowed_verbs": ["was not generated"],
            "forbidden_interpretations": ["no candidates exist"],
            "counterevidence": "Absence of a summary is not evidence of biological absence.",
        })

    reference_cards = _literature_cards(references or state.get("collected_references") or [])
    cards.extend(reference_cards)
    reader_cards = [card for card in cards if card.get("reader_summary") and not _INTERNAL_TERM_RE.search(card["reader_summary"])]
    has_traceable_literature = bool(reference_cards)
    figure_manifest = _as_mapping(state.get("figure_manifest"))
    figure_cards = []
    main_number = 1
    supplementary_number = 1
    for figure in figure_manifest.get("figures") or []:
        if not isinstance(figure, Mapping) or figure.get("placement") not in {"main", "supplementary"}:
            continue
        placement = str(figure.get("placement"))
        figure_label = f"Figure {main_number}" if placement == "main" else f"Supplementary Figure {supplementary_number}"
        if placement == "main":
            main_number += 1
        else:
            supplementary_number += 1
        figure_cards.append({
            "figure_key": figure.get("figure_key"),
            "figure_label": figure_label,
            "placement": placement,
            "question": figure.get("research_question"),
            "reader_summary": f"{figure.get('kind')} selected under {figure.get('selection_rule')}",
            "allowed_interpretation": "descriptive temporal pattern or cited external context",
            "forbidden_interpretation": "activation, direct kinase–substrate relation, causal order, isoform-specific activity",
            "citation_ids": list(figure.get("citation_ids") or []),
            "source_evidence_ids": list(figure.get("source_evidence_ids") or []),
        })
    section_claim_budget = {
        "abstract": ["O1", "O2", "C1", "H1"] + (["L1"] if has_traceable_literature else []),
        "introduction": ["O1", "O2", "L1", "H1"] if has_traceable_literature else ["O1", "O2", "H1"],
        "results": ["O1", "O2", "C1", "H1"],
        "research_question_answers": ["O1", "O2", "C1", "H1"],
        "discussion": ["O1", "O2", "C1", "H1"] + (["L1"] if has_traceable_literature else []),
        "conclusion": ["O1", "O2", "C1", "H1"],
        "methods": ["O1", "O2"],
    }
    return {
        "contract_version": AUTHORING_PACKET_VERSION,
        "mode": "citation_complete" if has_traceable_literature else "data_only",
        "reader_cards": reader_cards,
        "figure_cards": figure_cards,
        "section_claim_budget": section_claim_budget,
        "authoring_rules": {
            "required_evidence_anchor": "[EVID:<evidence_id>] after each factual sentence; this anchor is removed before reader rendering.",
            "citation_marker": "Use [REF:pmid:*], [REF:doi:*], or [REF:title:*] only for supplied literature cards.",
            "directness": "Do not claim direct kinase–substrate regulation, causal propagation, catalytic activation, isoform-specific attribution, or perturbation outcome.",
            "de_novo": "Control-undetected rows are detection/LOD context only and must not be placed on conventional Log2FC axes or magnitude rankings.",
            "normalization": "Describe the track as protein-abundance-adjusted relative PTM ratio, not absolute occupancy or kinase activity.",
        },
    }


def format_authoring_packet_for_llm(packet: Mapping[str, Any], section_type: str, plan: Mapping[str, Any] | None = None) -> str:
    """Format the narrow writer context without exposing internal evidence state."""
    allowed = set(_as_mapping(packet.get("section_claim_budget")).get(section_type) or ["O1", "O2"])
    lines = [
        "=== READER-READY AUTHORING PACKET ===",
        f"Mode: {packet.get('mode', 'data_only')}",
        f"Section: {section_type}",
        "Write formal academic prose for general cell-signaling and proteomics researchers.",
        "Use only these evidence cards and citations; do not add background knowledge.",
        "Every factual sentence must end with one supplied [EVID:<id>] marker. These markers will be removed before rendering.",
        "Use supplied [REF:*] markers for every literature-context sentence. Never cite a source not listed below.",
        "Do not expose implementation codes, raw diagnostic field names, serialized status strings, or temporal internal identifiers.",
        "Do not make direct/causal/activation/isoform/perturbation claims. Use candidate-context or testable-hypothesis language where appropriate.",
        "Temporal Profile Clustering and Interval-wise Concordance Analysis are descriptive methods; do not call them causal flow.",
        "",
        "Allowed claim tiers: " + ", ".join(sorted(allowed)),
        "Evidence cards:",
    ]
    for card in packet.get("reader_cards") or []:
        if card.get("claim_tier") not in allowed:
            continue
        line = (
            f"- [EVID:{card['evidence_ids'][0]}] tier={card['claim_tier']}; "
            f"summary={card['reader_summary']}; allowed verbs={', '.join(card['allowed_verbs'])}"
        )
        citation_ids = card.get("citation_ids") or []
        if citation_ids:
            line += "; citations=" + ", ".join(f"[REF:{ref_id}]" for ref_id in citation_ids)
        if card.get("counterevidence"):
            line += f"; boundary={card['counterevidence']}"
        lines.append(line)
    if packet.get("figure_cards"):
        lines.extend(["", "Eligible figure cards:"])
        for figure in packet["figure_cards"]:
            lines.append(
                f"- {figure.get('figure_label')}: key={figure.get('figure_key')}; placement={figure.get('placement')}; "
                f"question={figure.get('question')}; use at most one eligible figure per paragraph."
            )
    if plan:
        claim_map = _as_mapping(plan.get("sections")).get(section_type)
        if claim_map:
            lines.extend(["", "Section plan:", _clean_text(claim_map)])
    lines.append("=== END READER-READY AUTHORING PACKET ===")
    return "\n".join(lines)


def deterministic_authoring_plan(packet: Mapping[str, Any]) -> dict:
    """Return a safe plan fallback when the optional LLM planner is unavailable."""
    cards = packet.get("reader_cards") or []
    categories = {str(card.get("category")) for card in cards if isinstance(card, Mapping)}
    return {
        "source": "deterministic_fallback",
        "sections": {
            "abstract": "State the study frame, quantitative scope, observed temporal pattern, candidate-context boundary, and a testable next question.",
            "introduction": "Connect the recorded study question, time-resolved measurement design, and traceable literature context without making current-order mechanistic claims.",
            "results": "Progress from coverage to selected temporal profile observations, interval-wise concordance, protein-linked context, and candidate context.",
            "discussion": "Distinguish current observations from cited external context, explain alternative interpretations, and end with a discriminating validation experiment.",
            "conclusion": "Summarize what was observed and what is proposed for testing without promoting candidate context to direct regulation.",
            "methods": "Describe recorded normalization, conventional/de novo representation, Temporal Profile Clustering, and Interval-wise Concordance Analysis.",
        },
        "available_categories": sorted(categories),
    }


def _known_evidence_ids(packet: Mapping[str, Any]) -> set[str]:
    return {
        evidence_id
        for card in packet.get("reader_cards") or []
        if isinstance(card, Mapping)
        for evidence_id in card.get("evidence_ids") or []
    }


def _known_reference_ids(packet: Mapping[str, Any]) -> set[str]:
    return {
        citation_id.lower()
        for card in packet.get("reader_cards") or []
        if isinstance(card, Mapping)
        for citation_id in card.get("citation_ids") or []
    }


def _replace_unsafe_terms(text: str) -> str:
    replacements = [
        (r"\bdirectly activates?\b", "provides candidate context for"),
        (r"\bactivates?\b", "is associated with"),
        (r"\bcauses?\b", "is consistent with"),
        (r"\bdrives?\b", "is associated with"),
        (r"\bproves?\b", "is compatible with"),
        (r"\bestablishes?\b", "summarizes"),
        (r"\bcausal propagation\b", "observed temporal pattern"),
        (r"\bsignal propagation\b", "time-resolved observation"),
        (r"\bactivation loop\b", "candidate regulatory-site context"),
        (r"\bcatalytic activity\b", "candidate-context score"),
        (r"\bisoform[- ]specific\b", "kinase-family"),
        (r"\bkinase[- ]substrate(?: relationship| regulation| attribution)?\b", "kinase-family candidate context"),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def _split_sentences(text: str) -> list[str]:
    return [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", text or "") if sentence.strip()]


def validate_and_repair_sections(
    sections: Mapping[str, Any],
    packet: Mapping[str, Any],
) -> tuple[dict, dict]:
    """Validate evidence/citation/claim boundaries and repair clauses locally.

    Valid sentences are retained.  A problematic clause is either rewritten with
    candidate-context wording or removed; no whole section is replaced.
    """
    known_evidence = _known_evidence_ids(packet)
    known_references = _known_reference_ids(packet)
    budgets = _as_mapping(packet.get("section_claim_budget"))
    validated: dict[str, str] = {}
    audit_entries: list[dict] = []
    for section_name, raw_content in dict(sections or {}).items():
        content = str(raw_content or "")
        if not content:
            validated[section_name] = content
            continue
        allowed_tiers = set(budgets.get(section_name) or ["O1", "O2"])
        retained: list[str] = []
        for sentence_index, sentence in enumerate(_split_sentences(content), 1):
            if sentence.startswith("#"):
                retained.append(sentence)
                continue
            evidence_ids = _EVIDENCE_MARKER_RE.findall(sentence)
            citations = [item.lower() for item in _REFERENCE_MARKER_RE.findall(sentence)]
            actions: list[str] = []
            reasons: list[str] = []
            invalid_evidence = [item for item in evidence_ids if item not in known_evidence]
            invalid_citations = [item for item in citations if item not in known_references]
            if invalid_evidence:
                sentence = _EVIDENCE_MARKER_RE.sub("", sentence)
                actions.append("remove_invalid_evidence_anchor")
                reasons.append("unknown_evidence_id")
                evidence_ids = [item for item in evidence_ids if item in known_evidence]
            if invalid_citations:
                sentence = _REFERENCE_MARKER_RE.sub("", sentence)
                actions.append("remove_invalid_citation")
                reasons.append("unknown_citation_id")
                citations = [item for item in citations if item in known_references]
            if _INTERNAL_TERM_RE.search(sentence):
                sentence = _clean_text(sentence)
                actions.append("remove_internal_terminology")
                reasons.append("reader_body_internal_leakage")
            direct_claim = bool(_DIRECT_OR_CAUSAL_RE.search(sentence))
            if direct_claim and "D1" not in allowed_tiers:
                sentence = _replace_unsafe_terms(sentence)
                actions.append("rewrite_claim_to_candidate_context")
                reasons.append("directness_or_causality_claim_exceeds_budget")
            if _DENOVO_AXIS_RE.search(sentence):
                sentence = (
                    "Control-undetected features were retained as detection/LOD context and were not used on conventional "
                    "quantitative axes or magnitude rankings."
                )
                actions.append("rewrite_de_novo_axis_claim")
                reasons.append("de_novo_conventional_axis_or_ranking")
            if _OCCUPANCY_RE.search(sentence) and not re.search(r"\bnot\b", sentence, flags=re.IGNORECASE):
                sentence = _OCCUPANCY_RE.sub("protein-abundance-adjusted relative PTM ratio", sentence)
                actions.append("rewrite_quantitation_interpretation")
                reasons.append("uncalibrated_occupancy_or_stoichiometry")
            if _LITERATURE_SIGNAL_RE.search(sentence) and not citations:
                # Preserve current-study observations but remove an unsupported external-context clause.
                clauses = re.split(r"(?<=[,;:])\s+|\s+(?=whereas\b|while\b)", sentence, flags=re.IGNORECASE)
                keep = [clause for clause in clauses if not _LITERATURE_SIGNAL_RE.search(clause)]
                sentence = " ".join(keep).strip()
                actions.append("remove_uncited_literature_clause")
                reasons.append("literature_context_without_stable_citation")
            # A meaningful factual sentence needs a supplied evidence anchor.
            factual = bool(re.search(r"\b(?:measured|observed|identified|summarized|increased|decreased|profile|feature|protein|kinase|PTM|time)\b", sentence, flags=re.IGNORECASE))
            if factual and not evidence_ids and not citations:
                actions.append("remove_unanchored_factual_sentence")
                reasons.append("missing_evidence_anchor")
                sentence = ""
            if sentence:
                retained.append(sentence.strip())
            audit_entries.append({
                "section": section_name,
                "sentence_index": sentence_index,
                "evidence_ids": evidence_ids,
                "citation_ids": citations,
                "claim_tier_budget": sorted(allowed_tiers),
                "validator_action": actions or ["retain"],
                "reason_code": reasons or ["within_contract"],
                "retained": bool(sentence),
            })
        validated[section_name] = "\n\n".join(retained)
    audit = {
        "contract_version": "reader_authoring_validator.v1",
        "packet_version": packet.get("contract_version"),
        "entries": audit_entries,
        "removed_sentence_count": sum(1 for entry in audit_entries if not entry["retained"]),
        "repaired_sentence_count": sum(1 for entry in audit_entries if entry["validator_action"] != ["retain"] and entry["retained"]),
    }
    return validated, audit


def strip_authoring_anchors(text: str) -> str:
    """Remove draft-only evidence anchors after validation, preserving citations."""
    text = _EVIDENCE_MARKER_RE.sub("", text or "")
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def render_data_only_reader_report(
    state: Mapping[str, Any],
    packet: Mapping[str, Any],
    *,
    title: str,
    generated_at: str,
) -> str:
    """Render a useful data-only manuscript without citation-dependent claims.

    This fallback is used only when citation identities are unavailable. It uses
    the same reader cards as the LLM path and therefore never exposes internal
    provenance status in the researcher-facing body.
    """
    cards = [card for card in packet.get("reader_cards") or [] if isinstance(card, Mapping)]
    by_category: dict[str, list[str]] = {}
    for card in cards:
        by_category.setdefault(str(card.get("category") or "other"), []).append(str(card.get("reader_summary") or ""))

    def summaries(*categories: str, limit: int = 4) -> str:
        selected: list[str] = []
        for category in categories:
            selected.extend(value for value in by_category.get(category, []) if value)
        return " ".join(selected[:limit]) or "The available data support a bounded quantitative description of the recorded study frame."

    study = summaries("study_frame", limit=1)
    quantitative = summaries("quantitative_landscape", "quantitative_provenance", limit=3)
    temporal = summaries("temporal_profile", limit=5)
    kinase = summaries("kinase_context", limit=3)
    candidate = summaries("candidate_discovery", limit=3)
    return "\n\n".join([
        f"# {title}",
        f"*Generated: {generated_at}*",
        "## Abstract\n\n"
        f"{study} {quantitative} {temporal} This data-only manuscript intentionally confines interpretation to "
        "recorded observations, bounded temporal-profile summaries, and pre-specified follow-up questions because "
        "traceable publication metadata were not available for literature comparison. The results are not used to "
        "claim direct kinase–substrate regulation, catalytic activity, causal propagation, isoform-specific action, "
        "or perturbation outcome.",
        "## Introduction\n\n"
        f"{study} The report separates phosphorylation-feature measurements from linked total-protein abundance so that "
        "a relative PTM signal is not treated as a direct activity or occupancy measurement. Temporal Profile Clustering "
        "and Interval-wise Concordance Analysis provide a descriptive framework for comparing sampled response profiles. "
        "External biological background and pathway assertions are deliberately omitted in this data-only version; this "
        "maintains a clear distinction between the current experiment and claims requiring traceable literature support.",
        "## Results\n\n"
        f"### Quantitative landscape\n\n{quantitative}\n\n"
        f"### Temporal-profile observations\n\n{temporal}\n\n"
        "### Candidate context and next question\n\n"
        f"{kinase} {candidate} Candidate context is used to prioritize a discriminating measurement or perturbation design, "
        "rather than to assert a direct regulatory relationship.",
        "## Discussion\n\n"
        "The current data provide a time-resolved quantitative record that can be inspected for reproducible profile structure, "
        "concordance change, and protein-linked context. The analytical value of this record does not depend on converting a "
        "large numeric contrast, a profile grouping, or a substrate-derived score into mechanistic proof. The most informative "
        "next experiment is one that tests a specific candidate relationship with matched temporal sampling and an orthogonal "
        "measurement, while preserving the distinction between observed data and the proposed hypothesis.",
        "## Methods\n\n"
        "The report uses recorded preprocessing provenance, separates conventional quantitative contrasts from control-undetected "
        "detection/LOD context, and reports phosphorylation-feature change alongside linked protein-abundance context. "
        "Hierarchical Clustering of Temporal Phosphorylation Feature Profiles was used to construct descriptive Temporal Profile "
        "Clusters. Interval-wise Concordance Analysis summarizes retained, gained, or lost local profile concordance across sampled intervals. "
        "Large conventional Log2FC values are retained as measured numeric contrasts but are not used alone to infer biological priority, "
        "mechanistic importance, or direct regulatory strength.",
        "## Conclusion\n\n"
        "This data-only report presents the recorded quantitative and temporal observations in researcher-facing language while reserving "
        "citation-dependent biological interpretation and direct mechanistic claims for a citation-complete follow-up report.",
        "## References\n\n"
        "Traceable publication metadata were not available for this Report. No external biological or prior-work claims are included.",
    ])


def render_evidence_reproducibility_audit(
    state: Mapping[str, Any],
    *,
    authoring_packet: Mapping[str, Any] | None = None,
    validator_audit: Mapping[str, Any] | None = None,
    figure_manifest: Mapping[str, Any] | None = None,
) -> str:
    """Render the complete technical audit outside the researcher manuscript."""
    payload = {
        "temporal_report_evidence_packet": state.get("temporal_report_evidence_packet") or {},
        "biological_synthesis_packet": state.get("biological_synthesis_packet") or {},
        "temporal_report_fidelity": state.get("temporal_report_fidelity") or {},
        "pipeline_statistics": state.get("pipeline_statistics") or {},
        "kinase_activity_heatmap": state.get("kinase_activity_heatmap") or state.get("frontend_kinase_analysis") or {},
        "authoring_packet": authoring_packet or state.get("authoring_packet") or {},
        "validator_audit": validator_audit or state.get("reader_authoring_validator_audit") or {},
        "figure_manifest": figure_manifest or state.get("figure_manifest") or {},
    }
    serialized = json.dumps(payload, indent=2, sort_keys=True, default=str)
    return (
        "# Evidence and Reproducibility Audit\n\n"
        "This technical audit is separate from the researcher-facing manuscript. It retains provenance, readiness, "
        "mapping/relation/allocation state, normalization details, full footprint diagnostics, figure eligibility, "
        "and validator actions required for reproducibility review.\n\n"
        "## Machine-readable technical record\n\n"
        "```json\n"
        f"{serialized}\n"
        "```\n"
    )
