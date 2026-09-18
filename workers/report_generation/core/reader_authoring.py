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
from ptm_shared.feature_identity import (
    audit_feature_identities,
    project_reader_display_identity,
    scan_reader_technical_id_leaks,
)
from ptm_shared.evidence_record_contract import typed_record
from .companion_evidence import (
    atlas_cards,
    cluster_profile_cards,
    dual_track_cards,
    module_interval_records,
    multiform_cards,
    paired_fraction_cards,
    prepare_companion_state,
    typed_concordance_records,
)
from .research_questions import build_question_map, audit_question_coverage, unresolved_question_paragraphs

from typing import Any, Iterable, Mapping

from common.section_budgets import SECTION_BUDGETS
from common.temporal_utils import condition_sort_key
from .quantitative_claims import AXIS_LABELS, quantitative_records, validate_quantitative_sentence
from report_generation.core.measured_feature_cards import (
    build_feature_observation_cards,
    build_quantitation_comparison_cards,
    select_finding_cards,
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
    sentence_evidence_scope,
    is_negated_boundary,
)
from ptm_shared.quantitation_estimator_contract import (
    build_quantitation_estimator_contract,
    ensure_quantitation_methods_contract,
    repair_quantitation_estimator_sentence,
)


AUTHORING_PACKET_VERSION = "reader_authoring_packet.v5"
VALID_CLAIM_TIERS = {"O1", "O2", "C1", "L1", "H1", "D1"}

# The reader-facing manuscript has one stable story arc.  These are authoring
# obligations, not evidence and not a claim-promotion mechanism.  Keeping them
# beside the card contract prevents every section from becoming an inventory of
# the same compact diagnostics.
SECTION_STORY_CONTRACT = {
    "abstract": {
        "categories": ("study_frame", "measured_feature_observation", "quantitation_comparison", "temporal_profile", "kinase_context", "protein_context", "pathway_context", "candidate_discovery"),
        "role": "Summarize the study frame, the most informative observed pattern, its bounded significance, and the discriminating next question.",
        "sequence": "study frame → measured landscape → selected observation → bounded candidate context → next question",
    },
    "introduction": {
        "categories": ("study_frame", "quantitation_provenance", "traceable_literature", "temporal_profile"),
        "role": "Establish the recorded biological question, why time-resolved PTM and protein measurements are informative, the traceable background, and the study objective.",
        "sequence": "study problem → measurement rationale → cited context → unresolved question → present study objective",
    },
    "results": {
        "categories": ("quantitative_landscape", "quantitative_provenance", "measured_feature_observation", "quantitation_comparison", "temporal_profile", "kinase_context", "pathway_context", "candidate_discovery"),
        "role": "Report measured PTM scope before selected temporal observations, quantitation-validity context, and any eligible candidate-family context.",
        "sequence": "coverage → selected PTM temporal observation → quantitation-validity context → temporal/candidate context → observation boundary",
        "paragraph_roles": (
            "measurement_scope_and_quantitative_landscape",
            "principal_observed_temporal_pattern",
            "quantitation_validity_and_alternative_explanation",
            "temporal_profile_and_interval_concordance",
            "candidate_family_context",
        ),
    },
    "discussion": {
        "categories": ("measured_feature_observation", "quantitation_comparison", "quantitative_provenance", "temporal_profile", "kinase_context", "pathway_context", "candidate_discovery", "traceable_literature"),
        "role": "Interpret current observations in the selected literature context, state the alternative explanation that remains, and identify the next discriminating experiment.",
        "sequence": "principal observation → cited comparison → bounded interpretation → remaining alternative → discriminating validation",
        "paragraph_roles": (
            "principal_observation_and_source_anchored_literature",
            "competing_explanation_and_current_limitation",
            "discriminating_next_experiment",
        ),
    },
    "methods": {
        "categories": ("study_frame", "quantitation_provenance", "quantitation_comparison", "temporal_profile"),
        "role": "Describe only recorded quantitative and temporal analysis procedures and their interpretation boundaries.",
        "sequence": "study design → normalization and replicate unit → explicit contrast equations → Welch/BH uncertainty → clustering and interval concordance denominator → missingness/de-novo policy → reporting boundary",
    },
    "conclusion": {
        "categories": ("study_frame", "measured_feature_observation", "quantitation_comparison", "temporal_profile", "kinase_context", "protein_context", "pathway_context", "candidate_discovery"),
        "role": "Close the same study question in no more than two short paragraphs with the observed advance, the bounded interpretation, and one testable next step.",
        "sequence": "study question → observed advance → bounded interpretation → next validation",
    },
}
for _section, _contract in SECTION_STORY_CONTRACT.items():
    _contract.update(SECTION_BUDGETS[_section])

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
    r"activates?|activated|activation loop|catalytic activity|causal propagation|"
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
READER_SAFE_LIMITATIONS = {
    "candidate_family_unavailable": (
        "No candidate-family interpretation meeting the prespecified evidence criteria was retained for this dataset."
    ),
    "footprint_not_supported": (
        "The available measurements did not support a family-specific footprint interpretation under the prespecified criteria."
    ),
    "direct_relationship_not_assigned": (
        "The present measurements were not used to assign direct kinase–site relationships."
    ),
    "temporal_global_order_not_established": (
        "Temporal summaries describe observed sampled-interval patterns; they do not establish a globally ordered causal sequence."
    ),
}
_TECHNICAL_APPENDIX_SPLIT_RE = re.compile(
    r"(?im)^##\s+(?:Technical Appendix|Technical Audit)\b.*$",
)
_FORBIDDEN_TECHNICAL_PATTERNS = (
    ("gate_layer", re.compile(r"\b(?:P[0-5]|M[0-4]|R[0-4])\b")),
    ("temporal_window_id", re.compile(r"\bTW-\d+\b", re.I)),
    ("legacy_wave_id", re.compile(r"\b(?:Co-)?Wave[- ]?\d+\b", re.I)),
    ("loto", re.compile(r"\bLOTO\b")),
    ("n_eff", re.compile(r"\bn_eff\b", re.I)),
    ("status_assignment", re.compile(r"\bstatus=")),
    ("candidate_capacity", re.compile(r"\bcandidate capacity\b", re.I)),
    ("selected_candidate_cards", re.compile(r"\bselected candidate cards\b", re.I)),
    ("not_recorded", re.compile(r"\bnot recorded\b", re.I)),
    ("not_evaluable", re.compile(r"\bnot evaluable\b", re.I)),
    ("pair_window_denominator", re.compile(r"\bpair-window denominator\b", re.I)),
    ("global_adjacency_order", re.compile(r"\bglobal adjacency-order\b", re.I)),
    ("compact_packet", re.compile(r"\bcompact packet\b", re.I)),
    ("implementation_surface", re.compile(
        r"\b(?:renderer|sidecar|raw ledger|feature-level status records)\b", re.I
    )),
    ("kinase_footprint_diagnostics", re.compile(r"\bKinase Footprint Diagnostics\b", re.I)),
)


def audit_reader_technical_leakage(
    text: str,
    *,
    audience: str = "researcher_manuscript",
) -> dict:
    """Scan researcher main body for forbidden technical diagnostics.

    구현 대상: docs/report_audience_mode_contract_v1.md §5
    사전등록: 2026-09-15. 본문 누수 검사이지 분석 성능 검사가 아니다.
    해석 한계: 토큰 부재가 과학적 타당성을 증명하지 않는다.
    주장 금지: 누수 0건을 kinase 예측 향상으로 해석하지 않는다.
    """
    body = str(text or "")
    main_body = _TECHNICAL_APPENDIX_SPLIT_RE.split(body, maxsplit=1)[0]
    from .scientific_semantics import prose_without_reference_section
    narrative = prose_without_reference_section(main_body)
    findings: list[dict] = []
    if str(audience or "").strip().lower() != "researcher_manuscript":
        return {
            "status": "not_applicable",
            "reason_codes": [],
            "findings": [],
            "audience": audience,
        }
    for code, pattern in _FORBIDDEN_TECHNICAL_PATTERNS:
        matches = pattern.findall(narrative)
        if matches:
            findings.append({"reason_code": code, "match_count": len(matches), "examples": [str(item) for item in matches[:5]]})
    return {
        "status": "leak_detected" if findings else "clean",
        "reason_codes": ["researcher_technical_leakage"] if findings else [],
        "findings": findings,
        "audience": audience,
    }


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
        "value_records": module_interval_records(record, evidence_id),
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
        "analysis_scope_contract": {k:v for k,v in (state.get("analysis_evidence_inventory") or {}).items()
            if k in {"analysis_revision", "input_revision", "analysis_manifest_id", "coverage", "execution_status",
                     "evaluation_status", "track_status", "artifact_directory", "input_scope"}},
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
    policy = (state.get('source_run_manifest') or {}).get('normalization_policy')
    if policy == 'legacy_median.v1':
        method = 'sample-wise median scaling of PR and PG separately; a global intensity shift can be removed by this policy'
    elif policy == 'already_normalized.v1':
        method = 'the supplied normalized intensities without additional sample scaling'
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
        "normalization_policy": policy or 'not_recorded',
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
        anchors = [str(c.get("quote")) for c in ref.get("feature_comparisons") or [] if c.get("quote")]
        excerpt = " ".join(dict.fromkeys(anchors)) if anchors else excerpt
        source_excerpt = excerpt
        if len(excerpt) > 1800:
            # Bound quotes and unbound background share the same display cap.
            selected_sentences = []
            for sentence in _split_sentences(excerpt):
                if selected_sentences and sum(map(len, selected_sentences)) + len(sentence) > 1800:
                    break
                selected_sentences.append(sentence)
            excerpt = " ".join(selected_sentences)
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
            "excerpt_selection": {"rule": "comparison_source_anchors" if anchors else "complete_background_sentences", "source_characters": len(source_excerpt), "selected_characters": len(excerpt)},
            "allowed_verbs": ["reported", "described", "provided context for", "was consistent with"],
            "forbidden_interpretations": ["proved the current observation", "established a current direct relationship"],
            "counterevidence": "Literature context does not convert a prior relationship into a current-order observation.",
        })
    return cards


