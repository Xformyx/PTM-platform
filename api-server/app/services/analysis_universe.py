"""Shared full-input adapter used by interactive and queued production analysis."""
import os
from ptm_shared.vector_snapshot import load_vector_snapshot, attach_full_motif_annotations
from ptm_shared.analysis_universe import build_full_candidate_modules, build_analysis_manifest, signature
from ptm_shared.report_revision import file_sha256


def prepare_analysis(output_dir, ptm_type, context=None, *, config=None, scope="full_eligible", subset_ids=None, subset_reason=None):
    suffix = "_phospho" if ptm_type == "phosphorylation" else "_ubi"
    snapshot = attach_full_motif_annotations(load_vector_snapshot(output_dir, suffix), output_dir, suffix)
    paths = {"mapping_manifest": os.getenv("PTM_MAPPING_SOURCE_BUNDLE_PATH"),
             "mapping_root": os.getenv("PTM_MAPPING_SNAPSHOT_ROOT"),
             "relation_manifest": os.getenv("PTM_RELATION_SOURCE_BUNDLE_PATH"),
             "relation_root": os.getenv("PTM_RELATION_SNAPSHOT_ROOT")}
    import json
    from pathlib import Path
    frozen_path = Path(output_dir) / "manifest.json"
    frozen = json.loads(frozen_path.read_text()) if frozen_path.is_file() else {}
    snapshot["input_scope"] = frozen.get("config", {}).get("analysis_options") or {"analysis_mode":"legacy_unknown"}
    modules, sources = build_full_candidate_modules(snapshot, **paths)
    from pathlib import Path
    references = {k: file_sha256(p) if p and Path(p).is_file() else "unavailable"
                  for k, p in paths.items() if k.endswith("manifest")}
    manifest, inputs = build_analysis_manifest(snapshot, candidate_modules=modules,
        sample_manifest=(context or {}).get("sample_manifest"), study_context=context,
        reference_snapshots=references, config=config, scope=scope, subset_ids=subset_ids, subset_reason=subset_reason)
    return manifest, inputs, sources


def module_response(manifest, *, compact=False):
    modules = [{**m, "total_count": len(m["members"]), "confirmed_count": 0,
                "inferred_count": len(m["members"]), "source_count": len(m.get("sources", [])), "cowave_overlap": [],
                "members": [] if compact else [{**x, "evidence": "; ".join(x.get("evidence_roles", []))} for x in m["members"]],
                "members_status":"paged" if compact else "complete"}
               for m in manifest["candidate_modules"]]
    summary_manifest = {k:v for k,v in manifest.items() if k not in {"inventory","candidate_modules","analysis_feature_ids","eligible_feature_ids"}} if compact else manifest
    return {"analysis_manifest": summary_manifest, "analysis_manifest_id": manifest["analysis_manifest_id"],
            "kinase_modules": modules, "tmm_candidate_modules": modules,
            "unassigned_ptms": [] if compact else [{**r, "key":r["feature_id"], "gene":"", "position":"", "motif_families":[]} for r in manifest["inventory"] if r["candidate_status"] == "unassigned"],
            "inventory_status":"paged" if compact else "complete",
            "annotation_details": [], "summary": {**manifest["coverage"], "analysis_scope": manifest["analysis_scope"],
                "total_ptms":manifest["coverage"]["analysis_features"],"total_kinase_modules":len(modules),
                "total_confirmed":0,"total_inferred":manifest["coverage"]["mapped_features"],
                "total_unassigned":manifest["coverage"]["analysis_features"]-manifest["coverage"]["mapped_features"],
                "status_counts":{"unassigned":manifest["coverage"]["analysis_features"]-manifest["coverage"]["mapped_features"]},
                "top_kinases":[]},
            "cowave_cross_analysis": {}, "temporal_cascade": {}, "effector_proteins": [], "wave_kinase_profile": [],
            "_cache_hash": signature(manifest), "_cached": False}
