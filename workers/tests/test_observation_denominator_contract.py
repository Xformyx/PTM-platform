"""Synthetic PR/PG missingness regressions; no original experiment data."""

import numpy as np
import pandas as pd
import pytest

from workers.preprocessing.core.ptm_quantification import PTMQuantificationAnalyzer


def analyzer_for(pr_values, pg_values):
    analyzer = PTMQuantificationAnalyzer.__new__(PTMQuantificationAnalyzer)
    analyzer.target_ptms = {"21": "Phosphorylation"}
    analyzer.sample_columns = ["c1", "c2", "t1"]
    analyzer.condition_map = {"c1": "Control", "c2": "Control", "t1": "5min"}
    analyzer.treatment_conditions = ["5min"]
    analyzer.fasta_dict = {}
    analyzer.pr_matrix_normalized = pd.DataFrame([{
        "Protein.Group": "P1", "Precursor.Id": "form1",
        "Modified.Sequence": "AS(UniMod:21)K",
        **dict(zip(analyzer.sample_columns, pr_values)),
    }])
    analyzer.pg_matrix_normalized = pd.DataFrame([{
        "Protein.Group": "P1", **dict(zip(analyzer.sample_columns, pg_values)),
    }])
    analyzer._resolve_protein_name = lambda _: "protein"
    analyzer._resolve_gene_name = lambda _: "GENE"
    return analyzer


def quantify(analyzer):
    observations = analyzer.calculate_site_level_relative_quantification(analyzer.pr_matrix_normalized)
    adjusted = analyzer.calculate_condition_comparisons(observations)
    unadjusted = analyzer.calculate_unadjusted_condition_comparisons(analyzer.pr_matrix_normalized)
    _, proteins = analyzer.calculate_protein_level_changes()
    vector = analyzer.create_ptm_vector_data(adjusted, proteins, unadjusted_ptm_comparisons=unadjusted)
    return observations, adjusted, vector


@pytest.mark.parametrize("pg_values", [[np.nan, 1000, 1000], [np.nan, np.nan, np.nan]])
def test_pr_detection_survives_unavailable_protein_denominator(pg_values):
    observations, adjusted, vector = quantify(analyzer_for([100, np.nan, 200], pg_values))
    assert len(vector) == 1
    row = vector.iloc[0]
    assert row["Detection_Control"] == "1/2"
    assert row["PTM_Unadjusted_Log2FC"] == pytest.approx(1)
    assert row["PTM_Unadjusted_Control_N"] == 1
    assert pd.isna(row["PTM_ProteinAdjusted_Log2FC"])
    assert row["PTM_ProteinAdjusted_Missing_Reason"] == "protein_denominator_unavailable"
    assert not row["Control_Pseudocount_Used"]
    assert not row["Conventional_Log2FC_NA"]  # Legacy detection/de novo flag, not adjusted availability.
    assert not row["DeNovo_Confidence"]
    assert pd.isna(row["q_value"])
    assert row["PTM_ProteinAdjusted_Control_N"] == 0
    from workers.report_generation.core.vector_projection import project_report_vector_row
    projected = project_report_vector_row(row.to_dict())
    assert projected["ptm_unadjusted_log2fc"] == pytest.approx(1)
    assert projected["ptm_protein_adjusted_log2fc"] is None
    assert projected["ptm_protein_adjusted_control_n"] == 0
    assert projected["ptm_protein_adjusted_missing_reason"] == "protein_denominator_unavailable"
    masks = observations.set_index("Sample")
    assert bool(masks.loc["c1", "PR_Observed"])
    assert not bool(masks.loc["c1", "PG_Observed"])
    assert not bool(masks.loc["c1", "Paired_Ratio_Observed"])


def test_partial_denominators_use_only_observed_pairs_without_changing_pr_detection():
    observations, adjusted, vector = quantify(analyzer_for([100, 200, 400], [np.nan, 1000, 1000]))
    row = vector.iloc[0]
    assert row["Detection_Control"] == "2/2"
    assert row["PTM_ProteinAdjusted_Log2FC"] == pytest.approx(1)
    assert row["PTM_Unadjusted_Log2FC"] == pytest.approx(np.log2(400 / 150))
    assert row["PTM_ProteinAdjusted_Control_N"] == 1
    assert row["PTM_Unadjusted_Control_N"] == 2
    assert pd.isna(row["p_value"])
    assert row["PTM_ProteinAdjusted_Missing_Reason"] == ""


def test_true_pr_control_nondetection_remains_de_novo():
    _, _, vector = quantify(analyzer_for([np.nan, np.nan, 200], [1000, 1000, 1000]))
    row = vector.iloc[0]
    assert row["Detection_Control"] == "0/2"
    assert row["Conventional_Log2FC_NA"]
    assert row["Control_Pseudocount_Used"]
    assert pd.isna(row["PTM_Unadjusted_Log2FC"])


def test_nonfinite_intensities_are_not_observations():
    observations, _, vector = quantify(analyzer_for([100, np.inf, 200], [np.inf, 1000, 1000]))
    assert vector.iloc[0]["Detection_Control"] == "1/2"
    assert vector.iloc[0]["PTM_Unadjusted_Log2FC"] == pytest.approx(1)
    assert not observations.set_index("Sample").loc["c2", "PR_Observed"]


def test_treatment_denominator_missing_only_withholds_adjusted_axis():
    _, _, vector = quantify(analyzer_for([100, np.nan, 200], [1000, 1000, np.nan]))
    row = vector.iloc[0]
    assert row["Detection_Control"] == "1/2"
    assert row["Detection_Treatment"] == "1/1"
    assert row["PTM_Unadjusted_Log2FC"] == pytest.approx(1)
    assert row["PTM_ProteinAdjusted_Control_N"] == 1
    assert row["PTM_ProteinAdjusted_Treatment_N"] == 0
    assert row["PTM_ProteinAdjusted_Missing_Reason"] == "protein_denominator_unavailable"
    assert pd.isna(row["PTM_ProteinAdjusted_Log2FC"])
    assert not row["Conventional_Log2FC_NA"]


def test_absent_protein_group_does_not_drop_observed_precursor():
    analyzer = analyzer_for([100, np.nan, 200], [1000, 1000, 1000])
    analyzer.pg_matrix_normalized = analyzer.pg_matrix_normalized.iloc[:0]
    _, _, vector = quantify(analyzer)
    assert len(vector) == 1
    assert vector.iloc[0]["PTM_Unadjusted_Log2FC"] == pytest.approx(1)
