"""Source-aware experimental metadata contract for reader-facing Reports.

The Report may repeat recorded metadata, but it must not infer lineage, species,
receptor status, or engineering history from a short cell-model label.  A user-
verified override may correct stale free text without hard-coding any benchmark
model in production logic.  Unresolved identity conflicts are release-blocking.
"""

from __future__ import annotations

import re
from typing import Any, Mapping


STUDY_METADATA_CONTRACT_VERSION = "study_metadata_contract.v2"

_FIELD_ALIASES = {
    "cell_model": ("cell_model", "cell_type", "cell_line", "tissue"),
    "organism": ("organism", "species", "taxonomy"),
    "parent_line": ("parent_line", "parent_cell_line"),
    "engineering": ("engineering", "genetic_modification", "transgene", "receptor_status"),
    "treatment": ("treatment", "compound"),
}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _value(context: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = _text(context.get(key))
        if value:
            return value
    return None


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _normalise(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _distinct_values(context: Mapping[str, Any], aliases: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for key in aliases:
        value = _text(context.get(key))
        marker = _normalise(value)
        if value and marker not in seen:
            values.append(value)
            seen.add(marker)
    return values


def _verified_override(context: Mapping[str, Any]) -> dict[str, Any]:
    for key in ("verified_metadata", "study_metadata_override", "metadata_override"):
        candidate = context.get(key)
        if isinstance(candidate, Mapping):
            return dict(candidate)
    return {}


def _reader_system_label(values: Mapping[str, Any]) -> str:
    cell_model = _text(values.get("cell_model")) or "the recorded experimental system"
    qualifiers: list[str] = []
    parent_line = _text(values.get("parent_line"))
    organism = _text(values.get("organism"))
    engineering = _text(values.get("engineering"))
    if parent_line:
        qualifiers.append(f"parent line {parent_line}")
    if organism:
        qualifiers.append(organism)
    if engineering:
        qualifiers.append(engineering)
    return f"{cell_model} ({'; '.join(qualifiers)})" if qualifiers else cell_model


def build_study_metadata_contract(context: Mapping[str, Any] | None) -> dict[str, Any]:
    """Resolve recorded metadata and an optional user-verified override.

    The override is generic configuration supplied with the Order/report request;
    no named cell model, organism, pathway, or perturbation is encoded here.
    """
    source = dict(context or {})
    override = _verified_override(source)
    selected: dict[str, Any] = {}
    source_fields: dict[str, str | None] = {}
    conflict_records: list[dict[str, Any]] = []
    blocking_conflicts: list[str] = []
    resolved_conflicts: list[str] = []

    for field, aliases in _FIELD_ALIASES.items():
        recorded_values = _distinct_values(source, aliases)
        override_value = _text(override.get(field))
        selected_value = override_value or (recorded_values[0] if recorded_values else None)
        selected[field] = selected_value
        if override_value:
            source_fields[field] = f"verified_metadata.{field}"
        else:
            source_fields[field] = next((key for key in aliases if _text(source.get(key))), None)

        recorded_markers = {_normalise(value) for value in recorded_values}
        if len(recorded_markers) > 1 and not override_value:
            code = f"unresolved_{field}_conflict"
            blocking_conflicts.append(code)
            conflict_records.append({"field": field, "status": "unresolved", "reason_code": code})
        elif override_value and recorded_values and _normalise(override_value) not in recorded_markers:
            code = f"{field}_conflict_resolved_by_verified_override"
            resolved_conflicts.append(code)
            conflict_records.append({"field": field, "status": "resolved_by_verified_override", "reason_code": code})

    timepoints = list(source.get("timepoints") or source.get("conditions") or [])
    verification_source = _text(override.get("verification_source") or override.get("source"))
    verification_reference_ids = [
        str(item).strip() for item in (override.get("reference_ids") or []) if str(item).strip()
    ]
    metadata_status = (
        "conflict_unresolved" if blocking_conflicts
        else "verified_override" if override
        else "recorded_unverified"
    )
    review_reasons: list[str] = []
    if not selected.get("cell_model"):
        review_reasons.append("cell_model_not_recorded")
    if selected.get("cell_model") and not selected.get("organism"):
        review_reasons.append("organism_not_recorded")

    reader_system_label = _reader_system_label(selected)
    return {
        "contract_version": STUDY_METADATA_CONTRACT_VERSION,
        "cell_model": selected.get("cell_model") or "the recorded experimental system",
        "organism": selected.get("organism"),
        "parent_line": selected.get("parent_line"),
        "engineering": selected.get("engineering"),
        "treatment": selected.get("treatment"),
        "timepoints": timepoints,
        "reader_system_label": reader_system_label,
        "source_fields": source_fields,
        "metadata_status": metadata_status,
        "verification_source": verification_source,
        "verification_reference_ids": verification_reference_ids,
        "resolved_conflict_reason_codes": resolved_conflicts,
        "release_blocking_conflicts": blocking_conflicts,
        "conflict_records": conflict_records,
        "review_reason_codes": review_reasons,
        "lineage_or_species_inference_allowed": False,
        "reader_boundary": (
            "Use only the resolved metadata values and their exact meaning. Do not infer lineage, species, receptor "
            "status, or engineering history from a cell-model name. A verified override supersedes stale free text; "
            "an unresolved identity conflict blocks final release."
        ),
    }


_IDENTITY_TERMS = re.compile(
    r"\b(?:human|murine|mouse|rat|hamster|chinese hamster|CHO|HEK(?:-?293)?|fibroblast|hepatocyte|"
    r"overexpress(?:ing|ed)?|transfect(?:ed|ion)?|transgene|receptor[- ]positive)\b",
    flags=re.IGNORECASE,
)


def repair_unrecorded_metadata_claim(sentence: str, contract: Mapping[str, Any]) -> tuple[str, bool]:
    """Replace unsupported cell-system expansion with the canonical resolved label."""
    text = str(sentence or "")
    if not re.search(r"\b(?:cell(?:[- ]line| model)?|experimental system|culture|cells?)\b", text, flags=re.IGNORECASE):
        return text, False

    canonical_values = " ".join(
        str(contract.get(key) or "")
        for key in ("cell_model", "organism", "parent_line", "engineering")
    )
    allowed_tokens = {
        _normalise(match.group(0))
        for match in _IDENTITY_TERMS.finditer(canonical_values)
        if _normalise(match.group(0))
    }
    observed_tokens = {
        _normalise(match.group(0))
        for match in _IDENTITY_TERMS.finditer(text)
        if _normalise(match.group(0))
    }
    unsupported = observed_tokens - allowed_tokens
    if not unsupported and not contract.get("release_blocking_conflicts"):
        return text, False

    label = str(contract.get("reader_system_label") or contract.get("cell_model") or "the recorded experimental system")
    repaired = f"The study used {label} under the recorded experimental design."
    return repaired, True
