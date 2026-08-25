from __future__ import annotations

import json
from pathlib import Path

from benchmarking.contracts import MANIFEST_SCHEMA_VERSION, TRUTH_SCHEMA_VERSION, BenchmarkManifest, sha256_file
from benchmarking.locked_scorer import LockedBenchmarkScorer
from benchmarking.result_bundle import write_score_bundle


def _mapping() -> dict[str, object]:
    return {
        "method": "sequence_isoform_species",
        "sequence_match": True,
        "isoform_match": True,
        "species_match": True,
    }


def _manifest(tmp_path: Path) -> BenchmarkManifest:
    truth = {
        "schema_version": TRUTH_SCHEMA_VERSION,
        "anchors": [
            {
                "Anchor_ID": "A001",
                "Evidence_tier": "Tier 1",
                "Branch": "PI3K–AKT",
                "Gene": "AKT1",
                "Rat_site": "T308",
                "Human_site": "T308",
                "Expected_p_direction": "Up",
                "Expected_peak_window": "5–15 min",
                "Benchmark_truth_use": "Positive truth",
            },
            {
                "Anchor_ID": "A002",
                "Evidence_tier": "Tier 2",
                "Branch": "PI3K–AKT",
                "Gene": "AKT1",
                "Rat_site": "S473",
                "Human_site": "S473",
                "Expected_p_direction": "Up",
                "Expected_peak_window": "15–30 min",
                "Benchmark_truth_use": "Conditional positive truth",
            },
            {
                "Anchor_ID": "A003",
                "Evidence_tier": "Tier 3",
                "Branch": "Feedback",
                "Gene": "RAF1",
                "Rat_site": "S259",
                "Human_site": "S259",
                "Expected_p_direction": "Up",
                "Expected_peak_window": "15–30 min",
                "Benchmark_truth_use": "Context-only",
            },
        ],
    }
    truth_path = tmp_path / "truth.json"
    truth_path.write_text(json.dumps(truth), encoding="utf-8")
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "dataset_id": "fixture_v1",
        "locked_truth_bundle": "truth.json",
        "locked_truth_sha256": sha256_file(truth_path),
        "production_contract": {
            "id": "tmm_full_temporal.v1",
            "representation_learning_in_primary_score": False,
        },
        "blind_policy": {
            "stimulus_hidden_from_analysis_runtime": True,
            "research_question_hidden_from_analysis_runtime": True,
            "truth_available_to_scorer_only": True,
        },
        "score_config": {
            "evidence_tier_weights": {"Tier 1": 2, "Tier 2": 1},
            "component_weights": {
                "detectable_anchor_recall": 0.25,
                "regulated_anchor_recall": 0.25,
                "direction_accuracy": 0.20,
                "peak_window_accuracy": 0.20,
                "chain_completeness": 0.10,
            },
        },
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return BenchmarkManifest.load(manifest_path)


def test_locked_scorer_uses_only_tier_1_2_and_weighted_denominators(tmp_path: Path) -> None:
    scorer = LockedBenchmarkScorer(_manifest(tmp_path))
    artifact = {
        "site_availability": [
            {"gene": "AKT1", "site": "T308", "is_measurable": True, "mapping_evidence": _mapping()},
            {"gene": "AKT1", "site": "S473", "is_measurable": True, "mapping_evidence": _mapping()},
        ],
        "site_observations": [
            {"gene": "AKT1", "site": "T308", "mapping_evidence": _mapping(), "detected": True, "regulated": True, "phosphorylation_direction": "up", "peak_minutes": 10},
            {"gene": "AKT1", "site": "S473", "mapping_evidence": _mapping(), "detected": True, "regulated": False, "phosphorylation_direction": "up", "peak_minutes": 20},
        ],
        "branch_evidence": [{"branch": "PI3K–AKT", "evaluable": True, "ordered_layers": 2}],
    }
    result = scorer.score(artifact)
    assert result["metrics"]["detectable_anchor_recall"] == 1.0
    assert result["metrics"]["regulated_anchor_recall"] == 2 / 3
    assert result["metrics"]["direction_accuracy"] == 1.0
    assert result["metrics"]["peak_window_accuracy"] == 1.0
    assert len(result["anchor_results"]) == 2


def test_gene_site_only_observation_is_rejected_from_scoring(tmp_path: Path) -> None:
    scorer = LockedBenchmarkScorer(_manifest(tmp_path))
    result = scorer.score(
        {
            "site_availability": [{"gene": "AKT1", "site": "T308", "is_measurable": True, "mapping_evidence": _mapping()}],
            "site_observations": [{"gene": "AKT1", "site": "T308", "detected": True, "regulated": True}],
        }
    )
    assert result["metrics"]["detectable_anchor_recall"] == 0.0
    assert result["provenance"]["mapping_rejections"] == ["A001"]


def test_score_bundle_writes_auditable_json_and_anchor_tsv(tmp_path: Path) -> None:
    scorer = LockedBenchmarkScorer(_manifest(tmp_path))
    artifact = tmp_path / "artifact.json"
    artifact.write_text(json.dumps({"site_availability": [], "site_observations": []}), encoding="utf-8")
    paths = write_score_bundle(tmp_path / "bundle", scorer.score(json.loads(artifact.read_text())), analysis_artifact_path=artifact)
    assert Path(paths["score_json"]).is_file()
    assert Path(paths["anchor_tsv"]).is_file()
