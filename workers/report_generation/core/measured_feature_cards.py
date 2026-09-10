"""Reader-safe current-order feature and quantitation comparison cards.

This module translates measured vector rows into bounded scientific-authoring
records.  It never queries literature, assigns kinases, or promotes magnitude to
biological priority.  Independent unadjusted PTM contrasts are kept distinct
from protein-adjusted and legacy reconstructed values.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Any, Iterable, Mapping

from ptm_shared.evidence_contracts import (
    EvaluationStatus,
    ObservationStatus,
    OutcomeClass,
    build_evidence_envelope,
    build_measurement_provenance,
)
from ptm_shared.de_novo_representation import is_de_novo_representation


FEATURE_OBSERVATION_CARD_VERSION = "feature_observation_card.v1"
QUANTITATION_COMPARISON_CARD_VERSION = "quantitation_comparison_card.v1"


def _mapping(value: Any) -> dict:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(row: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip() and str(value).strip().lower() not in {"nan", "none"}:
            return str(value).strip()
    return ""


def _number(row: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = row.get(key)
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(parsed):
            return parsed
    return None


def _truthy(row: Mapping[str, Any], *keys: str) -> bool:
    for key in keys:
        value = row.get(key)
        if isinstance(value, bool):
            return value
        if value is not None and str(value).strip().lower() in {"true", "1", "yes"}:
            return True
    return False


def _condition_sort_key(value: str) -> tuple[int, float, str]:
    label = str(value or "")
    lowered = label.lower()
    if lowered in {"control", "baseline", "0", "0min", "0 min"}:
        return (0, 0.0, lowered)
    match = re.search(r"[-+]?\d+(?:\.\d+)?", label)
    return (1, float(match.group(0)) if match else math.inf, lowered)


def _condition_rows(row: Mapping[str, Any]) -> list[dict]:
    condition_data = row.get("condition_data")
    if isinstance(condition_data, list) and condition_data:
        return [dict(item) for item in condition_data if isinstance(item, Mapping)]
    return [dict(row)]


def _source_rows(state: Mapping[str, Any]) -> list[dict]:
    vector = [dict(row) for row in state.get("vector_plot_raw_data") or [] if isinstance(row, Mapping)]
    if vector:
        return vector
    return [dict(row) for row in state.get("enriched_ptm_data") or [] if isinstance(row, Mapping)]


def _feature_key(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    gene = _text(row, "gene", "Gene.Name", "gene_name").upper()
    position = _text(row, "position", "PTM_Position", "site").upper()
    precursor = _text(row, "Precursor.Id", "precursor_id", "source_feature_id")
    sequence = _text(row, "Modified.Sequence", "modified_sequence")
    return gene, position, precursor, sequence


def _has_reader_identity(row: Mapping[str, Any]) -> bool:
    """Require a source feature identity before reader-facing aggregation."""
    explicit = row.get("identity_complete_for_reader_cards")
    if isinstance(explicit, bool):
        return explicit
    return bool(_text(row, "Precursor.Id", "precursor_id", "source_feature_id", "Modified.Sequence", "modified_sequence"))


def _group_feature_rows(rows: Iterable[Mapping[str, Any]]) -> list[tuple[tuple[str, str, str, str], list[dict]]]:
    grouped: dict[tuple[str, str, str, str], list[dict]] = defaultdict(list)
    for source in rows:
        row = _mapping(source)
        gene, position, precursor, sequence = _feature_key(row)
        if not gene or gene in {"?", "UNKNOWN", "UNMAPPED"}:
            continue
        if not _has_reader_identity(row):
            # A gene plus candidate-residue annotation is not a unique modified
            # precursor.  Preserve such rows for aggregate legacy summaries, but
            # do not synthesize a named feature card from them.
            continue
        key = (gene, position, precursor, sequence)
        for condition_row in _condition_rows(row):
            merged = {**row, **condition_row}
            grouped[key].append(merged)
    return sorted(grouped.items(), key=lambda item: item[0])


def _identity_complete_condition_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict] | None:
    """Return one identity-complete row per condition or withhold the group.

    Multiple rows for one `(modified precursor, condition)` can be genuine
    replicate/aggregation ambiguity.  It must carry an explicit aggregation
    contract before a future renderer may summarize it; Phase 2 reader cards do
    not silently select a subset or treat the array as a trajectory.
    """
    per_condition: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        per_condition[_condition_label(row)].append(dict(row))
    if any(len(items) != 1 for items in per_condition.values()):
        return None
    return [items[0] for _, items in sorted(per_condition.items(), key=lambda item: _condition_sort_key(item[0]))]


def _condition_value(row: Mapping[str, Any], axis: str) -> float | None:
    aliases = {
        "unadjusted": ("PTM_Unadjusted_Log2FC", "ptm_unadjusted_log2fc"),
        "adjusted": (
            "PTM_ProteinAdjusted_Log2FC",
            "ptm_protein_adjusted_log2fc",
            "PTM_Relative_Log2FC",
            "ptm_relative_log2fc",
        ),
        "protein": ("Protein_Log2FC", "protein_log2fc"),
        "reconstructed": (
            "PTM_Reconstructed_Log2FC",
            "ptm_reconstructed_log2fc",
            "PTM_Absolute_Log2FC",
            "ptm_absolute_log2fc",
        ),
        "q_value": ("PTM_Unadjusted_Q_Value", "ptm_unadjusted_q_value", "q_value"),
    }
    return _number(row, *aliases[axis])


def _condition_label(row: Mapping[str, Any]) -> str:
    return _text(row, "Condition", "condition", "Comparison") or "recorded condition"


def _display_label(key: tuple[str, str, str, str], measurement: Mapping[str, Any]) -> str:
    gene, position, _, _ = key
    reader_unit = str(measurement.get("reader_measurement_unit") or "")
    if reader_unit == "localized_ptm_site_feature" and position:
        return f"{gene} {position} localized phosphorylation feature"
    if position:
        return f"{gene} modified-precursor feature with candidate residue annotation {position}"
    return f"{gene} modified-precursor feature"


def _format_signed(value: float | None) -> str:
    return "not available" if value is None else f"{value:+.3f}"


def _trajectory_complexity(values: list[float]) -> tuple[int, int]:
    if not values:
        return (0, 0)
    signs = [1 if value > 0.25 else -1 if value < -0.25 else 0 for value in values]
    transitions = sum(left != right for left, right in zip(signs, signs[1:]))
    return len(set(signs)), transitions


def build_feature_observation_cards(
    state: Mapping[str, Any],
    *,
    maximum: int = 5,
) -> list[dict]:
    """Select named measured features by coverage and temporal-shape diversity.

    Selection never sorts by absolute fold-change magnitude.  A lexical tie-breaker
    is used after completeness and signed temporal-shape complexity.
    """
    candidates: list[dict] = []
    for key, rows in _group_feature_rows(_source_rows(state)):
        ordered = _identity_complete_condition_rows(rows)
        if ordered is None:
            continue
        first = ordered[0]
        measurement = _mapping(first.get("measurement_provenance")) or build_measurement_provenance(
            first,
            feature_id=_text(first, "Precursor.Id", "precursor_id") or None,
            member_feature_ids=[
                _text(row, "Precursor.Id", "precursor_id") for row in ordered
                if _text(row, "Precursor.Id", "precursor_id")
            ],
            aggregation_rule="reader_card_grouped_by_feature_identity_across_conditions",
        )
        points: list[dict] = []
        adjusted_values: list[float] = []
        de_novo_count = 0
        for row in ordered:
            condition = _condition_label(row)
            adjusted = _condition_value(row, "adjusted")
            unadjusted = _condition_value(row, "unadjusted")
            protein = _condition_value(row, "protein")
            de_novo = is_de_novo_representation(row) or _truthy(
                row,
                "PTM_Unadjusted_Conventional_Log2FC_NA",
                "ptm_unadjusted_conventional_log2fc_na",
            )
            if de_novo:
                de_novo_count += 1
            if adjusted is not None and not de_novo:
                adjusted_values.append(adjusted)
            points.append({
                "condition": condition,
                "ptm_unadjusted_log2fc": unadjusted,
                "ptm_protein_adjusted_log2fc": adjusted,
                "protein_log2fc": protein,
                "conventional_log2fc_available": not de_novo and unadjusted is not None,
                "detection_context_only": bool(de_novo),
            })
        numeric_points = sum(
            point["ptm_protein_adjusted_log2fc"] is not None or point["ptm_unadjusted_log2fc"] is not None
            for point in points
        )
        if numeric_points < 2:
            continue
        complexity = _trajectory_complexity(adjusted_values)
        candidates.append({
            "key": key,
            "measurement": measurement,
            "points": points,
            "numeric_point_count": numeric_points,
            "de_novo_count": de_novo_count,
            "shape_complexity": complexity,
        })

    candidates.sort(key=lambda item: (
        -item["numeric_point_count"],
        -item["shape_complexity"][0],
        -item["shape_complexity"][1],
        item["key"],
    ))
    selected: list[dict] = []
    seen_shapes: set[tuple[int, int]] = set()
    for candidate in candidates:
        if candidate["shape_complexity"] in seen_shapes and len(candidates) > maximum:
            continue
        selected.append(candidate)
        seen_shapes.add(candidate["shape_complexity"])
        if len(selected) >= maximum:
            break
    if len(selected) < min(maximum, len(candidates)):
        selected_keys = {item["key"] for item in selected}
        for candidate in candidates:
            if candidate["key"] in selected_keys:
                continue
            selected.append(candidate)
            if len(selected) >= maximum:
                break

    cards: list[dict] = []
    for index, candidate in enumerate(selected, 1):
        label = _display_label(candidate["key"], candidate["measurement"])
        fragments = []
        for point in candidate["points"][:8]:
            if point["detection_context_only"]:
                fragments.append(f"{point['condition']}: detected only as control-undetected/LOD context")
                continue
            values = []
            if point["ptm_unadjusted_log2fc"] is not None:
                values.append(f"unadjusted PTM {_format_signed(point['ptm_unadjusted_log2fc'])}")
            if point["ptm_protein_adjusted_log2fc"] is not None:
                values.append(f"protein-adjusted PTM {_format_signed(point['ptm_protein_adjusted_log2fc'])}")
            if point["protein_log2fc"] is not None:
                values.append(f"protein {_format_signed(point['protein_log2fc'])}")
            if values:
                fragments.append(f"{point['condition']}: " + ", ".join(values))
        evidence_id = f"feature.observation.{index}"
        envelope = build_evidence_envelope(
            observation_status=(
                ObservationStatus.observed_complete
                if candidate["numeric_point_count"] == len(candidate["points"])
                else ObservationStatus.observed_partial
            ),
            measurement_unit=str(candidate["measurement"].get("reader_measurement_unit") or "modified_precursor_feature"),
            value_ids=(evidence_id,),
            evaluation_status=EvaluationStatus.not_requested,
            reason_codes=("descriptive_current_order_feature_card",),
            outcome_class=OutcomeClass.unavailable,
            maximum_tier="O1",
            allowed_predicates=("was measured", "increased", "decreased", "showed a temporal profile"),
            forbidden_predicates=("was biologically prioritized", "was directly phosphorylated by", "activated"),
        )
        cards.append({
            "contract_version": FEATURE_OBSERVATION_CARD_VERSION,
            "card_id": evidence_id,
            "category": "measured_feature_observation",
            "reader_summary": f"{label} showed the following current-order measurements: " + "; ".join(fragments) + ".",
            "claim_tier": "O1",
            "evidence_ids": [evidence_id],
            "citation_ids": [],
            "allowed_verbs": ["was measured", "increased", "decreased", "showed"],
            "forbidden_interpretations": ["biological priority from magnitude", "direct kinase attribution", "causal activation"],
            "counterevidence": (
                "These are measured numeric contrasts. Magnitude alone does not establish biological priority, "
                "mechanistic importance, direct regulatory strength, occupancy, or causality."
            ),
            "feature_label": label,
            "feature_identity": {
                "gene": candidate["key"][0],
                "candidate_residue_annotation": candidate["key"][1] or None,
                "source_feature_id": candidate["key"][2] or None,
                "modified_sequence": candidate["key"][3] or None,
                "condition_identity_status": "unique_per_feature_condition",
            },
            "measurement_provenance": candidate["measurement"],
            "trajectory": candidate["points"],
            "selection_rule": "condition coverage; signed temporal-shape diversity; lexical tie-breaker; no magnitude ranking",
            "evidence_envelope": envelope,
        })
    return cards


def _comparison_class(unadjusted: float, adjusted: float, *, tolerance: float = 0.15) -> str:
    if unadjusted * adjusted < 0 and abs(unadjusted) > tolerance and abs(adjusted) > tolerance:
        return "direction_changed_after_protein_adjustment"
    magnitude_delta = abs(adjusted) - abs(unadjusted)
    if magnitude_delta < -tolerance:
        return "attenuated_after_protein_adjustment"
    if magnitude_delta > tolerance:
        return "amplified_after_protein_adjustment"
    return "similar_after_protein_adjustment"


def build_quantitation_comparison_cards(
    state: Mapping[str, Any],
    *,
    maximum: int = 8,
) -> list[dict]:
    """Build matched independent-unadjusted versus protein-adjusted comparisons."""
    rows: list[dict] = []
    for key, grouped_rows in _group_feature_rows(_source_rows(state)):
        unique_rows = _identity_complete_condition_rows(grouped_rows)
        if unique_rows is None:
            continue
        for row in unique_rows:
            if is_de_novo_representation(row) or _truthy(
                row,
                "PTM_Unadjusted_Conventional_Log2FC_NA",
                "ptm_unadjusted_conventional_log2fc_na",
            ):
                continue
            unadjusted = _condition_value(row, "unadjusted")
            adjusted = _condition_value(row, "adjusted")
            protein = _condition_value(row, "protein")
            if unadjusted is None or adjusted is None or protein is None:
                continue
            measurement = _mapping(row.get("measurement_provenance")) or build_measurement_provenance(
                row,
                feature_id=_text(row, "Precursor.Id", "precursor_id") or None,
                aggregation_rule="single_feature_condition_quantitation_comparison",
            )
            rows.append({
                "key": key,
                "condition": _condition_label(row),
                "unadjusted": unadjusted,
                "adjusted": adjusted,
                "protein": protein,
                "reconstructed": _condition_value(row, "reconstructed"),
                "delta": adjusted - unadjusted,
                "comparison_class": _comparison_class(unadjusted, adjusted),
                "measurement": measurement,
            })

    class_order = {
        "direction_changed_after_protein_adjustment": 0,
        "attenuated_after_protein_adjustment": 1,
        "amplified_after_protein_adjustment": 2,
        "similar_after_protein_adjustment": 3,
    }
    rows.sort(key=lambda row: (
        class_order.get(row["comparison_class"], 99),
        row["key"],
        _condition_sort_key(row["condition"]),
    ))
    selected: list[dict] = []
    seen_classes: set[str] = set()
    for row in rows:
        if row["comparison_class"] in seen_classes:
            continue
        selected.append(row)
        seen_classes.add(row["comparison_class"])
        if len(selected) >= maximum:
            break
    if len(selected) < min(maximum, len(rows)):
        selected_keys = {(row["key"], row["condition"]) for row in selected}
        for row in rows:
            if (row["key"], row["condition"]) in selected_keys:
                continue
            selected.append(row)
            if len(selected) >= maximum:
                break

    cards: list[dict] = []
    for index, row in enumerate(selected, 1):
        label = _display_label(row["key"], row["measurement"])
        evidence_id = f"quantitation.comparison.{index}"
        cards.append({
            "contract_version": QUANTITATION_COMPARISON_CARD_VERSION,
            "card_id": evidence_id,
            "category": "quantitation_comparison",
            "reader_summary": (
                f"For {label} at {row['condition']}, the independently calculated unadjusted PTM contrast was "
                f"{_format_signed(row['unadjusted'])}, the protein-adjusted PTM contrast was "
                f"{_format_signed(row['adjusted'])}, and the linked protein contrast was "
                f"{_format_signed(row['protein'])}; this was classified descriptively as "
                f"{row['comparison_class'].replace('_', ' ')}."
            ),
            "claim_tier": "O1",
            "evidence_ids": [evidence_id],
            "citation_ids": [],
            "allowed_verbs": ["differed from", "was attenuated", "was amplified", "changed direction"],
            "forbidden_interpretations": ["proved correction", "improved truth", "absolute occupancy", "kinase activity"],
            "counterevidence": (
                "This arithmetic comparison describes how protein adjustment changed the reported contrast. "
                "It does not prove that the adjusted value is biologically truer. The legacy reconstructed value is excluded."
            ),
            "feature_label": label,
            "feature_identity": {
                "gene": row["key"][0],
                "candidate_residue_annotation": row["key"][1] or None,
                "source_feature_id": row["key"][2] or None,
                "modified_sequence": row["key"][3] or None,
                "condition_identity_status": "unique_per_feature_condition",
            },
            "condition": row["condition"],
            "ptm_unadjusted_log2fc": row["unadjusted"],
            "ptm_protein_adjusted_log2fc": row["adjusted"],
            "protein_log2fc": row["protein"],
            "protein_adjustment_delta_log2fc": row["delta"],
            "comparison_class": row["comparison_class"],
            "reconstructed_metric_excluded_from_comparison": True,
            "reconstructed_value_for_audit_only": row["reconstructed"],
            "selection_rule": "matched conventional axes; comparison-class diversity; lexical tie-breaker; no magnitude ranking",
            "measurement_provenance": row["measurement"],
        })
    return cards
