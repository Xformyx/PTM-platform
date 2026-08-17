from ptm_shared.reference_fasta import missing_reference_detail, resolve_reference_fasta
from ptm_shared.species_registry import resolve_species_context


def test_rat_hir_reference_resolves_only_from_its_custom_directory(tmp_path):
    rat_context = resolve_species_context("rat")
    rat_dir = tmp_path / rat_context.reference_subdir
    rat_dir.mkdir(parents=True)
    (rat_dir / "standard_rat.fasta").write_text(">sp|P00000|RAT\nMPEPTIDE\n")

    rat_hir_context = resolve_species_context("rat_hir")
    assert resolve_reference_fasta(str(tmp_path), rat_hir_context.label) is None

    custom_dir = tmp_path / rat_hir_context.reference_subdir
    custom_dir.mkdir(parents=True)
    custom_fasta = custom_dir / "rat_hir_reference.fa"
    custom_fasta.write_text(">sp|P06213|INSR_HUMAN GN=INSR OX=9606\nMPEPTIDE\n")

    assert resolve_reference_fasta(str(tmp_path), rat_hir_context.label) == str(custom_fasta)


def test_missing_rat_hir_reference_error_does_not_recommend_standard_rat_fallback(tmp_path):
    context = resolve_species_context("rat_hir")
    detail = missing_reference_detail(str(tmp_path), context)

    assert "custom reference FASTA" in detail
    assert "GN=INSR" in detail
    assert "OX=9606" in detail
    assert "cannot fall back to the standard rat FASTA" in detail


def test_missing_standard_rat_reference_error_points_to_registered_directory(tmp_path):
    context = resolve_species_context("rat")
    detail = missing_reference_detail(str(tmp_path), context)

    assert "No reference FASTA" in detail
    assert str(tmp_path / "rat") in detail
