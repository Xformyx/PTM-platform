"""Versioned manifest contract for offline PTM benchmark evaluation.

The manifest identifies an analysis contract and a locked truth bundle.  It is
loaded only by benchmark tooling after a blind analysis artifact is archived.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


MANIFEST_SCHEMA_VERSION = "ptm_locked_benchmark_manifest.v1"
TRUTH_SCHEMA_VERSION = "ptm_locked_truth_bundle.v1"


class BenchmarkManifestError(ValueError):
    """Raised when a benchmark manifest is incomplete or unsafe to execute."""


def sha256_file(path: str | Path) -> str:
    """Return a content hash without interpreting the file payload."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class BenchmarkManifest:
    """A validated, dataset-specific benchmark configuration."""

    path: Path
    raw: Mapping[str, Any]
    truth_path: Path

    @property
    def dataset_id(self) -> str:
        return str(self.raw["dataset_id"])

    @property
    def production_contract(self) -> Mapping[str, Any]:
        return dict(self.raw["production_contract"])

    @property
    def blind_policy(self) -> Mapping[str, Any]:
        return dict(self.raw["blind_policy"])

    @property
    def score_config(self) -> Mapping[str, Any]:
        return dict(self.raw["score_config"])

    @classmethod
    def load(cls, path: str | Path) -> "BenchmarkManifest":
        manifest_path = Path(path).resolve()
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise BenchmarkManifestError(f"manifest does not exist: {manifest_path}") from error
        except json.JSONDecodeError as error:
            raise BenchmarkManifestError(f"manifest is not valid JSON: {manifest_path}") from error
        if not isinstance(raw, dict):
            raise BenchmarkManifestError("manifest root must be an object")
        _validate_manifest(raw)
        truth_path = (manifest_path.parent / str(raw["locked_truth_bundle"])).resolve()
        if not truth_path.is_file():
            raise BenchmarkManifestError(f"locked truth bundle does not exist: {truth_path}")
        expected_hash = str(raw.get("locked_truth_sha256") or "")
        if expected_hash and sha256_file(truth_path) != expected_hash:
            raise BenchmarkManifestError("locked truth hash does not match the manifest")
        return cls(path=manifest_path, raw=raw, truth_path=truth_path)


def load_locked_truth_bundle(manifest: BenchmarkManifest) -> dict[str, Any]:
    """Load and validate the bundle only from the benchmark-side manifest."""

    try:
        truth = json.loads(manifest.truth_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise BenchmarkManifestError("locked truth bundle is not valid JSON") from error
    if not isinstance(truth, dict):
        raise BenchmarkManifestError("locked truth bundle root must be an object")
    if truth.get("schema_version") != TRUTH_SCHEMA_VERSION:
        raise BenchmarkManifestError(
            f"unsupported locked truth schema: {truth.get('schema_version')!r}"
        )
    anchors = truth.get("anchors")
    if not isinstance(anchors, list) or not anchors:
        raise BenchmarkManifestError("locked truth bundle must contain non-empty anchors")
    return truth


def _validate_manifest(raw: Mapping[str, Any]) -> None:
    if raw.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise BenchmarkManifestError(
            f"unsupported manifest schema: {raw.get('schema_version')!r}"
        )
    required_strings = ("dataset_id", "locked_truth_bundle", "locked_truth_sha256")
    missing = [name for name in required_strings if not str(raw.get(name) or "").strip()]
    if missing:
        raise BenchmarkManifestError(f"manifest is missing required values: {', '.join(missing)}")
    for section in ("production_contract", "blind_policy", "score_config"):
        if not isinstance(raw.get(section), Mapping):
            raise BenchmarkManifestError(f"manifest.{section} must be an object")
    contract = raw["production_contract"]
    if not str(contract.get("id") or "").strip():
        raise BenchmarkManifestError("production_contract.id is required")
    if contract.get("representation_learning_in_primary_score") is not False:
        raise BenchmarkManifestError(
            "primary benchmark must explicitly exclude additive representation learning"
        )
    policy = raw["blind_policy"]
    required_true = (
        "stimulus_hidden_from_analysis_runtime",
        "research_question_hidden_from_analysis_runtime",
        "truth_available_to_scorer_only",
    )
    not_locked = [name for name in required_true if policy.get(name) is not True]
    if not_locked:
        raise BenchmarkManifestError(
            "blind policy must explicitly enable: " + ", ".join(not_locked)
        )
    weights = raw["score_config"].get("component_weights")
    if not isinstance(weights, Mapping) or not weights:
        raise BenchmarkManifestError("score_config.component_weights must be a non-empty object")
