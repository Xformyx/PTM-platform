from __future__ import annotations

from benchmarking.figure2_source import build_figure2_source, write_figure2_tsvs


def test_figure2_rearranges_existing_score_rows_without_new_metrics() -> None:
    result = {
        "metrics": {
            "detectable_anchor_recall": 1.0,
            "regulated_anchor_recall": 0.5,
            "direction_accuracy": 1.0,
            "peak_window_accuracy": 0.0,
            "chain_completeness": 1.0,
            "canonical_weighted_score": 0.7,
        },
        "metric_numerators": {"detectable_anchor_recall": 3, "regulated_anchor_recall": 1.5},
        "metric_denominators": {"detectable_anchor_recall": 3, "regulated_anchor_recall": 3},
        "anchor_results": [
            {
                "anchor_id": "A001",
                "tier": "Tier 1",
                "branch": "PI3K–AKT",
                "is_measurable": True,
                "detected": True,
                "regulated": True,
                "direction_correct": True,
                "peak_window_correct": False,
            },
            {
                "anchor_id": "A002",
                "tier": "Tier 2",
                "branch": "PI3K–AKT",
                "is_measurable": True,
                "detected": True,
                "regulated": False,
                "direction_correct": None,
                "peak_window_correct": None,
            },
            {
                "anchor_id": "A003",
                "tier": "Tier 2",
                "branch": "RAS–ERK",
                "is_measurable": False,
                "detected": False,
                "regulated": False,
                "direction_correct": None,
                "peak_window_correct": None,
            },
        ],
    }
    figure2 = build_figure2_source(result)
    assert figure2["primary_score_unchanged"] is True
    assert figure2["ci_available"] is False
    assert figure2["panel_2a_metrics"][0]["estimate"] == 1.0
    assert figure2["panel_2d_status"] == {
        "not_measurable": 1,
        "measurable_not_detected": 0,
        "detected_not_regulated": 1,
        "correct_regulation": 1,
    }
    akt = next(row for row in figure2["panel_2b_branches"] if row["branch"] == "PI3K–AKT")
    assert akt["n_evaluable"] == 2
    assert akt["detectable_anchor_recall"] == 1.0
    assert akt["regulated_anchor_recall"] == 0.5
    assert akt["peak_window_accuracy"] == 0.0
    windows = {row["anchor_id"]: row["window_status"] for row in figure2["panel_2c_anchors"]}
    assert windows == {"A001": "miss", "A002": "not_evaluable", "A003": "not_evaluable"}


def test_figure2_tsv_writer_emits_source_tables(tmp_path) -> None:
    figure2 = build_figure2_source(
        {
            "metrics": {"detectable_anchor_recall": 1.0},
            "metric_numerators": {"detectable_anchor_recall": 1},
            "metric_denominators": {"detectable_anchor_recall": 1},
            "anchor_results": [
                {
                    "anchor_id": "A001",
                    "tier": "Tier 1",
                    "branch": "PI3K–AKT",
                    "is_measurable": True,
                    "detected": True,
                    "regulated": True,
                    "direction_correct": True,
                    "peak_window_correct": True,
                }
            ],
        }
    )
    paths = write_figure2_tsvs(tmp_path, figure2)
    assert (tmp_path / "metrics_summary.tsv").read_text(encoding="utf-8").startswith("key\t")
    assert "A001" in (tmp_path / "anchor_scores.tsv").read_text(encoding="utf-8")
    assert paths["metrics_summary"].endswith("metrics_summary.tsv")