def _kinase_context_cards(state: Mapping[str, Any]) -> list[dict]:
    """Build bounded family-level kinase candidate context without raw diagnostics."""
    heatmap = _as_mapping(state.get("kinase_activity_heatmap")) or _as_mapping(state.get("frontend_kinase_analysis"))
    scores = [
        _as_mapping(row) for row in heatmap.get("kinase_scores") or []
        if isinstance(row, Mapping) and not row.get("is_sub_pattern")
    ]
    if not scores:
        return []

    def sort_key(row: Mapping[str, Any]) -> tuple[float, str]:
        try:
            magnitude = abs(float(row.get("peak_score") or 0.0))
        except (TypeError, ValueError):
            magnitude = 0.0
        return (-magnitude, str(row.get("canonical") or row.get("kinase") or ""))

    computed = [
        row for row in scores
        if str(_as_mapping(row.get("footprint_diagnostics")).get("status") or "not_evaluable") == "computed"
    ]
    ranked = sorted(scores, key=sort_key)
    pool = computed or [
        row for row in ranked
        if row.get("peak_score") is not None or _as_mapping(row.get("trajectory_evidence"))
    ]
    cards: list[dict] = []
    if not computed:
        cards.append({
            "card_id": "kinase.context_availability",
            "category": "kinase_context",
            "reader_summary": (
                f"{READER_SAFE_LIMITATIONS['footprint_not_supported']} "
                f"{READER_SAFE_LIMITATIONS['direct_relationship_not_assigned']} "
                "Stored candidate rankings and any signed interval comparisons remain observational context only."
            ),
            "claim_tier": "O1",
            "evidence_ids": ["kinase.context_availability"],
            "citation_ids": [],
            "allowed_verbs": ["did not support", "was not independently evaluated"],
            "forbidden_interpretations": ["kinase absence", "kinase inactivity", "kinase rank"],
            "counterevidence": "A non-evaluable footprint is not evidence that a kinase is absent or inactive.",
        })
    if not pool:
        return cards

    grouped: dict[tuple, list[dict]] = {}
    for row in sorted(pool, key=sort_key):
        equivalence = _as_mapping(row.get("footprint_equivalence"))
        group_id = equivalence.get("equivalence_group_id")
        # Equal scores and temporal summaries do not establish shared identity.
        fingerprint = ("explicit_equivalence", str(group_id)) if group_id else (
            "candidate", str(row.get("canonical") or row.get("kinase") or ""))
        grouped.setdefault(fingerprint, []).append(row)

    emitted: set[str] = set()
    candidate_index = 0
    for rows in grouped.values():
        row = rows[0]
        names: list[str] = []
        for item in rows:
            equivalence = _as_mapping(item.get("footprint_equivalence"))
            members = [str(member).strip() for member in equivalence.get("members") or [] if str(member).strip()]
            canonical = str(item.get("canonical") or item.get("kinase") or "").strip()
            names.extend(members or ([canonical] if canonical else []))
        names = list(dict.fromkeys(names))
        candidate = names[0] if names else str(row.get("canonical") or row.get("kinase") or "candidate kinase").strip()
        equivalence = _as_mapping(row.get("footprint_equivalence"))
        group_id = str(equivalence.get("equivalence_group_id") or " / ".join(names) or candidate).strip()
        if group_id in emitted:
            continue
        emitted.add(group_id)
        footprint_status = str(_as_mapping(row.get("footprint_diagnostics")).get("status") or "not_evaluable")
        trajectory = _as_mapping(row.get("trajectory_evidence"))
        trajectory_status = str(trajectory.get("support_status") or "legacy_unavailable")
        named_ok = footprint_status == "computed" or trajectory_status == "computed"
        family_label = (
            (" / ".join(names) + " candidate group" if len(names) >= 2 else f"{candidate} candidate")
            if named_ok
            else "stored candidate"
        )
        concordance = trajectory.get("median_direction_concordance_fraction")
        correlation = trajectory.get("median_signed_profile_correlation")
        n_targets = trajectory.get("n_targets_evaluable")
        if trajectory_status == "computed" and concordance is not None:
            correlation_clause = (
                f" and signed profile correlation {float(correlation):.2f}"
                if correlation is not None else ""
            )
            target_clause = f" across {int(n_targets)} evaluable substrate targets" if n_targets else ""
            trajectory_clause = (
                f"{family_label} had direction concordance fraction {float(concordance):.2f}"
                f"{correlation_clause}{target_clause}. "
                "This signed interval comparison is not a catalytic rate."
            )
        elif trajectory and trajectory_status != "legacy_unavailable":
            trajectory_clause = (
                f" {family_label} signed interval comparison was {trajectory_status.replace('_', ' ')} "
                f"({trajectory.get('unavailable_reason') or 'insufficient shared observed intervals'})."
            )
        else:
            trajectory_clause = f" {family_label} signed interval comparison was not available on this stored heatmap."
        if footprint_status == "computed":
            footprint_clause = f"A contribution-weighted {family_label} footprint provided kinase-family candidate context across the sampled conditions. "
        else:
            footprint_clause = (
                "A stored candidate ranking provided kinase-family candidate context. "
                f"{READER_SAFE_LIMITATIONS['footprint_not_supported']} "
            )
        value_records = [
            typed_record(
                record_type="kinase_footprint",
                entity_id=candidate,
                metric_id="peak_score",
                value=row.get("peak_score"),
                unit="weighted_signed_sum",
                condition=str(row.get("peak_condition") or ""),
                estimator="observed_tmm.v1",
                support_status="computed" if footprint_status == "computed" else "not_evaluable",
                evidence_id=f"kinase.footprint.{group_id}",
                source={"schema_version": "observed_tmm.v1", "footprint_status": footprint_status},
            )
        ]
        if concordance is not None:
            value_records.append(typed_record(
                record_type="kinase_trajectory",
                entity_id=candidate,
                metric_id="direction_concordance_fraction",
                value=round(float(concordance), 4),
                unit="fraction",
                numerator=None,
                denominator=None,
                estimator="kinase_trajectory_evidence.v1",
                support_status=trajectory_status,
                evidence_id=f"kinase.trajectory.{group_id}",
                source={"schema_version": "kinase_trajectory_evidence.v1"},
            ))
        if correlation is not None:
            value_records.append(typed_record(
                record_type="kinase_trajectory",
                entity_id=candidate,
                metric_id="signed_profile_correlation",
                value=round(float(correlation), 4),
                unit="pearson_r",
                estimator="kinase_trajectory_evidence.v1",
                support_status=trajectory_status,
                evidence_id=f"kinase.trajectory.{group_id}",
                source={"schema_version": "kinase_trajectory_evidence.v1"},
            ))
        if n_targets is not None:
            value_records.append(typed_record(
                record_type="kinase_trajectory",
                entity_id=candidate,
                metric_id="n_targets_evaluable",
                value=int(n_targets),
                unit="target_count",
                estimator="kinase_trajectory_evidence.v1",
                support_status=trajectory_status,
                evidence_id=f"kinase.trajectory.{group_id}",
                source={"schema_version": "kinase_trajectory_evidence.v1"},
            ))
        candidate_index += 1
        cards.append({
            "card_id": f"kinase.{candidate_index}",
            "category": "kinase_context",
            "evidence_type": "kinase_candidate",
            "reader_summary": footprint_clause + trajectory_clause,
            "claim_tier": "C1",
            "evidence_ids": [f"kinase.footprint.{group_id}", f"kinase.trajectory.{group_id}"],
            "citation_ids": [],
            "value_records": value_records,
            "trajectory_evidence": {
                "support_status": trajectory_status,
                "median_direction_concordance_fraction": concordance,
                "median_signed_profile_correlation": correlation,
                "n_targets_evaluable": trajectory.get("n_targets_evaluable"),
                "unavailable_reason": trajectory.get("unavailable_reason"),
            },
            "figure_keys": ["reader_interval_concordance"],
            "allowed_verbs": ["provided candidate context", "was consistent with", "prioritized for testing"],
            "forbidden_interpretations": ["kinase activation", "direct kinase–site attribution", "isoform-specific activity"],
            "counterevidence": (
                "Shared substrate support and family equivalence are retained as robustness context; direct kinase–site "
                "attribution and isoform-specific activity are not made from this dataset. Interval concordance is not "
                "a catalytic rate."
            ),
        })
    return cards


def _protein_trajectory_cards(state: Mapping[str, Any], *, maximum: int = 3) -> list[dict]:
    heatmap = _as_mapping(state.get("kinase_activity_heatmap"))
    propagation = _as_mapping(state.get("signal_propagation_data") or heatmap.get("signal_propagation"))
    effectors = [
        _as_mapping(row) for row in propagation.get("effectors") or []
        if isinstance(row, Mapping) and row.get("gene")
    ]
    cards = []
    for row in effectors[:maximum]:
        gene = str(row.get("gene"))
        pattern = str(row.get("pattern") or "observed_protein_trajectory")
        cards.append({
            "card_id": f"protein.{gene}",
            "category": "protein_context",
            "evidence_type": "protein_trajectory",
            "reader_summary": (
                f"{gene} protein-group abundance was tracked as {pattern.replace('_', ' ')}. "
                "This is a protein-group point estimate, not an enzyme-activity call."
            ),
            "claim_tier": "O1",
            "evidence_ids": [f"protein.trajectory.{gene}"],
            "citation_ids": [],
            "value_records": [
                typed_record(
                    record_type="protein_group",
                    entity_id=gene,
                    metric_id="max_change",
                    value=row.get("max_change"),
                    unit="log2_contrast",
                    estimator="protein_group_point_estimate",
                    support_status="computed" if row.get("max_change") is not None else "not_computable",
                    test_status="not_a_significance_test",
                    evidence_id=f"protein.trajectory.{gene}",
                )
            ],
            "allowed_verbs": ["was tracked", "provided protein context"],
            "forbidden_interpretations": ["kinase activity", "significant abundance change from amplitude alone"],
            "counterevidence": "Has_PTM=False means PTM was not quantified for this protein in these data.",
        })
    return cards


def _pathway_context_cards(state: Mapping[str, Any], *, maximum: int = 3) -> list[dict]:
    facts = [
        _as_mapping(row) for row in state.get("pathway_statistical_evidence") or []
        if isinstance(row, Mapping) and row.get("pathway_name")
    ]
    cards = []
    for row in facts[:maximum]:
        name = str(row.get("pathway_name"))
        q_value = row.get("q_value")
        cards.append({
            "card_id": f"pathway.{len(cards) + 1}",
            "category": "pathway_context",
            "evidence_type": "pathway_context",
            "reader_summary": (
                f"{name} had an enrichment q of {q_value} in the supplied statistical artifact. "
                "Global enrichment is not cluster enrichment and is not pathway activation."
            ),
            "claim_tier": "C1",
            "evidence_ids": [f"pathway.{name}"],
            "citation_ids": [],
            "value_records": [
                typed_record(
                    record_type="pathway_enrichment",
                    entity_id=name,
                    metric_id="q_value",
                    value=q_value,
                    unit="q",
                    estimator=str(row.get("estimator") or "supplied_pathway_test"),
                    support_status="computed" if q_value is not None else "not_computable",
                    test_status="supplied_enrichment_test",
                    evidence_id=f"pathway.{name}",
                    source={"sha256": row.get("source_artifact_sha256")},
                )
            ],
            "allowed_verbs": ["was enriched", "had a supplied q"],
            "forbidden_interpretations": ["pathway activation", "cluster enrichment substitute"],
            "counterevidence": "Enrichment q is bound to the supplied universe and FDR family only.",
        })
    return cards


def build_evidence_utilization(cards: list[dict], observation_audit: Mapping[str, Any] | None = None) -> dict:
    """Count source → adapted → selected cards. Absence ≠ adapter failure."""
    by_type: dict[str, dict[str, int]] = {}
    for card in cards:
        evidence_type = str(card.get("evidence_type") or card.get("category") or "unspecified")
        bucket = by_type.setdefault(evidence_type, {
            "adapted": 0, "with_value_records": 0, "with_trajectory": 0,
        })
        bucket["adapted"] += 1
        if card.get("value_records"):
            bucket["with_value_records"] += 1
        if card.get("trajectory_evidence"):
            bucket["with_trajectory"] += 1
    return {
        "schema_version": "report_evidence_utilization.v1",
        "by_evidence_type": by_type,
        "observation_selection_audit": dict(observation_audit or {}),
        "exclusion_reasons": list((observation_audit or {}).get("exclusions") or []),
    }


