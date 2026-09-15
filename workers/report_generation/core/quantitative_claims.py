"""Bind reader measurements to precursor/condition/axis, never to gene alone.

Free prose uses a deliberately narrow grammar: identify the feature, condition
and axis before each number. Unresolvable claims are withheld, not guessed.
Structured drafts use source tokens to render complete measurement clauses.
"""
from __future__ import annotations

import json
import math
import re
from decimal import Decimal
from typing import Any, Mapping

from common.model_json import parse_model_json

from .quantitative_fields import axis_number

CLAIM_SCHEMA_VERSION = "reader_quantitative_claim.v2"
NARRATIVE_CLAIM_SCHEMA_VERSION = "reader_narrative_claim.v1"
AXIS_LABELS = {"unadjusted": "unadjusted PTM contrast",
               "adjusted": "protein-adjusted relative PTM log2 contrast",
               "protein": "linked protein contrast"}
_ID = re.compile(r"\bPF-(?:[A-Z0-9]{20}|[A-Z0-9]{8})\b", re.I)
_TIME = re.compile(r"\b\d+(?:\.\d+)?\s*(?:min(?:utes?)?|h(?:ours?)?|s(?:ec(?:onds?)?)?)\b", re.I)
_AXIS = re.compile(r"\b(unadjusted(?: PTM)?|protein[- ]adjusted(?: relative)?(?: PTM)?(?: log2)?|linked protein|protein)(?: contrast| log2fc)?\b", re.I)
_NUMBER = re.compile(r"(?<![\w.])[+−-]?\d+(?:\.\d+)?(?:e[-+]?\d+)?(?!\w|\.\d)", re.I)


_TYPED_RECORD_TYPES = {
    "kinase_trajectory", "kinase_footprint", "module_interval",
    "protein_group", "pathway_enrichment",
    "dual_track", "paired_peptide_fraction", "multiform_comparison",
    "atlas_observation", "cluster_profile",
}


def _display_identity(identity: Mapping[str, Any], card: Mapping[str, Any] | None = None) -> str:
    display = str(identity.get("reader_display_identity") or "").strip()
    disambiguator = str(identity.get("reader_disambiguator") or "").strip()
    if display and disambiguator and disambiguator not in display:
        return f"{display} {disambiguator}"
    if display:
        return display
    if card and card.get("feature_label"):
        return str(card["feature_label"])
    gene = str(identity.get("gene") or "").strip()
    residue = str(identity.get("candidate_residue_annotation") or identity.get("position") or "").strip()
    if gene and residue:
        return f"{gene} modified-precursor feature annotated at {residue}"
    return gene or str(identity.get("reader_feature_id") or "measured feature")


def quantitative_records(card: Mapping[str, Any]) -> list[dict]:
    typed = [dict(record) for record in card.get("value_records") or [] if isinstance(record, Mapping)]
    identity = card.get("feature_identity") or {}
    fid = identity.get("reader_feature_id")
    if not fid:
        return typed
    display = _display_identity(identity, card)
    measurement = card.get("measurement_provenance") or {}
    records = []
    raw_points = card.get("trajectory") or [card]
    if isinstance(raw_points, Mapping):
        raw_points = [raw_points.get("first"), raw_points.get("peak"), raw_points.get("last")]
    for point in raw_points:
        if not isinstance(point, Mapping) or point.get("detection_context_only"):
            continue
        point_measurement = point.get("measurement_provenance") or measurement
        support = point.get("quality") or {**(card.get("replicate_support") or {}), **(card.get("statistical_support") or {})}
        for axis in AXIS_LABELS:
            prefix = "protein_adjusted" if axis == "adjusted" else axis
            axis_support = (point.get("axes") or {}).get(axis) or {}
            records.append({
                "evidence_id": (card.get("evidence_ids") or [card.get("card_id")])[0],
                "feature_id": fid, "condition": point.get("condition"), "axis": axis,
                "display_identity": display,
                "canonical_feature_id": identity.get("feature_id"),
                "feature_identity_version": identity.get("feature_identity_version"),
                "value": axis_number(point, axis),
                "p": support.get(f"{prefix}_p_value"), "q": support.get(f"{prefix}_q_value"),
                "control_n": support.get(f"{prefix}_control_n"), "treatment_n": support.get(f"{prefix}_treatment_n"),
                "measurement_unit": point_measurement.get("reader_measurement_unit"),
                "localization": point_measurement.get("localization_evidence"),
                "support": axis_support,
                "time_minutes": point.get("time_minutes"),
                "support_sets_differ": point.get("support_sets_differ"),
                "record_type": "feature_axis",
            })
    return typed + records


