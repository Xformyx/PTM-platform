"""Read-only validation descriptors; execution is not scientific validation."""
from .analysis_universe import signature

VERSION = "analysis_validation_registry.v1"


def validation_record(name, *, requested, execution_status, evaluation_status,
                      method, unit, reason=None, value=None, repetitions=0,
                      seed=None, denominator=None, null_hypothesis=None):
    if evaluation_status != "evaluated" and value is not None:
        raise ValueError("unevaluated_validation_has_value")
    return dict(name=name, requested=requested, execution_status=execution_status,
                evaluation_status=evaluation_status, method=method, unit=unit,
                reason=reason, value=value, repetitions=repetitions, seed=seed,
                denominator=denominator, null_hypothesis=null_hypothesis,
                multiple_testing="not_applicable", independent_biological_validation=False)


def build_validation_registry(scores, sidecar):
    config = scores.get("effective_config", {})
    records = []
    for name, requested, method in (
        ("tmm_noise_bootstrap", config.get("uncertainty_bootstrap_repeats", 0) > 0,
         "condition_mean_gaussian_noise_model_sensitivity"),
        ("tmm_loto", bool(config.get("uncertainty_loto_enabled")), "leave_one_timepoint_out"),
    ):
        # Shared candidate details refer to the same fit. Count each track and
        # feature once; executed settings alone do not establish evaluation.
        attempted, evaluated = set(), set()
        for track in ("relative", "occupancy"):
            for score in scores.get(track, {}).values():
                for detail in score.get("contribution_details", []):
                    uncertainty = detail.get("uncertainty") or detail.get("observation_support") or {}
                    if not uncertainty: continue
                    key = (track, detail["ptm_key"])
                    attempted.add(key)
                    metric = uncertainty.get("bootstrap_top1_stability" if name.endswith("bootstrap") else "loto_top_group_stability")
                    if metric is not None: evaluated.add(key)
        state = "evaluated" if evaluated and len(evaluated)==len(attempted) else "partially_evaluable" if evaluated else "not_evaluable"
        record = validation_record(name, requested=requested,
            execution_status="completed" if requested else "not_requested",
            evaluation_status=state if requested else "not_evaluable", method=method, unit="track_feature_allocation",
            repetitions=config.get("uncertainty_bootstrap_repeats", 0) if name.endswith("bootstrap") else 0,
            seed=config.get("uncertainty_seed"), denominator=len(attempted),
            reason="per_feature_metrics_in_score_artifact" if evaluated else "no_evaluable_allocation" if requested else "not_requested")
        record.update(attempted_count=len(attempted), evaluated_count=len(evaluated), metric_scope="per_feature_not_run_wide_probability")
        records.append(record)
    wave = sidecar.get("temporal_wave_contract", {})
    consensus = wave.get("consensus_membership", {})
    requested = consensus.get("status") not in {None,"disabled"}
    computed = consensus.get("status")=="computed" and consensus.get("usable_replicate_site_count", 0)>0
    records.append(validation_record("wave_replicate_consensus", requested=requested,
        execution_status="completed" if requested else "not_requested",
        evaluation_status="evaluated" if computed else "not_evaluable", method=consensus.get("method", "biological_unit_bootstrap"),
        unit="precursor_feature_with_biological_unit_resampling", reason="per_feature_metrics_in_temporal_artifact" if computed else consensus.get("reason", "not_requested"),
        repetitions=consensus.get("bootstrap_repeats", 0), seed=consensus.get("bootstrap_seed"),
        denominator=consensus.get("usable_replicate_site_count")))
    return {"schema_version": VERSION, "records": records,
            "research_gates": {f"G{i}": {"status": "not_evaluated", "reason": "independent_data_not_bound"} for i in range(1, 6)}}


def compare_engine_bindings(production, comparator):
    """Explicit parity, never transfer historical performance to a new engine."""
    fields = ("measurement_revision", "feature_identity_version", "analysis_scope",
              "candidate_graph_hash", "reference_snapshots", "effective_config", "engine_signature",
              "sample_manifest_hash", "condition_grid", "primary_track", "inference_mode")
    missing = [k for k in fields if production.get(k) is None or comparator.get(k) is None]
    different = [k for k in fields if k not in missing and production[k] != comparator[k]]
    return {"schema_version": "engine_parity.v2", "production_signature": signature(production),
            "comparator_signature": signature(comparator), "missing_fields": missing,
            "different_fields": different, "status": "equivalent" if not missing and not different else "historical_comparator"}
