from report_generation.core.vector_projection import project_report_vector_row
from report_generation.core.measured_feature_cards import (
    build_feature_observation_cards, build_quantitation_comparison_cards,
)


def raw_row(gene="AARSD1", condition="1min", precursor="charge2", **extra):
    return {
        "Gene.Name": gene, "PTM_Position": "S88", "Condition": condition,
        "Precursor.Id": precursor, "Modified.Sequence": "AS(UniMod:21)TK",
        "Protein.Group": "P12345", "PTM_Unadjusted_Log2FC": .141,
        "PTM_Relative_Log2FC": .295, "Protein_Log2FC": -.1,
        "PTM_Relative_P_Value": .0002, "PTM_Relative_Q_Value": .001,
        "PTM_Unadjusted_P_Value": None, "PTM_Unadjusted_Q_Value": None,
        "PTM_Unadjusted_Control_N": 3, "PTM_Unadjusted_Treatment_N": 3,
        "PTM_ProteinAdjusted_Control_N": 2, "PTM_ProteinAdjusted_Treatment_N": 3,
        **extra,
    }


def test_axis_statistics_survive_projection_observation_and_comparison():
    projected = [project_report_vector_row(raw_row(condition=c)) for c in ("1min", "5min")]
    assert project_report_vector_row(projected[0])["ptm_protein_adjusted_q_value"] == .001
    state = {"vector_plot_raw_data": projected}
    observation = build_feature_observation_cards(state)[0]
    comparison = build_quantitation_comparison_cards(state)[0]
    for support in (observation["trajectory"][0]["quality"], comparison["statistical_support"]):
        assert support["protein_adjusted_q_value"] == .001
        assert support["protein_adjusted_p_value"] == .0002
        assert support["unadjusted_q_value"] is None
        assert support["unadjusted_p_value"] is None
    assert observation["trajectory"][0]["quality"]["q_supported"] is True
    assert comparison["replicate_support"]["protein_adjusted_control_n"] == 2
    assert comparison["measurement_provenance"] == projected[0]["measurement_provenance"]


def test_single_condition_support_precedes_lexical_order_without_claim_promotion():
    supported = raw_row(gene="ZZZ_SUPPORTED", PTM_Unadjusted_Q_Value=.001)
    low = raw_row(gene="AAA_LOW_SUPPORT", precursor="low", PTM_Unadjusted_Control_N=1,
                  PTM_Unadjusted_Treatment_N=2, PTM_Relative_Q_Value=None,
                  PTM_ProteinAdjusted_Control_N=None, PTM_ProteinAdjusted_Treatment_N=None)
    cards = build_quantitation_comparison_cards({"vector_plot_raw_data": [low, supported]})
    assert cards[0]["feature_identity"]["gene"] == "ZZZ_SUPPORTED"
    assert cards[0]["narrative_quality_tier"] == "high"
    assert cards[1]["narrative_quality_tier"] == "exploratory"
    assert all(card["biological_direction_inference_allowed"] is False for card in cards)


def test_missing_axis_n_and_q_are_not_borrowed():
    card = build_quantitation_comparison_cards({"vector_plot_raw_data": [raw_row(
        PTM_ProteinAdjusted_Control_N=None, PTM_ProteinAdjusted_Treatment_N=None)]})[0]
    assert card["replicate_support"]["protein_adjusted_control_n"] is None
    assert card["statistical_support"]["unadjusted_q_value"] is None
