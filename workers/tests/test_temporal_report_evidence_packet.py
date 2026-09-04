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
        "dynamic_transition_pair_scope": {
            "candidate_pair_count": 42,
            "non_evaluable_pair_window_count": 6,
        },
        "dynamic_transition_event_exposure": {
            "non_evaluable_site_transition_count": 3,
        },
        "provenance": {
            "wave_input_projection": {
                "missing_value_policy": "complete_case_no_imputation",
                "eligible_site_count": 7,
                "excluded_site_count": 2,
                "excluded_reason_counts": {"incomplete_time_grid": 2},
            },
        },
        "dynamic_transition_per_wave": [{
            "static_wave_id": "W1",
            "pair_transition_count": 10,
            "nonpersistence_pair_transition_count": 3,
            "site_transition_count": 2,
            "pair_transition_type_counts": {"persistence": 7, "split": 3},
            "site_transition_type_counts": {"recruitment": 2},
        }],
        "temporal_precedence_status": {
            "status": "computed",
            "n_sites": 9,
            "n_evaluable": 7,
            "tier_breakdown": {"resolved_within_grid": 5, "left_censored": 2, "not_evaluable": 2},
            "replicate_mode": "replicate_level",
            "n_sites_with_replicate_data": 9,
            "p4_gate_passed": False,
            "claim_boundary": "Observed response timing only; causal interpretation is not supported.",
            "contract_version": "temporal_precedence_output.v1",
        },
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
    assert packet["contract_version"] == "report_temporal_evidence_packet.v4"
    assert packet["record_count"] == 7
    dynamic = next(row for row in packet["records"] if row["evidence_id"] == "DATA-DYNAMIC-SUMMARY")
    assert dynamic["availability"] == "computed"
    assert dynamic["claim_level"] == "L2_observational_dynamic"
    assert "drives" in dynamic["forbidden_verbs"]
    assert packet["section_plan"]["computed_layers"]["dynamic"] is True
    assert packet["section_plan"]["dynamic_context_allowed"] is True
    assert packet["section_plan"]["directed_temporal_context_allowed"] is False
    assert packet["section_plan"]["mechanism_context_allowed"] is False
    text = format_temporal_evidence_packet_for_llm(packet)
    assert "DATA-TEMPORAL-SUMMARY" not in text
    assert "protein trajectories=12" in text
    assert "DATA-DYNAMIC-WAVE-1" not in text
    assert "DATA-TEMPORAL-PRECEDENCE" not in text
    assert "evaluable sites=7" in text
    assert "P4 validation passed=False" in text
    assert "Static Wave W1" in text
    assert "DATA-CROSS-LAYER-1" not in text
    assert "observed onset-timepoint difference=15 min" in text
    assert "causality=not_tested" in text
    assert "does not establish kinase switching" in text
    quality = next(row for row in packet["records"] if row["evidence_id"] == "DATA-WAVE-INPUT-QUALITY")
    assert "complete_case_no_imputation" in quality["text"]
    assert "not converted to biological zeroes" in quality["text"]
    assert "same-Wave candidate pairs=42" in dynamic["text"]
    assert "exposure-dependent descriptive counts" in dynamic["text"]
    readiness = next(row for row in packet["records"] if row["evidence_id"] == "DATA-KINASE-ATTRIBUTION-READINESS")
    assert "P0 explicit modified-precursor feature records=3030" in readiness["text"]
    assert "M3=1882" in readiness["text"]
    assert "R3=0" in readiness["text"]
    assert "eligible feature sets=0" in readiness["text"]


def test_results_instruction_requires_available_record_classes_and_final_prose_hides_ids():
    packet = build_temporal_evidence_packet(_sidecar_summary())
    text = format_temporal_evidence_packet_for_llm(packet, section_type="results")
    assert "SECTION EVIDENCE PLAN" in text
    assert "Claim ceiling=L1_observed_measurement_only" in text
    assert "Do not use receptor-cascade context" in text
    assert "Available required classes: temporal-precedence=True; dynamic=True; TMM=False; PTM-protein=True; counterevidence=False." in text
    assert "DATA-DYNAMIC-SUMMARY" not in strip_internal_data_labels(text)
    assert "DATA-KINASE-ATTRIBUTION-READINESS" not in strip_internal_data_labels(text)
    assert "P0 explicit modified-precursor feature records=3030" in strip_internal_data_labels(text)


def test_packet_unavailable_explicitly_blocks_invented_temporal_claims():
    packet = build_temporal_evidence_packet({})
    assert packet["status"] == "unavailable"
    text = format_temporal_evidence_packet_for_llm(packet)
    assert "Do not invent temporal PTM-protein" in text


def test_zero_temporal_layers_force_observed_measurement_claim_ceiling():
    summary = _sidecar_summary()
    summary.update({
        "dynamic_co_wave_transition_status": "not_evaluable",
        "dynamic_transition_pair_count": 0,
        "dynamic_transition_site_count": 0,
        "dynamic_transition_supported_wave_count": 0,
        "top_cross_layer_edges": [],
        "temporal_precedence_status": {
            "status": "not_evaluable_context_not_registered",
            "n_sites": 0,
            "n_evaluable": 0,
        },
    })
    packet = build_temporal_evidence_packet(summary)
    assert packet["section_plan"]["mechanism_context_allowed"] is False
    assert packet["section_plan"]["results_discussion_claim_ceiling"] == "L1_observed_measurement_only"
    text = format_temporal_evidence_packet_for_llm(packet, section_type="results")
    assert "Mechanism-context allowed in this section=False" in text
    assert "omit that mechanism claim" in text
    assert packet["section_plan"]["observation_only_claim_ceiling"] is True


