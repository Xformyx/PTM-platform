"""Truth-free static-versus-dynamic co-wave candidate evaluator."""

from __future__ import annotations

from typing import Any, Mapping

from ptm_shared.dynamic_cowave_transition import analyze_dynamic_co_wave_transitions


def evaluate_dynamic_candidate(
    analysis_artifact: Mapping[str, Any],
    *,
    config: Mapping[str, Any],
    adoption_gate: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate an additive transition annotation using no locked truth fields."""

    wave_contract = dict(analysis_artifact.get("temporal_wave_contract") or {})
    if not wave_contract:
        raise ValueError("analysis artifact lacks temporal_wave_contract")
    annotation = analyze_dynamic_co_wave_transitions(wave_contract, config=config)
    summary = dict(annotation.get("summary") or {})
    lotto = dict(annotation.get("lotto") or {})
    pair_lotto = lotto.get("mean_pair_transition_jaccard")
    site_lotto = lotto.get("mean_site_transition_jaccard")
    coverage = summary.get("local_active_pair_coverage")
    resolution = summary.get("transition_resolution")
    stable_waves = int(summary.get("transition_supported_wave_count") or 0)
    numeric = all(value is not None for value in (pair_lotto, site_lotto, coverage, resolution))
    objective = (
        0.45 * float(pair_lotto) + 0.25 * float(site_lotto) + 0.20 * float(coverage) + 0.10 * float(resolution)
        if numeric
        else None
    )
    edge_rows = list((analysis_artifact.get("v2_extensions") or {}).get("cross_layer_edges") or [])
    transition_waves = set(summary.get("transition_supported_wave_ids") or [])
    aligned = [
        row for row in edge_rows
        if row.get("source_wave_id") in transition_waves
        and float(row.get("peak_lag_minutes") or 0.0) > 0.0
    ]
    gate_failures: list[str] = []
    if not numeric:
        gate_failures.append("undefined_lotto_or_coverage_metric")
    if pair_lotto is None or float(pair_lotto) < float(adoption_gate["minimum_pair_loto_jaccard"]):
        gate_failures.append("pair_lotto_below_minimum")
    if site_lotto is None or float(site_lotto) < float(adoption_gate["minimum_site_loto_jaccard"]):
        gate_failures.append("site_lotto_below_minimum")
    if coverage is None or float(coverage) < float(adoption_gate["minimum_active_pair_coverage"]):
        gate_failures.append("active_pair_coverage_below_minimum")
    if resolution is None or not (float(adoption_gate["minimum_transition_resolution_exclusive"]) < float(resolution) < float(adoption_gate["maximum_transition_resolution_exclusive"])):
        gate_failures.append("transition_resolution_outside_nontrivial_range")
    if stable_waves < int(adoption_gate["minimum_stable_transition_waves"]):
        gate_failures.append("no_transition_supported_wave")
    return {
        "schema_version": "dynamic_cowave_truth_free_evaluation.v1",
        "candidate_config": dict(config),
        "dynamic_transition": annotation,
        "metrics": {
            "mean_pair_loto_jaccard": pair_lotto,
            "mean_site_loto_jaccard": site_lotto,
            "local_active_pair_coverage": coverage,
            "transition_resolution": resolution,
            "transition_supported_wave_count": stable_waves,
            "cross_layer_temporal_alignment_count": len(aligned),
            "cross_layer_temporal_alignment_fraction": (len(aligned) / len(edge_rows)) if edge_rows else None,
            "serialized_pair_transition_examples": len(
                ((annotation.get("transition_examples") or {}).get("pair_transitions") or [])
            ),
            "full_pair_transition_count": int(
                ((annotation.get("transition_examples") or {}).get("truncation") or {}).get("pair_transition_total_count") or 0
            ),
            "objective": objective,
        },
        "adoption_gate": {
            "passed": not gate_failures,
            "failures": gate_failures,
            "static_membership_preserved": True,
            "tmm_preserved": True,
            "causality_status": "not_tested",
        },
        "selection_boundary": "Truth-free numeric artifact evaluation only; no workbook truth, biological labels, RAG, LLM, or report context used.",
    }
