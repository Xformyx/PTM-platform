"""Deterministic scientific-language facts and sentence-level semantic guards.

These helpers do not infer mechanism.  They translate numeric trajectories and
explicit analysis units into bounded wording that can be reused across Results,
Discussion, Abstract, and Conclusion.
"""

from __future__ import annotations

import math
import re
from typing import Any, Iterable, Mapping
from common.section_budgets import closing_section_maxima, word_count, conclusion_roles, REQUIRED_CONCLUSION_ROLES


TRAJECTORY_FACT_VERSION = "trajectory_shape_fact.v1"
SEMANTIC_GUARD_VERSION = "reader_semantic_guard.v2"
DEFAULT_BASELINE_BAND_LOG2 = 0.15


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def build_trajectory_shape_fact(
    points: Iterable[Mapping[str, Any]],
    *,
    axis: str = "ptm_protein_adjusted_log2fc",
    baseline_band_log2: float = DEFAULT_BASELINE_BAND_LOG2,
) -> dict[str, Any]:
    ordered: list[dict[str, Any]] = []
    for point in points:
        value = _finite(point.get(axis))
        if value is None or bool(point.get("detection_context_only")):
            continue
        ordered.append({"condition": str(point.get("condition") or "recorded condition"), "value": value})

    if len(ordered) < 2:
        return {
            "contract_version": TRAJECTORY_FACT_VERSION,
            "axis": axis,
            "classification": "insufficient_numeric_points",
            "baseline_band_log2": baseline_band_log2,
            "reader_summary": "The recorded trajectory did not contain enough conventional numeric points for a shape classification.",
            "monotonic_claim_allowed": False,
            "baseline_return_claim_allowed": False,
            "points": ordered,
        }

    values = [item["value"] for item in ordered]
    deltas = [right - left for left, right in zip(values, values[1:])]
    direction_steps = [
        1 if delta > baseline_band_log2 else -1 if delta < -baseline_band_log2 else 0
        for delta in deltas
    ]
    has_up = any(step > 0 for step in direction_steps)
    has_down = any(step < 0 for step in direction_steps)
    if has_up and has_down:
        classification = "non_monotonic"
    elif has_up:
        classification = "monotonic_increase"
    elif has_down:
        classification = "monotonic_decrease"
    else:
        classification = "approximately_stable_within_descriptive_band"

    excursions = [abs(value) > baseline_band_log2 for value in values]
    baseline_return_indices = [
        index for index, value in enumerate(values)
        if index > 0 and abs(value) <= baseline_band_log2 and any(excursions[:index])
    ]
    baseline_return_claim_allowed = bool(baseline_return_indices)
    extrema = {
        "maximum": {"condition": ordered[max(range(len(values)), key=values.__getitem__)]["condition"], "value": max(values)},
        "minimum": {"condition": ordered[min(range(len(values)), key=values.__getitem__)]["condition"], "value": min(values)},
    }
    axis_label = {
        "ptm_protein_adjusted_log2fc": "protein-adjusted PTM contrast",
        "ptm_unadjusted_log2fc": "unadjusted PTM contrast",
        "protein_log2fc": "linked protein contrast",
    }.get(axis, axis.replace("_", " "))
    point_text = "; ".join(f"{item['condition']} {item['value']:+.3f}" for item in ordered)
    if classification == "non_monotonic":
        interpretation = "showed a non-monotonic trajectory across the sampled conditions"
    elif classification == "monotonic_increase":
        interpretation = "increased monotonically within the pre-specified descriptive tolerance"
    elif classification == "monotonic_decrease":
        interpretation = "decreased monotonically within the pre-specified descriptive tolerance"
    else:
        interpretation = "remained within the pre-specified descriptive tolerance"
    return {
        "contract_version": TRAJECTORY_FACT_VERSION,
        "axis": axis,
        "classification": classification,
        "baseline_band_log2": baseline_band_log2,
        "reader_summary": f"The {axis_label} {interpretation}: {point_text}.",
        "monotonic_claim_allowed": classification in {"monotonic_increase", "monotonic_decrease"},
        "baseline_return_claim_allowed": baseline_return_claim_allowed,
        "baseline_return_conditions": [ordered[index]["condition"] for index in baseline_return_indices],
        "extrema": extrema,
        "points": ordered,
    }