def matching_cards(sentence: str, cards) -> list[Mapping[str, Any]]:
    ids = set(_ID.findall(sentence.upper()))
    matched = []
    display_matched = []
    for card in cards:
        identity = card.get("feature_identity") or {}
        if not identity:
            continue
        display = _display_identity(identity, card)
        if ids:
            match = identity.get("reader_feature_id") in ids or identity.get("feature_id") in ids
        elif display and display.lower() in sentence.lower():
            match = True
            display_matched.append(card)
        else:
            labels = [identity.get("gene"), identity.get("candidate_residue_annotation")]
            match = all(label and re.search(r"(?<!\w)" + re.escape(str(label)) + r"(?!\w)", sentence, re.I) for label in labels)
            disambiguator = str(identity.get("reader_disambiguator") or "").strip()
            if match and disambiguator and disambiguator.lower() not in sentence.lower():
                match = False
        if match:
            matched.append(card)
    if display_matched and not ids:
        return display_matched
    return matched


def _condition(value):
    return re.sub(r"\s+", "", str(value)).lower()


def validate_quantitative_sentence(sentence: str, packet: Mapping[str, Any]) -> list[str]:
    from .scientific_semantics import sentence_evidence_scope
    if sentence_evidence_scope(sentence) == "literature_context":
        return []
    if (re.search(r"\bpathway\b.*\bsignifican|\bsignifican\w*\b.*\bpathway\b", sentence, re.I)
            and not re.search(r"\b(?:not|no|without)\b", sentence, re.I)):
        pathway_facts = packet.get("pathway_statistical_evidence") or []
        if not any(f.get("pathway_name") and str(f["pathway_name"]).lower() in sentence.lower()
                   and f.get("q_value") is not None and f["q_value"] < f.get("alpha", .05)
                   and f.get("source_artifact_sha256") for f in pathway_facts):
            return ["pathway_significance_not_bound_to_evaluable_test"]
    typed_errors = validate_typed_aggregate_sentence(sentence, packet)
    if typed_errors:
        return typed_errors
    cards = matching_cards(sentence, packet.get("reader_cards") or [])
    if not cards:
        ambiguous = []
        for card in packet.get("reader_cards") or []:
            identity = card.get("feature_identity") or {}
            labels = [identity.get("gene"), identity.get("candidate_residue_annotation")]
            if all(label and re.search(r"(?<!\w)" + re.escape(str(label)) + r"(?!\w)", sentence, re.I) for label in labels):
                ambiguous.append(card)
        if len({(c.get("feature_identity") or {}).get("reader_feature_id") for c in ambiguous}) > 1:
            return ["precursor_identity_ambiguous_or_stitched"]
    if re.search(r"(?:(?<!\w)no(?!\w)|without|unavailable|not available|not recorded).{0,70}(?:independent |unadjusted )+PTM|(?:independent |unadjusted )+PTM.{0,70}(?:unavailable|not available|not recorded)", sentence, re.I):
        scope_cards = cards or packet.get("reader_cards") or []
        if any(r["axis"] == "unadjusted" and r["value"] is not None for c in scope_cards for r in quantitative_records(c)):
            return ["available_unadjusted_observation_denied"]
    explicit_ids = set(_ID.findall(sentence.upper()))
    known_ids = {c.get("feature_identity", {}).get("reader_feature_id") for c in packet.get("reader_cards") or []}
    if explicit_ids - known_ids:
        return ["quantitative_unknown_feature_id"]
    if not cards:
        measured_number = re.search(r"\b(?:contrast|log2fc)\s*(?:(?:of|was|is|=)\s*)?[+−-]?\d", sentence, re.I)
        return ["quantitative_missing_precursor_identity"] if measured_number else []
    ids = {c["feature_identity"].get("reader_feature_id") for c in cards} - {None}
    if re.search(r"\b(?:single|only one|singly)[- ]?(?:phosphorylated|phosphorylation|site|residue)", sentence, re.I):
        if any(str(c["feature_identity"].get("modified_sequence") or "").lower().count("unimod:21") > 1 for c in cards):
            return ["multimodified_precursor_cannot_be_reduced_to_single_site"]
    if len(ids) > 1 and (not explicit_ids or re.search(r"\b(?:same|single)\b.*?\b(?:feature|precursor|trajectory)\b", sentence, re.I)):
        return ["precursor_identity_ambiguous_or_stitched"]
    if not ids:
        return ["quantitative_missing_precursor_identity"] if _NUMBER.search(sentence) else []
    from .scientific_semantics import is_negated_boundary
    if not is_negated_boundary(sentence) and sentence_evidence_scope(sentence) == "observation":
        if re.search(r"biologically reproducible|biological reproducibility|population[- ](?:level )?confidence interval", sentence, re.I):
            return ["pattern_population_inference_not_established"]
        if re.search(r"(?:no[- ]call|not evaluable|no annotation).*?kinase.*?inactive", sentence, re.I):
            return ["kinase_no_call_is_not_inactivity"]
    for figure_label in re.findall(r"\b(?:Supplementary\s+)?Figure\s+\d+[A-Z]?\b", sentence, re.I):
        figure = next((f for f in packet.get("figure_cards") or []
                       if (f.get("figure_label") or f.get("display_label") or "").lower() == figure_label.lower()), None)
        members = set((figure or {}).get("selected_reader_feature_ids") or [])
        members.update(f.get("reader_feature_id") for f in (figure or {}).get("selected_features") or [])
        if not figure or not ids.issubset(members):
            return ["quantitative_figure_membership_mismatch"]

    # Exclude identifiers, time labels and references from numeric-value parsing.
    clean = re.sub(r"\[(?:EVID|REF):[^\]]+\]", lambda m: " " * len(m[0]), sentence)
    clean = _ID.sub(lambda m: " " * len(m[0]), clean)
    clean = _TIME.sub(lambda m: " " * len(m[0]), clean)
    clean = re.sub(r"\bFigure\s+\d+[A-Z]?\b", lambda m: " " * len(m[0]), clean, flags=re.I)
    records = [r for card in cards for r in quantitative_records(card)]
    significance = bool(re.search(r"\bsignifican(?:t|tly|ce)\b", sentence, re.I)) and not re.search(r"\b(?:not|no|without|unavailable)\b", sentence, re.I)
    if significance and re.search(r"descriptive (?:tolerance|band)|after (?:protein )?adjustment|adjustment effect", sentence, re.I):
        return ["quantitative_adjustment_effect_not_tested"]
    for number in _NUMBER.finditer(clean):
        before = sentence[:number.start()]
        # The descriptive comparison band is an explicit contract, not a q test.
        if number[0] in {"0.15", "+0.15", "-0.15"} and re.search(r"descriptive (?:tolerance|band)", sentence, re.I):
            continue
        preceding_ids = list(_ID.finditer(before))
        fid = preceding_ids[-1][0].upper() if preceding_ids else None
        if fid is None:
            display_matches = []
            for card in cards:
                display = _display_identity(card.get("feature_identity") or {}, card)
                hidden = (card.get("feature_identity") or {}).get("reader_feature_id")
                if display and display.lower() in before.lower() and hidden:
                    display_matches.append(hidden)
            unique_displays = list(dict.fromkeys(display_matches))
            if len(unique_displays) == 1:
                fid = unique_displays[0]
            elif len(ids) == 1:
                fid = next(iter(ids))
        condition_patterns = [_TIME.pattern] + [r"(?<!\w)" + re.escape(str(r["condition"])) + r"(?!\w)" for r in records if r["condition"]]
        condition_pattern = re.compile("|".join(condition_patterns), re.I)
        times = list(condition_pattern.finditer(before))
        all_times = list(condition_pattern.finditer(sentence))
        condition = times[-1][0] if times else (all_times[0][0] if len(all_times) == 1 else None)
        axes = list(_AXIS.finditer(before))
        label = axes[-1][1].lower() if axes else ""
        axis = "unadjusted" if label.startswith("unadjusted") else "adjusted" if "adjusted" in label else "protein" if label else None
        field_match = re.search(r"\b(p|q)(?:[- ]value)?\s*[=:]?\s*$|\b(control|treatment)\s+n\s*[=:]?\s*$", before, re.I)
        field = (field_match[1].lower() if field_match[1] else field_match[2].lower() + "_n") if field_match else "value"
        candidates = [r for r in records if r["feature_id"] == fid and _condition(r["condition"]) == _condition(condition) and r["axis"] == axis]
        if not candidates:
            return ["quantitative_feature_condition_axis_unbound"]
        for figure_label in re.findall(r"\bFigure\s+\d+[A-Z]?\b", sentence, re.I):
            figure = next((f for f in packet.get("figure_cards") or [] if
                           (f.get("figure_label") or f.get("display_label") or "").lower() == figure_label.lower()), {})
            if figure.get("quantitative_bindings") and not any(
                b.get("feature_id") == fid and _condition(b.get("condition")) == _condition(condition)
                and b.get("axis") == axis and b.get("value") is not None
                for b in figure["quantitative_bindings"]
            ):
                return ["quantitative_figure_condition_axis_mismatch"]
        if significance and not any(r["q"] is not None and r["q"] < .05 for r in candidates):
            return ["quantitative_axis_significance_unsupported"]
        printed = number[0].replace("−", "-")
        tolerance = .5 * 10 ** Decimal(printed).as_tuple().exponent + 1e-12
        if not any(r[field] is not None and math.isclose(float(printed), r[field], abs_tol=tolerance, rel_tol=0) for r in candidates):
            return ["quantitative_source_value_mismatch"]
    return []


