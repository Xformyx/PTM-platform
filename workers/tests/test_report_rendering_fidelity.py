"""Focused regression tests for deterministic Report rendering boundaries."""

import re

from report_generation.core.biological_synthesis import (
    build_biological_synthesis_packet,
    format_candidate_discovery_packet_for_report,
)
from report_generation.core.dynamic_prompt_generator import build_temporal_evidence_packet
from report_generation.core.graph import format_citations
from report_generation.core.citation_formatter import ReportPostProcessor
from report_generation.core.nodes.kinase_annotation_node import _direct_attribution_figure_allowed
from report_generation.core.nodes.network_node import _generate_legends
from report_generation.core.nodes.question_generator import _get_co_scientist_questions
from report_generation.core.nodes.signal_flow_figure import generate_context_aware_ptm_heatmap, generate_pathway_diagram
from report_generation.core.nodes.temporal_comovement_node import (
    _append_cluster_detail,
    _conventional_members,
    _generate_transient_burst_figure,
)
from report_generation.core.nodes.writer_node import _stabilize_section_citations
from report_generation.core.reader_authoring import (
    build_authoring_packet,
    render_data_only_reader_report,
    validate_and_repair_sections,
)
from report_generation.core.figure_manifest import (
    FigureEligibilityPolicy,
    build_figure_manifest,
    compile_reader_caption,
    select_reader_heatmap_features,
)


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


def test_citation_complete_observation_only_order_replaces_llm_sections_deterministically():
    packet = build_temporal_evidence_packet(_sidecar())
    assert packet["section_plan"]["observation_only_claim_ceiling"] is True
    final = format_citations({
        "report_title": "Observation-only final artifact",
        "experimental_context": {
            "cell_type": "generic cells",
            "treatment": "compound X",
            "timepoints": ["0min", "30min"],
        },
        "sections": {
            "title": "Observation-only final artifact",
            "abstract": "LLM claim: a molecular switch proves direct activation.",
            "introduction": "LLM claim: pathway cascade.",
            "results": "### Nested Results\nLLM claim: kinase X directly drives a functional module.",
            "research_question_answers": "### Q1\nLLM claim: direct causal pathway.",
            "discussion": "### Nested Discussion\nLLM claim: high-priority kinase activity.",
            "conclusion": "LLM claim: validated biological priority.",
        },
        "network_analysis": {},
        "signal_flow_figures": [],
        "temporal_report_evidence_packet": packet,
        "biological_synthesis_packet": _p5_packet(),
        "collected_references": [{
            "chromadb_ref": True,
            "title": "Traceable collection article",
            "authors": "Evidence Author",
            "journal": "Evidence Journal",
            "year": "2025",
            "pmid": "34567890",
            "doi": "10.1000/example.1",
        }],
    })["final_report"]
    assert "Quantitative coverage and evidence status" in final
    assert "Evidence-bounded answers" in final
    assert "Observational conclusion" in final
    assert "molecular switch proves" not in final.lower()
    assert "kinase x directly drives" not in final.lower()
    assert "high-priority kinase" not in final.lower()
    assert "validated biological priority" not in final.lower()
    assert "Traceable collection article" in final
    assert "https://pubmed.ncbi.nlm.nih.gov/34567890/" in final
    assert "[1]" in final
    assert "P0 explicit modified-precursor feature records=3030" in final
    assert "P5 availability" in final


def test_reader_authoring_packet_never_exposes_internal_readiness_labels():
    packet = build_authoring_packet(
        {
            "experimental_context": {
                "cell_type": "generic cells",
                "treatment": "compound X",
                "timepoints": ["0min", "30min"],
            },
            "ptm_type": "phosphorylation",
        },
        temporal_evidence_packet=build_temporal_evidence_packet(_sidecar()),
        biological_synthesis_packet=_p5_packet(),
        references=[{
            "title": "Traceable collection article", "authors": "Evidence Author", "year": "2025",
            "journal": "Evidence Journal", "pmid": "34567890",
        }],
    )
    reader_text = "\n".join(card["reader_summary"] for card in packet["reader_cards"])
    for forbidden in ("P0", "P1", "P2", "P3", "P5", "M1", "R3"):
        assert not re.search(rf"\b{forbidden}\b", reader_text, flags=re.IGNORECASE)
    for forbidden in ("TW-", "not_recorded", "DATA-"):
        assert forbidden.lower() not in reader_text.lower()
    assert packet["mode"] == "citation_complete"
    assert any(card["claim_tier"] == "L1" for card in packet["reader_cards"])


