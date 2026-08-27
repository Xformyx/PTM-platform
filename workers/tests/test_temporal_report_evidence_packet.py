"""Regression tests for deterministic Report temporal numerical evidence."""

from pathlib import Path

from report_generation.core.dynamic_prompt_generator import (
    build_temporal_evidence_packet,
    build_temporal_evidence_fallback_addendum,
    format_temporal_evidence_packet_for_llm,
)
from report_generation.core.nodes.question_generator import _build_content_for_questions
from report_generation.core.report_temporal_fidelity import audit_report_temporal_fidelity, strip_internal_data_labels


def _sidecar_summary() -> dict:
    return {
        "shared_engine_contract": "temporal_ptm_protein_sidecar.v2",
        "artifact_path": "/tmp/temporal_ptm_protein_analysis_v2.json",
        "protein_trajectory_count": 12,
        "ptm_protein_pair_count": 9,
        "cross_layer_edge_count": 6,
        "temporally_eligible_edge_count": 4,
        "mechanism_chain_count": 4,
        "evidence_supported_mechanism_count": 0,
        "kinase_timing_status": "not_evaluable_no_direct_anchor",
        "dynamic_co_wave_transition_status": "computed",
        "dynamic_transition_supported_wave_count": 2,
        "dynamic_transition_pair_count": 18,
        "dynamic_transition_site_count": 5,
        "dynamic_transition_resolution": 0.5,
        "dynamic_transition_loto": {
            "mean_pair_transition_jaccard": 0.71,
            "mean_site_transition_jaccard": 0.72,
        },
        "dynamic_transition_per_wave": [{
            "static_wave_id": "W1",
            "pair_transition_count": 10,
            "nonpersistence_pair_transition_count": 3,
            "site_transition_count": 2,
            "pair_transition_type_counts": {"persistence": 7, "split": 3},
            "site_transition_type_counts": {"recruitment": 2},
        }],
        "top_cross_layer_edges": [{
            "edge_id": "edge-1",
            "source_wave_id": "W1",
            "target_gene": "TARGET1",
            "direction": "up",
            "onset_lag_minutes": 15,
            "peak_lag_minutes": 30,
            "lag_aware_similarity": 0.82,
            "eligible_for_mechanism_chain": True,
            "temporal_interpretation": "temporal_precedence_supported",
            "causality_status": "not_tested",
        }],
    }


def test_packet_preserves_numerical_fields_and_observational_boundary():
    packet = build_temporal_evidence_packet(_sidecar_summary())

    assert packet["status"] == "available"
    assert packet["record_count"] == 4
    text = format_temporal_evidence_packet_for_llm(packet)
    assert "[DATA-TEMPORAL-SUMMARY]" in text
    assert "protein trajectories=12" in text
    assert "[DATA-DYNAMIC-WAVE-1]" in text
    assert "Static Wave W1" in text
    assert "[DATA-CROSS-LAYER-1]" in text
    assert "onset lag=15 min" in text
    assert "causality=not_tested" in text
    assert "does not establish kinase switching" in text


def test_results_instruction_requires_available_record_classes_and_final_prose_hides_ids():
    packet = build_temporal_evidence_packet(_sidecar_summary())
    text = format_temporal_evidence_packet_for_llm(packet, section_type="results")
    assert "dedicated temporal-evidence paragraph" in text
    assert "Available required classes: dynamic=True; TMM=False; PTM-protein=True; counterevidence=False." in text
    assert "DATA-DYNAMIC-SUMMARY" not in strip_internal_data_labels(text)


def test_packet_unavailable_explicitly_blocks_invented_temporal_claims():
    packet = build_temporal_evidence_packet({})
    assert packet["status"] == "unavailable"
    text = format_temporal_evidence_packet_for_llm(packet)
    assert "Do not invent temporal PTM-protein" in text