def adapt_discovery_candidates(synthesis: Mapping[str, Any], *, maximum: int = 5, state: Mapping[str, Any] | None = None) -> tuple[list[dict], dict]:
    """Adapt production trajectories, with an explicit legacy schema boundary."""
    packet = _as_mapping(synthesis.get("candidate_discovery_packet"))
    field = next((key for key in ("selected_cards", "candidate_cards", "cards") if key in packet), None)
    candidates = list(packet.get(field) or []) if field else []
    audit = {"contract_version": "candidate_reader_adapter.v1", "source_contract": packet.get("contract_version", "legacy_unversioned"),
             "source_field": field, "input_count": len(candidates), "eligible_count": 0,
             "reader_card_count": 0, "body_selected_count": 0, "exclusions": []}
    cards = []
    for index, candidate in enumerate(candidates):
        candidate = _as_mapping(candidate)
        identity = _as_mapping(candidate.get("feature_identity"))
        rows = [{**candidate, "precursor_id": identity.get("source_feature_id") or candidate.get("precursor_id"),
                 "position": candidate.get("position") or identity.get("candidate_residue_annotation"),
                 "gene": candidate.get("gene") or identity.get("gene"), **_as_mapping(point)}
                for point in candidate.get("trajectory") or []]
        observed = build_feature_observation_cards({**dict(state or {}), "vector_plot_raw_data": rows}, maximum=1, minimum_points=1)
        if not observed:
            audit["exclusions"].append({"input_index": index, "reason": "no_identity_complete_numeric_observation"})
            continue
        audit["eligible_count"] += 1
        if len(cards) >= maximum:
            audit["exclusions"].append({"input_index": index, "reason": "reader_capacity"})
            continue
        card = observed[0]
        key = "candidate." + card["feature_identity"]["reader_feature_id"]
        rationale = candidate.get("discovery_rationale") or []
        card.update(card_id=key, evidence_ids=[key], category="candidate_discovery",
                    discovery_rationale=list(rationale), candidate_contract=packet.get("contract_version", "legacy_unversioned"),
                    primary_bucket=candidate.get("primary_bucket"), annotation_context=candidate.get("annotation_context"))
        card["mechanistic_status"] = candidate.get("kinase_evaluation_status") or "not_evaluated"
        card["mechanistic_reason"] = candidate.get("kinase_no_call_reason") or "no_feature_bound_attribution_result_supplied"
        cards.append(card)
    audit["reader_card_count"] = len(cards)
    audit["status"] = "available" if cards else "no_eligible_candidates" if candidates else "not_supplied"
    return cards, audit


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
    state = prepare_companion_state(state)
    temporal = _as_mapping(temporal_evidence_packet or state.get("temporal_report_evidence_packet"))
    synthesis = _as_mapping(biological_synthesis_packet or state.get("biological_synthesis_packet"))
    metadata_contract = build_study_metadata_contract(_study_context_with_override(state))
    from ptm_shared.annotation_species import audit_annotation_species
    species_audit = audit_annotation_species(state.get("parsed_ptms") or [], _study_context_with_override(state))
    metadata_contract["native_annotation_audit"] = species_audit
    if species_audit["status"] == "review_required":
        metadata_contract["review_reason_codes"].append("native_annotation_revalidation_required")
    cards = [_study_frame_card(state, synthesis), *_quantitative_cards(synthesis), _normalization_card(state)]
    cross = state.get('cross_talk_data') or state.get('crosstalk_data') or {}
    if cross.get('evaluation_status') == 'computed':
        from ptm_shared.evidence_record_contract import typed_record
        evidence_id = 'crosstalk.observation.counts'
        metrics = {'shared_proteins': 'dual_ptm_proteins', 'concordant_patterns': 'concordant_pairs',
                   'discordant_patterns': 'discordant_pairs', 'candidate_temporal_orderings': 'sequential_gating'}
        cards.append({'card_id': evidence_id, 'category': 'quantitative_landscape',
            'evidence_type': 'atlas_observation', 'claim_tier': 'O1', 'evidence_ids': [evidence_id],
            'citation_ids': [], 'reader_summary': 'The two PTM inventories contain shared proteins and descriptive joint patterns. Counts describe overlap and temporal observations; they do not establish direct cross-talk.',
            'counterevidence': 'Biological pairing, enzyme activity and causal gating are not established by overlapping proteins or temporal order.',
            'allowed_verbs': ['observed', 'contained'], 'forbidden_interpretations': ['causal gating', 'activation', 'independent validation'],
            'value_records': [typed_record(record_type='atlas_observation', entity_id='cross_talk',
                metric_id=metric, value=len(cross.get(field) or []), unit='count', estimator='cross_ptm_descriptive_inventory_count.v1',
                support_status='descriptive_observation', evidence_id=evidence_id,
                source={'module': 'cross_talk', 'field': field, 'denominator': 'computed_cross_ptm_inventory'})
                for metric, field in metrics.items()]})
        import hashlib
        for observation in cross.get("dual_ptm_proteins") or []:
            gene = str(observation.get("gene") or "")
            evidence_id = "crosstalk.observation." + hashlib.sha256(gene.encode()).hexdigest()[:16]
            records = []
            for condition, values in sorted((observation.get("temporal_comparison") or {}).items()):
                for arm in ("primary", "secondary"):
                    value = values.get(arm + "_ptm_log2fc")
                    if value is None:
                        continue
                    records.append({**typed_record(record_type="atlas_observation", entity_id=gene,
                        metric_id=arm + "_protein_adjusted_ptm", value=value, unit="log2 ratio",
                        condition=condition, estimator="precomputed_protein_adjusted_contrast",
                        support_status="descriptive_observation", evidence_id=evidence_id,
                        source={"module": "cross_talk", "arm": arm, "ptm_type": cross.get(arm + "_ptm_type"),
                                "sites": observation.get(arm + "_sites"), "input_status": cross.get("source_status")}),
                        "axis": "protein_adjusted", "display_identity": gene + " " + str(cross.get(arm + "_ptm_type"))})
            cards.append({"card_id": evidence_id, "category": "quantitative_landscape",
                "evidence_type": "atlas_observation", "claim_tier": "O1", "evidence_ids": [evidence_id],
                "citation_ids": [], "feature_label": gene,
                "reader_summary": f"{gene}: {observation.get('pattern')} descriptive cross-PTM pattern; sites and axes remain separate.",
                "counterevidence": "Different PTM forms and sampled condition patterns do not establish causal gating or catalytic activity. No replicate-level concordance test was supplied.",
                "allowed_verbs": ["observed", "co-occurred"], "forbidden_interpretations": ["causal gating", "activation"],
                "value_records": records})
    estimator_contract = build_quantitation_estimator_contract((state.get('source_run_manifest') or {}).get('normalization_policy'))
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
    observations = build_feature_observation_cards(state, maximum=max(20, len(state.get("vector_plot_raw_data") or [])), minimum_points=1)
    question_map = build_question_map(state.get("original_research_questions") or state.get("research_questions") or [], observations)
    requested_ids = {fid for q in question_map["questions"] for fid in q["feature_ids"]}
    observations.sort(key=lambda c: (c["feature_identity"]["reader_feature_id"] not in requested_ids,))
    for card in observations:
        card["question_ids"] = [q["question_id"] for q in question_map["questions"] if card["feature_identity"]["reader_feature_id"] in q["feature_ids"]]
    selected_observations = observations
    observation_selection_audit = {"contract_version": "observation_inventory.v1", "input_unique_feature_count": len(observations),
                                   "selected_count": len(observations), "exclusions": []}
    cards.extend(selected_observations)
    cards.extend(build_quantitation_comparison_cards(state, maximum=max(1, len(observations))))
    for index, record in enumerate(temporal.get("records") or [], 1):
        if isinstance(record, Mapping):
            card = _record_card(record, index)
            if card and card["category"] == "temporal_profile":
                cards.append(card)
    kinase_cards = _kinase_context_cards(state)
    protein_cards = _protein_trajectory_cards(state)
    pathway_cards = _pathway_context_cards(state)
    dual_cards = dual_track_cards(state)
    paired_cards = paired_fraction_cards(state)
    form_cards = multiform_cards(selected_observations)
    atlas_context_cards = atlas_cards(state)
    cluster_cards = cluster_profile_cards(state)
    companion_cards = dual_cards + paired_cards + form_cards + atlas_context_cards + cluster_cards
    cards.extend(kinase_cards)
    cards.extend(protein_cards)
    cards.extend(pathway_cards)
    cards.extend(companion_cards)
    question_map = build_question_map(
        state.get("original_research_questions") or state.get("research_questions") or [],
        list(observations) + kinase_cards + protein_cards + pathway_cards + companion_cards,
    )

    candidate_cards, candidate_transfer_audit = adapt_discovery_candidates(synthesis, state=state,
        maximum=max(1, len(synthesis.get('candidate_observation_cards') or [])))
    cards.extend(candidate_cards)
    if not candidate_cards:
        cards.append({
            "card_id": "candidate.family_unavailable",
            "category": "candidate_discovery",
            "reader_summary": READER_SAFE_LIMITATIONS["candidate_family_unavailable"],
            "claim_tier": "C1",
            "evidence_ids": ["candidate.family_unavailable"],
            "citation_ids": [],
            "allowed_verbs": ["was not retained", "did not meet"],
            "forbidden_interpretations": ["kinase absence", "negative discovery"],
            "counterevidence": "Absence of a retained candidate family is not evidence that a kinase is inactive.",
        })
    section_plan = _as_mapping(temporal.get("section_plan"))
    if section_plan.get("observation_only_claim_ceiling") or not any(
        card.get("category") == "temporal_profile" for card in cards
    ):
        cards.append({
            "card_id": "temporal.global_order_boundary",
            "category": "temporal_profile",
            "reader_summary": READER_SAFE_LIMITATIONS["temporal_global_order_not_established"],
            "claim_tier": "O2",
            "evidence_ids": ["temporal.global_order_boundary"],
            "citation_ids": [],
            "allowed_verbs": ["describe", "do not establish"],
            "forbidden_interpretations": ["global causal sequence", "pathway activation"],
            "counterevidence": "Local sampled-interval patterns are not a globally ordered cascade.",
        })

    source_references = list(references if references is not None else state.get("collected_references") or [])
    reference_cards = _literature_cards(source_references)
    for card in cards:
        if card.get("trajectory"):
            card["literature_comparison"] = _finding_literature_context(card, source_references, (state.get("finding_literature_retrieval") or {}).get("records", {}).get((card.get("feature_identity") or {}).get("reader_feature_id")))
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
            "quantitative_bindings": list(figure.get("quantitative_bindings") or []),
            "selected_reader_feature_ids": list(
                figure.get("selected_reader_feature_ids")
                or [
                    str(item.get("reader_feature_id") or "")
                    for item in figure.get("selected_features") or []
                    if str(item.get("reader_feature_id") or "")
                ]
            ),
        })
        if figure.get("figure_key") == "reader_interval_concordance":
            figure_cards[-1]["quantitative_bindings"] = list(figure.get("quantitative_bindings") or []) + [
                record for card in kinase_cards for record in card.get("value_records") or []
                if record.get("record_type") == "kinase_trajectory"
            ] + typed_concordance_records(figure.get("quantitative_bindings") or []) + [
                record for card in cards for record in card.get("value_records") or []
                if record.get("record_type") == "module_interval"
            ]
        if figure.get("figure_key") == "reader_temporal_profiles":
            figure_cards[-1]["quantitative_bindings"] = list(figure.get("quantitative_bindings") or []) + [
                record for card in cluster_cards for record in card.get("value_records") or []
                if record.get("record_type") == "cluster_profile"
            ]
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
        "report_scope_policy": "inventory_review_authoring.v1",
        "main_finding_word_budget": (state.get("report_config") or {}).get("main_finding_word_budget", 2400),
        "coverage_inventory": build_coverage_inventory(state, observations),
        "module_evidence_index": build_module_evidence_index(observations),
        "required_module_status": {
            "cross_talk": (state.get("cross_talk_data") or state.get("crosstalk_data") or {}).get("evaluation_status", "not_evaluable")
                           if state.get("analysis_mode") == "cross_talk" else "not_requested",
            "drug_repositioning": (state.get("drug_repositioning_results") or {}).get("evaluation_status", "not_evaluable")
                                  if state.get("report_type") == "extended" else "not_requested"},
        "module_evidence": {"biological_unit_crosswalk": state.get('biological_unit_crosswalk') or {'status': 'pairing_not_declared'}, "cross_talk": state.get("cross_talk_data") or state.get("crosstalk_data") or {"evaluation_status": "not_evaluable" if state.get('analysis_mode') == 'cross_talk' else "not_requested"},
                            "cascade_context": {key: (state.get('cascade_context_snapshot') or {}).get(key)
                                                for key in ('evidence_role', 'direct_relation_claim_allowed', 'cascade_pathway_names', 'required_limitations')},
                            "drug_repositioning": {"evidence_role": "candidate_hypothesis_context", "independent_validation": "not_performed",
                                                   "analysis": state.get("drug_repositioning_results") or {"evaluation_status": "not_requested"}}},
        "study_design": dict(state.get("sample_manifest") or {}),
        "research_question_evidence_map": question_map,
        "feature_identity_audit": audit_feature_identities(state.get("vector_plot_raw_data") or []),
        "mode": "citation_complete" if has_traceable_literature else "data_only",
        "reader_cards": reader_cards,
        "study_metadata_contract": metadata_contract,
        "observation_selection_audit": observation_selection_audit,
        "candidate_transfer_audit": candidate_transfer_audit,
        "report_evidence_utilization": build_evidence_utilization(reader_cards, observation_selection_audit),
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


def build_module_evidence_index(observations):
    """Thin, complete grouping over existing observation/claim identities.

    Descriptive temporal-pattern groups are not kinase families or causal
    pathways. Section projection resolves included members from the same packet.
    """
    import hashlib
    groups = {}
    for card in observations:
        patterns = tuple((axis, str(summary.get('label') or summary.get('pattern') or 'unknown'))
                         for axis, summary in sorted((card.get('axis_patterns') or {}).items()))
        key = hashlib.sha256(json.dumps(patterns).encode()).hexdigest()[:20]
        group = groups.setdefault(key, {'bundle_id': 'pattern.' + key, 'grouping': 'descriptive_axis_pattern',
            'patterns': patterns, 'study_frame_ref': 'study.frame', 'member_card_ids': [],
            'observation_claim_ids': [], 'parent_protein_ids': [],
            'required_limitations': ['Shared temporal patterns do not establish a regulatory relationship.'],
            'review_status': 'not_independently_reviewed'})
        group['member_card_ids'].append(card['card_id'])
        group['observation_claim_ids'].extend(card.get('evidence_ids') or [])
        group['parent_protein_ids'].extend(card.get('parent_protein_ids') or [])
    for group in groups.values():
        for field in ('member_card_ids', 'observation_claim_ids', 'parent_protein_ids'):
            group[field] = sorted(set(group[field]))
    return {'schema_version': 'module_evidence_index.v1', 'source': 'feature_observation_card.v3',
            'member_count': len(observations), 'bundles': [groups[key] for key in sorted(groups)]}


