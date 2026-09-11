"""Reader Report release disposition.

The technical audit and a draft markdown file may be retained for diagnosis, but
the user-facing final artifact must be withheld if a shadow Report violates a
hard output-correctness contract.
"""

from __future__ import annotations

from typing import Any, Mapping


REPORT_RELEASE_CONTRACT_VERSION = "reader_report_release.v4"


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
    *,
    reader_authoring_shadow: bool,
    output_correctness: Mapping[str, Any] | None,
    artifact_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    audit = dict(output_correctness or {})
    reasons = list(audit.get("reason_codes") or [])
    manifest = dict(artifact_manifest or {})
    if reader_authoring_shadow and manifest and manifest.get("status") != "validated":
        return {
            "contract_version": REPORT_RELEASE_CONTRACT_VERSION,
            "status": "draft_review_required",
            "final_artifact_withheld": False,
            "review_artifact_available": True,
            "publish_as_final": False,
            "reason_codes": list(manifest.get("reason_codes") or ["same_run_artifact_manifest_incompatible"]),
            "message": "Reader Report review artifacts are available, but final publication approval is blocked because the required same-run evidence bundle is incomplete or provenance-incompatible.",
        }
    if reader_authoring_shadow and not manifest:
        return {
            "contract_version": REPORT_RELEASE_CONTRACT_VERSION,
            "status": "draft_review_required",
            "final_artifact_withheld": False,
            "review_artifact_available": True,
            "publish_as_final": False,
            "reason_codes": ["same_run_artifact_manifest_missing"],
            "message": "Reader Report review artifacts are available, but final publication approval is blocked because the required same-run evidence manifest was not produced.",
        }
    if reader_authoring_shadow and audit.get("status") == "blocked_for_review":
        return {
            "contract_version": REPORT_RELEASE_CONTRACT_VERSION,
            "status": "blocked_final",
            "final_artifact_withheld": True,
            "review_artifact_available": False,
            "publish_as_final": False,
            "reason_codes": reasons or ["output_correctness_blocked"],
            "message": "Reader Report final artifact withheld pending output-correctness repair; technical audit remains available.",
        }
    if reader_authoring_shadow and audit.get("status") == "draft_review_required":
        return {
            "contract_version": REPORT_RELEASE_CONTRACT_VERSION,
            "status": "draft_review_required",
            "final_artifact_withheld": False,
            "review_artifact_available": True,
            "publish_as_final": False,
            "reason_codes": list(audit.get("review_reason_codes") or reasons or ["review_required"]),
            "message": "Reader Report generated as a review draft; it must not be labelled or published as final.",
        }
    if reader_authoring_shadow:
        return {
            "contract_version": REPORT_RELEASE_CONTRACT_VERSION,
            "status": "final_ready",
            "final_artifact_withheld": False,
            "review_artifact_available": True,
            "publish_as_final": True,
            "reason_codes": [],
            "message": "Reader Report passed output-correctness release checks.",
        }
    return {
        "contract_version": REPORT_RELEASE_CONTRACT_VERSION,
        "status": "legacy_not_gated",
        "final_artifact_withheld": False,
        "review_artifact_available": True,
        "publish_as_final": False,
        "reason_codes": [],
        "message": "Legacy Report path does not use the reader-authoring final release gate.",
    }
