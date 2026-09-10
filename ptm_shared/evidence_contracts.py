"""Shared evidence and measurement contracts for PTM analysis artifacts.

The contracts in this module are deliberately orthogonal.  A feature can be
observed quantitatively while a specific statistical or mechanistic evaluation
is not evaluable.  Measurement identity likewise keeps modification count,
localization, protein mapping, and aggregation provenance separate.

This module contains no benchmark truth, literature retrieval, LLM inference,
or kinase assignment logic.
"""

from __future__ import annotations

import math
import re
from enum import Enum
from typing import Any, Mapping, Sequence


EVIDENCE_ENVELOPE_CONTRACT_VERSION = "ptm_evidence_envelope.v1"
MEASUREMENT_PROVENANCE_CONTRACT_VERSION = "ptm_measurement_provenance.v1"
CLASS_I_LOCALIZATION_THRESHOLD = 0.75


class ObservationStatus(str, Enum):
    observed_complete = "observed_complete"
    observed_partial = "observed_partial"
    not_detected = "not_detected"
    unavailable = "unavailable"


class EvaluationStatus(str, Enum):
    evaluated = "evaluated"
    not_evaluable = "not_evaluable"
    not_requested = "not_requested"
    not_applicable = "not_applicable"


class OutcomeClass(str, Enum):
    passed = "passed"
    below_threshold = "below_threshold"
    inconsistent = "inconsistent"
    neutral = "neutral"
    unavailable = "unavailable"


class EffectDirection(str, Enum):
    positive = "positive"
    negative = "negative"
    mixed = "mixed"
    none = "none"
    unavailable = "unavailable"


class ClaimTier(str, Enum):
    O1 = "O1"
    O2 = "O2"
    C1 = "C1"
    L1 = "L1"
    H1 = "H1"
    D1 = "D1"


def _enum_value(value: Any, enum_cls: type[Enum]) -> str:
    if isinstance(value, enum_cls):
        return str(value.value)
    return str(value or "")


def build_evidence_envelope(
    *,
    observation_status: ObservationStatus | str,
    measurement_unit: str,
    value_ids: Sequence[str] = (),
    evaluation_status: EvaluationStatus | str,
    method_id: str | None = None,
    reason_codes: Sequence[str] = (),
    outcome_class: OutcomeClass | str = OutcomeClass.unavailable,
    effect_direction: EffectDirection | str = EffectDirection.unavailable,
    uncertainty: Mapping[str, Any] | None = None,
    maximum_tier: ClaimTier | str = ClaimTier.O1,
    allowed_predicates: Sequence[str] = (),
    forbidden_predicates: Sequence[str] = (),
) -> dict[str, Any]:
    """Build an evidence envelope without collapsing its four semantic axes."""
    envelope = {
        "contract_version": EVIDENCE_ENVELOPE_CONTRACT_VERSION,
        "observation": {
            "status": _enum_value(observation_status, ObservationStatus),
            "measurement_unit": str(measurement_unit or "unavailable"),
            "value_ids": [str(value) for value in value_ids if str(value).strip()],
        },
        "evaluation": {
            "status": _enum_value(evaluation_status, EvaluationStatus),
            "method_id": str(method_id) if method_id else None,
            "reason_codes": sorted({str(code) for code in reason_codes if str(code).strip()}),
        },
        "outcome": {
            "class": _enum_value(outcome_class, OutcomeClass),
            "effect_direction": _enum_value(effect_direction, EffectDirection),
            "uncertainty": dict(uncertainty or {}),
        },
        "claim_scope": {
            "maximum_tier": _enum_value(maximum_tier, ClaimTier),
            "allowed_predicates": sorted({
                str(predicate).strip() for predicate in allowed_predicates if str(predicate).strip()
            }),
            "forbidden_predicates": sorted({
                str(predicate).strip() for predicate in forbidden_predicates if str(predicate).strip()
            }),
        },
    }
    errors = validate_evidence_envelope(envelope)
    if errors:
        raise ValueError("Invalid evidence envelope: " + "; ".join(errors))
    return envelope


def validate_evidence_envelope(envelope: Mapping[str, Any]) -> list[str]:
    """Return structural/semantic contract violations without merging axes."""
    errors: list[str] = []
    observation = dict(envelope.get("observation") or {})
    evaluation = dict(envelope.get("evaluation") or {})
    outcome = dict(envelope.get("outcome") or {})
    claim_scope = dict(envelope.get("claim_scope") or {})

    valid_observation = {item.value for item in ObservationStatus}
    valid_evaluation = {item.value for item in EvaluationStatus}
    valid_outcome = {item.value for item in OutcomeClass}
    valid_direction = {item.value for item in EffectDirection}
    valid_tiers = {item.value for item in ClaimTier}
    if observation.get("status") not in valid_observation:
        errors.append("invalid_observation_status")
    if not str(observation.get("measurement_unit") or "").strip():
        errors.append("missing_measurement_unit")
    if evaluation.get("status") not in valid_evaluation:
        errors.append("invalid_evaluation_status")
    if evaluation.get("status") == EvaluationStatus.evaluated.value and not evaluation.get("method_id"):
        errors.append("evaluated_without_method_id")
    if evaluation.get("status") != EvaluationStatus.evaluated.value and outcome.get("class") not in {
        OutcomeClass.unavailable.value,
        OutcomeClass.neutral.value,
    }:
        errors.append("unevaluated_with_assertive_outcome")
    if outcome.get("class") not in valid_outcome:
        errors.append("invalid_outcome_class")
    if outcome.get("effect_direction") not in valid_direction:
        errors.append("invalid_effect_direction")
    if claim_scope.get("maximum_tier") not in valid_tiers:
        errors.append("invalid_claim_tier")
    return errors


