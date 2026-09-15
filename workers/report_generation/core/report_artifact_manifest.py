"""Build a fail-closed manifest for one shadow Report generation run."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


MANIFEST_VERSION = "reader_report_artifact_manifest.v1"


def report_runtime_provenance():
    """Read allowlisted runtime identifiers; never serialize environment secrets."""
    import os
    import subprocess
    from datetime import datetime, timezone
    from common.section_budgets import SECTION_BUDGET_VERSION
    from common.report_display_policy import effective_display_policy
    from .quantitative_claims import CLAIM_SCHEMA_VERSION
    commit = os.getenv("PTM_GIT_COMMIT") or os.getenv("GIT_COMMIT_SHA")
    dirty = None
    try:
        root = Path(__file__).resolve().parents[3]
        commit = commit or subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL, timeout=3).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=root, text=True, stderr=subprocess.DEVNULL, timeout=3).strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return {"git_commit_sha": commit, "tracked_worktree_dirty": dirty,
            "worker_git_revision": commit or "unknown",
            "worker_image_or_mount_revision": os.getenv("PTM_CONTAINER_DIGEST") or os.getenv("PTM_WORKER_VERSION") or "unknown",
            "container_digest": os.getenv("PTM_CONTAINER_DIGEST"),
            "worker_version": os.getenv("PTM_WORKER_VERSION"),
            "generated_at": datetime.now(timezone.utc).isoformat(), "generation_timezone": "UTC",
            "section_budget_version": SECTION_BUDGET_VERSION, "claim_schema_version": CLAIM_SCHEMA_VERSION,
            "display_policy": effective_display_policy("shadow")}


def persist_report_packets(state, output_dir):
    """Snapshot only current-state derived evidence, without discovering old files."""
    keys = ("authoring_packet", "reader_authoring_plan", "biological_synthesis_packet",
            "finding_literature_retrieval", "figure_manifest", "pathway_expansion",
            "ptm_representation_benchmark", "temporal_report_evidence_packet",
            "report_evidence_utilization")
    paths = {}
    for key in keys:
        value = state.get(key)
        if value is None and key == "report_evidence_utilization":
            packet = state.get("authoring_packet")
            if isinstance(packet, Mapping):
                value = packet.get("report_evidence_utilization")
        if value is None:
            continue
        path = Path(output_dir) / ("report_" + key + ".json")
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        paths[key] = str(path)
    return paths


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(role: str, value: str | Path | None, *, required: bool) -> dict[str, Any]:
    path = Path(str(value or "")) if value else None
    exists = bool(path and path.exists() and path.is_file())
    return {
        "role": role,
        "required": required,
        "path": str(path) if path else None,
        "exists": exists,
        "size_bytes": path.stat().st_size if exists else None,
        "sha256": _sha256(path) if exists else None,
    }


def _load_json(path: str | Path | None) -> Any:
    if not path:
        return None
    candidate = Path(str(path))
    if not candidate.exists():
        return None
    try:
        return json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _enriched_provenance_status(path: str | Path | None) -> dict[str, Any]:
    payload = _load_json(path)
    if isinstance(payload, Mapping):
        payload = next((value for value in payload.values() if isinstance(value, list)), [])
    records = [item for item in payload or [] if isinstance(item, Mapping)] if isinstance(payload, list) else []
    audited = [item for item in records if item.get("site_form_trajectories") or item.get("site_aggregation")]
    invalid = [
        item for item in audited
        if (item.get("site_form_provenance_audit") or {}).get("status") != "validated"
        or not bool(item.get("report_eligible_temporal_site_aggregation"))
    ]
    unaudited_count = len(records) - len(audited)
    status = "validated" if records and len(audited) == len(records) and not invalid else "incompatible"
    return {
        "status": status,
        "record_count": len(records),
        "audited_site_record_count": len(audited),
        "unaudited_site_record_count": unaudited_count,
        "incompatible_site_record_count": len(invalid),
    }


def _temporal_provenance_status(path: str | Path | None) -> dict[str, Any]:
    payload = _load_json(path)
    provenance = dict(payload.get("provenance") or {}) if isinstance(payload, Mapping) else {}
    temporal_input = dict(provenance.get("temporal_input") or {})
    site_audit = dict(temporal_input.get("site_form_provenance_audit") or {})
    crosswalk_audit = dict(temporal_input.get("enriched_vector_crosswalk_audit") or {})
    return {
        "status": (
            "validated"
            if site_audit.get("status") == "validated" and crosswalk_audit.get("status") == "validated"
            else "incompatible"
        ),
        "site_form_provenance_status": site_audit.get("status") or "missing",
        "enriched_vector_crosswalk_status": crosswalk_audit.get("status") or "missing",
        "feature_provenance_input": temporal_input.get("feature_provenance_input"),
    }


def build_report_artifact_manifest(
    *,
    order_id: int,
    output_dir: str | Path,
    report_markdown_paths: list[str | Path],
    vector_path: str | Path | None,
    enriched_path: str | Path | None,
    temporal_sidecar_path: str | Path | None,
    evidence_audit_path: str | Path | None,
    prose_trace_path: str | Path | None,
    output_correctness_path: str | Path | None,
    report_config: Mapping[str, Any] | None,
    temporal_required: bool,
    derived_packet_paths: Mapping[str, str | Path] | None = None,
    report_mode_contract: Mapping[str, Any] | None = None,
    requested_report_config: Mapping[str, Any] | None = None,
    effective_report_config: Mapping[str, Any] | None = None,
    writer_effective_mode: str | None = None,
    graph_effective_mode: str | None = None,
    release_effective_mode: str | None = None,
    report_generation_started_at: str | None = None,
) -> dict[str, Any]:
    artifacts = [
        _artifact("vector_tsv", vector_path, required=True),
        _artifact("enriched_json", enriched_path, required=True),
        _artifact("temporal_sidecar", temporal_sidecar_path, required=temporal_required),
        _artifact("evidence_and_reproducibility_audit", evidence_audit_path, required=True),
        _artifact("prose_trace", prose_trace_path, required=True),
        _artifact("output_correctness_audit", output_correctness_path, required=True),
    ]
    artifacts.extend(
        _artifact(f"report_markdown_{index}", path, required=True)
        for index, path in enumerate(report_markdown_paths, 1)
    )
    artifacts.extend(_artifact(role, path, required=True) for role, path in (derived_packet_paths or {}).items())
    reasons = [
        f"missing_required_artifact:{item['role']}"
        for item in artifacts
        if item["required"] and not item["exists"]
    ]
    enriched_status = _enriched_provenance_status(enriched_path)
    if enriched_status["status"] != "validated":
        reasons.append("enriched_site_form_provenance_not_validated")
    temporal_status = _temporal_provenance_status(temporal_sidecar_path) if temporal_required else {"status": "not_required"}
    if temporal_required and temporal_status["status"] != "validated":
        reasons.append("temporal_site_form_and_vector_provenance_not_validated")

    config_json = json.dumps(dict(report_config or {}), sort_keys=True, separators=(",", ":"), default=str)
    config_sha256 = hashlib.sha256(config_json.encode("utf-8")).hexdigest()
    fingerprint_input = {
        "order_id": int(order_id),
        "config_sha256": config_sha256,
        "artifacts": {item["role"]: item["sha256"] for item in artifacts if item["sha256"]},
    }
    run_fingerprint = hashlib.sha256(
        json.dumps(fingerprint_input, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    manifest = {
        "contract_version": MANIFEST_VERSION,
        "status": "validated" if not reasons else "incompatible",
        "report_eligible": not reasons,
        "order_id": int(order_id),
        "output_dir": str(Path(output_dir)),
        "report_run_fingerprint": run_fingerprint,
        "report_config_sha256": config_sha256,
        "reason_codes": sorted(set(reasons)),
        "artifacts": artifacts,
        "enriched_provenance": enriched_status,
        "temporal_provenance": temporal_status,
        "runtime_provenance": report_runtime_provenance(),
        "report_mode_contract": dict(report_mode_contract or {}),
        "report_mode_contract_sha256": dict(report_mode_contract or {}).get("report_mode_contract_sha256"),
        "requested_report_config": dict(requested_report_config or {}),
        "effective_report_config": dict(effective_report_config or report_config or {}),
        "writer_effective_mode": writer_effective_mode,
        "graph_effective_mode": graph_effective_mode,
        "release_effective_mode": release_effective_mode,
        "report_generation_started_at": report_generation_started_at,
    }
    output_path = Path(output_dir) / "report_artifact_manifest.json"
    output_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["manifest_path"] = str(output_path)
    return manifest


def finalize_rendered_artifacts(manifest: Mapping[str, Any], rendered_paths, figure_manifest, *, requested_formats=None, export_failures=None):
    """Seal only files returned by this export, not stale files found by glob."""
    result = dict(manifest)
    records = [_artifact("rendered_" + Path(path).suffix.lstrip("."), path, required=True)
               for path in sorted(set(map(str, rendered_paths)))]
    for figure in figure_manifest.get("figures") or []:
        if figure.get("placement") in {"main", "supplementary"} and figure.get("insertion_verified"):
            record = _artifact("figure:" + str(figure.get("figure_key")), figure.get("image_path"), required=True)
            record["quantitative_binding_sha256"] = hashlib.sha256(json.dumps(figure.get("quantitative_bindings") or [], sort_keys=True, default=str).encode()).hexdigest()
            record["quantitative_source_artifacts"] = {a["role"]: a["sha256"] for a in result.get("artifacts") or []
                                                        if a["role"] in {"vector_tsv", "temporal_sidecar", "enriched_json"} and a.get("sha256")}
            records.append(record)
    stale_sources = [item["role"] for item in result.get("artifacts") or [] if item.get("sha256")
                     and (not Path(item["path"]).is_file() or _sha256(Path(item["path"])) != item["sha256"])]
    requested = set(requested_formats if requested_formats is not None else ("docx", "html"))
    actual = {Path(r["path"]).suffix.lstrip(".") for r in records if r["exists"] and r["role"].startswith("rendered_")}
    missing = sorted(requested - actual)
    result["requested_formats"] = sorted(requested)
    result["actual_formats"] = sorted(actual)
    result["export_failures"] = list(export_failures or [])
    result["missing_formats"] = missing
    result["render_contract_version"] = "report_rendered_artifacts.v2"
    result["rendered_artifacts"] = records
    result["render_status"] = "recorded" if rendered_paths and records and all(r["exists"] for r in records) and not stale_sources and not missing and not export_failures else "incomplete"
    result["changed_source_artifacts"] = stale_sources
    # Artifact integrity and scientific/publication status remain distinct.
    if missing or export_failures:
        result["report_eligible"] = False
        result["reason_codes"] = sorted(set(result.get("reason_codes") or []) | {"requested_export_incomplete"})
    if stale_sources:
        result["report_eligible"] = False
        result["reason_codes"] = sorted(set(result.get("reason_codes") or []) | {"source_changed_before_export"})
    path = result.get("manifest_path")
    if path:
        target = Path(path)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(target)
    return result


def verify_rendered_artifacts(manifest):
    records = list(manifest.get("rendered_artifacts") or []) + [r for r in manifest.get("artifacts") or [] if r.get("sha256") or r.get("required")]
    mismatches = [r["role"] for r in records
                  if not r.get("sha256") or not r.get("path") or not Path(r["path"]).is_file()
                  or _sha256(Path(r["path"])) != r["sha256"]]
    return {"status": "mismatch" if mismatches else "verified" if manifest.get("rendered_artifacts") else "unavailable",
            "mismatched_roles": mismatches}