def value_token_catalog(packet: Mapping[str, Any]) -> dict[str, dict]:
    return {f"V{index}": record for index, record in enumerate(
        (record for card in packet.get("reader_cards") or [] for record in quantitative_records(card)
         if record.get("value") is not None), 1)}


def render_value_record(record: Mapping[str, Any]) -> str:
    """An indivisible clause keeps a source value attached to its actual axis."""
    if record.get("record_type") in _TYPED_RECORD_TYPES:
        entity = record.get("entity_id") or record.get("feature_id") or "entity"
        metric = record.get("metric_id") or record.get("axis") or "metric"
        where = record.get("interval") or record.get("condition") or "the evaluated window"
        unit = record.get("unit") or ""
        return f"{entity} had {metric} {record['value']} {unit} at {where}".strip()
    article = "an" if record["axis"] == "unadjusted" else "a"
    label = record.get("display_identity") or record.get("feature_id") or "measured feature"
    return (f"{label} at {record['condition']} had {article} {AXIS_LABELS[record['axis']]} "
            f"of {record['value']:+.3f}")


def typed_records(packet: Mapping[str, Any]) -> list[dict]:
    return [
        record for card in packet.get("reader_cards") or []
        for record in quantitative_records(card)
        if record.get("record_type") in _TYPED_RECORD_TYPES
    ]


