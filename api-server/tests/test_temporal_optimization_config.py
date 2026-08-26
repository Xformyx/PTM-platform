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
    assert CONFIG_SHA256 == "ee1671c91e1b8913b35e7eb95c1d9ea3ed916b1f220c69d31a1bbeb96dfa9455"
    assert SELECTION_RECORD_SHA256 == "2a6c7c728b2b931cb00f275e39be721a4ed904f95c566077219c3f5c254201e1"
    assert SITE_AGGREGATION == "median"
    assert WAVE_CONFIG["minimum_amplitude"] == 0.40
    assert WAVE_CONFIG["compute_directionality"] is True
    assert WAVE_CONFIG["bootstrap_repeats"] == 25
    assert WAVE_CONFIG["soft_membership_threshold"] == 0.60
    assert TMM_CONFIG == {
        "profile_min_exclusive": 5,
        "gaussian_sigma_log": 0.80,
        "target_transform": "magnitude",
        "activity_metric": "shrunken_mean",
        "shrinkage_prior_support": 10.0,
        "candidate_prior_strength": 5.0,
        "candidate_hierarchy_mode": "family_guard",
        "iterative_profile_rounds": 0,
        "iterative_min_top1_probability": 0.80,
        "iterative_min_shared_support": 3,
        "iterative_profile_blend": 0.50,
        "dual_track_correlation_threshold": 0.50,
        "dual_track_peak_index_tolerance": 2,
        "dual_track_magnitude_log2_ratio_threshold": 1.0,
        "uncertainty_bootstrap_repeats": 50,
        "uncertainty_loto_enabled": True,
        "uncertainty_seed": 20260826,
    }
    assert provenance()["truth_used_for_selection"] is False
    assert provenance()["iterative_profile_decision"] == "rejected_rounds_zero_retained"


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
