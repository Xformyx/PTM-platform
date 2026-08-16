import pandas as pd

from workers.preprocessing.core.ptm_quantification import PTMQuantificationAnalyzer


SAMPLES = [
    "control_r1", "control_r2", "5min_r1", "5min_r2", "15min_r1", "15min_r2",
    "30min_r1", "30min_r2", "60min_r1", "60min_r2",
]
CONDITIONS = {
    "control_r1": "Control", "control_r2": "Control",
    "5min_r1": "5min", "5min_r2": "5min",
    "15min_r1": "15min", "15min_r2": "15min",
    "30min_r1": "30min", "30min_r2": "30min",
    "60min_r1": "60min", "60min_r2": "60min",
}


def _analyzer(pr_matrix):
    analyzer = PTMQuantificationAnalyzer.__new__(PTMQuantificationAnalyzer)
    analyzer.ptm_mode_config = {"unimod_id": "21"}
    analyzer.pr_matrix_normalized = pr_matrix
    analyzer.sample_columns = SAMPLES
    analyzer.condition_map = CONDITIONS
    return analyzer


def _pair_matrix(missing_unmodified_15min=False):
    modified = {
        "Protein.Group": "P12345",
        "Precursor.Id": "mod_1",
        "Modified.Sequence": "AST(UniMod:21)YK",
        **{sample: 20.0 for sample in SAMPLES},
    }
    unmodified = {
        "Protein.Group": "P12345",
        "Precursor.Id": "unmod_1",
        "Modified.Sequence": "ASTYK",
        **{sample: 80.0 for sample in SAMPLES},
    }
    if missing_unmodified_15min:
        unmodified["15min_r1"] = 0.0
        unmodified["15min_r2"] = 0.0
    return pd.DataFrame([modified, unmodified])


def test_paired_occupancy_uses_counterpart_fraction_and_is_explicitly_uncalibrated():
    matrix = _pair_matrix()
    analyzer = _analyzer(matrix)
    occupancy, audit = analyzer.calculate_paired_occupancy(matrix.iloc[[0]])

    assert len(occupancy) == 4
    assert set(occupancy["Condition"]) == {"5min", "15min", "30min", "60min"}
    assert set(occupancy["Pair_Quality_Tier"]) == {"O2"}
    assert set(occupancy["Occupancy_Calibration_Type"]) == {"none"}
    assert all(abs(value - 0.2) < 1e-9 for value in occupancy["Occupancy_Fraction"])
    assert audit.iloc[0]["Pair_Status"] == "qualified_apparent_paired_occupancy"


def test_paired_occupancy_keeps_missing_counterpart_timepoint_out_of_track_one():
    matrix = _pair_matrix(missing_unmodified_15min=True)
    analyzer = _analyzer(matrix)
    occupancy, audit = analyzer.calculate_paired_occupancy(matrix.iloc[[0]])

    assert "15min" not in set(occupancy["Condition"])
    assert audit.iloc[0]["Pair_Quality_Tier"] == "O2"
    assert audit.iloc[0]["Pair_Missingness"] == 0.2
    assert "15min:missing_unmodified" in audit.iloc[0]["Missing_Reason_By_Condition"]


def test_paired_occupancy_aggregates_multiple_modified_precursors_by_peptide_form():
    matrix = _pair_matrix()
    second_charge = matrix.iloc[0].copy()
    second_charge["Precursor.Id"] = "mod_1_z3"
    for sample in SAMPLES:
        second_charge[sample] = 20.0
    matrix = pd.concat([matrix, pd.DataFrame([second_charge])], ignore_index=True)
    analyzer = _analyzer(matrix)

    occupancy, audit = analyzer.calculate_paired_occupancy(matrix.iloc[[0, 2]])

    # (20 + 20) / ((20 + 20) + 80) = 1/3; only one peptide-form result per condition.
    assert len(occupancy) == 4
    assert all(abs(value - (1 / 3)) < 1e-9 for value in occupancy["Occupancy_Fraction"])
    assert audit.iloc[0]["Modified_Precursor_Ids"] == "mod_1;mod_1_z3"


def test_track_two_vector_values_survive_when_no_counterpart_is_available():
    analyzer = _analyzer(pd.DataFrame())
    comparisons = pd.DataFrame([{
        "Protein.Group": "P12345", "Precursor.Id": "mod_1", "Modified.Sequence": "AST(UniMod:21)YK",
        "PTM_Type": "Phosphorylation", "PTM_Position": "T3", "Condition": "5min",
        "Comparison": "5min_vs_Control", "Log2FC": 1.2, "Control_Mean": 0.1,
        "Treatment_Mean": 0.23,
        "Control_Pseudocount_Used": False, "p_value": 0.01, "q_value": 0.02,
    }])
    protein_changes = pd.DataFrame([{
        "Protein.Group": "P12345", "Condition": "5min", "Protein.Name": "Example protein",
        "Gene.Name": "EXAMPLE", "Control_Mean": 10.0, "Treatment_Mean": 12.0,
        "Log2FC": 0.263, "Fold_Change": 1.2,
    }])
    analyzer.treatment_conditions = ["5min"]

    vector = analyzer.create_ptm_vector_data(comparisons, protein_changes, pd.DataFrame())

    assert vector.iloc[0]["PTM_Relative_Log2FC"] == 1.2
    assert vector.iloc[0]["Quantification_Track"] == "protein_normalized_relative_ptm"
    assert vector.iloc[0]["Pair_Quality_Tier"] == "O0"
    assert pd.isna(vector.iloc[0]["Occupancy_Fraction"])