def validate_typed_aggregate_sentence(sentence: str, packet: Mapping[str, Any]) -> list[str]:
    """Bind kinase/module/pathway numbers without a fake PF identity."""
    if _ID.search(sentence):
        return []
    records = typed_records(packet)
    if not records:
        return []
    mentions_typed = bool(re.search(
        r"\b(?:kinase|concordance|correlation|NES|enrichment|module|pathway|trajectory|paired|logit|multiform|dual[- ]track|cluster)\b",
        sentence, re.I,
    ))
    if not mentions_typed:
        return []
    clean = re.sub(r"\[(?:EVID|REF):[^\]]+\]", lambda m: " " * len(m[0]), sentence)
    numbers = list(_NUMBER.finditer(clean))
    if not numbers:
        return []
    for match in numbers:
        printed = match[0].replace("−", "-")
        try:
            numeric = float(printed)
        except ValueError:
            continue
        if printed in {"0.15", "+0.15", "-0.15"} and re.search(r"descriptive (?:tolerance|band)", sentence, re.I):
            continue
        fraction = re.search(r"\b(\d+)\s*/\s*(\d+)\b", sentence)
        if fraction and match.start() >= fraction.start() and match.end() <= fraction.end():
            for record in records:
                if record.get("denominator") is None:
                    continue
                entity = str(record.get("entity_id") or "").lower()
                if entity and entity not in sentence.lower():
                    continue
                if int(fraction[2]) != int(record["denominator"]):
                    return ["typed_record_denominator_mismatch"]
            continue
        before = sentence[:match.start()].lower()
        bound = False
        for record in records:
            if record.get("value") is None:
                continue
            entity = str(record.get("entity_id") or "").lower()
            metric = str(record.get("metric_id") or "").lower()
            interval = str(record.get("interval") or record.get("condition") or "").lower()
            if entity and entity not in sentence.lower():
                continue
            if metric and metric.replace("_", " ") not in before and metric not in before:
                if not re.search(r"\br\b|concordance|correlation|nes|q\b", before):
                    continue
            try:
                source = float(record["value"])
            except (TypeError, ValueError):
                continue
            tolerance = .5 * 10 ** Decimal(printed).as_tuple().exponent + 1e-12
            if math.isclose(numeric, source, abs_tol=tolerance, rel_tol=0):
                if interval and interval not in sentence.lower() and record.get("interval"):
                    return ["typed_record_interval_unbound"]
                bound = True
                break
        if not bound:
            return ["typed_record_value_unbound"]
    return []


