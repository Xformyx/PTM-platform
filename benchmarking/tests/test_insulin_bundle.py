from __future__ import annotations

from pathlib import Path

from benchmarking.contracts import BenchmarkManifest, load_locked_truth_bundle


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "benchmarks" / "insulin_signaling_v1" / "insulin_signaling_v1.manifest.json"


def test_insulin_bundle_is_hash_locked_and_contains_scoreable_tier_1_2_anchors() -> None:
    manifest = BenchmarkManifest.load(MANIFEST_PATH)
    truth = load_locked_truth_bundle(manifest)
    scoreable = [
        row
        for row in truth["anchors"]
        if row.get("Evidence_tier") in {"Tier 1", "Tier 2"}
        and "truth" in str(row.get("Benchmark_truth_use") or "").lower()
    ]
    assert manifest.dataset_id == "insulin_signaling_v1"
    assert manifest.production_contract["id"] == "tmm_full_temporal.v1"
    assert manifest.blind_policy["truth_available_to_scorer_only"] is True
    assert manifest.production_contract["representation_learning_in_primary_score"] is False
    assert scoreable
    assert all(row.get("Anchor_ID") and row.get("Gene") for row in scoreable)
    directly_mapped = [row for row in scoreable if row.get("Rat_site")]
    unresolved_orthologs = [row for row in scoreable if not row.get("Rat_site")]
    assert directly_mapped
    # The workbook deliberately retains conditional human/ortholog rows. They
    # are not denominator-positive until a sequence+isoform+species mapping
    # produces a concrete observed site in the offline scorer.
    assert unresolved_orthologs
