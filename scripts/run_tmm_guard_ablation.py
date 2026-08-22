"""Quantify what the attribution guard withholds, from the frozen audit fixture.

구현 대상: docs/chapter2_audit_protocol_v1.md §5 (guard ablation)
사전등록: 2026-08-21. 판정은 2026-08-18 동결된 ``attribution_supported``를 쓰고 새 임계를
          도입하지 않는다. ``fc_threshold``는 production 기본값 0.3이며 두 arm 동일.
해석 한계: 공유 site 만 다룬다. exclusive substrate 는 guard 대상이 아니므로 집계 밖이다.
          q-value 가 fixture 에 없어 통과 판정은 ``|fc| >= fc_threshold`` 만 쓴다.
주장 금지: 보류량을 정확도 개선폭으로 서술하지 않는다. 발표 범위의 축소다.

DB 를 읽지 않는다. 동결 fixture 만 쓰므로 언제든 같은 값이 나온다.

    docker exec ptm-worker-preprocessing sh -c 'cd /app && \
        env PYTHONPATH=/app:/opt python scripts/run_tmm_guard_ablation.py'
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

sys.path[:0] = ["/app", "/opt"]

from ptm_shared.tmm_audit import (  # noqa: E402
    guard_ablation,
    solver_provenance,
    thaw_site_inputs,
)

DEFAULT_FIXTURE_DIR = "tests/fixtures/tmm_audit_v1"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-dir", default=DEFAULT_FIXTURE_DIR)
    parser.add_argument("--fc-threshold", type=float, default=0.3)
    parser.add_argument("--output", default=None, help="집계 결과를 쓸 JSON 경로")
    args = parser.parse_args()

    fixture_dir = Path(args.fixture_dir)
    manifest = json.loads((fixture_dir / "manifest.json").read_text(encoding="utf-8"))

    pooled_inputs = []
    per_order: Dict[int, Any] = {}
    for entry in manifest["orders"]:
        fixture = json.loads((fixture_dir / entry["file"]).read_text(encoding="utf-8"))
        site_inputs = thaw_site_inputs(fixture)
        pooled_inputs.extend(site_inputs)
        per_order[int(entry["order_id"])] = (
            entry["order_code"],
            guard_ablation(site_inputs, fc_threshold=args.fc_threshold),
        )

    print("=== per order ===")
    header = f"  {'id':>3}  {'order':<34} {'sites':>5} {'withheld':>9} {'rate':>7} {'lose-all':>9}"
    print(header)
    for order_id, (code, ablation) in sorted(per_order.items()):
        rate = ablation["withheld_site_rate"] or 0.0
        print(
            f"  {order_id:>3}  {code[:34]:<34}"
            f" {ablation['n_shared_sites']:>5}"
            f" {ablation['n_withheld_sites']:>9}"
            f" {100.0 * rate:>6.1f}%"
            f" {ablation['n_kinases_losing_all_shared_evidence']:>4}"
            f"/{ablation['n_kinases']:<4}"
        )

    pooled = guard_ablation(pooled_inputs, fc_threshold=args.fc_threshold)
    print("\n=== pooled ===")
    for key in (
        "n_shared_sites",
        "n_withheld_sites",
        "withheld_site_rate",
        "n_published_pairs",
        "n_withheld_pairs",
        "withheld_pair_rate",
        "n_kinases",
        "n_kinases_losing_all_shared_evidence",
        "n_kinases_losing_majority_shared_evidence",
    ):
        print(f"  {key}: {pooled[key]}")
    losing = pooled["kinases_losing_all_shared_evidence"]
    print(f"  kinases losing all shared evidence ({len(losing)}): {losing[:16]}")

    group_share = pooled["group_share"]
    print("\n=== group_share arm (§5.5) — 발표량만 바뀐다. 점수는 strict 와 동일 ===")
    for key in (
        "n_withheld_pairs",
        "withheld_pair_rate",
        "n_published_per_kinase_ratios",
        "n_estimable_group_shares",
        "n_ambiguous_groups",
        "published_quantity_reduction",
        "n_kinases_without_any_separable_site",
    ):
        print(f"  {key}: {group_share[key]}")

    print("\n=== per order (group_share) ===")
    print(f"  {'id':>3}  {'order':<34} {'pairs':>6} {'withheld':>9} {'groups':>7} {'감소':>7}")
    for order_id, (code, ablation) in sorted(per_order.items()):
        arm = ablation["group_share"]
        reduction = arm["published_quantity_reduction"] or 0.0
        print(
            f"  {order_id:>3}  {code[:34]:<34}"
            f" {ablation['n_published_pairs']:>6}"
            f" {arm['n_withheld_pairs']:>9}"
            f" {arm['n_estimable_group_shares']:>7}"
            f" {100.0 * reduction:>6.1f}%"
        )

    print(f"\n  determinism: {json.dumps(solver_provenance())}")

    if args.output:
        payload = {
            "determinism": solver_provenance(),
            "fixture_dir": str(fixture_dir),
            "pooled": pooled,
            "per_order": {
                str(order_id): {"order_code": code, **ablation}
                for order_id, (code, ablation) in per_order.items()
            },
        }
        Path(args.output).write_text(json.dumps(payload, indent=1), encoding="utf-8")
        print(f"\nWritten to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