def structured_authoring_instructions(
    packet: Mapping[str, Any],
    *,
    token_catalog: Mapping[str, Any] | None = None,
    unavailable_records: list[Mapping[str, Any]] | None = None,
) -> str:
    """Build structured-generation instructions from an explicitly scoped payload.

    The audit packet remains the canonical source for validation. A section model
    packet may, however, provide a reduced token/unavailable-record view so audit
    only observations cannot silently consume the provider prompt budget.
    """
    catalog = dict(token_catalog) if token_catalog is not None else value_token_catalog(packet)
    unavailable = (
        [dict(record) for record in unavailable_records]
        if unavailable_records is not None
        else [
            record
            for card in packet.get("reader_cards") or []
            for record in quantitative_records(card)
            if record["value"] is None
        ]
    )
    return ("\nReturn a JSON object with sentences matching this schema: "
            + json.dumps(SENTENCE_RESPONSE_FORMAT["json_schema"]["schema"])
            + "\nEach sentence carries evidence_ids and scope. Use {{V1}} style tokens for quantitative clauses; "
              "each token expands to a COMPLETE clause containing reader display identity, condition, axis and source value. "
              "Do not attach another condition, feature or axis to a token. List tokens in value_tokens. "
              "List only figures supporting this sentence in figure_keys. Use separate sentences for background, "
              "current observations and hypotheses. Preserve [REF:*] citations in text. Group sentences with paragraph integers. "
              "Do not emit numeric feature measurements outside tokens.\nImmutable token references: "
            + json.dumps(catalog, ensure_ascii=False, separators=(",", ":"))
            + "\nUnavailable observations (not value tokens; preserve the supplied reasons): "
            + json.dumps(unavailable, ensure_ascii=False, separators=(",", ":")))


def narrative_authoring_instructions(
    packet: Mapping[str, Any],
    *,
    token_catalog: Mapping[str, Any] | None = None,
    unavailable_records: list[Mapping[str, Any]] | None = None,
) -> str:
    """Request cohesive paragraphs before applying local evidence binding.

    The immutable token catalogue is retained for any exact current-study value,
    but the provider is no longer asked to turn every sentence into a separate
    evidence record.  This keeps the manuscript bridge sentences and paragraph
    roles legible while the decoder remains free to withhold a single unsupported
    numerical sentence rather than discarding a whole section.
    """
    catalog = dict(token_catalog) if token_catalog is not None else value_token_catalog(packet)
    unavailable = (
        [dict(record) for record in unavailable_records]
        if unavailable_records is not None
        else [
            record
            for card in packet.get("reader_cards") or []
            for record in quantitative_records(card)
            if record["value"] is None
        ]
    )
    return (
        "\nNarrative response contract: reader_narrative_section. Return a JSON object with cohesive manuscript paragraphs matching this schema: "
        + json.dumps(NARRATIVE_RESPONSE_FORMAT["json_schema"]["schema"])
        + "\nWrite 2–4 sentences per paragraph and use the requested paragraph role once. "
        "Use a bridge sentence between observed PTM patterns, descriptive temporal context, "
        "candidate-family context, and the next discriminating experiment. "
        "Current-study numbers must appear only as {{V1}} style value tokens; each token expands to "
        "a source-bound reader-safe feature, condition, axis, and value clause. Do not invent or alter "
        "numbers, evidence IDs, figures, citations, direct kinase–substrate assignments, catalytic activity, "
        "or causal propagation. Keep linked-protein values as denominator/quantitation-validity context rather "
        "than a co-equal biological response storyline. Preserve [REF:*] citations in text. "
        "A paragraph may use no value tokens when a qualitative, source-bound bridge is clearer. "
        "\nImmutable value tokens: "
        + json.dumps(catalog, ensure_ascii=False, separators=(",", ":"))
        + "\nUnavailable observations (not value tokens; use only their stated limitation when relevant): "
        + json.dumps(unavailable, ensure_ascii=False, separators=(",", ":"))
    )


