from __future__ import annotations

import math

from ptm_shared.temporal_wave_input_projection import (
    CONTRACT_VERSION,
    MISSING_VALUE_POLICY,
    project_temporal_wave_input,
)


def test_projection_never_converts_missing_measurements_to_zero() -> None:
    projected, provenance = project_temporal_wave_input(
        {
            "gene1_s1": {"1min": 0.0, "5min": 1.0, "15min": -0.5},
            "gene2_s2": {"1min": 0.2, "15min": 0.9},
            "gene3_s3": {"1min": math.nan, "5min": 0.4, "15min": 0.8},
        },
        ["1min", "5min", "15min"],
    )

    assert projected == {
        "GENE1_S1": {"1min": 0.0, "5min": 1.0, "15min": -0.5},
    }
    assert provenance["contract_version"] == CONTRACT_VERSION
    assert provenance["missing_value_policy"] == MISSING_VALUE_POLICY
    assert provenance["imputation_applied"] is False
    assert provenance["eligible_site_count"] == 1
    assert provenance["excluded_reason_counts"]["incomplete_time_grid"] == 2


def test_projection_is_deterministic_and_key_normalized() -> None:
    left, left_provenance = project_temporal_wave_input(
        {"b_s2": {"1min": 2, "5min": 3}, "a_s1": {"1min": 0, "5min": 1}},
        ["1min", "5min"],
    )
    right, right_provenance = project_temporal_wave_input(
        {"a_s1": {"5min": 1, "1min": 0}, "b_s2": {"5min": 3, "1min": 2}},
        ["1min", "5min"],
    )

    assert left == right
    assert left_provenance["eligible_site_keys_sha256"] == right_provenance["eligible_site_keys_sha256"]
