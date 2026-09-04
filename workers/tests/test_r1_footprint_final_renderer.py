"""R1.0 deterministic footprint/Methods/caption renderer contracts."""

from report_generation.core.citation_formatter import ReportPostProcessor
from report_generation.core.graph import format_citations
from report_generation.core.nodes.kinase_annotation_node import (
    format_kinase_footprint_diagnostics_for_report,
)


def _heatmap_with_p0_p1_diagnostics() -> dict:
    return {
        "conditions": ["0min", "15min"],
        "kinase_scores": [
            {
                "kinase": "KINA",
                "peak_score": 2.4,
                "direction": "positive_substrate_footprint",
                "footprint_equivalence": {
                    "equivalence_group_id": "exact-set-demo",
                    "members": ["KINA", "KINB"],
                    "site_count": 6,
                },
                "footprint_diagnostics": {
                    "status": "computed",
                    "effective_substrate_number": 2.0,
                    "n_exclusive": 2,
                    "n_shared": 4,
                    "shared_fraction": 2 / 3,
                    "dominant_substrate_fraction": 0.7,
                    "leave_one_substrate_out": [
                        {"peak_condition_preserved": False, "direction_preserved": True},
                        {"peak_condition_preserved": True, "direction_preserved": True},
                    ],
                    "unique_only_footprint": {
                        "status": "computed",
                        "direction": "negative_substrate_footprint",
                    },
                },
            },
            {
                "kinase": "KINB",
                "peak_score": 2.4,
                "direction": "positive_substrate_footprint",
                "footprint_equivalence": {
                    "equivalence_group_id": "exact-set-demo",
                    "members": ["KINA", "KINB"],
                    "site_count": 6,
                },
                "footprint_diagnostics": {"status": "not_evaluable_no_weighted_site_profiles"},
            },
        ],
    }


def test_final_renderer_includes_compact_p0_p1_footprint_diagnostics_without_scalar_confidence():
    final = format_citations({
        "sections": {"title": "Footprint test", "results": "Observed trajectories were summarized."},
        "network_analysis": {},
        "signal_flow_figures": [],
        "kinase_activity_heatmap": _heatmap_with_p0_p1_diagnostics(),
        "collected_references": [],
    })["final_report"]
    assert "Kinase Footprint Diagnostics (P0/P1)" in final
    assert "KINA / KINB: identical observed substrate set (n=6)" in final
    assert "n_eff=2.00" in final
    assert "unique/shared=2/4" in final
    assert "LOSO=1/2 top-site omissions preserved peak and direction" in final
    assert "scalar confidence is intentionally not reported" in final.lower()
    assert "conf=50%" not in final
    assert "direct kinase–site relation" in final


def test_footprint_diagnostics_are_aggregate_only_and_do_not_expose_loso_site_keys():
    payload = _heatmap_with_p0_p1_diagnostics()
    payload["kinase_scores"][0]["footprint_diagnostics"]["leave_one_substrate_out"][0]["site_key"] = "SECRET_S999"
    rendered = format_kinase_footprint_diagnostics_for_report(payload)
    assert "SECRET_S999" not in rendered
    assert "LOSO=1/2" in rendered


def test_methods_policy_is_created_when_llm_omits_methods_section():
    processed = ReportPostProcessor().process(
        "## Results\n\nObserved data.\n\n## Discussion\n\nInterpretation."
    )
    assert "## Methods" in processed
    assert "### Reporting Policy" in processed
    assert processed.index("## Methods") < processed.index("## Discussion")


def test_postprocessor_lowers_legacy_network_caption_activation_labels():
    text = (
        "## Supplementary Figures\n\n"
        "Panel A: 272 activated PTMs, 65 inhibited PTMs. Top activated: SITE1.\n\n"
        "**Top Activated PTMs**: SITE1\n\n"
        "**Top Inhibited PTMs**: SITE2\n"
    )
    processed = ReportPostProcessor().process(text)
    assert "272 PTMs with higher measured abundance" in processed
    assert "65 PTMs with lower measured abundance" in processed
    assert "Top activated" not in processed
    assert "Top Activated PTMs" not in processed
    assert "Top higher measured PTM-abundance contrasts" in processed


def test_final_renderer_processes_supplementary_before_appending_references():
    final = format_citations({
        "sections": {
            "title": "Supplement order test",
            "results": "Traceable context [REF:pmid:12345].",
        },
        "network_analysis": {},
        "signal_flow_figures": [{
            "type": "signal_flow",
            "path": "/tmp/supplementary.png",
            "caption": "Supplementary context map",
        }],
        "collected_references": [{
            "pmid": "12345", "title": "Traceable paper", "authors": "Author A",
            "journal": "Journal", "pub_date": "2025",
        }],
    })["final_report"]
    assert "## Supplementary Figures" in final
    assert "## References" in final
    assert final.rfind("## References") > final.rfind("## Supplementary Figures")
    assert final.rstrip().endswith("https://pubmed.ncbi.nlm.nih.gov/12345/)")
