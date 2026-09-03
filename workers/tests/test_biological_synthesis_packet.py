"""Regression coverage for the Gemini biological-synthesis input layer."""

from report_generation.core.biological_synthesis import (
    BIOLOGICAL_SYNTHESIS_CONTRACT,
    build_biological_synthesis_packet,
    build_data_anchored_rag_queries,
    format_biological_synthesis_packet_for_llm,
)
from report_generation.core.report_temporal_fidelity import audit_report_temporal_fidelity
from report_generation.core.rag_retriever import RAGRetriever
from report_generation.core.dynamic_prompt_generator import (
    DynamicPromptGenerator,
    build_nonptm_temporal_analysis,
    build_signal_propagation_json,
)
from report_generation.core.nodes.cascade_mediator_node import extract_discussed_pathways
from pathlib import Path


def _packet() -> dict:
    return build_biological_synthesis_packet(
        experimental_context={
            "cell_type": "HIRc-B fibroblasts",
            "organism": "rat with human INSR transgene",
            "treatment": "insulin",
            "timepoints": ["0min", "5min", "30min", "180min"],
            "biological_question": "Which time-resolved PTM programmes characterize the insulin response?",
        },
        vector_plot_raw_data=[
            {"gene": "MAPK1", "position": "T185", "condition": "0min", "ptm_relative_log2fc": 0.0, "protein_log2fc": 0.0},
            {"gene": "MAPK1", "position": "T185", "condition": "5min", "ptm_relative_log2fc": 1.2, "protein_log2fc": 0.1},
            {"gene": "MAPK1", "position": "T185", "condition": "30min", "ptm_relative_log2fc": 0.3, "protein_log2fc": 0.1},
            {"gene": "PPP4R1", "position": "S493", "condition": "0min", "ptm_relative_log2fc": 0.0, "protein_log2fc": 0.0},
            {"gene": "PPP4R1", "position": "S493", "condition": "5min", "ptm_relative_log2fc": 0.2, "protein_log2fc": 0.0},
            {"gene": "PPP4R1", "position": "S493", "condition": "180min", "ptm_relative_log2fc": 1.6, "protein_log2fc": 0.1},
            {"gene": "unknown", "position": "S1", "condition": "5min", "ptm_relative_log2fc": 9.0},
        ],
        parsed_ptms=[{"gene": "MAPK1"}, {"gene": "PPP4R1"}],
        network_analysis={
            "pathway_expansion": {
                "summaries": [
                    {"pathway": "MAPK signaling", "term": "enriched", "peak_nes": 2.1, "peak_q": 0.01, "n_direct": 4},
                    {"pathway": "Focal adhesion", "term": "enriched", "peak_nes": 1.8, "peak_q": 0.03, "n_direct": 3},
                ]
            }
        },
        temporal_evidence_packet={
            "status": "available",
            "section_plan": {
                "dynamic_context_allowed": True,
                "directed_temporal_context_allowed": False,
                "mechanism_context_allowed": False,
            },
        },
    )


def test_packet_uses_order_measurements_and_excludes_unknown_gene_rows():
    packet = _packet()
    assert packet["contract_version"] == BIOLOGICAL_SYNTHESIS_CONTRACT
    assert packet["quantitative_landscape"]["vector_row_count"] == 7
    assert packet["quantitative_landscape"]["unique_gene_count"] == 2
    assert [card["gene"] for card in packet["candidate_observation_cards"]] == ["PPP4R1", "MAPK1"]
    assert packet["candidate_observation_cards"][0]["profile_label"] == "late-maximal"
    assert packet["candidate_observation_cards"][1]["profile_label"] == "transient-intermediate"
    assert packet["pathway_anchors"][0]["pathway"] == "MAPK signaling"
    assert "direct kinase" in packet["scope"]["direct_kinase_attribution"].lower()


