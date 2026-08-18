"""Measure whether deployed TMM kinase attributions are identifiable.

Read-only.  For every shared PTM site in a completed order this rebuilds the
exact design matrix the production solver receives - the same profile builder,
the same Gaussian priors for kinases without enough exclusive substrates, and
the same zero-imputation of unmeasured timepoints - then reports whether the
resulting non-negative least squares problem determines the contribution ratio
that the platform publishes.

The reported ratios are also compared against ``deconvolve_shared_ptm`` itself,
so the diagnosis is provably about the deployed estimator and not a lookalike.

Run inside the API container, which is where the production scoring module and
the reference kinase tables live:

    docker exec -i ptm-api-server env PYTHONPATH=/app:/opt python - \
        --order-ids 48,47,45,36,33,28 < scripts/diagnose_tmm_identifiability.py
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

sys.path[:0] = ["/app", "/opt"]

from ptm_shared.tmm_identifiability import (  # noqa: E402
    VERDICT_EQUAL_WEIGHT_FALLBACK,
    VERDICT_IDENTIFIABLE,
    VERDICT_NON_IDENTIFIABLE,
    VERDICT_NO_SIGNAL,
    VERDICT_WEAK,
    ambiguity_aware_attribution,
    diagnose_site,
    normalized_ratios,
    solve_nnls,
    summarize_bias,
    summarize_diagnostics,
    zero_imputation_bias,
)

DEFAULT_OUTPUT_DIR = "/app/data/outputs/_diagnostics/tmm_identifiability"


# ---------------------------------------------------------------------------
# Order inputs
# ---------------------------------------------------------------------------


async def load_orders(order_ids: Sequence[int]) -> List[Dict[str, Any]]:
    from sqlalchemy import text

    from app.core.database import AsyncSessionLocal

    placeholders = ", ".join(f":id{i}" for i in range(len(order_ids)))
    params = {f"id{i}": order_id for i, order_id in enumerate(order_ids)}
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    "SELECT id, order_code, ptm_type, status, kinase_activity_heatmap"
                    f" FROM orders WHERE id IN ({placeholders})"
                ),
                params,
            )
        ).all()
    orders: List[Dict[str, Any]] = []
    for row in rows:
        raw = row.kinase_activity_heatmap
        if not raw:
            continue
        heatmap = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
        orders.append(
            {
                "id": int(row.id),
                "order_code": str(row.order_code),
                "ptm_type": str(row.ptm_type or ""),
                "status": str(row.status or ""),
                "heatmap": heatmap,
            }
        )
    orders.sort(key=lambda item: item["id"])
    return orders


def build_kinase_modules(
    kinase_scores: Sequence[Mapping[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, List[str]], int]:
    """Rebuild the module structure and the site-to-kinase map from stored scores."""
    modules: List[Dict[str, Any]] = []
    ptm_to_kinases: Dict[str, List[str]] = {}
    n_truncated = 0
    for entry in kinase_scores:
        canonical = str(entry.get("kinase") or entry.get("canonical") or "").upper()
        if not canonical:
            continue
        substrates = entry.get("substrates") or entry.get("members") or []
        keys = [str(item.get("ptm_key") or item.get("key") or "") for item in substrates]
        keys = [key for key in keys if key]
        declared = entry.get("substrate_count") or entry.get("total_substrates")
        if declared and int(declared) > len(keys):
            n_truncated += 1
        modules.append({"canonical": canonical, "members": [{"key": key} for key in keys]})
        for key in keys:
            ptm_to_kinases.setdefault(key, [])
            if canonical not in ptm_to_kinases[key]:
                ptm_to_kinases[key].append(canonical)
    return modules, ptm_to_kinases, n_truncated


def load_timeseries(
    output_dir: Path, file_suffix: str
) -> Tuple[Dict[str, Dict[str, float]], Dict[str, set]]:
    """Rebuild ptm_timeseries exactly as the kinase endpoint does, plus an observed set."""
    timeseries: Dict[str, Dict[str, float]] = {}
    observed: Dict[str, set] = {}
    for name in (
        f"ptm_vector_data_normalized{file_suffix}.tsv",
        f"ptm_vector_data_with_motifs{file_suffix}.tsv",
    ):
        path = output_dir / name
        if not path.exists():
            continue
        with open(path, "r", encoding="utf-8") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                gene = row.get("Gene.Name", row.get("gene", "")) or ""
                position = str(row.get("PTM_Position", row.get("position", "")) or "")
                condition = row.get("Condition", "") or ""
                if not gene or not position or not condition:
                    continue
                raw = row.get("PTM_Relative_Log2FC", "")
                try:
                    value = float(raw) if raw else 0.0
                except ValueError:
                    value = 0.0
                key = f"{gene.upper()}_{position.upper()}"
                timeseries.setdefault(key, {})[condition] = value
                observed.setdefault(key, set()).add(condition)
        break
    return timeseries, observed


# ---------------------------------------------------------------------------
# Production design matrix
# ---------------------------------------------------------------------------


def build_design(
    candidates: Sequence[str],
    kinase_profiles: Mapping[str, Mapping[str, Any]],
    conditions: Sequence[str],
) -> Tuple[np.ndarray, List[str], List[bool]]:
    """Reproduce the design matrix assembled inside ``deconvolve_shared_ptm``.

    A column is prior-derived when the kinase had too few exclusive substrates
    for a data-driven profile, so the literature peak time enters the basis as
    if it were an observation.
    """
    from app.services.temporal_kinase_scoring import (
        BASOPHILIC_KINASES,
        PRO_DIRECTED_KINASES,
        _gaussian_kinase_profile,
    )

    columns: List[np.ndarray] = []
    names: List[str] = []
    prior_flags: List[bool] = []
    for canonical in candidates:
        info = kinase_profiles.get(canonical)
        if info is None:
            reference = BASOPHILIC_KINASES.get(canonical) or PRO_DIRECTED_KINASES.get(canonical)
            if reference:
                low, high = reference["typical_peak_min"]
                peak = (low + high) / 2.0
            else:
                peak = 30.0
            columns.append(np.asarray(_gaussian_kinase_profile(conditions, peak), dtype=float))
            prior_flags.append(True)
        else:
            columns.append(np.asarray(info["profile"], dtype=float))
            prior_flags.append(info.get("profile_type") != "data_driven")
        names.append(canonical)
    if not columns:
        return np.zeros((len(conditions), 0)), names, prior_flags
    return np.column_stack(columns), names, prior_flags


# ---------------------------------------------------------------------------
# Per-order diagnosis
# ---------------------------------------------------------------------------


def diagnose_order(
    order: Mapping[str, Any],
    *,
    output_root: Path,
    relative_noise: float,
    n_bootstrap: int,
    max_sites: int,
    seed: int,
) -> Optional[Dict[str, Any]]:
    from app.services.temporal_kinase_scoring import (
        build_kinase_profiles_from_data,
        deconvolve_shared_ptm,
    )

    heatmap = order["heatmap"]
    conditions = [str(condition) for condition in (heatmap.get("conditions") or [])]
    kinase_scores = heatmap.get("kinase_scores") or []
    if len(conditions) < 2 or not kinase_scores:
        print(f"  [skip] order {order['id']}: conditions={len(conditions)} kinases={len(kinase_scores)}")
        return None

    file_suffix = "_phospho" if order["ptm_type"] == "phosphorylation" else "_ubi"
    order_dir = output_root / order["order_code"]
    timeseries, observed = load_timeseries(order_dir, file_suffix)
    if not timeseries:
        print(f"  [skip] order {order['id']}: no vector TSV under {order_dir}")
        return None

    modules, ptm_to_kinases, n_truncated = build_kinase_modules(kinase_scores)
    profiles = build_kinase_profiles_from_data(modules, timeseries, ptm_to_kinases, conditions)
    profile_types: Dict[str, int] = {}
    for info in profiles.values():
        label = str(info.get("profile_type", "unknown"))
        profile_types[label] = profile_types.get(label, 0) + 1

    shared_sites = [key for key, kinases in ptm_to_kinases.items() if len(kinases) >= 2]
    shared_sites.sort()
    truncated_sites = False
    if max_sites and len(shared_sites) > max_sites:
        shared_sites = shared_sites[:max_sites]
        truncated_sites = True

    diagnostics = []
    bias_records: List[Dict[str, Any]] = []
    attribution_records: List[Dict[str, Any]] = []
    max_ratio_deviation = 0.0
    for index, site_key in enumerate(shared_sites):
        candidates = ptm_to_kinases[site_key]
        design, names, prior_flags = build_design(candidates, profiles, conditions)
        if design.shape[1] == 0:
            continue
        series = timeseries.get(site_key, {})
        target = np.asarray([series.get(condition, 0.0) for condition in conditions], dtype=float)

        result = diagnose_site(
            site_key,
            target,
            design,
            names,
            relative_noise=relative_noise,
            n_bootstrap=n_bootstrap,
            seed=seed + index,
            prior_columns=prior_flags,
        )
        diagnostics.append(result)

        production = deconvolve_shared_ptm(
            site_key, list(candidates), profiles, timeseries, conditions
        )
        replicated = normalized_ratios(solve_nnls(design, target)[0])
        for position, name in enumerate(names):
            deviation = abs(float(production.get(name, 0.0)) - float(replicated[position]))
            max_ratio_deviation = max(max_ratio_deviation, deviation)

        attribution = ambiguity_aware_attribution(
            site_key, target, design, names, relative_noise=relative_noise
        )
        attribution_records.append(
            {
                "site_key": site_key,
                "n_candidates": attribution.n_candidates,
                "n_groups": attribution.n_groups,
                "attribution_supported": attribution.attribution_supported,
                "unsupported_reason": attribution.unsupported_reason,
                "n_ambiguous_groups": sum(1 for group in attribution.groups if group.ambiguous),
                "largest_group_size": max(
                    (len(group.members) for group in attribution.groups), default=0
                ),
                "reduced_verdict": (
                    attribution.reduced_diagnosis.verdict
                    if attribution.reduced_diagnosis
                    else None
                ),
            }
        )

        seen = observed.get(site_key, set())
        mask = np.asarray([condition in seen for condition in conditions], dtype=bool)
        bias_records.append(
            zero_imputation_bias(site_key, target, design, names, mask)
        )

    summary = summarize_diagnostics(diagnostics)
    report = {
        "attribution": summarize_attribution(attribution_records),
        "order_id": order["id"],
        "order_code": order["order_code"],
        "status": order["status"],
        "ptm_type": order["ptm_type"],
        "conditions": conditions,
        "n_timepoints": len(conditions),
        "n_kinases": len(kinase_scores),
        "n_kinase_profiles": len(profiles),
        "profile_types": profile_types,
        "n_sites_in_modules": len(ptm_to_kinases),
        "n_shared_sites": len([1 for kinases in ptm_to_kinases.values() if len(kinases) >= 2]),
        "n_diagnosed": len(diagnostics),
        "site_list_truncated": truncated_sites,
        "n_kinases_with_truncated_substrate_list": n_truncated,
        "assumptions": {
            "relative_noise": relative_noise,
            "n_bootstrap": n_bootstrap,
            "seed": seed,
        },
        "production_ratio_max_deviation": max_ratio_deviation,
        "identifiability": summary,
        "zero_imputation_bias": summarize_bias(bias_records),
        "sites": [item.to_dict() for item in diagnostics],
    }
    return report


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def quantiles(values: Sequence[float], points: Sequence[int] = (10, 50, 90)) -> Dict[str, Any]:
    finite = np.asarray([value for value in values if np.isfinite(value)], dtype=float)
    if finite.size == 0:
        return {"n": 0, **{f"p{point}": None for point in points}, "max": None}
    summary: Dict[str, Any] = {"n": int(finite.size)}
    for point in points:
        summary[f"p{point}"] = float(np.percentile(finite, point))
    summary["max"] = float(finite.max())
    return summary


def summarize_attribution(records: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Compare what production publishes against what is actually estimable.

    Production reports one ratio per candidate kinase.  The ambiguity-aware
    estimator reports one share per group of candidates the data cannot separate,
    and nothing at all for sites no non-negative combination can explain.
    """
    summary: Dict[str, Any] = {"n_sites": len(records)}
    if not records:
        return summary

    published = sum(int(record["n_candidates"]) for record in records)
    supported = [record for record in records if record["attribution_supported"]]
    estimable = sum(int(record["n_groups"]) for record in supported)
    verdicts: Dict[str, int] = {}
    for record in supported:
        label = str(record.get("reduced_verdict"))
        verdicts[label] = verdicts.get(label, 0) + 1

    summary.update(
        {
            "per_kinase_ratios_published": published,
            "estimable_group_shares": estimable,
            "quantity_reduction": 1.0 - (estimable / published) if published else None,
            "n_supported": len(supported),
            "unsupported_rate": 1.0 - len(supported) / len(records),
            "sites_needing_merge_rate": float(
                np.mean([record["n_groups"] < record["n_candidates"] for record in records])
            ),
            "largest_group_size": quantiles(
                [int(record["largest_group_size"]) for record in records]
            ),
            "reduced_verdicts": verdicts,
            "reduced_verdict_fractions": {
                key: value / len(supported) for key, value in verdicts.items()
            }
            if supported
            else {},
        }
    )
    return summary