def test_clause_validator_preserves_cited_observation_and_repairs_only_unsafe_clause():
    packet = build_authoring_packet(
        {
            "experimental_context": {"cell_type": "generic cells", "treatment": "compound X"},
            "ptm_type": "phosphorylation",
        },
        temporal_evidence_packet=build_temporal_evidence_packet(_sidecar()),
        biological_synthesis_packet=_p5_packet(),
        references=[{
            "title": "Traceable collection article", "authors": "Evidence Author", "year": "2025",
            "journal": "Evidence Journal", "pmid": "34567890",
        }],
    )
    sections, audit = validate_and_repair_sections(
        {
            "results": (
                "The study measured phosphorylation features [EVID:study.frame]. "
                "Kinase X directly activates its substrate [EVID:study.frame]. "
                "Prior literature provided context [REF:pmid:34567890]."
            )
        },
        packet,
    )
    rendered = sections["results"].lower()
    assert "the study measured phosphorylation features" in rendered
    assert "directly activates" not in rendered
    assert "candidate context" in rendered
    assert "[ref:pmid:34567890]" in rendered
    assert audit["repaired_sentence_count"] >= 1


def test_reader_data_only_fallback_is_substantive_without_internal_statuses():
    packet = build_authoring_packet(
        {
            "experimental_context": {"cell_type": "generic cells", "treatment": "compound X", "timepoints": ["0min", "30min"]},
            "ptm_type": "phosphorylation",
        },
        temporal_evidence_packet=build_temporal_evidence_packet(_sidecar()),
        biological_synthesis_packet=_p5_packet(),
        references=[],
    )
    report = render_data_only_reader_report(
        {}, packet, title="Data-only report", generated_at="2026-09-07 00:00"
    )
    assert "## Abstract" in report and "## Discussion" in report and "## Methods" in report
    assert "traceable publication metadata were not available" in report.lower()
    assert "P0" not in report and "M1" not in report and "R3" not in report
    assert "direct kinase–substrate regulation" in report


def test_authoring_packet_suppresses_kinase_names_when_all_footprints_are_non_evaluable():
    packet = build_authoring_packet(
        {
            "experimental_context": {"cell_type": "generic cells", "treatment": "compound X"},
            "ptm_type": "phosphorylation",
            "kinase_activity_heatmap": {
                "kinase_scores": [{
                    "kinase": "SHOULD_NOT_APPEAR",
                    "footprint_diagnostics": {"status": "not_evaluable"},
                }]
            },
        },
        temporal_evidence_packet=build_temporal_evidence_packet(_sidecar()),
        biological_synthesis_packet=_p5_packet(),
    )
    summaries = "\n".join(card["reader_summary"] for card in packet["reader_cards"])
    assert "SHOULD_NOT_APPEAR" not in summaries
    assert "did not support a stable evaluation of kinase footprint candidate context" in summaries


def test_authoring_packet_uses_kinase_family_not_isoform_specific_activity():
    packet = build_authoring_packet(
        {
            "experimental_context": {"cell_type": "generic cells", "treatment": "compound X"},
            "ptm_type": "phosphorylation",
            "kinase_activity_heatmap": {
                "kinase_scores": [{
                    "kinase": "KIN1",
                    "peak_score": 2.0,
                    "footprint_diagnostics": {"status": "computed"},
                    "footprint_equivalence": {"equivalence_group_id": "KIN1_KIN2", "members": ["KIN1", "KIN2"]},
                }]
            },
        },
        temporal_evidence_packet=build_temporal_evidence_packet(_sidecar()),
        biological_synthesis_packet=_p5_packet(),
    )
    kinase_cards = [card for card in packet["reader_cards"] if card["category"] == "kinase_context"]
    assert len(kinase_cards) == 1
    assert "KIN1 / KIN2 family" in kinase_cards[0]["reader_summary"]
    assert "isoform-specific activity" in kinase_cards[0]["counterevidence"]


