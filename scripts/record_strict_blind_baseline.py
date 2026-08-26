#!/usr/bin/env python3
"""Record a truth-free temporal benchmark baseline in the blind trial ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from benchmarking.blind_trial_ledger import append_trial
from ptm_shared.temporal_optimization_config import provenance as temporal_config_provenance


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def current_commit(repo: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()


def _profile_type(row: dict[str, Any]) -> str:
    return str(row.get("tmm_profile_type") or row.get("profile_type") or "unavailable")


def _candidate_count_distribution(matrix: dict[str, Any]) -> dict[str, int]:
    counts = Counter()
    for key, candidates in matrix.items():
        if " " in key:
            continue
        size = len(candidates) if isinstance(candidates, dict) else 0
        if size <= 1:
            bucket = "1"
        elif size <= 3:
            bucket = "2_3"
        elif size <= 6:
            bucket = "4_6"
        else:
            bucket = "7_plus"
        counts[bucket] += 1
    return dict(sorted(counts.items()))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--primary-matrix", required=True)
    parser.add_argument("--normalizer-matrix", required=True)
    parser.add_argument("--sequence-database", required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--trial-id", default="baseline-000")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo = Path(args.repo)
    artifact = json.loads(Path(args.artifact).read_text(encoding="utf-8"))
    tmm = artifact.get("tmm_full_temporal") or {}
    matrix = tmm.get("tmm_site_contribution_matrix") or {}
    canonical_keys = sorted(key for key in matrix if "_" in key and " " not in key)
    alias_keys = sorted(key for key in matrix if " " in key)
    profile_counts = Counter(
        _profile_type(row)
        for row in (tmm.get("kinase_scores") or [])
        if row.get("tmm_profile_type") or row.get("profile_type")
    )
    cascade = tmm.get("tmm_weighted_temporal_cascade") or {}
    dual_track = tmm.get("dual_track_kinase_evidence") or {}
    dual_track_rows = dual_track.values() if isinstance(dual_track, dict) else dual_track
    runtime_config = temporal_config_provenance()
    variable_config = {
        "site_aggregation": runtime_config["site_aggregation"],
        "wave.correlation_threshold": runtime_config["wave"]["correlation_threshold"],
        "wave.minimum_variance": runtime_config["wave"]["minimum_variance"],
        "wave.minimum_amplitude": runtime_config["wave"]["minimum_amplitude"],
        "wave.minimum_cluster_size": runtime_config["wave"]["minimum_cluster_size"],
        "wave.maximum_waves": runtime_config["wave"]["maximum_waves"],
        "tmm.profile_min_exclusive": runtime_config["tmm"]["profile_min_exclusive"],
        "tmm.gaussian_sigma_log": runtime_config["tmm"]["gaussian_sigma_log"],
        "tmm.target_transform": runtime_config["tmm"]["target_transform"],
        "activity.effect_size": "weighted_sum",
        "tmm.iterative_profile_rounds": 0,
        "wave.bootstrap_repeats": 0,
        "uncertainty.bootstrap_repeats": 0,
        "uncertainty.loto_enabled": False,
    }
    objective = {
        "mapped_site_count": len(artifact.get("site_availability") or []),
        "canonical_contribution_key_count": len(canonical_keys),
        "alias_contribution_key_count": len(alias_keys),
        "profile_type_counts": dict(sorted(profile_counts.items())),
        "candidate_count_distribution": _candidate_count_distribution(matrix),
        "cascade_timepoint_count": len(cascade.get("timepoints") or []),
        "directionality_edge_count": len(tmm.get("tmm_kinase_pair_directionality") or []),
        "dual_track_status_counts": dict(sorted(Counter(
            str(row.get("status") or "missing")
            for row in dual_track_rows
            if isinstance(row, dict)
        ).items())),
    }
    record = append_trial(
        args.ledger,
        trial_id=args.trial_id,
        phase="truth_free_baseline",
        code_commit=current_commit(repo),
        input_hashes={
            "quant_matrix_primary": file_sha256(args.primary_matrix),
            "quant_matrix_normalizer": file_sha256(args.normalizer_matrix),
            "sequence_database": file_sha256(args.sequence_database),
        },
        variable_config=variable_config,
        objective=objective,
        fold_metrics=[],
        decision="continue",
        decision_reason="Baseline recorded before P0-P2 scientific-contract changes.",
    )
    print(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
