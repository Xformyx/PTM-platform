"""Offline evaluation of frozen Explorer results; never imported by production.

Reuses the locked scorer and frozen blind-trial ledger. Candidate generation and
numeric inference must finish before this module is allowed to read truth.
"""
import argparse
import json
from pathlib import Path
from ptm_shared.analysis_revision import verify_result
from ptm_shared.analysis_universe import signature
from ptm_shared.analysis_validation_registry import compare_engine_bindings
from ptm_shared.report_revision import file_sha256, _atomic_json
from .contracts import BenchmarkManifest
from .locked_scorer import LockedBenchmarkScorer
from .blind_trial_ledger import verify_ledger
from .result_bundle import write_score_bundle


def evaluate(directory, observations_path, plan_path, output):
    directory,observations_path,plan_path,output=map(Path,(directory,observations_path,plan_path,output))
    # Verify immutable discovery artifacts before resolving any truth path.
    revision=verify_result(directory)
    if output.exists(): raise FileExistsError("evaluation_output_must_be_new")
    plan=json.loads(plan_path.read_text())
    if plan.get("schema_version")!="explorer_evaluation_plan.v1": raise ValueError("unsupported_evaluation_plan")
    observation_hash=file_sha256(observations_path)
    if observation_hash!=plan.get("observations_sha256"): raise ValueError("observations_changed_since_freeze")
    artifact=json.loads(observations_path.read_text())
    provenance=artifact.get("provenance",{})
    if provenance.get("analysis_revision")!=revision["revision_id"]:
        raise ValueError("observations_analysis_binding_missing")
    binding=json.loads((directory/"engine_binding.json").read_text())
    if not any(a["filename"]=="engine_binding.json" for a in revision["artifacts"]):
        raise ValueError("unregistered_engine_binding")
    parity=compare_engine_bindings(binding,plan.get("expected_engine_binding",{}))
    ledger=verify_ledger(plan_path.parent/plan["trial_ledger"])
    frozen=next((r for r in ledger if r["record_sha256"]==plan.get("frozen_trial_sha256")),None)
    if not frozen or frozen["decision"]!="freeze": raise ValueError("frozen_blind_trial_required")
    if frozen["input_hashes"].get("engine")!=binding["engine_signature"] or frozen["input_hashes"].get("effective_config")!=signature(binding["effective_config"]):
        raise ValueError("frozen_engine_config_mismatch")
    status={f"G{i}":{"evaluation_status":"not_evaluated","reason":"required_independent_data_or_metrics_not_bound"} for i in range(6)}
    status["G0"]={"evaluation_status":"evaluated" if parity["status"]=="equivalent" else "not_evaluable",
        "reason":None if parity["status"]=="equivalent" else "historical_comparator",
        "scope":"engine_binding_parity_only","parity":parity}
    output.mkdir(parents=True)
    scored=None
    if plan.get("benchmark_manifest"):
        # Only runner-side code loads the locked truth; it is never copied into
        # the run bundle or passed to discovery, RAG queries or caches.
        benchmark=BenchmarkManifest.load(plan_path.parent/plan["benchmark_manifest"])
        scored=LockedBenchmarkScorer(benchmark).score(artifact)
        write_score_bundle(output/"locked-score",scored,analysis_artifact_path=observations_path,publication_figures=False)
        required=plan.get("required_metrics") or []
        missing=[m for m in required if scored["metrics"].get(m) is None]
        status["G1"]={"evaluation_status":"evaluated" if required and not missing else "not_evaluable",
            "reason":None if required and not missing else "required_metrics_missing",
            "missing_metrics":missing,"metrics":scored["metrics"],
            "denominators":scored["metric_denominators"],"scope":"dataset_specific_locked_anchor_recovery",
            "dataset_id":benchmark.dataset_id,"independent_generalization_established":False}
    result={"schema_version":"explorer_research_evaluation.v1","analysis_revision":revision["revision_id"],
        "observations_sha256":observation_hash,"plan_sha256":file_sha256(plan_path),
        "frozen_trial_sha256":frozen["record_sha256"],"gates":status,
        "default_model_promoted":False,"promotion_eligible":False,
        "promotion_reason":"external_generalization_ablation_calibration_and_intervention_gates_incomplete",
        "independence":{"candidate_reference_snapshots":binding["reference_snapshots"],
            "evaluation_source_ids":plan.get("evaluation_source_ids",[]),
            "status":"not_established","reason":"source_identity_overlap_and_independent_design_require_review"}}
    _atomic_json(output/"evaluation.json",result)
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    for name in ("analysis-directory","observations","plan","output"): parser.add_argument("--"+name,required=True)
    args=parser.parse_args()
    print(json.dumps(evaluate(args.analysis_directory,args.observations,args.plan,args.output)))
