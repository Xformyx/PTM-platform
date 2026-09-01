#!/usr/bin/env python3
"""Build a local-only P2 iPTMnet release 6.2 relation bundle.

This offline utility transforms an operator-acquired, CC BY-NC-SA 4.0
iPTMnet static download. It must never run in an Order/RAG/Report worker and
does not download, query, or otherwise access the network.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


RELEASE = "6.2"
SOURCE_CONTRACT = "ptm_kinase_relation_source_bundle.v1"
ROW_SCHEMA = "ptm_kinase_relation_rows.v1"
CROSS_REFERENCE_SCHEMA = "ptm_kinase_relation_cross_reference.v1"
IDENTITY_SCOPE = "accession_site_exact_iPTMnet_release_6_2"
TAXONOMY_BY_ORGANISM = {
    "Homo sapiens (Human)": 9606,
    "Mus musculus (Mouse)": 10090,
    "Rattus norvegicus (Rat)": 10116,
}
SITE_RE = re.compile(r"^([STY])(\d+)$")
PMID_RE = re.compile(r"\d+")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def split_pmids(value: str) -> list[str]:
    return sorted({f"PMID:{item}" for item in PMID_RE.findall(value or "")})


def read_proteins(path: Path) -> dict[str, dict[str, Any]]:
    proteins: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            fields = raw_line.rstrip("\n").split("\t")
            if len(fields) != 7:
                raise ValueError(f"protein.txt line {line_number} does not have 7 columns")
            accession, uniprot_id, protein_name, gene_name, organism, pro_id, reviewed = fields
            taxonomy_id = TAXONOMY_BY_ORGANISM.get(organism)
            if not taxonomy_id or not accession:
                continue
            if accession in proteins:
                raise ValueError(f"protein.txt line {line_number} duplicates accession {accession}")
            proteins[accession] = {
                "accession": accession,
                "uniprot_id": uniprot_id,
                "gene_name": gene_name,
                "organism": organism,
                "taxonomy_id": taxonomy_id,
                "pro_id": pro_id,
                "reviewed_status": reviewed,
                "source_line_number": line_number,
                "source_record_sha256": sha256_text(raw_line.rstrip("\n")),
            }
    return proteins


def relation_rows(ptm_path: Path, proteins: dict[str, dict[str, Any]]) -> Iterable[dict[str, Any]]:
    grouped: dict[tuple[str, int, str, int, str, int], dict[str, Any]] = {}
    with ptm_path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            fields = raw_line.rstrip("\n").split("\t")
            if len(fields) != 10:
                raise ValueError(f"ptm.txt line {line_number} does not have 10 columns")
            ptm_type, source, substrate_ac, substrate_gene, organism, site, enzyme_ac, enzyme_gene, note, pmid = fields
            if ptm_type != "PHOSPHORYLATION" or not enzyme_ac:
                continue
            site_match = SITE_RE.fullmatch(site)
            if not site_match:
                continue
            substrate = proteins.get(substrate_ac)
            enzyme = proteins.get(enzyme_ac)
            if not substrate or not enzyme or substrate["taxonomy_id"] != enzyme["taxonomy_id"]:
                continue
            pmids = split_pmids(pmid)
            if not pmids:
                continue
            residue, position_text = site_match.groups()
            position = int(position_text)
            key = (enzyme_ac, enzyme["taxonomy_id"], substrate_ac, substrate["taxonomy_id"], residue, position)
            if key not in grouped:
                identity_token = f"iPTMnet-release-{RELEASE}:{substrate_ac}"
                grouped[key] = {
                    "edge_id": "iptmnet-r6.2-" + sha256_text("|".join(map(str, key)))[:24],
                    "relation_type": "kinase_substrate_phosphorylation",
                    "kinase_accession": enzyme_ac,
                    "kinase_taxonomy_id": enzyme["taxonomy_id"],
                    "substrate_accession": substrate_ac,
                    "substrate_taxonomy_id": substrate["taxonomy_id"],
                    "residue": residue,
                    "position": position,
                    "substrate_isoform_or_sequence_id": identity_token,
                    "source_identity_scope": IDENTITY_SCOPE,
                    "evidence_reference_ids": set(),
                    "source_provenance": {
                        "source_dataset": "iPTMnet release 6.2",
                        "source_file": "source_original/ptm.txt",
                        "source_labels": set(),
                        "source_line_numbers": [],
                        "source_row_sha256": [],
                        "notes": set(),
                    },
                }
            record = grouped[key]
            record["evidence_reference_ids"].update(pmids)
            record["source_provenance"]["source_labels"].add(source)
            record["source_provenance"]["source_line_numbers"].append(line_number)
            record["source_provenance"]["source_row_sha256"].append(sha256_text(raw_line.rstrip("\n")))
            if note:
                record["source_provenance"]["notes"].add(note)
    for record in grouped.values():
        record["evidence_reference_ids"] = sorted(record["evidence_reference_ids"])
        provenance = record["source_provenance"]
        provenance["source_labels"] = sorted(provenance["source_labels"])
        provenance["source_line_numbers"] = sorted(provenance["source_line_numbers"])
        provenance["source_row_sha256"] = sorted(provenance["source_row_sha256"])
        provenance["notes"] = sorted(provenance["notes"])
        yield record


def write_jsonl_gz(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    count = 0
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
            count += 1
    return count


def build(snapshot_root: Path) -> dict[str, Any]:
    source = snapshot_root / "source_original"
    required = {name: source / name for name in ("readme.txt", "ptm.txt", "score.txt", "protein.txt", "retrieval_metadata.txt")}
    missing = [name for name, path in required.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing iPTMnet source artifacts: {', '.join(missing)}")
    readme = required["readme.txt"].read_text(encoding="utf-8")
    if "release 6.2" not in readme or "CC BY-NC-SA 4.0" not in readme:
        raise ValueError("readme does not identify iPTMnet release 6.2 under CC BY-NC-SA 4.0")
    derived = snapshot_root / "derived"
    derived.mkdir(parents=True, exist_ok=True)
    proteins = read_proteins(required["protein.txt"])
    rows = sorted(
        relation_rows(required["ptm.txt"], proteins),
        key=lambda row: (row["substrate_taxonomy_id"], row["substrate_accession"], row["position"], row["kinase_accession"]),
    )
    relation_path = derived / "iptmnet_release_6_2_phosphorylation_enzyme_site.jsonl.gz"
    edge_count = write_jsonl_gz(relation_path, rows)
    substrate_keys = {(row["substrate_accession"], row["substrate_taxonomy_id"]) for row in rows}
    cross_references = [
        {
            "source_accession": accession,
            "source_taxonomy_id": taxonomy_id,
            "relation_accession": accession,
            "relation_taxonomy_id": taxonomy_id,
            "relation_identity_scope": IDENTITY_SCOPE,
            "relation_isoform_or_sequence_id": f"iPTMnet-release-{RELEASE}:{accession}",
            "source_protein_record_sha256": proteins[accession]["source_record_sha256"],
            "source_protein_line_number": proteins[accession]["source_line_number"],
            "source_file": "source_original/protein.txt",
        }
        for accession, taxonomy_id in sorted(substrate_keys)
    ]
    crossref_path = derived / "iptmnet_release_6_2_accession_site_cross_reference.jsonl.gz"
    crossref_count = write_jsonl_gz(crossref_path, cross_references)
    original_hashes = {f"source_original/{name}": sha256(path) for name, path in required.items()}
    manifest = {
        "contract_version": SOURCE_CONTRACT,
        "bundle_id": "iptmnet_release_6_2_phosphorylation_enzyme_site",
        "source_name": "iPTMnet",
        "source_url": "https://research.bioinformatics.udel.edu/iptmnet/download",
        "license_spdx_or_text": "CC-BY-NC-SA-4.0",
        "license_evidence_url": "https://research.bioinformatics.udel.edu/iptmnet/download",
        "release_or_retrieval_date": "release 6.2; retrieved per source_original/retrieval_metadata.txt",
        "transform_description": (
            "Offline transform of iPTMnet release 6.2 static ptm.txt/protein.txt; retains only PHOSPHORYLATION "
            "rows with same-taxonomy canonical enzyme/substrate accessions, one S/T/Y coordinate and at least one PMID. "
            "Duplicate exact enzyme-substrate-site rows aggregate source labels, original row hashes and PMIDs; no score is used. "
            "Identity scope is accession/site exact for iPTMnet release 6.2, not isoform or sequence exact."
        ),
        "original_source_artifacts": original_hashes,
        "relation_snapshot": {
            "schema_version": ROW_SCHEMA,
            "relative_path": str(relation_path.relative_to(snapshot_root)),
            "sha256": sha256(relation_path),
            "row_count": edge_count,
        },
        "cross_reference_snapshot": {
            "schema_version": CROSS_REFERENCE_SCHEMA,
            "relative_path": str(crossref_path.relative_to(snapshot_root)),
            "sha256": sha256(crossref_path),
            "row_count": crossref_count,
        },
    }
    manifest_path = snapshot_root / "iptmnet_release_6_2_p2_bundle.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    notice = snapshot_root / "NOTICE_CC_BY_NC_SA_4.0.md"
    notice.write_text(
        "# iPTMnet release 6.2 P2 source attribution\n\n"
        "This local research-only derived bundle incorporates iPTMnet release 6.2 data. It is distributed under "
        "[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). It may not be used for commercial "
        "purposes. Redistribution must provide attribution, link the license, indicate changes and share adaptations "
        "under the same license. The original iPTMnet source labels retained in each full-ledger candidate record "
        "identify databases that require citation.\n\n"
        "Source: https://research.bioinformatics.udel.edu/iptmnet/download\n"
        "Release: iPTMnet 6.2\n"
        "Transform: scripts/build_p2_iptmnet_release_6_2_bundle.py\n",
        encoding="utf-8",
    )
    return {"manifest_path": str(manifest_path), "edge_count": edge_count, "cross_reference_count": crossref_count}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", required=True, type=Path)
    args = parser.parse_args()
    result = build(args.snapshot_root)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