def build_coverage_inventory(state, observations):
    """Account for every input row separately from literature depth and manuscript space."""
    from ptm_shared.feature_identity import canonical_feature_identity
    card_ids = {(c.get("feature_identity") or {}).get("reader_feature_id") for c in observations}
    retrieval = (state.get("finding_literature_retrieval") or {}).get("records") or {}
    records = []
    for index, row in enumerate(state.get("vector_plot_raw_data") or []):
        identity = canonical_feature_identity(row)
        fid = identity.get("reader_feature_id")
        records.append({"row_index": index, "feature_id": identity.get("feature_id"), "reader_feature_id": fid,
                        "condition": row.get("condition") or row.get("Condition"),
                        "analysis_status": "processed" if fid in card_ids else "not_evaluable",
                        "analysis_reason": None if fid in card_ids else "identity_or_quantitation_unavailable",
                        "deep_review_status": retrieval.get(fid, {}).get("status", "not_searched"),
                        "authoring_destinations": ["appendix"], "authoring_reason": "inventory_retained"})
    return {"schema_version": "report_coverage_inventory.v1", "denominator": "input_vector_rows",
            "input_count": len(records), "accounted_count": len(records), "records": records,
            "analysis_evidence_inventory": state.get("analysis_evidence_inventory"),
            "source_observation_inventory": state.get("source_observation_inventory"),
            "source_inventory_status": "available" if state.get("source_observation_inventory") else "legacy_not_recorded"}


def format_authoring_packet_for_llm(packet: Mapping[str, Any], section_type: str, plan: Mapping[str, Any] | None = None, *, include_quantitative_records: bool = True) -> str:
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
        "Do not attribute direct regulation, activation or causality to current measurements without corresponding evidence. Cited literature may explain established mechanisms within its external species, cell and site scope. Clearly distinguish that context from a testable hypothesis about this experiment.",
        "Temporal Profile Clustering and Interval-wise Concordance Analysis are descriptive methods; do not call them causal flow.",
        "",
        "Allowed claim tiers: " + ", ".join(sorted(allowed)),
        "Narrative role: " + str(section_contract.get("role") or "Write a bounded evidence-guided manuscript section."),
        "Required narrative sequence: " + str(section_contract.get("sequence") or "study frame → observation → bounded interpretation"),
        "Target minimum length: approximately " + str(section_contract.get("minimum_words") or 120) + " words; maximum_words=" + str(section_contract.get("maximum_words") or "unbounded") + ". A shorter complete section is acceptable. Never pad evidence. Conclusion must retain finding, interpretation, limitation and next validation.",
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
        records = quantitative_records(card)
        if records:
            # The structured writer appends one authoritative token catalog.
            # Repeating every support/identity record here can exceed the input
            # limit before the provider is called, even for four small findings.
            if include_quantitative_records:
                lines.append("  Quantitative references: " + json.dumps(records, ensure_ascii=False))
            lines.append("  Observed pattern contract: " + json.dumps(card.get("axis_patterns") or {}, ensure_ascii=False))
            lines.append("  Literature comparison: " + json.dumps(card.get("literature_comparison") or {}, ensure_ascii=False))
    lines.append("Every quantitative clause must identify the reader display identity, condition and axis before the value. Different precursors at the same gene/site remain separate observations. Do not emit PF- or FEATURE- identifiers in reader prose. Missing p/q/n is unknown, never zero or non-significant. The ±0.15 tolerance is descriptive, not a significance test.")
    if packet.get("figure_cards"):
        lines.extend(["", "Eligible figure cards:"])
        for figure in packet["figure_cards"]:
            selected_labels = figure.get("selected_display_identities") or [
                item.get("display_label") or item.get("reader_display_identity")
                for item in figure.get("selected_features") or []
                if isinstance(item, dict)
            ]
            figure_line = (
                f"- {figure.get('figure_label')}: key={figure.get('figure_key')}; placement={figure.get('placement')}; "
                f"question={figure.get('question')}; selected_display_identities={selected_labels}"
            )
            if packet.get("packet_role") != "section_model" and figure.get("selected_reader_feature_ids"):
                figure_line += f"; selected_reader_feature_ids={figure.get('selected_reader_feature_ids', [])}"
            figure_line += "; use at most one eligible figure per paragraph."
            lines.append(figure_line)
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
            lines.append("  Finding claim contract: " + json.dumps({key: finding.get(key) for key in
                ("claim_scope", "pattern_support", "biological_reproducibility_claim_allowed", "opposing_feature_ids", "dependencies", "hypothesis_contract", "literature_comparison")}, ensure_ascii=False))
        bridge = _as_mapping(plan.get("bridge_commitments")).get(section_type)
        if bridge:
            lines.append("- Required section bridge: " + _clean_text(bridge))
        if plan.get("do_not_repeat"):
            lines.append("- Do not repeat: " + "; ".join(_clean_text(item) for item in plan.get("do_not_repeat") or []))
        claim_map = _as_mapping(plan.get("sections")).get(section_type)
        if claim_map:
            lines.extend(["", "Section plan:", _clean_text(claim_map)])
    if section_type in {"results", "discussion"}:
        lines.append("Internal question evidence map (integrate observations into Results and meaning/uncertainty into Discussion; no Q&A headings): " + json.dumps(packet.get("research_question_evidence_map") or {}, ensure_ascii=False))
    lines.append("=== END READER-READY AUTHORING PACKET ===")
    if packet.get("module_evidence"):
        lines.append("Module evidence (observations and hypotheses remain separate): " + json.dumps(packet["module_evidence"], default=str))
    if packet.get('resolved_module_bundles'):
        groups = [{key: value for key, value in bundle.items() if key != 'resolved_members'}
                  for bundle in packet['resolved_module_bundles']]
        lines.append('Descriptive module groups; interpret only the member cards resolved above, and keep unresolved members outside claim scope: ' + json.dumps(groups, default=str))
    return "\n".join(lines)


def _finding_literature_context(card, references, retrieval_status):
    """Keep supplied feature comparisons separate from measured facts.

    A citation identity is necessary, not proof that a comparison is correct.
    Empty retrieval never establishes novelty or a negative biological result.
    """
    fid = _as_mapping(card.get("feature_identity")).get("reader_feature_id")
    comparisons = []
    for ref in references:
        if not isinstance(ref, Mapping) or not is_traceable_reference(ref):
            continue
        for value in ref.get("feature_comparisons") or []:
            if not isinstance(value, Mapping) or value.get("reader_feature_id") != fid:
                continue
            if value.get("relationship") not in {"known_agreement", "disagreement", "not_explained_by_retrieved_evidence", "literature_background", "gene_function_context", "pathway_context", "compatible_pattern", "context_difference", "direct_site_evidence", "contradictory_evidence"}:
                continue
            if not value.get("external_finding") or not value.get("observation"):
                continue
            comparisons.append({**dict(value), "citation_id": _stable_reference_id(ref),
                                "claim_scope": "literature_context", "measured_relation": False,
                                "condition_differences": list(value.get("condition_differences") or []),
                                "comparison_status": value.get("comparison_status", "supplied_comparison_requires_source_review")})
    return {"contract_version": "finding_literature_comparison.v1",
            "status": (retrieval_status or {}).get("status", "comparisons_available" if comparisons else "retrieval_unavailable") if isinstance(retrieval_status, Mapping) else "comparisons_available" if comparisons else "retrieval_unavailable",
            "retrieval_record": dict(retrieval_status) if isinstance(retrieval_status, Mapping) else None,
            "comparisons": comparisons, "novelty_claim_allowed": False,
            "retrieval_scope": "finding_scoped_search" if isinstance(retrieval_status, Mapping) else "supplied_records_only", "conditions_not_matched_by_default": True}


def _finding_metadata(card, selected):
    fid = _as_mapping(card.get("feature_identity")).get("reader_feature_id")
    parents = set(card.get("parent_protein_ids") or [])
    opposing = []
    own = {p["condition"]: p for p in card.get("trajectory") or []}
    for other in selected:
        other_id = _as_mapping(other.get("feature_identity")).get("reader_feature_id")
        if other_id == fid or not parents.intersection(other.get("parent_protein_ids") or []):
            continue
        for point in other.get("trajectory") or []:
            left = own.get(point.get("condition"), {})
            if any(left.get(field) is not None and point.get(field) is not None and left[field] * point[field] < 0
                   for field in ("ptm_unadjusted_log2fc", "ptm_protein_adjusted_log2fc")):
                opposing.append(other_id)
                break
    return {"contract_version": "report_finding.v1", "claim_scope": "descriptive_pattern",
            "pattern_ids": [f"{fid}:{axis}:observed_joint_pattern.v1" for axis in card.get("axis_patterns") or {}],
            "supporting_feature_ids": [fid] if fid else [], "opposing_feature_ids": sorted(set(opposing)),
            "measurement_unit": _as_mapping(card.get("measurement_provenance")).get("reader_measurement_unit"),
            "dependencies": {"parent_protein_ids": sorted(parents), "shared_control": "retain_recorded_sample_ids",
                             "independent_sample_count": None, "sensitivity_status": "not_computed"},
            "pattern_q_value": None, "pattern_support": "descriptive_observations_no_pattern_level_test",
            "biological_reproducibility_claim_allowed": False,
            "mechanistic_status": card.get("mechanistic_status", "not_evaluated"),
            "mechanistic_reason": card.get("mechanistic_reason", "no_feature_bound_attribution_result_supplied"),
            "literature_comparison": card.get("literature_comparison", _finding_literature_context(card, [], None)),
            "hypothesis_contract": {"scope": "mechanistic_hypothesis", "requires": ["observation_evidence_ids", "citation_ids", "alternative_explanation", "discriminating_prediction"],
                                    "direct_regulation_claim_allowed": False},
            "claim_stage_mapping": {"O1": "observed_or_descriptive_pattern", "O2": "supported_only_with_claim_specific_analysis",
                                    "L1": "literature_context", "H1": "mechanistic_hypothesis", "D1": "requires_separate_perturbation_evidence"}}