def _matching_feature_fact(sentence: str, cards: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    from .quantitative_claims import matching_cards
    matches = matching_cards(sentence, cards)
    identities = {c.get("feature_identity", {}).get("reader_feature_id") for c in matches}
    if len(identities) != 1:
        return None
    return next((c["trajectory_shape_fact"] for c in matches if isinstance(c.get("trajectory_shape_fact"), Mapping)), None)


def sentence_evidence_scope(sentence: str) -> str:
    # Citations alone cannot exempt a statement about the present measurements.
    current = re.search(r"\b(?:our|these|this (?:study|analysis|experiment)|current|the (?:measured|observed)|data show)\b|PF-[A-Z0-9]+", sentence, re.I)
    if not current and re.search(r"\[REF:|\[\d+(?:[,–-]\d+)*\]|\b(?:published|literature|prior work)\b", sentence, re.I):
        return "literature_context"
    if re.search(r"\b(?:hypothes\w*|propose to test|could be tested|test whether)\b", sentence, re.I):
        return "hypothesis"
    return "observation"


def is_negated_boundary(sentence: str) -> bool:
    # A later affirmative clause is validated separately instead of inheriting
    # an earlier negation ("does not prove X, but demonstrates Y").
    return bool(re.search(r"\b(?:does not|do not|did not|cannot|could not|doesn't|can't)\s+(?:directly\s+)?(?:prove|establish|demonstrate|show|imply|measure|support|infer)\b", sentence, re.I)) and not re.search(r"\b(?:but|however|yet)\b", sentence, re.I)


def _protected_sentence(text: str) -> bool:
    return is_negated_boundary(text) or sentence_evidence_scope(text) in {"literature_context", "hypothesis"}


def repair_semantic_sentence(
    sentence: str,
    cards: Iterable[Mapping[str, Any]],
) -> tuple[str, list[str], list[str]]:
    """Repair only semantics that can be validated deterministically."""
    text = str(sentence or "")
    actions: list[str] = []
    reasons: list[str] = []

    if _protected_sentence(text):
        return text, actions, reasons
    fact = _matching_feature_fact(text, cards)
    monotonic_signal = re.search(
        r"\b(?:continued to rise|continued rising|steadily (?:rose|increased)|monotonic(?:ally)? (?:rise|increase)|"
        r"sustained increase across|progressively increased)\b",
        text,
        flags=re.IGNORECASE,
    )
    if monotonic_signal and fact and not bool(fact.get("monotonic_claim_allowed")):
        text = str(fact.get("reader_summary") or text)
        actions.append("rewrite_trajectory_summary_from_deterministic_fact")
        reasons.append("monotonic_claim_conflicts_with_recorded_trajectory")

    if re.search(r"\b(?:returned to|near|approached) baseline\b", text, flags=re.IGNORECASE):
        if fact and not bool(fact.get("baseline_return_claim_allowed")):
            text = str(fact.get("reader_summary") or text)
            actions.append("rewrite_baseline_claim_from_deterministic_fact")
            reasons.append("baseline_return_not_supported_by_predeclared_band")

    # Reject an unsupported mechanism as a whole sentence. Keep ordinary
    # phosphorylation/dephosphorylation background intact.
    overreach = re.search(
        r"\b(?:gain of activity|signaling activation|pathway reconfiguration|significant rewiring|"
        r"propagation|waves? of signaling activity|signaling flow|return toward basal state|"
        r"signal termination|negative feedback|post-receptor signaling defects)\b", text, re.I)
    current_dephosphorylation = re.search(r"\b(?:measured|observed|our|these|current)\b", text, re.I) and re.search(r"\bdephosphorylation\b", text, re.I)
    if overreach or current_dephosphorylation:
        # Never replace a sentence containing immutable facts with unrelated
        # prose. Such sentences are withheld for an evidence-bound rewrite.
        protected = re.search(r"PF-[A-Z0-9]+|\d|\[REF:", text, re.I)
        text = "" if protected else (
            "The observed local concordance reorganization and temporal profile patterns describe a "
            "time-ordered measured pattern across sampled intervals; they do not establish a mechanism."
        )
        actions.append("bound_concordance_interpretation")
        reasons.append("current_data_mechanism_not_supported")

    if re.search(r"\b\d[\d,]*\s+candidate pairs\b", text, flags=re.IGNORECASE) and not re.search(
        r"\bunique\s+candidate pairs\b", text, flags=re.IGNORECASE
    ):
        text = re.sub(r"\b(\d[\d,]*)\s+candidate pairs\b", r"\1 pair-transition records", text, flags=re.IGNORECASE)
        actions.append("clarify_pair_transition_unit")
        reasons.append("pair_transition_records_are_not_unique_pairs")

    if re.search(r"\bonset and exit (?:were|was) (?:both )?resolved\b", text, flags=re.IGNORECASE):
        text = re.sub(
            r"\bonset and exit (?:were|was) (?:both )?resolved\b",
            "onset and exit were independently evaluable for the stated subset",
            text,
            flags=re.IGNORECASE,
        )
        actions.append("clarify_event_intersection_scope")
        reasons.append("onset_exit_intersection_requires_explicit_subset")

    if "footprint" in text.lower() and "self-ptm" in text.lower() and re.search(
        r"\b(?:therefore|thus|so|prevent(?:ed|s)?|could not)\b", text, flags=re.IGNORECASE
    ):
        text = (
            "Kinase-family substrate-footprint evaluability and observation of a kinase self-PTM are separate evidence questions; "
            "the former does not determine whether a kinase feature was measured or annotated."
        )
        actions.append("separate_footprint_from_self_ptm_evidence")
        reasons.append("footprint_evaluability_does_not_control_self_ptm_observation")

    return text, actions, reasons


def normalize_reader_prose(text: str) -> str:
    """Repair mechanical damage after marker removal without changing claims."""
    value = str(text or "")
    value = re.sub(r"[,;:]\.+\s+(?=(?:whereas|while|although)\b)", ", ", value, flags=re.I)
    value = re.sub(r"([.!?])\s*[,;:]", r"\1", value)
    value = re.sub(r"[ \t]+([,.;:!?])", r"\1", value)
    value = re.sub(r"([,;:])\s*\.", ".", value)
    value = re.sub(r"\.{2,}", ".", value)
    value = re.sub(r",{2,}", ",", value)
    value = re.sub(r";{2,}", ";", value)
    value = re.sub(r":{2,}", ":", value)
    value = re.sub(r"\?{2,}", "?", value)
    value = re.sub(r"!{2,}", "!", value)
    value = re.sub(r"[ \t]{2,}", " ", value)
    def repair_sentence(sentence: str) -> str:
        stripped = sentence.strip()
        alpha = re.search(r"[A-Za-z]", stripped)
        if alpha and stripped[alpha.start()].islower():
            index = alpha.start()
            stripped = stripped[:index] + stripped[index].upper() + stripped[index + 1:]
        return stripped

    repaired_lines: list[str] = []
    for line in value.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "|", "![", "- ", "* ", ">")):
            repaired_lines.append(line.rstrip())
            continue
        sentences = [
            repair_sentence(sentence)
            for sentence in re.split(r"(?<=[.!?])\s+", stripped)
            if sentence.strip()
        ]
        repaired_lines.append(" ".join(sentence for sentence in sentences if sentence))
    return "\n".join(repaired_lines).strip()


