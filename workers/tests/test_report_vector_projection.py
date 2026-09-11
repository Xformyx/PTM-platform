from report_generation.core.vector_projection import project_report_vector_row


def test_report_projection_preserves_identity_and_independent_quantitation_axes():
    projected = project_report_vector_row({
        "Gene.Name": "GENE1", "PTM_Position": "S10", "Condition": "5min",
        "Precursor.Id": "precursor-1", "Modified.Sequence": "AA(UniMod:21)BB",
        "Protein.Group": "P11111", "Localization.Probability": "0.92",
        "PTM_Unadjusted_Log2FC": "0.72", "PTM_ProteinAdjusted_Log2FC": "0.31",
        "Protein_Log2FC": "0.41", "PTM_Reconstructed_Log2FC": "0.72",
        "PTM_Unadjusted_Conventional_Log2FC_NA": "false",
        "PTM_Unadjusted_P_Value": "0.02", "PTM_Unadjusted_Q_Value": "0.04",
        "PTM_Unadjusted_Control_N": "3", "PTM_Unadjusted_Treatment_N": "4",
        "PTM_Unadjusted_Calculation_Mode": "ratio_of_condition_arithmetic_means_from_normalized_pr_intensity",
        "PTM_Unadjusted_Input_Scale": "sample_wise_median_scaled_pr_intensity",
        "PTM_Unadjusted_Pseudocount_Used": "false",
    })

    assert projected["precursor_id"] == "precursor-1"
    assert projected["modified_sequence"] == "AA(UniMod:21)BB"
    assert projected["ptm_unadjusted_log2fc"] == 0.72
    assert projected["ptm_protein_adjusted_log2fc"] == 0.31
    assert projected["protein_log2fc"] == 0.41
    assert projected["ptm_unadjusted_p_value"] == 0.02
    assert projected["ptm_unadjusted_q_value"] == 0.04
    assert projected["ptm_unadjusted_control_n"] == 3.0
    assert projected["ptm_unadjusted_treatment_n"] == 4.0
    assert projected["ptm_unadjusted_pseudocount_used"] is False
    assert projected["identity_complete_for_reader_cards"] is True


def test_report_projection_keeps_missing_numeric_values_null_not_zero():
    projected = project_report_vector_row({
        "Gene.Name": "GENE1", "PTM_Position": "S10", "Condition": "5min",
        "Precursor.Id": "precursor-1", "PTM_Unadjusted_Log2FC": "NA",
        "PTM_Relative_Log2FC": "", "Protein_Log2FC": "nan",
    })

    assert projected["ptm_unadjusted_log2fc"] is None
    assert projected["ptm_relative_log2fc"] is None
    assert projected["protein_log2fc"] is None
