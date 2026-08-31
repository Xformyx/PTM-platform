"""Regression coverage for the offline release-116 strict-tree bundle builder."""

from __future__ import annotations

import gzip
import importlib.util
import json
import sys
from pathlib import Path

from ptm_shared.species_site_mapping import attach_mapping_context, map_feature_records
from ptm_shared.kinase_evidence_ledger import build_feature_provenance_ledger


BUILDER = Path(__file__).resolve().parents[2] / "scripts" / "build_p1_release_116_strict_orthology_snapshot.py"


def _load_builder():
    spec = importlib.util.spec_from_file_location("p1_release_116_builder", BUILDER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _gz(path: Path, content: str) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(content)


def test_strict_tree_builder_writes_checksum_pinned_m3_only_bundle(tmp_path: Path, monkeypatch) -> None:
    builder = _load_builder()
    source = tmp_path / "strict.orthoxml.xml.gz"
    rat = tmp_path / "rat.fa.gz"
    human = tmp_path / "human.fa.gz"
    analysis = tmp_path / "analysis.fa"
    _gz(rat, ">ENSRNOP0001.1 gene:ENSRNOG0001.1 gene_symbol:RatA\nMSTYAA\n")
    _gz(human, ">ENSP0001.1 gene:ENSG0001.1 gene_symbol:HUMANA\nMSAYAA\n")
    analysis.write_text(">sp|RAT1|RATA_RAT OS=Rattus norvegicus OX=10116 GN=RatA\nMSTYAA\n", encoding="utf-8")
    _gz(source, """<?xml version=\"1.0\" encoding=\"utf-8\"?>
<orthoXML xmlns=\"http://orthoXML.org/2011/\" origin=\"Ensembl Compara\" version=\"0.3\" originVersion=\"116\">
 <species name=\"rattus_norvegicus\" NCBITaxId=\"10116\"><database name=\"Ensembl\" version=\"116\"><genes><gene id=\"r\" protId=\"ENSRNOP0001.1\"/></genes></database></species>
 <species name=\"homo_sapiens\" NCBITaxId=\"9606\"><database name=\"Ensembl\" version=\"116\"><genes><gene id=\"h\" protId=\"ENSP0001.1\"/></genes></database></species>
 <groups><orthologGroup id=\"1\"><geneRef id=\"r\"/><geneRef id=\"h\"/></orthologGroup></groups>
</orthoXML>""")
    output = tmp_path / "bundle"
    monkeypatch.setattr(sys, "argv", [
        str(BUILDER), "--strict-orthoxml", str(source), "--rat-fasta", str(rat), "--human-fasta", str(human),
        "--analysis-fasta", str(analysis), "--output-root", str(output), "--bundle-id", "synthetic-rat-human-116",
        "--source-url", "https://example.test/strict.orthoxml.xml.gz", "--retrieved-at", "2026-08-31T14:28:37Z",
    ])
    assert builder.main() == 0
    manifest = json.loads((output / "bundle.json").read_text(encoding="utf-8"))
    snapshot = output / manifest["orthology_snapshot"]["relative_path"]
    with gzip.open(snapshot, "rt", encoding="utf-8") as handle:
        row = json.loads(handle.readline())
    assert row["homology_type"] == "ortholog_one2one"
    assert row["is_high_confidence"] is False
    assert row["source_aligned"] == row["target_aligned"] == row["cigar_line"] == ""
    assert manifest["orthology_snapshot"]["mapping_ceiling"] == "M3_gene_only_context"
    ledger = build_feature_provenance_ledger([{
        "gene": "RatA", "position": "T3", "condition": "audit", "log2fc": 0.0,
        "protein_group": "RAT1", "modified_sequence": "MSTYAA", "precursor_id": "audit-rat1",
        "all_reported_ptm_positions": "T3", "localization_probability": 0.99, "fasta_taxonomy_id": 10116,
    }], ["audit"])
    attached = attach_mapping_context(ledger, map_feature_records(ledger, manifest_path=output / "bundle.json", snapshot_root=output))
    assert attached["feature_records"][0]["mapping_evidence"]["mapping_class"] == "M3_gene_only_context"
    assert attached["feature_records"][0]["direct_kinase_attribution"]["status"] == "no_call"
