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
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import numpy as np

from ptm_shared.directed_temporal_relationship import timepoint_to_minutes


CONTRACT_VERSION = "site_form_provenance.v1"
FORM_SEQUENCE_KEYS = ("Modified.Sequence", "modified_sequence", "ModifiedSequence")
FORM_CHARGE_KEYS = ("Precursor.Charge", "precursor_charge", "PrecursorCharge")
FORM_PRECURSOR_KEYS = ("Precursor.Id", "precursor_id", "PrecursorId")


def _first_nonempty(record: Mapping[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        value = record.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


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
    charge = _first_nonempty(record, FORM_CHARGE_KEYS)
    precursor_id = _first_nonempty(record, FORM_PRECURSOR_KEYS)
    if sequence or charge:
        form_key = f"{site_key}|seq={sequence or '?'}|z={charge or '?'}"
        status = "resolved_sequence_charge"
    else:
        form_key = f"{site_key}|form=unresolved"
        status = "unresolved_missing_sequence_charge"
    return {
        "site_key": site_key,
        "site_form_key": form_key,
        "modified_sequence": sequence or None,
        "precursor_charge": charge or None,
        "precursor_id": precursor_id or None,
        "form_identity_status": status,
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
        timepoints.append({
            "timeLabel": label,
            "ptmLog2FC": float(np.median(values)),
            "contributing_form_count": len(values),
            "contributing_form_keys": sorted(set(contributing_forms[label])),
        })

    return {
        "aggregation_method": "per_timepoint_median_track2_across_forms",
        "form_count": len(forms),
        "source_form_keys": sorted(set(source_keys)),
        "timepoints": timepoints,
        "contract_version": CONTRACT_VERSION,
    }
