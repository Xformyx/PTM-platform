"""Reader-safe current-order feature and quantitation comparison cards.

This module translates measured vector rows into bounded scientific-authoring
records.  It never queries literature, assigns kinases, or promotes magnitude to
biological priority.  Independent unadjusted PTM contrasts are kept distinct
from protein-adjusted and legacy reconstructed values.
"""

from __future__ import annotations

import math
import re
import hashlib
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
from report_generation.core.scientific_semantics import build_trajectory_shape_fact
from .quantitative_fields import axis_number, axis_support, axis_evidence, QUANTITATIVE_SCHEMA_VERSION
from .temporal_analysis import observed_time_minutes, summarize_observed_pattern, joint_axis_pattern


FEATURE_OBSERVATION_CARD_VERSION = "feature_observation_card.v3"
QUANTITATION_COMPARISON_CARD_VERSION = "quantitation_comparison_card.v3"


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
    minutes = observed_time_minutes({"condition": label})
    return (1, minutes if minutes is not None else math.inf, lowered)


def _condition_rows(row: Mapping[str, Any]) -> list[dict]:
    condition_data = row.get("condition_data")
    if isinstance(condition_data, list) and condition_data:
        return [dict(item) for item in condition_data if isinstance(item, Mapping)]
    return [dict(row)]


def _source_rows(state: Mapping[str, Any]) -> list[dict]:
    vector = [dict(row) for row in state.get("vector_plot_raw_data") or [] if isinstance(row, Mapping)]
    if vector:
        return vector
    enriched: list[dict] = []
    for row in state.get("enriched_ptm_data") or []:
        if not isinstance(row, Mapping):
            continue
        if row.get("site_form_trajectories") or row.get("site_aggregation"):
            audit = _mapping(row.get("site_form_provenance_audit"))
            if audit.get("status") != "validated" or not bool(
                row.get("report_eligible_temporal_site_aggregation", audit.get("report_eligible"))
            ):
                continue
        enriched.append(dict(row))
    return enriched


from ptm_shared.feature_identity import (
    FIELDS,
    assign_local_disambiguators,
    canonical_feature_identity,
    feature_key as _feature_key,
    project_reader_display_identity,
    reader_id,
    technical_crosswalk_reference,
)


def reader_feature_id(key):
    return reader_id(key)


def _has_reader_identity(row):
    return canonical_feature_identity(row)["identity_complete_for_reader_cards"]


def _group_feature_rows(rows: Iterable[Mapping[str, Any]]) -> list[tuple[tuple[str, str, str, str], list[dict]]]:
    grouped: dict[tuple[str, str, str, str], list[dict]] = defaultdict(list)
    for source in rows:
        row = _mapping(source)
        gene, position, precursor, sequence = _feature_key(row)[:4]
        if not gene or gene in {"?", "UNKNOWN", "UNMAPPED"}:
            continue
        if not _has_reader_identity(row):
            # A gene plus candidate-residue annotation is not a unique modified
            # precursor.  Preserve such rows for aggregate legacy summaries, but
            # do not synthesize a named feature card from them.
            continue
        for condition_row in _condition_rows(row):
            merged = {**row, **condition_row}
            merged_key = _feature_key(merged)
            if not _has_reader_identity(merged):
                continue
            if not merged_key[0] or merged_key[0] in {"?", "UNKNOWN", "UNMAPPED"}:
                continue
            grouped[merged_key].append(merged)
    return sorted(grouped.items(), key=lambda item: item[0])