def test_no_call_claim_ceiling_blocks_direct_and_cascade_language():
    summary = _sidecar_summary()
    summary["temporal_precedence_status"] = {
        "status": "not_evaluable_context_not_registered",
        "n_sites": 0,
        "n_evaluable": 0,
    }
    packet = build_temporal_evidence_packet(summary)
    audit = audit_report_temporal_fidelity(
        "CSNK2 drives a receptor-to-kinase cascade through direct regulation, autophosphorylation, and a feedback loop.",
        packet,
        section_type="results",
    )
    assert audit["status"] == "review_required"
    assert audit["observation_only_claim_ceiling"] is True
    assert audit["unsafe_temporal_claim_count"] == 1


def test_writer_emits_last_wins_observation_only_directive_for_no_call_packet():
    from report_generation.core.nodes.writer_node import _build_observation_only_claim_ceiling

    packet = build_temporal_evidence_packet(_sidecar_summary())
    directive = _build_observation_only_claim_ceiling(
        "results",
        packet["section_plan"],
    )
    assert directive.startswith("=== MANDATORY CURRENT-ORDER CLAIM CEILING")
    assert "substantive biological synthesis" in directive
    assert "MUST NOT state that this Order establishes a receptor-to-kinase-to-substrate propagation path" in directive
    assert "autophosphorylation" in directive
    assert "local temporal co-membership annotations" in directive
    assert "Do not emit DATA-* labels" in directive


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
    assert "DATA-DYNAMIC-SUMMARY" not in content
    assert "transition-supported Waves=2" in content


def test_writer_makes_the_packet_mandatory_in_all_temporal_sections():
    writer = Path(__file__).parents[1] / "report_generation/core/nodes/writer_node.py"
    source = writer.read_text(encoding="utf-8")
    required = 'supplement_blocks.append(("temporal_evidence_packet", section_temporal_evidence))'
    assert source.count(required) == 4
    assert source.index(required) < source.index('supplement_blocks.append(("vector_plot_full", aux_vector_plot_full))')
    assert "temporal_report_fidelity[section_type] = audit_report_temporal_fidelity" in source
    assert "kinase_activity_heatmap=(" in source
    assert "EVIDENCE-CONSTRAINED REWRITE REQUIRED" in source
    assert '"status"] = "blocked_for_review"' in source
    assert "dynamic_context_allowed = bool(temporal_section_plan.get" in source
    assert "MANDATORY CURRENT-ORDER CLAIM CEILING" in source
    assert "generic legacy auxiliary contexts cannot" in source
    assert "directed_temporal_context_allowed = bool(" in source
    assert "base_prompt_directed_context_allowed = (" in source
    assert "if base_prompt_directed_context_allowed else None" in source
    assert "aux_directionality_context and directed_temporal_context_allowed" in source
    assert '"temporal_report_fidelity.json"' in source
    assert 'supplement_blocks.append(("comovement", comovement_llm_context))' not in source
    assert 'supplement_blocks.append(("nonptm_temporal", aux_nonptm_temporal))' not in source
    assert 'supplement_blocks.append(("tf_inference", aux_tf_inference_context))' not in source
    assert 'supplement_blocks.append(("pathway_ctx", aux_pathway_ctx))' not in source
    comovement = Path(__file__).parents[1] / "report_generation/core/nodes/temporal_comovement_node.py"
    comovement_source = comovement.read_text(encoding="utf-8")
    assert "protein_complex_stoichiometry" not in comovement_source
    assert "transcriptional_coregulation" not in comovement_source
    assert "upstream_regulation" not in comovement_source
    assert "Observed sampled-timepoint association only" in comovement_source
    tasks = Path(__file__).parents[1] / "report_generation/tasks.py"
    task_source = tasks.read_text(encoding="utf-8")
    assert '"llm_draft_section_status"' in task_source
    assert '"fidelity_snapshot"' in task_source
    assert '"blocked_for_review_sections"' in task_source
    assert '"constrained_rewrite_sections"' in task_source
    assert '"release_status"' in task_source


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
    assert {"temporal_precedence", "dynamic", "tmm", "cross_layer", "counterevidence"}.issubset(audit["missing_required_groups"])
    addendum = build_temporal_evidence_fallback_addendum(packet)
    audited = audit_report_temporal_fidelity(addendum, packet, section_type="results")
    assert audited["status"] == "pass"
    assert audited["temporal_precedence_trace_status"] == "cited"


def test_raw_heatmap_without_persisted_tmm_cascade_does_not_create_tmm_record():
    packet = build_temporal_evidence_packet(
        _sidecar_summary(),
        kinase_activity_heatmap={"kinase_scores": [{"kinase": "KIN1", "peak_score": 0.7}]},
    )
    assert not any(record["evidence_id"].startswith("DATA-TMM-KINASE") for record in packet["records"])


def test_dynamic_packet_forbids_robust_order_claim_without_a_valid_null_calibration():
    packet = build_temporal_evidence_packet({
        "dynamic_co_wave_transition_status": "computed",
        "dynamic_transition_pair_count": 4,
        "dynamic_transition_site_count": 3,
        "dynamic_temporal_adjacency_status": "not_requested",
        "dynamic_temporal_adjacency_verdict": "not_evaluable",
    })
    rendered = format_temporal_evidence_packet_for_llm(packet, section_type="results")
    assert "No valid global adjacency-order null calibration supports temporal ordering" in rendered
    assert "do not call a co-wave pattern robust, significant, validated, or globally temporally resolved" in rendered