def _word_count(text: str) -> int:
    return word_count(text)


def _compress_plain_section(body: str, maximum_words: int) -> str:
    sentences = list(dict.fromkeys(s.strip() for s in re.split(r"(?<=[.!?])\s+", body or "") if s.strip()))
    # Reserve one complete sentence for each role, including the ending boundary
    # and next test. No truncation or fabricated replacement of protected facts.
    required = set()
    covered = set()
    for role in REQUIRED_CONCLUSION_ROLES:
        if role in covered:
            continue
        options = [(i, sentence) for i, sentence in enumerate(sentences) if role in conclusion_roles(sentence)]
        if options:
            i, sentence = min(options, key=lambda item: word_count(item[1]))
            required.add(i)
            covered.update(conclusion_roles(sentence))
    selected = set(required)
    used = sum(word_count(sentences[i]) for i in selected)
    for i, sentence in enumerate(sentences):
        if i not in selected and used + word_count(sentence) <= maximum_words:
            selected.add(i)
            used += word_count(sentence)
    # If required sentences alone exceed the budget, preserve them and let the
    # audit fail visibly. A passing length audit must not erase limitations.
    return " ".join(sentences[i] for i in sorted(selected))


def _compress_question_answers(body: str, maximum_words: int) -> str:
    parts = re.split(r"(?m)(?=^###\s+Q\d+\b)", body or "")
    questions = [part.strip() for part in parts if part.strip().startswith("###")]
    if not questions:
        return _compress_plain_section(body, maximum_words)
    heading_word_count = sum(_word_count(question.partition("\n")[0]) for question in questions)
    available_answer_words = max(0, maximum_words - heading_word_count)
    per_question = max(5, available_answer_words // len(questions))
    compressed: list[str] = []
    for question in questions:
        heading, _, answer = question.partition("\n")
        answer_sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", answer.strip())
            if sentence.strip()
        ]
        kept: list[str] = []
        boundary = next(
            (sentence for sentence in reversed(answer_sentences) if re.search(r"\b(?:restricted|does not|requires?|next|follow-up|validation)\b", sentence, flags=re.IGNORECASE)),
            "",
        )
        for sentence in answer_sentences:
            if sentence == boundary:
                continue
            if _word_count(" ".join([*kept, sentence, boundary])) > per_question:
                continue
            kept.append(sentence)
            if len(kept) >= 2:
                break
        if boundary and _word_count(" ".join([*kept, boundary])) <= per_question:
            kept.append(boundary)
        compressed.append(heading + "\n\n" + " ".join(kept))
    result = "\n\n".join(compressed)
    return result


