"""Form-aware PTM provenance and explicit site aggregation for temporal Atlas.

The RAG/report workflow remains site-centric for evidence retrieval, but a
gene-position site can have multiple modified peptide forms and precursor
charge states.  This module preserves those forms for temporal interpretation
and makes aggregation explicit rather than silently selecting the first row.

Aggregation is descriptive: per-timepoint median Track 2 value across
available forms.  It does not assert that forms are analytically equivalent.
Consumers must retain the form records alongside the aggregate.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections import Counter
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import numpy as np

from ptm_shared.directed_temporal_relationship import timepoint_to_minutes


CONTRACT_VERSION = "site_form_provenance.v2"
FORM_SEQUENCE_KEYS = ("Modified.Sequence", "modified_sequence", "ModifiedSequence")
FORM_CHARGE_KEYS = ("Precursor.Charge", "precursor_charge", "PrecursorCharge")
FORM_PRECURSOR_KEYS = ("Precursor.Id", "precursor_id", "PrecursorId")


_MISSING_TEXT = {"", "nan", "none", "null", "na", "n/a", "?"}


def _clean_text(value: Any) -> str:
    text = str(value).strip() if value is not None else ""
    return "" if text.lower() in _MISSING_TEXT else text


def _first_nonempty(record: Mapping[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        value = _clean_text(record.get(key))
        if value:
            return value
    return ""


def _normalise_charge(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    try:
        number = float(text)
    except (TypeError, ValueError):
        return text
    if not math.isfinite(number) or number <= 0 or not number.is_integer():
        return ""
    return str(int(number))


def _charge_from_precursor_id(precursor_id: str, sequence: str) -> str:
    """Recover charge only from an exact DIA-NN sequence+integer suffix."""
    if not precursor_id or not sequence or not precursor_id.startswith(sequence):
        return ""
    suffix = precursor_id[len(sequence):]
    return suffix if re.fullmatch(r"[1-9]\d*", suffix or "") else ""


def _optional_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def canonical_site_key(record: Mapping[str, Any]) -> str:
    gene = record.get("gene") or record.get("Gene.Name") or "?"
    position = record.get("position") or record.get("PTM_Position") or "?"
    return f"{gene}_{position}"


def form_identity(record: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a stable, transparent identity for a modified peptide form.

    A precursor ID is recorded as provenance but intentionally not part of the
    primary key when sequence/charge are available: technical precursor IDs can
    vary between exports for the same analytical form.  If neither sequence nor
    charge survives the upstream output, the record is labeled unresolved
    instead of pretending it represents a unique form.
    """
    site_key = canonical_site_key(record)
    sequence = _first_nonempty(record, FORM_SEQUENCE_KEYS)
    charge = _normalise_charge(_first_nonempty(record, FORM_CHARGE_KEYS))
    precursor_id = _first_nonempty(record, FORM_PRECURSOR_KEYS)
    charge_source = "recorded_field" if charge else None
    if not charge:
        charge = _charge_from_precursor_id(precursor_id, sequence)
        if charge:
            charge_source = "recovered_from_exact_precursor_suffix"
    if sequence and charge:
        form_key = f"{site_key}|seq={sequence}|z={charge}"
        status = "resolved_sequence_charge"
        report_eligible = True
    elif precursor_id or sequence or charge:
        form_key = (
            f"{site_key}|precursor={precursor_id or '?'}|seq={sequence or '?'}|z={charge or '?'}"
        )
        missing = []
        if not sequence:
            missing.append("sequence")
        if not charge:
            missing.append("charge")
        status = "unresolved_missing_" + "_and_".join(missing or ["form_identity"])
        report_eligible = False
    else:
        form_key = f"{site_key}|form=unresolved"
        status = "unresolved_missing_sequence_charge"
        report_eligible = False
    return {
        "site_key": site_key,
        "site_form_key": form_key,
        "modified_sequence": sequence or None,
        "precursor_charge": charge or None,
        "precursor_charge_source": charge_source,
        "precursor_id": precursor_id or None,
        "form_identity_status": status,
        "report_eligible": report_eligible,
        "contract_version": CONTRACT_VERSION,
    }


def _timepoint_sort_key(timepoint: Mapping[str, Any]) -> tuple[float, str]:
    label = str(timepoint.get("timeLabel", ""))
    minute = timepoint_to_minutes(label)
    return (minute if math.isfinite(minute) else math.inf, label)


