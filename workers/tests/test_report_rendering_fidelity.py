"""Focused regression tests for deterministic Report rendering boundaries."""

from report_generation.core.biological_synthesis import (
    build_biological_synthesis_packet,
    format_candidate_discovery_packet_for_report,
)
from report_generation.core.dynamic_prompt_generator import build_temporal_evidence_packet
from report_generation.core.graph import format_citations
from report_generation.core.citation_formatter import ReportPostProcessor
from report_generation.core.nodes.kinase_annotation_node import _direct_attribution_figure_allowed
from report_generation.core.nodes.signal_flow_figure import generate_pathway_diagram
from report_generation.core.nodes.writer_node import _stabilize_section_citations


def _sidecar() -> dict:
    return {
        "protein_trajectory_count": 12,
        "ptm_protein_pair_count": 9,
        "cross_layer_edge_count": 0,
        "temporally_eligible_edge_count": 0,
        "mechanism_chain_count": 0,
        "evidence_supported_mechanism_count": 0,
        "kinase_timing_status": "not_evaluable_no_direct_anchor",
        "dynamic_co_wave_transition_status": "computed",
        "dynamic_transition_supported_wave_count": 1,
        "dynamic_transition_pair_count": 2,
        "dynamic_transition_site_count": 2,
        "kinase_feature_evidence_ledger_summary": {
            "feature_record_count": 3030,
            "nominal_aggregate_count": 2447,
            "identity_readiness_counts": {"localization_status": {"not_recorded": 3030}},
            "mapping_readiness": {
                "mapping_bundle_status": "validated",
                "mapping_class_counts": {"M0": 0, "M1": 1, "M2": 0, "M3": 1882, "M4": 1147},
            },
            "relation_readiness": {
                "relation_bundle_status": "validated",
                "relation_class_counts": {"R0": 0, "R1": 3030, "R2": 0, "R3": 0, "R4": 0},
            },
            "candidate_allocation_readiness": {
                "allocation_status": "computed_no_eligible_R3_candidate_sets",
                "eligible_feature_count": 0,
                "mass_conservation_status": "not_evaluable_or_no_candidate_set",
            },
            "direct_kinase_attribution_status": "no_call_without_p3_candidate_allocation_and_required_feature_mapping_localization_relation_provenance",
            "claim_boundary": "Counts are aggregate provenance only and do not establish direct kinase attribution.",
        },
    }


def _p5_packet() -> dict:
    return build_biological_synthesis_packet(
        experimental_context={"cell_type": "generic cells", "treatment": "compound X", "timepoints": ["0min", "30min"]},
        vector_plot_raw_data=[
            {"gene": "DENOVO", "position": "S7", "condition": "0min", "ptm_relative_log2fc": 99.0,
             "Conventional_Log2FC_NA": True, "DeNovo_Confidence": "high", "Ranking_Score": 4.0,
             "Detection_Pattern": "3/4 → 4/4", "Peak_Condition": "30min"},
            {"gene": "DENOVO", "position": "S7", "condition": "30min", "ptm_relative_log2fc": 99.0,
             "Conventional_Log2FC_NA": True, "DeNovo_Confidence": "high", "Ranking_Score": 4.0,
             "Detection_Pattern": "3/4 → 4/4", "Peak_Condition": "30min"},
        ],
        parsed_ptms=[],
        network_analysis={},
        temporal_evidence_packet=build_temporal_evidence_packet(_sidecar()),
        candidate_limit=2,
    )


def test_final_renderer_includes_compact_p0_p3_and_denovo_safe_p5_cards():
    final = format_citations({
        "sections": {"title": "Test report", "results": "Observed trajectories were summarized."},
        "network_analysis": {},
        "signal_flow_figures": [],
        "temporal_report_evidence_packet": build_temporal_evidence_packet(_sidecar()),
        "biological_synthesis_packet": _p5_packet(),
        "collected_references": [],
    })["final_report"]
    assert "Kinase-attribution readiness and provenance boundary" in final
    assert "P0 explicit modified-precursor feature records=3030" in final
    assert "R3=0" in final
    assert "Data-prioritized candidate discoveries" in final
    assert "frozen capped LOD-relative selection effect=4.0" in final
    assert "PTM=99.0" not in final
    assert "direct kinase target" in final


def test_p5_report_renderer_keeps_denovo_detection_context_without_pseudo_log2fc():
    rendered = format_candidate_discovery_packet_for_report(_p5_packet())
    assert "DENOVO S7" in rendered
    assert "de novo detection context" in rendered
    assert "confidence=high" in rendered
    assert "cap=4.0" in rendered
    assert "99.0" not in rendered
    assert "not a confirmed novel substrate" in rendered


