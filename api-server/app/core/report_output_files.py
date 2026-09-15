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


def merge_result_files_with_disk(result_files: dict | None, output_dir: Path) -> dict:
    """Keep historical report files visible even if the last run registered only the latest."""
    merged = dict(result_files or {})
    on_disk = list_report_output_files(output_dir)
    reports = sorted({*(merged.get("report_files") or []), *on_disk})
    reports = [name for name in reports if (output_dir / name).is_file()]
    all_files = sorted({*(merged.get("all_files") or []), *reports})
    merged["report_files"] = reports
    merged["all_files"] = all_files
    return merged
