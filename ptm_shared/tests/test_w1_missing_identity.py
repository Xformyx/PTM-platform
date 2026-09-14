"""Missing values stay missing; they do not create a peak or precedence."""
from ptm_shared.multisite_divergence import compute_divergence_pairs


def test_missing_middle_does_not_create_divergence_precedence():
    pairs, _ = compute_divergence_pairs(
        {
            "AKT1 S473|A": {"1min": 1.0, "15min": 0.2},
            "AKT1 T308|B": {"1min": 1.0, "15min": -0.8},
        },
        ["1min", "5min", "15min"],
        {"AKT1 S473|A": "regulated", "AKT1 T308|B": "regulated"},
        set(),
    )
    assert pairs
    assert pairs[0].directionality_tier == "D0_unresolved"


def test_measured_zero_is_kept_as_zero():
    pairs, _ = compute_divergence_pairs(
        {
            "AKT1 S473|A": {"1min": 0.0, "5min": 1.0, "15min": 0.2},
            "AKT1 T308|B": {"1min": 0.0, "5min": -1.0, "15min": -0.8},
        },
        ["1min", "5min", "15min"],
        {"AKT1 S473|A": "regulated", "AKT1 T308|B": "regulated"},
        set(),
    )
    assert pairs
    assert pairs[0].peak_condA in {"5min", "15min"}
