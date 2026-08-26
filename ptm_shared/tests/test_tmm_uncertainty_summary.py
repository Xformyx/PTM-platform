from ptm_shared.tmm_multikinase_integration import summarize_tmm_uncertainty


def test_uncertainty_summary_deduplicates_site_across_kinases():
    uncertainty = {
        "evaluated": True,
        "bootstrap_top1_stability": 0.9,
        "loto_top_group_stability": 0.8,
    }
    scores = {
        "K1": {"contribution_details": [{"ptm_key": "G_S1", "resolution": "resolved", "uncertainty": uncertainty}]},
        "K2": {"contribution_details": [{"ptm_key": "G S1", "resolution": "resolved", "uncertainty": uncertainty}]},
    }
    summary = summarize_tmm_uncertainty(scores)
    assert summary["unique_contribution_sites"] == 1
    assert summary["evaluated_unique_sites"] == 1
    assert summary["bootstrap_top1_stability"]["median"] == 0.9
    assert summary["loto_top_group_stability"]["fraction_ge_0_8"] == 1.0


def test_uncertainty_summary_ignores_unevaluated_and_unresolved_records():
    scores = {
        "K1": {"contribution_details": [
            {"ptm_key": "G_S1", "resolution": "unresolved_shared"},
            {"ptm_key": "H_T2", "resolution": "resolved", "uncertainty": {"evaluated": False}},
        ]}
    }
    summary = summarize_tmm_uncertainty(scores)
    assert summary["unique_contribution_sites"] == 2
    assert summary["evaluated_unique_sites"] == 0
    assert summary["bootstrap_top1_stability"]["count"] == 0
