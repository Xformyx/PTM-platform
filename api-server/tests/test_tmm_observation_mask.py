import numpy as np
import pytest

from app.services.temporal_kinase_scoring import (
    attribute_shared_ptm, build_kinase_profiles_from_data,
    compute_weighted_kinase_scores, deconvolve_shared_ptm,
)


CONDITIONS = ["1min", "5min", "15min"]


def exclusive_inputs(include_zero=False):
    keys = ["G1_S1", "G2_S1", "G3_S1"]
    series = {key: {"1min": 1., "15min": 1.} for key in keys}
    if include_zero:
        for ts in series.values():
            ts["5min"] = 0.
    modules = [{"canonical": "K1", "members": [{"key": key} for key in keys]}]
    candidates = {key: ["K1"] for key in keys}
    return modules, series, candidates


def test_missing_profile_time_is_not_an_observed_trough():
    profile = build_kinase_profiles_from_data(*exclusive_inputs(), CONDITIONS)["K1"]
    assert profile["profile"][[0, 2]].tolist() == [1., 1.]
    assert np.isnan(profile["profile"][1])
    assert profile["profile_type"] == "partial_data_driven"
    assert profile["observed_mask"] == [True, False, True]
    assert profile["support_by_condition"] == {"1min": 3, "5min": 0, "15min": 3}
    assert profile["peak_condition"] is None


def test_measured_zero_remains_observed():
    profile = build_kinase_profiles_from_data(*exclusive_inputs(True), CONDITIONS)["K1"]
    assert profile["profile"].tolist() == [1., 0., 1.]
    assert profile["observed_mask"] == [True, True, True]
    assert profile["profile_type"] == "data_driven"


def test_missing_target_does_not_distinguish_kinases_on_unmeasured_time():
    profiles = {"K1": {"profile": np.array([1., 0., 1.])},
                "K2": {"profile": np.array([1., 1., 1.])}}
    sparse = {"G_S1": {"1min": 1., "15min": 1.}}
    result = attribute_shared_ptm("G_S1", list(profiles), profiles, sparse, CONDITIONS)
    assert result.per_kinase["K1"]["ambiguous"]
    assert result.per_kinase["K2"]["ambiguous"]
    assert result.uncertainty["observed_conditions"] == ["1min", "15min"]
    assert result.uncertainty["missing_conditions"] == ["5min"]
    full = {"G_S1": {**sparse["G_S1"], "5min": 0.}}
    observed = attribute_shared_ptm("G_S1", list(profiles), profiles, full, CONDITIONS)
    assert not observed.per_kinase["K1"]["ambiguous"]


def test_deconvolution_uses_same_observed_rows_as_attribution():
    profiles = {"K1": {"profile": np.array([1., 0., .2])},
                "K2": {"profile": np.array([.2, 1., 1.])}}
    series = {"G_S1": {"1min": .2, "15min": 1.}}
    ratios = deconvolve_shared_ptm("G_S1", list(profiles), profiles, series, CONDITIONS)
    assert ratios["K2"] == pytest.approx(1)
    assert ratios["K1"] == pytest.approx(0)


def test_weighted_result_serializes_missing_profile_as_null_and_keeps_support():
    result = compute_weighted_kinase_scores(*exclusive_inputs(), CONDITIONS)["K1"]
    assert result["profile_values"]["5min"] is None
    assert result["observation_counts"]["5min"] == 0
    assert result["observation_counts"]["1min"] == 3
    assert result["_weighted_site_profiles_for_diagnostics"]["G1_S1"].get("5min") is None


@pytest.mark.parametrize("series", [{}, {"1min": 1.}])
def test_fewer_than_two_observed_times_withholds_attribution(series):
    profiles = {"K1": {"profile": np.ones(3)}, "K2": {"profile": np.array([1., 0., .2])}}
    result = attribute_shared_ptm("G_S1", list(profiles), profiles, {"G_S1": series}, CONDITIONS,
                                  uncertainty_bootstrap_repeats=10, uncertainty_loto_enabled=True)
    assert not result.attribution_supported
    assert result.unsupported_reason == "insufficient_observed_timepoints"
    assert result.uncertainty["bootstrap_repeats"] == 0
    assert result.uncertainty["loto_records"] == []


def test_partial_candidate_profiles_use_common_finite_rows_without_failure_fallback():
    profiles = {"K1": {"profile": np.array([1., np.nan, .2])},
                "K2": {"profile": np.array([.2, np.nan, 1.])}}
    result = deconvolve_shared_ptm("G_S1", list(profiles), profiles,
                                   {"G_S1": {"1min": .2, "5min": 99., "15min": 1.}}, CONDITIONS)
    assert result["K2"] == pytest.approx(1)
