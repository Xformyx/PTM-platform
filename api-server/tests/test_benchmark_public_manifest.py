from __future__ import annotations

from pathlib import Path

from app.services.benchmark_blind_context import load_public_manifest


PUBLIC_MANIFEST_ROOT = Path(__file__).resolve().parents[1] / "app" / "benchmark_manifests"


def test_api_public_manifest_exposes_only_preflight_contract() -> None:
    manifest = load_public_manifest("insulin_signaling_v1", PUBLIC_MANIFEST_ROOT)
    assert manifest["visibility"] == "api_preflight_contract_only"
    assert manifest["production_contract"]["id"] == "tmm_full_temporal.v1"
    assert manifest["blind_policy"]["truth_available_to_scorer_only"] is True
    assert not {"locked_truth_bundle", "locked_truth_sha256", "score_config", "source_reference"}.intersection(manifest)