def test_shadow_renderer_preserves_validated_narrative_without_deterministic_replacement(tmp_path):
    final = format_citations({
        "report_title": "Reader authoring shadow report",
        "reader_authoring_mode": "shadow",
        "sections": {
            "title": "Reader authoring shadow report",
            "abstract": "Observed temporal profiles were summarized for the recorded study [REF:pmid:34567890].",
            "results": "The quantitative landscape was interpreted as descriptive evidence [REF:pmid:34567890].",
        },
        "network_analysis": {},
        "signal_flow_figures": [],
        "output_dir": str(tmp_path),
        "temporal_report_evidence_packet": build_temporal_evidence_packet(_sidecar()),
        "biological_synthesis_packet": _p5_packet(),
        "collected_references": [{
            "chromadb_ref": True, "title": "Traceable collection article", "authors": "Evidence Author",
            "journal": "Evidence Journal", "year": "2025", "pmid": "34567890",
        }],
    })["final_report"]
    assert "Observed temporal profiles were summarized" in final
    assert "Quantitative coverage and evidence status" not in final
    assert "P0 explicit modified-precursor" not in final
    audit_path = tmp_path / "evidence_and_reproducibility_audit.md"
    assert audit_path.exists()
    audit = audit_path.read_text(encoding="utf-8")
    assert "Evidence and Reproducibility Audit" in audit
    assert "P0 explicit modified-precursor feature records=3030" in audit


def test_shadow_data_only_renderer_keeps_reader_body_and_separate_audit(tmp_path):
    rendered = format_citations({
        "report_title": "Reader authoring data-only report",
        "reader_authoring_mode": "shadow",
        "experimental_context": {
            "cell_type": "generic cells", "treatment": "compound X", "timepoints": ["0min", "30min"],
        },
        "ptm_type": "phosphorylation",
        "sections": {"title": "Reader authoring data-only report"},
        "network_analysis": {},
        "signal_flow_figures": [],
        "output_dir": str(tmp_path),
        "temporal_report_evidence_packet": build_temporal_evidence_packet(_sidecar()),
        "biological_synthesis_packet": _p5_packet(),
        "collected_references": [],
    })
    report = rendered["final_report"]
    assert "## Abstract" in report and "## Results" in report and "## Discussion" in report
    assert "P0 explicit modified-precursor" not in report
    assert "traceable publication metadata were not available" in report.lower()
    assert (tmp_path / "evidence_and_reproducibility_audit.md").exists()


def _complete_conventional_vector_rows() -> list[dict]:
    rows = []
    for index in range(12):
        for condition, value in (("0min", -0.5), ("15min", 0.25), ("60min", 0.75)):
            rows.append({
                "gene": f"GENE{index:02d}",
                "position": f"S{index + 1}",
                "condition": condition,
                "ptm_relative_log2fc": value + (index % 3) * 0.1,
            })
    rows.extend([
        {"gene": "DENOVO", "position": "S99", "condition": "0min", "ptm_relative_log2fc": 99.0, "Conventional_Log2FC_NA": True},
        {"gene": "DENOVO", "position": "S99", "condition": "15min", "ptm_relative_log2fc": 99.0, "Conventional_Log2FC_NA": True},
        {"gene": "DENOVO", "position": "S99", "condition": "60min", "ptm_relative_log2fc": 99.0, "Conventional_Log2FC_NA": True},
    ])
    return rows


def test_figure_manifest_selects_12_to_20_complete_conventional_feature_cards_without_denovo_ranking():
    rows = _complete_conventional_vector_rows()
    selected = select_reader_heatmap_features(rows, ["0min", "15min", "60min"])
    assert len(selected) == 12
    assert all(item["gene"] != "DENOVO" for item in selected)
    assert all("representative signed profile pattern" in item["selection_reason"] for item in selected)
    manifest = build_figure_manifest(
        {"vector_plot_raw_data": rows, "network_analysis": {"timepoints": ["0min", "15min", "60min"]}},
        citation_complete=False,
    )
    heatmap = next(item for item in manifest["figures"] if item["figure_key"] == "reader_quantitative_heatmap")
    assert heatmap["placement"] == "main"
    assert heatmap["suppression_reason"] is None
    caption = compile_reader_caption(heatmap)
    assert "Data unit and scope" in caption and "Visual encoding" in caption and "Interpretation boundary" in caption


