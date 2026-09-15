"""List on-disk report revisions for the Order Results tab."""

from __future__ import annotations

from pathlib import Path

REPORT_SUFFIXES = {".md", ".html", ".docx"}


def is_report_output_name(name: str) -> bool:
    lower = name.lower()
    suffix = Path(name).suffix.lower()
    if suffix not in REPORT_SUFFIXES:
        return False
    return "_report_" in lower or lower.startswith("comprehensive_report")


def list_report_output_files(output_dir: Path) -> list[str]:
    if not output_dir.is_dir():
        return []
    return sorted(
        path.name
        for path in output_dir.iterdir()
        if path.is_file() and is_report_output_name(path.name)
    )


def merge_result_files_with_disk(
    result_files: dict | None,
    output_dir: Path,
    *,
    report_options: dict | None = None,
) -> dict:
    """Return only files explicitly registered by the current artifact contract.

    Directory discovery is intentionally excluded from `report_files`: a stale
    technical-audit DOCX has the same extension/name pattern as a researcher
    manuscript and must not reappear as the active Report after a failed run.
    Explicit technical requests are exposed in a separate typed field.
    """
    from ptm_shared.report_mode import resolve_report_mode_contract

    merged = dict(result_files or {})
    config = dict((report_options or {}).get("report_config") or {})
    contract = dict(resolve_report_mode_contract(config))
    audience = str(contract.get("report_audience") or "").strip().lower()
    registered = sorted({str(name) for name in (merged.get("report_files") or []) if (output_dir / str(name)).is_file()})
    technical = sorted({str(name) for name in (merged.get("technical_audit_files") or []) if (output_dir / str(name)).is_file()})
    release = dict(merged.get("report_release") or {})
    release_audience = str(release.get("report_audience") or "").strip().lower()

    # The UI must never infer artifact kind from extension/name. With an absent
    # or inconsistent contract, retain only non-report diagnostics and expose a
    # typed blocked status. This prevents old technical reports from filling a
    # researcher Results slot after a failed/retried request.
    if not contract.get("valid"):
        registered, technical = [], []
        merged["report_files"] = []
        merged["current_report_files"] = []
        merged["technical_audit_files"] = []
        merged["report_file_visibility"] = {
            "status": "blocked_report_mode_contract",
            "reason_codes": list(contract.get("reason_codes") or []),
        }
    elif audience == "technical_audit":
        technical = sorted(set(technical) | set(registered))
        registered = []
        merged["report_file_visibility"] = {"status": "technical_audit_only", "reason_codes": []}
    elif release_audience and release_audience != "researcher_manuscript":
        # A stored technical release cannot be relabelled as researcher output
        # merely because a later request has researcher options.
        technical = sorted(set(technical) | set(registered))
        registered = []
        merged["current_report_files"] = []
        merged["report_file_visibility"] = {
            "status": "blocked_stale_artifact_audience_mismatch",
            "reason_codes": ["stored_release_audience_mismatch"],
        }
    else:
        merged["report_file_visibility"] = {"status": "researcher_artifacts_available", "reason_codes": []}
    all_files = {
        str(name) for name in (merged.get("all_files") or [])
        if not is_report_output_name(str(name))
    }
    all_files.update(registered)
    merged["report_files"] = registered
    merged["technical_audit_files"] = technical
    merged["all_files"] = sorted(all_files)
    return merged
