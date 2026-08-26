import csv
from pathlib import Path

import numpy as np

from app.services.benchmark_artifact import build_temporal_request
from app.services.temporal_kinase_scoring import _tmm_target_vector
from ptm_shared.temporal_optimization_config import (
    CONFIG_SHA256,
    SELECTION_RECORD_SHA256,
    SITE_AGGREGATION,
    TMM_CONFIG,
    WAVE_CONFIG,
    provenance,
)


def test_frozen_truth_free_temporal_config_has_expected_boundary() -> None:
    assert CONFIG_SHA256 == "7b9674a29bde3f094f40e0bb6323f1c3d1ba99b075a801f00e26de9d6825a28c"
    assert SELECTION_RECORD_SHA256 == "2c625933b8fdab6fe59f7bc48eee00ee1698b1f4f253df86e1099fb79f618c62"
    assert SITE_AGGREGATION == "median"
    assert WAVE_CONFIG["minimum_amplitude"] == 0.40
    assert WAVE_CONFIG["compute_directionality"] is True
    assert TMM_CONFIG == {
        "profile_min_exclusive": 5,
        "gaussian_sigma_log": 0.80,
        "target_transform": "magnitude",
    }
    assert provenance()["truth_used_for_selection"] is False


def test_magnitude_target_transform_preserves_shape_not_sign() -> None:
    transformed = _tmm_target_vector([-2.0, 0.5, 1.0], target_transform="magnitude")
    assert np.allclose(transformed, np.array([2.0, 0.5, 1.0]))


def test_temporal_request_median_aggregates_duplicate_precursor_rows(tmp_path: Path) -> None:
    path = tmp_path / "ptm_vector_data_normalized_phospho.tsv"
    fields = ["Gene.Name", "PTM_Position", "Condition", "PTM_Relative_Log2FC", "q_value"]
    rows = [
        ["GENE1", "S10", "1min", "-4.0", "0.01"],
        ["GENE1", "S10", "1min", "2.0", "0.02"],
        ["GENE1", "S10", "5min", "1.0", "0.01"],
        ["GENE1", "S10", "15min", "3.0", "0.01"],
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(fields)
        writer.writerows(rows)

    request = build_temporal_request(
        output_dir=tmp_path,
        ptm_type="phosphorylation",
        site_aggregation="median",
        wave_config={"compute_directionality": False},
    )
    assert request["site_aggregation"] == "median"
    assert request["site_rows"]["GENE1_S10"]["values"]["1min"] == -1.0