def test_figure_policy_suppresses_uncited_context_and_routes_dense_network_to_technical_audit():
    policy = FigureEligibilityPolicy()
    assert policy.classify({"kind": "context_map", "image_path": "/tmp/context.png"}, citation_complete=False) == (
        "suppressed", "traceable_citations_unavailable"
    )
    assert policy.classify({"kind": "dense_network", "image_path": "/tmp/network.png"}, citation_complete=True) == (
        "technical_audit", "dense_or_diagnostic_visualization"
    )


def test_shadow_renderer_inserts_manifest_selected_heatmap_as_main_figure_one(tmp_path):
    final = format_citations({
        "report_title": "Manifest figure report",
        "reader_authoring_mode": "shadow",
        "experimental_context": {"cell_type": "generic cells", "treatment": "compound X"},
        "ptm_type": "phosphorylation",
        "sections": {
            "title": "Manifest figure report",
            "results": "Observed profiles were summarized [REF:pmid:34567890].",
        },
        "network_analysis": {"timepoints": ["0min", "15min", "60min"]},
        "signal_flow_figures": [],
        "output_dir": str(tmp_path),
        "vector_plot_raw_data": _complete_conventional_vector_rows(),
        "kinase_activity_heatmap": {"conditions": ["0min", "15min", "60min"]},
        "temporal_report_evidence_packet": build_temporal_evidence_packet(_sidecar()),
        "biological_synthesis_packet": _p5_packet(),
        "collected_references": [{
            "chromadb_ref": True, "title": "Traceable collection article", "authors": "Evidence Author",
            "journal": "Evidence Journal", "year": "2025", "pmid": "34567890",
        }],
    })
    assert "### Figure 1. Quantitative Phosphorylation-Feature Landscape" in final["final_report"]
    assert "Selection rule:" in final["final_report"]
    manifest = final["figure_manifest"]
    heatmap = next(item for item in manifest["figures"] if item["figure_key"] == "reader_quantitative_heatmap")
    assert heatmap["placement"] == "main"
    assert heatmap["image_path"].endswith("context_ptm_heatmap.png")
    assert "pathway_membership" not in [item["figure_key"] for item in manifest["figures"] if item["placement"] == "main"]
    audit = (tmp_path / "evidence_and_reproducibility_audit.md").read_text(encoding="utf-8")
    assert "reader_quantitative_heatmap" in audit
    assert '"placement": "main"' in audit


def test_p5_report_renderer_keeps_denovo_detection_context_without_pseudo_log2fc():
    rendered = format_candidate_discovery_packet_for_report(_p5_packet())
    assert "DENOVO S7" in rendered
    assert "de novo detection context" in rendered
    assert "confidence=high" in rendered
    assert "cap=4.0" in rendered
    assert "99.0" not in rendered
    assert "not a confirmed novel substrate" in rendered


def test_p5_report_renderer_exposes_explicit_unavailable_state():
    rendered = format_candidate_discovery_packet_for_report({})
    assert "P5 availability: not available" in rendered
    assert "No direct kinase target" in rendered


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


def test_network_legend_uses_measured_contrast_and_candidate_context_not_activation():
    legend = _generate_legends(
        {
            "nodes": [
                {"type": "PTM", "state": "high_active", "id": "SITE1", "value": 2.5},
                {"type": "PTM", "state": "inhibited", "id": "SITE2", "value": -1.8},
            ],
            "edges": [],
        },
        [],
        ptm_type="phosphorylation",
    )["full_legend"]
    assert "Higher measured PTM abundance" in legend
    assert "candidate context" in legend
    assert "Strong upregulation" not in legend
    assert "increased activity" not in legend


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
    assert "## References" in report
    assert "blocked for review" in report
    assert final["citation_data"]["completion_status"] == "blocked_for_review_missing_traceable_references"


def test_postprocessor_removes_orphan_spacing_after_unresolved_citation_drop():
    processed = ReportPostProcessor().process("## Discussion\n\nThis extends prior work .")
    assert "prior work ." not in processed
    assert "prior work." in processed


