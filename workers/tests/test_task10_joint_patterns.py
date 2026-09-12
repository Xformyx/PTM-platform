import pytest
from report_generation.core.measured_feature_cards import build_feature_observation_cards
from report_generation.core.temporal_analysis import summarize_observed_pattern
from report_generation.core.vector_projection import project_report_vector_row
from test_observation_denominator_contract import analyzer_for, quantify


@pytest.mark.parametrize("pr,pg,label", [
    ([100, 100, 200], [1000, 1000, 2000], "ptm_protein_co_movement"),
    ([100, 100, 100], [1000, 1000, 500], "ptm_maintained_protein_decreased_adjusted_increased"),
    ([100, 100, 200], [1000, 1000, 1000], "ptm_increased_with_stable_protein"),
])
def test_t10_03_patterns_use_the_actual_sample_ratio_estimator(pr, pg, label):
    _, _, vector = quantify(analyzer_for(pr, pg))
    row = project_report_vector_row(vector.iloc[0].to_dict())
    card = build_feature_observation_cards({"vector_plot_raw_data": [row]}, minimum_points=1)[0]
    point = card["trajectory"][0]
    assert point["joint_pattern"] == label
    assert point["axes"]["adjusted"]["control_sample_ids"] == ["c1", "c2"]


def test_t10_04_support_sets_and_non_equivalent_estimators_survive_projection():
    _, _, vector = quantify(analyzer_for([100, 200, 400], [float("nan"), 1000, 1000]))
    card = build_feature_observation_cards({"vector_plot_raw_data": [project_report_vector_row(vector.iloc[0].to_dict())]}, minimum_points=1)[0]
    point = card["trajectory"][0]
    assert point["support_sets_differ"]
    u, p, a = [point["axes"][key] for key in ("unadjusted", "protein", "adjusted")]
    assert a["value"] != pytest.approx(u["value"] - p["value"])
    assert u["control_sample_ids"] == ["c1", "c2"]
    assert a["control_sample_ids"] == ["c2"]


def test_unavailable_protein_does_not_remove_independent_ptm_finding():
    _, _, vector = quantify(analyzer_for([100, float("nan"), 200], [float("nan")] * 3))
    card = build_feature_observation_cards({"vector_plot_raw_data": [project_report_vector_row(vector.iloc[0].to_dict())]}, minimum_points=1)[0]
    axes = card["trajectory"][0]["axes"]
    assert axes["unadjusted"]["value"] == 1
    assert axes["unadjusted"]["control_sample_ids"] == ["c1"]
    assert axes["adjusted"]["value"] is None
    assert axes["adjusted"]["missing_reason"] == "protein_denominator_unavailable"
    assert axes["protein"]["value"] is None
    assert card["trajectory"][0]["joint_pattern"] == "incomplete_axes_observation"


def supported_row(precursor="P1", gene="UNKNOWN_CANDIDATE", condition="5min", **kwargs):
    return {"gene": gene, "position": "S7", "precursor_id": precursor, "protein_group": "PG1",
            "condition": condition, "ptm_unadjusted_log2fc": 0., "protein_log2fc": -1.,
            "ptm_protein_adjusted_log2fc": 1., "ptm_unadjusted_control_n": 3,
            "ptm_unadjusted_treatment_n": 3, "ptm_unadjusted_q_value": .001, **kwargs}


def test_t10_05_06_shared_denominator_and_technical_repeats_are_not_biological_n():
    rows = [supported_row(precursor=f"P{i}", **{f"ptm_unadjusted_{g}_sample_ids": [f"{g}{n}" for n in range(3)] for g in ("control", "treatment")}) for i in range(3)]
    manifest = {"samples": [{"sample_id": f"{g}{n}", "biological_unit": "one-donor", "technical_injection": n, "condition": g} for g in ("control", "treatment") for n in range(3)]}
    cards = build_feature_observation_cards({"vector_plot_raw_data": rows, "sample_manifest": manifest}, maximum=3, minimum_points=1)
    assert len(cards) == 3
    for card in cards:
        point = card["trajectory"][0]
        assert point["axes"]["unadjusted"]["treatment_biological_n"] == 1
        assert point["joint_pattern"] == "ptm_maintained_protein_decreased_adjusted_increased"
        assert point["axes"]["unadjusted"]["ci"] is None
        assert card["parent_protein_ids"] == ["PG1"]


def test_t10_07_irregular_times_boundary_maximum_and_unknown_time():
    points = [{"condition": f"{t}min", "ptm_relative_log2fc": v} for t, v in zip([0, 5, 40, 180], [0, 1, .5, 2])]
    pattern = summarize_observed_pattern(points)
    assert pattern["observed_times_minutes"] == [0, 5, 40, 180]
    assert pattern["observed_extrema"][0]["time_minutes"] == 180
    assert pattern["pattern_q_value"] is None
    assert "no_biological_peak" in pattern["peak_status"]
    unknown = summarize_observed_pattern(points + [{"condition": "sample999", "ptm_relative_log2fc": 3}])
    assert unknown["label"] == "time-unavailable"
    assert unknown["unknown_time_conditions"] == ["sample999"]


def test_t10_08_equal_means_keep_different_support_without_inventing_ci():
    rows = [supported_row(precursor="supported"), supported_row(precursor="single", ptm_unadjusted_control_n=1, ptm_unadjusted_treatment_n=1, ptm_unadjusted_q_value=None)]
    cards = build_feature_observation_cards({"vector_plot_raw_data": rows}, maximum=2, minimum_points=1)
    assert cards[0]["feature_identity"]["source_feature_id"] == "supported"
    assert cards[0]["narrative_quality_tier"] == "exploratory"  # One timepoint is not a supported trajectory.
    assert all(c["trajectory"][0]["axes"]["adjusted"]["ci_status"] == "not_available" for c in cards)


def test_manifest_times_and_sample_rename_do_not_infer_pairing_or_replicates():
    row = supported_row(condition="early", ptm_unadjusted_control_sample_ids=["run-z", "run-a"])
    design = {"conditions": [{"condition": "early", "elapsed_time": 5, "time_unit": "minutes", "reference_id": "vehicle"}],
              "samples": [{"sample_id": sample, "biological_unit": "donor", "technical_injection": i}
                          for i, sample in enumerate(["run-z", "run-a"])]}
    card = build_feature_observation_cards({"vector_plot_raw_data": [row], "sample_manifest": design}, minimum_points=1)[0]
    point = card["trajectory"][0]
    assert point["time_minutes"] == 5
    assert point["reference_id"] == "vehicle"
    assert point["axes"]["unadjusted"]["control_biological_n"] == 1
    row["ptm_unadjusted_control_sample_ids"] = ["renamed-a", "renamed-z"]
    for sample, name in zip(design["samples"], row["ptm_unadjusted_control_sample_ids"]):
        sample["sample_id"] = name
    renamed = build_feature_observation_cards({"vector_plot_raw_data": [row], "sample_manifest": design}, minimum_points=1)[0]
    assert renamed["trajectory"][0]["axes"]["unadjusted"]["control_biological_n"] == 1
    assert renamed["feature_identity"] == card["feature_identity"]
    assert renamed["trajectory"][0]["joint_pattern"] == point["joint_pattern"]
