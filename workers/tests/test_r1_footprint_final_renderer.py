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


def test_all_non_evaluable_footprints_are_summarized_without_candidate_names():
    payload = {
        "kinase_scores": [
            {"kinase": "KINA", "peak_score": 2.0, "footprint_diagnostics": {"status": "not_evaluable_no_profiles"}},
            {"kinase": "KINB", "peak_score": 1.0, "footprint_diagnostics": {"status": "not_evaluable_no_profiles"}},
        ]
    }
    rendered = format_kinase_footprint_diagnostics_for_report(payload)
    assert "No candidate-specific kinase footprint diagnostic was evaluable" in rendered
    assert "KINA" not in rendered
    assert "KINB" not in rendered


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
    assert "Top higher measured PTM-abundance contrasts" not in processed
    assert "SITE1" not in processed
    assert "SITE2" not in processed


def test_final_gate_bounds_residual_1207_style_claims_in_narrative_and_tables():
    text = """## Results

### Temporal Results Subsection

Ppp4r1 showed PTM Log2FC=12.08, a strong and persistent signaling input and key regulatory event [7].
The co-wave membership establishes a signaling cascade and functional module that is assembled over time.
The temporal synchronization may reflect a coordinated cellular feedback mechanism.
The observed profile suggests a direct signaling input into the chaperone machinery.

| Kinase Family | Example Putative Substrates |
|---|---|
| KINA | SITE1 |

| Time Point | Key Observation | Classification |
|---|---|---|
| 15 min | Transition to later signaling phase | PTM-driven ↑↑ |

## Introduction

A cited canonical signaling cascade may be described as external background [1].
"""
    processed = ReportPostProcessor().process(text)
    assert "strong and persistent signaling input" not in processed.lower()
    assert "key regulatory event" not in processed.lower()
    assert "establishes a signaling cascade" not in processed.lower()
    assert "functional module" not in processed.lower()
    assert "Example Putative Substrates" not in processed
    assert "PTM-driven" not in processed
    assert "feedback mechanism" not in processed.lower()
    assert "direct signaling input" not in processed.lower()
    assert "measured PTM/protein contrasts" in processed
    assert "[7]" in processed
    # Cited canonical background in the Introduction remains outside the
    # Order-derived Results/Q&A/Discussion/Conclusion claim ceiling.
    assert "canonical signaling cascade may be described" in processed


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


def test_final_renderer_preserves_traceable_chromadb_pmid_and_doi():
    final = format_citations({
        "sections": {
            "title": "Collection metadata",
            "results": "Selected collection comparison [REF:pmid:34567890].",
        },
        "network_analysis": {},
        "signal_flow_figures": [],
        "collected_references": [{
            "chromadb_ref": True,
            "title": "Traceable collection article",
            "authors": "Evidence Author",
            "journal": "Evidence Journal",
            "year": "2023",
            "pmid": "34567890",
            "doi": "10.1000/example.1",
        }],
    })
    assert final["citation_data"]["completion_status"] == "complete"
    assert "Traceable collection article" in final["final_report"]
    assert "https://pubmed.ncbi.nlm.nih.gov/34567890/" in final["final_report"]
    assert "https://doi.org/10.1000/example.1" in final["final_report"]


def test_data_only_report_uses_neutral_title_and_nonempty_scientific_sections():
    result = format_citations({
        "sections": {"title": "Delineates a signaling network response", "results": "Unsafe free prose."},
        "network_analysis": {},
        "signal_flow_figures": [],
        "collected_references": [],
        "ptm_type": "phosphorylation",
        "experimental_context": {
            "cell_type": "primary microglia",
            "treatment": "amyloid fibril",
            "timepoints": ["0 min", "15 min"],
        },
        "biological_synthesis_packet": {
            "study_frame": {"cell_model": "primary microglia", "treatment": "amyloid fibril", "timepoints": ["0 min", "15 min"]},
            "quantitative_landscape": {"vector_row_count": 12, "unique_site_count": 8, "unique_gene_count": 7, "parsed_ptm_count": 8, "de_novo_vector_row_count": 1},
        },
        "temporal_report_evidence_packet": {"status": "unavailable", "records": []},
    })["final_report"]
    assert "Delineates a signaling network response" not in result
    assert "# Data-only evidence and readiness summary" in result
    for section in ("## Abstract", "## Introduction", "## Results", "## Discussion", "## Conclusion"):
        assert section in result


