from __future__ import annotations

from benchmarking.golden_baseline import (
    _cascade_timepoint_count,
    compare_v1_semantic_baseline,
)


def test_cascade_timepoint_count_supports_production_object_schema() -> None:
    assert _cascade_timepoint_count({"timepoints": ["1", "5", "15"]}) == 3
    assert _cascade_timepoint_count({"cascade_flow": [{}, {}]}) == 2
    assert _cascade_timepoint_count([{}, {}]) == 2


def test_semantic_comparison_ignores_additive_file_hashes() -> None:
    expected = {
        "semantic": {"site_observation_count": 10},
        "primary_v1": {"metrics": {"canonical_weighted_score": 0.7}},
        "publication_sha256": {"figures/Fig1.svg": "old"},
    }
    observed = {
        "semantic": {"site_observation_count": 10, "protein_count": 20},
        "primary_v1": {"metrics": {"canonical_weighted_score": 0.7}},
        "publication_sha256": {"figures/Fig1.svg": "new"},
    }
    assert compare_v1_semantic_baseline(expected, observed)["passed"] is True


def test_semantic_comparison_rejects_primary_regression() -> None:
    expected = {
        "semantic": {"site_observation_count": 10},
        "primary_v1": {"metrics": {"canonical_weighted_score": 0.7}},
    }
    observed = {
        "semantic": {"site_observation_count": 9},
        "primary_v1": {"metrics": {"canonical_weighted_score": 0.6}},
    }
    report = compare_v1_semantic_baseline(expected, observed)
    assert report["passed"] is False
    assert report["failure_count"] == 2