def _text(record: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = record.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _accession_tokens(protein_group: str) -> list[str]:
    tokens: list[str] = []
    for candidate in re.split(r"[;,]", protein_group or ""):
        item = candidate.strip()
        if not item:
            continue
        pipe_parts = [part.strip() for part in item.split("|")]
        if len(pipe_parts) >= 2 and pipe_parts[0].lower() in {"sp", "tr"}:
            item = pipe_parts[1]
        tokens.append(item)
    return sorted(set(tokens))


def _reported_positions(record: Mapping[str, Any]) -> list[str]:
    raw = _text(
        record,
        "all_reported_ptm_positions",
        "PTM_Positions",
        "PTM_Sites",
        "PTM_Position",
        "position",
    )
    return sorted({item.strip().upper() for item in re.split(r"[;,|/]", raw) if item.strip()})


def _target_modification_count(modified_sequence: str) -> int:
    if not modified_sequence:
        return 0
    named = len(re.findall(r"(?:phospho|phosphoryl)", modified_sequence, flags=re.IGNORECASE))
    unimod = len(re.findall(r"UniMod:(?:21|259|267)\b", modified_sequence, flags=re.IGNORECASE))
    return max(named, unimod)


def build_measurement_provenance(
    record: Mapping[str, Any],
    *,
    feature_id: str | None = None,
    member_feature_ids: Sequence[str] = (),
    aggregation_rule: str = "none_single_source_feature",
) -> dict[str, Any]:
    """Build independent measurement-identity axes from an exported feature."""
    protein_group = _text(
        record,
        "protein_group",
        "Protein.Group",
        "Protein.Ids",
        "protein_accession",
        "UniProt_ID",
    )
    modified_sequence = _text(record, "modified_sequence", "Modified.Sequence", "ModifiedSequence")
    positions = _reported_positions(record)
    modification_count = _target_modification_count(modified_sequence)
    localization_probability = _finite(_text(
        record,
        "localization_probability",
        "Localization.Probability",
        "PTM_Probability",
    ))
    accessions = _accession_tokens(protein_group)
    source_feature_id = feature_id or _text(
        record,
        "source_feature_key",
        "Source_Feature_Key",
        "Precursor.Id",
        "PrecursorId",
    )
    members = [str(item) for item in member_feature_ids if str(item).strip()]
    if not members and source_feature_id:
        members = [source_feature_id]

    if localization_probability is None:
        localization_status = "not_recorded"
    elif localization_probability >= CLASS_I_LOCALIZATION_THRESHOLD:
        localization_status = "recorded_class_I_or_higher"
    else:
        localization_status = "recorded_below_class_I_threshold"

    if (
        modification_count == 1
        and len(positions) == 1
        and localization_status == "recorded_class_I_or_higher"
        and len(accessions) == 1
    ):
        reader_unit = "localized_ptm_site_feature"
    elif modification_count > 1:
        reader_unit = "multi_modified_precursor_feature"
    else:
        reader_unit = "candidate_residue_modified_precursor_feature"

    return {
        "contract_version": MEASUREMENT_PROVENANCE_CONTRACT_VERSION,
        "feature_entity": "modified_precursor_feature",
        "source_feature_id": source_feature_id or None,
        "reader_measurement_unit": reader_unit,
        "modification_form": {
            "modified_sequence": modified_sequence or None,
            "target_modification_count": int(modification_count),
            "target_modification_count_source": (
                "explicit_modified_sequence" if modified_sequence else "not_inferable"
            ),
            "candidate_residues": positions,
        },
        "localization_evidence": {
            "probability": localization_probability,
            "threshold": CLASS_I_LOCALIZATION_THRESHOLD,
            "status": localization_status,
            "candidate_residue_count": len(positions),
        },
        "protein_mapping": {
            "protein_group": protein_group or None,
            "accession_tokens": accessions,
            "status": (
                "unique_accession" if len(accessions) == 1
                else "ambiguous_group" if len(accessions) > 1
                else "missing"
            ),
            "taxonomy_id": _text(
                record,
                "fasta_taxonomy_id",
                "FASTA_Taxonomy_ID",
                "Annotation_Species_Taxonomy_ID",
            ) or None,
        },
        "aggregation_provenance": {
            "member_feature_ids": sorted(set(members)),
            "aggregation_rule": str(aggregation_rule or "unspecified"),
            "lost_distinctions": [],
        },
        "claim_boundary": (
            "Measurement provenance does not establish residue-exact species/isoform mapping, "
            "direct kinase relation, occupancy, or causality."
        ),
    }
