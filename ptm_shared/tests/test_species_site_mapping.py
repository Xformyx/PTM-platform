"""P1 mapping provenance tests use only synthetic, local snapshot fixtures."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ptm_shared.kinase_evidence_ledger import build_feature_provenance_ledger, compact_summary
from ptm_shared.species_site_mapping import (
    M0_NOT_EVALUABLE,
    M1_EXACT,
    M2_ALIGNED_ONE_TO_ONE,
    M3_GENE_ONLY,
    M4_UNMAPPED_OR_AMBIGUOUS,
    MAPPING_IMPORTER_CONTRACT_VERSION,
    SOURCE_BUNDLE_CONTRACT_VERSION,
    attach_mapping_context,
    map_feature_records,
)


def _write(path: Path, text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fasta(primary: str, sequence: str, *, taxon: int, gene: str) -> str:
    return f">{primary} OS=synthetic OX={taxon} GN={gene}\n{sequence}\n"


def _feature(*, accession: str, gene: str, position: str, peptide: str, taxon: int | None = None) -> dict:
    record = {
        "gene": gene,
        "position": position,
        "condition": "1min",
        "log2fc": 0.4,
        "protein_group": accession,
        "modified_sequence": peptide,
        "precursor_id": f"precursor-{accession}",
        "all_reported_ptm_positions": position,
        "localization_probability": "0.99",
    }
    if taxon is not None:
        record["fasta_taxonomy_id"] = str(taxon)
    return record


def _row(
    *,
    source_protein: str,
    target_protein: str,
    source_sequence: str,
    target_sequence: str,
    source_gene: str = "MAPK1",
    target_gene: str = "ENSG_TARGET",
    homology_type: str = "ortholog_one2one",
    high_confidence: bool = True,
    source_aligned: str | None = None,
    target_aligned: str | None = None,
    cigar_line: str | None = None,
) -> dict:
    return {
        "source_ensembl_gene_id": "ENSRNOG_SOURCE",
        "target_ensembl_gene_id": target_gene,
        "source_ensembl_protein_id": source_protein,
        "target_ensembl_protein_id": target_protein,
        "homology_type": homology_type,
        "is_high_confidence": high_confidence,
        "source_taxonomy_id": 10116,
        "target_taxonomy_id": 9606,
        "source_sequence": source_sequence,
        "target_sequence": target_sequence,
        "source_aligned": source_aligned or source_sequence,
        "target_aligned": target_aligned or target_sequence,
        "cigar_line": cigar_line or f"{len(source_sequence)}M",
        "source_gene_symbol": source_gene,
        "target_gene_symbol": "MAPK1",
    }


def _bundle(tmp_path: Path, *, analysis: str, rat: str, human: str, rows: list[dict]) -> tuple[Path, Path]:
    root = tmp_path / "snapshots"
    analysis_hash = _write(root / "analysis.fasta", analysis)
    rat_hash = _write(root / "rat.fasta", rat)
    human_hash = _write(root / "human.fasta", human)
    orthology_text = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    orthology_hash = _write(root / "orthology.jsonl", orthology_text)
    manifest = {
        "contract_version": SOURCE_BUNDLE_CONTRACT_VERSION,
        "bundle_id": "synthetic-p1-bundle",
        "analysis_reference": {"relative_path": "analysis.fasta", "sha256": analysis_hash},
        "reference_fastas": {
            "rat": {"relative_path": "rat.fasta", "sha256": rat_hash, "release": "synthetic-1", "taxonomy_id": 10116},
            "human": {"relative_path": "human.fasta", "sha256": human_hash, "release": "synthetic-1", "taxonomy_id": 9606},
        },
        "orthology_snapshot": {
            "relative_path": "orthology.jsonl",
            "sha256": orthology_hash,
            "release": "synthetic-1",
            "source_taxonomy_id": 10116,
            "target_taxonomy_id": 9606,
        },
    }
    manifest_path = root / "bundle.json"
    _write(manifest_path, json.dumps(manifest, sort_keys=True))
    return root, manifest_path


def _mapped_record(ledger: dict, root: Path | None, manifest: Path | None) -> dict:
    context = map_feature_records(ledger, manifest_path=manifest, snapshot_root=root)
    return next(iter(context["feature_mappings"].values()))


def test_m0_missing_bundle_is_explicit_and_does_not_promote_direct_kinase() -> None:
    ledger = build_feature_provenance_ledger([_feature(accession="RAT1", gene="MAPK1", position="T3", peptide="MSTYAA")], ["1min"])
    context = map_feature_records(ledger)
    mapped = next(iter(context["feature_mappings"].values()))
    attached = attach_mapping_context(ledger, context)
    assert mapped["mapping_class"] == M0_NOT_EVALUABLE
    assert attached["feature_records"][0]["direct_kinase_attribution"]["status"] == "no_call"
    assert "feature_level_mapping_not_evaluable" in attached["feature_records"][0]["direct_kinase_attribution"]["reasons"]


def test_m1_exact_same_species_human_transgene_preserves_human_source(tmp_path: Path) -> None:
    sequence = "MSTYAA"
    root, manifest = _bundle(
        tmp_path,
        analysis=_fasta("sp|P06213|INSR_HUMAN", sequence, taxon=9606, gene="INSR"),
        rat=_fasta("ENSRAT1", "AAAAAA", taxon=10116, gene="RatOnly"),
        human=_fasta("ENSHUM1", sequence, taxon=9606, gene="INSR"),
        rows=[],
    )
    ledger = build_feature_provenance_ledger([_feature(accession="P06213", gene="INSR", position="T3", peptide="MSTYAA", taxon=9606)], ["1min"])
    mapped = _mapped_record(ledger, root, manifest)
    assert mapped["mapping_class"] == M1_EXACT
    assert mapped["source"]["fasta_taxonomy_id"] == 9606
    assert mapped["target"]["taxonomy_id"] == 9606
    assert mapped["reason"] == "same_species_explicit_analysis_fasta_entry"


def test_m1_mapping_never_bypasses_low_localization_direct_no_call_guard(tmp_path: Path) -> None:
    sequence = "MSTYAA"
    root, manifest = _bundle(
        tmp_path,
        analysis=_fasta("sp|P06213|INSR_HUMAN", sequence, taxon=9606, gene="INSR"),
        rat=_fasta("ENSRAT1", "AAAAAA", taxon=10116, gene="RatOnly"),
        human=_fasta("ENSHUM1", sequence, taxon=9606, gene="INSR"),
        rows=[],
    )
    row = _feature(accession="P06213", gene="INSR", position="T3", peptide="MSTYAA", taxon=9606)
    row["localization_probability"] = "0.20"
    ledger = build_feature_provenance_ledger([row], ["1min"])
    attached = attach_mapping_context(ledger, map_feature_records(ledger, manifest_path=manifest, snapshot_root=root))
    record = attached["feature_records"][0]
    assert record["mapping_evidence"]["mapping_class"] == M1_EXACT
    assert record["direct_kinase_attribution"]["status"] == "no_call"
    assert "localization_probability_below_class_I_threshold" in record["direct_kinase_attribution"]["reasons"]
    assert "curated_kinase_edge_provenance_absent" in record["direct_kinase_attribution"]["reasons"]


def test_m2_one_to_one_aligned_site_is_context_only(tmp_path: Path) -> None:
    source = "MSTYAA"
    target = "MQSTYAA"
    root, manifest = _bundle(
        tmp_path,
        analysis=_fasta("RAT1", source, taxon=10116, gene="MAPK1"),
        rat=_fasta("ENSRAT1", source, taxon=10116, gene="MAPK1"),
        human=_fasta("ENSHUM1", target, taxon=9606, gene="MAPK1"),
        rows=[_row(
            source_protein="ENSRAT1", target_protein="ENSHUM1", source_sequence=source,
            target_sequence=target, source_aligned="M-STYAA", target_aligned=target,
            cigar_line="1M1I5M",
        )],
    )
    ledger = build_feature_provenance_ledger([_feature(accession="RAT1", gene="MAPK1", position="T3", peptide="MSTYAA", taxon=10116)], ["1min"])
    context = map_feature_records(ledger, manifest_path=manifest, snapshot_root=root)
    mapped = next(iter(context["feature_mappings"].values()))
    attached = attach_mapping_context(ledger, context)
    assert mapped["mapping_class"] == M2_ALIGNED_ONE_TO_ONE
    assert mapped["target"]["position"] == 4
    assert attached["feature_records"][0]["direct_kinase_attribution"]["evidence_tier"] == "E_direct_kinase_no_call"
    assert "aligned_ortholog_context_does_not_permit_direct_kinase_attribution" in attached["feature_records"][0]["direct_kinase_attribution"]["reasons"]


def test_m3_gene_context_does_not_require_site_transfer_or_promote(tmp_path: Path) -> None:
    source = "MSTYAA"
    root, manifest = _bundle(
        tmp_path,
        analysis=_fasta("RAT1", source, taxon=10116, gene="MAPK1"),
        rat=_fasta("ENSRAT1", source, taxon=10116, gene="MAPK1"),
        human=_fasta("ENSHUM1", "MSTYGA", taxon=9606, gene="MAPK1"),
        rows=[_row(source_protein="ENSRAT1", target_protein="ENSHUM1", source_sequence="MSAYAA", target_sequence="MSTYGA")],
    )
    ledger = build_feature_provenance_ledger([_feature(accession="RAT1", gene="MAPK1", position="T3", peptide="MSTYAA", taxon=10116)], ["1min"])
    attached = attach_mapping_context(ledger, map_feature_records(ledger, manifest_path=manifest, snapshot_root=root))
    mapping = attached["feature_records"][0]["mapping_evidence"]
    assert mapping["mapping_class"] == M3_GENE_ONLY
    assert attached["feature_records"][0]["direct_kinase_attribution"]["status"] == "no_call"


def test_m4_ambiguous_m2_targets_never_selects_arbitrarily(tmp_path: Path) -> None:
    source = "MSTYAA"
    target_a = "MQSTYAA"
    target_b = "MRSTYAA"
    rows = [
        _row(source_protein="ENSRAT1", target_protein="ENSHUM1", source_sequence=source, target_sequence=target_a, target_gene="ENSG_A", source_aligned="M-STYAA", target_aligned=target_a, cigar_line="1M1I5M"),
        _row(source_protein="ENSRAT1", target_protein="ENSHUM2", source_sequence=source, target_sequence=target_b, target_gene="ENSG_B", source_aligned="M-STYAA", target_aligned=target_b, cigar_line="1M1I5M"),
    ]
    root, manifest = _bundle(
        tmp_path,
        analysis=_fasta("RAT1", source, taxon=10116, gene="MAPK1"),
        rat=_fasta("ENSRAT1", source, taxon=10116, gene="MAPK1"),
        human=_fasta("ENSHUM1", target_a, taxon=9606, gene="MAPK1") + _fasta("ENSHUM2", target_b, taxon=9606, gene="MAPK1"),
        rows=rows,
    )
    ledger = build_feature_provenance_ledger([_feature(accession="RAT1", gene="MAPK1", position="T3", peptide="MSTYAA", taxon=10116)], ["1min"])
    mapped = _mapped_record(ledger, root, manifest)
    assert mapped["mapping_class"] == M4_UNMAPPED_OR_AMBIGUOUS
    assert mapped["reason"] == "multiple_equally_eligible_target_sites"
    assert mapped["candidate_count"] == 2


def test_checksum_mismatch_is_m0_and_compact_summary_excludes_identity(tmp_path: Path) -> None:
    root, manifest = _bundle(
        tmp_path,
        analysis=_fasta("RAT1", "MSTYAA", taxon=10116, gene="MAPK1"),
        rat=_fasta("ENSRAT1", "MSTYAA", taxon=10116, gene="MAPK1"),
        human=_fasta("ENSHUM1", "MSTYAA", taxon=9606, gene="MAPK1"),
        rows=[],
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["reference_fastas"]["human"]["sha256"] = "0" * 64
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    ledger = build_feature_provenance_ledger([_feature(accession="RAT1", gene="MAPK1", position="T3", peptide="MSTYAA", taxon=10116)], ["1min"])
    attached = attach_mapping_context(ledger, map_feature_records(ledger, manifest_path=manifest, snapshot_root=root))
    compact = compact_summary(attached)
    assert attached["feature_records"][0]["mapping_evidence"]["mapping_class"] == M0_NOT_EVALUABLE
    assert compact["mapping_readiness"]["mapping_class_counts"]["M0"] == 1
    assert "RAT1" not in str(compact)
    assert "MSTYAA" not in str(compact)


def test_mapping_is_local_only_and_compact_projection_has_no_coordinate_or_accession(tmp_path: Path) -> None:
    source = "MSTYAA"
    root, manifest = _bundle(
        tmp_path,
        analysis=_fasta("RAT1", source, taxon=10116, gene="MAPK1"),
        rat=_fasta("ENSRAT1", source, taxon=10116, gene="MAPK1"),
        human=_fasta("ENSHUM1", source, taxon=9606, gene="MAPK1"),
        rows=[_row(source_protein="ENSRAT1", target_protein="ENSHUM1", source_sequence=source, target_sequence=source)],
    )
    source_code = Path(__file__).resolve().parents[1] / "species_site_mapping.py"
    code = source_code.read_text(encoding="utf-8")
    assert "import requests" not in code
    assert "import httpx" not in code
    assert "urllib.request" not in code
    ledger = build_feature_provenance_ledger([_feature(accession="RAT1", gene="MAPK1", position="T3", peptide="MSTYAA", taxon=10116)], ["1min"])
    attached = attach_mapping_context(ledger, map_feature_records(ledger, manifest_path=manifest, snapshot_root=root))
    compact = compact_summary(attached)
    assert compact["mapping_readiness"]["mapping_importer_contract_version"] == MAPPING_IMPORTER_CONTRACT_VERSION
    assert "RAT1" not in str(compact)
    assert "MSTYAA" not in str(compact)
    assert "T3" not in str(compact)
