import numpy as np

from app.services.temporal_kinase_scoring import deconvolve_shared_ptm


def test_candidate_prior_strength_zero_preserves_legacy_identical_profile_solution():
    profiles = {
        "K1": {"profile": np.array([0.0, 1.0, 0.5])},
        "K2": {"profile": np.array([0.0, 1.0, 0.5])},
    }
    ratios = deconvolve_shared_ptm(
        "G_S1", ["K1", "K2"], profiles,
        {"G_S1": {"1min": 0.0, "5min": 1.0, "15min": 0.5}},
        ["1min", "5min", "15min"],
        target_transform="magnitude",
        candidate_prior_weights={"K1": 0.8, "K2": 0.2},
        candidate_prior_strength=0.0,
    )
    assert ratios == {"K1": 1.0, "K2": 0.0}


def test_candidate_prior_calibrates_only_the_unidentified_identical_profile_tie():
    profiles = {
        "K1": {"profile": np.array([0.0, 1.0, 0.5])},
        "K2": {"profile": np.array([0.0, 1.0, 0.5])},
    }
    ratios = deconvolve_shared_ptm(
        "G_S1", ["K1", "K2"], profiles,
        {"G_S1": {"1min": 0.0, "5min": 1.0, "15min": 0.5}},
        ["1min", "5min", "15min"],
        target_transform="magnitude",
        candidate_prior_weights={"K1": 0.1, "K2": 0.9},
        candidate_prior_strength=10.0,
    )
    assert ratios["K2"] > ratios["K1"]
    assert abs(sum(ratios.values()) - 1.0) < 1e-3
