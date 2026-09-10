"""Regression tests for selection-mode RAG input collapse."""

import importlib.util
from pathlib import Path


_MERGER_PATH = Path(__file__).resolve().parents[1] / "rag_enrichment" / "core" / "ptm_merger.py"
_SPEC = importlib.util.spec_from_file_location("rag_ptm_merger_for_test", _MERGER_PATH)
assert _SPEC and _SPEC.loader
_MERGER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MERGER)

collapse_ptm_rows_for_enrichment = _MERGER.collapse_ptm_rows_for_enrichment
merge_multi_condition_ptms = _MERGER.merge_multi_condition_ptms


def _row(condition: str, ptm_fc: float, protein_fc: float = 0.0) -> dict:
    return {
        "Gene.Name": "INSR",
        "PTM_Position": "Y1158",
        "Condition": condition,
        "PTM_Relative_Log2FC": ptm_fc,
        "Protein_Log2FC": protein_fc,
        "q_value": 0.01,
    }


def test_collapse_creates_one_rag_work_item_and_preserves_trajectory():
    collapsed = collapse_ptm_rows_for_enrichment([
        _row("0min", 0.0),
        _row("5min", 2.0),
        _row("30min", 0.5),
    ])

    assert len(collapsed) == 1
    item = collapsed[0]
    assert item["Condition"] == "5min"  # representative is max |relative FC|
    assert item["rag_source_row_count"] == 3
    assert len(item["condition_data"]) == 3
    assert [tp["timeLabel"] for tp in item["trajectory"]["timepoints"]] == [
        "0min", "5min", "30min",
    ]


def test_collapse_preserves_independent_and_reconstructed_quantitation_axes():
    row = _row("5min", 1.0, protein_fc=0.5)
    row.update({
        "PTM_ProteinAdjusted_Log2FC": 1.0,
        "PTM_Unadjusted_Log2FC": 1.4,
        "PTM_Unadjusted_Status": "computed_from_normalized_pr_replicates",
        "PTM_Unadjusted_Conventional_Log2FC_NA": False,
        "PTM_Unadjusted_Calculation_Mode": (
            "ratio_of_condition_arithmetic_means_from_normalized_pr_intensity"
        ),
        "PTM_Absolute_Log2FC": 1.5,
        "PTM_Reconstructed_Log2FC": 1.5,
        "Protein_Adjustment_Delta_Log2FC": -0.4,
    })

    collapsed = collapse_ptm_rows_for_enrichment([row])
    condition = collapsed[0]["condition_data"][0]

    assert condition["ptm_unadjusted_log2fc"] == 1.4
    assert condition["ptm_protein_adjusted_log2fc"] == 1.0
    assert condition["ptm_reconstructed_log2fc"] == 1.5
    assert condition["protein_adjustment_delta_log2fc"] == -0.4
    assert condition["ptm_unadjusted_status"] == "computed_from_normalized_pr_replicates"
    assert condition["ptm_unadjusted_conventional_log2fc_na"] is False


def test_post_enrichment_merge_preserves_precollapsed_condition_data():
    collapsed = collapse_ptm_rows_for_enrichment([
        _row("0min", 0.0),
        _row("5min", 2.0),
    ])
    collapsed[0]["rag_enrichment"] = {"articles": [], "pathways": []}

    merged = merge_multi_condition_ptms(collapsed)

    assert len(merged) == 1
    assert len(merged[0]["condition_data"]) == 2
    assert len(merged[0]["rag_enrichment"]["trajectory"]["timepoints"]) == 2