SENTENCE_RESPONSE_FORMAT = {"type": "json_schema", "json_schema": {
    "name": "reader_section", "strict": True, "schema": {
        "type": "object", "additionalProperties": False, "required": ["sentences"],
        "properties": {"sentences": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["text", "paragraph", "scope", "evidence_ids", "value_tokens", "figure_keys"],
            "properties": {"text": {"type": "string"}, "paragraph": {"type": "integer"},
                "scope": {"type": "string", "enum": ["observation", "literature_context", "hypothesis", "study_rationale", "biological_interpretation", "testable_hypothesis"]},
                "evidence_ids": {"type": "array", "items": {"type": "string"}},
                "value_tokens": {"type": "array", "items": {"type": "string"}},
                "figure_keys": {"type": "array", "items": {"type": "string"}}}}}}}}}


NARRATIVE_RESPONSE_FORMAT = {"type": "json_schema", "json_schema": {
    "name": "reader_narrative_section", "strict": True, "schema": {
        "type": "object", "additionalProperties": False, "required": ["paragraphs"],
        "properties": {"paragraphs": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["role", "text", "scope", "evidence_ids", "value_tokens", "figure_keys"],
            "properties": {
                "role": {"type": "string"},
                "text": {"type": "string"},
                "scope": {"type": "string", "enum": ["observation", "literature_context", "hypothesis", "study_rationale", "biological_interpretation", "testable_hypothesis"]},
                "evidence_ids": {"type": "array", "items": {"type": "string"}},
                "value_tokens": {"type": "array", "items": {"type": "string"}},
                "figure_keys": {"type": "array", "items": {"type": "string"}}
            }
        }}}}}}


def decode_narrative_draft(content: str, packet: Mapping[str, Any]) -> tuple[str, list[dict]]:
    """Bind a paragraph-first provider draft without flattening its narrative arc.

    A malformed paragraph or a numerical sentence with no source binding is
    withheld locally.  Valid bridge, comparison, and next-experiment sentences
    in the same paragraph remain available to the downstream semantic repair.
    """
    catalog = value_token_catalog(packet)
    try:
        parsed = parse_model_json(content)
        paragraphs = parsed["paragraphs"] if isinstance(parsed, dict) else None
        if not isinstance(paragraphs, list):
            raise ValueError("paragraphs must be an array")
    except (ValueError, TypeError, KeyError):
        return "", [{"reason_code": "invalid_narrative_json", "retained": False}]

    evidence = {eid for card in packet.get("reader_cards") or [] for eid in card.get("evidence_ids") or []}
    figures = {str(figure.get("figure_key")): figure for figure in packet.get("figure_cards") or []}
    rendered: list[str] = []
    audit: list[dict] = []
    valid_scopes = {"observation", "literature_context", "hypothesis", "study_rationale", "biological_interpretation", "testable_hypothesis"}
    for index, item in enumerate(paragraphs, 1):
        reasons: list[str] = []
        if (
            not isinstance(item, Mapping)
            or not isinstance(item.get("text"), str)
            or not isinstance(item.get("role"), str)
            or not str(item.get("role") or "").strip()
            or item.get("scope") not in valid_scopes
            or any(
                not isinstance(item.get(key), list) or any(not isinstance(value, str) for value in item[key])
                for key in ("evidence_ids", "value_tokens", "figure_keys")
            )
        ):
            audit.append({"paragraph_index": index, "reason_code": "invalid_narrative_paragraph_record", "retained": False})
            continue
        text = str(item["text"]).strip()
        tokens = list(item["value_tokens"])
        references = [catalog[token] for token in tokens if token in catalog]
        if set(re.findall(r"\{\{(V\d+)\}\}", text)) != set(tokens) or any(token not in catalog for token in tokens):
            reasons.append("unknown_or_unbound_value_token")
        if references and item["scope"] != "observation":
            reasons.append("quantitative_reference_scope_mismatch")
        if not set(item["evidence_ids"]).issubset(evidence) or any(record["evidence_id"] not in item["evidence_ids"] for record in references):
            reasons.append("unbound_paragraph_evidence")
        for key in item["figure_keys"]:
            figure = figures.get(str(key))
            if figure is None or any(record.get("feature_id") not in figure.get("selected_reader_feature_ids", []) for record in references):
                reasons.append("quantitative_figure_membership_mismatch")
        if reasons:
            audit.append({"paragraph_index": index, "role": item.get("role"), "reason_codes": reasons, "retained": False})
            continue
        for token in tokens:
            text = text.replace("{{" + token + "}}", render_value_record(catalog[token]))

        retained_sentences: list[str] = []
        sentence_audit: list[dict] = []
        for sentence in _split_draft_sentences(text):
            local_reasons = validate_quantitative_sentence(sentence, packet)
            sentence_audit.append({
                "source_sentence": sentence,
                "validated_sentence": "" if local_reasons else sentence,
                "reason_codes": local_reasons or ["within_contract"],
                "retained": not local_reasons,
            })
            if not local_reasons:
                retained_sentences.append(sentence)
        paragraph_text = " ".join(retained_sentences)
        if paragraph_text:
            anchors = " ".join(f"[EVID:{eid}]" for eid in item["evidence_ids"])
            rendered.append((paragraph_text + " " + anchors).strip())
        audit.append({
            "paragraph_index": index,
            "role": item["role"],
            "scope": item["scope"],
            "evidence_ids": list(item["evidence_ids"]),
            "value_tokens": tokens,
            "sentence_audit": sentence_audit,
            "resolved_text": paragraph_text,
            "retained": bool(paragraph_text),
        })
    return "\n\n".join(rendered), audit


