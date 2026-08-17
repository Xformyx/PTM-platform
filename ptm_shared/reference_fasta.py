"""Reference FASTA resolution shared by order-creation entry points."""

from pathlib import Path

from .species_registry import SpeciesContext, resolve_species_context


def resolve_reference_fasta(reference_dir: str, species: str) -> str | None:
    """Return the first registered .fasta/.fa file for a valid species label."""
    try:
        context = resolve_species_context(species)
    except ValueError:
        return None

    species_dir = Path(reference_dir) / context.reference_subdir
    if not species_dir.is_dir():
        return None
    for pattern in ("*.fasta", "*.fa"):
        candidate = next(iter(sorted(species_dir.glob(pattern))), None)
        if candidate:
            return str(candidate)
    return None


def missing_reference_detail(reference_dir: str, species_context: SpeciesContext) -> str:
    """Explain a missing reference without suggesting an unsafe fallback."""
    expected_dir = Path(reference_dir) / species_context.reference_subdir
    if species_context.custom_reference:
        return (
            f"No custom reference FASTA is available for '{species_context.label}'. "
            f"Add a .fasta or .fa file under {expected_dir}. "
            "Rat_hir must contain the rat reference proteins plus the human INSR entry "
            "with GN=INSR and OX=9606; it cannot fall back to the standard rat FASTA."
        )
    return (
        f"No reference FASTA is available for '{species_context.label}'. "
        f"Add a .fasta or .fa file under {expected_dir}."
    )
