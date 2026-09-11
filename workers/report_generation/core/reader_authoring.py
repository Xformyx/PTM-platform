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

from common.temporal_utils import condition_sort_key
from report_generation.core.measured_feature_cards import (
    build_feature_observation_cards,
    build_quantitation_comparison_cards,
)
from report_generation.core.study_metadata import (
    build_study_metadata_contract,
    repair_unrecorded_metadata_claim,
)
from report_generation.core.scientific_semantics import (
    audit_language_quality,
    audit_semantic_claims,
    normalize_reader_prose,
    repair_semantic_sentence,
)
from ptm_shared.quantitation_estimator_contract import (
    build_quantitation_estimator_contract,
    ensure_quantitation_methods_contract,
    repair_quantitation_estimator_sentence,
)


AUTHORING_PACKET_VERSION = "reader_authoring_packet.v4"
VALID_CLAIM_TIERS = {"O1", "O2", "C1", "L1", "H1", "D1"}

# The reader-facing manuscript has one stable story arc.  These are authoring
# obligations, not evidence and not a claim-promotion mechanism.  Keeping them
# beside the card contract prevents every section from becoming an inventory of
# the same compact diagnostics.
SECTION_STORY_CONTRACT = {
    "abstract": {
        "categories": ("study_frame", "measured_feature_observation", "quantitation_comparison", "temporal_profile", "kinase_context", "candidate_discovery"),
        "minimum_words": 170,
        "role": "Summarize the study frame, the most informative observed pattern, its bounded significance, and the discriminating next question.",
        "sequence": "study frame → measured landscape → selected observation → bounded candidate context → next question",
    },
    "introduction": {
        "categories": ("study_frame", "quantitation_provenance", "traceable_literature", "temporal_profile"),
        "minimum_words": 320,
        "role": "Establish the recorded biological question, why time-resolved PTM and protein measurements are informative, the traceable background, and the study objective.",
        "sequence": "study problem → measurement rationale → cited context → unresolved question → present study objective",
    },
    "results": {
        "categories": ("quantitative_landscape", "quantitative_provenance", "measured_feature_observation", "quantitation_comparison", "temporal_profile", "kinase_context", "candidate_discovery"),
        "minimum_words": 350,
        "role": "Report measured scope before selected temporal observations, protein-linked context, and any eligible candidate context.",
        "sequence": "coverage → selected temporal observation → protein-linked quantitative context → candidate context → observation boundary",
    },
    "research_question_answers": {
        "categories": ("study_frame", "measured_feature_observation", "quantitation_comparison", "temporal_profile", "kinase_context", "candidate_discovery"),
        "minimum_words": 80,
        "maximum_words": 220,
        "role": "Provide concise supplementary answers to at most three non-duplicative research questions after the main conclusion.",
        "sequence": "question → one evidence-bound answer → one boundary or discriminating next measurement",
    },
    "discussion": {
        "categories": ("measured_feature_observation", "quantitation_comparison", "quantitative_provenance", "temporal_profile", "kinase_context", "candidate_discovery", "traceable_literature"),
        "minimum_words": 300,
        "role": "Interpret current observations in the selected literature context, state the alternative explanation that remains, and identify the next discriminating experiment.",
        "sequence": "principal observation → cited comparison → bounded interpretation → remaining alternative → discriminating validation",
    },
    "methods": {
        "categories": ("study_frame", "quantitation_provenance", "quantitation_comparison", "temporal_profile"),
        "minimum_words": 260,
        "role": "Describe only recorded quantitative and temporal analysis procedures and their interpretation boundaries.",
        "sequence": "study design → normalization and replicate unit → explicit contrast equations → Welch/BH uncertainty → clustering and interval concordance denominator → missingness/de-novo policy → reporting boundary",
    },
    "conclusion": {
        "categories": ("study_frame", "measured_feature_observation", "quantitation_comparison", "temporal_profile", "kinase_context", "candidate_discovery"),
        "minimum_words": 80,
        "maximum_words": 170,
        "role": "Close the same study question in no more than two short paragraphs with the observed advance, the bounded interpretation, and one testable next step.",
        "sequence": "study question → observed advance → bounded interpretation → next validation",
    },
}