def aggregate_site_form_trajectories(
    form_trajectories: Iterable[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Create explicit per-site medians while retaining form contribution counts.

    The input is the ``site_form_trajectories`` record emitted by the RAG PTM
    merger.  For each time label, finite form-level Track 2 values are combined
    by median.  q-values are *not* aggregated into a significance claim; the
    response reports only the available form count and source form keys.
    """
    forms = list(form_trajectories)
    by_label: Dict[str, List[float]] = defaultdict(list)
    contributing_forms: Dict[str, List[str]] = defaultdict(list)
    source_keys: List[str] = []

    for form in forms:
        form_key = str(form.get("site_form_key") or "")
        if form_key:
            source_keys.append(form_key)
        trajectory = form.get("trajectory") or {}
        for point in trajectory.get("timepoints") or []:
            value = _optional_float(
                point.get("ptmLog2FC")
                if point.get("ptmLog2FC") is not None
                else point.get("ptm_relative_log2fc")
            )
            label = str(point.get("timeLabel", ""))
            if value is None or not label:
                continue
            by_label[label].append(value)
            if form_key:
                contributing_forms[label].append(form_key)

    timepoints = []
    for label in sorted(by_label, key=lambda item: _timepoint_sort_key({"timeLabel": item})):
        values = by_label[label]
        distinct_keys = sorted(set(contributing_forms[label]))
        timepoints.append({
            "timeLabel": label,
            "ptmLog2FC": float(np.median(values)),
            "contributing_form_count": len(distinct_keys),
            "contributing_value_count": len(values),
            "contributing_form_keys": distinct_keys,
        })

    unique_source_keys = sorted(set(source_keys))
    unresolved_keys = sorted({
        str(form.get("site_form_key") or "")
        for form in forms
        if not bool(form.get("report_eligible", True))
    } - {""})
    return {
        "aggregation_method": "per_timepoint_median_track2_across_forms",
        "form_count": len(unique_source_keys),
        "source_form_record_count": len(forms),
        "source_form_keys": unique_source_keys,
        "source_form_keys_unique": len(unique_source_keys) == len(source_keys) == len(forms),
        "unresolved_form_keys": unresolved_keys,
        "report_eligible": not unresolved_keys and len(unique_source_keys) == len(forms),
        "timepoints": timepoints,
        "contract_version": CONTRACT_VERSION,
    }


def audit_site_form_record(record: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate one collapsed site record without inventing missing identity."""
    raw_forms = record.get("site_form_trajectories")
    aggregation = record.get("site_aggregation")
    forms = [dict(item) for item in raw_forms or [] if isinstance(item, Mapping)]
    applicable = bool(forms or isinstance(aggregation, Mapping))
    errors: list[str] = []
    keys = [str(form.get("site_form_key") or "").strip() for form in forms]
    if applicable and (not forms or any(not key for key in keys)):
        errors.append("missing_complete_site_form_records")
    if len(keys) != len(set(keys)):
        errors.append("duplicate_site_form_key")
    if any("|z=nan" in key.lower() for key in keys):
        errors.append("noncanonical_nan_charge")
    if any(not bool(form.get("report_eligible", True)) for form in forms):
        errors.append("unresolved_site_form_identity")

    duplicate_pairs: list[str] = []
    pairs: list[tuple[str, str]] = []
    for item in record.get("condition_data") or []:
        if not isinstance(item, Mapping):
            continue
        identity = str(
            item.get("precursor_id")
            or item.get("Precursor.Id")
            or item.get("site_form_key")
            or ""
        ).strip()
        condition = str(item.get("condition") or item.get("Condition") or "").strip()
        if identity and condition:
            pairs.append((identity, condition))
    for pair, count in Counter(pairs).items():
        if count > 1:
            duplicate_pairs.append(f"{pair[0]}|{pair[1]}")
    if duplicate_pairs:
        errors.append("duplicate_precursor_condition")

    if len(forms) == 1:
        top_precursor = _first_nonempty(record, FORM_PRECURSOR_KEYS)
        sole_precursor = _clean_text(forms[0].get("precursor_id"))
        if top_precursor and sole_precursor and top_precursor != sole_precursor:
            errors.append("sole_form_top_level_precursor_mismatch")

    aggregation_map = dict(aggregation) if isinstance(aggregation, Mapping) else {}
    if aggregation_map:
        if int(aggregation_map.get("form_count") or 0) != len(set(keys)):
            errors.append("persisted_form_count_mismatch")
        if sorted(aggregation_map.get("source_form_keys") or []) != sorted(set(keys)):
            errors.append("source_form_key_set_mismatch")
        for point in aggregation_map.get("timepoints") or []:
            if not isinstance(point, Mapping):
                continue
            point_keys = {str(value) for value in point.get("contributing_form_keys") or [] if str(value)}
            count = int(point.get("contributing_form_count") or 0)
            if count != len(point_keys) or count > len(set(keys)) or not point_keys.issubset(set(keys)):
                errors.append("contributing_form_count_or_key_mismatch")
                break

    errors = sorted(set(errors))
    return {
        "contract_version": "site_form_provenance_audit.v1",
        "applicable": applicable,
        "status": "validated" if applicable and not errors else "not_applicable" if not applicable else "incompatible",
        "report_eligible": bool(applicable and not errors),
        "site_key": canonical_site_key(record),
        "form_count": len(forms),
        "duplicate_precursor_conditions": sorted(duplicate_pairs),
        "error_codes": errors,
    }


def audit_enriched_site_form_records(records: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """Return a compact eligibility audit for an enriched temporal input artifact."""
    audits = [audit_site_form_record(record) for record in records if isinstance(record, Mapping)]
    applicable = [audit for audit in audits if audit["applicable"]]
    incompatible = [audit for audit in applicable if not audit["report_eligible"]]
    error_counts = Counter(code for audit in incompatible for code in audit["error_codes"])
    return {
        "contract_version": "enriched_site_form_provenance_audit.v1",
        "status": "validated" if applicable and not incompatible else "not_applicable" if not applicable else "incompatible",
        "report_eligible": bool(applicable and not incompatible),
        "input_record_count": len(audits),
        "audited_record_count": len(applicable),
        "incompatible_record_count": len(incompatible),
        "error_code_counts": dict(sorted(error_counts.items())),
        "incompatible_site_keys": sorted({audit["site_key"] for audit in incompatible})[:100],
    }


def audit_enriched_vector_crosswalk(
    enriched_records: Iterable[Mapping[str, Any]],
    vector_rows: Iterable[Mapping[str, Any]],
    *,
    tolerance: float = 1e-9,
) -> Dict[str, Any]:
    """Compare eligible enriched form values with Stage-1 rows by exact identity.

    The audit does not infer an identity from gene or residue. Only explicit
    ``(precursor_id, condition)`` pairs are compared. A missing pair, duplicate
    pair, or numerical disagreement makes the enriched artifact ineligible for
    temporal/report use.
    """
    vector_index: dict[tuple[str, str], float] = {}
    vector_duplicates: set[tuple[str, str]] = set()
    for row in vector_rows:
        if not isinstance(row, Mapping):
            continue
        precursor = _clean_text(row.get("precursor_id") or row.get("Precursor.Id"))
        condition = _clean_text(row.get("condition") or row.get("Condition"))
        value = _optional_float(
            row.get("log2fc")
            if row.get("log2fc") is not None
            else row.get("ptm_relative_log2fc")
            if row.get("ptm_relative_log2fc") is not None
            else row.get("PTM_Relative_Log2FC")
        )
        if not precursor or not condition or value is None:
            continue
        key = (precursor, condition)
        if key in vector_index:
            vector_duplicates.add(key)
        else:
            vector_index[key] = value

    enriched_index: dict[tuple[str, str], float] = {}
    enriched_duplicates: set[tuple[str, str]] = set()
    missing_identity_count = 0
    for record in enriched_records:
        if not isinstance(record, Mapping):
            continue
        for point in record.get("condition_data") or []:
            if not isinstance(point, Mapping):
                continue
            precursor = _clean_text(point.get("precursor_id") or point.get("Precursor.Id"))
            condition = _clean_text(point.get("condition") or point.get("Condition"))
            value = _optional_float(
                point.get("ptm_relative_log2fc")
                if point.get("ptm_relative_log2fc") is not None
                else point.get("PTM_Relative_Log2FC")
            )
            if not precursor or not condition:
                missing_identity_count += 1
                continue
            if value is None:
                continue
            key = (precursor, condition)
            if key in enriched_index:
                enriched_duplicates.add(key)
            else:
                enriched_index[key] = value

    missing_vector_pairs = sorted(set(enriched_index) - set(vector_index))
    value_mismatches = sorted(
        key for key in set(enriched_index) & set(vector_index)
        if abs(enriched_index[key] - vector_index[key]) > tolerance
    )
    error_codes: list[str] = []
    if vector_duplicates:
        error_codes.append("duplicate_vector_precursor_condition")
    if enriched_duplicates:
        error_codes.append("duplicate_enriched_precursor_condition")
    if missing_identity_count:
        error_codes.append("enriched_condition_identity_missing")
    if missing_vector_pairs:
        error_codes.append("enriched_pair_missing_from_vector")
    if value_mismatches:
        error_codes.append("enriched_vector_value_mismatch")
    compared_pairs = len(set(enriched_index) & set(vector_index))
    if not vector_index:
        error_codes.append("vector_crosswalk_source_unavailable")
    if not enriched_index:
        error_codes.append("enriched_crosswalk_identity_unavailable")
    return {
        "contract_version": "enriched_vector_crosswalk_audit.v1",
        "status": "validated" if not error_codes else "incompatible",
        "report_eligible": not error_codes,
        "vector_pair_count": len(vector_index),
        "enriched_pair_count": len(enriched_index),
        "compared_pair_count": compared_pairs,
        "missing_enriched_identity_count": missing_identity_count,
        "duplicate_vector_pair_count": len(vector_duplicates),
        "duplicate_enriched_pair_count": len(enriched_duplicates),
        "missing_vector_pair_count": len(missing_vector_pairs),
        "value_mismatch_count": len(value_mismatches),
        "error_codes": error_codes,
        "sample_missing_vector_pairs": [f"{precursor}|{condition}" for precursor, condition in missing_vector_pairs[:20]],
        "sample_value_mismatches": [f"{precursor}|{condition}" for precursor, condition in value_mismatches[:20]],
        "numeric_tolerance": tolerance,
    }