def test_postprocessor_lowers_numeric_contrast_and_no_null_overclaim_tone():
    text = (
        "## Results\n\n"
        "IRS1 S522 Log2FC 28.97 indicates a molecular switch is flipped. "
        "CFLAR T231 Log2FC 31.98 is a powerful, rapid signal. "
        "UBC T83 Log2FC 32.61 is substantially increased. "
        "The analysis shows significant rewiring and extensive evidence for activation of MAPK and SRC family kinase signaling."
    )
    processed = ReportPostProcessor().process(text)
    assert "molecular switch is flipped" not in processed
    assert "powerful, rapid signal" not in processed
    assert "substantially increased" not in processed
    assert "significant rewiring" not in processed
    assert "extensive evidence for activation of MAPK and SRC family kinase signaling" not in processed
    assert "IRS1 S522 Log2FC 28.97" in processed
    assert "pronounced measured contrast" in processed
    assert "observed interval-wise activity-state concordance change" in processed
    assert "MAPK/SRC-associated pathway context" in processed


def test_postprocessor_lowers_residual_conventional_contrast_and_local_membership_overclaim():
    text = (
        "## Results\n\n"
        "Log2FC 28.97 confirms potent activation and PTM-driven hyperactivation. "
        "This is direct evidence for the dynamic assembly and disassembly of signaling modules. "
        "The transient signaling hubs show extensive rewiring of the phosphoproteome and kinase switching."
    )
    processed = ReportPostProcessor().process(text)
    assert "potent activation" not in processed
    assert "PTM-driven hyperactivation" not in processed
    assert "direct evidence for the dynamic assembly" not in processed
    assert "transient signaling hubs" not in processed
    assert "extensive rewiring" not in processed
    assert "kinase switching" not in processed
    assert "measured contrast" in processed
    assert "observed interval-wise activity-state concordance" in processed


def test_postprocessor_removes_unpersisted_per_wave_biological_process_column():
    text = (
        "| Temporal Cluster | Peak Time | Key Member(s) | Associated Biological Process |\n"
        "|---|---|---|---|\n"
        "| Cluster 1 | 5 min | SITE1 | Proximal signaling |\n"
    )
    processed = ReportPostProcessor().process(text)
    assert "Associated Biological Process" not in processed
    assert "no persisted per-cluster enrichment" in processed


def test_postprocessor_removes_unpersisted_cowave_functional_context_column():
    text = (
        "| Co-Wave | Peak Time | Temporal Pattern | Potential Functional Context (based on members) |\n"
        "|---|---|---|---|\n"
        "| TW-05 | 5 min | transient_burst | Proximal signaling, RNA processing |\n"
    )
    processed = ReportPostProcessor().process(text)
    assert "Potential Functional Context" not in processed
    assert "Proximal signaling, RNA processing" not in processed
    assert "Concordance interpretation boundary" in processed
    assert "| Temporal Profile Cluster | Sampled Maximum | Measured Profile Pattern |" in processed
    assert "not assigned (no persisted per-cluster enrichment)" in processed


def test_postprocessor_enforces_actual_report_claim_and_contrast_boundaries():
    text = (
        "## Results\n\n"
        "The pathway context diagram (Figure 4) places these candidate kinases downstream of inferred upstream receptors. "
        "This high number of unique substrates provides strong, data-anchored evidence for a role for CSNK2 activity in the response. "
        "These events, with their large fold-changes and involvement of key signaling nodes, likely represent critical steps in the propagation of the insulin signal in HIRc-B cells. "
        "Ppp4r1 Log2FC=12.08 shows a PTM-driven hyperactivation pattern.\n\n"
        "## Supplementary Figures\n\n"
        "Panel A (1min): 272 PTMs with higher measured abundance, 65 PTMs with lower measured abundance, 293 context edges. "
        "Largest positive measured contrasts: CFLAR(T231), SITE2(S20). "
        "Descriptive pathway-membership context: Metabolic pathways.\n\n"
        "Top higher measured PTM-abundance contrasts: CFLAR(T231): Log2FC=31.98\n"
    )
    processed = ReportPostProcessor().process(text)
    assert "downstream of inferred upstream receptors" not in processed
    assert "strong, data-anchored evidence for a role" not in processed
    assert "critical steps in the propagation" not in processed
    assert "PTM-driven hyperactivation" not in processed
    assert "candidate footprint context" in processed
    assert "measured contrasts at named sites" in processed
    assert "Largest positive measured contrasts" not in processed
    assert "Top higher measured PTM-abundance contrasts" not in processed
    assert "CFLAR(T231)" not in processed


