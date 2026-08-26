from benchmarking.locked_scorer import _score_secondary_reference


def test_secondary_kinase_and_temporal_metrics_are_explicit_and_separate():
    artifact = {
        "tmm_full_temporal": {
            "kinase_scores": [{
                "kinase": "PDK1",
                "direction": "activation",
                "peak_condition": "5min",
                "tmm_evidence": {"confidence_tier": "tmm_data_anchored"},
            }]
        },
        "temporal_wave_contract": {"waves": [{"peak_timepoint": "5min"}]},
    }
    truth = {
        "kinase_reference": [{
            "Kinase_ID": "KX",
            "Kinase_or_complex": "PDPK1/PDK1",
            "Expected_activity_direction": "Up",
            "Expected_time": "Early",
        }],
        "temporal_layers": [{
            "Window_ID": "TX",
            "Temporal_layer": "Early layer",
            "Biological_window": "1-15 min",
        }],
    }
    result = _score_secondary_reference(artifact, truth)
    assert result["metrics"]["kinase_reference_coverage"] == 1.0
    assert result["metrics"]["kinase_expected_direction_accuracy"] == 1.0
    assert result["metrics"]["kinase_expected_timing_accuracy"] == 1.0
    assert result["metrics"]["temporal_layer_coverage"] == 1.0
    assert "primary" in result["selection_boundary"]


def test_secondary_metrics_report_zero_coverage_without_prediction():
    result = _score_secondary_reference(
        {"tmm_full_temporal": {"kinase_scores": []}, "temporal_wave_contract": {"waves": []}},
        {"kinase_reference": [{"Kinase_ID": "KX", "Kinase_or_complex": "KX"}], "temporal_layers": []},
    )
    assert result["metrics"]["kinase_reference_coverage"] == 0.0
    assert result["metrics"]["kinase_expected_direction_accuracy"] is None
