"""Truth-free nested optimization helpers for temporal PTM analysis.

The module never loads benchmark truth.  Parameter selection uses only replicate
holdout stability, structural Wave quality, TMM reconstruction, identifiability
proxies, and parsimony.  A locked scorer may be invoked only after a configuration
has been selected and frozen by the caller.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from ptm_shared.temporal_wave_engine import analyze_temporal_waves
from ptm_shared.tmm_identifiability import normalized_ratios, solve_nnls


def _number(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


def _minutes(label: str) -> float:
    import re

    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(min|m|h|hr|hour)", str(label).strip(), re.I)
    if not match:
        return math.inf
    value = float(match.group(1))
    return value * 60.0 if match.group(2).lower() in {"h", "hr", "hour"} else value


def _aggregate(values: Sequence[float], method: str) -> float:
    if not values:
        return 0.0
    if method == "mean":
        return float(sum(values) / len(values))
    if method == "median":
        return float(statistics.median(values))
    if method == "legacy_last":
        return float(values[-1])
    raise ValueError(f"unsupported aggregation: {method}")


def load_condition_series(vector_path: str | Path, *, aggregation: str) -> tuple[dict[str, dict[str, float]], list[str]]:
    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    with Path(vector_path).open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            gene = str(row.get("Gene.Name") or "").strip().upper()
            site = str(row.get("PTM_Position") or "").strip().upper()
            condition = str(row.get("Condition") or "").strip()
            if gene and site and condition:
                grouped[(f"{gene}_{site}", condition)].append(
                    _number(row.get("PTM_Relative_Log2FC"))
                )
    series: dict[str, dict[str, float]] = defaultdict(dict)
    for (site_key, condition), values in grouped.items():
        series[site_key][condition] = _aggregate(values, aggregation)
    conditions = sorted({condition for values in series.values() for condition in values}, key=lambda value: (_minutes(value), value))
    return dict(series), conditions


def load_replicate_abundance(
    site_level_path: str | Path,
    vector_path: str | Path,
    *,
    aggregation: str,
) -> tuple[dict[str, dict[str, dict[int, float]]], list[str], int]:
    gene_by_protein: dict[str, str] = {}
    with Path(vector_path).open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            protein = str(row.get("Protein.Group") or "").strip()
            gene = str(row.get("Gene.Name") or "").strip().upper()
            if protein and gene:
                gene_by_protein.setdefault(protein, gene)

    records: list[tuple[str, str, str, str, float]] = []
    samples_by_condition: dict[str, set[str]] = defaultdict(set)
    with Path(site_level_path).open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            protein = str(row.get("Protein.Group") or "").strip()
            gene = gene_by_protein.get(protein, "")
            site = str(row.get("PTM_Position") or "").strip().upper()
            condition = str(row.get("Condition") or "").strip()
            sample = str(row.get("Sample") or "").strip()
            abundance = _number(row.get("PTM_Relative_Abundance"), float("nan"))
            if gene and site and condition and sample and math.isfinite(abundance) and abundance > 0:
                records.append((f"{gene}_{site}", condition, sample, protein, abundance))
                samples_by_condition[condition].add(sample)

    index_by_sample = {
        (condition, sample): index
        for condition, samples in samples_by_condition.items()
        for index, sample in enumerate(sorted(samples))
    }
    grouped: dict[tuple[str, str, int], list[float]] = defaultdict(list)
    for site_key, condition, sample, _protein, abundance in records:
        grouped[(site_key, condition, index_by_sample[(condition, sample)])].append(abundance)
    abundance_by_site: dict[str, dict[str, dict[int, float]]] = defaultdict(lambda: defaultdict(dict))
    for (site_key, condition, replicate_index), values in grouped.items():
        abundance_by_site[site_key][condition][replicate_index] = _aggregate(values, aggregation)
    conditions = sorted((condition for condition in samples_by_condition if condition.lower() != "control"), key=lambda value: (_minutes(value), value))
    replicate_count = min((len(samples) for samples in samples_by_condition.values()), default=0)
    return {site: {condition: dict(values) for condition, values in conditions_map.items()} for site, conditions_map in abundance_by_site.items()}, conditions, replicate_count


def fold_series_from_abundance(
    abundance_by_site: Mapping[str, Mapping[str, Mapping[int, float]]],
    conditions: Sequence[str],
    *,
    held_out_replicate: int,
    replicate_count: int,
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    train_indices = [index for index in range(replicate_count) if index != held_out_replicate]
    train: dict[str, dict[str, float]] = {}
    test: dict[str, dict[str, float]] = {}
    for site_key, by_condition in abundance_by_site.items():
        control = by_condition.get("Control") or by_condition.get("control") or {}
        train_control = [control[index] for index in train_indices if index in control and control[index] > 0]
        test_control = control.get(held_out_replicate)
        if not train_control or not test_control or test_control <= 0:
            continue
        train_values: dict[str, float] = {}
        test_values: dict[str, float] = {}
        for condition in conditions:
            values = by_condition.get(condition) or {}
            train_condition = [values[index] for index in train_indices if index in values and values[index] > 0]
            test_condition = values.get(held_out_replicate)
            if train_condition:
                train_values[condition] = math.log2(float(np.mean(train_condition)) / float(np.mean(train_control)))
            if test_condition and test_condition > 0:
                test_values[condition] = math.log2(float(test_condition) / float(test_control))
        if len(train_values) == len(conditions):
            train[site_key] = train_values
        if len(test_values) == len(conditions):
            test[site_key] = test_values
    return train, test


def load_candidate_modules(replay_path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(replay_path).read_text(encoding="utf-8"))
    annotation = payload.get("annotation") or {}
    modules = annotation.get("tmm_candidate_modules") or annotation.get("kinase_modules") or []
    return list(modules)


def build_ptm_to_kinases(modules: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for module in modules:
        canonical = str(module.get("canonical") or module.get("kinase") or "").upper()
        for member in module.get("members") or []:
            key = str(member.get("key") or "")
            if canonical and key:
                result[key].add(canonical)
    return {key: sorted(values) for key, values in result.items()}


def adjusted_rand_index(left: Mapping[str, str], right: Mapping[str, str]) -> float:
    keys = sorted(set(left) & set(right))
    if len(keys) < 2:
        return 0.0
    contingency = Counter((left[key], right[key]) for key in keys)
    left_counts = Counter(left[key] for key in keys)
    right_counts = Counter(right[key] for key in keys)

    def comb2(value: int) -> float:
        return value * (value - 1) / 2.0

    sum_comb = sum(comb2(value) for value in contingency.values())
    sum_left = sum(comb2(value) for value in left_counts.values())
    sum_right = sum(comb2(value) for value in right_counts.values())
    total = comb2(len(keys))
    expected = sum_left * sum_right / total if total else 0.0
    maximum = (sum_left + sum_right) / 2.0
    denominator = maximum - expected
    return (sum_comb - expected) / denominator if denominator else 1.0


def wave_labels(contract: Mapping[str, Any], all_sites: Iterable[str]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for wave in contract.get("waves") or []:
        wave_id = str(wave.get("wave_id") or wave.get("cluster_id") or "")
        for member in wave.get("members") or []:
            labels[str(member)] = wave_id
    for site in all_sites:
        labels.setdefault(site, f"unassigned:{site}")
    return labels


def evaluate_wave_configuration(
    full_series: Mapping[str, Mapping[str, float]],
    fold_pairs: Sequence[tuple[Mapping[str, Mapping[str, float]], Mapping[str, Mapping[str, float]]]],
    conditions: Sequence[str],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    contract = analyze_temporal_waves(full_series, conditions, config=config)
    total = max(1, int(contract.get("summary", {}).get("total_input_sites", len(full_series))))
    assigned = sum(int(wave.get("member_count") or 0) for wave in contract.get("waves") or [])
    assigned_fraction = assigned / total
    wave_sizes = [int(wave.get("member_count") or 0) for wave in contract.get("waves") or []]
    weighted_coherence = (
        sum(float(wave.get("correlation_mean") or 0.0) * int(wave.get("member_count") or 0) for wave in contract.get("waves") or []) / assigned
        if assigned else 0.0
    )
    peaks = {str(wave.get("peak_timepoint") or "") for wave in contract.get("waves") or [] if wave.get("peak_timepoint")}
    peak_diversity = len(peaks) / max(1, min(len(conditions), len(wave_sizes)))
    fold_ari = []
    for train, test in fold_pairs:
        shared = sorted(set(train) & set(test))
        train_contract = analyze_temporal_waves({key: train[key] for key in shared}, conditions, config=config)
        test_contract = analyze_temporal_waves({key: test[key] for key in shared}, conditions, config=config)
        fold_ari.append(
            adjusted_rand_index(
                wave_labels(train_contract, shared),
                wave_labels(test_contract, shared),
            )
        )
    stability = float(np.mean(fold_ari)) if fold_ari else 0.0
    excess_complexity = max(0.0, (len(wave_sizes) - 8) / 8.0)
    objective = (
        0.45 * max(0.0, stability)
        + 0.25 * max(0.0, weighted_coherence)
        + 0.20 * assigned_fraction
        + 0.10 * peak_diversity
        - 0.05 * excess_complexity
    )
    return {
        "objective": round(objective, 8),
        "replicate_adjusted_rand": round(stability, 8),
        "replicate_adjusted_rand_folds": [round(value, 8) for value in fold_ari],
        "weighted_within_wave_correlation": round(weighted_coherence, 8),
        "assigned_fraction": round(assigned_fraction, 8),
        "peak_diversity": round(peak_diversity, 8),
        "num_waves": len(wave_sizes),
        "wave_sizes": wave_sizes,
        "eligible_sites": contract.get("summary", {}).get("eligible_sites", 0),
        "config": dict(config),
    }


def _profile_correlation(left: np.ndarray, right: np.ndarray) -> float | None:
    if left.size != right.size or left.size < 3 or float(np.std(left)) == 0.0 or float(np.std(right)) == 0.0:
        return None
    value = float(np.corrcoef(left, right)[0, 1])
    return value if math.isfinite(value) else None


def deterministic_shared_sites(
    ptm_to_kinases: Mapping[str, Sequence[str]],
    *,
    limit: int,
    salt: str = "ptm_tmm_search_v1",
) -> list[str]:
    shared = [key for key, kinases in ptm_to_kinases.items() if len(kinases) >= 2]
    shared.sort(key=lambda key: hashlib.sha256(f"{salt}:{key}".encode("utf-8")).hexdigest())
    return shared[:limit]


def deterministic_site_sample(
    sites: Iterable[str],
    *,
    limit: int,
    salt: str = "ptm_wave_search_v1",
) -> list[str]:
    ordered = sorted(
        set(sites),
        key=lambda key: hashlib.sha256(f"{salt}:{key}".encode("utf-8")).hexdigest(),
    )
    return ordered[:limit] if limit > 0 else ordered


def evaluate_tmm_configuration(
    modules: Sequence[Mapping[str, Any]],
    fold_pairs: Sequence[tuple[Mapping[str, Mapping[str, float]], Mapping[str, Mapping[str, float]]]],
    conditions: Sequence[str],
    config: Mapping[str, Any],
    *,
    site_limit: int = 300,
    site_salt: str = "ptm_tmm_search_v1",
) -> dict[str, Any]:
    from app.services.temporal_kinase_scoring import (
        TMM_TARGET_MAGNITUDE,
        _build_kinase_design,
        _tmm_target_vector,
        build_kinase_profiles_from_data,
    )

    ptm_to_kinases = build_ptm_to_kinases(modules)
    sites = deterministic_shared_sites(ptm_to_kinases, limit=site_limit, salt=site_salt)
    min_exclusive = int(config["profile_min_exclusive"])
    sigma = float(config["gaussian_sigma_log"])
    transform = str(config["target_transform"])
    fold_metrics: list[dict[str, float]] = []
    for train, test in fold_pairs:
        profiles_train = build_kinase_profiles_from_data(
            list(modules), dict(train), ptm_to_kinases, list(conditions),
            min_exclusive_for_profile=min_exclusive,
            gaussian_sigma_log=sigma,
        )
        profiles_test = build_kinase_profiles_from_data(
            list(modules), dict(test), ptm_to_kinases, list(conditions),
            min_exclusive_for_profile=min_exclusive,
            gaussian_sigma_log=sigma,
        )
        profile_correlations = []
        data_driven = 0
        for kinase, profile in profiles_train.items():
            if profile.get("profile_type") == "data_driven":
                data_driven += 1
                other = profiles_test.get(kinase)
                if other and other.get("profile_type") == "data_driven":
                    correlation = _profile_correlation(
                        np.asarray(profile["profile"], dtype=float),
                        np.asarray(other["profile"], dtype=float),
                    )
                    if correlation is not None:
                        profile_correlations.append(correlation)

        residuals = []
        equal_residuals = []
        top1_matches = []
        evaluated = 0
        for site in sites:
            if site not in train or site not in test:
                continue
            candidates = list(ptm_to_kinases.get(site) or [])
            design, names = _build_kinase_design(
                candidates,
                profiles_train,
                list(conditions),
                gaussian_sigma_log=sigma,
            )
            if design.shape[1] < 2:
                continue
            y_train = _tmm_target_vector(
                [train[site].get(condition, 0.0) for condition in conditions],
                target_transform=transform,
            )
            y_test = _tmm_target_vector(
                [test[site].get(condition, 0.0) for condition in conditions],
                target_transform=transform,
            )
            train_coefficients, _ = solve_nnls(design, y_train)
            test_coefficients, _ = solve_nnls(design, y_test)
            prediction = design @ train_coefficients
            denominator = max(float(np.linalg.norm(y_test)), 1e-9)
            residuals.append(float(np.linalg.norm(prediction - y_test)) / denominator)

            equal_profile = np.mean(design, axis=1)
            scale_denominator = float(equal_profile @ equal_profile)
            scale = max(0.0, float(equal_profile @ y_train) / scale_denominator) if scale_denominator > 0 else 0.0
            equal_prediction = equal_profile * scale
            equal_residuals.append(float(np.linalg.norm(equal_prediction - y_test)) / denominator)

            train_ratios = normalized_ratios(train_coefficients)
            test_ratios = normalized_ratios(test_coefficients)
            if train_ratios.size and test_ratios.size:
                top1_matches.append(float(int(np.argmax(train_ratios)) == int(np.argmax(test_ratios))))
            evaluated += 1

        median_residual = float(np.median(residuals)) if residuals else 1.0
        median_equal = float(np.median(equal_residuals)) if equal_residuals else 1.0
        profile_stability = float(np.mean(profile_correlations)) if profile_correlations else 0.0
        top1_stability = float(np.mean(top1_matches)) if top1_matches else 0.0
        data_driven_fraction = data_driven / max(1, len(profiles_train))
        fold_metrics.append({
            "median_holdout_residual": median_residual,
            "median_equal_weight_residual": median_equal,
            "residual_improvement": median_equal - median_residual,
            "top1_stability": top1_stability,
            "profile_correlation": profile_stability,
            "data_driven_fraction": data_driven_fraction,
            "evaluated_sites": float(evaluated),
        })

    mean_metrics = {
        key: float(np.mean([fold[key] for fold in fold_metrics])) if fold_metrics else 0.0
        for key in (
            "median_holdout_residual",
            "median_equal_weight_residual",
            "residual_improvement",
            "top1_stability",
            "profile_correlation",
            "data_driven_fraction",
            "evaluated_sites",
        )
    }
    residual_score = max(0.0, 1.0 - min(1.0, mean_metrics["median_holdout_residual"]))
    improvement_score = max(0.0, min(1.0, 0.5 + mean_metrics["residual_improvement"] / 2.0))
    objective = (
        0.35 * residual_score
        + 0.20 * mean_metrics["top1_stability"]
        + 0.20 * max(0.0, mean_metrics["profile_correlation"])
        + 0.15 * improvement_score
        + 0.10 * mean_metrics["data_driven_fraction"]
    )
    return {
        "objective": round(objective, 8),
        **{key: round(value, 8) for key, value in mean_metrics.items()},
        "shared_sites_available": len([key for key, values in ptm_to_kinases.items() if len(values) >= 2]),
        "candidate_sites_sampled": len(sites),
        "site_sample_salt": site_salt,
        "fold_metrics": [{key: round(value, 8) for key, value in fold.items()} for fold in fold_metrics],
        "config": dict(config),
        "target_is_magnitude": transform == TMM_TARGET_MAGNITUDE,
    }


def wave_search_space(seed: int = 20260826, random_count: int = 32) -> list[dict[str, Any]]:
    baseline = {
        "correlation_threshold": 0.70,
        "minimum_variance": 0.30,
        "minimum_amplitude": 0.80,
        "minimum_cluster_size": 2,
        "maximum_waves": 8,
        "compute_directionality": False,
        "threshold_source": "optimization_study.v1",
    }
    candidates = [baseline]
    dimensions = {
        "correlation_threshold": [0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85],
        "minimum_variance": [0.10, 0.20, 0.30, 0.40, 0.50],
        "minimum_amplitude": [0.40, 0.60, 0.80, 1.00, 1.20],
        "minimum_cluster_size": [2, 3, 4, 5],
        "maximum_waves": [6, 8, 10, 12],
    }
    for key, values in dimensions.items():
        for value in values:
            candidate = dict(baseline)
            candidate[key] = value
            candidates.append(candidate)
    generator = random.Random(seed)
    for _ in range(random_count):
        candidate = dict(baseline)
        for key, values in dimensions.items():
            candidate[key] = generator.choice(values)
        candidates.append(candidate)
    unique = {json.dumps(candidate, sort_keys=True): candidate for candidate in candidates}
    return list(unique.values())


def tmm_search_space() -> list[dict[str, Any]]:
    return [
        {
            "profile_min_exclusive": minimum,
            "gaussian_sigma_log": sigma,
            "target_transform": transform,
        }
        for minimum in (2, 3, 4, 5, 6)
        for sigma in (0.4, 0.6, 0.8, 1.0)
        for transform in ("signed", "magnitude")
    ]


def config_sha256(config: Mapping[str, Any]) -> str:
    payload = json.dumps(dict(config), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def write_json(path: str | Path, payload: Any) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return destination