def test_co_scientist_questions_do_not_presume_kinase_activation_or_wave_function():
    questions = _get_co_scientist_questions({
        "experimental_context": {"cell_type": "generic cells", "treatment": "compound X"},
        "kinase_activity_heatmap": {
            "kinase_scores": [{"kinase": "MAPK1", "peak_score": 0.7, "self_ptm": True, "tmm_n_shared": 4}],
            "cowave_groups": [{"group_id": "TW-01"}],
        },
        "frontend_kinase_analysis": {"temporal_cascade": {"cascade_flow": [{"timepoint": "15min"}]}},
    })
    joined = "\n".join(questions).lower()
    assert "top-activated kinase" not in joined
    assert "which specific substrates do they regulate" not in joined
    assert "functional modules are revealed" not in joined
    assert "autophosphorylation-based activation loops" not in joined
    assert "candidate-context patterns" in joined
    assert "within-cluster interval-wise activity-state concordance" in joined


def test_cluster_detail_excludes_unpersisted_per_wave_functional_annotations():
    parts: list[str] = []
    _append_cluster_detail(
        parts,
        {
            "cluster_id": "TW-01",
            "pattern": "transient_burst",
            "members": ["IRS1_S522"],
            "member_details": [{"key": "IRS1_S522", "activity_class": "regulated"}],
            "activity_class_counts": {"regulated": 1},
            "dominant_activity_class": "regulated",
            "correlation_mean": 0.9,
            "peak_timepoint": "15min",
            "mean_profile": {"0min": 0.0, "15min": 1.5},
            "annotations": {
                "biological_summary": "Metabolic pathway module",
                "per_gene_pathways": {"IRS1": ["Insulin signaling"]},
                "per_gene_shared_pathways": [{"name": "Insulin signaling", "overlap_count": 1, "total_cluster": 1, "members": ["IRS1"]}],
            },
        },
        ["0min", "15min"],
        is_primary=False,
        figure_num=2,
    )
    rendered = "\n".join(parts)
    assert "Concordance interpretation boundary" in rendered
    assert "Metabolic pathway module" not in rendered
    assert "Per-Gene Pathway Mapping" not in rendered
    assert "Shared Pathways Explaining Temporal Coordination" not in rendered


def test_transient_composite_excludes_extreme_denovo_pseudocount_from_numerical_display(tmp_path):
    members = [
        {
            "key": "DENOVO_S7", "activity_class": "de_novo", "control_pseudocount_used": True,
            "max_fc": 99.0, "temporal_values": {"0min": 99.0, "15min": 99.0},
        },
        {
            "key": "CONVENTIONAL_S8", "activity_class": "regulated", "max_fc": 1.2,
            "temporal_values": {"0min": 0.0, "15min": 1.2},
        },
    ]
    assert [member["key"] for member in _conventional_members(members)] == ["CONVENTIONAL_S8"]
    path = _generate_transient_burst_figure(
        [{
            "cluster_id": "TW-01", "member_count": 2, "member_details": members,
            "mean_profile": {"0min": 49.5, "15min": 50.1},
        }],
        ["0min", "15min"], str(tmp_path),
    )
    assert path is not None
    assert (tmp_path / "fig1_transient_burst.png").exists()


def test_dense_context_heatmap_renders_with_adaptive_text_thinning(tmp_path):
    conditions = ["0min", "1min", "5min", "15min"]
    rows = []
    genes = []
    for index in range(20):
        gene = f"GENE{index}"
        genes.append(gene)
        for condition in conditions:
            rows.append({
                "gene": gene,
                "position": f"S{index + 1}",
                "condition": condition,
                "ptm_relative_log2fc": 1.0 if condition != "0min" else 0.0,
            })
    output = generate_context_aware_ptm_heatmap(
        sections={"results": " ".join(genes)},
        vector_plot_raw_data=rows,
        conditions=conditions,
        output_dir=str(tmp_path),
    )
    assert output is not None
    assert (tmp_path / "context_ptm_heatmap.png").exists()
