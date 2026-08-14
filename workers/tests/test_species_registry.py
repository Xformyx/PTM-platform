import pytest

from ptm_shared.species_registry import resolve_species_context, species_registry_for_ui


def test_rat_hir_is_a_rat_base_custom_reference_not_a_new_organism():
    context = resolve_species_context("Rat_hir")

    assert context.label == "rat_hir"
    assert context.analysis_species == "rat"
    assert context.taxonomy_id == "10116"
    assert context.kegg_organism == "rno"
    assert context.reference_subdir == "rat_hir"
    assert context.custom_reference is True
    assert "human insulin receptor" in context.description.lower()


def test_rat_hir_aliases_resolve_to_the_same_custom_reference():
    assert resolve_species_context("rat-hir") == resolve_species_context("rat_hir")
    assert resolve_species_context("rat_human_insulin_receptor") == resolve_species_context("rat_hir")


def test_unknown_species_is_rejected_instead_of_falling_back_to_mouse():
    with pytest.raises(ValueError, match="Unsupported species/reference label"):
        resolve_species_context("rat_hir_typo")


def test_ui_registry_exposes_the_custom_reference_label():
    entries = {entry["value"]: entry for entry in species_registry_for_ui()}
    assert entries["rat_hir"]["analysis_species"] == "rat"
    assert entries["rat_hir"]["reference_subdir"] == "rat_hir"
