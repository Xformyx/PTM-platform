from types import SimpleNamespace

from report_generation.core.nodes.question_generator import _get_co_scientist_questions


def _shared_summary() -> dict:
    return {
        "protein_trajectory_count": 24,
        "ptm_protein_pair_count": 8,
        "cross_layer_edge_count": 5,
        "temporally_eligible_edge_count": 3,
        "mechanism_chain_count": 15,
        "evidence_supported_mechanism_count": 0,
        "kinase_timing_status": "not_evaluable",
        "causality_status": "not_tested",
        "top_cross_layer_edges": [
            {
                "edge_id": "TW-01__EFFECTOR1",
                "source_wave_id": "TW-01",
                "target_gene": "EFFECTOR1",
                "direction": "source_precedes_target",
                "peak_lag_minutes": 25.0,
                "eligible_for_mechanism_chain": True,
                "causality_status": "not_tested",
            }
        ],
    }


def test_shared_summary_reaches_question_context_without_causal_claim() -> None:
    summary = _shared_summary()
    questions = _get_co_scientist_questions(
        {
            "frontend_kinase_analysis": {"temporal_ptm_protein_analysis": summary},
            "temporal_ptm_protein_analysis": summary,
            "kinase_activity_heatmap": {"kinase_scores": [], "cowave_groups": []},
            "experimental_context": {},
        }
    )

    assert any("observational temporal candidate" in question for question in questions)
