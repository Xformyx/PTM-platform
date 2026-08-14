"""Canonical species and custom-reference registry for PTM-platform.

Custom reference labels remain visible on an order and select their own FASTA
directory, while downstream public annotation is routed through an explicitly
declared base organism.  This prevents an alias from silently falling back to
another species or from being treated as a novel NCBI organism.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpeciesContext:
    label: str
    analysis_species: str
    taxonomy_id: str
    kegg_organism: str
    reference_subdir: str
    display_name: str
    custom_reference: bool = False
    description: str = ""


_REGISTRY = {
    "mouse": SpeciesContext("mouse", "mouse", "10090", "mmu", "mouse", "Mouse"),
    "human": SpeciesContext("human", "human", "9606", "hsa", "human", "Human"),
    "rat": SpeciesContext("rat", "rat", "10116", "rno", "rat", "Rat"),
    # Rat_hir is a custom Rattus norvegicus reference database with one
    # Homo sapiens INSR FASTA entry.  The per-protein FASTA provenance layer
    # routes P06213/INSR to human annotation; the order-level context stays rat.
    "rat_hir": SpeciesContext(
        "rat_hir",
        "rat",
        "10116",
        "rno",
        "rat_hir",
        "Rat_hir (Rat + human INSR)",
        custom_reference=True,
        description="Rattus norvegicus reference FASTA supplemented with human insulin receptor.",
    ),
}

_ALIASES = {
    "rat-hir": "rat_hir",
    "rat hir": "rat_hir",
    "rat_human_insulin_receptor": "rat_hir",
}


def resolve_species_context(label: str | None) -> SpeciesContext:
    """Resolve a persisted species label without silently defaulting to mouse."""
    raw = (label or "mouse").strip().lower()
    canonical = _ALIASES.get(raw, raw.replace("-", "_"))
    if canonical not in _REGISTRY:
        raise ValueError(
            f"Unsupported species/reference label '{label}'. "
            f"Supported labels: {', '.join(sorted(_REGISTRY))}."
        )
    return _REGISTRY[canonical]


def species_registry_for_ui() -> list[dict[str, str | bool]]:
    """Return non-sensitive display metadata for species selection UIs."""
    return [
        {
            "value": context.label,
            "label": context.display_name,
            "analysis_species": context.analysis_species,
            "reference_subdir": context.reference_subdir,
            "custom_reference": context.custom_reference,
            "description": context.description,
        }
        for context in _REGISTRY.values()
    ]
