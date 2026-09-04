"""Fail-closed full-document behavior when bibliography identity is unavailable."""

from report_generation.core.graph import format_citations


def test_bibliography_blocked_report_is_data_only_and_has_no_external_figure_prose():
    result = format_citations({
        "sections": {
            "title": "No identity report",
            "abstract": "Known canonical biology activates a pathway.",
            "results": "MAPK activation and pathway function were observed.",
            "discussion": "Prior work supports causal propagation.",
        },
        "network_analysis": {},
        "signal_flow_figures": [],
        "collected_references": [],
        "temporal_report_evidence_packet": {},
        "biological_synthesis_packet": {},
        "kinase_activity_heatmap": {},
    })
    report = result["final_report"]
    assert result["citation_data"]["completion_status"] == "blocked_for_review_missing_traceable_references"
    assert result["citation_data"]["data_only_review_mode"] is True
    assert "## Citation Integrity Gate" in report
    assert "Known canonical biology" not in report
    assert "causal propagation" not in report
    assert "## Supplementary Figures" not in report
    assert "Citation completeness status: blocked for review" in report


def test_bibliography_blocked_report_retains_compact_order_evidence_without_llm_prose():
    result = format_citations({
        "sections": {"title": "Blocked with evidence", "results": "Known pathway function."},
        "network_analysis": {},
        "signal_flow_figures": [],
        "collected_references": [],
        "temporal_report_evidence_packet": {
            "attribution_readiness": {
                "p0": {"status": "ready", "feature_count": 3},
                "p1": {"status": "validated"},
                "p2": {"status": "validated"},
                "p3": {"status": "not_evaluable"},
                "direct_attribution": "no_call",
            }
        },
        "biological_synthesis_packet": {},
        "kinase_activity_heatmap": {},
    })
    report = result["final_report"]
    assert "Known pathway function" not in report
    assert "## Results" in report
    assert "## Methods" in report
