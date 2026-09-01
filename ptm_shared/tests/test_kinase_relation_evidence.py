"""P2 curated relation provenance must never create a direct kinase call."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

from ptm_shared.kinase_evidence_ledger import build_feature_provenance_ledger, compact_summary
from ptm_shared.kinase_relation_evidence import (
    R0_NOT_EVALUABLE,
    R1_INELIGIBLE,
    R2_NO_EXACT_EDGE,
    R3_CANDIDATE_SET,
    RelationSourceBundleError,
    attach_relation_evidence,
    load_relation_source_bundle,
    map_feature_relations,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _feature(*, localization: float = 0.99, position: str = "T3", multi: bool = False) -> dict:
    return {
        "gene": "INSR", "position": position, "condition": "1min", "log2fc": 0.3,
        "protein_group": "P06213", "modified_sequence": "MSTYAA[Phospho]" if multi else "MSTYAA",
        "precursor_id": "p1", "all_reported_ptm_positions": position,
        "localization_probability": localization, "fasta_taxonomy_id": 9606,
    }


def _m1_ledger(*, localization: float = 0.99, position: str = "T3", mapping_class: str = "M1", relation_identity: bool = True) -> dict:
    ledger = build_feature_provenance_ledger([_feature(localization=localization, position=position)], ["1min"])
    target = {"taxonomy_id": 9606, "target_accession": "P06213"} if relation_identity else {}
    if relation_identity:
        target.update({"target_relation_accession": "P06213", "target_relation_isoform_or_sequence_id": "P06213-1"})
    record = ledger["feature_records"][0]
    record["mapping_evidence"] = {"mapping_class_code": mapping_class, "target": target}
    return ledger


def _row(*, edge_id: str = "edge-1", position: int = 3, kinase: str = "KIN1") -> dict:
    return {
        "edge_id": edge_id,
        "relation_type": "kinase_substrate_phosphorylation",
        "kinase_accession": kinase,
        "kinase_taxonomy_id": 9606,
        "substrate_accession": "P06213",
        "substrate_taxonomy_id": 9606,
        "residue": "T",
        "position": position,
        "substrate_isoform_or_sequence_id": "P06213-1",
        "source_identity_scope": "isoform_or_sequence_exact",
        "evidence_reference_ids": ["PMID:1"],
        "source_provenance": {"source_row_id": edge_id, "evidence_type": "curated"},
    }


def _bundle(tmp_path: Path, rows: list[dict], *, include_license: bool = True) -> tuple[Path, Path]:
    root = tmp_path / "bundle"
    root.mkdir(parents=True)
    snapshot = root / "relations.jsonl.gz"
    with gzip.open(snapshot, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    manifest = {
        "contract_version": "ptm_kinase_relation_source_bundle.v1",
        "bundle_id": "synthetic-p2-v1",
        "source_name": "synthetic licensed relation source",
        "source_url": "https://example.test/source",
        "license_spdx_or_text": "CC-BY-4.0" if include_license else "",
        "license_evidence_url": "https://example.test/license",
        "release_or_retrieval_date": "2026-08-31",
        "transform_description": "synthetic P2 test source",
        "relation_snapshot": {
            "schema_version": "ptm_kinase_relation_rows.v1",
            "relative_path": snapshot.name,
            "sha256": _sha(snapshot),
        },
    }
    cross_reference = root / "cross_reference.jsonl.gz"
    with gzip.open(cross_reference, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "source_accession": "P06213",
            "source_taxonomy_id": 9606,
            "relation_accession": "P06213",
            "relation_taxonomy_id": 9606,
            "relation_identity_scope": "isoform_or_sequence_exact",
            "relation_isoform_or_sequence_id": "P06213-1",
            "source_protein_record_sha256": "a" * 64,
            "source_protein_line_number": 1,
            "source_file": "protein.tsv",
        }, sort_keys=True) + "\n")
    manifest["cross_reference_snapshot"] = {
        "schema_version": "ptm_kinase_relation_cross_reference.v1",
        "relative_path": cross_reference.name,
        "sha256": _sha(cross_reference),
    }
    manifest_path = root / "bundle.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    return root, manifest_path


def _relation_result(ledger: dict, root: Path | None, manifest: Path | None) -> dict:
    context = map_feature_relations(ledger, manifest_path=manifest, snapshot_root=root)
    return next(iter(context["feature_relations"].values()))


def test_exact_m1_p0_ready_local_edge_yields_r3_candidate_set_but_no_direct_call(tmp_path: Path) -> None:
    root, manifest = _bundle(tmp_path, [_row(), _row(edge_id="edge-2", kinase="KIN2")])
    ledger = _m1_ledger()
    context = map_feature_relations(ledger, manifest_path=manifest, snapshot_root=root)
    result = next(iter(context["feature_relations"].values()))
    attached = attach_relation_evidence(ledger, context)
    record = attached["feature_records"][0]
    compact = compact_summary(attached)
    assert result["relation_class"] == R3_CANDIDATE_SET
    assert result["candidate_count"] == 2
    assert record["direct_kinase_attribution"]["status"] == "no_call"
    assert "curated_kinase_candidate_set_requires_p3_allocation_policy" in record["direct_kinase_attribution"]["reasons"]
    assert compact["relation_readiness"]["relation_class_counts"] == {"R0": 0, "R1": 0, "R2": 0, "R3": 1, "R4": 0}
    assert "KIN1" not in json.dumps(compact)
    assert "P06213" not in json.dumps(compact)
    assert "PMID:1" not in json.dumps(compact)


def test_p1_m1_target_accession_and_taxon_are_authorized_only_by_validated_cross_reference(tmp_path: Path) -> None:
    root, manifest = _bundle(tmp_path, [_row()])
    ledger = _m1_ledger()
    target = ledger["feature_records"][0]["mapping_evidence"]["target"]
    target.pop("target_relation_accession")
    target.pop("target_relation_isoform_or_sequence_id")
    result = _relation_result(ledger, root, manifest)
    assert result["relation_class"] == R3_CANDIDATE_SET


def test_m2_or_m3_context_can_never_join_a_p2_edge(tmp_path: Path) -> None:
    root, manifest = _bundle(tmp_path, [_row()])
    for mapping_class in ("M0", "M2", "M3", "M4"):
        result = _relation_result(_m1_ledger(mapping_class=mapping_class), root, manifest)
        assert result["relation_class"] == R1_INELIGIBLE
        assert result["relation_status"] == "p1_mapping_not_eligible_for_exact_relation_join"


def test_p0_localization_or_target_relation_identity_failure_is_r1(tmp_path: Path) -> None:
    root, manifest = _bundle(tmp_path, [_row()])
    low_localization = _relation_result(_m1_ledger(localization=0.20), root, manifest)
    missing_relation_identity = _relation_result(_m1_ledger(relation_identity=False), root, manifest)
    assert low_localization["relation_class"] == R1_INELIGIBLE
    assert low_localization["reason"] == "p0_localization_not_class_I"
    assert missing_relation_identity["relation_class"] == R1_INELIGIBLE
    assert missing_relation_identity["reason"] == "p1_exact_target_accession_or_taxonomy_missing"


def test_exact_m1_with_no_local_edge_is_r2(tmp_path: Path) -> None:
    root, manifest = _bundle(tmp_path, [_row(position=4)])
    result = _relation_result(_m1_ledger(), root, manifest)
    assert result["relation_class"] == R2_NO_EXACT_EDGE
    assert result["candidate_count"] == 0


def test_missing_bundle_is_explicit_r0_and_no_call(tmp_path: Path) -> None:
    ledger = _m1_ledger()
    context = map_feature_relations(ledger)
    attached = attach_relation_evidence(ledger, context)
    result = next(iter(context["feature_relations"].values()))
    assert result["relation_class"] == R0_NOT_EVALUABLE
    assert attached["feature_records"][0]["direct_kinase_attribution"]["status"] == "no_call"
    assert compact_summary(attached)["relation_readiness"]["relation_class_counts"]["R0"] == 1


def test_manifest_license_hash_and_duplicate_edge_fail_closed(tmp_path: Path) -> None:
    root, manifest = _bundle(tmp_path, [_row()], include_license=False)
    with __import__("pytest").raises(RelationSourceBundleError, match="license_spdx_or_text"):
        load_relation_source_bundle(manifest, snapshot_root=root)
    assert _relation_result(_m1_ledger(), root, manifest)["relation_class"] == R0_NOT_EVALUABLE

    root, manifest = _bundle(tmp_path / "hash", [_row()])
    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_data["relation_snapshot"]["sha256"] = "0" * 64
    manifest.write_text(json.dumps(manifest_data), encoding="utf-8")
    assert _relation_result(_m1_ledger(), root, manifest)["relation_class"] == R0_NOT_EVALUABLE

    root, manifest = _bundle(tmp_path / "duplicate", [_row(), _row(edge_id="edge-2")])
    assert _relation_result(_m1_ledger(), root, manifest)["relation_class"] == R0_NOT_EVALUABLE

    root, manifest = _bundle(tmp_path / "crossref", [_row()])
    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_data.pop("cross_reference_snapshot")
    manifest.write_text(json.dumps(manifest_data), encoding="utf-8")
    assert _relation_result(_m1_ledger(), root, manifest)["relation_class"] == R0_NOT_EVALUABLE

    malformed = _row()
    malformed.pop("source_identity_scope")
    root, manifest = _bundle(tmp_path / "identity-scope", [malformed])
    assert _relation_result(_m1_ledger(), root, manifest)["relation_class"] == R0_NOT_EVALUABLE


def test_relation_importer_has_no_live_network_client() -> None:
    module = Path(__file__).resolve().parents[1] / "kinase_relation_evidence.py"
    code = module.read_text(encoding="utf-8")
    assert "requests" not in code
    assert "httpx" not in code
    assert "urllib.request" not in code