def test_packet_formatter_supplies_named_quantitative_anchors_and_synthesis_pattern():
    text = format_biological_synthesis_packet_for_llm(_packet(), section_type="discussion")
    assert "HIRc-B fibroblasts" in text
    assert "PPP4R1 S493" in text
    assert "MAPK signaling" in text
    assert "measured observation → pathway/candidate context → cited literature comparison" in text
    assert "not direct kinase assignments" in text
    assert "FDR-supported enrichment (statistically significant)" in text
    assert "do not claim stoichiometry or occupancy" in text


def test_pathway_q_value_claim_ceiling_and_legacy_quantitative_prompt_exclude_denovo_pseudofc():
    packet = build_biological_synthesis_packet(
        experimental_context={"cell_type": "generic cells", "treatment": "compound X"},
        vector_plot_raw_data=[
            {"gene": "OBSERVED", "position": "S1", "condition": "0min", "ptm_relative_log2fc": 0.0},
            {"gene": "OBSERVED", "position": "S1", "condition": "30min", "ptm_relative_log2fc": 1.2},
        ],
        parsed_ptms=[],
        network_analysis={
            "pathway_expansion": {"summaries": [
                {"pathway": "FDR pathway", "peak_q": 0.01},
                {"pathway": "Ranked trend", "peak_q": 0.25},
                {"pathway": "Annotation only"},
            ]}
        },
        temporal_evidence_packet={"status": "available", "section_plan": {}},
    )
    classes = {row["pathway"]: row["enrichment_claim_class"] for row in packet["pathway_anchors"]}
    assert classes == {
        "FDR pathway": "fdr_supported",
        "Ranked trend": "descriptive_ranked_trend_not_fdr_supported",
        "Annotation only": "annotation_or_q_not_recorded",
    }
    text = format_biological_synthesis_packet_for_llm(packet, section_type="discussion")
    assert "Ranked trend: term=modulated; q=0.25; wording=top-ranked descriptive pathway trend; do not call significant/enriched" in text
    assert "Only anchors explicitly labelled FDR-supported enrichment" in text

    legacy = DynamicPromptGenerator([
        {"gene": "OBSERVED", "position": "S1", "ptm_relative_log2fc": 1.5, "protein_log2fc": 0.1},
        {
            "gene": "DENOVO", "position": "S2", "ptm_relative_log2fc": 99.0,
            "protein_log2fc": 0.0, "Conventional_Log2FC_NA": True,
            "DeNovo_Confidence": "high", "Ranking_Score": 4.0,
        },
    ])
    quantitative = legacy.get_top_ptms_context()
    assert "DENOVO" not in quantitative
    assert "99.00" not in quantitative
    assert "x)" not in quantitative


def test_data_anchored_rag_plan_covers_system_pathway_candidate_and_temporal_roles():
    queries = build_data_anchored_rag_queries(_packet(), section_type="discussion")
    roles = {query["role"] for query in queries}
    assert {"study_context", "pathway_comparison", "discovery_candidate_biology", "temporal_programme"}.issubset(roles)
    assert any(query.get("anchor") == "PPP4R1" for query in queries)
    assert all(
        "insulin" in query["query"].lower()
        or query["role"] in {"canonical_anchor_biology", "discovery_candidate_biology"}
        for query in queries
    )