def test_ordinary_question_content_includes_deterministic_temporal_packet():
    packet_text = format_temporal_evidence_packet_for_llm(
        build_temporal_evidence_packet(_sidecar_summary())
    )
    content = _build_content_for_questions(
        "summary",
        [],
        temporal_evidence_packet_text=packet_text,
    )
    assert "summary" in content
    assert "DATA-DYNAMIC-SUMMARY" in content


def test_writer_makes_the_packet_mandatory_in_all_temporal_sections():
    writer = Path(__file__).parents[1] / "report_generation/core/nodes/writer_node.py"
    source = writer.read_text(encoding="utf-8")
    required = 'supplement_blocks.append(("temporal_evidence_packet", section_temporal_evidence))'
    assert source.count(required) == 4
    assert source.index(required) < source.index('supplement_blocks.append(("vector_plot_full", aux_vector_plot_full))')
    assert "temporal_report_fidelity[section_type] = audit_report_temporal_fidelity" in source
    assert "kinase_activity_heatmap=(" in source
    assert "build_temporal_evidence_fallback_addendum" in source
    assert '"temporal_report_fidelity.json"' in source
    tasks = Path(__file__).parents[1] / "report_generation/tasks.py"
    task_source = tasks.read_text(encoding="utf-8")
    assert '"llm_draft_section_status"' in task_source
    assert '"fidelity_snapshot"' in task_source


def test_packet_includes_tmm_uncertainty_and_counterevidence_when_persisted():
    summary = _sidecar_summary()
    summary["top_mechanism_counterevidence"] = [{
        "chain_id": "chain-1",
        "status": "insufficient_evidence",
        "reasons": ["no_direct_anchor"],
    }]
    heatmap = {
        "tmm_weighted_temporal_cascade": {
            "activity_metric": "shrunken_mean",
            "timepoints": [{
                "timepoint": "15min",
                "active_kinases": [{
                    "kinase": "KIN1",
                    "canonical": "KIN1",
                    "selected_activity": 0.8,
                    "tmm_weighted_activity": 1.2,
                    "tmm_weighted_substrate_support": 4.0,
                    "direction": "activation",
                    "tmm_evidence": {"profile_support": 4},
                }],
            }],
        },
        "relative_tmm_uncertainty_summary": {"status": "available", "bootstrap_replicates": 50},
    }
    packet = build_temporal_evidence_packet(summary, kinase_activity_heatmap=heatmap)
    ids = {record["evidence_id"] for record in packet["records"]}
    assert "DATA-TMM-KINASE-1" in ids
    assert "DATA-TMM-UNCERTAINTY" in ids
    assert "DATA-COUNTEREVIDENCE-1" in ids


def test_results_fidelity_requires_available_evidence_groups_and_uses_fallback():
    summary = _sidecar_summary()
    summary["top_mechanism_counterevidence"] = [{"chain_id": "chain-1", "reasons": ["not_evaluable"]}]
    heatmap = {
        "tmm_weighted_temporal_cascade": {
            "timepoints": [{
                "timepoint": "15min",
                "active_kinases": [{"kinase": "KIN1", "selected_activity": 0.7}],
            }],
        },
    }
    packet = build_temporal_evidence_packet(summary, kinase_activity_heatmap=heatmap)
    audit = audit_report_temporal_fidelity("Generic pathway text.", packet, section_type="results")
    assert audit["status"] == "review_required"
    assert {"dynamic", "tmm", "cross_layer", "counterevidence"}.issubset(audit["missing_required_groups"])
    addendum = build_temporal_evidence_fallback_addendum(packet)
    audited = audit_report_temporal_fidelity(addendum, packet, section_type="results")
    assert audited["status"] == "pass"


def test_raw_heatmap_without_persisted_tmm_cascade_does_not_create_tmm_record():
    packet = build_temporal_evidence_packet(
        _sidecar_summary(),
        kinase_activity_heatmap={"kinase_scores": [{"kinase": "KIN1", "peak_score": 0.7}]},
    )
    assert not any(record["evidence_id"].startswith("DATA-TMM-KINASE") for record in packet["records"])
