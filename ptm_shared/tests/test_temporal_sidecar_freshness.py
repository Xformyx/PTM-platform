from __future__ import annotations

import json
from pathlib import Path

from ptm_shared.temporal_sidecar_freshness import (
    CURRENT_DYNAMIC_CONFIG_SHA256,
    CURRENT_DYNAMIC_CONTRACT_VERSION,
    api_has_local_reference_bundle_access,
    compact_dynamic_is_current,
    evaluate_temporal_evidence_readiness,
    full_dynamic_is_current,
    full_sidecar_has_validated_local_reference_bundles,
    load_preservable_local_reference_sidecar,
)
from ptm_shared.kinase_evidence_ledger import CONTRACT_VERSION as KINASE_LEDGER_CONTRACT_VERSION
from ptm_shared.species_site_mapping import MAPPING_IMPORTER_CONTRACT_VERSION
from ptm_shared.kinase_relation_evidence import RELATION_IMPORTER_CONTRACT_VERSION
from ptm_shared.kinase_candidate_allocation import ALLOCATION_CONTRACT_VERSION


def _current_compact() -> dict:
    return {
        "dynamic_co_wave_transition_contract_version": CURRENT_DYNAMIC_CONTRACT_VERSION,
        "dynamic_co_wave_transition_config_sha256": CURRENT_DYNAMIC_CONFIG_SHA256,
        "kinase_feature_evidence_ledger_summary": {
            "contract_version": KINASE_LEDGER_CONTRACT_VERSION,
            "mapping_readiness": {
                "mapping_importer_contract_version": MAPPING_IMPORTER_CONTRACT_VERSION,
            },
            "relation_readiness": {
                "relation_importer_contract_version": RELATION_IMPORTER_CONTRACT_VERSION,
            },
            "candidate_allocation_readiness": {
                "allocation_contract_version": ALLOCATION_CONTRACT_VERSION,
            },
        },
    }


def _current_full() -> dict:
    return {
        "dynamic_co_wave_transition": {
            "contract_version": CURRENT_DYNAMIC_CONTRACT_VERSION,
            "provenance": {"config_sha256": CURRENT_DYNAMIC_CONFIG_SHA256},
        },
        "kinase_feature_evidence_ledger": {
            "contract_version": KINASE_LEDGER_CONTRACT_VERSION,
            "mapping_importer": {
                "mapping_importer_contract_version": MAPPING_IMPORTER_CONTRACT_VERSION,
            },
            "relation_importer": {
                "relation_importer_contract_version": RELATION_IMPORTER_CONTRACT_VERSION,
            },
            "candidate_allocation": {
                "allocation_contract_version": ALLOCATION_CONTRACT_VERSION,
            },
        },
    }


def test_current_compact_and_full_sidecars_are_reusable() -> None:
    assert compact_dynamic_is_current(_current_compact()) is True
    assert full_dynamic_is_current(_current_full()) is True


def test_contract_or_config_mismatch_is_not_reusable() -> None:
    stale_compact = _current_compact()
    stale_compact["dynamic_co_wave_transition_contract_version"] = "dynamic_co_wave_transition.v1"
    stale_full = _current_full()
    stale_full["dynamic_co_wave_transition"]["provenance"]["config_sha256"] = "stale"
    assert compact_dynamic_is_current(stale_compact) is False
    assert full_dynamic_is_current(stale_full) is False


def test_legacy_mapping_contract_is_not_reusable() -> None:
    stale_compact = _current_compact()
    stale_compact["kinase_feature_evidence_ledger_summary"]["mapping_readiness"]["mapping_importer_contract_version"] = "legacy"
    stale_full = _current_full()
    stale_full["kinase_feature_evidence_ledger"]["mapping_importer"]["mapping_importer_contract_version"] = "legacy"
    assert compact_dynamic_is_current(stale_compact) is False
    assert full_dynamic_is_current(stale_full) is False


def test_configured_mapping_bundle_hash_mismatch_is_not_reusable(monkeypatch) -> None:
    expected = "a" * 64
    monkeypatch.setenv("PTM_MAPPING_BUNDLE_SHA256", expected)
    compact = _current_compact()
    compact["kinase_feature_evidence_ledger_summary"]["mapping_readiness"]["mapping_bundle_sha256"] = "b" * 64
    full = _current_full()
    full["kinase_feature_evidence_ledger"]["mapping_importer"]["mapping_bundle_sha256"] = "b" * 64
    assert compact_dynamic_is_current(compact) is False
    assert full_dynamic_is_current(full) is False


