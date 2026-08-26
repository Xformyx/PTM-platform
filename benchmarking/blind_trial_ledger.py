"""Append-only, truth-free optimization ledger for strict blind benchmarks.

The ledger accepts only hashed inputs, neutral phase names, versioned variables,
truth-free objectives, fold metrics, and selection decisions.  It rejects
stimulus, workbook, anchor, treatment, biological-question, and locked-truth
content recursively before anything is written.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "strict_blind_optimization_trial.v1"
REGISTRY_VERSION = "strict_blind_temporal_variables.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_KEY_FRAGMENTS = {
    "anchor",
    "biological_question",
    "locked_truth",
    "reference_workbook",
    "stimulus",
    "treatment",
    "truth",
    "workbook",
}
_FORBIDDEN_VALUE_FRAGMENTS = {
    "insulin",
    "locked truth",
    "reference workbook",
}
_BOUNDARY_ATTESTATION_KEY = "truth_used_for_selection"


class BlindTrialLedgerError(ValueError):
    """Raised when blind-boundary or hash-chain validation fails."""


VARIABLE_REGISTRY: dict[str, dict[str, Any]] = {
    "site_aggregation": {"type": "enum", "values": ["mean", "median"], "default": "median"},
    "wave.correlation_threshold": {"type": "float", "minimum": 0.50, "maximum": 0.90, "default": 0.70},
    "wave.minimum_variance": {"type": "float", "minimum": 0.05, "maximum": 0.60, "default": 0.30},
    "wave.minimum_amplitude": {"type": "float", "minimum": 0.20, "maximum": 1.50, "default": 0.40},
    "wave.minimum_cluster_size": {"type": "int", "minimum": 2, "maximum": 8, "default": 2},
    "wave.maximum_waves": {"type": "int", "minimum": 4, "maximum": 16, "default": 8},
    "wave.bootstrap_repeats": {"type": "int", "minimum": 0, "maximum": 500, "default": 100},
    "wave.soft_membership_threshold": {"type": "float", "minimum": 0.50, "maximum": 0.95, "default": 0.70},
    "candidate.max_per_site": {"type": "int", "minimum": 1, "maximum": 20, "default": 10},
    "candidate.quantile_threshold": {"type": "float", "minimum": 0.50, "maximum": 0.9999, "default": 0.90},
    "candidate.family_resolution": {"type": "enum", "values": ["family_first", "gene_first", "hierarchical"], "default": "hierarchical"},
    "candidate.prior_strength": {"type": "float", "minimum": 0.0, "maximum": 20.0, "default": 0.0},
    "activity.effect_size": {"type": "enum", "values": ["weighted_sum", "weighted_mean", "shrunken_mean"], "default": "shrunken_mean"},
    "activity.shrinkage_prior_support": {"type": "float", "minimum": 0.0, "maximum": 100.0, "default": 5.0},
    "tmm.profile_min_exclusive": {"type": "int", "minimum": 2, "maximum": 12, "default": 5},
    "tmm.gaussian_sigma_log": {"type": "float", "minimum": 0.20, "maximum": 1.50, "default": 0.80},
    "tmm.target_transform": {"type": "enum", "values": ["signed", "magnitude"], "default": "magnitude"},
    "tmm.iterative_profile_rounds": {"type": "int", "minimum": 0, "maximum": 20, "default": 0},
    "tmm.iterative_min_top1_probability": {"type": "float", "minimum": 0.50, "maximum": 0.99, "default": 0.80},
    "tmm.iterative_min_shared_support": {"type": "int", "minimum": 1, "maximum": 20, "default": 3},
    "tmm.iterative_profile_blend": {"type": "float", "minimum": 0.10, "maximum": 1.0, "default": 0.50},
    "dual_track.correlation_threshold": {"type": "float", "minimum": 0.0, "maximum": 0.95, "default": 0.50},
    "dual_track.peak_index_tolerance": {"type": "int", "minimum": 0, "maximum": 3, "default": 1},
    "dual_track.magnitude_log2_ratio_threshold": {"type": "float", "minimum": 0.25, "maximum": 3.0, "default": 1.0},
    "uncertainty.bootstrap_repeats": {"type": "int", "minimum": 0, "maximum": 2000, "default": 100},
    "uncertainty.loto_enabled": {"type": "bool", "default": True},
    "directionality.minimum_data_anchored_endpoints": {"type": "int", "minimum": 0, "maximum": 2, "default": 1},
    "cross_layer.minimum_absolute_change": {"type": "float", "minimum": 0.10, "maximum": 1.50, "default": 0.40},
    "cross_layer.minimum_lag_aware_similarity": {"type": "float", "minimum": 0.0, "maximum": 0.95, "default": 0.40},
    "cross_layer.minimum_loto_stability": {"type": "float", "minimum": 0.0, "maximum": 1.0, "default": 0.60},
}


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _validate_truth_free(value: Any, path: str = "record") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).strip().lower()
            if normalized != _BOUNDARY_ATTESTATION_KEY and any(
                fragment in normalized for fragment in _FORBIDDEN_KEY_FRAGMENTS
            ):
                raise BlindTrialLedgerError(f"forbidden blind-ledger key at {path}.{key}")
            if normalized == _BOUNDARY_ATTESTATION_KEY and nested is not False:
                raise BlindTrialLedgerError("truth-use attestation must remain false")
            _validate_truth_free(nested, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, nested in enumerate(value):
            _validate_truth_free(nested, f"{path}[{index}]")
    elif isinstance(value, str):
        lowered = value.lower()
        if any(fragment in lowered for fragment in _FORBIDDEN_VALUE_FRAGMENTS):
            raise BlindTrialLedgerError(f"forbidden blind-ledger value at {path}")


def _validate_input_hashes(input_hashes: Mapping[str, str]) -> None:
    if not input_hashes:
        raise BlindTrialLedgerError("input_hashes must not be empty")
    for neutral_name, digest in input_hashes.items():
        if not re.fullmatch(r"[a-z][a-z0-9_]*", str(neutral_name)):
            raise BlindTrialLedgerError(f"input hash name must be neutral snake_case: {neutral_name}")
        if not _SHA256.fullmatch(str(digest)):
            raise BlindTrialLedgerError(f"invalid SHA-256 for {neutral_name}")


def validate_variable_config(config: Mapping[str, Any]) -> None:
    for name, value in config.items():
        spec = VARIABLE_REGISTRY.get(str(name))
        if spec is None:
            raise BlindTrialLedgerError(f"unregistered optimization variable: {name}")
        kind = spec["type"]
        if kind == "enum" and value not in spec["values"]:
            raise BlindTrialLedgerError(f"{name} must be one of {spec['values']}")
        if kind == "bool" and not isinstance(value, bool):
            raise BlindTrialLedgerError(f"{name} must be boolean")
        if kind in {"int", "float"}:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise BlindTrialLedgerError(f"{name} must be numeric")
            if kind == "int" and int(value) != value:
                raise BlindTrialLedgerError(f"{name} must be an integer")
            if value < spec["minimum"] or value > spec["maximum"]:
                raise BlindTrialLedgerError(f"{name} is outside the registered range")


def _load_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise BlindTrialLedgerError(f"invalid ledger JSON at line {line_number}") from exc
    return records


def verify_ledger(path: str | Path) -> list[dict[str, Any]]:
    records = _load_records(Path(path))
    previous = None
    for index, record in enumerate(records):
        digest = record.get("record_sha256")
        unsigned = {key: value for key, value in record.items() if key != "record_sha256"}
        if digest != canonical_sha256(unsigned):
            raise BlindTrialLedgerError(f"record hash mismatch at index {index}")
        if record.get("previous_record_sha256") != previous:
            raise BlindTrialLedgerError(f"hash-chain mismatch at index {index}")
        _validate_truth_free(record)
        previous = digest
    return records


def append_trial(
    path: str | Path,
    *,
    trial_id: str,
    phase: str,
    code_commit: str,
    input_hashes: Mapping[str, str],
    variable_config: Mapping[str, Any],
    objective: Mapping[str, Any],
    fold_metrics: Sequence[Mapping[str, Any]],
    decision: str,
    decision_reason: str,
    parent_config_sha256: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    ledger_path = Path(path)
    existing = verify_ledger(ledger_path)
    _validate_input_hashes(input_hashes)
    validate_variable_config(variable_config)
    if decision not in {"continue", "reject", "select", "freeze"}:
        raise BlindTrialLedgerError("unsupported decision")
    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "registry_version": REGISTRY_VERSION,
        "trial_id": str(trial_id),
        "phase": str(phase),
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "code_commit": str(code_commit),
        "input_hashes": dict(sorted(input_hashes.items())),
        "variable_config": dict(sorted(variable_config.items())),
        "config_sha256": canonical_sha256(dict(sorted(variable_config.items()))),
        "parent_config_sha256": parent_config_sha256,
        "objective": dict(objective),
        "fold_metrics": [dict(row) for row in fold_metrics],
        "decision": decision,
        "decision_reason": str(decision_reason),
        "truth_used_for_selection": False,
        "previous_record_sha256": existing[-1]["record_sha256"] if existing else None,
    }
    _validate_truth_free(record)
    record["record_sha256"] = canonical_sha256(record)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    verify_ledger(ledger_path)
    return record


def registry_document() -> dict[str, Any]:
    return {
        "schema_version": REGISTRY_VERSION,
        "variables": VARIABLE_REGISTRY,
        "registry_sha256": canonical_sha256(VARIABLE_REGISTRY),
    }
