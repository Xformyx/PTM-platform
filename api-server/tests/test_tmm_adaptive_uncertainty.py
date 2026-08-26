import numpy as np

from app.services.temporal_kinase_scoring import attribute_shared_ptm


def test_adaptive_uncertainty_is_default_off_and_additive():
    conditions = ["1min", "5min", "15min", "30min"]
    profiles = {
        "K1": {"profile": np.asarray([0.0, 1.0, 0.3, 0.0])},
        "K2": {"profile": np.asarray([0.0, 0.1, 0.5, 1.0])},
    }
    series = {"G_S1": dict(zip(conditions, [0.0, 1.0, 0.3, 0.0]))}
    result = attribute_shared_ptm("G_S1", ["K1", "K2"], profiles, series, conditions)
    assert result.uncertainty["evaluated"] is False
    assert result.uncertainty["bootstrap_repeats"] == 0


def test_adaptive_uncertainty_bootstrap_and_loto_preserve_resolved_top_group():
    conditions = ["1min", "5min", "15min", "30min"]
    profiles = {
        "K1": {"profile": np.asarray([0.0, 1.0, 0.3, 0.0])},
        "K2": {"profile": np.asarray([0.0, 0.1, 0.5, 1.0])},
    }
    series = {"G_S1": dict(zip(conditions, [0.0, 1.0, 0.3, 0.0]))}
    result = attribute_shared_ptm(
        "G_S1", ["K1", "K2"], profiles, series, conditions,
        uncertainty_bootstrap_repeats=50,
        uncertainty_loto_enabled=True,
        uncertainty_seed=7,
    )
    assert result.uncertainty["evaluated"] is True
    assert result.uncertainty["bootstrap_repeats"] == 50
    assert result.uncertainty["bootstrap_top1_stability"] is not None
    assert result.uncertainty["loto_top_group_stability"] is not None
    assert len(result.uncertainty["loto_records"]) == len(conditions)