def enforce_report_word_budgets(text: str) -> tuple[str, dict[str, Any]]:
    """Deterministically compress only bounded closing/supplementary sections."""
    source = str(text or "")
    pattern = re.compile(r"(?m)^##\s+(.+?)\s*$")
    matches = list(pattern.finditer(source))
    if not matches:
        return normalize_reader_prose(source), {"contract_version": "reader_section_compression.v1", "sections": []}
    output: list[str] = [source[:matches[0].start()]]
    audit: list[dict[str, Any]] = []
    budgets = closing_section_maxima()
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(source)
        heading = match.group(0)
        label = match.group(1).strip().lower()
        body = source[match.end():end].strip()
        before = _word_count(body)
        maximum = budgets.get(label)
        compressed = body
        if maximum is not None and before > maximum:
            compressed = (
                _compress_question_answers(body, maximum)
                if "question answers" in label
                else _compress_plain_section(body, maximum)
            )
        after = _word_count(compressed)
        output.append(heading + ("\n\n" + compressed if compressed else "") + "\n\n")
        if maximum is not None:
            audit.append({
                "section": label,
                "before_words": before,
                "after_words": after,
                "maximum_words": maximum,
                "compressed": after < before,
                "within_budget": after <= maximum,
                "preserved_roles": sorted(conclusion_roles(compressed)) if label == "conclusion" else [],
                "missing_roles": sorted(set(REQUIRED_CONCLUSION_ROLES) - conclusion_roles(compressed)) if label == "conclusion" else [],
            })
    return normalize_reader_prose("".join(output).rstrip()), {
        "contract_version": "reader_section_compression.v1",
        "sections": audit,
        "all_within_budget": all(item["within_budget"] for item in audit),
    }