def merge_valid_narrative_drafts(drafts, packet: Mapping[str, Any]) -> tuple[str, list[dict]]:
    """Merge retries by paragraph role, retaining the most complete valid draft."""
    by_role: dict[str, tuple[str, int]] = {}
    audit: list[dict] = []
    for attempt, draft in enumerate(drafts, 1):
        if not draft or str(draft).startswith("[LLM Error"):
            continue
        prose, records = decode_narrative_draft(str(draft), packet)
        for record in records:
            audit.append({**record, "attempt": attempt})
            if not record.get("retained") or not record.get("role"):
                continue
            role = str(record["role"])
            candidate = str(record.get("resolved_text") or "").strip()
            if not candidate:
                continue
            score = len(candidate.split())
            prior = by_role.get(role)
            if prior is None or score > prior[1]:
                by_role[role] = (candidate, score)
    return "\n\n".join(value[0] for value in by_role.values()), audit


def decode_sentence_draft(content: str, packet: Mapping[str, Any]) -> tuple[str, list[dict]]:
    """Validate JSON and resolve immutable references; fail closed per sentence."""
    catalog = value_token_catalog(packet)
    try:
        parsed = parse_model_json(content)
        if not isinstance(parsed, dict):
            raise ValueError("draft must be an object")
        sentences = parsed["sentences"]
        if not isinstance(sentences, list):
            raise ValueError("sentences must be an array")
    except (ValueError, TypeError, KeyError):
        return "", [{"reason_code": "invalid_sentence_json", "retained": False}]
    paragraphs: dict[int, list[str]] = {}
    audit = []
    evidence = {eid for c in packet.get("reader_cards") or [] for eid in c.get("evidence_ids") or []}
    figures = {f["figure_key"]: f for f in packet.get("figure_cards") or []}
    for item in sentences:
        reasons = []
        if not isinstance(item, dict) or not isinstance(item.get("text"), str) or not isinstance(item.get("paragraph"), int) or any(
            not isinstance(item.get(key), list) or any(not isinstance(v, str) for v in item[key])
            for key in ("evidence_ids", "value_tokens", "figure_keys")
        ) or item.get("scope") not in {"observation", "literature_context", "hypothesis", "study_rationale", "biological_interpretation", "testable_hypothesis"}:
            audit.append({"reason_code": "invalid_sentence_record", "retained": False})
            continue
        text = item["text"]
        tokens = item["value_tokens"]
        unexpanded = re.sub(r"\{\{V\d+\}\}", "", text)
        unexpanded = re.sub(r"\[(?:REF|EVID):[^\]]+\]|\b(?:Supplementary\s+)?Figure\s+\d+[A-Z]?\b", "", unexpanded, flags=re.I)
        if tokens and (_TIME.search(unexpanded) or _ID.search(unexpanded) or _AXIS.search(unexpanded) or _NUMBER.search(unexpanded)):
            reasons.append("quantitative_token_rebinding_or_free_value")
        refs = [catalog[token] for token in tokens if token in catalog]
        if refs and item["scope"] != "observation":
            reasons.append("quantitative_reference_scope_mismatch")
        if set(re.findall(r"\{\{(V\d+)\}\}", text)) != set(tokens) or any(token not in catalog for token in tokens):
            reasons.append("unknown_or_unbound_value_token")
        if not set(item["evidence_ids"]).issubset(evidence) or any(r["evidence_id"] not in item["evidence_ids"] for r in refs):
            reasons.append("unbound_sentence_evidence")
        for key in item["figure_keys"]:
            if key not in figures or any(r["feature_id"] not in figures[key].get("selected_reader_feature_ids", []) for r in refs):
                reasons.append("quantitative_figure_membership_mismatch")
        for token in tokens:
            if token in catalog:
                text = text.replace("{{" + token + "}}", render_value_record(catalog[token]))
        reasons.extend(validate_quantitative_sentence(text, packet))
        audit.append({"sentence": item, "references": refs, "reason_codes": reasons, "retained": not reasons, "resolved_text": text})
    # Only individually valid observation/context sentences can support another
    # sentence. A rejected sibling cannot donate a citation or fabricated fact.
    observation_ids = {eid for c in packet.get("reader_cards") or [] if c.get("trajectory") for eid in c.get("evidence_ids") or []}
    citation_ids = {eid.lower() for c in packet.get("reader_cards") or [] for eid in c.get("citation_ids") or []}
    for record in audit:
        if not record["retained"]:
            continue
        item = record["sentence"]
        if item["scope"] in {"hypothesis", "testable_hypothesis", "biological_interpretation"}:
            siblings = [r["sentence"] for r in audit if r["retained"] and r["sentence"]["paragraph"] == item["paragraph"]
                        and r["sentence"]["scope"] in {"observation", "literature_context"}]
            group_text = " ".join(s["text"] for s in siblings + [item])
            group_evidence = {eid for s in siblings for eid in s["evidence_ids"]}
            cited = {v.lower() for v in re.findall(r"\[REF:([^\]]+)\]", group_text)}
            if (not siblings or not observation_ids.intersection(group_evidence) or not cited
                    or not cited.issubset(citation_ids)
                    or (item["scope"] != "biological_interpretation" and not re.search(r"predict|test|distinguish|discriminat", group_text, re.I))):
                record["reason_codes"].append("hypothesis_observation_literature_prediction_unbound")
                record["retained"] = False
        if record["retained"]:
            paragraphs.setdefault(item["paragraph"], []).append(record["resolved_text"] + " " + " ".join(f"[EVID:{eid}]" for eid in item["evidence_ids"]))
    return "\n\n".join(" ".join(paragraphs[k]) for k in sorted(paragraphs)), audit


