from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _cascade_timepoint_count(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, Mapping):
        timepoints = value.get("timepoints")
        if isinstance(timepoints, list):
            return len(timepoints)
        flow = value.get("cascade_flow")
        if isinstance(flow, list):
            return len(flow)
    return 0


def capture_v1_semantic_baseline(
    *,
    artifact: Mapping[str, Any],
    score_summary: Mapping[str, Any],
    artifact_path: str | Path,
    score_path: str | Path,
    figure_dir: str | Path,
    source_data_dir: str | Path,
    input_hashes: Mapping[str, str],
    code_commit: str,
) -> dict[str, Any]:
    """Capture truth-free v1 semantics plus aggregate locked-score invariants.

    The baseline stores no anchor identities.  It is suitable for proving that an
    additive v2 sidecar did not alter the v1 analysis or primary-score contract.
    """

    wave = _mapping(artifact.get("temporal_wave_contract"))
    tmm = _mapping(artifact.get("tmm_full_temporal"))
    kinase_scores = _list(tmm.get("kinase_scores"))
    profile_count = sum(
        1
        for row in kinase_scores
        if isinstance(row, Mapping) and str(row.get("tmm_profile_type") or "").strip()
    )
    figures = Path(figure_dir)
    sources = Path(source_data_dir)

    primary_metrics = dict(_mapping(score_summary.get("metrics")))
    primary_denominators = dict(_mapping(score_summary.get("metric_denominators")))

    return {
        "schema_version": "ptm_benchmark_v1_golden.v1",
        "code_commit": str(code_commit),
        "input_hashes": dict(sorted((str(k), str(v)) for k, v in input_hashes.items())),
        "artifact_sha256": sha256_file(artifact_path),
        "score_summary_sha256": sha256_file(score_path),
        "semantic": {
            "artifact_schema_version": artifact.get("schema_version"),
            "site_observation_count": len(_list(artifact.get("site_observations"))),
            "site_availability_count": len(_list(artifact.get("site_availability"))),
            "wave_count": len(_list(wave.get("waves"))),
            "wave_member_count": sum(
                len(_list(row.get("members")))
                for row in _list(wave.get("waves"))
                if isinstance(row, Mapping)
            ),
            "kinase_score_count": len(kinase_scores),
            "tmm_profile_count": profile_count,
            "relative_contribution_site_count": len(
                _mapping(tmm.get("relative_site_contribution_matrix"))
            ),
            "occupancy_contribution_site_count": len(
                _mapping(tmm.get("occupancy_site_contribution_matrix"))
            ),
            "cascade_timepoint_count": _cascade_timepoint_count(
                tmm.get("tmm_weighted_temporal_cascade")
            ),
            "main_directionality_edge_count": len(
                _list(tmm.get("tmm_kinase_pair_directionality"))
            ),
            "candidate_directionality_edge_count": len(
                _list(tmm.get("tmm_kinase_pair_directionality_candidates"))
            ),
        },
        "primary_v1": {
            "metrics": primary_metrics,
            "metric_denominators": primary_denominators,
        },
        "publication_sha256": {
            **{
                f"figures/Fig{index}.svg": sha256_file(figures / f"Fig{index}.svg")
                for index in range(1, 5)
            },
            **{
                f"source_data/Fig{index}_source_data.tsv": sha256_file(
                    sources / f"Fig{index}_source_data.tsv"
                )
                for index in range(1, 5)
            },
        },
    }


def compare_v1_semantic_baseline(
    expected: Mapping[str, Any], observed: Mapping[str, Any]
) -> dict[str, Any]:
    """Return a field-level semantic noninferiority report.

    Exact file hashes are reported separately because additive publication rows may
    legitimately change v2 files.  v1 semantics and primary metrics must remain exact.
    """

    failures: list[dict[str, Any]] = []
    for section_name in ("semantic", "primary_v1"):
        expected_section = _mapping(expected.get(section_name))
        observed_section = _mapping(observed.get(section_name))
        for key, expected_value in expected_section.items():
            observed_value = observed_section.get(key)
            if observed_value != expected_value:
                failures.append(
                    {
                        "section": section_name,
                        "field": key,
                        "expected": expected_value,
                        "observed": observed_value,
                    }
                )
    return {
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
    }


def write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