def _supporting_context_cards(cards: Iterable[Mapping[str, Any]], *, maximum: int | None = None) -> list[dict]:
    """Keep kinase/module companions off the named-feature finding budget."""
    ranked = []
    for card in cards or []:
        if not isinstance(card, Mapping):
            continue
        if card.get("card_id") == "kinase.context_availability":
            continue
        if card.get("evidence_type") == "atlas_observation":
            continue
        if card.get("category") == "kinase_context" or card.get("evidence_type") in {
            "kinase_candidate", "multiform_comparison", "cluster_profile",
        }:
            ranked.append(dict(card))
    ranked.sort(key=lambda card: (
        0 if card.get("category") == "kinase_context" else 1,
        str(card.get("card_id") or ""),
    ))
    selected = []
    seen: set[str] = set()
    for card in ranked:
        card_id = str(card.get("card_id") or "")
        if not card_id or card_id in seen:
            continue
        seen.add(card_id)
        selected.append(card)
        if maximum is not None and len(selected) >= maximum:
            break
    return selected


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
    selected_cards, selection_audit = select_finding_cards(cards, word_budget=packet.get("main_finding_word_budget"))
    if not selected_cards:
        # Preserve the existing aggregate fallback only when no named observation
        # can be bound. Availability/kinase no-call is never itself a discovery.
        selected_cards = [card for card in cards if isinstance(card, Mapping)
                          and card.get("category") in {"temporal_profile", "quantitative_landscape"}][:3]
    transfer = packet.get("candidate_transfer_audit")
    if isinstance(transfer, dict):
        selected_ids = set(selection_audit["selected_reader_feature_ids"])
        transferred = [
            card for card in cards
            if card.get("category") == "candidate_discovery"
            and _as_mapping(card.get("feature_identity")).get("reader_feature_id")
        ]
        transfer["body_selected_count"] = sum(card["feature_identity"]["reader_feature_id"] in selected_ids for card in transferred)
        transfer["body_exclusions"] = [{"reader_feature_id": card["feature_identity"]["reader_feature_id"],
                                         "reason": "finding_selection_capacity_or_diversity"}
                                        for card in transferred if card["feature_identity"]["reader_feature_id"] not in selected_ids]
    figure_cards = [figure for figure in packet.get("figure_cards") or [] if isinstance(figure, Mapping)]

    def figure_keys_for(card: Mapping[str, Any]) -> list[str]:
        category = str(card.get("category") or "")
        desired = {
            "quantitative_landscape": {"reader_quantitative_heatmap"},
            "temporal_profile": {"reader_temporal_profiles", "reader_interval_concordance"},
            "quantitative_observation": {"reader_protein_context"},
            "measured_feature_observation": {"reader_joint_trajectories", "reader_quantitative_heatmap", "reader_protein_context"},
            "candidate_discovery": {"reader_joint_trajectories", "reader_quantitative_heatmap", "reader_protein_context"},
            "quantitation_comparison": {"reader_protein_context"},
            "kinase_context": {"reader_interval_concordance"},
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
            **_finding_metadata(card, selected_cards),
            "finding_id": f"F{index}",
            "category": category,
            "observation": _clean_text(card.get("reader_summary")),
            "evidence_ids": [str(item) for item in card.get("evidence_ids") or []],
            "reader_feature_id": str(_as_mapping(card.get("feature_identity")).get("reader_feature_id") or "") or None,
            "reader_display_identity": _card_display_identity(card),
            "figure_keys": figure_keys_for(card),
            "citation_ids": [str(item) for item in card.get("citation_ids") or []],
            "allowed_interpretation": "retain the card claim tier and reader-facing verbs",
            "alternative_explanation": _clean_text(card.get("counterevidence")) or "the observed pattern can reflect multiple biological and measurement processes",
            "next_test": next_test_for(category),
        })
    # Candidate-family, multiform, and cluster cards are supporting context for
    # the narrative. They must not inflate the selected named-observation set or
    # cause reader coverage to require a PF/FEATURE-like internal binding.
    supporting_contexts = [
        {
            "category": str(card.get("category") or "kinase_context"),
            "observation": _clean_text(card.get("reader_summary")),
            "evidence_ids": [str(item) for item in card.get("evidence_ids") or []],
            "reader_display_identity": _card_display_identity(card),
            "figure_keys": figure_keys_for(card),
            "citation_ids": [str(item) for item in card.get("citation_ids") or []],
            "alternative_explanation": _clean_text(card.get("counterevidence")) or "candidate context is not a direct kinase–substrate assignment",
            "next_test": next_test_for(str(card.get("category") or "kinase_context")),
        }
        for card in _supporting_context_cards(cards)
    ]
    feature_findings = [finding for finding in key_findings if finding.get("category") == "measured_feature_observation"]
    central_answer = " ".join(str(finding.get("observation") or "") for finding in (feature_findings or key_findings)[:3]).strip()
    finding_ids = [str(finding.get("finding_id")) for finding in key_findings]
    question_map = {**(packet.get("research_question_evidence_map") or {}), "questions": []}
    for question in (packet.get("research_question_evidence_map") or {}).get("questions") or []:
        related = [f for f in key_findings if f.get("reader_feature_id") in question.get("feature_ids", [])]
        question_map["questions"].append({**question, "finding_ids": [f["finding_id"] for f in related],
            "literature_evidence_ids": sorted({c["citation_id"] for f in related for c in (f.get("literature_comparison") or {}).get("comparisons") or []})})
    return {
        "source": "deterministic_fallback",
        "sections": default_sections,
        "available_categories": sorted(categories),
        "central_question": central_question,
        "central_answer": central_answer or "The available reader-safe evidence supports a bounded descriptive answer and a defined next experiment.",
        "key_findings": key_findings,
        "supporting_contexts": supporting_contexts,
        "finding_selection_audit": selection_audit,
        "section_finding_map": {
            "abstract": finding_ids,
            "introduction": [],
            "methods": [],
            "results": finding_ids,
            "discussion": finding_ids,
            "conclusion": finding_ids,
        },
        "research_question_evidence_map": question_map,
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
        "research_question_evidence_map": base.get("research_question_evidence_map", {}),
        "finding_selection_audit": dict(base.get("finding_selection_audit") or {}),
        "section_finding_map": dict(_as_mapping(base.get("section_finding_map"))),
        "bridge_commitments": dict(_as_mapping(base.get("bridge_commitments"))),
        "do_not_repeat": list(base.get("do_not_repeat") or []),
    }
    text = str(planned_text or "").strip()
    if not text:
        return result
    result["gemini_plan"] = text
    try:
        from common.model_json import parse_model_json
        parsed_json = parse_model_json(text)
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
                if filtered and (section not in {"results", "discussion"} or set(filtered) == known_ids):
                    result["section_finding_map"][str(section)] = filtered
        # The planner may express narrative intent; quantitative facts remain frozen.
        for key in ("central_question", "central_answer"):
            if isinstance(parsed_json.get(key), str):
                result[key] = parsed_json[key]
        for section, bridge in _as_mapping(parsed_json.get("bridge_commitments")).items():
            if section in result["sections"] and isinstance(bridge, str):
                result["bridge_commitments"][section] = bridge
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


def refresh_finding_context(plan, packet):
    """Refresh retrieved context without changing the frozen finding selection."""
    candidates, _ = select_finding_cards(packet.get("reader_cards") or [])
    by_id = {c["feature_identity"]["reader_feature_id"]: c for c in candidates}
    result = dict(plan)
    result["key_findings"] = []
    for finding in plan.get("key_findings") or []:
        card = by_id.get(finding.get("reader_feature_id"))
        result["key_findings"].append({**finding, **(_finding_metadata(card, candidates) if card else {})})
    selected_fids = {f.get("reader_feature_id") for f in result["key_findings"]}
    for record in (packet.get("coverage_inventory") or {}).get("records") or []:
        in_main = record.get("reader_feature_id") in selected_fids
        record["authoring_destinations"] = ["main", "appendix"] if in_main else ["appendix"]
        record["authoring_reason"] = "selected_finding" if in_main else "outside_main_manuscript_scope"
    # Update transfer counts for this exact packet, including final rebuilt packets.
    selected_ids = {f.get("reader_feature_id") for f in result["key_findings"]}
    transfer = packet.get("candidate_transfer_audit")
    if isinstance(transfer, dict):
        transferred = [
            c for c in packet.get("reader_cards") or []
            if c.get("category") == "candidate_discovery"
            and _as_mapping(c.get("feature_identity")).get("reader_feature_id")
        ]
        transfer["body_selected_count"] = sum(c["feature_identity"]["reader_feature_id"] in selected_ids for c in transferred)
        transfer["body_exclusions"] = [{"reader_feature_id": c["feature_identity"]["reader_feature_id"], "reason": "not_in_frozen_finding_selection"}
                                       for c in transferred if c["feature_identity"]["reader_feature_id"] not in selected_ids]
    return result


def focus_authoring_packet(packet, plan):
    """Filter reader cards to frozen findings while retaining the full audit mapping.

    Model-visible context must be built with build_section_model_packet(); this
    function keeps hidden identities and audit fields for validators and decode.
    """
    selected = {f.get("reader_feature_id") for f in plan.get("key_findings") or []}
    selected_evidence = {
        str(evidence_id)
        for finding in plan.get("key_findings") or []
        for evidence_id in finding.get("evidence_ids") or []
        if evidence_id
    }
    return {**packet, "reader_cards": [c for c in packet.get("reader_cards") or []
            if not c.get("feature_identity")
            or c["feature_identity"].get("reader_feature_id") in selected
            or selected_evidence.intersection(str(item) for item in c.get("evidence_ids") or [])
            or c.get("category") in {"kinase_context", "study_frame", "quantitation_provenance", "traceable_literature"}]}


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
            labels.append((
                gene,
                residue,
                identity.get("reader_display_identity")
                or project_reader_display_identity(
                    identity,
                    reader_measurement_unit=measurement.get("reader_measurement_unit"),
                ),
            ))
    return labels


def _card_display_identity(card: Mapping[str, Any]) -> str:
    identity = _as_mapping(card.get("feature_identity"))
    display = str(identity.get("reader_display_identity") or card.get("feature_label") or "").strip()
    disambiguator = str(identity.get("reader_disambiguator") or "").strip()
    if display and disambiguator and disambiguator not in display:
        return f"{display} {disambiguator}"
    return display or project_reader_display_identity(identity)


def _replace_known_technical_ids(sentence: str, packet: Mapping[str, Any]) -> tuple[str, bool, list[str]]:
    """Map known hidden IDs to display identity. Unknown leaks stay and are audited."""
    leaks = scan_reader_technical_id_leaks(sentence)
    if not leaks:
        return sentence, False, []
    lookup = {}
    for card in packet.get("reader_cards") or []:
        if not isinstance(card, Mapping):
            continue
        identity = _as_mapping(card.get("feature_identity"))
        display = _card_display_identity(card)
        for key in (
            identity.get("reader_feature_id"),
            identity.get("feature_id"),
            identity.get("legacy_reader_feature_id"),
        ):
            if key and display:
                lookup[str(key).upper()] = display
    repaired = sentence
    unknown: list[str] = []
    for leak in leaks:
        display = lookup.get(leak.upper())
        if display:
            repaired = re.sub(re.escape(leak), display, repaired, flags=re.IGNORECASE)
        else:
            unknown.append(leak.upper())
    return repaired, repaired != sentence, unknown


def audit_named_feature_ceiling(text: str, cards: Iterable[Mapping[str, Any]] | None = None, *, limit: int = 3) -> list[dict]:
    displays = []
    for card in cards or []:
        if not isinstance(card, Mapping):
            continue
        if card.get("category") not in {"measured_feature_observation", "quantitation_comparison", "candidate_discovery"}:
            continue
        label = _card_display_identity(card)
        if label:
            displays.append(label)
    violations = []
    for index, paragraph in enumerate(_split_paragraphs(text), 1):
        named = [label for label in dict.fromkeys(displays) if label.lower() in paragraph.lower()]
        leaks = scan_reader_technical_id_leaks(paragraph)
        if len(named) > limit or leaks:
            violations.append({
                "paragraph_index": index,
                "named_feature_count": len(named),
                "named_features": named,
                "technical_id_leaks": leaks,
                "limit": limit,
            })
    return violations