def _identity_complete_condition_rows(rows: Iterable[Mapping[str, Any]], *, allow_partial_conflicts=False) -> list[dict] | None:
    """Return one identity-complete row per condition or withhold the group.

    Multiple rows for one `(modified precursor, condition)` can be genuine
    replicate/aggregation ambiguity.  It must carry an explicit aggregation
    contract before a future renderer may summarize it; Phase 2 reader cards do
    not silently select a subset or treat the array as a trajectory.
    """
    per_condition: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if dict(row) not in per_condition[_condition_label(row)]:
            per_condition[_condition_label(row)].append(dict(row))
    for condition, items in per_condition.items():
        if len(items) > 1:
            if not allow_partial_conflicts:
                return None
            missing = {**dict(zip(FIELDS, _feature_key(items[0]))), "condition": condition,
                       "condition_identity_status": "conflicting_feature_condition"}
            for prefix in ("ptm_unadjusted", "ptm_protein_adjusted", "protein"):
                missing[f"{prefix}_log2fc"] = None
                missing[f"{prefix}_missing_reason"] = "conflicting_feature_condition"
            per_condition[condition] = [missing]
    return [items[0] for _, items in sorted(per_condition.items(), key=lambda item: _condition_sort_key(item[0]))]


def _condition_value(row: Mapping[str, Any], axis: str) -> float | None:
    return axis_number(row, axis, "value")


def _condition_label(row: Mapping[str, Any]) -> str:
    return _text(row, "Condition", "condition", "Comparison") or "recorded condition"


def _display_label(
    key: tuple[str, str, str, str],
    measurement: Mapping[str, Any],
    *,
    disambiguator: str | None = None,
) -> str:
    return project_reader_display_identity(
        {"gene": key[0], "position": key[1]},
        reader_measurement_unit=measurement.get("reader_measurement_unit"),
        disambiguator=disambiguator,
    )


def _attach_display_identity(identity: Mapping[str, Any], measurement: Mapping[str, Any], *, disambiguator: str | None = None) -> dict:
    record = dict(identity or {})
    record["reader_disambiguator"] = disambiguator
    record["reader_display_identity"] = project_reader_display_identity(
        record,
        reader_measurement_unit=(measurement or {}).get("reader_measurement_unit"),
        disambiguator=disambiguator,
        gene_ambiguous=not record.get("main_named_finding_eligible", True),
    )
    record["technical_crosswalk_reference"] = technical_crosswalk_reference(record)
    return record


def _format_signed(value: float | None) -> str:
    return "not available" if value is None else f"{value:+.3f}"


def _trajectory_complexity(values: list[float]) -> tuple[int, int]:
    if not values:
        return (0, 0)
    signs = [1 if value > 0.25 else -1 if value < -0.25 else 0 for value in values]
    transitions = sum(left != right for left, right in zip(signs, signs[1:]))
    return len(set(signs)), transitions


def _point_quality(row: Mapping[str, Any], *, conventional_available: bool, sample_manifest=None) -> dict[str, Any]:
    support = axis_support(row)
    axes = {}
    for axis in ("unadjusted", "protein_adjusted", "protein"):
        replicate = all(support[f"{axis}_{group}_n"] is not None and support[f"{axis}_{group}_n"] >= 2
                        for group in ("control", "treatment"))
        evidence = axis_evidence(row, "adjusted" if axis == "protein_adjusted" else axis, sample_manifest)
        biological_n = [evidence[f"{group}_biological_n"] for group in ("control", "treatment")]
        biological_supported = all(n is not None and n >= 2 for n in biological_n)
        technical_supported = replicate
        if sample_manifest and sample_manifest.get("samples"):
            replicate = biological_supported
        q = support[f"{axis}_q_value"]
        axes[axis] = {"biological_supported": biological_supported, "biological_n": biological_n,
                      "technical_precision_supported": technical_supported,
                      "test_unit_matches_support": (not (sample_manifest and sample_manifest.get("samples"))
                                                     or evidence.get("statistical_unit") == "biological_unit"),
                      "support_scope": "biological_units" if sample_manifest and sample_manifest.get("samples") else "sample_observations_design_unavailable",
                      "replicate_supported": bool(conventional_available and replicate),
                      "q_supported": bool(conventional_available and q is not None and 0 <= q < .05)}
    ptm_axes = [axes[axis] for axis in ("unadjusted", "protein_adjusted")]
    return {**support, "axis_support": axes,
            "replicate_supported": any(item["replicate_supported"] for item in ptm_axes),
            "q_supported": any(item["q_supported"] for item in ptm_axes),
            "matched_axis_support": any(item["replicate_supported"] and item["q_supported"] and item["test_unit_matches_support"] for item in ptm_axes)}