_REFERENCE_SECTION_RE = re.compile(r"(?ms)^#{1,3}\s+References\b.*\Z")


def prose_without_reference_section(text: str) -> str:
    """Drop the bibliography before semantic-claim audit.

    Citation titles are not reader scientific claims. A paper title that
    contains a guarded word such as "propagation" must not withhold MD/HTML/DOCX.

    docs/implementation_log.md [2026-09-12] References 제목은 semantic withhold 대상이 아님.
    """

    return _REFERENCE_SECTION_RE.sub("", str(text or "")).rstrip()


def audit_semantic_claims(text: str, cards: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    violations: list[dict[str, Any]] = []
    body = prose_without_reference_section(text)
    for index, sentence in enumerate(re.split(r"(?<=[.!?])\s+", body), 1):
        repaired, actions, reasons = repair_semantic_sentence(sentence, cards)
        if actions and repaired != sentence:
            violations.append({"sentence_index": index, "actions": actions, "reason_codes": reasons})
    return {
        "contract_version": SEMANTIC_GUARD_VERSION,
        "violation_count": len(violations),
        "violations": violations,
    }


def audit_language_quality(text: str) -> dict[str, Any]:
    """Detect mechanical prose damage without grading scientific style."""
    fragment_records: list[dict[str, Any]] = []
    lowercase_records: list[dict[str, Any]] = []
    doubled_punctuation: list[dict[str, Any]] = []
    duplicate_quantitation_phrases: list[dict[str, Any]] = []
    section_lines: dict[str, list[str]] = {}
    current_section = ""
    index = 0
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if line.startswith("## ") and not line.startswith("### "):
            current_section = line[3:].strip().lower()
            section_lines.setdefault(current_section, [])
            continue
        if current_section and line and not line.startswith(("![", "|")):
            section_lines.setdefault(current_section, []).append(line)
        if not line or line.startswith(("#", "|", "![", "- ", "* ", ">")):
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", line):
            sentence = sentence.strip()
            if not sentence:
                continue
            index += 1
            alpha = re.search(r"[A-Za-z]", sentence)
            if alpha and sentence[alpha.start()].islower():
                lowercase_records.append({"sentence_index": index, "text": sentence[:160]})
            if re.match(r"^(?:which|thereby|thusly)\b", sentence, flags=re.IGNORECASE) or (re.match(r"^(?:whereas|while|although|because)\b", sentence, re.I) and "," not in sentence):
                fragment_records.append({"sentence_index": index, "text": sentence[:160]})
            if re.search(r"(?:\.{2,}|,{2,}|;{2,}|:{2,}|\?{2,}|!{2,}|[;,]\s*\.|[.!?]\s*[,;:])", sentence):
                doubled_punctuation.append({"sentence_index": index, "text": sentence[:160]})
            if re.search(r"phosphorylation\s+protein-abundance-adjusted relative PTM ratio|(?:relative PTM ratio\s*){2}", sentence, re.I):
                duplicate_quantitation_phrases.append({"sentence_index": index, "text": sentence[:160]})
    section_word_budgets = closing_section_maxima()
    section_word_budget_violations = []
    for section, maximum in section_word_budgets.items():
        word_count = len(re.findall(r"\b\w+[\w'’-]*\b", " ".join(section_lines.get(section) or [])))
        if word_count > maximum:
            section_word_budget_violations.append({
                "section": section,
                "word_count": word_count,
                "maximum_words": maximum,
            })
    return {
        "contract_version": "reader_language_quality.v2",
        "fragment_count": len(fragment_records),
        "lowercase_sentence_start_count": len(lowercase_records),
        "doubled_punctuation_count": len(doubled_punctuation),
        "duplicate_quantitation_phrase_count": len(duplicate_quantitation_phrases),
        "section_word_budget_violation_count": len(section_word_budget_violations),
        "fragments": fragment_records,
        "lowercase_sentence_starts": lowercase_records,
        "doubled_punctuation": doubled_punctuation,
        "section_word_budget_violations": section_word_budget_violations,
    }
