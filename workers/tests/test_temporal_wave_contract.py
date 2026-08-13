"""Unit tests for P0 canonical Temporal Wave infrastructure.

The deterministic rows in this file are software fixtures only. They are not
benchmark data and are never used to make a scientific performance claim.
"""

import json

import numpy as np
import pytest

from ptm_shared.temporal_wave_benchmark import ManifestError, run_benchmark
from ptm_shared.temporal_wave_engine import (
    CONTRACT_VERSION,
    analyze_temporal_waves,
    build_input_from_vector_rows,
    validate_temporal_wave_contract,
)
from report_generation.core.nodes.temporal_comovement_node import _cluster_comoving_ptms


def test_contract_returns_reproducible_wave_membership_and_provenance():
    series = {
        "MAPK1 T185": {"0min": 0.0, "5min": 1.0, "10min": 2.0, "15min": 3.0},
        "MAPK3 T202": {"0min": 0.0, "5min": 1.1, "10min": 2.1, "15min": 3.2},
        "AKT1 S473": {"0min": 0.0, "5min": -1.0, "10min": -2.0, "15min": -3.0},
    }
    metadata = {
        "MAPK1 T185": {"gene": "MAPK1", "site": "T185", "activity_class": "regulated"},
        "MAPK3 T202": {"gene": "MAPK3", "site": "T202", "activity_class": "regulated"},
        "AKT1 S473": {"gene": "AKT1", "site": "S473", "activity_class": "regulated"},
    }
    result = analyze_temporal_waves(
        series,
        ["15min", "0min", "10min", "5min"],
        metadata=metadata,
        config={"correlation_threshold": 0.7, "threshold_source": "unit_test"},
    )

    assert result["contract_version"] == CONTRACT_VERSION
    assert validate_temporal_wave_contract(result) == []
    assert result["timepoints"] == ["0min", "5min", "10min", "15min"]
    assert len(result["waves"]) == 1
    wave = result["waves"][0]
    assert wave["wave_id"] == "TW-01"
    assert set(wave["members"]) == {"MAPK1 T185", "MAPK3 T202"}
    assert wave["evidence_profile"]["evidence_tier"] in {
        "moderate_structural_evidence",
        "high_structural_evidence",
    }
    assert result["threshold_provenance"]["threshold_source"] == "unit_test"
    assert result["threshold_provenance"]["config_sha256"]


def test_vector_rows_are_aggregated_by_site_condition_without_hardcoded_dataset_fields():
    rows = [
        {"gene": "MAPK1", "position": "T185", "condition": "5min", "ptm_relative_log2fc": 1.0, "candidate_kinases": ["MAP2K1"]},
        {"gene": "MAPK1", "position": "T185", "condition": "5min", "ptm_relative_log2fc": 1.2, "candidate_kinases": ["MAP2K1"]},
        {"gene": "MAPK1", "position": "T185", "condition": "10min", "ptm_relative_log2fc": 2.0, "candidate_kinases": ["MAP2K1"]},
    ]
    series, timepoints, metadata = build_input_from_vector_rows(rows)

    assert series["MAPK1 T185"]["5min"] == pytest.approx(1.1)
    assert timepoints == ["5min", "10min"]
    assert metadata["MAPK1 T185"]["candidate_kinases"] == ["MAP2K1"]


def test_report_temporal_node_delegates_to_the_canonical_contract():
    matrix = np.asarray(
        [
            [0.0, 1.0, 2.0, 3.0],
            [0.0, 1.1, 2.1, 3.2],
            [0.0, -1.0, -2.0, -3.0],
        ]
    )
    metadata = [
        {"key": "MAPK1(T185)", "gene": "MAPK1", "site": "T185", "activity_class": "regulated"},
        {"key": "MAPK3(T202)", "gene": "MAPK3", "site": "T202", "activity_class": "regulated"},
        {"key": "AKT1(S473)", "gene": "AKT1", "site": "S473", "activity_class": "regulated"},
    ]
    clusters, singletons, contract = _cluster_comoving_ptms(
        matrix,
        metadata,
        ["0min", "5min", "10min", "15min"],
        state={"temporal_wave_config": {"correlation_threshold": 0.7, "threshold_source": "unit_test"}},
    )

    assert contract["contract_version"] == CONTRACT_VERSION
    assert len(clusters) == 1
    assert set(clusters[0]["members"]) == {"MAPK1(T185)", "MAPK3(T202)"}
    assert len(singletons) == 1


def test_benchmark_refuses_to_claim_results_when_manifest_data_file_is_absent(tmp_path):
    manifest = {
        "schema_version": "temporal_wave_benchmark_manifest.v1",
        "dataset_id": "real_dataset_not_downloaded",
        "data_path": "missing_real_dataset.csv",
        "known_targets": ["MAP2K1"],
        "input_columns": {
            "gene": "gene",
            "site": "site",
            "timepoint": "timepoint",
            "log2fc": "ptm_relative_log2fc",
            "candidate_kinases": "candidate_kinases",
        },
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ManifestError, match="Real benchmark data is not available"):
        run_benchmark(manifest_path, tmp_path / "output")
