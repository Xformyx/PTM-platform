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