def test_citation_renderer_resolves_stable_markers_and_drops_ambiguous_raw_numbers():
    final = format_citations({
        "sections": {
            "title": "Citation test",
            "introduction": "Literature-supported statement [REF:pmid:12345]. Ambiguous local citation [99].",
        },
        "network_analysis": {},
        "signal_flow_figures": [],
        "collected_references": [{
            "pmid": "12345", "title": "Traceable paper", "authors": "Author A", "journal": "Journal", "pub_date": "2025",
        }],
    })
    report = final["final_report"]
    assert "Literature-supported statement [1]." in report
    assert "[99]" not in report
    assert "1. Author A Traceable paper." in report
    assert final["citation_data"]["total_references"] == 1


def test_external_addendum_global_citation_is_retained_as_a_stable_reference():
    final = format_citations({
        "sections": {
            "title": "External citation test",
            "co_scientist_addendum": "A re-resolved follow-up note [1].",
        },
        "co_scientist_status": "ready",
        "co_scientist_integration_mode": "none",
        "network_analysis": {},
        "signal_flow_figures": [],
        "collected_references": [{
            "pmid": "54321", "title": "External traceable paper", "authors": "Author B", "journal": "Journal", "pub_date": "2024",
        }],
    })
    report = final["final_report"]
    assert "re-resolved follow-up note [1]." in report
    assert "External traceable paper" in report
    assert final["citation_data"]["total_references"] == 1


def test_section_local_citation_becomes_identity_marker_before_global_rendering():
    local = [{"pmid": "111", "title": "One"}, {"pmid": "222", "title": "Two"}]
    stabilized = _stabilize_section_citations("First [1], second [2], both [1-2].", local)
    assert "[REF:pmid:111]" in stabilized
    assert "[REF:pmid:222]" in stabilized
    assert "[1-2]" not in stabilized


def test_direct_figure_edges_require_explicit_perturbation_supported_status():
    assert not _direct_attribution_figure_allowed({"temporal_ptm_protein_analysis": _sidecar()})
    permitted = _sidecar()
    permitted["kinase_feature_evidence_ledger_summary"]["direct_kinase_attribution_status"] = (
        "perturbation_supported_direct_kinase_attribution"
    )
    assert _direct_attribution_figure_allowed({"temporal_ptm_protein_analysis": permitted})


def test_pathway_diagram_defaults_to_context_only_output(tmp_path):
    path = generate_pathway_diagram(
        inferred_receptors=[{"name": "REC1", "receptor_class": "receptor", "via_kinases": ["KIN1"]}],
        global_kinase_modules={"kinase_modules": [{"kinase": "KIN1", "canonical": "KIN1", "members": [{"gene": "SITE1", "position": "S10"}]}]},
        enriched_ptm_data=[{"gene": "SITE1", "position": "S10", "ptm_relative_log2fc": 1.2, "q_value": 0.01}],
        output_dir=str(tmp_path),
        experimental_context={"treatment": "compound X"},
    )
    assert path is not None
    output = tmp_path / "pathway_diagram.png"
    assert output.exists() and output.stat().st_size > 1000


def test_report_postprocessor_renumbers_batched_questions_and_collapses_table_separators():
    text = """## Research Question Answers

### Q1: First question?
Answer one.

### Q1: Second question?
Answer two.

| Metric | Value |
|---|---|
|---|---|
| n | 2 |
"""
    processed = ReportPostProcessor().process(text)
    assert "### Q1: First question?" in processed
    assert "### Q2: Second question?" in processed
    assert processed.count("|---|---|") == 1


def test_methods_always_include_conventional_log2fc_reporting_policy_once():
    text = "## Methods\n\nQuantification was performed.\n\n## Results\n\nObserved data."
    processed = ReportPostProcessor().process(text)
    policy = (
        "Large conventional Log2FC values are retained as measured numeric contrasts, "
        "but are not used alone to infer biological priority, mechanistic importance, "
        "or direct regulatory strength."
    )
    assert processed.count(policy) == 1
    assert "### Reporting Policy" in processed


def test_chromadb_bundle_label_without_bibliographic_metadata_is_not_rendered_as_reference():
    final = format_citations({
        "sections": {"title": "Citation provenance", "discussion": "Internal bundle reference [REF:title:allptmarticles]."},
        "network_analysis": {},
        "signal_flow_figures": [],
        "collected_references": [{"chromadb_ref": True, "title": "All PTM Articles"}],
    })
    report = final["final_report"]
    assert "All PTM Articles" not in report
    assert "## References" not in report
