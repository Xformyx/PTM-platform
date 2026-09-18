"""Immutable analysis inputs/artifacts using the existing atomic file primitives."""
import json
import fcntl
import os
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from functools import lru_cache
from .analysis_universe import signature
from .report_revision import _atomic_json, file_sha256

INPUT_VERSION = "temporal_analysis_input.v1"
RESULT_VERSION = "temporal_analysis_revision.v1"


@lru_cache(maxsize=256)
def _checked_immutable_hash(path, expected, identity):
    # Identity includes inode, size, mtime and ctime. A modified/replaced file
    # must be hashed again; the filename/revision alone is not trusted.
    if file_sha256(path) != expected:
        raise ValueError("result_artifact_integrity_mismatch")
    return True


def _verify_immutable_file(path, expected):
    stat=path.stat()
    _checked_immutable_hash(str(path),expected,(stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns))


def publish_analysis_input(output_dir, *, config, parent_generation=None, before_publish=None):
    storage = Path(output_dir) / ".analysis_inputs"
    storage.mkdir(parents=True, exist_ok=True)
    with (storage / "publication.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _publish_analysis_input(output_dir, config=config, parent_generation=parent_generation, before_publish=before_publish)


def _publish_analysis_input(output_dir, *, config, parent_generation=None, before_publish=None):
    """Called at preprocessing publication, not on chart or job POST requests."""
    root = Path(output_dir)
    names = sorted(p.name for p in root.iterdir() if p.is_file() and (
        p.name.startswith(("ptm_vector_data_", "ptm_condition_comparisons_", "site_level_relative_quantification_", "all_protein_level_changes_"))
        and p.suffix == ".tsv") or p.is_file() and p.name.startswith(("observation_inventory_", "pipeline_statistics", "import_")) and p.suffix in {".json", ".jsonl"})
    files = [{"name": name, "sha256": file_sha256(root/name)} for name in names]
    quick_manifest = root/"quick_analysis"/"quick_analysis_manifest.json"
    source_paths = {name:root/name for name in names}
    if quick_manifest.is_file():
        source_paths["quick_analysis_manifest.json"] = quick_manifest
        files.append({"name":"quick_analysis_manifest.json", "sha256":file_sha256(quick_manifest)})
    if not any(f["name"].startswith("ptm_vector_data_") for f in files):
        raise ValueError("measurement_artifact_unavailable")
    # Do not persist credentials or unrelated provider settings from worker config.
    effective = {k: config[k] for k in ("ptm_type", "ptm_mode", "sample_manifest", "experimental_context",
                 "analysis_context", "normalization_policy", "temporal_contract", "tmm_config", "analysis_mode", "analysis_options") if k in config}
    effective["analysis_options"] = {k:v for k,v in (config.get("analysis_options") or {}).items() if k.startswith("quick_")}
    manifest = {"schema_version": INPUT_VERSION, "files": files, "config": effective, "parent_generation": parent_generation}
    manifest["input_revision"] = signature(manifest)
    storage = root / ".analysis_inputs"
    storage.mkdir(exist_ok=True)
    destination = storage / manifest["input_revision"]
    if not destination.exists():
        with TemporaryDirectory(dir=storage, prefix="pending-") as temporary:
            tmp = Path(temporary)
            for item in files:
                shutil.copyfile(source_paths[item["name"]], tmp/item["name"])
                if file_sha256(tmp/item["name"]) != item["sha256"]:
                    raise ValueError("input_changed_during_snapshot")
            _atomic_json(tmp/"manifest.json", manifest)
            try:
                os.rename(tmp, destination)
            except FileExistsError:
                verify_input(destination)
    if before_publish is not None:
        before_publish()
    _atomic_json(storage/"current.json", {"input_revision": manifest["input_revision"]})
    return manifest


def input_directory(output_dir, revision=None):
    root = Path(output_dir) / ".analysis_inputs"
    if revision is None:
        revision = json.loads((root/"current.json").read_text())["input_revision"]
    if not isinstance(revision, str) or len(revision) != 64 or any(c not in "0123456789abcdef" for c in revision):
        raise ValueError("invalid_input_revision")
    return root / revision


def verify_input(directory):
    directory = Path(directory)
    manifest = json.loads((directory/"manifest.json").read_text())
    if manifest.get("schema_version") != INPUT_VERSION or signature({k:v for k,v in manifest.items() if k != "input_revision"}) != manifest.get("input_revision"):
        raise ValueError("input_manifest_integrity_mismatch")
    for item in manifest["files"]:
        if Path(item["name"]).name != item["name"] or file_sha256(directory/item["name"]) != item["sha256"]:
            raise ValueError("input_artifact_integrity_mismatch")
    return manifest


def write_stage(directory, name, payload, input_signature):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    # Validate numeric JSON types before the shared atomic serializer runs.
    for _ in json.JSONEncoder(allow_nan=False).iterencode(payload):
        pass
    artifact = directory / f"{name}.json"
    if artifact.exists():
        old = json.loads(artifact.read_text())
        if old != payload:
            raise ValueError("immutable_stage_collision")
    else:
        _atomic_json(artifact, payload)
    return {"name": name, "filename": artifact.name, "sha256": file_sha256(artifact), "input_signature": input_signature}


def verify_result(directory):
    directory = Path(directory)
    manifest = json.loads((directory/"manifest.json").read_text())
    if manifest.get("schema_version") != RESULT_VERSION or manifest.get("execution_status") != "completed":
        raise ValueError("analysis_revision_incomplete")
    if signature({k:v for k,v in manifest.items() if k != "revision_id"}) != manifest.get("revision_id"):
        raise ValueError("result_manifest_integrity_mismatch")
    required = {"input_validation", "candidates", "score", "trajectory_diagnostics", "temporal_diagnostics", "result"}
    names = [a["name"] for a in manifest["artifacts"]]
    if not required.issubset(names) or len(names) != len(set(names)) or not required.issubset(manifest.get("required_stages", [])):
        raise ValueError("analysis_required_stages_incomplete")
    for artifact in manifest["artifacts"]:
        if artifact.get("input_signature") != manifest["input_signature"]:
            raise ValueError("analysis_mixed_stage_signature")
        if Path(artifact["filename"]).name != artifact["filename"]:
            raise ValueError("result_artifact_integrity_mismatch")
        _verify_immutable_file(directory/artifact["filename"],artifact["sha256"])
    return manifest


def resolve_analysis_artifacts(output_dir, pointer):
    """Hydrate a pinned analysis for API/report consumers; never glob a result."""
    root = Path(output_dir).resolve()
    directory = (root / pointer["result_path"]).resolve()
    if not directory.is_relative_to(root / ".analysis_results"):
        raise ValueError("analysis_artifact_outside_order")
    revision = verify_result(directory)
    if pointer.get("revision_id") and pointer["revision_id"] != revision["revision_id"]:
        raise ValueError("analysis_pointer_revision_mismatch")
    result = json.loads((directory/"result.json").read_text())
    candidates = json.loads((directory/"candidates.json").read_text())["manifest"]
    summary = dict(result["temporal_ptm_protein_analysis"])
    summary.update(artifact_path=str((directory/"temporal_diagnostics.json").relative_to(root)),
                   analysis_revision=revision["revision_id"])
    result.update(temporal_ptm_protein_analysis=summary, analysis_revision=revision["revision_id"],
                  result_path=str(directory.relative_to(root)))
    inventory = {"analysis_revision": revision["revision_id"], "input_revision": revision["input_revision"],
                 "analysis_manifest_id": candidates["analysis_manifest_id"], "coverage": result["coverage"], "input_scope":candidates.get("input_scope", {}),
                 "execution_status": revision["execution_status"], "evaluation_status": revision["evaluation_status"],
                 "track_status": result["track_status"], "artifacts": revision["artifacts"],
                 "artifact_directory": str(directory.relative_to(root)), "inventory": candidates["inventory"]}
    return {"heatmap": result, "candidate_manifest": candidates, "evidence_inventory": inventory,
            "revision": revision, "source_directory": input_directory(root, revision["input_revision"])}
