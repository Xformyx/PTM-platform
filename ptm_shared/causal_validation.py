"""Post-analysis validation proposals and optional perturbation-evidence review.

This module is deliberately downstream of discovery.  It never changes Wave
membership, kinase scoring, or temporal directionality.  It can recommend a
small number of experiments for D2/D3 relationships and, only after a user
uploads a normalized follow-up dataset, mark an individual relationship as
perturbation-supported.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Mapping


ELIGIBLE_TIERS = {"D2_reproducible_directionality", "D3_mechanistically_supported_directionality"}


def _as_float(value: Any, default: float | None = None) -> float | None:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


def relationship_key(relationship: Mapping[str, Any]) -> str:
    source = relationship.get("source") or relationship.get("ptm_key") or relationship.get("ptm_substrate") or "unknown"
    target = relationship.get("target") or relationship.get("effector") or relationship.get("gene") or "unknown"
    if isinstance(source, Mapping):
        source = source.get("key", "unknown")
    if isinstance(target, Mapping):
        target = target.get("key", "unknown")
    return f"{source}->{target}"


def collect_directionality_relationships(signal_propagation: Mapping[str, Any] | None) -> List[Dict[str, Any]]:
    """Normalize directionality records persisted by the timeline builder."""
    source = signal_propagation or {}
    relationships: List[Dict[str, Any]] = []
    for record in list(source.get("self_timelags") or []) + list(source.get("cascade_timelags") or []):
        relation = dict(record.get("directionality") or {})
        if not relation:
            continue
        relation.setdefault("source", {"key": record.get("ptm_key") or record.get("ptm_substrate") or "unknown"})
        relation.setdefault("target", {"key": record.get("effector") or f"{record.get('gene', 'unknown')} protein abundance"})
        relation.setdefault("directionality_tier", record.get("directionality_tier", "D0_unresolved"))
        relation.setdefault("causality_status", record.get("causality_status", "not_tested"))
        relation["relationship_id"] = relationship_key(relation)
        relationships.append(relation)
    return relationships


def propose_causal_validation_experiments(
    relationships: Iterable[Mapping[str, Any]],
    *,
    maximum_recommendations: int = 5,
) -> Dict[str, Any]:
    """Recommend follow-up experiments only for high-quality observed candidates.

    Recommendations avoid naming an inhibitor or predicting a discovery result.
    They specify what should be measured and the decision rule needed to test the
    temporal hypothesis while keeping the original time-course unbiased.
    """
    candidates = [
        dict(item) for item in relationships
        if item.get("directionality_tier") in ELIGIBLE_TIERS
        and item.get("direction") == "source_precedes_target"
        and item.get("causality_status", "not_tested") == "not_tested"
    ]
    candidates.sort(
        key=lambda item: (
            0 if item.get("directionality_tier") == "D3_mechanistically_supported_directionality" else 1,
            -(float(item.get("temporal_order_score") or 0)),
        )
    )
    recommendations: List[Dict[str, Any]] = []
    for relation in candidates[:max(0, maximum_recommendations)]:
        source = relationship_key({"source": relation.get("source"), "target": {"key": ""}}).rstrip("->")
        target = relationship_key({"source": {"key": ""}, "target": relation.get("target")}).lstrip("->")
        onset_lag = relation.get("onset_lag_minutes")
        peak_lag = relation.get("peak_lag_minutes")
        windows = sorted({value for value in [relation.get("source_onset_minutes"), relation.get("target_onset_minutes"), relation.get("source_peak_minutes"), relation.get("target_peak_minutes")] if value is not None})
        recommendations.append({
            "relationship_id": relationship_key(relation),
            "directionality_tier": relation.get("directionality_tier"),
            "hypothesis_boundary": "Observational temporal precedence only; causal status is not tested.",
            "source": source,
            "target": target,
            "recommended_design": {
                "primary_assay": "Targeted time-resolved phosphosite/protein quantification",
                "optional_intervention": f"If independently justified, perturb {source} using a selective genetic or pharmacological strategy and measure {target} alongside matched vehicle/control samples.",
                "time_windows_minutes": windows,
                "decision_rule": "Classify as perturbation-supported only if a preregistered expected downstream change is observed with the supplied statistical threshold; otherwise retain not_tested or unsupported.",
                "negative_controls": "Include matched vehicle/control, intervention-only viability assessment, and a time-matched unrelated pathway readout.",
            },
            "observed_timing": {"onset_lag_minutes": onset_lag, "peak_lag_minutes": peak_lag},
        })
    return {
        "analysis_scope": "post_analysis_causal_validation_proposal",
        "interpretation_boundary": "Recommendations do not alter unbiased discovery results and are not causal conclusions.",
        "eligible_relationship_count": len(candidates),
        "recommendations": recommendations,
    }


def evaluate_uploaded_perturbation_evidence(
    relationships: Iterable[Mapping[str, Any]],
    uploaded_rows: Iterable[Mapping[str, Any]],
    *,
    alpha: float = 0.05,
) -> Dict[str, Any]:
    """Evaluate a normalized user-uploaded follow-up table against known links.

    Required row fields are ``source``, ``target``, ``control_mean``,
    ``perturbed_mean``, ``expected_target_change`` (``up`` or ``down``), and
    ``q_value``. The evaluator does not invent an expected effect and only
    assesses source-precedes-target relationships already observed in discovery.
    """
    relation_index = {
        relationship_key(relation): dict(relation)
        for relation in relationships
        if relationship_key(relation) and relation.get("direction") == "source_precedes_target"
    }
    evaluations: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for row_number, raw_row in enumerate(uploaded_rows, 2):
        source = str(raw_row.get("source") or "").strip()
        target = str(raw_row.get("target") or "").strip()
        key = f"{source}->{target}"
        relation = relation_index.get(key)
        if not relation:
            rejected.append({"row": row_number, "reason": "relationship_not_in_discovery_directionality", "relationship_id": key})
            continue
        control = _as_float(raw_row.get("control_mean"))
        perturbed = _as_float(raw_row.get("perturbed_mean"))
        q_value = _as_float(raw_row.get("q_value"))
        expected = str(raw_row.get("expected_target_change") or "").strip().lower()
        if control is None or perturbed is None or q_value is None or expected not in {"up", "down"}:
            rejected.append({"row": row_number, "reason": "invalid_required_fields", "relationship_id": key})
            continue
        observed_delta = perturbed - control
        direction_matches = (expected == "up" and observed_delta > 0) or (expected == "down" and observed_delta < 0)
        supported = q_value <= alpha and direction_matches
        evaluations.append({
            "relationship_id": key,
            "discovery_directionality_tier": relation.get("directionality_tier"),
            "control_mean": control,
            "perturbed_mean": perturbed,
            "observed_delta": observed_delta,
            "expected_target_change": expected,
            "q_value": q_value,
            "causality_status": "perturbation_supported" if supported else "perturbation_not_supported",
            "interpretation_boundary": "This is intervention evidence for the uploaded condition only; it does not generalize beyond the tested system.",
        })
    return {
        "schema_version": "perturbation_evidence.v1",
        "analysis_scope": "optional_post_analysis_perturbation_evidence",
        "alpha": alpha,
        "evaluations": evaluations,
        "rejected_rows": rejected,
        "summary": {
            "uploaded_rows_evaluated": len(evaluations),
            "perturbation_supported": sum(item["causality_status"] == "perturbation_supported" for item in evaluations),
            "perturbation_not_supported": sum(item["causality_status"] == "perturbation_not_supported" for item in evaluations),
            "rejected_rows": len(rejected),
        },
    }