def required_section_roles(section_type: str) -> tuple[str, ...]:
    return tuple(_as_mapping(SECTION_STORY_CONTRACT.get(section_type)).get("paragraph_roles") or ())


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
                source_sentence = sentence
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
                quantitative_reasons = validate_quantitative_sentence(sentence, packet)
                if quantitative_reasons:
                    sentence = ""
                    actions.append("withhold_unbound_quantitative_sentence")
                    reasons.extend(quantitative_reasons)
                bound_kinase_interval = bool(
                    sentence
                    and re.search(r"direction concordance fraction", sentence, re.I)
                    and not quantitative_reasons
                )
                evidence_scope = sentence_evidence_scope(sentence)
                protected_context = (
                    is_negated_boundary(sentence)
                    or evidence_scope in {"literature_context", "hypothesis"}
                    or bound_kinase_interval
                )
                direct_claim = bool(_DIRECT_OR_CAUSAL_RE.search(sentence))
                if direct_claim and "D1" not in allowed_tiers and not protected_context:
                    immutable = re.search(r"PF-[A-Z0-9]+|\d|\[REF:", _EVIDENCE_MARKER_RE.sub("", sentence), re.I)
                    sentence = "" if immutable else "The supplied evidence supports descriptive observations and candidate context; it does not establish direct regulation."
                    actions.append("rewrite_claim_to_candidate_context")
                    reasons.append("directness_or_causality_claim_exceeds_budget")
                if _DENOVO_AXIS_RE.search(sentence):
                    sentence = (
                        "Control-undetected features were retained as detection/LOD context and were not used on conventional "
                        "quantitative axes or magnitude rankings."
                    )
                    actions.append("rewrite_de_novo_axis_claim")
                    reasons.append("de_novo_conventional_axis_or_ranking")
                if _OCCUPANCY_RE.search(sentence) and not protected_context:
                    sentence = ""
                    actions.append("rewrite_quantitation_interpretation")
                    reasons.append("uncalibrated_occupancy_or_stoichiometry")
                repaired_metadata, metadata_repaired = ((sentence, False) if protected_context else repair_unrecorded_metadata_claim(sentence, metadata_contract))
                if metadata_repaired:
                    sentence = repaired_metadata
                    actions.append("remove_unrecorded_metadata_inference")
                    reasons.append("study_metadata_lineage_or_species_not_recorded")
                repaired_measurement, measurement_repaired = ((sentence, False) if protected_context else
                    _repair_candidate_residue_site_claim(sentence, candidate_residue_labels))
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
                    sentence = ""
                    actions.append("withhold_uncited_literature_sentence")
                    reasons.append("literature_context_without_stable_citation")
                # Recheck after local repair; no postprocessor may move a valid
                # number onto another feature, timepoint or axis.
                repaired_quantitative_reasons = validate_quantitative_sentence(sentence, packet)
                if repaired_quantitative_reasons:
                    sentence = ""
                    actions.append("withhold_unbound_repaired_sentence")
                    reasons.extend(repaired_quantitative_reasons)
                if _ANY_EVIDENCE_RESIDUE_RE.search(sentence):
                    sentence = _ANY_EVIDENCE_RESIDUE_RE.sub("", sentence)
                    actions.append("remove_malformed_evidence_anchor")
                    reasons.append("malformed_draft_only_anchor")
                if sentence:
                    repaired_ids, ids_replaced, unknown_ids = _replace_known_technical_ids(sentence, packet)
                    if ids_replaced:
                        sentence = repaired_ids
                        actions.append("replace_technical_id_with_display_identity")
                    if unknown_ids:
                        reasons.append("reader_technical_identifier_leak")
                sentence = normalize_reader_prose(sentence)
                if sentence:
                    retained_sentences.append(sentence)
                audit_entries.append({
                    "section": section_name,
                    "paragraph_index": paragraph_index,
                    "sentence_index": sentence_index,
                    "source_sentence": source_sentence,
                    "validated_sentence": sentence,
                    "evidence_ids": evidence_ids,
                    "citation_ids": citations,
                    "claim_tier_budget": sorted(allowed_tiers),
                    "evidence_scope": evidence_scope,
                    "validator_action": actions or ["retain"],
                    "reason_code": reasons or ["within_contract"],
                    "retained": bool(sentence),
                })
            if retained_sentences:
                repaired_paragraphs.append(" ".join(retained_sentences))
        section_text = "\n\n".join(repaired_paragraphs)
        if section_name == "methods":
            section_text = ensure_quantitation_methods_contract(section_text)
        if section_name in {"results", "discussion"}:
            section_text, _ = restore_kinase_interval_sentences(section_name, section_text, packet)
        validated[section_name] = section_text
    audit = {
        "contract_version": "reader_authoring_validator.v2",
        "packet_version": packet.get("contract_version"),
        "entries": audit_entries,
        "removed_sentence_count": sum(1 for entry in audit_entries if not entry["retained"]),
        "repaired_sentence_count": sum(1 for entry in audit_entries if entry["validator_action"] != ["retain"] and entry["retained"]),
        "finding_coverage": audit_finding_coverage(validated, packet),
    }
    return validated, audit


def audit_finding_coverage(sections, packet, plan=None):
    """Check that repair/assembly has not erased the selected observations."""
    plan = plan or deterministic_authoring_plan(packet)
    findings = [f for f in plan.get("key_findings") or [] if f.get("reader_feature_id")]
    sentences = _split_sentences(str(sections.get("results") or ""))
    missing, unlinked, duplicates, discussion_missing = [], [], [], []
    links = []
    for finding in findings:
        fid = finding["reader_feature_id"]
        display = str(finding.get("reader_display_identity") or "").strip()
        evidence = set(finding.get("evidence_ids") or [])
        matched = [s for s in sentences if (fid in s or (display and display.lower() in s.lower()) or evidence.intersection(_EVIDENCE_MARKER_RE.findall(s)))
                   and not validate_quantitative_sentence(s, packet)
                   and re.search(r"\b(?:contrast|PTM|protein)\b.*?[+−-]?\d+\.\d+", s, re.I)]
        if "results" in sections and not matched:
            missing.append(finding["finding_id"])
        if "results" in sections and not finding.get("figure_keys"):
            unlinked.append(finding["finding_id"])
        if len(matched) != len(set(matched)):
            duplicates.append(finding["finding_id"])
        if "discussion" in sections:
            paragraphs = re.split(r"\n\s*\n", str(sections.get("discussion") or ""))
            substantive = [p for p in paragraphs if (fid in p or (display and display.lower() in p.lower()) or evidence.intersection(_EVIDENCE_MARKER_RE.findall(p)))
                           and len(p.split()) >= 25 and re.search(r"contrast|response|abundance|precursor", p, re.I)
                           and re.search(r"explain|interpret|contribut|compare|comparison|test|validat|denominator|reference level|observed", p, re.I)]
            if not substantive:
                discussion_missing.append(finding["finding_id"])
        links.append({"finding_id": finding["finding_id"], "reader_feature_id": fid,
                      "evidence_ids": sorted(evidence), "figure_keys": finding.get("figure_keys") or [],
                      "results_sentences": list(dict.fromkeys(matched))})
    return {"contract_version": "finding_coverage_audit.v1", "status": "review_required" if missing or unlinked or duplicates or discussion_missing else "covered",
            "missing_finding_ids": missing, "figure_unlinked_finding_ids": unlinked,
            "discussion_missing_finding_ids": discussion_missing,
            "duplicate_finding_ids": duplicates, "sentence_evidence_links": links,
            "scope": "selected_descriptive_findings_not_a_scientific_validity_proof"}


def strip_authoring_anchors(text: str) -> str:
    """Remove draft-only evidence anchors after validation, preserving citations."""
    text = _EVIDENCE_MARKER_RE.sub("", text or "")
    text = _ANY_EVIDENCE_RESIDUE_RE.sub("", text)
    return normalize_reader_prose(text)


def _kinase_interval_sentence(card: Mapping[str, Any]) -> str:
    """Keep family names and computed interval numbers in one bindable sentence."""
    records = [
        record for record in card.get("value_records") or []
        if record.get("record_type") == "kinase_trajectory" and record.get("value") is not None
    ]
    if not records:
        return _clean_text(card.get("reader_summary"))
    entity = str(records[0].get("entity_id") or "candidate")
    by_metric = {str(record.get("metric_id")): record for record in records}
    concordance = by_metric.get("direction_concordance_fraction")
    correlation = by_metric.get("signed_profile_correlation")
    n_targets = by_metric.get("n_targets_evaluable")
    if concordance is None:
        return _clean_text(card.get("reader_summary"))
    family = entity if "family" in entity.lower() else f"{entity} family"
    parts = [f"{family} had direction concordance fraction {float(concordance['value']):.2f}"]
    if correlation is not None:
        parts.append(f"and signed profile correlation {float(correlation['value']):.2f}")
    if n_targets is not None:
        parts.append(f"across {int(n_targets['value'])} evaluable substrate targets")
    return " ".join(parts) + ". This signed interval comparison is not a catalytic rate."


def _text_has_bound_kinase_intervals(text: str, card: Mapping[str, Any]) -> bool:
    lowered = str(text or "").lower()
    for record in card.get("value_records") or []:
        if record.get("record_type") != "kinase_trajectory" or record.get("value") is None:
            continue
        if str(record.get("metric_id")) == "n_targets_evaluable":
            continue
        printed = f"{float(record['value']):.2f}"
        entity = str(record.get("entity_id") or "").lower()
        if printed not in lowered or (entity and entity.split("/")[0].strip() not in lowered):
            return False
    return any(
        record.get("record_type") == "kinase_trajectory" and record.get("metric_id") == "direction_concordance_fraction"
        for record in card.get("value_records") or []
    )


def restore_kinase_interval_sentences(section: str, text: str, packet: Mapping[str, Any]) -> tuple[str, list[dict]]:
    """Reattach computed interval numbers if the writer dropped them after the family name."""
    if section not in {"results", "discussion"}:
        return text, []
    additions = []
    for card in _supporting_context_cards(packet.get("reader_cards") or []):
        if not _kinase_interval_sentence(card):
            continue
        if _text_has_bound_kinase_intervals(text, card):
            continue
        sentence = _kinase_interval_sentence(card)
        if not sentence or sentence in (text or ""):
            continue
        additions.append(sentence)
    if not additions:
        return text, []
    return (text or "") + ("\n\n" if text else "") + "\n\n".join(additions), [{
        "status": "kinase_interval_numbers_restored",
        "added_text": "\n\n".join(additions),
    }]


