import numpy as np

from app.services.temporal_kinase_scoring import refine_kinase_profiles_iteratively


def test_iterative_profiles_are_disabled_by_default():
    profiles = {"K1": {"profile": np.array([0.0, 1.0, 0.5]), "profile_type": "gaussian_fallback"}}
    refined, provenance = refine_kinase_profiles_iteratively(
        profiles, {}, {}, ["1min", "5min", "15min"], rounds=0
    )
    assert refined["K1"]["profile_type"] == "gaussian_fallback"
    assert provenance["stop_reason"] == "disabled"


def test_iterative_profiles_do_not_promote_collinear_ambiguous_sites():
    profiles = {
        "K1": {"profile": np.array([0.0, 1.0, 0.5]), "profile_type": "gaussian_fallback"},
        "K2": {"profile": np.array([0.0, 1.0, 0.5]), "profile_type": "gaussian_fallback"},
    }
    series = {
        f"G_S{i}": {"1min": 0.0, "5min": 1.0, "15min": 0.5}
        for i in range(4)
    }
    mapping = {key: ["K1", "K2"] for key in series}
    refined, provenance = refine_kinase_profiles_iteratively(
        profiles,
        series,
        mapping,
        ["1min", "5min", "15min"],
        rounds=3,
        minimum_top1_probability=0.7,
        minimum_shared_support=2,
    )
    assert all(info["profile_type"] == "gaussian_fallback" for info in refined.values())
    assert provenance["stop_reason"] == "no_kinase_met_support_gate"
