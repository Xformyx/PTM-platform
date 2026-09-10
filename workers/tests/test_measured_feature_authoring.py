from report_generation.core.reader_authoring import (
    build_authoring_packet,
    deterministic_authoring_plan,
    format_authoring_packet_for_llm,
    render_reader_section_fallback,
)
from report_generation.core.figure_manifest import prepare_reader_figure_manifest
from report_generation.core.graph import format_citations


def _phase2_state():
    rows = []
    for condition, unadjusted, adjusted, protein in (
        ("1min", 0.2, 0.1, 0.1),
        ("5min", 1.3, 0.8, 0.5),
        ("15min", 0.2, -0.2, 0.4),
    ):
        rows.append({
            "gene": "GENEA",
            "position": "S10",
            "condition": condition,
            "Precursor.Id": "GENEA_precursor",
            "Modified.Sequence": "AS(UniMod:21)TYK",
            "Protein.Group": "P_GENEA",
            "ptm_unadjusted_log2fc": unadjusted,
            "ptm_protein_adjusted_log2fc": adjusted,
            "ptm_relative_log2fc": adjusted,
            "protein_log2fc": protein,
            "ptm_reconstructed_log2fc": adjusted + protein,
            "ptm_unadjusted_conventional_log2fc_na": False,
        })
    return {
        "ptm_type": "phosphorylation",
        "experimental_context": {"cell_type": "recorded cell model", "treatment": "recorded treatment", "timepoints": ["1min", "5min", "15min"]},
        "vector_plot_raw_data": rows,
    }


def _packet():
    return build_authoring_packet(
        _phase2_state(),
        temporal_evidence_packet={"records": []},
        biological_synthesis_packet={
            "study_frame": {},
            "quantitative_landscape": {"vector_row_count": 3, "unique_site_count": 1, "unique_gene_count": 1},
        },
        references=[],
    )


def test_phase2_authoring_packet_contains_named_feature_and_independent_adjustment_cards():
    packet = _packet()
    categories = [card["category"] for card in packet["reader_cards"]]

    assert packet["contract_version"] == "reader_authoring_packet.v3"
    assert "measured_feature_observation" in categories
    assert "quantitation_comparison" in categories
    assert any("GENEA" in card["reader_summary"] for card in packet["reader_cards"])
    assert any("independently calculated unadjusted PTM contrast" in card["reader_summary"] for card in packet["reader_cards"])


def test_phase2_manuscript_spine_prioritizes_named_measurements_over_count_inventory():
    packet = _packet()
    plan = deterministic_authoring_plan(packet)

    assert plan["key_findings"][0]["category"] == "measured_feature_observation"
    assert plan["key_findings"][1]["category"] == "quantitation_comparison"
    assert "GENEA" in plan["central_answer"]
    assert "quantitative landscape comprised" not in plan["central_answer"].lower()


def test_phase2_results_fallback_reports_named_features_and_adjustment_before_temporal_status():
    results = render_reader_section_fallback("results", _packet())

    assert "### Named current-order feature observations" in results
    assert "### Protein-adjustment comparison" in results
    assert "GENEA" in results
    assert "independently calculated unadjusted PTM contrast" in results
    assert "PTM_Absolute_Log2FC" not in results


def test_phase2_llm_context_exposes_bounded_cards_without_raw_provenance_fields():
    packet = _packet()
    context = format_authoring_packet_for_llm(packet, "results", deterministic_authoring_plan(packet))

    assert "GENEA" in context
    assert "protein adjustment" in context.lower()
    assert "measurement_provenance" not in context
    assert "ptm_reconstructed_log2fc" not in context.lower()
    assert "does not prove that the adjusted value is biologically truer" in context


