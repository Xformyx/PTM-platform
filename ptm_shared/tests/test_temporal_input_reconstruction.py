"""Regression tests for RAG-safe canonical temporal input reconstruction."""

from ptm_shared.temporal_input_reconstruction import (
    CONTRACT_VERSION,
    build_feature_provenance_rows,
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


def test_feature_provenance_rows_require_explicit_precursor_identity_and_exclude_rag_fields() -> None:
    rows, provenance = build_feature_provenance_rows(
        [
            {
                "gene": "insr",
                "position": "Y1150",
                "Protein.Group": "P06213",
                "Modified.Sequence": "MSTYAA",
                "Precursor.Id": "precursor-insr-y1150",
                "FASTA_Taxonomy_ID": "9606",
                "Localization.Probability": "0.98",
                "condition_data": [
                    {"condition": "1min", "ptm_relative_log2fc": 0.4},
                    {"condition": "5min", "ptm_relative_log2fc": 0.7},
                ],
                "benchmark_truth": "must not be used",
                "rag_enrichment": {"full_text": "must not be used"},
            },
            {
                "gene": "mapk1",
                "position": "T185",
                "condition_data": [{"condition": "1min", "ptm_relative_log2fc": 0.2}],
            },
        ],
        declared_conditions=["1min", "5min"],
    )
    assert len(rows) == 2
    assert {row["condition"] for row in rows} == {"1min", "5min"}
    assert all(row["fasta_taxonomy_id"] == "9606" for row in rows)
    assert "benchmark_truth" not in str(rows)
    assert "rag_enrichment" not in str(rows)
    assert provenance["explicit_feature_identity_row_count"] == 1
    assert provenance["excluded_missing_explicit_feature_identity_count"] == 1
    assert provenance["identity_fallback_policy"] == "no_gene_or_site_label_fallback"


def test_stage1_loader_prefers_vector_tsv_with_explicit_precursor(tmp_path) -> None:
    from ptm_shared.temporal_input_reconstruction import load_stage1_feature_provenance_rows

    (tmp_path / "ptm_vector_data_normalized_phospho.tsv").write_text(
        "Protein.Group\tGene.Name\tModified.Sequence\tPTM_Position\tCondition\tPTM_Relative_Log2FC\tPrecursor.Id\n"
        "P06213\tINSR\tMSTYAA\tY1150\t1min\t0.4\tprecursor-insr-y1150\n",
        encoding="utf-8",
    )
    (tmp_path / "ptm_condition_comparisons_normalized_phospho.tsv").write_text(
        "Protein.Group\tPrecursor.Id\tModified.Sequence\tPTM_Position\tCondition\tLog2FC\n"
        "P00000\tshould-not-be-used\tXXXX\tS1\t1min\t9.9\n",
        encoding="utf-8",
    )

    rows, provenance = load_stage1_feature_provenance_rows(
        tmp_path,
        file_suffix="_phospho",
        declared_conditions=["1min"],
    )
    assert len(rows) == 1
    assert rows[0]["precursor_id"] == "precursor-insr-y1150"
    assert provenance["stage1_source_strategy"] == "vector_tsv_explicit_precursor"
    assert provenance["explicit_feature_identity_row_count"] == 1
    assert "enriched_ptm_data_json" in provenance["excluded_inputs"]


def test_stage1_loader_restores_precursor_from_comparisons_and_protein_group_gene(tmp_path) -> None:
    from ptm_shared.temporal_input_reconstruction import load_stage1_feature_provenance_rows

    (tmp_path / "ptm_vector_data_normalized_phospho.tsv").write_text(
        "Protein.Group\tGene.Name\tModified.Sequence\tPTM_Position\tCondition\tPTM_Relative_Log2FC\n"
        "P06213\tINSR\tMSTYAA\tY1150\t1min\t0.4\n",
        encoding="utf-8",
    )
    (tmp_path / "ptm_condition_comparisons_normalized_phospho.tsv").write_text(
        "Protein.Group\tPrecursor.Id\tModified.Sequence\tPTM_Position\tCondition\tLog2FC\n"
        "P06213\tprecursor-insr-y1150\tMSTYAA\tY1150\t1min\t0.4\n"
        "P06213\tprecursor-insr-y1150-z3\tMSTYAA\tY1150\t1min\t0.5\n",
        encoding="utf-8",
    )
    (tmp_path / "ptm_protein_level_changes_normalized_phospho.tsv").write_text(
        "Protein.Group\tGene.Name\n"
        "P06213\tINSR\n",
        encoding="utf-8",
    )
    (tmp_path / "unified_protein_data_enriched_phospho.tsv").write_text(
        "Protein.Group\tFASTA_Taxonomy_ID\tFASTA_Organism\n"
        "P06213\t9606\tHomo sapiens\n",
        encoding="utf-8",
    )

    rows, provenance = load_stage1_feature_provenance_rows(
        tmp_path,
        file_suffix="_phospho",
        declared_conditions=["1min"],
    )
    assert len(rows) == 2
    assert {row["precursor_id"] for row in rows} == {
        "precursor-insr-y1150",
        "precursor-insr-y1150-z3",
    }
    assert all(row["gene"] == "INSR" for row in rows)
    assert all(row["fasta_taxonomy_id"] == "9606" for row in rows)
    assert provenance["stage1_source_strategy"] == "comparisons_tsv_plus_protein_group_gene"
    assert provenance["identity_fallback_policy"] == "no_gene_or_site_label_fallback"


def test_stage1_loader_does_not_invent_precursor_from_gene_site_only(tmp_path) -> None:
    from ptm_shared.temporal_input_reconstruction import load_stage1_feature_provenance_rows

    (tmp_path / "ptm_vector_data_normalized_phospho.tsv").write_text(
        "Protein.Group\tGene.Name\tModified.Sequence\tPTM_Position\tCondition\tPTM_Relative_Log2FC\n"
        "P06213\tINSR\tMSTYAA\tY1150\t1min\t0.4\n",
        encoding="utf-8",
    )

    rows, provenance = load_stage1_feature_provenance_rows(
        tmp_path,
        file_suffix="_phospho",
        declared_conditions=["1min"],
    )
    assert rows == []
    assert provenance["explicit_feature_identity_row_count"] == 0
    assert provenance["stage1_source_strategy"] == "unavailable"
    assert provenance["identity_fallback_policy"] == "no_gene_or_site_label_fallback"