def restore_missing_finding_paragraphs(section, text, packet, plan=None):
    """Supplement only missing roles after validation; retain original prose."""
    if section not in {"results", "discussion"}:
        return text, []
    text, kinase_audit = restore_kinase_interval_sentences(section, text, packet)
    plan = plan or deterministic_authoring_plan(packet)
    coverage = audit_finding_coverage({section: text}, packet, plan)
    missing = set(coverage["missing_finding_ids"] + coverage["discussion_missing_finding_ids"])
    if not missing:
        return text, kinase_audit
    missing_findings = [finding for finding in plan["key_findings"] if finding["finding_id"] in missing]
    selected_cards, _ = select_finding_cards(packet.get("reader_cards") or [])
    cards_by_id = {
        str(_as_mapping(card.get("feature_identity")).get("reader_feature_id") or ""): card
        for card in selected_cards
    }
    recovered = []
    for finding in missing_findings:
        card = cards_by_id.get(str(finding.get("reader_feature_id") or ""))
        if not card:
            continue
        if section == "results":
            recovered.append(_named_finding_clause(card, finding))
        else:
            recovered.append(
                f"{_card_display_identity(card)} {_joint_description(card)} "
                "This observation remains subject to protein-denominator, mapping, and sampling alternatives and requires matched validation."
            )
    candidate = "\n\n".join(recovered)
    validated, audit = validate_and_repair_sections({section: candidate}, packet)
    addition = validated.get(section, "")
    if not addition:
        return text, kinase_audit + [{"missing_finding_ids": sorted(missing), "status": "recovery_failed", "validator": audit}]
    return text + ("\n\n" if text else "") + addition, kinase_audit + [{"missing_finding_ids": sorted(missing), "status": "deterministic_observation_recovered_review_required", "added_text": addition, "validator": audit}]


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
    authoring_plan: Mapping[str, Any] | None = None,
    generation_failures: Iterable[str] | None = None,
    generation_degraded: bool = False,
    report_audience: str | None = None,
    required_module_status: Mapping[str, str] | None = None,
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
    incomplete_modules = sorted(name for name, status in (required_module_status or {}).items()
                                if status not in {"computed", "not_requested"})
    if incomplete_modules:
        review_reason_codes.append("required_module_analysis_incomplete")
    if metadata_review_reasons:
        review_reason_codes.append("study_metadata_review_required")
    quantitative_packet = {"reader_cards": list(reader_cards or []), "figure_cards": manifest.get("figures") or []}
    quantitative_violations = []
    from .scientific_semantics import prose_without_reference_section
    for line in prose_without_reference_section(body).splitlines():
        if line.lstrip().startswith(("#", "|", "![")):
            continue
        for sentence in _split_sentences(line):
            issues = validate_quantitative_sentence(sentence, quantitative_packet)
            if issues:
                quantitative_violations.append({"sentence": sentence, "reason_codes": issues})
    if quantitative_violations:
        reason_codes.append("unbound_quantitative_claim")
    semantic_audit = audit_semantic_claims(body, reader_cards or [])
    language_audit = audit_language_quality(body)
    if semantic_audit.get("violation_count"):
        reason_codes.append("unrepaired_scientific_semantic_claim")
    if language_audit.get("duplicate_quantitation_phrase_count"):
        reason_codes.append("duplicate_quantitation_phrase")
    if language_audit.get("fragment_count"):
        review_reason_codes.append("sentence_fragment_review_required")
    if language_audit.get("lowercase_sentence_start_count"):
        review_reason_codes.append("lowercase_sentence_start_review_required")
    if language_audit.get("doubled_punctuation_count"):
        review_reason_codes.append("punctuation_damage_review_required")
    if language_audit.get("section_word_budget_violation_count"):
        review_reason_codes.append("section_word_budget_review_required")
    finding_coverage = None
    if authoring_plan:
        sections = {}
        headings = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", body))
        for i, heading in enumerate(headings):
            section = _MAJOR_HEADING_ALIASES.get(heading[1].strip().lower())
            if section:
                section_body = body[heading.end():headings[i + 1].start() if i + 1 < len(headings) else len(body)]
                # Figure captions/tables cannot stand in for a Results finding.
                sections[section] = re.split(r"(?m)^###\s+(?:Supplementary\s+)?Figure\b", section_body)[0]
        sections.setdefault("results", "")
        finding_coverage = audit_finding_coverage(sections, quantitative_packet, authoring_plan)
        if finding_coverage["status"] != "covered":
            review_reason_codes.append("finding_coverage_review_required")
    from common.section_budgets import section_content_issues
    section_quality = {}
    content_sections = {}
    for match in re.finditer(r"(?ms)^##\s+(Abstract|Introduction|Methods|Results|Discussion|Conclusion)\s*\n(.*?)(?=^##\s|\Z)", body):
        name = match[1].lower()
        prose = re.split(r"(?m)^###\s+(?:Supplementary\s+)?Figure\b", match[2])[0]
        content_sections[name] = prose
        section_quality[name] = section_content_issues(prose, name)
    for name in ("abstract", "introduction", "methods", "results", "discussion", "conclusion"):
        section_quality.setdefault(name, ["empty_section"])
    _length_only = {"below_section_target", "language_specific_budget_not_configured"}
    if any(issue not in _length_only for issues in section_quality.values() for issue in issues):
        review_reason_codes.append("section_content_quality_incomplete")
    question_coverage = audit_question_coverage(content_sections, _as_mapping(authoring_plan).get("research_question_evidence_map"))
    if question_coverage["status"] != "covered":
        review_reason_codes.append("research_question_coverage_incomplete")
    if "research_question_answers" in major_sequence:
        review_reason_codes.append("independent_question_answer_section_not_allowed")
    registered_references = {cid.lower() for c in reader_cards or [] for cid in c.get("citation_ids") or []}
    narrative = "\n".join(content_sections.values())
    cited_markers = {cid.lower() for cid in re.findall(r'\[REF:([^\]]+)\]', narrative)}
    bibliography = re.split(r'(?im)^##\s+References\s*$', body, maxsplit=1)
    registered_numbers = set(re.findall(r'(?m)^(\d+)\.\s', bibliography[1])) if len(bibliography) == 2 else set()
    cited_numbers = {n for group in re.findall(r'\[(\d+(?:\s*,\s*\d+)*)\]', narrative) for n in re.findall(r'\d+', group)}
    literature_count = max(len(cited_markers & registered_references), len(cited_numbers & registered_numbers))
    # Citation counts describe use, not claim fidelity or scientific quality.
    # Claim/source binding and requested question coverage are separate gates.
    unreferenced = [f.get("display_label") for f in manifest.get("figures") or [] if f.get("placement") == "main"
                   and f.get("display_label") and f["display_label"] not in narrative]
    if unreferenced:
        review_reason_codes.append("main_figure_not_referenced_in_prose")
    if generation_failures:
        review_reason_codes.append("interpretation_generation_incomplete")
    if generation_degraded:
        review_reason_codes.append("generation_degraded")
    technical_leaks = scan_reader_technical_id_leaks(narrative)
    named_feature_violations = []
    for name in ("results", "discussion"):
        named_feature_violations.extend(
            {"section": name, **item}
            for item in audit_named_feature_ceiling(content_sections.get(name, ""), reader_cards)
        )
    if technical_leaks:
        reason_codes.append("reader_technical_identifier_leak")
    audience = report_audience or ("researcher_manuscript" if figure_manifest is not None else "technical_audit")
    technical_leakage = audit_reader_technical_leakage(body, audience=audience)
    reason_codes.extend(technical_leakage.get("reason_codes") or [])
    if named_feature_violations:
        review_reason_codes.append("named_feature_ceiling_exceeded")
    reason_codes = sorted(set(reason_codes))
    review_reason_codes = sorted(set(review_reason_codes))
    status = "blocked_for_review" if reason_codes else "draft_review_required" if review_reason_codes else "release_candidate"
    return {
        "contract_version": "reader_report_output_correctness.v2",
        "status": status,
        "reason_codes": reason_codes,
        "review_reason_codes": review_reason_codes,
        "generation_degraded": bool(generation_degraded),
        "reader_technical_identifier_leaks": technical_leaks,
        "technical_leakage_audit": technical_leakage,
        "named_feature_ceiling_violations": named_feature_violations,
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
        "quantitative_claim_violations": quantitative_violations,
        "semantic_claim_audit": semantic_audit,
        "language_quality_audit": language_audit,
        "finding_coverage": finding_coverage,
        "generation_fallback_sections": list(generation_failures or []),
        "section_content_quality": section_quality,
        "research_question_coverage": question_coverage,
        "required_module_status": dict(required_module_status or {}),
        "incomplete_required_modules": incomplete_modules,
        "scope_policy_version": "question_and_claim_coverage.v2",
        "literature_coverage": {"distinct_references": len(registered_references), "cited_reference_count": literature_count,
                                "target_range": None, "count_is_quality_gate": False, "padding_allowed": False,
                                "evidence_types": sorted({comparison.get("relationship") for c in reader_cards or []
                                    for comparison in _as_mapping(c.get("literature_comparison")).get("comparisons") or [] if comparison.get("relationship")})},
        "main_figures_unreferenced_in_prose": unreferenced,
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


def _joint_description(card):
    patterns = {p.get("joint_pattern") for p in card.get("trajectory") or [] if not p.get("detection_context_only")}
    descriptions = {
        "ptm_maintained_protein_decreased_adjusted_increased": "The independent PTM contrast remained near the reference level while the protein-adjusted relative PTM contrast was higher. The denominator check is therefore relevant before interpreting this as a precursor-specific response.",
        "ptm_protein_co_movement": "Independent and protein-adjusted relative PTM contrasts differed after denominator adjustment. This comparison is retained as a quantitation-validity check rather than a separate protein-response finding.",
        "ptm_increased_with_stable_protein": "Both independent and protein-adjusted relative PTM contrasts were higher in the available observations.",
        "near_reference_all_axes": "The independent and protein-adjusted relative PTM contrasts remained near their reference levels within the descriptive tolerance.",
        "incomplete_axes_observation": "Available PTM observations were retained, with unavailable axes excluded from joint interpretation.",
    }
    exact = descriptions.get(next(iter(patterns)) if len(patterns) == 1 else "")
    if exact:
        return exact
    points = card.get("trajectory") or []
    paired = [(p.get("ptm_unadjusted_log2fc"), p.get("protein_log2fc"), p.get("ptm_protein_adjusted_log2fc")) for p in points]
    paired = [(u, p, a) for u, p, a in paired if all(v is not None for v in (u, p, a))]
    if paired and all(u * p > 0 and abs(a) < abs(u) for u, p, a in paired):
        return "The independent and protein-adjusted relative PTM contrasts differed in magnitude. This supports checking denominator contribution before interpreting a PTM-specific response."
    if paired and all(abs(p) < .15 and abs(a) >= .15 for u, p, a in paired):
        return "The protein-adjusted relative PTM response remained after denominator adjustment. The available observations are retained as a PTM response, subject to denominator and sampling checks."
    values = [a for u, p, a in paired]
    if values and min(values) < 0 < max(values):
        return "The protein-adjusted relative PTM contrast changed direction within the sampled window. The reversal motivates comparison of early and late precursor responses while retaining denominator checks."
    return "Independent and protein-adjusted relative PTM contrasts varied across the sampled observations. Their differences identify where denominator quality should be checked before a precursor-specific interpretation."


def finding_observation_conditions(card):
    """First observed response, sampled extremum and last point, never a fitted peak."""
    points = [p for p in card.get("trajectory") or [] if not p.get("detection_context_only")]
    available = [p for p in points if any(p.get(k) is not None for k in ("ptm_unadjusted_log2fc", "ptm_protein_adjusted_log2fc"))]
    if not available:
        return []
    def magnitude(p):
        v = p.get("ptm_protein_adjusted_log2fc")
        return abs(v if v is not None else p.get("ptm_unadjusted_log2fc") or 0)
    first = next((p for p in available if magnitude(p) >= .15), available[0])
    peak = max(available, key=magnitude)
    return list(dict.fromkeys(p["condition"] for p in (first, peak, available[-1])))


def _sampled_trajectory_interpretation(card):
    """Describe sampled extrema and the last observation without fitting a peak."""
    pairs = [(p.get("condition"), p.get("ptm_protein_adjusted_log2fc")) for p in card.get("trajectory") or []
             if not p.get("detection_context_only") and p.get("ptm_protein_adjusted_log2fc") is not None]
    if not pairs:
        return "Protein-adjusted contrasts were unavailable; the independent precursor observations retain their own interpretation."
    levels = [v for _, v in pairs]
    if max(levels) - min(levels) <= 1e-12:
        return "The adjusted level was unchanged between the available observations; missing intervals remain unresolved."
    sign = "positive" if abs(max(levels)) >= abs(min(levels)) else "negative"
    extreme = max(levels) if sign == "positive" else min(levels)
    times = [str(c) for c, v in pairs if v == extreme]
    extrema = f"The largest sampled {sign} adjusted contrast occurred at {', '.join(times)}."
    if len(times) > 1:
        extrema = f"The sampled {sign} extremum was tied across {', '.join(times)}."
    last_time, last_value = pairs[-1]
    if last_time in times:
        return extrema + " Because the last observation is an extremum, the subsequent response remains unobserved."
    change = "changed direction" if last_value * extreme < 0 else "was smaller in magnitude" if abs(last_value) < abs(extreme) else "remained comparable in magnitude"
    return extrema + f" The last recorded contrast at {last_time} {change}; this comparison does not locate a continuous-time biological peak."


def _named_finding_clause(card, finding=None, *, maximum_conditions=3):
    records = [
        record for record in quantitative_records(card)
        if record.get("value") is not None and record.get("axis") in {"unadjusted", "adjusted"}
    ]
    conditions = finding_observation_conditions(card)[:maximum_conditions]
    compact: list[str] = []
    for condition in conditions:
        values = [
            f"{AXIS_LABELS.get(r['axis'], r['axis'])} {r['value']:+.3f}"
            for r in records
            if r.get("condition") == condition and r.get("value") is not None
        ]
        if values:
            compact.append(f"{condition}: " + ", ".join(values))
    description = _joint_description(card).rstrip(". ")
    label = _card_display_identity(card)
    clause = f"{label} {description[0].lower() + description[1:]}"
    if compact:
        # Sentence splitting treats the explanatory clause as complete. Repeat
        # the reader-safe (never PF/FEATURE) display identity once at the start
        # of the numeric clause so every value remains locally auditable.
        clause += f" {label} recorded contrasts were " + "; ".join(compact) + "."
    return clause


def _evidence_bound_bridge(kind: str) -> str:
    return {
        "quantitation": (
            "These selected measurements are next compared with the independently calculated "
            "unadjusted and protein-adjusted relative PTM contrasts, with linked protein retained as denominator context."
        ),
        "time": (
            "The same sampled intervals also support a descriptive temporal-profile and "
            "interval-concordance description."
        ),
        "scope": (
            "Candidate-family context is retained only as observational context and does not "
            "establish a direct kinase–substrate assignment."
        ),
        "literature": (
            "The selected source-anchored comparisons remain limited to their recorded experimental scope."
        ),
    }.get(kind, "")


def restore_narrative_bridges(section: str, text: str, packet: Mapping[str, Any]) -> tuple[str, list[dict]]:
    """Restore only a missing manuscript bridge, never a section-level fallback.

    This repair is deliberately qualitative and evidence-bounded.  It prevents a
    locally withheld numeric or directness clause from leaving a Results or
    Discussion paragraph as an abrupt list, without reintroducing technical
    diagnostics or fabricating a biological mechanism.
    """
    if section not in {"results", "discussion"} or not str(text or "").strip():
        return text, []
    lowered = str(text).lower()
    additions: list[dict] = []
    if section == "results":
        if not re.search(r"\b(?:temporal profile|interval-wise concordance|sampled interval)\b", lowered):
            additions.append({"role": "temporal_profile_and_interval_concordance", "text": _evidence_bound_bridge("time")})
        supporting = _supporting_context_cards(packet.get("reader_cards") or [])
        if supporting and not re.search(r"\b(?:candidate[- ]family|candidate context|substrate-anchor)\b", lowered):
            additions.append({"role": "candidate_family_context", "text": _evidence_bound_bridge("scope")})
    else:
        if not re.search(r"\b(?:alternative|denominator|mapping|sampling)\b", lowered):
            additions.append({
                "role": "competing_explanation_and_current_limitation",
                "text": "Denominator quality, mapping, and sampling remain alternative explanations for the observed relative PTM contrast."
            })
        if not re.search(r"\b(?:next experiment|next validation|discriminating|matched validation)\b", lowered):
            additions.append({
                "role": "discriminating_next_experiment",
                "text": "A matched measurement of the same modified precursor in independent samples is the next discriminating validation."
            })
    valid = [item for item in additions if str(item.get("text") or "").strip()]
    if not valid:
        return text, []
    suffix = "\n\n".join(str(item["text"]).strip() for item in valid)
    return str(text).rstrip() + "\n\n" + suffix, [{"status": "bridge_micro_recovery", **item} for item in valid]


def _literature_status_card(packet) -> str:
    statuses = []
    pending = 0
    failed = 0
    not_searched = 0
    anchored = 0
    for card in packet.get("reader_cards") or []:
        context = _as_mapping(card.get("literature_comparison"))
        status = str(context.get("status") or "")
        if not status:
            continue
        statuses.append(status)
        if status == "retrieved_comparison_pending":
            pending += 1
        elif status == "retrieval_failed":
            failed += 1
        elif status in {"not_searched", "retrieval_unavailable"}:
            not_searched += 1
        if context.get("comparisons"):
            anchored += 1
    if not statuses:
        return "A compact literature-status summary was not available for the selected findings."
    if anchored:
        return f"Source-anchored comparisons were available for {anchored} selected finding(s)."
    if failed:
        return "Finding-scoped literature search failed for the selected observations; this search failure does not erase the measured observations."
    if pending:
        return (
            "Retrieved literature comparison remains incomplete for the selected findings; "
            "this status does not erase the measured observations."
        )
    if not_searched:
        return "Finding-scoped literature comparison was not performed for the selected observations; this does not erase the measured observations."
    return "Traceable feature-specific literature comparison remained incomplete for the selected findings."


def _render_role_based_results(packet, study, cards, plan, figures):
    landscape = _default_summary(
        _summaries_by_category(packet, "quantitative_landscape", "quantitation_provenance", "study_frame", limit=2),
        study,
    )
    named = cards[:3]
    observation = " ".join(_named_finding_clause(card, finding) for card, finding in zip(named, plan.get("key_findings") or []))
    if not observation.strip():
        observation = "Selected current-order feature observations were not available for narrative display."
    figure_bits = []
    for finding in (plan.get("key_findings") or [])[:3]:
        for key in finding.get("figure_keys") or []:
            figure = figures.get(key) or {}
            label = figure.get("figure_label")
            if label and label not in figure_bits:
                figure_bits.append(label)
    if figure_bits:
        observation += " " + "; ".join(figure_bits) + " display the corresponding measured evidence."
    comparison_cards = [c for c in packet.get("reader_cards") or [] if c.get("category") == "quantitation_comparison"][:2]
    if comparison_cards:
        quantitation_context = (
            "Linked total-protein measurements were used as the denominator for protein-adjusted relative PTM contrasts "
            "and as a quantitation-validity check for the selected modified precursors. Their condition-level changes are "
            "not interpreted here as an independent biological response storyline. The descriptive comparison classes show "
            "how denominator adjustment changed the reported PTM contrast; they do not prove that either contrast is biologically truer."
        )
    else:
        quantitation_context = (
            "An independent unadjusted-versus-protein-adjusted comparison was not available "
            "for the selected findings; denominator validity remains unresolved rather than becoming a separate protein-response finding."
        )
    temporal = _default_summary(
        _summaries_by_category(packet, "temporal_profile", limit=2),
        "Temporal Profile Clustering and Interval-wise Concordance Analysis remain descriptive summaries of the sampled intervals.",
    )
    supporting = _supporting_context_cards(packet.get("reader_cards") or [])
    kinase = " ".join(
        (_kinase_interval_sentence(card) or str(card.get("reader_summary") or ""))
        for card in supporting[:2]
    )
    if not kinase.strip():
        kinase = _default_summary(
            _summaries_by_category(packet, "kinase_context", "candidate_discovery", limit=2),
            "No eligible candidate-family context was available beyond the measured feature observations.",
        )
    return "\n\n".join([
        landscape,
        _evidence_bound_bridge("quantitation"),
        observation,
        quantitation_context,
        _evidence_bound_bridge("time"),
        temporal,
        _evidence_bound_bridge("scope"),
        "Supplementary Figure 2 reports within-cluster pair-window counts. "
        "The kinase signed-interval fractions are a separate substrate-anchor comparison. "
        + kinase,
    ])


def _render_role_based_discussion(packet, cards, plan):
    # A reader paragraph can carry at most three selected observations.  This
    # keeps the discussion concise while preserving the full default finding
    # set used by Results and the public coverage audit.
    named = cards[:3]
    observation = " ".join(
        f"{_card_display_identity(card)} {_joint_description(card)}"
        for card in named
    ) or "Selected current-order observations remain the interpretation anchor."
    literature_bits = []
    for card, finding in zip(named, (plan.get("key_findings") or [])):
        context = _as_mapping(finding.get("literature_comparison")) or _as_mapping(card.get("literature_comparison"))
        for comparison in (context.get("comparisons") or [])[:2]:
            if comparison.get("claim_support_status") != "verified":
                quote = str(comparison.get("quote") or "").strip()
                if quote:
                    differences = "; ".join(comparison.get("condition_differences") or []) or "experimental comparability is unestablished"
                    literature_bits.append(
                        f'The retrieved source reports: “{quote}” [REF:{comparison.get("citation_id")}]. '
                        f'Its support for this observation requires review; {differences}.')
                continue
            relation = "agreed with" if comparison.get("relationship") == "known_agreement" else "differed from" if comparison.get("relationship") == "disagreement" else "provided biological context for"
            differences = "; ".join(comparison.get("condition_differences") or []) or "experimental comparability has not been established"
            external = str(comparison.get("external_finding") or "").rstrip(". ")
            literature_bits.append(
                f"The {comparison.get('reference_scope', 'supplied')}-level literature comparison {relation} "
                f"the recorded observation: {external} "
                f"[REF:{comparison.get('citation_id')}]. Conditions differ in {differences}."
            )
    if not literature_bits:
        literature_bits.append(_literature_status_card(packet))
    opposing = []
    for finding in plan.get("key_findings") or []:
        opposing.extend(finding.get("opposing_feature_ids") or [])
    if opposing:
        alternative = (
            "Shared parent abundance, mapping ambiguity, and distinct precursor forms remain competing explanations. "
            "A targeted comparison of the exact recorded forms, with localization and denominator quality checked, "
            "would test whether the divergence persists."
        )
    else:
        alternative = (
            "A change in the available protein denominator and differences in sample support can contribute to the adjusted contrast. "
            "These alternatives remain open because the current measurements do not separate occupancy, mapping error, and regulation."
        )
    next_experiment = (
        "The discriminating next experiment should quantify the same precursor and linked protein in matched independent "
        "biological samples, with the mapping and denominator quality recorded in advance."
    )
    unresolved = unresolved_question_paragraphs(packet.get("research_question_evidence_map"))
    paragraphs = [
        observation + " " + " ".join(literature_bits),
        _evidence_bound_bridge("literature"),
        alternative,
        next_experiment,
    ]
    paragraphs.extend(unresolved)
    supporting = _supporting_context_cards(packet.get("reader_cards") or [])
    if supporting:
        paragraphs.insert(
            1,
            (_kinase_interval_sentence(supporting[0]) or supporting[0]["reader_summary"])
            + " This remains observational candidate context.",
        )
    return "\n\n".join(paragraphs)


def _render_finding_section(section_type, packet, study):
    plan = deterministic_authoring_plan(packet)
    cards, _ = select_finding_cards(packet.get("reader_cards") or [])
    if not cards or section_type not in {"results", "discussion", "conclusion", "abstract", "introduction"}:
        return None
    if section_type == "introduction":
        return (study + "\n\nRepeated measurements of modified precursors and linked proteins allow the relative response of each layer to be compared over time. "
                "The study question is whether changes in measured PTM abundance accompany protein abundance, persist after protein adjustment, or differ among forms linked to the same parent. "
                "The interpretation is limited to the sampled conditions and to the mapping and uncertainty recorded with each observation.\n\n" +
                (_literature_context_for_fallback(packet) or "A feature-specific comparison with prior work requires traceable literature matched to the experimental system and sampling window.") +
                " The current objective is to identify measured PTM–protein patterns and define the next observation that could distinguish their possible explanations.")
    figures = {f["figure_key"]: f for f in packet.get("figure_cards") or []}
    if section_type == "results":
        return _render_role_based_results(packet, study, cards, plan, figures)
    if section_type == "discussion":
        return _render_role_based_discussion(packet, cards, plan)
    paragraphs = []
    for card, finding in zip(cards[:3], plan["key_findings"][:3]):
        description = _joint_description(card)
        label = _card_display_identity(card)
        paragraphs.append(f"For {label}, {description[0].lower() + description[1:]}")
    supporting = _supporting_context_cards(packet.get("reader_cards") or [])
    if supporting and section_type == "abstract":
        paragraphs.append(_kinase_interval_sentence(supporting[0]) or supporting[0]["reader_summary"])
    if section_type == "conclusion":
        main = cards[0]
        description = _joint_description(main)
        label = _card_display_identity(main)
        return (f"The recorded time course distinguishes changes in modified precursor abundance from changes relative to linked protein. For {label}, {description[0].lower() + description[1:]} "
                "These sampled relative contrasts do not establish causality, absolute occupancy, or biological reproducibility. "
                "The next validation should repeat paired measurements of the same precursor and parent protein in independent biological samples, with denominator quality and mapping checked explicitly.")
    if section_type == "abstract":
        return study + " " + " ".join(paragraphs) + " These observations are descriptive; independent paired validation is needed to distinguish regulation from denominator and sampling effects."
    return "\n\n".join(paragraphs)


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
    finding_section = _render_finding_section(section_type, packet, study)
    if finding_section is not None:
        return finding_section
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
            "### Candidate context\n\nSupplementary Figure 2 reports within-cluster pair-window counts. "
            "The kinase signed-interval fractions are a separate substrate-anchor comparison. "
            + kinase + " " + candidates,
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
        axis_methods = sorted({str(r["support"].get("method")) for c in packet.get("reader_cards") or []
                               for r in quantitative_records(c) if r.get("support", {}).get("method")})
        methods = ("Recorded axis-specific calculation and test methods: " + "; ".join(axis_methods) + ".") if axis_methods else "Axis-specific test metadata were not available from the recorded input; p/q fields remain attached to their original axes and unavailable values remain unspecified."
        design = packet.get("study_design") or {}
        design_text = ("Biological units, technical injections, batches and pairing are taken only from the explicit sample manifest. Technical injections and precursor counts are not biological replication.") if design.get("samples") else "The report input did not include an explicit biological-unit and technical-injection manifest; this is a provenance limitation, not evidence that the experiment lacked biological replication."
        return "\n\n".join([
            study,
            quantitative,
            estimator_paragraph,
            methods + " " + design_text,
            ("Hierarchical Clustering of Temporal Phosphorylation Feature Profiles and Interval-wise Concordance Analysis are interpreted as recorded descriptive analyses. The latter uses evaluable within-cluster pair-window comparisons as the denominator." if any(c.get("category") == "temporal_profile" for c in packet.get("reader_cards") or []) else "No cluster or concordance result was supplied for this report input. When applied, Interval-wise Concordance Analysis uses evaluable within-cluster pair-window comparisons as the denominator."),
            "Feature selection considered recorded observation and point-statistical support before parent and joint-pattern diversity. Pattern labels use elapsed time and the configurable descriptive tolerance; they are not pattern-level hypothesis tests. Missing measurements are not zero. Shared parents, controls and differing axis sample sets are retained as dependencies; no common-sample sensitivity estimate or population confidence interval was computed by this reporting step.",
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
    from .figure_manifest import render_verified_reader_figures
    return "\n\n".join([
        f"# {title}",
        f"*Generated: {generated_at}*",
        "## Abstract\n\n" + render_reader_section_fallback("abstract", packet),
        "## Introduction\n\n" + render_reader_section_fallback("introduction", packet),
        "## Methods\n\n" + render_reader_section_fallback("methods", packet),
        "## Results\n\n" + render_reader_section_fallback("results", packet),
        render_verified_reader_figures(state.get("figure_manifest") or {}),
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
