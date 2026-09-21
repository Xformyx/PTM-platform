"""Full production temporal computation; executed only in the durable worker."""
import inspect
import json
import os
import time
import resource
import math
from pathlib import Path
from collections import defaultdict
from ptm_shared.analysis_revision import write_stage
from ptm_shared.tmm_feature_allocation import TMMScoreResults, ALLOCATION_VERSION
from app.services.analysis_universe import prepare_analysis
from app.services.temporal_kinase_scoring import compute_weighted_kinase_scores


DISPLAY_DEFAULTS = {"activity_metric":"weighted_sum", "shrinkage_prior_support":5.0,
    "candidate_hierarchy_mode":"off", "dual_track_correlation_threshold":0.5,
    "dual_track_peak_index_tolerance":1,"dual_track_magnitude_log2_ratio_threshold":1.0}
RESERVED = {"kinase_modules", "ptm_timeseries", "ptm_to_kinases", "conditions_sorted", "ptm_qvalues",
    "ptm_identities", "ptm_is_denovo", "ptm_representation", "enable_trajectory_evidence", "allocation_version",
    "ptm_candidate_weights", "kinase_hierarchy"}


def _sidecar_identity_audits(source_dir, vector_rows):
    """Copy site-form and enriched-vector audits into the TMM sidecar.

    구현 대상: report_artifact_manifest temporal_input identity audits
    사전등록: 해당 없음 (sidecar 메타, 2026-09-21). TMM 점수 변경 아님.
    해석 한계: 감사 상태만 기록한다. 교차검증 통과가 귀속 정확도가 아니다.
    주장 금지: 이 필드로 kinase 예측 개선을 주장하지 않는다.
    """
    from ptm_shared.site_form_provenance import (
        audit_enriched_site_form_records,
        audit_enriched_vector_crosswalk,
    )
    order_root = Path(source_dir).resolve().parent.parent
    enriched_path = next(sorted(order_root.glob("enriched_ptm_data_*.json")), None)
    enriched_rows = []
    if enriched_path and enriched_path.is_file():
        payload = json.loads(enriched_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload = next((value for value in payload.values() if isinstance(value, list)), [])
        enriched_rows = [row for row in (payload or []) if isinstance(row, dict)]
    return {
        "site_form_provenance_audit": audit_enriched_site_form_records(enriched_rows or vector_rows),
        "enriched_vector_crosswalk_audit": audit_enriched_vector_crosswalk(enriched_rows, vector_rows),
    }


def effective_production_config(requested):
    parameters=inspect.signature(compute_weighted_kinase_scores).parameters
    defaults={k:p.default for k,p in parameters.items() if k not in RESERVED and p.default is not inspect.Parameter.empty}
    if set(requested)-set(defaults)-set(DISPLAY_DEFAULTS):
        raise ValueError("unsupported_tmm_configuration")
    result={**defaults,**DISPLAY_DEFAULTS,"profile_support_unit":"measurement_group.v1","profile_prior_policy":"observed_support_only.v1",**requested}
    if result["activity_metric"] not in {"weighted_sum","weighted_mean","shrunken_mean"}:
        raise ValueError("invalid_activity_metric")
    if result["candidate_hierarchy_mode"] not in {"off","family_guard"}:
        raise ValueError("invalid_candidate_hierarchy_mode")
    return result


def score_tracks(manifest, inputs, config):
    modules = manifest["candidate_modules"]
    candidates = defaultdict(list)
    weights = defaultdict(dict)
    families = defaultdict(set)
    for m in modules:
        for member in m["members"]:
            candidates[member["key"]].append(m["canonical"])
            probability = member.get("candidate_probability")
            if probability is not None:
                value = float(probability)
                if not math.isfinite(value) or value < 0:
                    raise ValueError("invalid_candidate_weight")
                weights[member["key"]][m["canonical"]] = value
            family = member.get("hierarchy_family") or m.get("hierarchy_family")
            if family:
                families[m["canonical"]].add(str(family).upper())
    requested = effective_production_config(config.get("tmm_config", {}))
    options = {k:v for k,v in requested.items() if k not in DISPLAY_DEFAULTS}
    options.update(allocation_version=ALLOCATION_VERSION, enable_trajectory_evidence=False)
    options["ptm_candidate_weights"] = dict(weights)
    if requested["candidate_hierarchy_mode"] == "family_guard":
        if any(len(values) > 1 for values in families.values()):
            raise ValueError("conflicting_candidate_hierarchy")
        options["kinase_hierarchy"] = {m["canonical"]:next(iter(families[m["canonical"]]), m["canonical"]) for m in modules}
    conditions = manifest["conditions"]
    relative = compute_weighted_kinase_scores(modules, inputs["ptm_timeseries"], dict(candidates), conditions,
        ptm_qvalues=inputs["ptm_qvalues"], ptm_identities=inputs["features"], ptm_is_denovo=inputs["ptm_is_denovo"],
        ptm_representation={k: "protein_adjusted_relative_ptm_log2_contrast" for k in inputs["features"]}, **options)
    occupancy = compute_weighted_kinase_scores(modules, inputs["occupancy_timeseries"], dict(candidates), conditions,
        ptm_qvalues=inputs["occupancy_qvalues"], ptm_identities=inputs["features"],
        ptm_representation={k: "occupancy_logit_delta" for k in inputs["occupancy_timeseries"]}, **options) if inputs["occupancy_timeseries"] else TMMScoreResults()
    return {"effective_config":requested, "relative": relative, "occupancy": occupancy,
            "allocation_ledger": relative.allocation_ledger, "occupancy_allocation_ledger": occupancy.allocation_ledger,
            "track_status": {name: "evaluated" if any(any(s["scoring_evaluable_observation_counts"].values()) for s in result.values()) else "not_evaluable"
                             for name,result in (("relative",relative),("occupancy",occupancy))}}


def trajectory_diagnostics(scores, manifest, inputs, result_dir):
    from ptm_shared.kinase_trajectory_evidence import attach_trajectory_evidence
    path = Path(result_dir)/"trajectory_targets.jsonl"
    from ptm_shared.kinase_footprint_diagnostics import summarize_weighted_footprint
    from ptm_shared.footprint_coherence import footprint_coherence
    modules={m["canonical"]:m for m in manifest["candidate_modules"]}
    for track in ("relative", "occupancy"):
        for kinase,value in scores[track].items():
            value["coherence_diagnostics"]=footprint_coherence([m["key"] for m in modules[kinase]["members"]],
                inputs["ptm_timeseries" if track=="relative" else "occupancy_timeseries"],manifest["conditions"])
            value["footprint_diagnostics"] = summarize_weighted_footprint(
                value.get("_weighted_site_profiles_for_diagnostics", {}), manifest["conditions"],
                shrinkage_prior_support=manifest.get("config", {}).get("shrinkage_prior_support", 5.0),
                max_leave_one_out=3, exclusive_site_keys=[d.get("ptm_key", "") for d in value.get("contribution_details", []) if d.get("n_competing_kinases") == 0])
    with path.open("x", encoding="utf-8") as stream:
        def sink(record):
            stream.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
        attach_trajectory_evidence(scores["relative"], kinase_modules=manifest["candidate_modules"],
            ptm_timeseries=inputs["ptm_timeseries"], conditions=manifest["conditions"], identities=inputs["features"],
            denovo_keys=inputs["ptm_is_denovo"], target_sink=sink,
            representation={k: "protein_adjusted_relative_ptm_log2_contrast" for k in inputs["features"]})
    scores["trajectory_details_artifact"] = path.name
    occupancy_path = Path(result_dir)/"occupancy_trajectory_targets.jsonl"
    with occupancy_path.open("x", encoding="utf-8") as stream:
        attach_trajectory_evidence(scores["occupancy"], kinase_modules=manifest["candidate_modules"],
            ptm_timeseries=inputs["occupancy_timeseries"], conditions=manifest["conditions"], identities=inputs["features"],
            target_sink=lambda record: stream.write(json.dumps(record, sort_keys=True, allow_nan=False)+"\n"),
            representation={k:"occupancy_logit_delta" for k in inputs["occupancy_timeseries"]})
    scores["occupancy_trajectory_details_artifact"] = occupancy_path.name
    return scores


def temporal_diagnostics(scores, manifest, inputs, source_dir, result_dir, ptm_type):
    from ptm_shared.enrichment_free_temporal_sidecar import build_production_temporal_ptm_protein_analysis
    from ptm_shared.temporal_input_reconstruction import load_biological_replicate_series
    from ptm_shared.study_temporal_context_resolution import resolve_study_temporal_context
    from ptm_shared.vector_snapshot import load_vector_snapshot
    from ptm_shared.tmm_multikinase_integration import build_tmm_site_contribution_matrix
    suffix = "_phospho" if ptm_type == "phosphorylation" else "_ubi"
    replicate, audit = load_biological_replicate_series(source_dir, file_suffix=suffix,
        conditions=manifest["conditions"], sample_manifest=manifest["sample_manifest"], feature_identities=inputs["features"])
    # Protein-layer inputs are immutable copies, not fixed live order paths.
    import shutil
    for path in Path(source_dir).glob("all_protein_level_changes_*.tsv"):
        target = Path(result_dir)/path.name
        if not target.exists(): shutil.copyfile(path, target)
    raw = [row["source_record"] for row in load_vector_snapshot(source_dir, suffix)["rows"]]
    context, _ = resolve_study_temporal_context(experimental_context=manifest["study_context"], declared_conditions=manifest["conditions"], study_id=manifest["analysis_manifest_id"])
    temporal_input_provenance = {
        "analysis_signature": manifest["analysis_manifest_id"],
        "feature_input_sha256": inputs["input_sha256"],
        "biological_replicate_adapter": audit,
    }
    temporal_input_provenance.update(_sidecar_identity_audits(source_dir, raw))
    return build_production_temporal_ptm_protein_analysis(output_dir=Path(result_dir), ptm_type=ptm_type,
        ptm_timeseries=inputs["ptm_timeseries"], conditions=manifest["conditions"], study_context=context,
        tmm_result={"relative_site_contribution_matrix": build_tmm_site_contribution_matrix(scores["relative"])},
        raw_replicate_fc_series=replicate, feature_provenance_rows=raw, feature_identities=inputs["features"],
        temporal_input_provenance=temporal_input_provenance,
        mapping_source_bundle_path=os.getenv("PTM_MAPPING_SOURCE_BUNDLE_PATH"), mapping_snapshot_root=os.getenv("PTM_MAPPING_SNAPSHOT_ROOT"),
        relation_source_bundle_path=os.getenv("PTM_RELATION_SOURCE_BUNDLE_PATH"), relation_snapshot_root=os.getenv("PTM_RELATION_SNAPSHOT_ROOT"))


def render_result(scores, sidecar, manifest, inputs):
    from ptm_shared.enrichment_free_temporal_sidecar import summarize_temporal_ptm_protein_analysis
    from ptm_shared.dual_track_evidence import build_dual_track_evidence
    rows = []
    for kinase, score in scores["relative"].items():
        supported = score["scoring_evaluable_observation_counts"]
        values = {c: score["weighted_up_sums"][c] + score["weighted_down_sums"][c] if supported.get(c) else None for c in manifest["conditions"]}
        finite = {c:v for c,v in values.items() if v is not None}
        peak = max(finite, key=lambda c: abs(finite[c])) if finite else None
        rows.append({"kinase": kinase, "canonical": kinase, "scores": values, "up_sums": score["weighted_up_sums"],
                     "down_sums": score["weighted_down_sums"], "up_counts": score["weighted_up_counts"],
                     "down_counts": score["weighted_down_counts"], "peak_condition": peak,
                     "peak_score": values.get(peak), "substrate_count": score["n_exclusive"]+score["n_shared"],
                     "direction": "substrate_footprint_not_catalytic_activity", "observation_counts": score["observation_counts"],
                     "scoring_evaluable_observation_counts":supported,
                     "trajectory_evidence": score.get("trajectory_evidence"), "footprint_diagnostics": score.get("footprint_diagnostics"), "tmm_identifiability": score["tmm_identifiability"],
                     "coherence":score["coherence_diagnostics"]["mean_abs_pearson"], "coherence_diagnostics":score["coherence_diagnostics"],
                     "tmm_profile_type": score["profile_type"]})
    from ptm_shared.tmm_multikinase_integration import build_tmm_weighted_temporal_cascade
    for row in rows:
        row.update(tmm_weighted_up_sums=row["up_sums"], tmm_weighted_down_sums=row["down_sums"],
                   tmm_weighted_up_counts=row["up_counts"], tmm_weighted_down_counts=row["down_counts"])
    effective = scores["effective_config"]
    cascade = build_tmm_weighted_temporal_cascade(rows, manifest["conditions"],
        activity_metric=effective["activity_metric"], shrinkage_prior_support=effective["shrinkage_prior_support"])
    for row in rows:
        selected = cascade["kinase_profiles"].get(row["canonical"], {})
        row["scores"] = {c:selected.get(c) if row["scoring_evaluable_observation_counts"].get(c) else None for c in manifest["conditions"]}
        finite = {c:v for c,v in row["scores"].items() if v is not None}
        row["peak_condition"] = max(finite, key=lambda c:abs(finite[c])) if finite else None
        row["peak_score"] = finite.get(row["peak_condition"])
    allocations=scores.get('allocation_ledger', {}).get('features', {})
    coverage={**manifest['coverage'],
        'individual_no_call_kinases':sum(not any(v is not None for v in r['scores'].values()) for r in rows),
        'shared_features_evaluation_attempted':len(allocations),
        'shared_features_evaluated':sum(r.get('evaluation_status')=='evaluated' for r in allocations.values()),
        'shared_features_not_evaluable':sum(r.get('evaluation_status')=='not_evaluable' for r in allocations.values()),
        'shared_features_with_unresolved_groups':sum(any(a['entity_type']=='kinase_group' for a in r.get('allocations',[])) for r in allocations.values())}
    return {"analysis_manifest_id": manifest["analysis_manifest_id"], "analysis_scope": manifest["analysis_scope"], "input_scope":manifest.get("input_scope", {}),
            "coverage": coverage, "conditions": manifest["conditions"], "kinase_scores": rows,
            "execution_status": "completed", "evaluation_status": scores["track_status"]["relative"],
            "scoring_method": "temporal_mixture_model_full_precursor.v3", "allocation_version": ALLOCATION_VERSION,
            "track_status": scores["track_status"], "tmm_config":effective, "temporal_cascade":cascade, "evidence_inventory_artifact": "candidates.json",
            "allocation_artifact": "score.json", "trajectory_artifact": "trajectory_diagnostics.json",
            "temporal_ptm_protein_analysis": summarize_temporal_ptm_protein_analysis(sidecar, artifact_path="temporal_diagnostics.json"),
            "dual_track_evidence_contract": build_dual_track_evidence(scores["relative"], scores["occupancy"], manifest["conditions"],
                correlation_threshold=effective["dual_track_correlation_threshold"], peak_index_tolerance=effective["dual_track_peak_index_tolerance"],
                magnitude_log2_ratio_threshold=effective["dual_track_magnitude_log2_ratio_threshold"])}
