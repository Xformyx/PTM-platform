#!/usr/bin/env python3
"""Build a frozen, local P1 rat→human context snapshot from Ensembl release 116.

This is an *offline acquisition* utility, never imported by an Order worker.
It reads local, downloaded Ensembl resources and writes a checksum-pinned P1
bundle below ``--output-root``. The strict OrthoXML export establishes an
official tree-compliant gene/protein pairing, but it does not expose the
``is_high_confidence`` field or Ensembl's protein alignment/CIGAR. To prevent
fabrication, every output record has ``is_high_confidence=false`` and blank
alignment/CIGAR fields. The production importer may therefore emit M3
gene-context records, never M2, from this bundle.

An M2-capable bundle must be generated later from an Ensembl Compara source
that explicitly supplies high-confidence and aligned protein/CIGAR evidence.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from xml.sax import make_parser
from xml.sax.handler import ContentHandler


RELEASE = "116"
SOURCE_TAXONOMY_ID = 10116
TARGET_TAXONOMY_ID = 9606
BUNDLE_CONTRACT_VERSION = "ptm_species_site_mapping_source_bundle.v1"
ORTHOLOGY_SNAPSHOT_FILENAME = "rat_to_human_orthology.strict_tree_context.jsonl.gz"


@dataclass(frozen=True)
class ProteinEntry:
    protein_id: str
    gene_id: str
    gene_symbol: str | None
    sequence: str


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_id(value: str) -> str:
    return value.strip().upper().split(".", 1)[0]


def fasta_entries(path: Path) -> dict[str, ProteinEntry]:
    """Index Ensembl peptide FASTA by version-independent stable protein ID."""

    entries: dict[str, ProteinEntry] = {}
    header: str | None = None
    parts: list[str] = []

    def emit() -> None:
        if not header:
            return
        fields = header[1:].split()
        if not fields:
            return
        protein = canonical_id(fields[0])
        gene_match = re.search(r"\bgene:([^\s]+)", header)
        if not gene_match:
            return
        symbol_match = re.search(r"\bgene_symbol:([^\s]+)", header)
        sequence = "".join(parts).upper()
        if sequence:
            entries[protein] = ProteinEntry(
                protein_id=fields[0].upper(),
                gene_id=gene_match.group(1).upper(),
                gene_symbol=symbol_match.group(1) if symbol_match else None,
                sequence=sequence,
            )

    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if line.startswith(">"):
                emit()
                header, parts = line, []
            elif line:
                parts.append(line)
    emit()
    return entries


class _StrictPairHandler(ContentHandler):
    """SAX handler that retains only rat/human gene references and pairs."""

    def __init__(self) -> None:
        super().__init__()
        self.active_taxonomy: int | None = None
        self.gene_taxon_and_protein: dict[str, tuple[int, str]] = {}
        self.group_members: list[list[tuple[int, str]]] = []
        self.pairs: list[tuple[str, str]] = []
        self.seen: set[tuple[str, str]] = set()

    def startElement(self, name: str, attrs) -> None:  # noqa: N802 (SAX API)
        tag = name.rsplit(":", 1)[-1]
        if tag == "species":
            try:
                self.active_taxonomy = int(attrs.get("NCBITaxId", ""))
            except ValueError:
                self.active_taxonomy = None
        elif tag == "gene" and self.active_taxonomy in {SOURCE_TAXONOMY_ID, TARGET_TAXONOMY_ID}:
            gene_ref = attrs.get("id")
            protein_id = attrs.get("protId")
            if gene_ref and protein_id:
                self.gene_taxon_and_protein[gene_ref] = (self.active_taxonomy, protein_id)
        elif tag == "orthologGroup":
            self.group_members.append([])
        elif tag == "geneRef" and self.group_members:
            member = self.gene_taxon_and_protein.get(attrs.get("id", ""))
            if member is not None:
                self.group_members[-1].append(member)

    def endElement(self, name: str) -> None:  # noqa: N802 (SAX API)
        tag = name.rsplit(":", 1)[-1]
        if tag == "species":
            self.active_taxonomy = None
        elif tag == "orthologGroup" and self.group_members:
            members = self.group_members.pop()
            source = [member for member in members if member[0] == SOURCE_TAXONOMY_ID]
            target = [member for member in members if member[0] == TARGET_TAXONOMY_ID]
            if len(source) == 1 and len(target) == 1:
                pair = (source[0][1], target[0][1])
                if pair not in self.seen:
                    self.seen.add(pair)
                    self.pairs.append(pair)


def strict_pairs(orthoxml_path: Path) -> Iterator[tuple[str, str]]:
    """Yield unique rat/human pairs without materialising the XML document."""

    handler = _StrictPairHandler()
    parser = make_parser()
    parser.setContentHandler(handler)
    with gzip.open(orthoxml_path, "rb") as handle:
        parser.parse(handle)
    yield from handler.pairs


def copy_input(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != destination.resolve():
        shutil.copy2(source, destination)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict-orthoxml", type=Path, required=True)
    parser.add_argument("--rat-fasta", type=Path, required=True)
    parser.add_argument("--human-fasta", type=Path, required=True)
    parser.add_argument("--analysis-fasta", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--bundle-id", required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--retrieved-at", required=True, help="UTC ISO-8601 acquisition timestamp")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    for input_path in (args.strict_orthoxml, args.rat_fasta, args.human_fasta, args.analysis_fasta):
        if not input_path.is_file():
            raise SystemExit(f"required local input missing: {input_path}")
    try:
        retrieved_at = datetime.fromisoformat(args.retrieved_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise SystemExit("--retrieved-at must be ISO-8601") from error
    if retrieved_at.tzinfo is None:
        raise SystemExit("--retrieved-at must include a timezone")

    root = args.output_root.resolve()
    if root.exists() and any(root.iterdir()):
        raise SystemExit(f"refusing to overwrite non-empty output root: {root}")
    root.mkdir(parents=True, exist_ok=False)
    reference_dir = root / "ensembl_116"
    analysis_dir = root / "analysis"
    compara_dir = root / "compara_116"
    compara_dir.mkdir(parents=True, exist_ok=False)
    rat_output = reference_dir / "Rattus_norvegicus.GRCr8.pep.all.fa.gz"
    human_output = reference_dir / "Homo_sapiens.GRCh38.pep.all.fa.gz"
    analysis_output = analysis_dir / args.analysis_fasta.name
    copy_input(args.rat_fasta, rat_output)
    copy_input(args.human_fasta, human_output)
    copy_input(args.analysis_fasta, analysis_output)

    print("Indexing local release-116 peptide FASTAs", file=sys.stderr)
    rat_entries = fasta_entries(rat_output)
    human_entries = fasta_entries(human_output)
    if not rat_entries or not human_entries:
        raise SystemExit("reference FASTA index is empty; refusing to create a bundle")

    orthology_output = compara_dir / ORTHOLOGY_SNAPSHOT_FILENAME
    paired_count = 0
    skipped_missing_reference_count = 0
    print("Streaming strict OrthoXML and extracting rat→human pairs", file=sys.stderr)
    with gzip.open(orthology_output, "wt", encoding="utf-8", newline="\n") as output:
        for rat_protein, human_protein in strict_pairs(args.strict_orthoxml):
            source = rat_entries.get(canonical_id(rat_protein))
            target = human_entries.get(canonical_id(human_protein))
            if source is None or target is None:
                skipped_missing_reference_count += 1
                continue
            row = {
                "source_ensembl_gene_id": source.gene_id,
                "target_ensembl_gene_id": target.gene_id,
                "source_ensembl_protein_id": source.protein_id,
                "target_ensembl_protein_id": target.protein_id,
                "homology_type": "ortholog_one2one",
                "is_high_confidence": False,
                "source_taxonomy_id": SOURCE_TAXONOMY_ID,
                "target_taxonomy_id": TARGET_TAXONOMY_ID,
                "source_sequence": source.sequence,
                "target_sequence": target.sequence,
                "source_aligned": "",
                "target_aligned": "",
                "cigar_line": "",
                "source_gene_symbol": source.gene_symbol,
                "target_gene_symbol": target.gene_symbol,
                "orthology_provenance": {
                    "provider": "Ensembl Compara",
                    "release": RELEASE,
                    "source_export": "protein_default.allhomologies_strict.orthoxml.xml.gz",
                    "tree_compliant": True,
                    "high_confidence_available": False,
                    "alignment_cigar_available": False,
                    "mapping_ceiling": "M3_gene_only_context",
                },
            }
            output.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
            paired_count += 1
    if paired_count == 0:
        raise SystemExit("no rat→human pairs could be reconciled to the release-116 peptide FASTAs")

    manifest = {
        "contract_version": BUNDLE_CONTRACT_VERSION,
        "bundle_id": args.bundle_id,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "analysis_reference": {
            "relative_path": str(analysis_output.relative_to(root)),
            "sha256": sha256(analysis_output),
            "order_species_taxonomy_id": SOURCE_TAXONOMY_ID,
            "mixed_taxa_allowed": [SOURCE_TAXONOMY_ID, TARGET_TAXONOMY_ID],
        },
        "reference_fastas": {
            "rattus_norvegicus": {
                "relative_path": str(rat_output.relative_to(root)),
                "sha256": sha256(rat_output),
                "provider": "Ensembl",
                "release": RELEASE,
                "assembly": "GRCr8",
                "taxonomy_id": SOURCE_TAXONOMY_ID,
            },
            "homo_sapiens": {
                "relative_path": str(human_output.relative_to(root)),
                "sha256": sha256(human_output),
                "provider": "Ensembl",
                "release": RELEASE,
                "assembly": "GRCh38",
                "taxonomy_id": TARGET_TAXONOMY_ID,
            },
        },
        "orthology_snapshot": {
            "relative_path": str(orthology_output.relative_to(root)),
            "sha256": sha256(orthology_output),
            "provider": "Ensembl Compara",
            "release": RELEASE,
            "source_taxonomy_id": SOURCE_TAXONOMY_ID,
            "target_taxonomy_id": TARGET_TAXONOMY_ID,
            "retrieval_query_contract": "offline strict OrthoXML release-116 extract; no high-confidence or aligned/CIGAR field available",
            "source_artifact_url": args.source_url,
            "source_artifact_sha256": sha256(args.strict_orthoxml),
            "source_artifact_retrieved_at": retrieved_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "mapping_ceiling": "M3_gene_only_context",
        },
        "build_provenance": {
            "builder": Path(__file__).name,
            "builder_contract": "p1_release_116_strict_orthology_offline_builder.v1",
            "strict_pair_count": paired_count,
            "skipped_missing_reference_count": skipped_missing_reference_count,
            "runtime_network_access": False,
            "benchmark_truth_used": False,
            "known_relation_registry_used": False,
            "rag_or_llm_used": False,
        },
    }
    manifest_path = root / "bundle.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "bundle_root": str(root),
        "manifest": str(manifest_path),
        "manifest_sha256": sha256(manifest_path),
        "orthology_snapshot": str(orthology_output),
        "orthology_snapshot_sha256": sha256(orthology_output),
        "strict_pair_count": paired_count,
        "skipped_missing_reference_count": skipped_missing_reference_count,
        "mapping_ceiling": "M3_gene_only_context",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
