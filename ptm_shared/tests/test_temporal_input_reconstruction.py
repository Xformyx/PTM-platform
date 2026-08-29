"""Regression tests for RAG-safe canonical temporal input reconstruction."""

from ptm_shared.temporal_input_reconstruction import (
    CONTRACT_VERSION,
    build_temporal_input_bundle,
    reconstruct_ptm_timeseries,
)


def test_condition_data_restores_collapsed_multi_timepoint_trajectory() -> None:
    vectors, provenance = reconstruct_ptm_timeseries(
        [
            {
                "gene": "erbb2",
                "position": "Y1248",
                "Condition": "1min",
                "PTM_Relative_Log2FC": 9.9,
                "condition_data": [
                    {"Condition": "1min", "PTM_Relative_Log2FC": 0.2},
                    {"Condition": "5min", "PTM_Relative_Log2FC": 1.1},
                    {"Condition": "15min", "PTM_Relative_Log2FC": 0.5},
                ],
            }
        ]
    )

    assert vectors == {"ERBB2_Y1248": {"1min": 0.2, "5min": 1.1, "15min": 0.5}}
    assert provenance["contract_version"] == CONTRACT_VERSION
    assert provenance["site_timepoint_source_counts"] == {"condition_data": 3}
    assert provenance["missing_value_policy"] == "preserve_missing_no_zero_imputation"


def test_site_aggregation_is_used_only_when_condition_data_is_absent() -> None:
    vectors, provenance = reconstruct_ptm_timeseries(
        [
            {
                "gene": "akt1",
                "position": "S473",
                "site_aggregation": {
                    "timepoints": [
                        {"timeLabel": "1min", "ptmLog2FC": 0.4},
                        {"timeLabel": "5min", "ptmLog2FC": 1.3},
                    ]
                },
                "Condition": "1min",
                "PTM_Relative_Log2FC": 0.9,
            }
        ]
    )

    assert vectors == {"AKT1_S473": {"1min": 0.4, "5min": 1.3}}
    assert provenance["site_timepoint_source_counts"] == {"site_aggregation": 2}


def test_duplicate_forms_are_median_aggregated_without_row_order_dependence() -> None:
    rows = [
        {
            "gene": "mapk1",
            "position": "T185",
            "condition_data": [{"condition": "5min", "ptm_relative_log2fc": value}],
        }
        for value in (2.0, 0.0, 1.0)
    ]
    forward, forward_provenance = reconstruct_ptm_timeseries(rows)
    reverse, reverse_provenance = reconstruct_ptm_timeseries(list(reversed(rows)))

    assert forward == {"MAPK1_T185": {"5min": 1.0}}
    assert reverse == forward
    assert forward_provenance["input_sha256"] == reverse_provenance["input_sha256"]
    assert forward_provenance["duplicate_site_timepoint_aggregations"] == 1


def test_missing_values_are_not_zero_filled_and_bundle_excludes_non_numeric_fields() -> None:
    bundle = build_temporal_input_bundle(
        [
            {
                "gene": "foxo1",
                "position": "S256",
                "condition_data": [
                    {"condition": "1min", "ptm_relative_log2fc": 0.0},
                    {"condition": "5min", "ptm_relative_log2fc": None},
                ],
                "rag_summary": "must not be read",
                "benchmark_truth": "must not be read",
            }
        ],
        declared_conditions=["1min", "5min"],
    )

    assert bundle["ptm_timeseries"] == {"FOXO1_S256": {"1min": 0.0}}
    assert bundle["declared_conditions"] == ["1min", "5min"]
    assert bundle["provenance"]["excluded_inputs"] == [
        "benchmark_truth",
        "locked_score",
        "rag_prose",
        "llm_output",
    ]
