"""Reader Report release disposition.

The technical audit and a draft markdown file may be retained for diagnosis, but
the user-facing final artifact must be withheld if a shadow Report violates a
hard output-correctness contract.
"""

from __future__ import annotations

from typing import Any, Mapping


REPORT_RELEASE_CONTRACT_VERSION = "reader_report_release.v5"


def report_artifact_export_allowed(release: Mapping[str, Any] | None) -> bool:
    """Whether a rendered MD/HTML/DOCX may be retained as a review artifact."""
    state = dict(release or {})
    if "review_artifact_available" in state:
        return bool(state.get("review_artifact_available"))
    return not bool(state.get("final_artifact_withheld"))


def report_release_requires_warning(release: Mapping[str, Any] | None) -> bool:
    """Whether completion must be presented as completed with warnings."""
    return str(dict(release or {}).get("status") or "") in {
        "draft_review_required",
        "blocked_final",
        "blocked_for_review",
    }


def resolve_report_release(
    *, reader_authoring_shadow: bool, output_correctness: Mapping[str, Any] | None,
    artifact_manifest: Mapping[str, Any] | None = None, phase: str = "final",
) -> dict[str, Any]:
    """Combine independent gates; final readiness requires verified physical exports."""
    if phase not in {"pre_export", "final"}:
        raise ValueError("Unknown release phase")
    audit, manifest = dict(output_correctness or {}), dict(artifact_manifest or {})
    reasons = set(audit.get("reason_codes") or []) | set(audit.get("review_reason_codes") or [])
    reasons.update(manifest.get("reason_codes") or [])
    blocked = audit.get("status") == "blocked_for_review"
    if reader_authoring_shadow:
        if audit.get("status") not in {"release_candidate", "draft_review_required", "blocked_for_review"}:
            reasons.add("output_correctness_audit_unavailable_or_unrecognized")
        if audit.get("status") == "draft_review_required":
            reasons.add("output_correctness_review_required")
        if not manifest:
            reasons.add("same_run_artifact_manifest_missing")
        elif manifest.get("status") != "validated" or manifest.get("report_eligible") is not True:
            reasons.add("same_run_artifact_manifest_incompatible")
        if phase == "final":
            from .report_artifact_manifest import verify_rendered_artifacts
            verification = verify_rendered_artifacts(manifest)
            if not manifest.get("artifacts"):
                reasons.add("source_integrity_unavailable")
            if manifest.get("render_status") != "recorded":
                reasons.add("requested_exports_incomplete")
            if verification["status"] != "verified":
                reasons.add("rendered_artifact_integrity_" + verification["status"])
            if verification["status"] == "mismatch" or manifest.get("changed_source_artifacts"):
                blocked = True
        status = "blocked_final" if blocked else "draft_review_required" if reasons else "export_ready" if phase == "pre_export" else "final_ready"
    else:
        status, blocked = "legacy_not_gated", False
    return {
        "contract_version": REPORT_RELEASE_CONTRACT_VERSION, "phase": phase, "status": status,
        "final_artifact_withheld": blocked, "review_artifact_available": not blocked,
        "publish_as_final": status == "final_ready", "reason_codes": sorted(reasons),
        "message": {
            "blocked_final": "Report export withheld; structural or artifact integrity repair is required.",
            "draft_review_required": "Report requires review; final publication checks are incomplete.",
            "export_ready": "Source checks passed; requested exports still require verification.",
            "final_ready": "Report passed source, correctness and final export checks.",
            "legacy_not_gated": "Legacy path has no scientific final-publication approval.",
        }[status],
    }
