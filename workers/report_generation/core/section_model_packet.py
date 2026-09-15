"""Section-scoped model packet distinct from the full authoring audit packet.

구현 대상: docs/개발_업무지시서_연구자용_PTM_Report의_Identity_Projection·서사·생성.md §4.B
사전등록: 2026-09-14 표시·생성 계약. 측정 공식 변경 아님.
해석 한계: 축약은 prompt 전달용이며 숨은 evidence를 삭제하지 않는다.
주장 금지: compaction 성공을 kinase 예측 개선으로 해석하지 않는다.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

from common.report_display_policy import PROMPT_CHAR_BUDGET, effective_display_policy
from report_generation.core.quantitative_claims import (
    narrative_authoring_instructions,
    quantitative_records,
    structured_authoring_instructions,
    value_token_catalog,
)
from report_generation.core.reader_authoring import (
    SECTION_STORY_CONTRACT,
    format_authoring_packet_for_llm,
)

SECTION_MODEL_PACKET_VERSION = "section_model_packet.v1"
MODEL_CARD_FIELDS = (
    "card_id",
    "category",
    "reader_summary",
    "claim_tier",
    "evidence_ids",
    "citation_ids",
    "allowed_verbs",
    "forbidden_interpretations",
    "counterevidence",
    "feature_label",
    "condition",
    "axis_patterns",
    "literature_comparison",
    "trajectory_shape_fact",
    "value_records",
)
HIDDEN_IDENTITY_FIELDS = (
    "feature_id",
    "reader_feature_id",
    "legacy_reader_feature_id",
    "technical_crosswalk_reference",
    "precursor_id",
    "source_feature_id",
    "modified_sequence",
    "precursor_charge",
    "protein_group",
    "fasta_taxonomy_id",
    "isoform",
)
AUDIT_ONLY_PACKET_KEYS = {
    "candidate_transfer_audit",
    "identity_audit",
    "exclusion_audit",
    "technical_crosswalk",
    "raw_status",
    "implementation_status",
}


def _as_mapping(value: Any) -> dict:
    return dict(value) if isinstance(value, Mapping) else {}


def _card_identity(card: Mapping[str, Any]) -> dict:
    identity = _as_mapping(card.get("feature_identity"))
    display = identity.get("reader_display_identity") or card.get("feature_label")
    disambiguator = identity.get("reader_disambiguator")
    if display and disambiguator and disambiguator not in str(display):
        display = f"{display} {disambiguator}"
    return {
        "reader_display_identity": display,
        "reader_disambiguator": disambiguator,
        "gene": identity.get("gene"),
        "candidate_residue_annotation": identity.get("candidate_residue_annotation"),
        "main_named_finding_eligible": identity.get("main_named_finding_eligible", True),
    }


def _public_records(card: Mapping[str, Any]) -> list[dict]:
    records = []
    for record in quantitative_records(card):
        item = {
            key: record.get(key)
            for key in (
                "evidence_id",
                "display_identity",
                "condition",
                "axis",
                "value",
                "record_type",
                "entity_id",
                "metric_id",
                "interval",
                "unit",
                "time_minutes",
            )
            if record.get(key) is not None or key in {"value", "axis", "condition", "display_identity"}
        }
        records.append(item)
    return records


def _compact_trajectory(card: Mapping[str, Any], *, stage: int) -> list[dict] | dict | None:
    points = [dict(point) for point in card.get("trajectory") or [] if isinstance(point, Mapping)]
    if stage < 3 or not points:
        return points or None
    numeric = []
    for point in points:
        value = point.get("ptm_protein_adjusted_log2fc")
        if value is None:
            value = point.get("ptm_relative_log2fc")
        if isinstance(value, (int, float)):
            numeric.append((abs(float(value)), point))
    selected = [points[0]]
    if numeric:
        peak = max(numeric, key=lambda item: item[0])[1]
        if peak not in selected:
            selected.append(peak)
    if points[-1] not in selected:
        selected.append(points[-1])
    missing = [
        str(point.get("condition") or "")
        for point in points
        if point.get("detection_context_only") or (
            point.get("ptm_protein_adjusted_log2fc") is None
            and point.get("ptm_unadjusted_log2fc") is None
        )
    ]
    shape = _as_mapping(card.get("trajectory_shape_fact")).get("reader_summary")
    return {
        "first": selected[0],
        "peak": selected[1] if len(selected) > 1 else selected[0],
        "last": selected[-1],
        "explicit_missing_gaps": [item for item in missing if item],
        "shape_summary": shape,
    }


def _limit_literature(card: Mapping[str, Any], *, stage: int) -> dict:
    context = _as_mapping(card.get("literature_comparison"))
    if stage < 4:
        return context
    comparisons = list(context.get("comparisons") or [])[:2]
    return {
        "status": context.get("status"),
        "comparisons": comparisons,
        "source_anchored_excerpt_limit": 2,
    }


def _assigned_ids(plan: Mapping[str, Any] | None, section_type: str) -> tuple[set[str], set[str], set[str]]:
    plan = _as_mapping(plan)
    section_findings = set(_as_mapping(plan.get("section_finding_map")).get(section_type) or [])
    feature_ids = {
        str(finding.get("reader_feature_id") or "")
        for finding in plan.get("key_findings") or []
        if not section_findings or finding.get("finding_id") in section_findings
    }
    evidence_ids = {
        str(evidence_id)
        for finding in plan.get("key_findings") or []
        if not section_findings or finding.get("finding_id") in section_findings
        for evidence_id in finding.get("evidence_ids") or []
    }
    figure_keys = {
        str(key)
        for finding in plan.get("key_findings") or []
        if not section_findings or finding.get("finding_id") in section_findings
        for key in finding.get("figure_keys") or []
    }
    return feature_ids - {""}, evidence_ids - {""}, figure_keys - {""}


def _card_is_assigned(card: Mapping[str, Any], feature_ids: set[str], evidence_ids: set[str], *, stage: int) -> bool:
    category = str(card.get("category") or "")
    if stage < 2:
        return True
    if category in {"study_frame", "quantitation_provenance", "quantitative_landscape", "traceable_literature"}:
        return True
    identity = _as_mapping(card.get("feature_identity"))
    if identity.get("reader_feature_id") in feature_ids:
        return True
    if evidence_ids.intersection(str(item) for item in card.get("evidence_ids") or []):
        return True
    if category in {"kinase_context", "temporal_profile"} and stage < 5:
        return True
    return False


def _group_family_cards(cards: list[dict], *, stage: int) -> list[dict]:
    if stage < 5:
        return cards
    grouped: list[dict] = []
    family_summaries: list[str] = []
    family_evidence: list[str] = []
    for card in cards:
        if card.get("category") != "kinase_context":
            grouped.append(card)
            continue
        family_summaries.append(str(card.get("reader_summary") or ""))
        family_evidence.extend(str(item) for item in card.get("evidence_ids") or [])
    if family_summaries:
        grouped.append({
            "card_id": "kinase.family_group",
            "category": "kinase_context",
            "reader_summary": "Equivalent family candidate context: " + " ".join(family_summaries[:3]),
            "claim_tier": "C1",
            "evidence_ids": family_evidence[:8] or ["kinase.family_group"],
            "citation_ids": [],
            "allowed_verbs": ["provided candidate context"],
            "forbidden_interpretations": ["direct kinase-substrate assignment", "catalytic activation"],
            "counterevidence": "Grouped family context remains observational candidate context.",
            "feature_identity": {"reader_display_identity": "candidate-family context"},
        })
    return grouped


def build_section_model_packet(
    audit_packet: Mapping[str, Any],
    plan: Mapping[str, Any] | None,
    section_type: str,
    *,
    compaction_stage: int = 0,
) -> dict:
    """Allowlist a section-scoped model packet. The audit packet remains unchanged."""
    audit = _as_mapping(audit_packet)
    feature_ids, evidence_ids, figure_keys = _assigned_ids(plan, section_type)
    contract = _as_mapping(SECTION_STORY_CONTRACT.get(section_type))
    omitted: list[dict] = []
    retained_cards: list[dict] = []
    for card in audit.get("reader_cards") or []:
        if not isinstance(card, Mapping):
            continue
        if compaction_stage >= 1 and not _card_is_assigned(card, feature_ids, evidence_ids, stage=compaction_stage):
            omitted.append({
                "evidence_ids": list(card.get("evidence_ids") or []),
                "reason": "unassigned_or_audit_only_card",
            })
            continue
        if contract.get("categories") and card.get("category") not in set(contract["categories"]) and card.get("category") not in {
            "study_frame",
            "quantitation_provenance",
            "quantitative_landscape",
        }:
            if compaction_stage >= 2:
                omitted.append({
                    "evidence_ids": list(card.get("evidence_ids") or []),
                    "reason": "unrelated_section_category",
                })
                continue
        public = {field: card.get(field) for field in MODEL_CARD_FIELDS if field in card}
        public["feature_identity"] = _card_identity(card)
        public["quantitative_records"] = _public_records(card)
        trajectory = _compact_trajectory(card, stage=compaction_stage)
        if trajectory:
            public["trajectory"] = trajectory
        literature = _limit_literature(card, stage=compaction_stage)
        if literature:
            public["literature_comparison"] = literature
        retained_cards.append(public)
    retained_cards = _group_family_cards(retained_cards, stage=compaction_stage)
    figures = []
    for figure in audit.get("figure_cards") or []:
        if not isinstance(figure, Mapping):
            continue
        key = str(figure.get("figure_key") or "")
        if compaction_stage >= 2 and figure_keys and key not in figure_keys:
            omitted.append({"figure_key": key, "reason": "unassigned_figure"})
            continue
        figures.append({
            "figure_key": key,
            "figure_label": figure.get("figure_label") or figure.get("display_label"),
            "display_label": figure.get("display_label") or figure.get("figure_label"),
            "placement": figure.get("placement"),
            "question": figure.get("question"),
            "selected_display_identities": [
                item.get("reader_display_identity") or item.get("display_label")
                for item in figure.get("selected_features") or []
                if isinstance(item, Mapping)
            ],
            "render_axis": figure.get("render_axis") or "protein_adjusted_relative_ptm_contrast",
        })
    questions = []
    question_map = _as_mapping(audit.get("research_question_evidence_map") or _as_mapping(plan).get("research_question_evidence_map"))
    for question in question_map.get("questions") or []:
        if compaction_stage >= 2 and section_type in {"results", "discussion"}:
            if question.get("coverage_status") == "missing" and not question.get("feature_ids"):
                omitted.append({"question_id": question.get("question_id"), "reason": "unrelated_question"})
                continue
        questions.append({
            "question_id": question.get("question_id"),
            "normalized_question": question.get("normalized_question") or question.get("original_text"),
            "display_identities": question.get("display_identities") or [],
            "evidence_ids": question.get("evidence_ids") or [],
            "answerability": question.get("answerability"),
        })
    retained_ids = [eid for card in retained_cards for eid in card.get("evidence_ids") or []]
    return {
        "contract_version": SECTION_MODEL_PACKET_VERSION,
        "packet_role": "section_model",
        "mode": audit.get("mode", "data_only"),
        "section_type": section_type,
        "section_story_contract": {section_type: contract} if contract else {},
        "section_claim_budget": {section_type: (_as_mapping(audit.get("section_claim_budget")).get(section_type) or ["O1", "O2"])},
        "reader_cards": retained_cards,
        "figure_cards": figures,
        "research_question_evidence_map": {"questions": questions},
        "quantitation_estimator_contract": audit.get("quantitation_estimator_contract"),
        "study_design": audit.get("study_design"),
        "prompt_compaction_stage": compaction_stage,
        "retained_evidence_ids": retained_ids,
        "omitted_evidence_ids_and_reason": omitted,
        "display_policy": effective_display_policy("shadow"),
    }


def redact_token_catalog_for_model(catalog: Mapping[str, Any]) -> dict:
    redacted = {}
    for token, record in dict(catalog or {}).items():
        item = dict(record)
        item.pop("canonical_feature_id", None)
        item.pop("feature_id", None)
        item.pop("feature_identity_version", None)
        redacted[token] = item
    return redacted


def _catalog_for_model(audit_packet: Mapping[str, Any], model_packet: Mapping[str, Any]) -> dict:
    catalog = value_token_catalog(audit_packet)
    retained = set(model_packet.get("retained_evidence_ids") or [])
    stage = int(model_packet.get("prompt_compaction_stage") or 0)
    if retained:
        catalog = {token: record for token, record in catalog.items() if record.get("evidence_id") in retained}
    if stage >= 3:
        compact_conditions = set()
        for card in model_packet.get("reader_cards") or []:
            trajectory = card.get("trajectory")
            if isinstance(trajectory, Mapping):
                for key in ("first", "peak", "last"):
                    condition = _as_mapping(trajectory.get(key)).get("condition")
                    if condition:
                        compact_conditions.add(condition)
        if compact_conditions:
            catalog = {
                token: record for token, record in catalog.items()
                if record.get("condition") in compact_conditions or record.get("record_type") != "feature_axis"
            }
    return redact_token_catalog_for_model(catalog)


def _unavailable_records_for_model(audit_packet: Mapping[str, Any], model_packet: Mapping[str, Any]) -> list[dict]:
    """Keep only section-retained unavailable records in the model prompt."""
    retained = set(model_packet.get("retained_evidence_ids") or [])
    stage = int(model_packet.get("prompt_compaction_stage") or 0)
    records = [
        record
        for card in audit_packet.get("reader_cards") or []
        for record in quantitative_records(card)
        if record.get("value") is None
        and (not retained or record.get("evidence_id") in retained)
    ]
    if stage >= 3:
        compact_conditions = set()
        for card in model_packet.get("reader_cards") or []:
            trajectory = card.get("trajectory")
            if isinstance(trajectory, Mapping):
                for key in ("first", "peak", "last"):
                    condition = _as_mapping(trajectory.get(key)).get("condition")
                    if condition:
                        compact_conditions.add(condition)
        if compact_conditions:
            records = [
                record for record in records
                if record.get("condition") in compact_conditions
                or record.get("record_type") != "feature_axis"
            ]
    return list(redact_token_catalog_for_model({str(index): record for index, record in enumerate(records)}).values())


def format_section_model_prompt(
    model_packet: Mapping[str, Any],
    section_type: str,
    plan: Mapping[str, Any] | None,
    audit_packet: Mapping[str, Any],
) -> str:
    """Format model-visible cards and a redacted token catalog bound to the audit packet."""
    prompt = format_authoring_packet_for_llm(
        model_packet,
        section_type,
        plan,
        include_quantitative_records=False,
    )
    catalog = _catalog_for_model(audit_packet, model_packet)
    instructions = structured_authoring_instructions(
        audit_packet,
        token_catalog=catalog,
        unavailable_records=_unavailable_records_for_model(audit_packet, model_packet),
    )
    return prompt + instructions


def format_narrative_model_prompt(
    model_packet: Mapping[str, Any],
    section_type: str,
    plan: Mapping[str, Any] | None,
    audit_packet: Mapping[str, Any],
) -> str:
    """Format a paragraph-first model prompt from the same compact evidence set."""
    prompt = format_authoring_packet_for_llm(
        model_packet,
        section_type,
        plan,
        include_quantitative_records=False,
    )
    catalog = _catalog_for_model(audit_packet, model_packet)
    instructions = narrative_authoring_instructions(
        audit_packet,
        token_catalog=catalog,
        unavailable_records=_unavailable_records_for_model(audit_packet, model_packet),
    )
    return prompt + instructions


def compose_compacted_section_prompt(
    audit_packet: Mapping[str, Any],
    section_type: str,
    plan: Mapping[str, Any] | None,
    *,
    extra_suffix: str = "",
    max_chars: int = PROMPT_CHAR_BUDGET,
) -> tuple[str, dict]:
    """Walk the compaction ladder until the prompt fits, without mutating the audit packet."""
    last_prompt = ""
    last_packet = {}
    for stage in range(0, 6):
        model_packet = build_section_model_packet(audit_packet, plan, section_type, compaction_stage=stage)
        prompt = format_section_model_prompt(model_packet, section_type, plan, audit_packet) + extra_suffix
        last_prompt, last_packet = prompt, model_packet
        if len(prompt) <= max_chars:
            return prompt, {
                "prompt_compaction_stage": stage,
                "prompt_character_count": len(prompt),
                "retained_evidence_ids": list(model_packet.get("retained_evidence_ids") or []),
                "omitted_evidence_ids_and_reason": list(model_packet.get("omitted_evidence_ids_and_reason") or []),
                "within_budget": True,
                "section_model_packet": model_packet,
            }
    return last_prompt, {
        "prompt_compaction_stage": 5,
        "prompt_character_count": len(last_prompt),
        "retained_evidence_ids": list(last_packet.get("retained_evidence_ids") or []),
        "omitted_evidence_ids_and_reason": list(last_packet.get("omitted_evidence_ids_and_reason") or []),
        "within_budget": len(last_prompt) <= max_chars,
        "section_model_packet": last_packet,
        "generation_degraded": True,
        "fallback_reason": None,
    }


def compose_compacted_narrative_prompt(
    audit_packet: Mapping[str, Any],
    section_type: str,
    plan: Mapping[str, Any] | None,
    *,
    extra_suffix: str = "",
    max_chars: int = PROMPT_CHAR_BUDGET,
    start_compaction_stage: int = 0,
) -> tuple[str, dict]:
    """Apply the established compaction ladder to paragraph-first generation."""
    last_prompt = ""
    last_packet: dict = {}
    for stage in range(max(0, min(int(start_compaction_stage), 5)), 6):
        model_packet = build_section_model_packet(audit_packet, plan, section_type, compaction_stage=stage)
        prompt = format_narrative_model_prompt(model_packet, section_type, plan, audit_packet) + extra_suffix
        last_prompt, last_packet = prompt, model_packet
        if len(prompt) <= max_chars:
            return prompt, {
                "prompt_compaction_stage": stage,
                "prompt_character_count": len(prompt),
                "retained_evidence_ids": list(model_packet.get("retained_evidence_ids") or []),
                "omitted_evidence_ids_and_reason": list(model_packet.get("omitted_evidence_ids_and_reason") or []),
                "within_budget": True,
                "section_model_packet": model_packet,
                "authoring_style": "narrative_first",
            }
    return last_prompt, {
        "prompt_compaction_stage": 5,
        "prompt_character_count": len(last_prompt),
        "retained_evidence_ids": list(last_packet.get("retained_evidence_ids") or []),
        "omitted_evidence_ids_and_reason": list(last_packet.get("omitted_evidence_ids_and_reason") or []),
        "within_budget": len(last_prompt) <= max_chars,
        "section_model_packet": last_packet,
        "authoring_style": "narrative_first",
        "generation_degraded": True,
        "fallback_reason": None,
    }