def _comparison_quality_tier(quality: Mapping[str, Any]) -> str:
    """Rank one feature-condition; this is support, not a test of adjustment."""
    if quality["matched_axis_support"]:
        return "high"
    if quality["replicate_supported"]:
        return "moderate"
    return "exploratory"


def _narrative_quality_tier(points: Iterable[Mapping[str, Any]]) -> tuple[str, dict[str, int]]:
    point_list = list(points)
    conventional_count = sum(bool(point.get("conventional_log2fc_available")) for point in point_list)
    replicate_supported_count = sum(bool(_mapping(point.get("quality")).get("replicate_supported")) for point in point_list)
    q_supported_count = sum(bool(_mapping(point.get("quality")).get("q_supported")) for point in point_list)
    matched_axis_count = sum(bool(_mapping(point.get("quality")).get("matched_axis_support")) for point in point_list)
    if conventional_count >= 2 and replicate_supported_count >= 2 and matched_axis_count >= 1:
        tier = "high"
    elif conventional_count >= 2 and replicate_supported_count >= 1:
        tier = "moderate"
    else:
        tier = "exploratory"
    return tier, {
        "conventional_point_count": conventional_count,
        "replicate_supported_point_count": replicate_supported_count,
        "q_supported_point_count": q_supported_count,
    }


