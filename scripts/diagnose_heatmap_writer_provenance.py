"""오더 48 후보 축소(87 → 29)의 원인 규명과 감사 표의 writer 혼합 영향 정량화.

구현 대상: docs/chapter2_audit_protocol_v1.md §8 (미결 1번), §4 (drift 관찰),
          `ptm_shared/tmm_audit.py::classify_heatmap_writer`
사전등록: **탐색적.** 이 진단은 감사 결과를 본 뒤에 착수했다. 사전등록된 임계가 없으며
          §3 의 공표 수치를 갱신하지 않는다 — 동결 fixture 재생값은 그대로다.
해석 한계: 두 writer 를 **구별**하지만 어느 쪽이 옳은지 말하지 않는다. 후보가 많은 쪽이 더
          정확한 것이 아니다(§4.1: 접미사 변종 정리 후 중복 열 비율이 91.0% → 95.9% 로
          오히려 올랐다). 2026-08-18 상태는 이 진단으로도 **복원되지 않는다.**
          writer 별 부분 통합은 오더 수가 3 대 3 이고 site 수가 크게 다르므로(오더 36 이
          endpoint 쪽을 지배) 두 부분 값의 차이를 writer 효과로만 귀속할 수 없다.
주장 금지: "endpoint writer 의 후보 집합이 진짜다".
          "writer 를 통일하면 식별성이 개선된다" — 식별성 병목은 §2 의 generic fallback
          프로파일이며 후보 수가 아니다.

정본 환경 (DB 조회 + 동결 fixture 재생):

    docker cp scripts/diagnose_heatmap_writer_provenance.py ptm-worker-preprocessing:/tmp/wp.py
    docker exec -i ptm-worker-preprocessing env PYTHONPATH=/app:/opt python /tmp/wp.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.path[:0] = ["/app", "/opt"]

from ptm_shared.tmm_audit import (  # noqa: E402
    HEATMAP_WRITER_ENDPOINT,
    HEATMAP_WRITER_PIPELINE,
    HEATMAP_WRITER_UNKNOWN,
    classify_heatmap_writer,
    combine,
    count_sub_pattern_candidates,
    replay_fixture_dir,
)

FIXTURE_DIR = Path("/app/tests/fixtures/tmm_audit_v1")
AUDITED_ORDERS = (28, 33, 36, 45, 47, 48)

POOLED_FIELDS = (
    "n_orders",
    "n_sites",
    "structurally_underdetermined_rate",
    "rank_one_design_rate",
    "explains_nothing_rate",
    "top1_in_ambiguity_set_rate",
    "top1_from_prior_rate",
    "equal_weight_fallback_rate",
)


def query_heatmaps(order_ids: Sequence[int]) -> Dict[int, Dict[str, Any]]:
    """DB 에서 각 오더의 heatmap 을 읽는다. **가변 production 상태이므로 읽기 전용이다.**"""
    from sqlalchemy import text

    from common.db_engine import get_engine

    placeholders = ", ".join(str(int(oid)) for oid in order_ids)
    engine = get_engine()
    rows: Dict[int, Dict[str, Any]] = {}
    with engine.connect() as connection:
        result = connection.execute(
            text(
                "SELECT id, order_code, kinase_activity_heatmap, updated_at "
                f"FROM orders WHERE id IN ({placeholders}) ORDER BY id"
            )
        )
        for order_id, order_code, heatmap, updated_at in result:
            payload = json.loads(heatmap) if isinstance(heatmap, str) else (heatmap or {})
            rows[int(order_id)] = {
                "order_code": order_code,
                "heatmap": payload,
                "updated_at": str(updated_at),
            }
    return rows


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-dir", default=str(FIXTURE_DIR))
    parser.add_argument("--output", default="")
    args = parser.parse_args(argv)

    rows = query_heatmaps(AUDITED_ORDERS)
    missing = [oid for oid in AUDITED_ORDERS if oid not in rows]
    if missing:
        print(f"FATAL: 오더 {missing} 의 heatmap 을 읽지 못했다", file=sys.stderr)
        return 2

    print("=" * 104)
    print("1. writer 판별 — 최상위 키로 코드 경로를 식별한다")
    print("=" * 104)
    print(f"  {'오더':<5} {'writer':<15} {'후보':>5} {'sub-pattern':>12} "
          f"{'일치':>5}  {'갱신 시각':<20}")
    per_order: Dict[str, Dict[str, Any]] = {}
    for order_id in AUDITED_ORDERS:
        row = rows[order_id]
        writer = classify_heatmap_writer(row["heatmap"])
        counts = count_sub_pattern_candidates(row["heatmap"].get("kinase_scores") or [])
        per_order[str(order_id)] = {
            "order_code": row["order_code"],
            "writer": writer,
            "updated_at": row["updated_at"],
            **counts,
        }
        print(f"  {order_id:<5} {writer:<15} {counts['n_candidates']:>5} "
              f"{counts['n_sub_pattern_by_name']:>12} "
              f"{'예' if counts['flag_and_name_agree'] else '아니오':>5}  {row['updated_at']:<20}")

    endpoint_orders = [
        oid for oid in AUDITED_ORDERS
        if per_order[str(oid)]["writer"] == HEATMAP_WRITER_ENDPOINT
    ]
    pipeline_orders = [
        oid for oid in AUDITED_ORDERS
        if per_order[str(oid)]["writer"] == HEATMAP_WRITER_PIPELINE
    ]
    unknown_orders = [
        oid for oid in AUDITED_ORDERS
        if per_order[str(oid)]["writer"] == HEATMAP_WRITER_UNKNOWN
    ]

    # writer 와 sub-pattern 후보 유무가 일치하는가. 일치하면 인과 설명이 완결된다.
    separation_holds = all(
        per_order[str(oid)]["n_sub_pattern_by_name"] > 0 for oid in endpoint_orders
    ) and all(
        per_order[str(oid)]["n_sub_pattern_by_name"] == 0 for oid in pipeline_orders
    )
    print(f"\n  endpoint writer : 오더 {endpoint_orders}")
    print(f"  pipeline writer : 오더 {pipeline_orders}")
    if unknown_orders:
        print(f"  판별 불가       : 오더 {unknown_orders}")
    print(f"\n  sub-pattern 후보 유무가 writer 와 **완전히 일치**: "
          f"{'예' if separation_holds else '아니오'}")
    print("  → 일치하면 '오더 48 후보 87→29' 는 writer 교체로 설명되며 반례가 없다")
    print("  → 후보가 많은 쪽이 옳다는 뜻은 아니다 (§4.1: 변종 정리 후 중복 열이 오히려 늘었다)")

    # ---- 2. 감사 표가 두 어휘를 섞은 영향 ---------------------------------
    print("\n" + "=" * 104)
    print("2. 동결 fixture 재생을 writer 로 층화 — 공표된 통합 표가 무엇을 섞고 있는가")
    print("=" * 104)
    reports, pooled = replay_fixture_dir(Path(args.fixture_dir))
    by_id = {int(report["order_id"]): report for report in reports}
    strata = {
        "pooled_all": list(AUDITED_ORDERS),
        HEATMAP_WRITER_ENDPOINT: endpoint_orders,
        HEATMAP_WRITER_PIPELINE: pipeline_orders,
    }
    stratified: Dict[str, Any] = {}
    print(f"  {'층':<16} {'오더':>4} {'site':>6} {'구조적 미결정':>13} {'rank-1':>8} "
          f"{'설명 없음':>10} {'prior 유래':>11} {'균등 fallback':>13}")
    for name, order_ids in strata.items():
        subset = [by_id[oid] for oid in order_ids if oid in by_id]
        if not subset:
            continue
        summary = combine(subset)
        stratified[name] = {field: summary.get(field) for field in POOLED_FIELDS}
        stratified[name]["order_ids"] = list(order_ids)
        stratified[name]["verdicts"] = summary.get("verdicts")
        stratified[name]["attribution_quantity_reduction"] = (
            summary.get("attribution", {}).get("quantity_reduction")
        )
        print(f"  {name:<16} {summary['n_orders']:>4} {summary['n_sites']:>6} "
              f"{_fmt(summary['structurally_underdetermined_rate']):>13} "
              f"{_fmt(summary['rank_one_design_rate']):>8} "
              f"{_fmt(summary['explains_nothing_rate']):>10} "
              f"{_fmt(summary['top1_from_prior_rate']):>11} "
              f"{_fmt(summary['equal_weight_fallback_rate']):>13}")

    # 재생이 공표값을 그대로 재현하는지 확인한다. 층화 이전의 무결성 검사다.
    frozen = json.loads((Path(args.fixture_dir) / "pooled_summary.json").read_text("utf-8"))
    reproduced = all(
        _close(pooled.get(field), frozen.get(field)) for field in POOLED_FIELDS
    )
    print(f"\n  동결 pooled_summary.json 재현: {'예' if reproduced else '아니오'}")
    if not reproduced:
        print("  ** 재현되지 않으면 아래 층화 값도 신뢰할 수 없다 **")

    print("\n  두 층의 차이를 writer 효과로만 귀속하지 않는다 — 오더 36(907 site)이 endpoint")
    print("  층을 지배하고 두 층의 실험·종·조건 수가 모두 다르다. 이것은 **교란된 대조**다.")

    # ---- 2b. 오더별 표 — pooling 이 무엇을 지배하는가 ----------------------
    print("\n" + "=" * 104)
    print("2b. 오더별 값. `combine` 의 docstring 이 경고한 pooling 지배를 수치로 확인한다")
    print("=" * 104)
    print(f"  {'오더':<5} {'writer':<15} {'site':>5} {'몫':>6} {'구조적 미결정':>13} "
          f"{'rank-1':>8} {'설명 없음':>10} {'prior 유래':>11} {'균등 fallback':>13}")
    total_sites = sum(len(report["sites"]) for report in reports)
    by_order: Dict[str, Any] = {}
    for order_id in AUDITED_ORDERS:
        if order_id not in by_id:
            continue
        summary = combine([by_id[order_id]])
        share = summary["n_sites"] / total_sites if total_sites else 0.0
        by_order[str(order_id)] = {
            "writer": per_order[str(order_id)]["writer"],
            "site_share_of_pool": round(share, 6),
            **{field: summary.get(field) for field in POOLED_FIELDS},
        }
        print(f"  {order_id:<5} {per_order[str(order_id)]['writer']:<15} "
              f"{summary['n_sites']:>5} {share:>6.1%} "
              f"{_fmt(summary['structurally_underdetermined_rate']):>13} "
              f"{_fmt(summary['rank_one_design_rate']):>8} "
              f"{_fmt(summary['explains_nothing_rate']):>10} "
              f"{_fmt(summary['top1_from_prior_rate']):>11} "
              f"{_fmt(summary['equal_weight_fallback_rate']):>13}")
    # 어떤 공표 비율이 pooling 에 강건한지 층화로 판별한다. 단정하지 않고 범위를 계산한다.
    rate_fields = [field for field in POOLED_FIELDS if field.endswith("_rate")]
    ranges: Dict[str, Any] = {}
    print(f"\n  {'공표 비율':<32} {'통합':>7} {'오더별 최소':>11} {'오더별 최대':>11} {'폭':>7}")
    for field in rate_fields:
        values = [
            float(entry[field]) for entry in by_order.values() if entry.get(field) is not None
        ]
        if not values:
            continue
        low, high = min(values), max(values)
        ranges[field] = {
            "pooled": pooled.get(field),
            "per_order_min": round(low, 6),
            "per_order_max": round(high, 6),
            "spread": round(high - low, 6),
        }
        print(f"  {field:<32} {_fmt(pooled.get(field)):>7} {low:>11.4f} {high:>11.4f} "
              f"{high - low:>7.4f}")
    dominant = max(by_order.items(), key=lambda item: item[1]["site_share_of_pool"])
    print(f"\n  지배 오더 = {dominant[0]} (site 몫 {dominant[1]['site_share_of_pool']:.1%})")
    print("  폭이 큰 비율은 통합값을 일반 성질로 읽을 수 없다 — 지배 오더의 성질이다")
    print("  폭이 작은 비율만 오더에 걸쳐 일반화된다. 어느 것이 그런지는 위 표가 정한다")

    # ---- 3. 짝지은 준대조 — 오더 47 대 48 ---------------------------------
    print("\n" + "=" * 104)
    print("3. 짝지은 준대조 — 오더 47(WithoutCu) 대 48(Cu). 같은 실험의 두 arm 이 writer 가 갈렸다")
    print("=" * 104)
    matched: Dict[str, Any] = {}
    if 47 in by_id and 48 in by_id:
        print(f"  {'오더':<5} {'writer':<15} {'site':>5} {'구조적 미결정':>13} {'rank-1':>8} "
              f"{'설명 없음':>10} {'prior 유래':>11} {'균등 fallback':>13}")
        for order_id in (47, 48):
            summary = combine([by_id[order_id]])
            matched[str(order_id)] = {
                "writer": per_order[str(order_id)]["writer"],
                "n_candidates": per_order[str(order_id)]["n_candidates"],
                "n_sub_pattern": per_order[str(order_id)]["n_sub_pattern_by_name"],
                **{field: summary.get(field) for field in POOLED_FIELDS},
            }
            print(f"  {order_id:<5} {per_order[str(order_id)]['writer']:<15} "
                  f"{summary['n_sites']:>5} "
                  f"{_fmt(summary['structurally_underdetermined_rate']):>13} "
                  f"{_fmt(summary['rank_one_design_rate']):>8} "
                  f"{_fmt(summary['explains_nothing_rate']):>10} "
                  f"{_fmt(summary['top1_from_prior_rate']):>11} "
                  f"{_fmt(summary['equal_weight_fallback_rate']):>13}")
        print("\n  같은 세포·같은 5 시점·Cu 유무만 다른 두 arm 이다. 남은 교란은 **처리 자체**이며")
        print("  writer 효과와 Cu 효과가 이 대조에서도 분리되지 않는다. n = 2 이므로 검정하지 않는다.")
    else:
        print("  오더 47 또는 48 의 fixture 가 없어 대조를 만들 수 없다")

    results = {
        "diagnosis": "heatmap_writer_provenance",
        "declaration": "docs/chapter2_audit_protocol_v1.md §4.3",
        "preregistered": False,
        "judgement": "none_by_design",
        "per_order": per_order,
        "endpoint_orders": endpoint_orders,
        "pipeline_orders": pipeline_orders,
        "unknown_orders": unknown_orders,
        "writer_explains_sub_pattern_presence": separation_holds,
        "frozen_pooled_reproduced": reproduced,
        "stratified": stratified,
        "by_order": by_order,
        "per_order_ranges": ranges,
        "matched_pair_47_vs_48": matched,
    }
    payload = json.dumps(results, ensure_ascii=False, default=str)
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
        print(f"\n산출 기록: {args.output}")
    else:
        print("\n" + payload)
    return 0


def _close(left: Any, right: Any, tolerance: float = 1e-12) -> bool:
    if left is None or right is None:
        return left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return abs(float(left) - float(right)) <= tolerance
    return left == right


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.4f}"


if __name__ == "__main__":
    raise SystemExit(main())