def test_candidate_discovery_packet_reserves_annotation_negative_candidates_under_canonical_crowding():
    rows = []
    known_members = []
    for index in range(8):
        gene = f"CAN{index}"
        position = f"S{index + 1}"
        rows.extend([
            {"gene": gene, "position": position, "condition": "0min", "ptm_relative_log2fc": 0.0, "protein_log2fc": 0.0, "q_value": 0.01},
            {"gene": gene, "position": position, "condition": "30min", "ptm_relative_log2fc": 5.0 - index / 10, "protein_log2fc": 0.2, "q_value": 0.01},
        ])
        known_members.append({"key": f"{gene}_{position}", "gene": gene, "position": position, "membership": "confirmed"})
    for gene, position, score, q_value in [("NEW1", "Y10", 0.9, 0.03), ("NEW2", "S25", 0.7, None)]:
        rows.extend([
            {"gene": gene, "position": position, "condition": "0min", "ptm_relative_log2fc": 0.0, "protein_log2fc": 0.0, "q_value": q_value},
            {"gene": gene, "position": position, "condition": "30min", "ptm_relative_log2fc": score, "protein_log2fc": 0.3, "q_value": q_value},
        ])
    packet = build_biological_synthesis_packet(
        experimental_context={"cell_type": "generic cells", "treatment": "compound X", "timepoints": ["0min", "30min"]},
        vector_plot_raw_data=rows,
        parsed_ptms=[],
        network_analysis={},
        temporal_evidence_packet={"status": "available", "section_plan": {}},
        global_kinase_modules={"kinase_modules": [{"members": known_members}]},
        candidate_limit=10,
    )
    discovery = packet["candidate_discovery_packet"]
    cards = discovery["selected_cards"]
    assert discovery["contract_version"] == "candidate_discovery_packet.v1"
    assert {card["gene"] for card in cards}.issuperset({"NEW1", "NEW2"})
    new1 = next(card for card in cards if card["gene"] == "NEW1")
    new2 = next(card for card in cards if card["gene"] == "NEW2")
    assert new1["primary_bucket"] == "annotation_negative_discovery"
    assert new1["selection_components"]["finite_q_value_count"] == 2
    assert new2["selection_components"]["finite_q_value_count"] == 0
    assert discovery["selection_summary"]["selected_by_quota"]["annotation_negative_discovery"] == 2
    assert "direct kinase" in discovery["boundary"].lower()


def test_candidate_discovery_packet_preserves_multisite_and_decoupled_observation_rationale():
    packet = build_biological_synthesis_packet(
        experimental_context={"cell_type": "generic cells", "treatment": "compound X", "timepoints": ["0min", "30min"]},
        vector_plot_raw_data=[
            {"gene": "MULTI", "position": "S10", "condition": "0min", "ptm_relative_log2fc": 0.0, "protein_log2fc": 0.0, "q_value": 0.02},
            {"gene": "MULTI", "position": "S10", "condition": "30min", "ptm_relative_log2fc": 0.9, "protein_log2fc": 0.0, "q_value": 0.02},
            {"gene": "DECOUP", "position": "Y5", "condition": "0min", "ptm_relative_log2fc": 0.0, "protein_log2fc": 0.0},
            {"gene": "DECOUP", "position": "Y5", "condition": "30min", "ptm_relative_log2fc": 1.3, "protein_log2fc": 0.1},
        ],
        parsed_ptms=[],
        network_analysis={},
        temporal_evidence_packet={"status": "available", "section_plan": {}},
        multisite_divergence=[{"gene": "MULTI", "siteA": {"key": "MULTI_S10"}, "siteB": {"key": "MULTI_S20"}}],
    )
    cards = {card["gene"]: card for card in packet["candidate_discovery_packet"]["selected_cards"]}
    assert cards["MULTI"]["primary_bucket"] == "multi_site_divergent"
    assert cards["MULTI"]["selection_components"]["multisite_divergent"] is True
    assert cards["DECOUP"]["primary_bucket"] == "ptm_protein_decoupled"
    assert cards["DECOUP"]["selection_components"]["ptm_protein_decoupled"] is True
    formatted = format_biological_synthesis_packet_for_llm(packet, section_type="discussion")
    assert "bucket=multi_site_divergent" in formatted
    assert "q coverage=0; best q=not recorded" in formatted


def test_candidate_rag_roles_reserve_discovery_and_canonical_anchors():
    packet = _packet()
    packet["candidate_discovery_packet"] = {
        "selected_cards": [
            {"gene": "MAPK1", "primary_bucket": "canonical_context_anchor"},
            {"gene": "PPP4R1", "primary_bucket": "annotation_negative_discovery"},
        ]
    }
    queries = build_data_anchored_rag_queries(packet, section_type="discussion")
    roles = {row["role"] for row in queries}
    assert "canonical_anchor_biology" in roles
    assert "discovery_candidate_biology" in roles
    assert any(row.get("selection_bucket") == "annotation_negative_discovery" for row in queries)


