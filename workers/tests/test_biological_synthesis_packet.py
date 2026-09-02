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
    build_nonptm_temporal_analysis,
    build_signal_propagation_json,
)
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


def test_data_anchored_rag_plan_covers_system_pathway_candidate_and_temporal_roles():
    queries = build_data_anchored_rag_queries(_packet(), section_type="discussion")
    roles = {query["role"] for query in queries}
    assert {"study_context", "pathway_comparison", "candidate_biology", "temporal_programme"}.issubset(roles)
    assert any(query.get("anchor") == "PPP4R1" for query in queries)
    assert all("insulin" in query["query"].lower() or query["role"] == "candidate_biology" for query in queries)


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