def print_order_summary(report: Mapping[str, Any]) -> None:
    identifiability = report["identifiability"]
    fractions = identifiability.get("verdict_fractions", {})
    rates = identifiability.get("rates", {})
    distributions = identifiability.get("distributions", {})
    bias = report["zero_imputation_bias"]

    def percent(value: Optional[float]) -> str:
        return "  n/a" if value is None else f"{100.0 * float(value):5.1f}%"

    def number(container: Mapping[str, Any], key: str, point: str = "p50") -> str:
        stats = container.get(key) or {}
        value = stats.get(point)
        return "n/a" if value is None else f"{float(value):.3f}"

    print(f"\n  order {report['order_id']} | {report['order_code']}")
    print(
        f"    T={report['n_timepoints']} conditions={report['conditions']}"
        f" kinases={report['n_kinases']} shared_sites={report['n_shared_sites']}"
        f" diagnosed={report['n_diagnosed']}"
    )
    print(f"    profile types: {report['profile_types']}")
    print(f"    production ratio max deviation: {report['production_ratio_max_deviation']:.2e}")
    print(
        f"    verdicts: identifiable {percent(fractions.get(VERDICT_IDENTIFIABLE))}"
        f" | weak {percent(fractions.get(VERDICT_WEAK))}"
        f" | non-identifiable {percent(fractions.get(VERDICT_NON_IDENTIFIABLE))}"
        f" | equal-weight {percent(fractions.get(VERDICT_EQUAL_WEIGHT_FALLBACK))}"
        f" | no-signal {percent(fractions.get(VERDICT_NO_SIGNAL))}"
    )
    print(
        f"    structural: underdetermined {percent(rates.get('structurally_underdetermined'))}"
        f" | rank-one design {percent(rates.get('rank_one_design'))}"
        f" | duplicate columns {percent(rates.get('duplicate_columns'))}"
        f" | non-unique {percent(rates.get('non_unique_solution'))}"
    )
    print(
        f"    fit: explains nothing {percent(rates.get('explains_nothing'))}"
        f" | design rank p50={number(distributions, 'design_rank')}"
        f" | y negative fraction p50={number(distributions, 'y_negative_fraction')}"
    )
    print(
        f"    top-1: in ambiguity set {percent(rates.get('top1_in_ambiguity_set'))}"
        f" | from prior profile {percent(rates.get('top1_from_prior_profile'))}"
        f" | stability p10={number(distributions, 'top1_stability', 'p10')}"
    )
    print(
        f"    medians: coherence={number(distributions, 'max_column_coherence')}"
        f" ambiguity_radius={number(distributions, 'ratio_ambiguity_radius')}"
        f" relative_residual={number(distributions, 'relative_residual')}"
        f" sigma_min={number(distributions, 'active_sigma_min')}"
    )
    reversal = bias.get("top1_reversal_rate")
    print(
        f"    zero-imputation: evaluated {bias.get('n_evaluated')}"
        f" | top-1 reversal {percent(reversal)}"
        f" | ratio TV p90={number(bias, 'ratio_total_variation', 'p90')}"
    )

    attribution = report.get("attribution") or {}
    if attribution.get("n_sites"):
        reduced = attribution.get("reduced_verdict_fractions") or {}
        print(
            f"    attribution: published per-kinase ratios"
            f" {attribution.get('per_kinase_ratios_published')}"
            f" -> estimable group shares {attribution.get('estimable_group_shares')}"
            f" ({percent(attribution.get('quantity_reduction'))} fewer)"
        )
        print(
            f"                 unsupported {percent(attribution.get('unsupported_rate'))}"
            f" | needs merge {percent(attribution.get('sites_needing_merge_rate'))}"
            f" | largest group p90={number(attribution, 'largest_group_size', 'p90')}"
            f" | after merge identifiable {percent(reduced.get(VERDICT_IDENTIFIABLE))}"
        )