def test_candidate_discovery_selection_is_deterministic_and_not_a_direct_kinase_claim():
    rows = [
        {"gene": "NOVELB", "position": "S2", "condition": "0min", "ptm_relative_log2fc": 0.0, "protein_log2fc": 0.0},
        {"gene": "NOVELB", "position": "S2", "condition": "30min", "ptm_relative_log2fc": 0.8, "protein_log2fc": 0.2},
        {"gene": "NOVELA", "position": "Y1", "condition": "0min", "ptm_relative_log2fc": 0.0, "protein_log2fc": 0.0},
        {"gene": "NOVELA", "position": "Y1", "condition": "30min", "ptm_relative_log2fc": 0.8, "protein_log2fc": 0.2},
    ]
    kwargs = {
        "experimental_context": {"cell_type": "generic cells", "treatment": "compound X", "timepoints": ["0min", "30min"]},
        "parsed_ptms": [],
        "network_analysis": {},
        "temporal_evidence_packet": {"status": "available", "section_plan": {}},
    }
    first = build_biological_synthesis_packet(vector_plot_raw_data=rows, **kwargs)
    second = build_biological_synthesis_packet(vector_plot_raw_data=list(reversed(rows)), **kwargs)
    first_cards = first["candidate_discovery_packet"]["selected_cards"]
    second_cards = second["candidate_discovery_packet"]["selected_cards"]
    assert [(row["gene"], row["position"], row["primary_bucket"]) for row in first_cards] == [
        (row["gene"], row["position"], row["primary_bucket"]) for row in second_cards
    ]
    assert all("kinase" not in row for row in first_cards)
    assert "not direct kinase" in first["candidate_discovery_packet"]["boundary"].lower()


def test_extreme_denovo_pseudo_log2fc_cannot_dominate_candidate_selection_or_llm_card():
    rows = [
        {
            "gene": "DENOVO_EXTREME", "position": "S7", "condition": "0min",
            "ptm_relative_log2fc": 99.0, "Conventional_Log2FC_NA": True,
            "DeNovo_Confidence": "low", "Ranking_Score": 0.10, "LOD_Relative_Log2": 50.0,
        },
        {
            "gene": "DENOVO_EXTREME", "position": "S7", "condition": "30min",
            "ptm_relative_log2fc": 99.0, "Conventional_Log2FC_NA": True,
            "DeNovo_Confidence": "low", "Ranking_Score": 0.10, "LOD_Relative_Log2": 50.0,
        },
        {"gene": "OBSERVED", "position": "Y11", "condition": "0min", "ptm_relative_log2fc": 0.0, "q_value": 0.02},
        {"gene": "OBSERVED", "position": "Y11", "condition": "30min", "ptm_relative_log2fc": 1.2, "q_value": 0.02},
    ]
    packet = build_biological_synthesis_packet(
        experimental_context={"cell_type": "generic cells", "treatment": "compound X", "timepoints": ["0min", "30min"]},
        vector_plot_raw_data=rows,
        parsed_ptms=[],
        network_analysis={},
        temporal_evidence_packet={"status": "available", "section_plan": {}},
        candidate_limit=1,
    )
    cards = packet["candidate_discovery_packet"]["selected_cards"]
    assert [card["gene"] for card in cards] == ["OBSERVED"]
    landscape = packet["quantitative_landscape"]
    assert landscape["maximum_absolute_conventional_ptm_log2fc"] == 1.2
    assert landscape["de_novo_vector_row_count"] == 2

    eligible_rows = [
        {
            "gene": "DENOVO_ELIGIBLE", "position": "S9", "condition": "0min",
            "ptm_relative_log2fc": 99.0, "Conventional_Log2FC_NA": True,
            "DeNovo_Confidence": "high", "Ranking_Score": 4.0, "LOD_Relative_Log2": 99.0,
            "Detection_Pattern": "4/4 → 4/4",
        },
        {
            "gene": "DENOVO_ELIGIBLE", "position": "S9", "condition": "30min",
            "ptm_relative_log2fc": 99.0, "Conventional_Log2FC_NA": True,
            "DeNovo_Confidence": "high", "Ranking_Score": 4.0, "LOD_Relative_Log2": 99.0,
            "Detection_Pattern": "4/4 → 4/4",
        },
        {"gene": "OBSERVED", "position": "Y11", "condition": "0min", "ptm_relative_log2fc": 0.0, "q_value": 0.02},
        {"gene": "OBSERVED", "position": "Y11", "condition": "30min", "ptm_relative_log2fc": 3.8, "q_value": 0.02},
    ]
    packet = build_biological_synthesis_packet(
        experimental_context={"cell_type": "generic cells", "treatment": "compound X", "timepoints": ["0min", "30min"]},
        vector_plot_raw_data=eligible_rows,
        parsed_ptms=[],
        network_analysis={},
        temporal_evidence_packet={"status": "available", "section_plan": {}},
        candidate_limit=2,
    )
    denovo = next(card for card in packet["candidate_discovery_packet"]["selected_cards"] if card["gene"] == "DENOVO_ELIGIBLE")
    assert denovo["selection_components"]["selection_effect"] == 4.0
    assert denovo["selection_components"]["selection_effect_type"] == "de_novo_confidence_weighted_capped_lod_relative"
    assert denovo["profile_label"] == "de_novo_detection_context"
    text = format_biological_synthesis_packet_for_llm(packet, section_type="discussion")
    assert "PTM=99.0" not in text
    assert "selection effect=4.0" in text


