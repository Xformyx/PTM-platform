"""Build a fail-closed manifest for one shadow Report generation run."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


MANIFEST_VERSION = "reader_report_artifact_manifest.v1"


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
    }
    output_path = Path(output_dir) / "report_artifact_manifest.json"
    output_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["manifest_path"] = str(output_path)
    return manifest


def finalize_rendered_artifacts(manifest: Mapping[str, Any], rendered_paths, figure_manifest):
    """Seal only files returned by this export, not stale files found by glob."""
    result = dict(manifest)
    records = [_artifact("rendered_" + Path(path).suffix.lstrip("."), path, required=True)
               for path in sorted(set(map(str, rendered_paths)))]
    for figure in figure_manifest.get("figures") or []:
        if figure.get("placement") == "main" and figure.get("insertion_verified"):
            record = _artifact("figure:" + str(figure.get("figure_key")), figure.get("image_path"), required=True)
            record["quantitative_binding_sha256"] = hashlib.sha256(json.dumps(figure.get("quantitative_bindings") or [], sort_keys=True, default=str).encode()).hexdigest()
            records.append(record)
    stale_sources = [item["role"] for item in result.get("artifacts") or [] if item.get("sha256")
                     and (not Path(item["path"]).is_file() or _sha256(Path(item["path"])) != item["sha256"])]
    result["render_contract_version"] = "report_rendered_artifacts.v1"
    result["rendered_artifacts"] = records
    result["render_status"] = "recorded" if rendered_paths and records and all(r["exists"] for r in records) and not stale_sources else "incomplete"
    result["changed_source_artifacts"] = stale_sources
    # Artifact integrity and scientific/publication status remain distinct.
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
    mismatches = [r["role"] for r in manifest.get("rendered_artifacts") or []
                  if not r.get("sha256") or not r.get("path") or not Path(r["path"]).is_file()
                  or _sha256(Path(r["path"])) != r["sha256"]]
    return {"status": "mismatch" if mismatches else "verified" if manifest.get("rendered_artifacts") else "unavailable",
            "mismatched_roles": mismatches}
