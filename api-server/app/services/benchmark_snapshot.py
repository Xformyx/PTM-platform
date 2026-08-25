"""Create an immutable, context-sanitized child Order for a strict benchmark.

The input matrices are copied with alias-only sample headers before any worker
reads them.  The source Order, cell-line name, transgene, treatment name, and
research question therefore never enter the child analysis runtime.
"""

from __future__ import annotations

import csv
import hashlib
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class SnapshotPaths:
    pr_matrix_path: str
    pg_matrix_path: str
    fasta_path: str
    sample_config: dict[str, Any]
    condition_map: dict[str, str]
    input_sha256: dict[str, str]


def create_sanitized_snapshot(
    *,
    source_order: Any,
    blind_context: Mapping[str, Any],
    destination_dir: Path,
) -> SnapshotPaths:
    """Copy source files and rewrite only matrix headers with neutral aliases."""

    destination_dir.mkdir(parents=True, exist_ok=False)
    samples = _samples(source_order.sample_config)
    if not samples:
        raise ValueError("source Order has no sample configuration")

    aliases: dict[str, str] = {}
    neutral_samples: list[dict[str, Any]] = []
    for index, sample in enumerate(samples, start=1):
        original = str(sample.get("file_name") or sample.get("File_Name") or "").strip()
        if not original:
            raise ValueError("source sample configuration contains an empty file name")
        alias = f"S{index:03d}"
        aliases[original] = alias
        group = str(sample.get("group") or sample.get("Group") or "").strip().lower()
        raw_condition = str(sample.get("condition") or sample.get("Condition") or "").strip()
        is_control = group == "control" or raw_condition.lower() == "control"
        condition = "Control" if is_control else _safe_time_label(raw_condition, index)
        neutral_samples.append(
            {
                "file_name": alias,
                "group": "control" if is_control else "treated",
                "condition": condition,
                "replicate": sample.get("replicate") or sample.get("Replicate"),
            }
        )

    pr_target = destination_dir / "ptm_precursor_matrix.tsv"
    pg_target = destination_dir / "protein_group_matrix.tsv"
    fasta_target = destination_dir / "reference.fasta"
    _copy_with_header_aliases(Path(source_order.pr_matrix_path), pr_target, aliases)
    _copy_with_header_aliases(Path(source_order.pg_matrix_path), pg_target, aliases)
    shutil.copy2(source_order.fasta_path, fasta_target)

    return SnapshotPaths(
        pr_matrix_path=str(pr_target),
        pg_matrix_path=str(pg_target),
        fasta_path=str(fasta_target),
        sample_config={"samples": neutral_samples, "single_time_point": False},
        condition_map={sample["file_name"]: sample["condition"] for sample in neutral_samples},
        input_sha256={
            "pr_matrix": _sha256(pr_target),
            "pg_matrix": _sha256(pg_target),
            "fasta": _sha256(fasta_target),
        },
    )


def _samples(sample_config: Any) -> list[Mapping[str, Any]]:
    if isinstance(sample_config, dict):
        rows = sample_config.get("samples", [])
    else:
        rows = sample_config or []
    return [row for row in rows if isinstance(row, Mapping)]


def _safe_time_label(raw: str, fallback_index: int) -> str:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(sec|s|min|m|hr|h|hour|d|day)s?", raw, re.I)
    if not match:
        return f"T{fallback_index:03d}"
    number, unit = match.groups()
    normal = {"sec": "sec", "s": "sec", "min": "min", "m": "min", "hr": "hr", "h": "hr", "hour": "hr", "d": "day", "day": "day"}
    return f"{number}{normal[unit.lower()]}"


def _copy_with_header_aliases(source: Path, destination: Path, aliases: Mapping[str, str]) -> None:
    if not source.is_file():
        raise ValueError(f"required source input is missing: {source.name}")
    delimiter = "\t" if source.suffix.lower() in {".tsv", ".txt"} else ","
    with source.open("r", encoding="utf-8-sig", newline="") as in_handle, destination.open("w", encoding="utf-8", newline="") as out_handle:
        reader = csv.reader(in_handle, delimiter=delimiter)
        writer = csv.writer(out_handle, delimiter=delimiter)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ValueError(f"source input is empty: {source.name}") from exc
        writer.writerow([aliases.get(value, value) for value in header])
        writer.writerows(reader)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
