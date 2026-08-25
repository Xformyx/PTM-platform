"""Truth-free context construction for Order-integrated strict benchmarks.

This service deliberately has no import path to ``benchmarking`` or any locked
reference.  It converts an existing Order only into neutral run metadata; a
later offline scorer receives the locked truth after analysis is archived.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping


LINEAGE_CLASSES = (
    "fibroblast_like",
    "epithelial_like",
    "immune_like",
    "muscle_like",
    "neuronal_like",
    "other_cultured_cells",
)


def manifest_path_for(dataset_id: str, public_manifest_root: Path) -> Path:
    """Resolve the API-visible contract without opening scorer-only truth files."""

    if not dataset_id.replace("_", "").replace("-", "").isalnum():
        raise ValueError("dataset_id may contain only letters, digits, hyphens, and underscores")
    path = public_manifest_root / f"{dataset_id}.manifest.json"
    if not path.is_file():
        raise ValueError(f"benchmark manifest is not available: {dataset_id}")
    return path


def public_manifest_root() -> Path:
    configured = os.getenv("BENCHMARK_PUBLIC_MANIFEST_DIR")
    if configured:
        return Path(configured).resolve()
    return Path(__file__).resolve().parents[1] / "benchmark_manifests"


def load_public_manifest(dataset_id: str, manifest_root: Path | None = None) -> dict[str, Any]:
    path = manifest_path_for(dataset_id, manifest_root or public_manifest_root())
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("dataset_id") != dataset_id:
        raise ValueError("benchmark manifest dataset_id does not match its path")
    if raw.get("visibility") != "api_preflight_contract_only":
        raise ValueError("benchmark manifest is not an API-visible preflight contract")
    forbidden = {"locked_truth_bundle", "locked_truth_sha256", "score_config", "source_reference"}
    if forbidden.intersection(raw):
        raise ValueError("API-visible benchmark manifest may not contain locked scoring metadata")
    if raw.get("blind_policy", {}).get("rag_policy") != "disabled_for_strict_primary":
        raise ValueError("strict primary benchmark requires disabled RAG")
    if raw.get("production_contract", {}).get("representation_learning_in_primary_score") is not False:
        raise ValueError("strict primary benchmark cannot include representation learning")
    raw["manifest_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return raw


def build_blind_context(*, lineage_class: str, manifest: Mapping[str, Any]) -> dict[str, Any]:
    if lineage_class not in LINEAGE_CLASSES:
        raise ValueError("lineage_class must be selected from the controlled benchmark vocabulary")
    return {
        "schema_version": "blind_context.v1",
        "mode": "strict_primary",
        "treatment_label": "Treatment A",
        "control_label": "Control",
        "research_questions": [],
        "special_conditions": [],
        "rag_policy": "disabled",
        "co_scientist_policy": "disabled",
        "report_generation": "disabled",
        "cell_context": {
            "policy": "lineage_only",
            "lineage_class": lineage_class,
            "source_cell_line_hidden": True,
            "transgene_hidden": True,
            "disease_model_hidden": True,
        },
        "production_contract_id": manifest["production_contract"]["id"],
    }


def source_snapshot(order: Any, *, manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Record immutable non-biological provenance without copying free text."""

    sample_config = order.sample_config or {}
    samples = sample_config.get("samples", sample_config) if isinstance(sample_config, dict) else sample_config
    sample_count = len(samples) if isinstance(samples, list) else 0
    return {
        "schema_version": "benchmark_source_snapshot.v1",
        "source_order_id": order.id,
        "source_order_code_sha256": hashlib.sha256(order.order_code.encode("utf-8")).hexdigest(),
        "ptm_type": order.ptm_type,
        "analysis_species": order.species,
        "sample_count": sample_count,
        "timepoint_count": _count_timepoints(samples),
        "manifest_sha256": manifest["manifest_sha256"],
        "source_paths_sha256": _stable_hash(
            {"pr": order.pr_matrix_path, "pg": order.pg_matrix_path, "fasta": order.fasta_path}
        ),
    }


def validate_benchmark_eligibility(order: Any, *, manifest: Mapping[str, Any]) -> list[str]:
    issues: list[str] = []
    snapshot = source_snapshot(order, manifest=manifest)
    if order.ptm_type != "phosphorylation":
        issues.append("strict insulin benchmark currently requires phosphorylation data")
    if snapshot["timepoint_count"] < 3:
        issues.append("strict temporal benchmark requires at least three non-control timepoints")
    if not order.pr_matrix_path or not order.pg_matrix_path or not order.fasta_path:
        issues.append("PR matrix, PG matrix, and FASTA are required for a reproducible benchmark snapshot")
    return issues


def _count_timepoints(samples: Any) -> int:
    if not isinstance(samples, list):
        return 0
    labels = set()
    for row in samples:
        if not isinstance(row, Mapping):
            continue
        group = str(row.get("group") or row.get("Group") or "").strip().lower()
        condition = str(row.get("condition") or row.get("Condition") or "").strip()
        if condition and group != "control":
            labels.add(condition)
    return len(labels)


def _stable_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