def build_feature_observation_cards(
    state: Mapping[str, Any],
    *,
    maximum: int = 5,
    minimum_points: int = 2,
) -> list[dict]:
    """Select named measured features by coverage and temporal-shape diversity.

    Selection never sorts by absolute fold-change magnitude.  A lexical tie-breaker
    is used after completeness and signed temporal-shape complexity.
    """
    candidates: list[dict] = []
    grouped_features = _group_feature_rows(_source_rows(state))
    observed_conditions = sorted({
        _condition_label(row)
        for _, rows in grouped_features
        for row in rows
    }, key=_condition_sort_key)
    design_conditions = (state.get("sample_manifest") or {}).get("conditions") or []
    declared = [str(d["condition"]) for d in design_conditions if isinstance(d, Mapping) and d.get("condition")]
    grid_source = "sample_manifest" if declared else "observed_execution_conditions"
    observed_conditions = sorted(set(observed_conditions) | set(declared), key=_condition_sort_key)
    for key, rows in grouped_features:
        ordered = _identity_complete_condition_rows(rows, allow_partial_conflicts=True)
        if ordered is None:
            continue
        first = ordered[0]
        present_conditions = {_condition_label(row) for row in ordered}
        for condition in observed_conditions:
            if condition not in present_conditions:
                missing = {**dict(zip(FIELDS, key)), "condition": condition, "observation_status": "unavailable"}
                for prefix in ("ptm_unadjusted", "ptm_protein_adjusted", "protein"):
                    missing[f"{prefix}_log2fc"] = None
                    missing[f"{prefix}_missing_reason"] = "feature_condition_unavailable"
                ordered.append(missing)

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
            design_conditions = (state.get("sample_manifest") or {}).get("conditions") or []
            recorded_design = next((d for d in design_conditions if isinstance(d, Mapping) and d.get("condition") == condition), {})
            time_source = {**recorded_design, **row, "condition": condition}
            # Projection's absent optional field must not hide an explicit design time.
            if time_source.get("time_minutes") is None and recorded_design.get("time_minutes") is not None:
                time_source["time_minutes"] = recorded_design["time_minutes"]
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
            conventional_available = not de_novo and unadjusted is not None
            axes = {axis: axis_evidence(row, axis, state.get("sample_manifest") or {}) for axis in ("unadjusted", "protein", "adjusted")}
            if de_novo:
                for axis in ("unadjusted", "adjusted"):
                    axes[axis].update(value=None, available=False, missing_reason="detection_context_only")
            support_sets = [tuple(axes[axis].get(f"{group}_sample_ids") or ()) for axis in axes for group in ("control", "treatment")]
            points.append({
                "condition": condition,
                "time_minutes": observed_time_minutes(time_source),
                "reference_id": row.get("reference_id") or recorded_design.get("reference_id"),
                "axes": axes,
                "joint_pattern": joint_axis_pattern(axes, tolerance=float(state.get("pattern_tolerance", .15))),
                "support_sets_differ": any(
                    axes["unadjusted"].get(f"{group}_sample_ids") != axes["adjusted"].get(f"{group}_sample_ids")
                    for group in ("control", "treatment")
                    if axes["unadjusted"].get(f"{group}_sample_ids") is not None and axes["adjusted"].get(f"{group}_sample_ids") is not None
                ),
                "support_set_status": "recorded" if all(support_sets) else "partially_or_not_recorded",
                "common_sample_sensitivity": {"status": "not_computed", "reason": "replicate_level_reanalysis_required"},
                "denominator_qc": {key: row.get(key) for key in ("protein_denominator_qc", "low_denominator", "qc_flags") if key in row},
                "measurement_provenance": _mapping(row.get("measurement_provenance")) or build_measurement_provenance(row),
                "ptm_unadjusted_log2fc": unadjusted,
                "ptm_protein_adjusted_log2fc": adjusted,
                "protein_log2fc": protein,
                "conventional_log2fc_available": conventional_available,
                "detection_context_only": bool(de_novo),
                "quality": _point_quality(row, conventional_available=conventional_available, sample_manifest=state.get("sample_manifest")),
            })
        points.sort(key=lambda p: (p["time_minutes"] if p["time_minutes"] is not None else math.inf, p["condition"]))
        adjusted_values = [p["ptm_protein_adjusted_log2fc"] for p in points if p["ptm_protein_adjusted_log2fc"] is not None and not p["detection_context_only"]]
        numeric_points = sum(
            point["ptm_protein_adjusted_log2fc"] is not None or point["ptm_unadjusted_log2fc"] is not None
            for point in points
        )
        if numeric_points < minimum_points:
            continue
        complexity = _trajectory_complexity(adjusted_values)
        quality_tier, quality_counts = _narrative_quality_tier(points)
        candidate_conditions = {point["condition"] for point in points}
        candidates.append({
            "key": key,
            "measurement": measurement,
            "mapping_identity": {**canonical_feature_identity(first), "accession": first.get("accession")},
            "parent_protein_ids": sorted({_text(row, "Protein.Group", "protein_group") for row in ordered if _text(row, "Protein.Group", "protein_group")}),
            "points": points,
            "numeric_point_count": numeric_points,
            "de_novo_count": de_novo_count,
            "shape_complexity": complexity,
            "narrative_quality_tier": quality_tier,
            "quality_counts": quality_counts,
            "display_eligible": True,
            "clustering_eligible": bool(
                observed_conditions
                and candidate_conditions == set(observed_conditions)
                and all(point["conventional_log2fc_available"] for point in points)
            ),
        })

    quality_order = {"high": 0, "moderate": 1, "exploratory": 2}
    candidates.sort(key=lambda item: (
        quality_order.get(item["narrative_quality_tier"], 99),
        -item["quality_counts"]["q_supported_point_count"],
        -item["quality_counts"]["replicate_supported_point_count"],
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

    disambiguated = assign_local_disambiguators([
        {
            **candidate["mapping_identity"],
            "gene": candidate["key"][0],
            "position": candidate["key"][1],
            "candidate_residue_annotation": candidate["key"][1] or None,
            "precursor_id": candidate["key"][2],
            "modified_sequence": candidate["key"][3],
            "reader_feature_id": reader_feature_id(candidate["key"]),
        }
        for candidate in selected
    ])
    for candidate, identity in zip(selected, disambiguated):
        candidate["reader_disambiguator"] = identity.get("reader_disambiguator")

    cards: list[dict] = []
    for index, candidate in enumerate(selected, 1):
        label = _display_label(
            candidate["key"],
            candidate["measurement"],
            disambiguator=candidate.get("reader_disambiguator"),
        )
        feature_id = reader_feature_id(candidate["key"])
        trajectory_fact = build_trajectory_shape_fact(candidate["points"])
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
            "quantitative_schema_version": QUANTITATIVE_SCHEMA_VERSION,
            "card_id": evidence_id,
            "category": "measured_feature_observation",
            "reader_summary": (
                f"{label} showed the following current-order measurements: " + "; ".join(fragments) + ". "
                + str(trajectory_fact.get("reader_summary") or "")
            ).strip(),
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
            "feature_identity": _attach_display_identity(
                {
                    **candidate["mapping_identity"],
                    "reader_feature_id": feature_id,
                    "gene": candidate["key"][0],
                    "candidate_residue_annotation": candidate["key"][1] or None,
                    "source_feature_id": candidate["key"][2] or None,
                    "modified_sequence": candidate["key"][3] or None,
                    "condition_identity_status": "unique_per_feature_condition",
                },
                candidate["measurement"],
                disambiguator=candidate.get("reader_disambiguator"),
            ),
            "measurement_provenance": candidate["measurement"],
            "trajectory": candidate["points"],
            "axis_patterns": {axis: summarize_observed_pattern(
                [{**point, "pattern_value": point["axes"][axis]["value"]} for point in candidate["points"]], value_key="pattern_value")
                for axis in ("unadjusted", "protein", "adjusted")},
            "parent_protein_ids": candidate["parent_protein_ids"],
            "trajectory_shape_fact": trajectory_fact,
            "display_eligible": candidate["display_eligible"],
            "clustering_eligible": candidate["clustering_eligible"],
            "condition_grid": {"conditions": observed_conditions, "source": grid_source},
            "narrative_quality_tier": candidate["narrative_quality_tier"],
            "quality_summary": candidate["quality_counts"],
            "selection_rule": "identity completeness; replicate/q-value support; observed condition coverage; signed temporal-shape diversity; lexical tie-breaker; no magnitude ranking",
            "evidence_envelope": envelope,
        })
    return cards