def test_denovo_p5_requires_eligible_frozen_score_and_fails_closed_for_mixed_rows():
    base = {
        "experimental_context": {"cell_type": "generic cells", "treatment": "compound X", "timepoints": ["0min", "30min"]},
        "parsed_ptms": [],
        "network_analysis": {},
        "temporal_evidence_packet": {"status": "available", "section_plan": {}},
    }
    rows = [
        {"gene": "LOW", "position": "S1", "condition": "0min", "ptm_relative_log2fc": 99.0, "Conventional_Log2FC_NA": True, "DeNovo_Confidence": "low", "Ranking_Score": 0.8},
        {"gene": "AMBIGUOUS", "position": "S2", "condition": "0min", "ptm_relative_log2fc": 99.0, "Conventional_Log2FC_NA": True, "DeNovo_Confidence": "ambiguous", "Ranking_Score": 0.4},
        {"gene": "MISSING", "position": "S3", "condition": "0min", "ptm_relative_log2fc": 99.0, "Conventional_Log2FC_NA": True, "DeNovo_Confidence": "high"},
        {"gene": "MIXED", "position": "S4", "condition": "0min", "ptm_relative_log2fc": 99.0, "Conventional_Log2FC_NA": True, "DeNovo_Confidence": "low", "Ranking_Score": 0.8},
        {"gene": "MIXED", "position": "S4", "condition": "30min", "ptm_relative_log2fc": 8.0},
        {"gene": "OBSERVED", "position": "Y11", "condition": "0min", "ptm_relative_log2fc": 0.0},
        {"gene": "OBSERVED", "position": "Y11", "condition": "30min", "ptm_relative_log2fc": 0.7},
    ]
    packet = build_biological_synthesis_packet(vector_plot_raw_data=rows, **base)
    assert [card["gene"] for card in packet["candidate_discovery_packet"]["selected_cards"]] == ["OBSERVED"]

    moderate_rows = [
        {"gene": "DENOVO_MODERATE", "position": "S6", "condition": "0min", "ptm_relative_log2fc": 99.0, "Conventional_Log2FC_NA": True, "DeNovo_Confidence": "moderate", "Ranking_Score": 2.2, "Detection_Pattern": "3/4 → 2/4"},
        {"gene": "DENOVO_MODERATE", "position": "S6", "condition": "30min", "ptm_relative_log2fc": 99.0, "Conventional_Log2FC_NA": True, "DeNovo_Confidence": "moderate", "Ranking_Score": 2.2, "Detection_Pattern": "3/4 → 2/4"},
        {"gene": "OBSERVED", "position": "Y11", "condition": "0min", "ptm_relative_log2fc": 0.0},
        {"gene": "OBSERVED", "position": "Y11", "condition": "30min", "ptm_relative_log2fc": 3.0},
    ]
    first = build_biological_synthesis_packet(vector_plot_raw_data=moderate_rows, candidate_limit=2, **base)
    second = build_biological_synthesis_packet(vector_plot_raw_data=list(reversed(moderate_rows)), candidate_limit=2, **base)
    first_cards = first["candidate_discovery_packet"]["selected_cards"]
    second_cards = second["candidate_discovery_packet"]["selected_cards"]
    assert [(card["gene"], card["position"]) for card in first_cards] == [(card["gene"], card["position"]) for card in second_cards]
    moderate = next(card for card in first_cards if card["gene"] == "DENOVO_MODERATE")
    assert moderate["selection_components"]["finite_condition_count"] == 2
    assert moderate["selection_components"]["selection_effect"] == 2.2
    queries = build_data_anchored_rag_queries(first, section_type="discussion")
    moderate_query = next(query for query in queries if query.get("anchor") == "DENOVO_MODERATE")
    assert moderate_query["role"] == "discovery_candidate_biology"
    assert "kinase" not in moderate_query["query"].lower()


