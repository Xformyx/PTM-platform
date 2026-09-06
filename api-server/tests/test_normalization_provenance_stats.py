"""Regression tests for the derived order-statistics provenance summary.

This test covers only metadata assembled from existing output files.  It does
not invoke preprocessing and must not mutate a vector, sidecar, or report.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from app.api.orders import (
    _generate_statistics_from_outputs,
    _with_truthful_normalization_provenance,
)


def _write_tsv(path: Path, rows: list[dict]) -> None:
    pd.DataFrame(rows).to_csv(path, sep="\t", index=False)


def test_generated_statistics_describe_scaling_without_false_batch_correction(tmp_path: Path):
    pr_path = tmp_path / "pr_matrix.tsv"
    pg_path = tmp_path / "pg_matrix.tsv"
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()

    _write_tsv(
        pr_path,
        [{
            "Protein.Group": "P001",
            "Precursor.Id": "precursor-1",
            "Modified.Sequence": "AA(UniMod:21)A",
            "sample_control": 100.0,
            "sample_treatment": 200.0,
        }],
    )
    _write_tsv(
        pg_path,
        [{
            "Protein.Group": "P001",
            "sample_control": 1000.0,
            "sample_treatment": 1200.0,
        }],
    )
    _write_tsv(
        output_dir / "ptm_vector_data_normalized_phospho.tsv",
        [{
            "Protein.Group": "P001",
            "PTM_Position": "S10",
            "Precursor.Id": "precursor-1",
        }],
    )
    _write_tsv(
        output_dir / "normalization_factors.tsv",
        [
            {"Sample": "sample_control", "Normalization_Factor": 1.0},
            {"Sample": "sample_treatment", "Normalization_Factor": 0.8},
        ],
    )
    order = SimpleNamespace(pr_matrix_path=str(pr_path), pg_matrix_path=str(pg_path))

    stats = _generate_statistics_from_outputs(order, output_dir, "_phospho")

    assert stats is not None
    normalization = stats["step2_quantification"]["normalization"]
    assert normalization["method"] == "separate_samplewise_median_scaling"
    assert normalization["normalization_method"] == "separate_samplewise_median_scaling"
    assert normalization["sample_scaling_status"] == "performed"
    assert normalization["batch_variation_corrected"] is False
    assert normalization["batch_correction_status"] == "not_performed"
    assert normalization["injection_order_drift_correction_status"] == "not_performed"
    assert normalization["upstream_quantity_scale_status"] == "unknown_not_recorded"
    assert normalization["ratio_track_interpretation"] == (
        "protein_abundance_adjusted_relative_ptm_ratio_contrast"
    )
    assert normalization["samples_corrected"] == 2
    assert normalization["factor_range"] == [0.8, 1.0]


def test_statistics_generation_does_not_mutate_existing_vector_file(tmp_path: Path):
    pr_path = tmp_path / "pr_matrix.tsv"
    pg_path = tmp_path / "pg_matrix.tsv"
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()

    _write_tsv(pr_path, [{"Protein.Group": "P001", "sample_a": 1.0}])
    _write_tsv(pg_path, [{"Protein.Group": "P001", "sample_a": 1.0}])
    vector_path = output_dir / "ptm_vector_data_normalized_phospho.tsv"
    _write_tsv(vector_path, [{"Protein.Group": "P001", "PTM_Position": "S10"}])
    before = vector_path.read_bytes()
    order = SimpleNamespace(pr_matrix_path=str(pr_path), pg_matrix_path=str(pg_path))

    _generate_statistics_from_outputs(order, output_dir, "_phospho")

    assert vector_path.read_bytes() == before


def test_legacy_statistics_are_sanitized_only_in_memory_without_file_mutation(tmp_path: Path):
    stats_file = tmp_path / "pipeline_statistics_phospho.json"
    legacy_stats = {
        "step2_quantification": {
            "normalization": {
                "method": "median",
                "batch_variation_corrected": True,
            },
            "relative_quant": {"total_entries": 42},
        }
    }
    stats_file.write_text(json.dumps(legacy_stats, sort_keys=True), encoding="utf-8")
    before = stats_file.read_bytes()

    sanitized = _with_truthful_normalization_provenance(legacy_stats)

    assert stats_file.read_bytes() == before
    assert legacy_stats["step2_quantification"]["normalization"] == {
        "method": "median",
        "batch_variation_corrected": True,
    }
    normalization = sanitized["step2_quantification"]["normalization"]
    assert normalization["method"] == "separate_samplewise_median_scaling"
    assert normalization["batch_variation_corrected"] is False
    assert normalization["batch_correction_status"] == "not_performed"
    assert normalization["injection_order_drift_correction_status"] == "not_performed"
    assert normalization["upstream_quantity_scale_status"] == "unknown_not_recorded"
    assert normalization["ratio_track_interpretation"] == (
        "protein_abundance_adjusted_relative_ptm_ratio_contrast"
    )


def test_explicit_future_batch_status_is_preserved():
    future_stats = {
        "step2_quantification": {
            "normalization": {
                "method": "pooled_qc_drift_correction",
                "batch_variation_corrected": True,
                "batch_correction_status": "performed",
                "injection_order_drift_correction_status": "performed",
            }
        }
    }

    sanitized = _with_truthful_normalization_provenance(future_stats)

    normalization = sanitized["step2_quantification"]["normalization"]
    assert normalization["method"] == "pooled_qc_drift_correction"
    assert normalization["batch_variation_corrected"] is True
    assert normalization["batch_correction_status"] == "performed"
    assert normalization["injection_order_drift_correction_status"] == "performed"
