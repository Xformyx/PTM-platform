"""Deterministic scientific-language facts and sentence-level semantic guards.

These helpers do not infer mechanism.  They translate numeric trajectories and
explicit analysis units into bounded wording that can be reused across Results,
Discussion, Abstract, and Conclusion.
"""

from __future__ import annotations

import math
import re
from typing import Any, Iterable, Mapping


TRAJECTORY_FACT_VERSION = "trajectory_shape_fact.v1"
SEMANTIC_GUARD_VERSION = "reader_semantic_guard.v1"
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
        "reader_summary": f"The {axis.replace('_', ' ')} {interpretation}: {point_text}.",
        "monotonic_claim_allowed": classification in {"monotonic_increase", "monotonic_decrease"},
        "baseline_return_claim_allowed": baseline_return_claim_allowed,
        "baseline_return_conditions": [ordered[index]["condition"] for index in baseline_return_indices],
        "extrema": extrema,
        "points": ordered,
    }


def _matching_feature_fact(sentence: str, cards: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    lowered = sentence.lower()
    for card in cards:
        if str(card.get("category")) != "measured_feature_observation":
            continue
        identity = card.get("feature_identity") or {}
        tokens = [str(identity.get("gene") or ""), str(identity.get("candidate_residue_annotation") or "")]
        tokens = [token.lower() for token in tokens if token]
        if tokens and all(token in lowered for token in tokens):
            fact = card.get("trajectory_shape_fact")
            if isinstance(fact, Mapping):
                return fact
    return None


def repair_semantic_sentence(
    sentence: str,
    cards: Iterable[Mapping[str, Any]],
) -> tuple[str, list[str], list[str]]:
    """Repair only semantics that can be validated deterministically."""
    text = str(sentence or "")
    actions: list[str] = []
    reasons: list[str] = []

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

    replacements = [
        (r"\bgain of activity\b", "gain in pair-level concordance"),
        (r"\bsignaling activation\b", "increase in pair-level concordance"),
        (r"\bpathway reconfiguration\b", "observed local concordance reorganization across sampled intervals"),
        (r"\bsignaling flow\b", "sampled temporal concordance pattern"),
        (r"\bcoordinated waves? of signaling activity\b", "observed temporal profile and concordance patterns"),
    ]
    for pattern, replacement in replacements:
        if re.search(pattern, text, flags=re.IGNORECASE):
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
            actions.append("bound_concordance_interpretation")
            reasons.append("concordance_is_descriptive_not_activation_or_flow")

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


def audit_semantic_claims(text: str, cards: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    violations: list[dict[str, Any]] = []
    for index, sentence in enumerate(re.split(r"(?<=[.!?])\s+", str(text or "")), 1):
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
            if re.match(r"^(?:whereas|while|which|although|because|and|but|or|thereby|thusly)\b", sentence, flags=re.IGNORECASE):
                fragment_records.append({"sentence_index": index, "text": sentence[:160]})
            if re.search(r"(?:\.{2,}|,{2,}|;{2,}|:{2,}|\?{2,}|!{2,}|[;,]\s*\.)", sentence):
                doubled_punctuation.append({"sentence_index": index, "text": sentence[:160]})
    section_word_budgets = {
        "conclusion": 180,
        "supplementary research question answers": 260,
        "research question answers": 260,
    }
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
        "section_word_budget_violation_count": len(section_word_budget_violations),
        "fragments": fragment_records,
        "lowercase_sentence_starts": lowercase_records,
        "doubled_punctuation": doubled_punctuation,
        "section_word_budget_violations": section_word_budget_violations,
    }