def test_non_insulin_order_context_drives_packet_and_rag_without_benchmark_leakage():
    packet = build_biological_synthesis_packet(
        experimental_context={
            "cell_type": "BV2 microglia",
            "organism": "mouse",
            "treatment": "amyloid-beta oligomers",
            "timepoints": ["0h", "1h", "6h"],
            "biological_question": "Which phosphorylation programmes accompany the microglial response?",
        },
        vector_plot_raw_data=[
            {"gene": "SYK", "position": "Y525", "condition": "0h", "ptm_relative_log2fc": 0.0, "protein_log2fc": 0.0},
            {"gene": "SYK", "position": "Y525", "condition": "1h", "ptm_relative_log2fc": 1.1, "protein_log2fc": 0.1},
            {"gene": "SYK", "position": "Y525", "condition": "6h", "ptm_relative_log2fc": 0.4, "protein_log2fc": 0.2},
        ],
        parsed_ptms=[{"gene": "SYK"}],
        network_analysis={
            "pathway_expansion": {"summaries": [{"pathway": "Toll-like receptor signaling", "term": "enriched", "peak_nes": 2.0, "peak_q": 0.02, "n_direct": 2}]}
        },
        temporal_evidence_packet={"status": "available", "section_plan": {}},
    )
    text = format_biological_synthesis_packet_for_llm(packet, section_type="discussion").lower()
    queries = build_data_anchored_rag_queries(packet, section_type="discussion")
    joined_queries = " ".join(row["query"] for row in queries).lower()
    assert "bv2 microglia" in text
    assert "amyloid-beta oligomers" in text
    assert "syk y525" in text
    assert "insulin" not in text
    assert "hir" not in text
    assert "amyloid-beta oligomers" in joined_queries
    assert "toll-like receptor signaling" in joined_queries
    assert "insulin" not in joined_queries


def test_cascade_mediator_uses_discussed_non_insulin_pathway_without_default_insulin_label():
    selected = extract_discussed_pathways(
        {
            "results": "Toll-like receptor signaling was enriched alongside TLR4 and SYK observations.",
            "discussion": "The Toll-like receptor context provides a testable framework for the microglial response.",
        },
        {
            "candidates": [
                {"name": "Toll-like receptor signaling", "genes": ["TLR4", "SYK"], "composite_score": 0.8},
                {"name": "Insulin signaling", "genes": ["INSR", "IRS1"], "composite_score": 0.9},
            ],
            "gene_data": {"TLR4": {}, "SYK": {}, "INSR": {}, "IRS1": {}},
        },
        min_gene_cluster=1,
    )
    assert [row["name"] for row in selected] == ["Toll-like receptor signaling"]