def select_finding_cards(cards: Iterable[Mapping[str, Any]], *, maximum: int = 4) -> tuple[list[dict], dict]:
    """Freeze descriptive findings using quality, parent and pattern diversity.

    A parent or repeated control is a dependency, never an independent replicate.
    No canonical/unknown quota and no magnitude-only priority is imposed.
    """
    unique: dict[str, dict] = {}
    excluded = []
    for source in cards:
        card = dict(source)
        fid = str(_mapping(card.get("feature_identity")).get("reader_feature_id") or "")
        eligible = any(any(_mapping(point.get("axes")).get(axis, {}).get("available")
                           for axis in ("unadjusted", "adjusted")) for point in card.get("trajectory") or [])
        if not fid or not eligible:
            excluded.append({"card_id": card.get("card_id"), "reason": "no_bound_numeric_observation"})
            continue
        if fid in unique:
            existing = unique[fid]
            primary, extra = (
                (card, existing)
                if card.get("category") == "measured_feature_observation"
                and existing.get("category") != "measured_feature_observation"
                else (existing, card)
            )
            primary = dict(primary)
            primary["evidence_ids"] = sorted(set(primary.get("evidence_ids", []) + extra.get("evidence_ids", [])))
            primary["question_ids"] = sorted(set(primary.get("question_ids", []) + extra.get("question_ids", [])))
            unique[fid] = primary
            continue
        unique[fid] = card
    selected = []
    parents_seen: set[str] = set()
    patterns_seen: set[tuple] = set()

    def parents(card):
        return set(card.get("parent_protein_ids") or [str(_mapping(card.get("feature_identity")).get("gene") or "unknown_parent")])

    def pattern(card):
        joint = tuple(sorted({str(p.get("joint_pattern")) for p in card.get("trajectory") or []}))
        temporal = tuple((axis, summary.get("label"), tuple((p.get("time_minutes"), p.get("kind")) for p in summary.get("observed_extrema") or []))
                         for axis, summary in sorted((card.get("axis_patterns") or {}).items()))
        return joint, temporal

    def priority(item):
        fid, card = item
        quality = _mapping(card.get("quality_summary"))
        return ({"high": 0, "moderate": 1, "exploratory": 2}.get(card.get("narrative_quality_tier"), 3),
                not bool(card.get("question_ids")),
                bool(parents(card) & parents_seen), pattern(card) in patterns_seen,
                -int(quality.get("q_supported_point_count") or 0),
                -int(quality.get("replicate_supported_point_count") or 0),
                fid)

    remaining = dict(unique)
    while remaining and len(selected) < maximum:
        fid, card = min(remaining.items(), key=priority)
        selected.append(card)
        parents_seen.update(parents(card))
        patterns_seen.add(pattern(card))
        del remaining[fid]
    excluded.extend({"reader_feature_id": fid, "reason": "quality_parent_pattern_diversity_capacity"} for fid in sorted(remaining))
    return selected, {"contract_version": "report_finding_selection.v3", "input_unique_feature_count": len(unique),
                      "selected_count": len(selected), "selected_reader_feature_ids": [c["feature_identity"]["reader_feature_id"] for c in selected],
                      "parent_count": len(parents_seen), "independent_sample_count": None,
                      "rule": "quality_then_question_relevance_parent_and_observed_temporal_diversity_then_point_support_and_stable_feature_id",
                      "exclusions": excluded}


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
                "protein_group": _text(row, "Protein.Group", "protein_group", "protein_accession"),
                "quality": _point_quality(row, conventional_available=True, sample_manifest=state.get("sample_manifest")),
                **axis_support(row),
                "adjusted_q_value": axis_number(row, "adjusted", "q"),
                "adjusted_p_value": axis_number(row, "adjusted", "p"),
                "narrative_quality_tier": _comparison_quality_tier(_point_quality(row, conventional_available=True, sample_manifest=state.get("sample_manifest"))),
            })

    shared_protein_counts: dict[tuple[str, str, float], int] = defaultdict(int)
    for row in rows:
        shared_protein_counts[(row["protein_group"], row["condition"], round(row["protein"], 9))] += 1

    class_order = {
        "direction_changed_after_protein_adjustment": 0,
        "attenuated_after_protein_adjustment": 1,
        "amplified_after_protein_adjustment": 2,
        "similar_after_protein_adjustment": 3,
    }
    rows.sort(key=lambda row: (
        {"high": 0, "moderate": 1, "exploratory": 2}.get(row["narrative_quality_tier"], 99),
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
    comparison_labels = {
        "direction_changed_after_protein_adjustment": "a direction change outside the ±0.15 descriptive tolerance",
        "attenuated_after_protein_adjustment": "attenuation beyond the ±0.15 descriptive tolerance",
        "amplified_after_protein_adjustment": "amplification beyond the ±0.15 descriptive tolerance",
        "similar_after_protein_adjustment": "similar magnitude within the ±0.15 descriptive tolerance, irrespective of a small numerical sign difference",
    }
    allowed_verbs = {
        "direction_changed_after_protein_adjustment": ["differed from", "changed direction outside the descriptive tolerance"],
        "attenuated_after_protein_adjustment": ["differed from", "was attenuated beyond the descriptive tolerance"],
        "amplified_after_protein_adjustment": ["differed from", "was amplified beyond the descriptive tolerance"],
        "similar_after_protein_adjustment": ["differed numerically from", "remained similar within the descriptive tolerance"],
    }
    disambiguated = assign_local_disambiguators([
        {
            "gene": row["key"][0],
            "position": row["key"][1],
            "candidate_residue_annotation": row["key"][1] or None,
            "precursor_id": row["key"][2],
            "modified_sequence": row["key"][3],
            "reader_feature_id": reader_feature_id(row["key"]),
            "feature_id": reader_feature_id(row["key"]),
        }
        for row in selected
    ])
    for row, identity in zip(selected, disambiguated):
        row["reader_disambiguator"] = identity.get("reader_disambiguator")

    for index, row in enumerate(selected, 1):
        label = _display_label(row["key"], row["measurement"], disambiguator=row.get("reader_disambiguator"))
        feature_id = reader_feature_id(row["key"])
        evidence_id = f"quantitation.comparison.{index}"
        cards.append({
            "contract_version": QUANTITATION_COMPARISON_CARD_VERSION,
            "quantitative_schema_version": QUANTITATIVE_SCHEMA_VERSION,
            "card_id": evidence_id,
            "category": "quantitation_comparison",
            "reader_summary": (
                f"For {label} at {row['condition']}, the independently calculated unadjusted PTM contrast was "
                f"{_format_signed(row['unadjusted'])}, the protein-adjusted PTM contrast was "
                f"{_format_signed(row['adjusted'])}; this was classified descriptively as "
                f"{comparison_labels[row['comparison_class']]}. "
                "The linked total-protein measurement is retained as denominator and quantitation-validity context, "
                "not as a separate biological-response finding."
            ),
            "claim_tier": "O1",
            "evidence_ids": [evidence_id],
            "citation_ids": [],
            "allowed_verbs": allowed_verbs[row["comparison_class"]],
            "forbidden_interpretations": ["proved correction", "improved truth", "absolute occupancy", "kinase activity", "independent protein-response storyline"],
            "counterevidence": (
                "This arithmetic comparison describes how denominator adjustment changed the reported PTM contrast. "
                "It does not prove that the adjusted value is biologically truer. The legacy reconstructed value is excluded."
            ),
            "feature_label": label,
            "feature_identity": _attach_display_identity(
                {
                    **canonical_feature_identity(dict(zip(FIELDS, row["key"]))),
                    "reader_feature_id": feature_id,
                    "gene": row["key"][0],
                    "candidate_residue_annotation": row["key"][1] or None,
                    "source_feature_id": row["key"][2] or None,
                    "modified_sequence": row["key"][3] or None,
                    "condition_identity_status": "unique_per_feature_condition",
                },
                row["measurement"],
                disambiguator=row.get("reader_disambiguator"),
            ),
            "condition": row["condition"],
            "ptm_unadjusted_log2fc": row["unadjusted"],
            "ptm_protein_adjusted_log2fc": row["adjusted"],
            "protein_log2fc": row["protein"],
            "protein_adjustment_delta_log2fc": row["delta"],
            "comparison_class": row["comparison_class"],
            "comparison_tolerance_log2": 0.15,
            "replicate_support": {key: value for key, value in row["quality"].items() if key.endswith("_n")},
            "statistical_support": {key: value for key, value in row["quality"].items() if key.endswith(("_p_value", "_q_value"))},
            "axis_support": row["quality"]["axis_support"],
            "quality_evaluation_unit": "single_feature_condition",
            "adjustment_effect_tested": False,
            "unadjusted_q_value": row["unadjusted_q_value"],
            "adjusted_q_value": row["adjusted_q_value"],
            "uncertainty_available": bool(row["unadjusted_q_value"] is not None or row["adjusted_q_value"] is not None),
            "display_eligible": True,
            "clustering_eligible": False,
            "narrative_quality_tier": row["narrative_quality_tier"],
            "biological_direction_inference_allowed": False,
            "shared_linked_protein_record_count": shared_protein_counts[(row["protein_group"], row["condition"], round(row["protein"], 9))],
            "reconstructed_metric_excluded_from_comparison": True,
            "reconstructed_value_for_audit_only": row["reconstructed"],
            "selection_rule": "matched conventional axes; replicate/q-value support; comparison-class diversity; lexical tie-breaker; no magnitude ranking",
            "measurement_provenance": row["measurement"],
        })
    return cards
