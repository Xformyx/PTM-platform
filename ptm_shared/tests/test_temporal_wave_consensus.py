from ptm_shared.temporal_wave_engine import analyze_temporal_waves


def test_consensus_wave_is_default_off_and_hard_membership_unchanged():
    series = {
        "A_S1": {"1min": 0.0, "5min": 2.0, "15min": 0.5},
        "B_S1": {"1min": 0.0, "5min": 1.8, "15min": 0.4},
        "C_S1": {"1min": 0.0, "5min": -2.0, "15min": -0.5},
        "D_S1": {"1min": 0.0, "5min": -1.8, "15min": -0.4},
    }
    result = analyze_temporal_waves(series, ["1min", "5min", "15min"], config={"minimum_variance": 0.0, "minimum_amplitude": 0.0})
    assert result["consensus_membership"]["status"] == "disabled"
    assert sum(wave["member_count"] for wave in result["waves"]) == 4


def test_consensus_wave_records_replicate_stability_without_replacing_hard_members():
    series = {
        "A_S1": {"1min": 0.0, "5min": 2.0, "15min": 0.5},
        "B_S1": {"1min": 0.0, "5min": 1.8, "15min": 0.4},
        "C_S1": {"1min": 0.0, "5min": -2.0, "15min": -0.5},
        "D_S1": {"1min": 0.0, "5min": -1.8, "15min": -0.4},
    }
    replicates = {
        key: {timepoint: [value * 0.95, value, value * 1.05] for timepoint, value in values.items()}
        for key, values in series.items()
    }
    baseline = analyze_temporal_waves(series, ["1min", "5min", "15min"], config={"minimum_variance": 0.0, "minimum_amplitude": 0.0})
    consensus = analyze_temporal_waves(
        series,
        ["1min", "5min", "15min"],
        config={
            "minimum_variance": 0.0,
            "minimum_amplitude": 0.0,
            "bootstrap_repeats": 25,
            "soft_membership_threshold": 0.7,
            "compute_directionality": False,
        },
        replicate_time_series=replicates,
    )
    assert [wave["members"] for wave in consensus["waves"]] == [wave["members"] for wave in baseline["waves"]]
    assert consensus["consensus_membership"]["status"] == "computed"
    assert consensus["consensus_membership"]["usable_replicate_site_count"] == 4
    assert all(wave["evidence_profile"]["replicate_stability"] > 0.9 for wave in consensus["waves"])