def test_literature_context_is_allowed_but_direct_edge_is_still_flagged_when_no_call():
    packet = {
        "status": "available",
        "section_plan": {"mechanism_context_allowed": False, "observation_only_claim_ceiling": True},
        "records": [],
    }
    context_only = audit_report_temporal_fidelity(
        "Published literature provides MAPK signaling as biological context for the observed early PTM programme.",
        packet,
        section_type="discussion",
    )
    assert context_only["unsafe_temporal_claim_count"] == 0
    direct_edge = audit_report_temporal_fidelity(
        "MAPK1 directly activates the observed downstream substrate in this Order.",
        packet,
        section_type="discussion",
    )
    assert direct_edge["unsafe_temporal_claim_count"] == 1


def test_data_anchored_retrieval_preserves_query_role_and_deduplicates_documents():
    plan = [
        {"role": "study_context", "query": "HIRc-B insulin phosphoproteomics"},
        {"role": "candidate_biology", "query": "PPP4R1 insulin phosphorylation", "anchor": "PPP4R1"},
    ]
    retriever = object.__new__(RAGRetriever)

    def _query(query_text: str, n_results: int):
        shared = {"title": "Shared paper", "document": "shared excerpt"}
        return [shared, {"title": query_text, "document": f"excerpt for {query_text}"}]

    retriever.query_with_reranking = _query
    references = retriever.search_for_biological_synthesis(plan, n_results=4)
    assert len(references) == 3
    assert {row["query_role"] for row in references} == {"study_context", "candidate_biology"}
    assert any(row["query_anchor"] == "PPP4R1" for row in references)


def test_writer_keeps_biological_packet_ahead_of_full_vector_data_in_core_sections():
    writer = Path(__file__).parents[1] / "report_generation/core/nodes/writer_node.py"
    source = writer.read_text(encoding="utf-8")
    required = 'supplement_blocks.append(("biological_synthesis", section_biological_synthesis))'
    assert source.count(required) == 5
    assert source.index(required) < source.index('supplement_blocks.append(("vector_plot_full", aux_vector_plot_full))')
    assert "search_for_biological_synthesis(data_anchored_queries" in source
    assert 'state.get("comovement_analysis") or {}).get("multisite_divergence")' in source


def test_nonptm_context_reports_relative_observed_timing_not_directional_relationships():
    network = {
        "networks": {
            "0min": {
                "ptm_nodes": [{"gene": "MAPK1", "ptm_relative_log2fc": 0.0}],
                "non_ptm_nodes": [{"gene": "HSP90AA1", "protein_log2fc": 0.0}],
                "all_edges": [{"source": "MAPK1", "target": "HSP90AA1"}],
            },
            "30min": {
                "ptm_nodes": [{"gene": "MAPK1", "ptm_relative_log2fc": 1.0}],
                "non_ptm_nodes": [{"gene": "HSP90AA1", "protein_log2fc": 0.6}],
                "all_edges": [{"source": "MAPK1", "target": "HSP90AA1"}],
            },
        }
    }
    text = build_nonptm_temporal_analysis(network, ["0min", "30min"])
    assert "NON-PTM PROTEIN TEMPORAL ABUNDANCE CONTEXT" in text
    assert "Relative Observed Timing" in text
    assert "upstream/downstream relationship" in text
    assert "Upstream of PTM" not in text
    assert "Downstream of PTM" not in text
    assert "Feedback Regulator" not in text
    assert "validation evidence" not in text


def test_temporal_reconfiguration_formatter_does_not_assert_signal_propagation():
    network = {
        "networks": {
            "0min": {"ptm_nodes": [{"gene": "MAPK1", "ptm_relative_log2fc": 0.6}]},
            "30min": {"ptm_nodes": [{"gene": "MAPK1", "ptm_relative_log2fc": 1.0}, {"gene": "PPP4R1", "ptm_relative_log2fc": 0.8}]},
        }
    }
    text = build_signal_propagation_json(network, ["0min", "30min"])
    assert "TEMPORAL PTM-SET RECONFIGURATION" in text
    assert "Signal propagated" not in text
    assert "Temporal Reconfiguration Events" in text
