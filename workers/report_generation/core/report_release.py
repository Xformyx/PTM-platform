"""Reader Report release disposition.

The technical audit and a draft markdown file may be retained for diagnosis, but
the user-facing final artifact must be withheld if a shadow Report violates a
hard output-correctness contract.
"""

from __future__ import annotations

from typing import Any, Mapping


REPORT_RELEASE_CONTRACT_VERSION = "reader_report_release.v1"


def resolve_report_release(
    *,
    reader_authoring_shadow: bool,
    output_correctness: Mapping[str, Any] | None,
) -> dict[str, Any]:
    audit = dict(output_correctness or {})
    reasons = list(audit.get("reason_codes") or [])
    if reader_authoring_shadow and audit.get("status") == "blocked_for_review":
        return {
            "contract_version": REPORT_RELEASE_CONTRACT_VERSION,
            "status": "blocked_final",
            "final_artifact_withheld": True,
            "reason_codes": reasons or ["output_correctness_blocked"],
            "message": "Reader Report final artifact withheld pending output-correctness repair; technical audit remains available.",
        }
    if reader_authoring_shadow:
        return {
            "contract_version": REPORT_RELEASE_CONTRACT_VERSION,
            "status": "final_ready",
            "final_artifact_withheld": False,
            "reason_codes": [],
            "message": "Reader Report passed output-correctness release checks.",
        }
    return {
        "contract_version": REPORT_RELEASE_CONTRACT_VERSION,
        "status": "legacy_not_gated",
        "final_artifact_withheld": False,
        "reason_codes": [],
        "message": "Legacy Report path does not use the reader-authoring final release gate.",
    }