def combine_attribution(reports: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    published = estimable = supported = sites = 0
    verdicts: Dict[str, int] = {}
    for report in reports:
        block = report.get("attribution") or {}
        if not block.get("n_sites"):
            continue
        sites += int(block["n_sites"])
        published += int(block["per_kinase_ratios_published"])
        estimable += int(block["estimable_group_shares"])
        supported += int(block["n_supported"])
        for key, value in (block.get("reduced_verdicts") or {}).items():
            verdicts[key] = verdicts.get(key, 0) + int(value)
    if not sites:
        return {}
    return {
        "n_sites": sites,
        "per_kinase_ratios_published": published,
        "estimable_group_shares": estimable,
        "quantity_reduction": 1.0 - estimable / published if published else None,
        "n_supported": supported,
        "unsupported_rate": 1.0 - supported / sites,
        "reduced_verdicts": verdicts,
        "reduced_verdict_fractions": (
            {key: value / supported for key, value in verdicts.items()} if supported else {}
        ),
    }


def combine(reports: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    pooled: List[Dict[str, Any]] = []
    for report in reports:
        pooled.extend(report["sites"])

    def rate(key: str) -> Optional[float]:
        flags = [site.get(key) for site in pooled if site.get(key) is not None]
        return float(np.mean([bool(flag) for flag in flags])) if flags else None

    verdicts: Dict[str, int] = {}
    for site in pooled:
        label = str(site.get("verdict"))
        verdicts[label] = verdicts.get(label, 0) + 1
    total = max(len(pooled), 1)
    return {
        "n_orders": len(reports),
        "n_sites": len(pooled),
        "verdicts": verdicts,
        "verdict_fractions": {key: value / total for key, value in verdicts.items()},
        "structurally_underdetermined_rate": rate("structurally_underdetermined"),
        "rank_one_design_rate": float(
            np.mean([int(site.get("design_rank") or 0) <= 1 for site in pooled])
        )
        if pooled
        else None,
        "explains_nothing_rate": float(
            np.mean([float(site.get("relative_residual") or 0.0) >= 0.999 for site in pooled])
        )
        if pooled
        else None,
        "top1_in_ambiguity_set_rate": float(
            np.mean(
                [
                    bool(site.get("top1_kinase") and site.get("top1_kinase") in (site.get("ambiguity_set") or []))
                    for site in pooled
                ]
            )
        )
        if pooled
        else None,
        "top1_from_prior_rate": rate("top1_from_prior"),
        "equal_weight_fallback_rate": rate("equal_weight_fallback"),
        "attribution": combine_attribution(reports),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--order-ids", default="48,47,45,36,33,28")
    parser.add_argument("--relative-noise", type=float, default=0.10)
    parser.add_argument("--bootstrap", type=int, default=32)
    parser.add_argument("--max-sites", type=int, default=4000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--outputs-root", default="/app/data/outputs")
    parser.add_argument("--report-dir", default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    order_ids = [int(token) for token in args.order_ids.split(",") if token.strip()]
    orders = asyncio.run(load_orders(order_ids))
    if not orders:
        print("No orders with stored kinase results were found.")
        return 1

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    outputs_root = Path(args.outputs_root)

    print(f"Diagnosing {len(orders)} order(s); relative_noise={args.relative_noise}")
    reports: List[Dict[str, Any]] = []
    for order in orders:
        report = diagnose_order(
            order,
            output_root=outputs_root,
            relative_noise=args.relative_noise,
            n_bootstrap=args.bootstrap,
            max_sites=args.max_sites,
            seed=args.seed,
        )
        if report is None:
            continue
        reports.append(report)
        print_order_summary(report)
        destination = report_dir / f"{order['order_code']}_tmm_identifiability.json"
        destination.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if not reports:
        print("\nNo order produced a diagnosable design matrix.")
        return 1

    pooled = combine(reports)
    (report_dir / "_pooled_summary.json").write_text(json.dumps(pooled, indent=2), encoding="utf-8")
    print("\n=== pooled across orders ===")
    print(json.dumps(pooled, indent=2))
    print(f"\nReports written to {report_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