def test_observation_only_composer_uses_landscape_temporal_and_traceable_context():
    result = format_citations({
        "sections": {"title": "Observation-only test", "results": "Unsafe LLM prose."},
        "network_analysis": {},
        "signal_flow_figures": [],
        "ptm_type": "phosphorylation",
        "experimental_context": {"cell_type": "cells", "treatment": "treatment", "timepoints": ["0 min", "15 min"]},
        "biological_synthesis_packet": {
            "study_frame": {"cell_model": "cells", "treatment": "treatment", "timepoints": ["0 min", "15 min"]},
            "quantitative_landscape": {"vector_row_count": 40, "unique_site_count": 20, "unique_gene_count": 15, "parsed_ptm_count": 20, "de_novo_vector_row_count": 3},
            "candidate_discovery_packet": {"selection_summary": {"candidate_capacity": 5, "selected_by_quota": {"discovery": 2}}},
        },
        "temporal_report_evidence_packet": {
            "status": "available",
            "section_plan": {"observation_only_claim_ceiling": True},
            "records": [
                {"evidence_id": "DATA-TEMPORAL-SUMMARY", "text": "Measured scope: protein trajectories=10."},
                {"evidence_id": "DATA-WAVE-INPUT-QUALITY", "text": "Eligible complete feature profiles=8."},
                {"evidence_id": "DATA-DYNAMIC-SUMMARY", "text": "Interval-wise concordance status=computed."},
            ],
        },
        "collected_references": [{"pmid": "12345", "title": "Traceable context", "authors": "Author A", "journal": "Journal", "pub_date": "2025"}],
    })["final_report"]
    assert "vector rows=40" in result
    assert "Measured scope: protein trajectories=10." in result
    assert "Traceable context" in result
    assert "Unsafe LLM prose" not in result


def test_observation_only_composer_retains_only_safe_stable_cited_context():
    result = format_citations({
        "sections": {
            "title": "Cited context test",
            "introduction": (
                "Prior work reported a phosphorylation profile under comparable experimental exposure "
                "[REF:pmid:12345]. This study proves direct kinase regulation [REF:pmid:12345]."
            ),
            "discussion": (
                "The cited study described a time-resolved proteomic measurement framework [REF:pmid:12345]. "
                "Our data directly establishes a causal pathway [REF:pmid:12345]."
            ),
        },
        "network_analysis": {},
        "signal_flow_figures": [],
        "ptm_type": "phosphorylation",
        "experimental_context": {"cell_type": "cells", "treatment": "treatment", "timepoints": ["0 min", "15 min"]},
        "temporal_report_evidence_packet": {
            "status": "available", "section_plan": {"observation_only_claim_ceiling": True},
            "records": [{"evidence_id": "DATA-TEMPORAL-SUMMARY", "text": "Measured scope: protein trajectories=10."}],
        },
        "collected_references": [{"pmid": "12345", "title": "Traceable context", "authors": "Author A", "journal": "Journal", "pub_date": "2025"}],
    })["final_report"]
    assert "Prior work reported a phosphorylation profile" in result
    assert "The cited study described a time-resolved proteomic measurement framework" in result
    assert "This study proves direct kinase regulation" not in result
    assert "Our data directly establishes a causal pathway" not in result


def test_observation_only_composer_retains_only_safe_stable_cited_context():
    result = format_citations({
        "sections": {
            "title": "Cited context test",
            "introduction": (
                "Prior work reported a phosphorylation profile under comparable experimental exposure "
                "[REF:pmid:12345]. This Order proves direct kinase regulation [REF:pmid:12345]."
            ),
            "discussion": (
                "The cited study described a time-resolved proteomic measurement framework [REF:pmid:12345]. "
                "Our data directly establishes a causal pathway [REF:pmid:12345]."
            ),
        },
        "network_analysis": {},
        "signal_flow_figures": [],
        "ptm_type": "phosphorylation",
        "experimental_context": {"cell_type": "cells", "treatment": "treatment", "timepoints": ["0 min", "15 min"]},
        "temporal_report_evidence_packet": {
            "status": "available", "section_plan": {"observation_only_claim_ceiling": True},
            "records": [{"evidence_id": "DATA-TEMPORAL-SUMMARY", "text": "Measured scope: protein trajectories=10."}],
        },
        "collected_references": [{"pmid": "12345", "title": "Traceable context", "authors": "Author A", "journal": "Journal", "pub_date": "2025"}],
    })["final_report"]
    assert "Prior work reported a phosphorylation profile" in result
    assert "The cited study described a time-resolved proteomic measurement framework" in result
    assert "This Order proves direct kinase regulation" not in result
    assert "Our data directly establishes a causal pathway" not in result


def test_final_renderer_marks_missing_traceable_bibliography_for_review():
    result = format_citations({
        "sections": {"title": "No literature", "results": "Observed trajectories."},
        "network_analysis": {},
        "signal_flow_figures": [],
        "collected_references": [],
    })
    assert "## References" in result["final_report"]
    assert "Citation completeness status: blocked for review" in result["final_report"]
    assert result["citation_data"]["completion_status"] == "blocked_for_review_missing_traceable_references"


def test_final_renderer_marks_missing_traceable_bibliography_for_review():
    result = format_citations({
        "sections": {"title": "No literature", "results": "Observed trajectories."},
        "network_analysis": {},
        "signal_flow_figures": [],
        "collected_references": [],
    })
    assert "## References" in result["final_report"]
    assert "Citation completeness status: blocked for review" in result["final_report"]
    assert result["citation_data"]["completion_status"] == "blocked_for_review_missing_traceable_references"