def test_configured_relation_bundle_hash_mismatch_is_not_reusable(monkeypatch) -> None:
    expected = "c" * 64
    monkeypatch.setenv("PTM_RELATION_BUNDLE_SHA256", expected)
    compact = _current_compact()
    compact["kinase_feature_evidence_ledger_summary"]["relation_readiness"]["relation_bundle_sha256"] = "d" * 64
    full = _current_full()
    full["kinase_feature_evidence_ledger"]["relation_importer"]["relation_bundle_sha256"] = "d" * 64
    assert compact_dynamic_is_current(compact) is False
    assert full_dynamic_is_current(full) is False


def test_readiness_rejects_stale_compact_and_accepts_current_compact(tmp_path: Path) -> None:
    stale = _current_compact()
    stale["dynamic_co_wave_transition_contract_version"] = "dynamic_co_wave_transition.v1"
    stale_readiness = evaluate_temporal_evidence_readiness(
        compact_sources=(("db", {"temporal_ptm_protein_analysis": stale}),),
        artifact_path=tmp_path / "temporal_ptm_protein_analysis_v2.json",
    )
    ready_readiness = evaluate_temporal_evidence_readiness(
        compact_sources=(("db", {"temporal_ptm_protein_analysis": {**_current_compact(), "full_artifact_available": True}}),),
        artifact_path=tmp_path / "temporal_ptm_protein_analysis_v2.json",
    )
    assert stale_readiness["status"] == "missing"
    assert stale_readiness["stale_sources"] == ["db"]
    assert ready_readiness["status"] == "ready"


def test_readiness_rejects_stale_full_artifact_and_accepts_current_full(tmp_path: Path) -> None:
    artifact_path = tmp_path / "temporal_ptm_protein_analysis_v2.json"
    stale = _current_full()
    stale["dynamic_co_wave_transition"]["contract_version"] = "dynamic_co_wave_transition.v1"
    artifact_path.write_text(json.dumps(stale), encoding="utf-8")
    stale_readiness = evaluate_temporal_evidence_readiness(compact_sources=(), artifact_path=artifact_path)
    artifact_path.write_text(json.dumps(_current_full()), encoding="utf-8")
    ready_readiness = evaluate_temporal_evidence_readiness(compact_sources=(), artifact_path=artifact_path)
    assert stale_readiness["status"] == "missing"
    assert stale_readiness["stale_sources"] == ["production_artifact"]
    assert ready_readiness["status"] == "ready"


def test_api_reference_access_requires_all_local_roots_and_manifests(monkeypatch, tmp_path: Path) -> None:
    mapping_root = tmp_path / "mapping"
    relation_root = tmp_path / "relation"
    mapping_root.mkdir()
    relation_root.mkdir()
    mapping_manifest = mapping_root / "bundle.json"
    relation_manifest = relation_root / "bundle.json"
    mapping_manifest.write_text("{}", encoding="utf-8")
    relation_manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("PTM_MAPPING_SNAPSHOT_ROOT", str(mapping_root))
    monkeypatch.setenv("PTM_MAPPING_SOURCE_BUNDLE_PATH", str(mapping_manifest))
    monkeypatch.setenv("PTM_RELATION_SNAPSHOT_ROOT", str(relation_root))
    monkeypatch.setenv("PTM_RELATION_SOURCE_BUNDLE_PATH", str(relation_manifest))
    assert api_has_local_reference_bundle_access() is True
    monkeypatch.delenv("PTM_RELATION_SOURCE_BUNDLE_PATH")
    assert api_has_local_reference_bundle_access() is False


def test_api_can_preserve_validated_worker_sidecar_without_local_mount(tmp_path: Path) -> None:
    artifact = _current_full()
    artifact["kinase_feature_evidence_ledger"]["mapping_importer"].update({
        "mapping_bundle_status": "validated",
        "mapping_bundle_sha256": "a" * 64,
    })
    artifact["kinase_feature_evidence_ledger"]["relation_importer"].update({
        "relation_bundle_status": "validated",
        "relation_bundle_sha256": "b" * 64,
    })
    path = tmp_path / "temporal_ptm_protein_analysis_v2.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    assert full_sidecar_has_validated_local_reference_bundles(artifact) is True
    assert load_preservable_local_reference_sidecar(path) == artifact
    artifact["kinase_feature_evidence_ledger"]["relation_importer"]["relation_bundle_status"] = "not_evaluable"
    assert full_sidecar_has_validated_local_reference_bundles(artifact) is False
    artifact["kinase_feature_evidence_ledger"]["relation_importer"]["relation_bundle_status"] = "validated"
    artifact["dynamic_co_wave_transition"]["contract_version"] = "stale"
    assert full_sidecar_has_validated_local_reference_bundles(artifact) is False
