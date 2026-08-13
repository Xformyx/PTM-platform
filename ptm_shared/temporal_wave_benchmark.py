"""Benchmark harness for canonical Temporal Wave versus individual PTM-site scoring.

The harness never fabricates benchmark results.  It only runs datasets declared
in a manifest that points to a real, locally available perturbation time-series
file and declares the experimentally known target kinase(s).  Its output is a
versioned JSON/Markdown record that can be committed with a manuscript or
benchmark release.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from ptm_shared.temporal_wave_engine import (
    CONTRACT_VERSION,
    ENGINE_VERSION,
    analyze_temporal_waves,
    build_input_from_vector_rows,
)


BENCHMARK_VERSION = "temporal_wave_benchmark.v1"


class ManifestError(ValueError):
    """Raised when a benchmark manifest cannot support a valid real-data run."""


def _read_manifest(path: Path) -> Dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"Unable to read JSON manifest: {exc}") from exc
    required = ["schema_version", "dataset_id", "data_path", "known_targets", "input_columns"]
    missing = [key for key in required if not manifest.get(key)]
    if missing:
        raise ManifestError(f"Missing required manifest keys: {', '.join(missing)}")
    if manifest["schema_version"] != "temporal_wave_benchmark_manifest.v1":
        raise ManifestError("Unsupported manifest schema_version")
    return manifest


def _load_rows(manifest: Mapping[str, Any], manifest_path: Path) -> List[Dict[str, Any]]:
    data_path = Path(str(manifest["data_path"]))
    if not data_path.is_absolute():
        data_path = manifest_path.parent / data_path
    if not data_path.exists():
        raise ManifestError(
            f"Real benchmark data is not available at {data_path}. "
            "Download and preprocess the declared dataset before running the harness."
        )
    delimiter = "\t" if data_path.suffix.lower() == ".tsv" else ","
    with data_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter=delimiter))


def _candidate_kinases(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value).replace("|", ";").split(";") if part.strip()]


def _normalize_rows(rows: Iterable[Mapping[str, Any]], columns: Mapping[str, str]) -> List[Dict[str, Any]]:
    required = ["gene", "site", "timepoint", "log2fc", "candidate_kinases"]
    missing = [key for key in required if key not in columns]
    if missing:
        raise ManifestError(f"input_columns missing mappings: {', '.join(missing)}")
    normalized: List[Dict[str, Any]] = []
    for row in rows:
        gene = str(row.get(columns["gene"], "")).strip()
        timepoint = str(row.get(columns["timepoint"], "")).strip()
        if not gene or not timepoint:
            continue
        normalized.append(
            {
                "gene": gene,
                "position": str(row.get(columns["site"], "")).strip(),
                "condition": timepoint,
                "ptm_relative_log2fc": row.get(columns["log2fc"]),
                "candidate_kinases": _candidate_kinases(row.get(columns["candidate_kinases"])),
                "q_value": row.get(columns.get("q_value", "")) if columns.get("q_value") else None,
                "activity_class": row.get(columns.get("activity_class", "")) if columns.get("activity_class") else "minor",
            }
        )
    if not normalized:
        raise ManifestError("No usable PTM rows after manifest column mapping")
    return normalized


def _time_to_minutes(label: str) -> float:
    from ptm_shared.temporal_wave_engine import _time_minutes  # internal parser, shared contract
    return _time_minutes(label)


def _temporal_alignment(kinase: str, peak_timepoint: str, expected_windows: Mapping[str, Any]) -> float:
    """Score a declared target window only when the real-data manifest provides one."""
    window = expected_windows.get(kinase)
    if not isinstance(window, Mapping):
        return 1.0
    minimum = float(window.get("min_minutes", float("-inf")))
    maximum = float(window.get("max_minutes", float("inf")))
    return 1.0 if minimum <= _time_to_minutes(peak_timepoint) <= maximum else 0.0


def _rank(scores: Mapping[str, float], target: str) -> int | None:
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    for index, (kinase, _) in enumerate(ordered, start=1):
        if kinase == target:
            return index
    return None


def _scores_from_rows(rows: Sequence[Mapping[str, Any]], expected_windows: Mapping[str, Any]) -> Dict[str, float]:
    scores: Dict[str, float] = defaultdict(float)
    by_site: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        by_site[f"{row['gene']} {row['position']}".strip()].append(row)
    for site_rows in by_site.values():
        peak_row = max(site_rows, key=lambda row: abs(float(row["ptm_relative_log2fc"] or 0.0)))
        amplitude = abs(float(peak_row["ptm_relative_log2fc"] or 0.0))
        for kinase in peak_row["candidate_kinases"]:
            scores[kinase] += amplitude * _temporal_alignment(kinase, peak_row["condition"], expected_windows)
    return dict(scores)


def _scores_from_waves(contract: Mapping[str, Any], expected_windows: Mapping[str, Any]) -> Dict[str, float]:
    scores: Dict[str, float] = defaultdict(float)
    for wave in contract.get("waves", []):
        profile = wave.get("evidence_profile", {})
        structural_weight = float(profile.get("temporal_coherence", 0.0)) * float(
            profile.get("median_member_amplitude", 0.0)
        )
        for member in wave.get("member_details", []):
            for kinase in member.get("candidate_kinases", []):
                scores[kinase] += structural_weight * _temporal_alignment(
                    kinase, wave["peak_timepoint"], expected_windows
                )
    return dict(scores)


def _target_metrics(scores: Mapping[str, float], known_targets: Sequence[str]) -> Dict[str, Any]:
    ranks = {target: _rank(scores, target) for target in known_targets}
    available = [rank for rank in ranks.values() if rank is not None]
    return {
        "target_ranks": ranks,
        "top1_recovery": sum(rank == 1 for rank in available) / len(known_targets) if known_targets else None,
        "top3_recovery": sum(rank is not None and rank <= 3 for rank in ranks.values()) / len(known_targets)
        if known_targets else None,
        "mean_reciprocal_rank": sum(1.0 / rank for rank in available) / len(known_targets) if known_targets else None,
        "candidate_kinases_scored": len(scores),
    }


def _permuted_rows(rows: Sequence[Mapping[str, Any]], seed: int) -> List[Dict[str, Any]]:
    """Permute time labels within site, preserving measured values and candidate labels."""
    generator = random.Random(seed)
    grouped: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[f"{row['gene']} {row['position']}".strip()].append(row)
    permuted: List[Dict[str, Any]] = []
    for site_rows in grouped.values():
        labels = [str(row["condition"]) for row in site_rows]
        generator.shuffle(labels)
        for row, label in zip(site_rows, labels):
            copied = dict(row)
            copied["condition"] = label
            permuted.append(copied)
    return permuted


def _run_method(rows: Sequence[Mapping[str, Any]], wave_config: Mapping[str, Any], expected_windows: Mapping[str, Any]) -> Dict[str, Any]:
    series, timepoints, metadata = build_input_from_vector_rows(rows)
    contract = analyze_temporal_waves(series, timepoints, metadata=metadata, config=wave_config)
    return {
        "contract": contract,
        "site_scores": _scores_from_rows(rows, expected_windows),
        "wave_scores": _scores_from_waves(contract, expected_windows),
    }


def run_benchmark(manifest_path: str | Path, output_dir: str | Path) -> Dict[str, Any]:
    """Execute a single real-data manifest and write reproducible benchmark artifacts."""
    source_path = Path(manifest_path).resolve()
    manifest = _read_manifest(source_path)
    rows = _normalize_rows(_load_rows(manifest, source_path), manifest["input_columns"])
    known_targets = [str(target) for target in manifest["known_targets"]]
    expected_windows = manifest.get("expected_target_windows", {})
    base_config = dict(manifest.get("wave_config") or {})
    observed = _run_method(rows, base_config, expected_windows)
    result: Dict[str, Any] = {
        "benchmark_version": BENCHMARK_VERSION,
        "contract_version": CONTRACT_VERSION,
        "engine_version": ENGINE_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": {
            "dataset_id": manifest["dataset_id"],
            "source_url": manifest.get("source_url"),
            "source_doi": manifest.get("source_doi"),
            "known_targets": known_targets,
            "timepoint_count": len(observed["contract"].get("timepoints", [])),
            "input_rows": len(rows),
        },
        "observed": {
            "site": _target_metrics(observed["site_scores"], known_targets),
            "wave": _target_metrics(observed["wave_scores"], known_targets),
            "wave_contract_summary": observed["contract"].get("summary", {}),
            "threshold_provenance": observed["contract"].get("threshold_provenance", {}),
        },
        "time_permutation": {},
        "threshold_sensitivity": [],
        "interpretation_boundary": (
            "Benchmark output compares declared known targets only. It does not establish causality, "
            "clinical utility, or universal kinase-inference performance."
        ),
    }
    repetitions = int(manifest.get("time_permutation", {}).get("repetitions", 100))
    seed = int(manifest.get("time_permutation", {}).get("seed", 20260813))
    if expected_windows:
        permutation_metrics = []
        for repetition in range(max(1, repetitions)):
            permuted = _run_method(_permuted_rows(rows, seed + repetition), base_config, expected_windows)
            permutation_metrics.append(_target_metrics(permuted["wave_scores"], known_targets))
        observed_mrr = result["observed"]["wave"]["mean_reciprocal_rank"]
        null_mrr = [metric["mean_reciprocal_rank"] for metric in permutation_metrics if metric["mean_reciprocal_rank"] is not None]
        result["time_permutation"] = {
            "evaluable": True,
            "repetitions": len(permutation_metrics),
            "seed": seed,
            "observed_wave_mrr": observed_mrr,
            "null_wave_mrr_mean": sum(null_mrr) / len(null_mrr) if null_mrr else None,
            "null_wave_mrr_values": null_mrr,
            "empirical_one_sided_p": (
                (1 + sum(value >= observed_mrr for value in null_mrr)) / (1 + len(null_mrr))
                if observed_mrr is not None and null_mrr else None
            ),
        }
    else:
        result["time_permutation"] = {
            "evaluable": False,
            "reason": "expected_target_windows_required_for_temporal_target_permutation_test",
        }
    for threshold in manifest.get("threshold_sensitivity", {}).get("correlation_thresholds", [0.60, 0.70, 0.80]):
        configured = dict(base_config)
        configured["correlation_threshold"] = float(threshold)
        configured["threshold_source"] = "benchmark_threshold_sensitivity"
        run = _run_method(rows, configured, expected_windows)
        result["threshold_sensitivity"].append(
            {
                "correlation_threshold": float(threshold),
                "wave": _target_metrics(run["wave_scores"], known_targets),
                "wave_contract_summary": run["contract"].get("summary", {}),
                "config_sha256": run["contract"].get("threshold_provenance", {}).get("config_sha256"),
            }
        )
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    json_path = destination / f"{manifest['dataset_id']}_temporal_wave_benchmark.json"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path = destination / f"{manifest['dataset_id']}_temporal_wave_benchmark.md"
    markdown_path.write_text(_render_markdown(result), encoding="utf-8")
    result["artifacts"] = {"json": str(json_path), "markdown": str(markdown_path)}
    return result


def _render_markdown(result: Mapping[str, Any]) -> str:
    dataset = result["dataset"]
    observed = result["observed"]
    lines = [
        f"# Temporal Wave Benchmark: {dataset['dataset_id']}",
        "",
        f"- Contract: `{result['contract_version']}`",
        f"- Engine: `{result['engine_version']}`",
        f"- Known targets: {', '.join(dataset['known_targets'])}",
        "",
        "| Method | Top-1 recovery | Top-3 recovery | MRR | Candidate kinases |",
        "|---|---:|---:|---:|---:|",
        f"| Individual site | {observed['site']['top1_recovery']} | {observed['site']['top3_recovery']} | {observed['site']['mean_reciprocal_rank']} | {observed['site']['candidate_kinases_scored']} |",
        f"| Canonical wave | {observed['wave']['top1_recovery']} | {observed['wave']['top3_recovery']} | {observed['wave']['mean_reciprocal_rank']} | {observed['wave']['candidate_kinases_scored']} |",
        "",
        "## Time permutation",
        "",
        f"```json\n{json.dumps(result['time_permutation'], ensure_ascii=False, indent=2)}\n```",
        "",
        "## Threshold sensitivity",
        "",
        "| Correlation threshold | Waves | Wave MRR | Top-3 recovery |",
        "|---:|---:|---:|---:|",
    ]
    for run in result["threshold_sensitivity"]:
        summary = run["wave_contract_summary"]
        metrics = run["wave"]
        lines.append(
            f"| {run['correlation_threshold']:.2f} | {summary.get('num_waves')} | "
            f"{metrics.get('mean_reciprocal_rank')} | {metrics.get('top3_recovery')} |"
        )
    lines.extend(["", "## Interpretation boundary", "", result["interpretation_boundary"], ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a real-data Temporal Wave benchmark manifest")
    parser.add_argument("--manifest", required=True, help="Path to a benchmark manifest JSON file")
    parser.add_argument("--output-dir", required=True, help="Directory for JSON and Markdown benchmark artifacts")
    arguments = parser.parse_args()
    result = run_benchmark(arguments.manifest, arguments.output_dir)
    print(json.dumps({"dataset_id": result["dataset"]["dataset_id"], "artifacts": result["artifacts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