_ABBREVIATION_END = re.compile(r"\b(?:Fig|Figs|e\.g|i\.e|vs|Ref|Dr|Prof)\.$", re.I)


def _split_draft_sentences(paragraph: str) -> list[str]:
    """Split on sentence ends without treating Fig./e.g. as a boundary."""
    merged: list[str] = []
    for piece in re.split(r"(?<=[.!?])\s+", str(paragraph or "").strip()):
        if not piece:
            continue
        if merged and _ABBREVIATION_END.search(merged[-1]):
            merged[-1] = f"{merged[-1]} {piece}"
        else:
            merged.append(piece)
    return merged


def merge_valid_sentence_drafts(drafts, packet):
    """Keep validated text from all attempts, with sentence-level rejection trace."""
    kept, audit = [], []
    for attempt, draft in enumerate(drafts, 1):
        if not draft or str(draft).startswith("[LLM Error"):
            continue
        prose, records = decode_sentence_draft(draft, packet)
        audit.extend({**r, "attempt": attempt} for r in records)
        for paragraph in prose.split("\n\n"):
            if not paragraph:
                continue
            # A repair commonly extends a previously valid paragraph. Keep the
            # complete supported replacement without repeating its old prefix.
            # Do not assemble isolated hypotheses from unrelated paragraphs.
            sentences = set(_split_draft_sentences(paragraph))
            if any(sentences <= prior for _, prior in kept):
                continue
            superseded = [i for i, (_, prior) in enumerate(kept) if prior <= sentences]
            position = min(superseded) if superseded else len(kept)
            kept = [entry for i, entry in enumerate(kept) if i not in superseded]
            kept.insert(position, (paragraph, sentences))
    return "\n\n".join(paragraph for paragraph, _ in kept), audit
