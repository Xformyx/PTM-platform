"""Source-aware study metadata contract for reader-facing Reports.

The Report can repeat supplied experimental metadata but must not infer a cell
line's lineage, species, or engineering history from a short cell-model label.
"""

from __future__ import annotations

import re
from typing import Any, Mapping


STUDY_METADATA_CONTRACT_VERSION = "study_metadata_contract.v1"


def _value(context: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        item = context.get(key)
        if item is not None and str(item).strip():
            return str(item).strip()
    return None


def build_study_metadata_contract(context: Mapping[str, Any] | None) -> dict[str, Any]:
    source = dict(context or {})
    cell_model = _value(source, "cell_model", "cell_type", "cell_line", "tissue")
    organism = _value(source, "organism", "species", "taxonomy")
    source_fields = {
        "cell_model": next((key for key in ("cell_model", "cell_type", "cell_line", "tissue") if _value(source, key)), None),
        "organism": next((key for key in ("organism", "species", "taxonomy") if _value(source, key)), None),
    }
    return {
        "contract_version": STUDY_METADATA_CONTRACT_VERSION,
        "cell_model": cell_model or "the recorded experimental system",
        "organism": organism,
        "treatment": _value(source, "treatment", "compound"),
        "timepoints": list(source.get("timepoints") or source.get("conditions") or []),
        "source_fields": source_fields,
        "lineage_or_species_inference_allowed": bool(organism),
        "reader_boundary": (
            "Repeat only recorded cell-model and organism metadata. Do not infer lineage, species, receptor status, "
            "or engineering history from a cell-model name."
        ),
    }


def repair_unrecorded_metadata_claim(sentence: str, contract: Mapping[str, Any]) -> tuple[str, bool]:
    """Remove unsupported lineage/species expansion in study-system statements.

    The guard activates only for sentences that explicitly discuss a cell model or
    experimental system. It does not modify cited external biology statements.
    """
    text = str(sentence or "")
    if contract.get("lineage_or_species_inference_allowed"):
        return text, False
    if not re.search(r"\b(?:cell(?:[- ]line| model)?|experimental system|culture)\b", text, flags=re.IGNORECASE):
        return text, False
    # Species/lineage words in an uncited current-study cell-system statement are
    # not supported unless supplied in study metadata.
    unsafe = re.compile(
        r"\b(?:human|murine|mouse|rat|hamster|chinese hamster|CHO|HEK(?:-?293)?|fibroblast|hepatocyte)\b",
        flags=re.IGNORECASE,
    )
    if not unsafe.search(text):
        return text, False
    repaired = unsafe.sub("recorded", text)
    repaired = re.sub(r"\brecorded\s+recorded\b", "recorded", repaired, flags=re.IGNORECASE)
    return repaired, True