_INTERNAL_TERM_RE = re.compile(
    r"\b(?:P[0-5]|M[0-4]|R[0-4]|TW-\d+|wave_[\w-]+|cowave_[\w-]+|"
    r"DATA-[A-Z0-9_-]+|computed_no_eligible_[\w-]+|not_recorded|"
    r"packet unavailable|n_eff|LOTO|p=None)\b",
    flags=re.IGNORECASE,
)
_EVIDENCE_MARKER_RE = re.compile(r"\s*\[EVID:([A-Za-z0-9_.:-]+)\]")
_MALFORMED_EVIDENCE_MARKER_RE = re.compile(
    r"\s*\[EVID(?:\s*:\s*(?:[A-Za-z0-9_.:-]+|<[^>\n]*>)?)?\]?",
    re.IGNORECASE,
)
# A formatter can remove an opening bracket while leaving a draft-only anchor
# such as `EVID:` or `EVID:feature.observation.1]` behind.  Treat every such
# residue as internal routing syntax, never as reader content.
_ANY_EVIDENCE_RESIDUE_RE = re.compile(
    r"\s*(?:\[\s*)?\bEVID\b\s*(?::\s*(?:[A-Za-z0-9_.:-]+|<[^>\n]*>)?)?\]?",
    re.IGNORECASE,
)
_REFERENCE_MARKER_RE = re.compile(r"\[REF:(pmid:[^\]]+|doi:[^\]]+|title:[^\]]+)\]", re.IGNORECASE)
_DIRECT_OR_CAUSAL_RE = re.compile(
    r"\b(?:direct(?:ly)?|causes?|drives?|proves?|establishes?|"
    r"activates?|activation loop|catalytic activity|causal propagation|"
    r"signal propagation|feedback loop|autophosphorylation|"
    r"kinase[- ]substrate(?: relationship| regulation| attribution)?|"
    r"isoform[- ]specific|kinase activity|pathway activation)\b",
    flags=re.IGNORECASE,
)
_PLAN_SECTION_RE = re.compile(
    r"(?:^|\n)\s*(?:#{1,3}\s*|\*\*)?"
    r"(abstract|introduction|results|discussion|conclusion|methods)\b\*?\*?:?\s*",
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
_READER_TECHNICAL_RECORD_RE = re.compile(
    r"\b(?:status=|candidate pairs=|pair-transition records=|feature-level status records=|"
    r"non-evaluable pair windows=|p=None|n_eff|LOTO)\b",
    flags=re.IGNORECASE,
)


def _as_mapping(value: Any) -> dict:
    return dict(value) if isinstance(value, Mapping) else {}


def _study_context_with_override(state: Mapping[str, Any]) -> dict:
    """Merge an explicit report-level verified metadata override into context."""
    context = _as_mapping(state.get("experimental_context"))
    report_config = _as_mapping(state.get("report_config"))
    for key in (
        "declared_timepoints", "timepoints", "time_points", "control_design", "control",
        "control_condition", "control_time_matching", "control_time_match", "time_matched_control",
        "control_reuse", "shared_control_across_timepoints", "control_reused",
        "sample_pairing", "paired_samples", "pairing_design", "replicate_semantics",
        "replicate_type", "replicate_design",
    ):
        if context.get(key) is None and report_config.get(key) is not None:
            context[key] = report_config.get(key)
    observed_conditions = sorted({
        str(row.get("condition") or row.get("Condition") or "").strip()
        for row in state.get("vector_plot_raw_data") or []
        if isinstance(row, Mapping) and str(row.get("condition") or row.get("Condition") or "").strip()
    }, key=lambda value: (condition_sort_key(value), value.lower()))
    if observed_conditions:
        context["observed_conditions"] = observed_conditions
    context["replicate_statistics_present"] = any(
        isinstance(row, Mapping)
        and any(
            row.get(key) is not None
            for key in (
                "PTM_Unadjusted_Control_N", "ptm_unadjusted_control_n",
                "PTM_Unadjusted_Treatment_N", "ptm_unadjusted_treatment_n",
                "PTM_Unadjusted_P_Value", "ptm_unadjusted_p_value", "p_value",
            )
        )
        for row in state.get("vector_plot_raw_data") or []
    )
    override = _as_mapping(
        state.get("study_metadata_override")
        or report_config.get("study_metadata_override")
        or context.get("verified_metadata")
    )
    if override:
        context["verified_metadata"] = override
    return context


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


def is_traceable_reference(reference: Mapping[str, Any] | None) -> bool:
    """Return True only for publication identities that may enter a bibliography.

    구현 대상: docs/official_temporal_terminology_contract.md reader-facing
    Report wording; 2026-09-07 implementation_log reader-authoring repair.
    사전등록: 2026-09-07 표시 계약. 결과 기반 primary 승격 아님.
    해석 한계: 추적 가능한 서지 식별자의 존재는 현재 Order 관측을 입증하지 않는다.
    주장 금지: title-only Chroma bundle label을 문헌 합의나 kinase 근거로 쓰지 않는다.
    """
    ref = _as_mapping(reference)
    if str(ref.get("pmid") or "").strip() or str(ref.get("doi") or "").strip():
        return True
    return bool(
        str(ref.get("title") or "").strip()
        and str(ref.get("authors") or "").strip()
        and str(ref.get("year") or ref.get("pub_date") or "").strip()
        and str(ref.get("journal") or "").strip()
    )


def references_are_citation_complete(references: Iterable[Mapping[str, Any]] | None) -> bool:
    """True when at least one supplied record is a traceable publication identity."""
    return any(is_traceable_reference(item) for item in (references or []) if isinstance(item, Mapping))


def get_reader_authoring_system_prompt(ptm_type: str = "phosphorylation") -> str:
    """Return the shadow-mode writer prompt without numbered-citation instructions.

    구현 대상: 2026-09-07 reader-authoring shadow contract.
    사전등록: 2026-09-07 표시 계약.
    해석 한계: 이 프롬프트는 입력 제한이지 모델 준수 보장은 아니다.
    주장 금지: system prompt 존재로 서술 품질이나 kinase 예측 향상을 주장하지 않는다.
    """
    label = str(ptm_type or "PTM").strip() or "PTM"
    return (
        f"You are a scientific author writing a {label} time-course manuscript for "
        "cell-signaling and proteomics researchers. Use only the supplied authoring packet. "
        "Do not add background pathway knowledge, receptor cascades, generic mechanism examples, "
        "or citations that are not listed in the packet. "
        "Every literature-context sentence must use a supplied [REF:pmid:*], [REF:doi:*], or "
        "[REF:title:*] marker. Do not write numbered citations such as [1] or [2]. "
        "When a supplied [EVID:<id>] marker exists, append it to the current-study sentence it supports; "
        "those markers are removed before rendering. "
        "Do not claim direct kinase–substrate regulation, catalytic activation, causal propagation, "
        "isoform-specific activity, or perturbation outcome. "
        "Write formal academic prose and do not expose implementation codes or readiness labels."
    )


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
    if _READER_TECHNICAL_RECORD_RE.search(text):
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
    context = _study_context_with_override(state)
    frame = _as_mapping(synthesis.get("study_frame"))
    metadata = build_study_metadata_contract(context)
    cell_model = str(metadata.get("reader_system_label") or metadata.get("cell_model") or "the recorded experimental system").strip()
    treatment = str(metadata.get("treatment") or frame.get("treatment") or "the recorded perturbation context").strip()
    timepoints = metadata.get("declared_timepoints") or metadata.get("observed_conditions") or frame.get("timepoints") or []
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
        "study_metadata_contract": metadata,
        "timepoint_interpretation": metadata.get("timepoint_interpretation"),
        "control_design": metadata.get("control_design"),
        "control_reuse": metadata.get("control_reuse"),
        "control_time_matching": metadata.get("control_time_matching"),
        "sample_pairing": metadata.get("sample_pairing"),
        "replicate_semantics": metadata.get("replicate_semantics"),
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
    emitted: set[str] = set()
    for index, reference in enumerate(references or [], 1):
        ref = _as_mapping(reference)
        stable_id = _stable_reference_id(ref)
        title = _clean_text(ref.get("title"))
        if not stable_id or stable_id in emitted or not title or not is_traceable_reference(ref):
            continue
        emitted.add(stable_id)
        authors = _clean_text(ref.get("authors"))
        year = _clean_text(ref.get("year") or ref.get("pub_date"))[:4]
        identity = ", ".join(value for value in (authors, year) if value)
        excerpt = _clean_text(ref.get("reader_excerpt") or ref.get("excerpt") or ref.get("document"))
        # A short source excerpt lets the scientific author write actual
        # literature context rather than an uninformative bibliography list.
        # It remains bound to the supplied publication identity and is never a
        # current-order observation.
        excerpt = excerpt[:600].rsplit(" ", 1)[0].strip() if len(excerpt) > 600 else excerpt
        contextual_summary = (
            f"Selected literature reported the following relevant external context: {excerpt}"
            if excerpt
            else f"Selected literature provides external context through {title}"
        )
        cards.append({
            "card_id": f"literature.{index}",
            "category": "traceable_literature",
            "reader_summary": contextual_summary + (f" ({identity})." if identity else "."),
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

    구현 대상: docs/official_temporal_terminology_contract.md reader-facing
    wording; 2026-09-07 implementation_log reader-authoring shadow contract.
    사전등록: 2026-09-07 표시 계약. primary 측정 임계가 아니다.
    해석 한계: cards are a writer-input serialization, not a readiness proof.
    주장 금지: packet 존재로 kinase 예측 향상이나 직접 귀속을 주장하지 않는다.

    The function deliberately serializes only short cards.  Full provenance,
    P-layer readiness data, relation snapshots, and raw diagnostic payloads stay
    in the technical audit inputs and are never copied into ``reader_summary``.
    """
    temporal = _as_mapping(temporal_evidence_packet or state.get("temporal_report_evidence_packet"))
    synthesis = _as_mapping(biological_synthesis_packet or state.get("biological_synthesis_packet"))
    metadata_contract = build_study_metadata_contract(_study_context_with_override(state))
    cards = [_study_frame_card(state, synthesis), *_quantitative_cards(synthesis), _normalization_card(state)]
    estimator_contract = build_quantitation_estimator_contract()
    cards.append({
        "card_id": "quantitation.estimator.contract",
        "category": "quantitation_provenance",
        "reader_summary": estimator_contract["deterministic_methods_paragraph"],
        "claim_tier": "O1",
        "evidence_ids": ["quantitation.estimator.contract"],
        "citation_ids": [],
        "allowed_verbs": ["was calculated", "was retained", "was not identical"],
        "forbidden_interpretations": ["absolute occupancy", "kinase activity", "adjusted equals unadjusted minus protein"],
        "counterevidence": estimator_contract["non_equivalence"],
    })
    cards.extend(build_feature_observation_cards(state, maximum=5))
    cards.extend(build_quantitation_comparison_cards(state, maximum=8))
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
    for figure in figure_manifest.get("figures") or []:
        if (
            not isinstance(figure, Mapping)
            or figure.get("placement") != "main"
            or not bool(figure.get("insertion_verified"))
            or not str(figure.get("image_path") or "").strip()
        ):
            continue
        placement = "main"
        figure_label = str(figure.get("display_label") or f"Figure {len(figure_cards) + 1}")
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
            "selected_reader_feature_ids": list(
                figure.get("selected_reader_feature_ids")
                or [
                    str(item.get("reader_feature_id") or "")
                    for item in figure.get("selected_features") or []
                    if str(item.get("reader_feature_id") or "")
                ]
            ),
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
    story_contract = {
        section: {
            **contract,
            "categories": list(contract["categories"]),
        }
        for section, contract in SECTION_STORY_CONTRACT.items()
    }
    return {
        "contract_version": AUTHORING_PACKET_VERSION,
        "mode": "citation_complete" if has_traceable_literature else "data_only",
        "reader_cards": reader_cards,
        "study_metadata_contract": metadata_contract,
        "quantitation_estimator_contract": estimator_contract,
        "figure_cards": figure_cards,
        "section_claim_budget": section_claim_budget,
        "section_story_contract": story_contract,
        "authoring_rules": {
            "required_evidence_anchor": "End each factual paragraph with one or more complete evidence markers copied exactly from supplied cards, for example [EVID:study.frame]. Never emit an incomplete marker or a placeholder.",
            "citation_marker": "Use [REF:pmid:*], [REF:doi:*], or [REF:title:*] only for supplied literature cards.",
            "directness": "Do not claim direct kinase–substrate regulation, causal propagation, catalytic activation, isoform-specific attribution, or perturbation outcome.",
            "de_novo": "Control-undetected rows are detection/LOD context only and must not be placed on conventional Log2FC axes or magnitude rankings.",
            "normalization": "Describe the track as protein-abundance-adjusted relative PTM ratio, not absolute occupancy or kinase activity.",
            "measured_features": "Name current-order measured features and report supplied time-resolved values before aggregate counts or availability statements. Do not call a candidate-residue feature a localized phosphosite unless the card does so.",
            "protein_adjustment": "Use the supplied immutable estimator paragraph exactly. The protein-adjusted estimator is a contrast of condition means of sample-wise PTM/protein ratios; it is not generally independent unadjusted Log2FC minus linked protein Log2FC. The reconstructed legacy metric is audit-only and adjustment does not prove biological truth.",
            "study_metadata": "Use only the resolved study metadata label. A user-verified override supersedes stale free text; unresolved identity conflicts prohibit final release. Do not infer lineage, species, receptor status, or engineering history from a cell-model name.",
        },
    }


def format_authoring_packet_for_llm(packet: Mapping[str, Any], section_type: str, plan: Mapping[str, Any] | None = None) -> str:
    """Format the narrow writer context without exposing internal evidence state."""
    allowed = set(_as_mapping(packet.get("section_claim_budget")).get(section_type) or ["O1", "O2"])
    story_contract = _as_mapping(packet.get("section_story_contract"))
    section_contract = _as_mapping(story_contract.get(section_type))
    allowed_categories = set(section_contract.get("categories") or ())
    lines = [
        "=== READER-READY AUTHORING PACKET ===",
        f"Mode: {packet.get('mode', 'data_only')}",
        f"Section: {section_type}",
        "Write formal academic prose for general cell-signaling and proteomics researchers.",
        "Use only these evidence cards and citations; do not add background knowledge.",
        "Write connected paragraphs, not an evidence-card inventory, a technical status list, or a bullet summary.",
        "Follow the stated narrative sequence so this section continues the same study question as the rest of the manuscript.",
        "End each factual paragraph with complete [EVID:exact.supplied.id] markers copied from the cards used in that paragraph. Never emit [EVID:<id>], [EVID:, or an invented ID. These draft-only markers are removed before rendering.",
        "Use supplied [REF:*] markers for every literature-context sentence. Never cite a source not listed below.",
        "Do not expose implementation codes, raw diagnostic field names, serialized status strings, or temporal internal identifiers.",
        "Do not make direct/causal/activation/isoform/perturbation claims. Use candidate-context or testable-hypothesis language where appropriate.",
        "Temporal Profile Clustering and Interval-wise Concordance Analysis are descriptive methods; do not call them causal flow.",
        "",
        "Allowed claim tiers: " + ", ".join(sorted(allowed)),
        "Narrative role: " + str(section_contract.get("role") or "Write a bounded evidence-guided manuscript section."),
        "Required narrative sequence: " + str(section_contract.get("sequence") or "study frame → observation → bounded interpretation"),
        "Target minimum length: approximately " + str(section_contract.get("minimum_words") or 120) + " words unless available evidence is genuinely sparse.",
        "Evidence cards:",
    ]
    for card in packet.get("reader_cards") or []:
        if card.get("claim_tier") not in allowed or (allowed_categories and card.get("category") not in allowed_categories):
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
        lines.extend([
            "",
            "Manuscript-wide narrative spine:",
            "- Central question: " + _clean_text(plan.get("central_question")),
            "- Bounded central answer: " + _clean_text(plan.get("central_answer")),
        ])
        section_finding_ids = list(_as_mapping(plan.get("section_finding_map")).get(section_type) or [])
        if section_finding_ids:
            lines.append("- Findings assigned to this section: " + ", ".join(str(item) for item in section_finding_ids))
        for finding in plan.get("key_findings") or []:
            if not isinstance(finding, Mapping) or (section_finding_ids and finding.get("finding_id") not in section_finding_ids):
                continue
            lines.append(
                f"  - {finding.get('finding_id')}: observation={finding.get('observation')}; "
                f"evidence={', '.join(finding.get('evidence_ids') or [])}; "
                f"figures={', '.join(finding.get('figure_keys') or []) or 'none'}; "
                f"boundary={finding.get('alternative_explanation') or 'retain the stated claim ceiling'}; "
                f"next test={finding.get('next_test')}"
            )
        bridge = _as_mapping(plan.get("bridge_commitments")).get(section_type)
        if bridge:
            lines.append("- Required section bridge: " + _clean_text(bridge))
        if plan.get("do_not_repeat"):
            lines.append("- Do not repeat: " + "; ".join(_clean_text(item) for item in plan.get("do_not_repeat") or []))
        claim_map = _as_mapping(plan.get("sections")).get(section_type)
        if claim_map:
            lines.extend(["", "Section plan:", _clean_text(claim_map)])
    lines.append("=== END READER-READY AUTHORING PACKET ===")
    return "\n".join(lines)


def deterministic_authoring_plan(packet: Mapping[str, Any]) -> dict:
    """Return a safe plan fallback when the optional LLM planner is unavailable."""
    cards = packet.get("reader_cards") or []
    categories = {str(card.get("category")) for card in cards if isinstance(card, Mapping)}
    story_contract = _as_mapping(packet.get("section_story_contract"))
    default_sections = {
        "abstract": "State the study frame, quantitative scope, observed temporal pattern, candidate-context boundary, and a testable next question.",
        "introduction": "Connect the recorded study question, time-resolved measurement design, and traceable literature context without making current-order mechanistic claims.",
        "results": "Progress from coverage to selected temporal profile observations, interval-wise concordance, protein-linked context, and candidate context.",
        "discussion": "Distinguish current observations from cited external context, explain alternative interpretations, and end with a discriminating validation experiment.",
        "conclusion": "Summarize what was observed and what is proposed for testing without promoting candidate context to direct regulation.",
        "methods": "Describe recorded normalization, conventional/de-novo representation, Temporal Profile Clustering, and Interval-wise Concordance Analysis.",
    }
    for section, contract in story_contract.items():
        default_sections[section] = str(
            contract.get("sequence") or default_sections.get(section) or "study frame → observation → bounded interpretation"
        )
    study_card = next(
        (card for card in cards if isinstance(card, Mapping) and card.get("category") == "study_frame"),
        {},
    )
    central_question = _clean_text(study_card.get("reader_summary")) or (
        "How do the recorded phosphorylation and linked protein-abundance measurements change across the sampled study design?"
    )
    phase2_named_categories = {"measured_feature_observation", "quantitation_comparison"}
    has_phase2_named_evidence = any(
        isinstance(card, Mapping) and card.get("category") in phase2_named_categories
        for card in cards
    )
    category_priority = (
        "measured_feature_observation",
        "quantitation_comparison",
        "temporal_profile",
        "quantitative_observation",
        "kinase_context",
        "candidate_discovery",
    ) + (() if has_phase2_named_evidence else ("quantitative_landscape",))
    selected_cards: list[Mapping[str, Any]] = []
    for category in category_priority:
        candidate = next(
            (
                card for card in cards
                if isinstance(card, Mapping)
                and card.get("category") == category
                and "not generated" not in str(card.get("reader_summary") or "").lower()
            ),
            None,
        )
        if candidate:
            selected_cards.append(candidate)
        if len(selected_cards) >= 3:
            break
    figure_cards = [figure for figure in packet.get("figure_cards") or [] if isinstance(figure, Mapping)]

    def figure_keys_for(card: Mapping[str, Any]) -> list[str]:
        category = str(card.get("category") or "")
        desired = {
            "quantitative_landscape": {"reader_quantitative_heatmap"},
            "temporal_profile": {"reader_temporal_profiles", "reader_interval_concordance"},
            "quantitative_observation": {"reader_protein_context"},
            "measured_feature_observation": {"reader_quantitative_heatmap"},
            "quantitation_comparison": {"reader_protein_context"},
        }.get(category, set())
        feature_id = str(_as_mapping(card.get("feature_identity")).get("reader_feature_id") or "")
        matches: list[str] = []
        for figure in figure_cards:
            if figure.get("figure_key") not in desired:
                continue
            selected_ids = {
                str(value) for value in figure.get("selected_reader_feature_ids") or [] if str(value)
            }
            if feature_id and selected_ids and feature_id not in selected_ids:
                continue
            matches.append(str(figure.get("figure_key")))
        return matches

    def next_test_for(category: str) -> str:
        if category == "temporal_profile":
            return "repeat the time course with biological replicates and denser sampling around the selected profile changes"
        if category in {"quantitative_observation", "quantitation_comparison"}:
            return "test the matched PTM/protein pattern with an explicitly paired quantitative contrast model"
        if category == "measured_feature_observation":
            return "repeat the named feature trajectory in an independent experiment with matched sampling and the same quantitative contract"
        if category in {"kinase_context", "candidate_discovery"}:
            return "evaluate the candidate in a matched vehicle–stimulus–intervention time course without changing the discovery result"
        return "repeat the measured contrast in an independent experiment using the same preprocessing and reporting contract"

    key_findings = []
    for index, card in enumerate(selected_cards, 1):
        category = str(card.get("category") or "")
        key_findings.append({
            "finding_id": f"F{index}",
            "category": category,
            "observation": _clean_text(card.get("reader_summary")),
            "evidence_ids": [str(item) for item in card.get("evidence_ids") or []],
            "reader_feature_id": str(_as_mapping(card.get("feature_identity")).get("reader_feature_id") or "") or None,
            "figure_keys": figure_keys_for(card),
            "citation_ids": [str(item) for item in card.get("citation_ids") or []],
            "allowed_interpretation": "retain the card claim tier and reader-facing verbs",
            "alternative_explanation": _clean_text(card.get("counterevidence")) or "the observed pattern can reflect multiple biological and measurement processes",
            "next_test": next_test_for(category),
        })
    central_answer = " ".join(str(finding.get("observation") or "") for finding in key_findings[:3]).strip()
    finding_ids = [str(finding.get("finding_id")) for finding in key_findings]
    return {
        "source": "deterministic_fallback",
        "sections": default_sections,
        "available_categories": sorted(categories),
        "central_question": central_question,
        "central_answer": central_answer or "The available reader-safe evidence supports a bounded descriptive answer and a defined next experiment.",
        "key_findings": key_findings,
        "section_finding_map": {
            "abstract": finding_ids,
            "introduction": [],
            "methods": [],
            "results": finding_ids,
            "discussion": finding_ids,
            "conclusion": finding_ids,
            "research_question_answers": finding_ids,
        },
        "bridge_commitments": {
            "introduction": "End with the exact current-study objective that Results addresses.",
            "methods": "End by stating that the analysis separates measured patterns, candidate context and testable hypotheses.",
            "results": "End with the bounded unresolved interpretation that Discussion evaluates.",
            "discussion": "End with the single most discriminating next experiment shared by the selected findings.",
            "conclusion": "Return to the central question without introducing a new number, pathway or candidate.",
        },
        "do_not_repeat": [
            "raw event totals outside the one Results paragraph where they are first defined",
            "the same no-call or evidence-unavailable sentence in more than one section",
            "figure descriptions without adding section-specific interpretation",
        ],
    }


def apply_llm_authoring_plan(planned_text: str, fallback: Mapping[str, Any] | None = None) -> dict:
    """Parse a model section plan into the deterministic section map.

    구현 대상: 2026-09-07 reader-authoring plan→write contract.
    사전등록: 2026-09-07 표시 계약.
    해석 한계: 파싱 실패 시 deterministic fallback이 유지된다. 계획이 데이터 존재를 증명하지 않는다.
    주장 금지: 계획 문구로 직접 조절이나 경로 활성화를 주장하지 않는다.
    """
    base = _as_mapping(fallback)
    sections = dict(_as_mapping(base.get("sections")))
    result = {
        "source": str(base.get("source") or "deterministic_fallback"),
        "sections": sections,
        "available_categories": list(base.get("available_categories") or []),
        "central_question": str(base.get("central_question") or ""),
        "central_answer": str(base.get("central_answer") or ""),
        "key_findings": list(base.get("key_findings") or []),
        "section_finding_map": dict(_as_mapping(base.get("section_finding_map"))),
        "bridge_commitments": dict(_as_mapping(base.get("bridge_commitments"))),
        "do_not_repeat": list(base.get("do_not_repeat") or []),
    }
    text = str(planned_text or "").strip()
    if not text:
        return result
    result["gemini_plan"] = text
    json_text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    try:
        parsed_json = json.loads(json_text)
    except Exception:
        parsed_json = None
    if isinstance(parsed_json, Mapping):
        parsed_sections = _as_mapping(parsed_json.get("sections"))
        if len(parsed_sections) >= 3:
            sections.update({str(key): _clean_text(value) for key, value in parsed_sections.items() if _clean_text(value)})
            result["sections"] = sections
            result["source"] = "gemini_structured_with_deterministic_evidence_spine"
        # The model may reorder supplied finding IDs, but it may not invent or
        # rewrite their factual observations/evidence bindings.
        known_ids = {str(item.get("finding_id")) for item in result["key_findings"] if isinstance(item, Mapping)}
        section_map = _as_mapping(parsed_json.get("section_finding_map"))
        for section, ids in section_map.items():
            if isinstance(ids, list):
                filtered = [str(item) for item in ids if str(item) in known_ids]
                if filtered:
                    result["section_finding_map"][str(section)] = filtered
        return result
    matches = list(_PLAN_SECTION_RE.finditer(text))
    parsed: dict[str, str] = {}
    for index, match in enumerate(matches):
        name = match.group(1).lower()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = _clean_text(text[start:end])
        if body:
            parsed[name] = body
    if len(parsed) >= 3:
        sections.update(parsed)
        result["source"] = "gemini_parsed_with_deterministic_fallback"
    else:
        result["source"] = "deterministic_fallback_unparsed_gemini_plan"
    return result


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


def _candidate_residue_feature_labels(packet: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    """Return current-order feature identities lacking localized-site evidence."""
    labels: list[tuple[str, str, str]] = []
    for card in packet.get("reader_cards") or []:
        if not isinstance(card, Mapping) or card.get("category") != "measured_feature_observation":
            continue
        measurement = _as_mapping(card.get("measurement_provenance"))
        if measurement.get("reader_measurement_unit") == "localized_ptm_site_feature":
            continue
        identity = _as_mapping(card.get("feature_identity"))
        gene = str(identity.get("gene") or "").strip()
        residue = str(identity.get("candidate_residue_annotation") or "").strip()
        if gene and residue:
            labels.append((gene, residue, f"{gene} modified-precursor feature with candidate residue annotation {residue}"))
    return labels


def _repair_candidate_residue_site_claim(sentence: str, labels: Iterable[tuple[str, str, str]]) -> tuple[str, bool]:
    """Prevent candidate residue annotations from being relabelled as localized sites."""
    if not re.search(r"\b(?:phosphosite|phosphorylation site|localized site|site-specific)\b", sentence, flags=re.IGNORECASE):
        return sentence, False
    repaired = sentence
    changed = False
    for gene, residue, replacement in labels:
        pattern = re.compile(
            rf"\b{re.escape(gene)}\s*(?:[-( ]+)?{re.escape(residue)}\b(?:\s+(?:phosphosite|phosphorylation site|site))?",
            flags=re.IGNORECASE,
        )
        if pattern.search(repaired):
            repaired = pattern.sub(replacement, repaired)
            changed = True
    return repaired, changed


def _replace_unsafe_terms(text: str) -> str:
    if re.search(
        r"\b(?:(?:does|do|did|can|could|would|should|is|are|was|were|has|have|had)\s+not|"
        r"cannot|can't|couldn't|didn't|doesn't)\s+(?:directly\s+)?"
        r"(?:prove|establish|demonstrate|show|activate|cause|drive|support|infer)\b",
        text,
        flags=re.IGNORECASE,
    ):
        return text
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
        (r"\bkinase activity\b", "kinase-family candidate context"),
        (r"\bpathway activation\b", "pathway-membership context"),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def _split_sentences(text: str) -> list[str]:
    return [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", text or "") if sentence.strip()]


def _split_paragraphs(text: str) -> list[str]:
    """Return non-empty manuscript paragraphs without flattening their order."""
    return [paragraph.strip() for paragraph in re.split(r"\n\s*\n+", text or "") if paragraph.strip()]


def validate_and_repair_sections(
    sections: Mapping[str, Any],
    packet: Mapping[str, Any],
) -> tuple[dict, dict]:
    """Validate evidence/citation/claim boundaries and repair clauses locally.

    구현 대상: 2026-09-07 reader-authoring validator contract.
    사전등록: 2026-09-07 표시 계약.
    해석 한계: 문장 수리는 필요조건이며 모델이 패킷 밖 지식을 쓰지 않았음을 증명하지 않는다.
    주장 금지: validator pass를 kinase 귀속 또는 인과 입증으로 해석하지 않는다.

    Valid observation sentences are retained even without draft-only [EVID:]
    anchors. A problematic clause is rewritten or removed; no whole section is
    replaced with a deterministic status paragraph.
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
        metadata_contract = _as_mapping(packet.get("study_metadata_contract"))
        candidate_residue_labels = _candidate_residue_feature_labels(packet)
        repaired_paragraphs: list[str] = []
        sentence_index = 0
        for paragraph_index, paragraph in enumerate(_split_paragraphs(content), 1):
            if paragraph.startswith("#") and "\n" not in paragraph:
                repaired_paragraphs.append(paragraph)
                continue
            retained_sentences: list[str] = []
            for sentence in _split_sentences(paragraph):
                sentence_index += 1
                evidence_ids = _EVIDENCE_MARKER_RE.findall(sentence)
                citations = [item.lower() for item in _REFERENCE_MARKER_RE.findall(sentence)]
                actions: list[str] = []
                reasons: list[str] = []
                if section_name == "methods":
                    repaired_estimator, estimator_repaired = repair_quantitation_estimator_sentence(sentence)
                    if estimator_repaired:
                        sentence = repaired_estimator
                        actions.append("replace_quantitation_estimator_with_immutable_contract")
                        reasons.append("quantitation_estimator_paraphrase_mismatch")
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
                repaired_metadata, metadata_repaired = repair_unrecorded_metadata_claim(sentence, metadata_contract)
                if metadata_repaired:
                    sentence = repaired_metadata
                    actions.append("remove_unrecorded_metadata_inference")
                    reasons.append("study_metadata_lineage_or_species_not_recorded")
                repaired_measurement, measurement_repaired = _repair_candidate_residue_site_claim(
                    sentence, candidate_residue_labels
                )
                if measurement_repaired:
                    sentence = repaired_measurement
                    actions.append("rewrite_candidate_residue_as_modified_precursor_feature")
                    reasons.append("candidate_residue_not_localized_site")
                semantic_repaired, semantic_actions, semantic_reasons = repair_semantic_sentence(
                    sentence,
                    packet.get("reader_cards") or [],
                )
                if semantic_actions:
                    sentence = semantic_repaired
                    actions.extend(semantic_actions)
                    reasons.extend(semantic_reasons)
                if _LITERATURE_SIGNAL_RE.search(sentence) and not citations:
                    # Preserve current-study observations but remove an unsupported external-context clause.
                    clauses = re.split(r"(?<=[,;:])\s+|\s+(?=whereas\b|while\b)", sentence, flags=re.IGNORECASE)
                    keep = [clause for clause in clauses if not _LITERATURE_SIGNAL_RE.search(clause)]
                    sentence = " ".join(keep).strip()
                    actions.append("remove_uncited_literature_clause")
                    reasons.append("literature_context_without_stable_citation")
                if _ANY_EVIDENCE_RESIDUE_RE.search(sentence):
                    sentence = _ANY_EVIDENCE_RESIDUE_RE.sub("", sentence)
                    actions.append("remove_malformed_evidence_anchor")
                    reasons.append("malformed_draft_only_anchor")
                sentence = normalize_reader_prose(sentence)
                if sentence:
                    retained_sentences.append(sentence)
                audit_entries.append({
                    "section": section_name,
                    "paragraph_index": paragraph_index,
                    "sentence_index": sentence_index,
                    "evidence_ids": evidence_ids,
                    "citation_ids": citations,
                    "claim_tier_budget": sorted(allowed_tiers),
                    "validator_action": actions or ["retain"],
                    "reason_code": reasons or ["within_contract"],
                    "retained": bool(sentence),
                })
            if retained_sentences:
                repaired_paragraphs.append(" ".join(retained_sentences))
        section_text = "\n\n".join(repaired_paragraphs)
        if section_name == "methods":
            section_text = ensure_quantitation_methods_contract(section_text)
        validated[section_name] = section_text
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
    text = _ANY_EVIDENCE_RESIDUE_RE.sub("", text)
    return normalize_reader_prose(text)


_MAJOR_HEADING_ALIASES = {
    "abstract": "abstract",
    "introduction": "introduction",
    "background": "introduction",
    "methods": "methods",
    "materials and methods": "methods",
    "results": "results",
    "findings": "results",
    "discussion": "discussion",
    "conclusion": "conclusion",
    "conclusions": "conclusion",
    "research question answers": "research_question_answers",
    "supplementary research question answers": "research_question_answers",
    "appendix: research question answers": "research_question_answers",
}


def audit_report_output_correctness(
    text: str,
    figure_manifest: Mapping[str, Any] | None = None,
    metadata_contract: Mapping[str, Any] | None = None,
    reader_cards: Iterable[Mapping[str, Any]] | None = None,
) -> dict:
    """Audit final reader output without changing scientific content.

    The gate checks only rendering/contract correctness.  It does not promote a
    biological claim or assert that an analysis layer was scientifically valid.
    """
    body = str(text or "")
    major_sequence: list[str] = []
    heading_labels: list[str] = []
    for match in re.finditer(r"(?m)^##\s+(.+?)\s*$", body):
        label = re.sub(r"[*_`]", "", match.group(1)).strip().rstrip(".:")
        canonical = _MAJOR_HEADING_ALIASES.get(label.lower())
        if canonical:
            major_sequence.append(canonical)
            heading_labels.append(label)
    duplicate_headings = sorted(
        heading for heading, count in __import__("collections").Counter(major_sequence).items() if count > 1
    )
    expected_order = [
        "abstract", "introduction", "methods", "results", "discussion", "conclusion", "research_question_answers",
    ]
    order_rank = {name: index for index, name in enumerate(expected_order)}
    observed_ranks = [order_rank[name] for name in major_sequence if name in order_rank]
    heading_order_valid = observed_ranks == sorted(observed_ranks)

    declared_figures = {
        re.sub(r"\s+", " ", match.group(1)).strip().lower()
        for match in re.finditer(r"(?mi)^###\s+((?:Supplementary\s+)?Figure\s+\d+[A-Z]?)\b", body)
    }
    mentioned_figures = {
        re.sub(r"\s+", " ", match.group(0)).strip().lower()
        for match in re.finditer(r"\b(?:Supplementary\s+)?Figure\s+\d+[A-Z]?\b", body, flags=re.IGNORECASE)
    }
    phantom_figure_mentions = sorted(mentioned_figures - declared_figures)
    missing_image_paths: list[str] = []
    for image_match in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", body):
        path = image_match.group(1).strip()
        if path.startswith(("http://", "https://")):
            continue
        try:
            if not __import__("pathlib").Path(path).exists():
                missing_image_paths.append(path)
        except OSError:
            missing_image_paths.append(path)

    manifest = _as_mapping(figure_manifest)
    eligible_missing_paths = sorted(
        str(figure.get("figure_key") or "unknown")
        for figure in manifest.get("figures") or []
        if isinstance(figure, Mapping)
        and figure.get("placement") in {"main", "supplementary"}
        and not str(figure.get("image_path") or "").strip()
    )
    malformed_anchor_count = len(_ANY_EVIDENCE_RESIDUE_RE.findall(body))
    unresolved_reference_marker_count = len(re.findall(r"\[REF:", body, flags=re.IGNORECASE))
    reason_codes: list[str] = []
    if malformed_anchor_count:
        reason_codes.append("malformed_evidence_anchor")
    if unresolved_reference_marker_count:
        reason_codes.append("unresolved_reference_marker")
    if duplicate_headings:
        reason_codes.append("duplicate_major_heading")
    if not heading_order_valid:
        reason_codes.append("invalid_major_heading_order")
    if phantom_figure_mentions:
        reason_codes.append("phantom_figure_reference")
    if missing_image_paths:
        reason_codes.append("missing_rendered_figure_path")
    if eligible_missing_paths:
        reason_codes.append("eligible_manifest_figure_missing_path")
    metadata = _as_mapping(metadata_contract)
    metadata_blocking_conflicts = list(metadata.get("release_blocking_conflicts") or [])
    metadata_review_reasons = list(metadata.get("review_reason_codes") or [])
    if metadata_blocking_conflicts:
        reason_codes.append("unresolved_study_metadata_conflict")
    review_reason_codes: list[str] = []
    if metadata_review_reasons:
        review_reason_codes.append("study_metadata_review_required")
    semantic_audit = audit_semantic_claims(body, reader_cards or [])
    language_audit = audit_language_quality(body)
    if semantic_audit.get("violation_count"):
        reason_codes.append("unrepaired_scientific_semantic_claim")
    if language_audit.get("fragment_count"):
        review_reason_codes.append("sentence_fragment_review_required")
    if language_audit.get("lowercase_sentence_start_count"):
        review_reason_codes.append("lowercase_sentence_start_review_required")
    if language_audit.get("doubled_punctuation_count"):
        review_reason_codes.append("punctuation_damage_review_required")
    if language_audit.get("section_word_budget_violation_count"):
        review_reason_codes.append("section_word_budget_review_required")
    reason_codes = sorted(set(reason_codes))
    review_reason_codes = sorted(set(review_reason_codes))
    status = "blocked_for_review" if reason_codes else "draft_review_required" if review_reason_codes else "release_candidate"
    return {
        "contract_version": "reader_report_output_correctness.v2",
        "status": status,
        "reason_codes": reason_codes,
        "review_reason_codes": review_reason_codes,
        "major_heading_sequence": major_sequence,
        "major_heading_labels": heading_labels,
        "duplicate_major_headings": duplicate_headings,
        "major_heading_order_valid": heading_order_valid,
        "declared_figure_labels": sorted(declared_figures),
        "mentioned_figure_labels": sorted(mentioned_figures),
        "phantom_figure_mentions": phantom_figure_mentions,
        "missing_image_paths": sorted(set(missing_image_paths)),
        "eligible_manifest_figures_missing_path": eligible_missing_paths,
        "malformed_evidence_anchor_count": malformed_anchor_count,
        "unresolved_reference_marker_count": unresolved_reference_marker_count,
        "study_metadata_status": metadata.get("metadata_status"),
        "study_metadata_blocking_conflicts": metadata_blocking_conflicts,
        "study_metadata_review_reasons": metadata_review_reasons,
        "semantic_claim_audit": semantic_audit,
        "language_quality_audit": language_audit,
    }


def _summaries_by_category(packet: Mapping[str, Any], *categories: str, limit: int = 4) -> list[str]:
    """Return bounded card summaries without turning a manuscript into a dump."""
    selected: list[str] = []
    category_set = set(categories)
    for card in packet.get("reader_cards") or []:
        if not isinstance(card, Mapping) or card.get("category") not in category_set:
            continue
        summary = _clean_text(card.get("reader_summary"))
        if summary:
            selected.append(summary)
        if len(selected) >= limit:
            break
    return selected


def _literature_context_for_fallback(packet: Mapping[str, Any], *, limit: int = 2) -> str:
    """Render only traceable, selected literature context with stable markers."""
    fragments: list[str] = []
    for card in packet.get("reader_cards") or []:
        if not isinstance(card, Mapping) or card.get("category") != "traceable_literature":
            continue
        summary = _clean_text(card.get("reader_summary"))
        citation_ids = [str(value).strip().lower() for value in card.get("citation_ids") or [] if str(value).strip()]
        if summary and citation_ids:
            fragments.append(summary + " " + " ".join(f"[REF:{identifier}]" for identifier in citation_ids))
        if len(fragments) >= limit:
            break
    return " ".join(fragments)


def _default_summary(values: list[str], default: str) -> str:
    return " ".join(values) if values else default


def render_reader_section_fallback(
    section_type: str,
    packet: Mapping[str, Any],
    *,
    questions: Iterable[str] | None = None,
) -> str:
    """Write a substantive, evidence-bounded section when the LLM is unavailable.

    This is intentionally a section-specific scientific narrative rather than the
    legacy generic fallback.  It uses only reader cards and keeps the same study
    frame → observation → bounded interpretation → next-test logic as the model
    prompt.  It never receives raw diagnostics or external context without a
    stable citation marker.
    """
    study = _default_summary(
        _summaries_by_category(packet, "study_frame", limit=1),
        "The report evaluates the recorded PTM and linked total-protein measurements in the stated experimental system.",
    )
    quantitative = _default_summary(
        _summaries_by_category(packet, "quantitative_landscape", "quantitative_provenance", limit=3),
        "The available quantitative data are interpreted as recorded PTM measurements with linked protein-abundance context.",
    )
    measured = _default_summary(
        _summaries_by_category(packet, "measured_feature_observation", limit=4),
        "Named current-order feature observations were not available in the reader packet for this legacy analysis run.",
    )
    adjustment = _default_summary(
        _summaries_by_category(packet, "quantitation_comparison", limit=3),
        "An independent unadjusted-versus-protein-adjusted PTM comparison was not available for this legacy analysis run.",
    )
    temporal = _default_summary(
        _summaries_by_category(packet, "temporal_profile", limit=4),
        "The time-course analysis provides a bounded description of measured Temporal Profile Clusters and Interval-wise Concordance Analysis.",
    )
    kinase = _default_summary(
        _summaries_by_category(packet, "kinase_context", limit=3),
        "Any kinase-related result is retained as contribution-weighted candidate context rather than a direct kinase–substrate assignment.",
    )
    candidates = _default_summary(
        _summaries_by_category(packet, "candidate_discovery", limit=3),
        "Observed features can be prioritized for a pre-specified follow-up measurement without being represented as confirmed substrates.",
    )
    literature = _literature_context_for_fallback(packet)

    if section_type == "abstract":
        paragraphs = [
            f"{study} {measured}",
            adjustment,
            f"{temporal} {kinase}",
            "Together, these measurements provide a time-resolved, protein-abundance-aware description of the recorded response. "
            f"{candidates} The resulting interpretation remains bounded to measured observations and candidate context, and the next informative step is a matched temporal or orthogonal assay that can discriminate the proposed explanation.",
        ]
        if literature:
            paragraphs[2] += " Selected literature is used only as external context for this interpretation. " + literature
        return "\n\n".join(paragraphs)

    if section_type == "introduction":
        paragraphs = [
            f"{study} The scientific question is how the recorded perturbation is reflected in time-resolved PTM measurements while accounting for linked changes in total-protein abundance.",
            "PTM measurements can change on a different time scale from protein abundance. The analysis therefore retains independent unadjusted PTM, protein-adjusted PTM, and linked protein contrasts as distinct quantitative observations, rather than treating their ratio as an absolute occupancy measurement or a direct readout of kinase activity. " + quantitative,
            "Temporal Profile Clustering summarizes similar measured phosphorylation-feature profiles, and Interval-wise Concordance Analysis describes endpoint activity-state concordance within fixed clusters across adjacent sampled intervals. These descriptive layers identify patterns that warrant comparison and follow-up without asserting a common regulator or causal signal flow. " + temporal,
            (
                "The selected traceable literature frames the biological question and defines the external context against which the current observations can be discussed. " + literature
                if literature else
                "This data-only report does not introduce external pathway background because traceable publication metadata were not available for comparison."
            ),
            "Accordingly, the report asks which quantitative and temporal patterns are observed in this experimental system, which protein-linked or kinase-family candidate contexts remain interpretable, and which next measurement would most clearly distinguish a testable hypothesis from an observed association.",
        ]
        return "\n\n".join(paragraphs)

    if section_type == "results":
        return "\n\n".join([
            "### Quantitative landscape\n\n" + study + " " + quantitative,
            "### Named current-order feature observations\n\n" + measured,
            "### Protein-adjustment comparison\n\n" + adjustment,
            "### Temporal-profile observations\n\n" + temporal,
            "### Candidate context\n\n" + kinase + " " + candidates,
            "### Interpretation boundary\n\nThe reported patterns describe measured phosphorylation features and linked protein-abundance context. They do not on their own establish direct kinase–substrate regulation, catalytic activation, causal propagation, isoform-specific activity, or a perturbation outcome.",
        ])

    if section_type == "research_question_answers":
        prompt_questions = [str(question).strip() for question in questions or [] if str(question).strip()]
        if not prompt_questions:
            prompt_questions = ["What does the current experiment establish, and what requires a discriminating follow-up measurement?"]
        answers: list[str] = []
        evidence_cycle = [measured, adjustment, temporal]
        for index, question in enumerate(prompt_questions[:3], 1):
            evidence = evidence_cycle[index - 1]
            answers.append(
                f"### Q{index}. {question}\n\n"
                f"{evidence} This supplementary answer is restricted to the supplied quantitative evidence; "
                "a matched temporal measurement, orthogonal assay, or pre-specified perturbation design is required before a direct regulatory conclusion."
            )
        return "\n\n".join(answers)

    if section_type == "discussion":
        paragraphs = [
            f"{measured} {adjustment} These current-order observations anchor the interpretation before aggregate temporal and candidate summaries.",
            f"{temporal} These observations define a structured time-resolved response in the recorded experimental system, while retaining protein abundance and PTM evidence as distinct but linked layers.",
            f"{kinase} {candidates}",
            (
                "The selected literature supplies external context for comparison rather than validation of an Order-specific mechanism. " + literature
                if literature else
                "Because traceable literature metadata were not available, this data-only discussion does not extend the observed patterns to external pathway assertions."
            ),
            "The remaining alternative explanation is that a measured temporal association may reflect shared regulation, protein-abundance context, incomplete mapping, or other unmeasured processes. A follow-up experiment should therefore preserve matched temporal sampling and specify in advance the observation that would support or refute the candidate interpretation.",
        ]
        return "\n\n".join(paragraphs)

    if section_type == "methods":
        estimator_contract = _as_mapping(packet.get("quantitation_estimator_contract"))
        estimator_paragraph = _clean_text(estimator_contract.get("deterministic_methods_paragraph"))
        return "\n\n".join([
            study,
            quantitative,
            estimator_paragraph,
            "Welch's unequal-variance t-test was used when both groups contained at least two replicate values, and Benjamini–Hochberg correction was applied to available p-values within the corresponding comparison output. Reported q-values are therefore analysis-specific uncertainty summaries, not evidence of causal regulation. Control-undetected features were not assigned a pseudocount-derived conventional fold change on the independent unadjusted axis.",
            "Hierarchical Clustering of Temporal Phosphorylation Feature Profiles was used to derive descriptive Temporal Profile Clusters. Interval-wise Concordance Analysis summarized retained concordance, concordance gain, and concordance loss across adjacent sampled intervals within fixed clusters, using evaluable within-cluster pair-window comparisons as the denominator. Cluster count and distance settings are retained in the technical audit when available.",
            "Large conventional Log2FC values were retained as measured numeric contrasts but were not used alone to infer biological priority, mechanistic importance, direct regulatory strength, absolute occupancy, or kinase activity. Control-undetected features were kept as detection/LOD context rather than placed on conventional quantitative axes or magnitude ranks.",
        ])

    if section_type == "conclusion":
        return "\n\n".join([
            f"{measured} {adjustment} Together, these observations answer the study question at the level of measured modified-precursor and linked protein contrasts.",
            f"{temporal} The interpretation remains descriptive rather than causal. The next step is one matched, pre-specified validation experiment that directly tests the principal selected finding.",
        ])

    return "\n\n".join([
        f"{study} {measured} {adjustment}",
        f"{temporal} {kinase}",
        f"This report advances a bounded quantitative description and identifies testable candidate context without promoting an observed association to direct regulation or causality. {candidates}",
    ])


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
    return "\n\n".join([
        f"# {title}",
        f"*Generated: {generated_at}*",
        "## Abstract\n\n" + render_reader_section_fallback("abstract", packet),
        "## Introduction\n\n" + render_reader_section_fallback("introduction", packet),
        "## Methods\n\n" + render_reader_section_fallback("methods", packet),
        "## Results\n\n" + render_reader_section_fallback("results", packet),
        "## Discussion\n\n" + render_reader_section_fallback("discussion", packet),
        "## Conclusion\n\n" + render_reader_section_fallback("conclusion", packet),
        "## References\n\n"
        "Traceable publication metadata were not available for this Report. No external biological or prior-work claims are included.",
    ])


def assess_narrative_continuity(
    sections: Mapping[str, Any],
    packet: Mapping[str, Any],
    plan: Mapping[str, Any] | None = None,
) -> dict:
    """Audit narrative depth and the shared study arc without rewriting prose.

    This is a release-review signal only.  It must never trigger a whole-section
    replacement or elevate the evidence tier of the generated manuscript.
    """
    contract = _as_mapping(packet.get("section_story_contract"))
    observed_categories = {
        str(card.get("category"))
        for card in packet.get("reader_cards") or []
        if isinstance(card, Mapping)
    }
    audits: dict[str, dict] = {}
    normalized_sentence_locations: dict[str, list[str]] = {}
    for section, rule in contract.items():
        text = str(_as_mapping(sections).get(section) or "").strip()
        words = len(re.findall(r"\b\w+[\w-]*\b", text))
        paragraph_values = [item.strip() for item in re.split(r"\n\s*\n", text) if item.strip() and not item.lstrip().startswith("#")]
        paragraphs = len(paragraph_values)
        paragraph_sentence_counts = [len(_split_sentences(item)) for item in paragraph_values]
        one_sentence_paragraph_fraction = (
            sum(count <= 1 for count in paragraph_sentence_counts) / len(paragraph_sentence_counts)
            if paragraph_sentence_counts else 0.0
        )
        for sentence in _split_sentences(text):
            normalized = re.sub(r"[^a-z0-9]+", " ", sentence.lower()).strip()
            if len(normalized.split()) >= 8:
                normalized_sentence_locations.setdefault(normalized, []).append(section)
        categories = [str(item) for item in rule.get("categories") or []]
        usable_categories = [item for item in categories if item in observed_categories]
        has_internal_leak = bool(_INTERNAL_TERM_RE.search(text))
        audits[section] = {
            "word_count": words,
            "paragraph_count": paragraphs,
            "one_sentence_paragraph_fraction": round(one_sentence_paragraph_fraction, 4),
            "target_minimum_words": int(rule.get("minimum_words") or 0),
            "story_sequence": str(rule.get("sequence") or ""),
            "available_story_categories": usable_categories,
            "internal_term_leak_detected": has_internal_leak,
            "status": (
                "missing" if not text else
                "review_for_depth" if words < max(60, int(rule.get("minimum_words") or 0) // 2) else
                "review_for_fragmented_paragraphs" if paragraphs >= 4 and one_sentence_paragraph_fraction > 0.75 else
                "review_for_internal_leakage" if has_internal_leak else
                "present"
            ),
        }
    repeated_across_sections = [
        {"sentence": sentence, "sections": sorted(set(locations))}
        for sentence, locations in normalized_sentence_locations.items()
        if len(set(locations)) > 1
    ]
    verified_labels = {
        str(figure.get("figure_label") or "").lower()
        for figure in packet.get("figure_cards") or []
        if isinstance(figure, Mapping) and str(figure.get("figure_label") or "").strip()
    }
    mentioned_labels = {
        match.group(0).lower()
        for text in _as_mapping(sections).values()
        for match in re.finditer(r"\bFigure\s+\d+[A-Z]?\b", str(text), flags=re.IGNORECASE)
    }
    return {
        "contract_version": "reader_narrative_continuity_audit.v2",
        "manuscript_plan_source": str(_as_mapping(plan).get("source") or "unavailable"),
        "central_question": str(_as_mapping(plan).get("central_question") or ""),
        "selected_finding_ids": [
            str(item.get("finding_id")) for item in _as_mapping(plan).get("key_findings") or [] if isinstance(item, Mapping)
        ],
        "sections": audits,
        "repeated_sentences_across_sections": repeated_across_sections,
        "unverified_figure_mentions": sorted(mentioned_labels - verified_labels),
        "review_required_sections": [
            section for section, audit in audits.items()
            if audit["status"] != "present"
        ],
        "manuscript_review_required": bool(
            any(audit["status"] != "present" for audit in audits.values())
            or repeated_across_sections
            or (mentioned_labels - verified_labels)
        ),
    }


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
        "narrative_continuity_audit": state.get("reader_narrative_continuity_audit") or {},
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