def test_phase2_citation_complete_packet_keeps_current_observations_distinct_from_literature():
    packet = build_authoring_packet(
        _phase2_state(),
        temporal_evidence_packet={"records": []},
        biological_synthesis_packet={"study_frame": {}, "quantitative_landscape": {}},
        references=[{
            "pmid": "12345678",
            "title": "Traceable temporal phosphoproteomics study",
            "authors": "Author A",
            "journal": "Evidence Journal",
            "year": "2024",
            "reader_excerpt": "The cited study reported a time-resolved phosphoproteomics design.",
        }],
    )
    categories = [card["category"] for card in packet["reader_cards"]]
    discussion = format_authoring_packet_for_llm(packet, "discussion", deterministic_authoring_plan(packet))

    assert packet["mode"] == "citation_complete"
    assert "measured_feature_observation" in categories
    assert "traceable_literature" in categories
    assert "[REF:pmid:12345678]" in discussion
    assert "GENEA" in discussion


def test_phase2_prepared_manifest_adds_verified_protein_adjustment_figure(tmp_path):
    state = {**_phase2_state(), "output_dir": str(tmp_path)}
    manifest = prepare_reader_figure_manifest(state, citation_complete=False)
    figure = next(item for item in manifest["figures"] if item.get("figure_key") == "reader_protein_context")

    assert manifest["contract_version"] == "report_figure_manifest.v3"
    assert figure["placement"] == "main"
    assert figure["insertion_verified"] is True
    assert figure["display_label"].startswith("Figure ")
    assert figure["matched_feature_count"] == 3
    assert figure["reconstructed_metric_excluded"] is True
    assert figure["de_novo_excluded"] is True
    assert tmp_path.joinpath("reader_protein_adjustment_comparison.png").stat().st_size > 1000

    packet = build_authoring_packet(
        {**state, "figure_manifest": manifest},
        temporal_evidence_packet={"records": []},
        biological_synthesis_packet={"study_frame": {}, "quantitative_landscape": {}},
        references=[],
    )
    assert any(card["figure_key"] == "reader_protein_context" for card in packet["figure_cards"])


def test_phase2_manifest_suppresses_adjustment_figure_when_independent_axis_is_missing(tmp_path):
    state = {
        "output_dir": str(tmp_path),
        "vector_plot_raw_data": [{
            "gene": "GENEA",
            "position": "S10",
            "condition": "5min",
            "ptm_relative_log2fc": 0.8,
            "protein_log2fc": 0.5,
            "ptm_absolute_log2fc": 1.3,
        }],
    }
    manifest = prepare_reader_figure_manifest(state, citation_complete=False)

    assert all(item.get("figure_key") != "reader_protein_context" for item in manifest["figures"])


def test_phase2_final_renderer_inserts_verified_adjustment_figure_once(tmp_path):
    state = {
        **_phase2_state(),
        "output_dir": str(tmp_path),
        "reader_authoring_mode": "shadow",
        "report_config": {"reader_authoring_mode": "shadow"},
        "report_title": "Measured feature report",
        "sections": {
            "title": "Measured feature report",
            "abstract": "The recorded experiment measured named phosphorylation features over time.",
            "introduction": "The analysis compares independent and protein-adjusted PTM contrasts.",
            "methods": "Independent unadjusted values were computed from normalized modified-precursor replicates.",
            "results": "Named current-order measurements were summarized before aggregate temporal context.",
            "discussion": "The arithmetic comparison does not establish biological truth or direct regulation.",
            "conclusion": "The measured comparison defines a bounded next validation question.",
            "research_question_answers": "The current data establish measured contrasts only.",
        },
        "network_analysis": {},
        "signal_flow_figures": [],
        "collected_references": [],
        "temporal_report_evidence_packet": {"records": []},
        "biological_synthesis_packet": {"study_frame": {}, "quantitative_landscape": {}},
    }
    state["figure_manifest"] = prepare_reader_figure_manifest(state, citation_complete=False)
    result = format_citations(state)
    report = result["final_report"]

    assert report.count("Independent PTM and Protein-Adjustment Comparison") == 2
    assert report.count("reader_protein_adjustment_comparison.png") == 1
    assert "PTM_Absolute_Log2FC" not in report
    assert result["report_output_correctness"]["phantom_figure_mentions"] == []
    assert "missing_rendered_figure_path" not in result["report_output_correctness"]["reason_codes"]
