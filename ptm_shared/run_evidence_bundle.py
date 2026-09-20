"""Thin immutable references to existing analysis components; no numeric copies."""
import json
import fcntl
from pathlib import Path
from .analysis_revision import verify_result, _verify_immutable_file
from .analysis_universe import signature
from .report_revision import _atomic_json

VERSION = "run_evidence_bundle.v1"


def publish_analysis_bundle(directory, *, order_id, job_id, parent_generation, reference_snapshots):
    root = Path(directory)
    revision = verify_result(root)
    summary = json.loads((root/"explorer.json").read_text())
    artifacts = {a["name"]: {"filename": a["filename"], "sha256": a["sha256"]} for a in revision["artifacts"]}
    manifest = {"schema_version": VERSION, "order_id": order_id, "run_id": job_id,
        "analysis_job_id": job_id, "parent_generation": parent_generation,
        "revisions": {"measurement": revision["input_revision"], "analysis": revision["revision_id"],
                      "pathway": artifacts["pathway_result.json"]["sha256"],
                      "atlas": artifacts["temporal_diagnostics"]["sha256"], "annotation": None, "report": None},
        "reference_snapshots": reference_snapshots, "artifacts": artifacts,
        "inference_mode":summary.get("inference_mode","legacy_unrecorded"),
        "requested_stages": ["measurement", "analysis", "pathway", "temporal"],
        "execution_status": "completed", "evaluation_status": revision["evaluation_status"],
        "explorer_status": "ready_with_limits", **summary}
    manifest["schema_version"] = VERSION
    manifest["bundle_id"] = job_id + "." + signature(manifest)
    path = root/"run_evidence_manifest.json"
    if path.exists() and json.loads(path.read_text()) != manifest:
        raise ValueError("immutable_bundle_collision")
    if not path.exists(): _atomic_json(path, manifest)
    return verify_bundle(root, order_id=order_id, bundle_id=manifest["bundle_id"])


def verify_bundle(directory, *, order_id, bundle_id=None):
    root = Path(directory)
    manifest = json.loads((root/"run_evidence_manifest.json").read_text())
    expected = manifest["analysis_job_id"] + "." + signature({k:v for k,v in manifest.items() if k != "bundle_id"})
    if (manifest.get("schema_version") != VERSION or manifest.get("order_id") != order_id
            or manifest["bundle_id"] != expected or bundle_id is not None and bundle_id != expected):
        raise ValueError("bundle_identity_mismatch")
    revision = verify_result(root)
    if manifest["revisions"]["analysis"] != revision["revision_id"] or manifest["revisions"]["measurement"] != revision["input_revision"]:
        raise ValueError("bundle_component_mismatch")
    registered = {a["name"]:{"filename":a["filename"],"sha256":a["sha256"]} for a in revision["artifacts"]}
    if manifest["artifacts"] != registered or manifest["revisions"]["pathway"] != registered["pathway_result.json"]["sha256"] or manifest["revisions"]["atlas"] != registered["temporal_diagnostics"]["sha256"]:
        raise ValueError("bundle_component_binding_mismatch")
    for record in manifest["artifacts"].values():
        if Path(record["filename"]).name != record["filename"]:
            raise ValueError("bundle_artifact_path_invalid")
        _verify_immutable_file(root/record["filename"], record["sha256"])
    return manifest


