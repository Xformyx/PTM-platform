"""Prove the identifiability annotations changed no existing TMM number.

Loads the pre-change ``temporal_kinase_scoring`` snapshot alongside the current
module, runs both over the same reconstructed order inputs, and compares every
pre-existing field.  The new ``resolution`` / ``group_ratio`` /
``ambiguity_group_members`` / ``tmm_identifiability`` keys are excluded from the
comparison because they did not exist before; everything else must match exactly.

Usage (snapshot is placed in the container first):

    git show HEAD:api-server/app/services/temporal_kinase_scoring.py > .tmp_baseline_tks.py
    docker cp .tmp_baseline_tks.py ptm-api-server:/tmp/baseline_tks.py
    docker exec -i ptm-api-server env PYTHONPATH=/app:/opt python - --order-ids 36 \
        < scripts/verify_tmm_identifiability_additive.py
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple

sys.path[:0] = ["/app", "/opt"]

NEW_DETAIL_KEYS = {
    "resolution",
    "group_ratio",
    "ambiguity_group_members",
    "unsupported_reason",
    # 아래 셋은 guard 정책이 켜진 실행에서만 나타난다.  기본값 `off` 로 비교할 때는
    # 등장하지 않으므로 이 허용 목록이 검증을 약화시키지 않는다.
    # docs/chapter2_audit_protocol_v1.md §5 (2026-08-21), §5.5 (2026-08-22).
    "guard_withheld",
    "guard_reason",
    "guard_scoring_excluded",
}
NEW_KINASE_KEYS = {"tmm_identifiability"}
NEW_NESTED_KEYS = {
    # tmm_identifiability 안에 나중에 추가된 키.  값이 아니라 존재만 허용한다.
    # docs/chapter2_audit_protocol_v1.md §5 에서 2026-08-21 선언
    # (`n_guard_scoring_excluded` 는 §5.5 에서 2026-08-22 선언).
    "tmm_identifiability": {
        "guard_policy",
        "n_guard_withheld",
        "n_guard_scoring_excluded",
    },
}
BASELINE_SNAPSHOT = "/tmp/baseline_tks.py"


def load_snapshot(path: str):
    spec = importlib.util.spec_from_file_location("baseline_tks", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load baseline snapshot from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["baseline_tks"] = module
    spec.loader.exec_module(module)
    return module


async def load_orders(order_ids: Sequence[int]) -> List[Dict[str, Any]]:
    """Load every order in one event loop; the engine pool cannot span loops."""
    from sqlalchemy import text

    from app.core.database import AsyncSessionLocal

    loaded: List[Dict[str, Any]] = []
    async with AsyncSessionLocal() as db:
        for order_id in order_ids:
            row = (
                await db.execute(
                    text(
                        "SELECT id, order_code, ptm_type, kinase_activity_heatmap"
                        " FROM orders WHERE id = :id"
                    ),
                    {"id": order_id},
                )
            ).first()
            if row is None or not row.kinase_activity_heatmap:
                print(f"  [skip] order {order_id} has no stored kinase results")
                continue
            raw = row.kinase_activity_heatmap
            loaded.append(
                {
                    "id": int(row.id),
                    "order_code": str(row.order_code),
                    "ptm_type": str(row.ptm_type or ""),
                    "heatmap": json.loads(raw) if isinstance(raw, (str, bytes)) else raw,
                }
            )
    return loaded


def rebuild_inputs(
    order: Mapping[str, Any], outputs_root: Path
) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, float]], Dict[str, List[str]], List[str]]:
    heatmap = order["heatmap"]
    conditions = [str(condition) for condition in (heatmap.get("conditions") or [])]
    modules: List[Dict[str, Any]] = []
    ptm_to_kinases: Dict[str, List[str]] = {}
    for entry in heatmap.get("kinase_scores") or []:
        canonical = str(entry.get("kinase") or entry.get("canonical") or "").upper()
        if not canonical:
            continue
        keys = [
            str(item.get("ptm_key") or item.get("key") or "")
            for item in (entry.get("substrates") or entry.get("members") or [])
        ]
        keys = [key for key in keys if key]
        modules.append({"canonical": canonical, "members": [{"key": key} for key in keys]})
        for key in keys:
            ptm_to_kinases.setdefault(key, [])
            if canonical not in ptm_to_kinases[key]:
                ptm_to_kinases[key].append(canonical)

    suffix = "_phospho" if order["ptm_type"] == "phosphorylation" else "_ubi"
    timeseries: Dict[str, Dict[str, float]] = {}
    path = outputs_root / order["order_code"] / f"ptm_vector_data_normalized{suffix}.tsv"
    with open(path, "r", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            gene = row.get("Gene.Name", "") or ""
            position = str(row.get("PTM_Position", "") or "")
            condition = row.get("Condition", "") or ""
            if not gene or not position or not condition:
                continue
            raw = row.get("PTM_Relative_Log2FC", "")
            try:
                value = float(raw) if raw else 0.0
            except ValueError:
                value = 0.0
            timeseries.setdefault(f"{gene.upper()}_{position.upper()}", {})[condition] = value
    return modules, timeseries, ptm_to_kinases, conditions


def compare(baseline: Mapping[str, Any], current: Mapping[str, Any]) -> List[str]:
    problems: List[str] = []
    if set(baseline) != set(current):
        problems.append(
            f"kinase set differs: only-baseline={sorted(set(baseline) - set(current))[:5]}"
            f" only-current={sorted(set(current) - set(baseline))[:5]}"
        )
    for canonical in sorted(set(baseline) & set(current)):
        before, after = baseline[canonical], current[canonical]
        added = set(after) - set(before)
        if added - NEW_KINASE_KEYS:
            problems.append(f"{canonical}: unexpected new keys {sorted(added - NEW_KINASE_KEYS)}")
        for key in before:
            if key == "contribution_details":
                continue
            old_value, new_value = before[key], after.get(key)
            if isinstance(old_value, Mapping) and isinstance(new_value, Mapping):
                # 중첩 dict 는 키별로 비교한다.  통째로 비교하면 선언된 키 추가가
                # 값 변경처럼 보여서 additive 검증이 거짓 실패한다.
                allowed = NEW_NESTED_KEYS.get(key, set())
                unexpected = (set(new_value) - set(old_value)) - allowed
                if unexpected:
                    problems.append(f"{canonical}.{key}: unexpected new keys {sorted(unexpected)}")
                for nested in old_value:
                    if old_value[nested] != new_value.get(nested):
                        problems.append(
                            f"{canonical}.{key}.{nested}:"
                            f" {old_value[nested]!r} -> {new_value.get(nested)!r}"
                        )
                continue
            if old_value != new_value:
                problems.append(f"{canonical}.{key}: {old_value!r} -> {new_value!r}")
        before_details = before.get("contribution_details") or []
        after_details = after.get("contribution_details") or []
        if len(before_details) != len(after_details):
            problems.append(
                f"{canonical}.contribution_details length"
                f" {len(before_details)} -> {len(after_details)}"
            )
            continue
        for position, (old, new) in enumerate(zip(before_details, after_details)):
            extra = set(new) - set(old)
            if extra - NEW_DETAIL_KEYS:
                problems.append(
                    f"{canonical}.contribution_details[{position}]:"
                    f" unexpected new keys {sorted(extra - NEW_DETAIL_KEYS)}"
                )
            for key in old:
                if old[key] != new.get(key):
                    problems.append(
                        f"{canonical}.contribution_details[{position}].{key}:"
                        f" {old[key]!r} -> {new.get(key)!r}"
                    )
    return problems


def summarize_resolution(scores: Mapping[str, Any]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for payload in scores.values():
        for detail in payload.get("contribution_details") or []:
            label = str(detail.get("resolution", "absent"))
            counts[label] = counts.get(label, 0) + 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--order-ids", default="36")
    parser.add_argument("--outputs-root", default="/app/data/outputs")
    parser.add_argument("--snapshot", default=BASELINE_SNAPSHOT)
    args = parser.parse_args()

    from app.services import temporal_kinase_scoring as current_module

    baseline_module = load_snapshot(args.snapshot)
    outputs_root = Path(args.outputs_root)

    order_ids = [int(token) for token in args.order_ids.split(",") if token.strip()]
    orders = asyncio.run(load_orders(order_ids))

    total_problems = 0
    for order in orders:
        modules, timeseries, ptm_to_kinases, conditions = rebuild_inputs(order, outputs_root)
        print(f"\norder {order['id']} | {order['order_code']}")
        print(f"  kinases={len(modules)} sites={len(ptm_to_kinases)} conditions={conditions}")

        baseline_scores = baseline_module.compute_weighted_kinase_scores(
            modules, timeseries, ptm_to_kinases, conditions
        )
        current_scores = current_module.compute_weighted_kinase_scores(
            modules, timeseries, ptm_to_kinases, conditions
        )

        problems = compare(baseline_scores, current_scores)
        total_problems += len(problems)
        if problems:
            print(f"  MISMATCHES: {len(problems)}")
            for line in problems[:10]:
                print(f"    {line}")
        else:
            print("  all pre-existing fields identical")

        print(f"  resolution labels: {summarize_resolution(current_scores)}")
        annotated = [
            payload["tmm_identifiability"]
            for payload in current_scores.values()
            if "tmm_identifiability" in payload
        ]
        print(
            f"  kinases annotated: {len(annotated)}/{len(current_scores)}"
            f" | unresolved_shared total={sum(a['n_unresolved_shared'] for a in annotated)}"
            f" | unsupported total={sum(a['n_unsupported'] for a in annotated)}"
            f" | resolved total={sum(a['n_resolved'] for a in annotated)}"
        )

    print(f"\ntotal mismatches: {total_problems}")
    return 0 if total_problems == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
