"""List on-disk report revisions when persisting Order result_files."""

from __future__ import annotations

from pathlib import Path

REPORT_SUFFIXES = {".md", ".html", ".docx"}


def list_report_output_files(output_dir: Path) -> list[str]:
    if not output_dir.is_dir():
        return []
    names = []
    for path in output_dir.iterdir():
        if not path.is_file():
            continue
        lower = path.name.lower()
        if path.suffix.lower() not in REPORT_SUFFIXES:
            continue
        if "_report_" in lower or lower.startswith("comprehensive_report"):
            names.append(path.name)
    return sorted(names)