def publish_report_bundle(output_dir, analysis_directory, *, order_id, report_revision, before_publish=None):
    """Append a bundle after the report is sealed. The report binds its parent,
    never the new bundle hash; the computation and parent bundle stay intact.
    """
    from .report_revision import read_revision, verify_revision
    root = Path(output_dir).resolve()
    analysis = Path(analysis_directory).resolve()
    if not analysis.is_relative_to(root/".analysis_results"):
        raise ValueError("analysis_artifact_outside_order")
    parent = verify_bundle(analysis, order_id=order_id)
    report = verify_revision(root, read_revision(root, report_revision))
    if not any(s.get("revision_id")==parent["revisions"]["analysis"] and s.get("evidence_bundle_id")==parent["bundle_id"] for s in report.get("source_revisions", [])):
        raise ValueError("report_analysis_binding_missing")
    derived = {k:v for k,v in parent.items() if k != "bundle_id"}
    derived.update(parent_bundle_id=parent["bundle_id"], analysis_result_path=str(analysis.relative_to(root)),
        revisions={**parent["revisions"],"report":report_revision},
        report_component={"revision_id":report_revision,"registry_sha256":report["registry_sha256"],"release":report["release"]},
        components={**parent["components"],"report":{"status":"completed","release_status":report["release"]["status"]}},
        requested_stages=parent["requested_stages"]+["report"])
    storage=root/".evidence_runs"; storage.mkdir(exist_ok=True)
    with (storage/"publication.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if before_publish: before_publish()
        from .report_explorer_index import build_report_explorer_index, VERSION as INDEX_VERSION
        evidence_index=build_report_explorer_index(root,report,storage/report_revision/INDEX_VERSION/"records.parquet")
        derived["report_evidence_index"]=evidence_index
        derived["revisions"]["annotation"]=evidence_index["annotation_snapshot"]
        derived["components"]["annotation"]={"status":"available" if evidence_index["annotation_snapshot"] else "unavailable",
            "scope":"sealed_report_packets","reason":None if evidence_index["annotation_snapshot"] else "no_sealed_evidence_packets"}
        derived["bundle_id"] = parent["analysis_job_id"]+"."+signature(derived)
        if before_publish: before_publish()
        path=storage/(derived["bundle_id"]+".json")
        if path.exists() and json.loads(path.read_text())!=derived:
            raise ValueError("immutable_bundle_collision")
        if not path.exists(): _atomic_json(path,derived)
        index_path=storage/"index.json"
        index=json.loads(index_path.read_text()) if index_path.exists() else {}
        index.setdefault(derived["bundle_id"],{"analysis_job_id":parent["analysis_job_id"],"report_revision":report_revision,
            "publication_order":len(index)+1})
        _atomic_json(index_path,index)
    return derived


def verify_report_bundle(output_dir, *, order_id, bundle_id):
    from .report_revision import read_revision, verify_revision
    root=Path(output_dir).resolve()
    if Path(bundle_id).name!=bundle_id: raise ValueError("invalid_bundle_id")
    value=json.loads((root/".evidence_runs"/(bundle_id+".json")).read_text())
    expected=value["analysis_job_id"]+"."+signature({k:v for k,v in value.items() if k!="bundle_id"})
    if value["order_id"]!=order_id or bundle_id!=expected: raise ValueError("bundle_identity_mismatch")
    directory=(root/value["analysis_result_path"]).resolve()
    if not directory.is_relative_to(root/".analysis_results"): raise ValueError("analysis_artifact_outside_order")
    parent=verify_bundle(directory,order_id=order_id,bundle_id=value["parent_bundle_id"])
    for key in ("measurement","analysis","pathway","atlas"):
        if value["revisions"][key]!=parent["revisions"][key]: raise ValueError("bundle_component_mismatch")
    if value["artifacts"]!=parent["artifacts"]: raise ValueError("bundle_component_binding_mismatch")
    report=verify_revision(root,read_revision(root,value["revisions"]["report"]))
    if value["report_component"]["registry_sha256"]!=report["registry_sha256"]:
        raise ValueError("report_bundle_integrity_mismatch")
    index=value.get("report_evidence_index")
    if index:
        from .report_explorer_index import VERSION as INDEX_VERSION
        if index.get("schema_version") != INDEX_VERSION: raise ValueError("report_index_schema_incompatible")
        path=(root/index["filename"]).resolve()
        if not path.is_relative_to(root/".evidence_runs"): raise ValueError("report_index_outside_order")
        _verify_immutable_file(path,index["sha256"])
        if value["revisions"]["annotation"]!=index["annotation_snapshot"]: raise ValueError("annotation_binding_mismatch")
    return value
