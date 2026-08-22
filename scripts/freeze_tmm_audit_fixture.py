"""Freeze the exact inputs the TMM identifiability audit consumed.

구현 대상: docs/chapter2_audit_protocol_v1.md §3 (reproduce)
사전등록: 2026-08-21. 감사 판정 기준은 2026-08-18에 동결되었고 이 스크립트는 그것을
          바꾸지 않는다. 새 수치를 만들지 않고 기존 수치의 입력을 아카이브한다.
해석 한계: 동결되는 것은 감사가 본 입력이다. 그 입력이 생물학적으로 옳은지는 다루지
          않으며, 재생이 성공해도 감사의 결론이 참임을 뜻하지 않는다. 재생이 보장하는
          것은 "표가 어디서 나왔는지 추적 가능하다"는 것뿐이다.
주장 금지: 재현 가능성을 정확도나 타당성의 근거로 서술하지 않는다.

왜 필요한가
-----------
공표된 감사 표(1,310 site, identifiable 1.1%)는 살아 있는 MySQL `orders` 행과
gitignore된 `data/outputs/**` TSV에서 나왔다. 둘 다 버전 관리 대상이 아니므로 그 표는
재생성 불가능했다. 학위논문 표가 재생성 불가능하면 방어할 수 없다.

동결 후에는 fixture 재생이 유일한 권위 있는 수치다(`pooled_summary.json`). 이전 산출물이
있으면 `--reference-summary`로 넘겨 표류를 진단할 수 있고, `--require-match`를 함께 주면
불일치를 실패로 처리한다.

2026-08-21 첫 동결에서 확인된 표류
----------------------------------
2026-08-18 공표값과 대조한 결과 **오더 48이 재현되지 않았다**. `orders.kinase_activity_heatmap`
은 가변 production 상태이고, 2026-08-20 06:19 재실행이 후보 집합을 덮어썼다
(kinase 87→29, module site 235→71, shared site 199→49). 조건 목록과 ptm_type은 동일하다.
사라진 후보는 `CSNK2_C1`…`CSNK2_C5`, `CAMK2_C0` 같은 클러스터 접미사 변종이다.

따라서 2026-08-18 표는 **원리적으로 복구 불가능**하다. 다만 결론은 유지되거나 강해진다
(identifiable 1.1%→0.7%, top-1 prior 유래 92.5%→94.1%, 오더 48 중복 열 91.0%→95.9%).
이 사건 자체가 「감사 대상이 버전 관리되지 않는 가변 상태였다」는 Chapter 2의 관찰이며,
동결이 필요한 이유의 실증이다. 상세는 docs/chapter2_audit_protocol_v1.md §4.

실행(설계행렬 조립과 참조 kinase 표가 있는 API 컨테이너 안에서):

    docker exec -i ptm-api-server env PYTHONPATH=/app:/opt python - \
        --order-ids 48,47,45,36,33,28 < scripts/freeze_tmm_audit_fixture.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

import numpy as np

sys.path[:0] = ["/app", "/opt"]

from ptm_shared.tmm_audit import (  # noqa: E402
    DEFAULT_BOOTSTRAP,
    DEFAULT_RELATIVE_NOISE,
    FIXTURE_SCHEMA,
    SiteInputs,
    audit_sites,
    build_design,
    build_kinase_modules,
    combine,
    fixture_digest,
    freeze_site_inputs,
    load_timeseries,
    replay_order,
    solver_provenance,
)
from ptm_shared.tmm_identifiability import (  # noqa: E402
    normalized_ratios,
    solve_nnls,
)

DEFAULT_FIXTURE_DIR = "/app/data/outputs/_diagnostics/tmm_audit_fixture_v1"
SUPERSEDED_SUMMARY_2026_08_18 = (
    "/app/data/outputs/_diagnostics/tmm_identifiability/_pooled_summary.json"
)
"""2026-08-18 산출물. 오더 48 입력이 그 뒤 덮어써졌으므로 **복구 불가능하며 초과됨**.

`--reference-summary`에 넘기면 표류 진단용으로만 쓰인다. 논문 수치의 출처로 쓰지 않는다.
"""


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


def freeze_order(
    order: Mapping[str, Any],
    *,
    output_root: Path,
    relative_noise: float,
    n_bootstrap: int,
    max_sites: int,
    seed: int,
) -> Optional[Dict[str, Any]]:
    """한 오더의 감사 입력을 동결하고 배포 추정기와의 동일성을 함께 기록한다.

    site 열거 순서와 인덱스는 ``diagnose_tmm_identifiability.py``와 동일해야 한다.
    site별 seed가 ``seed + index``이므로 순서가 어긋나면 부트스트랩이 달라진다.
    """
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

    all_shared = [key for key, kinases in ptm_to_kinases.items() if len(kinases) >= 2]
    shared_sites = sorted(all_shared)
    truncated_sites = False
    if max_sites and len(shared_sites) > max_sites:
        shared_sites = shared_sites[:max_sites]
        truncated_sites = True

    site_inputs: List[SiteInputs] = []
    max_ratio_deviation = 0.0
    for index, site_key in enumerate(shared_sites):
        candidates = ptm_to_kinases[site_key]
        design, names, prior_flags = build_design(candidates, profiles, conditions)
        series = timeseries.get(site_key, {})
        target = np.asarray([series.get(condition, 0.0) for condition in conditions], dtype=float)
        seen = observed.get(site_key, set())
        mask = [condition in seen for condition in conditions]
        site_inputs.append(
            SiteInputs(
                site_index=index,
                site_key=site_key,
                candidates=tuple(names),
                design=design,
                prior_flags=tuple(prior_flags),
                target=target,
                observed_mask=tuple(mask),
            )
        )

        # 동결 시점의 동일성 증거: 재구성한 행렬의 해가 배포 solver 출력과 같은가.
        # 재생 경로는 이 값을 다시 계산할 수 없으므로(라이브 모듈 필요) 기록만 한다.
        if design.shape[1] == 0:
            continue
        production = deconvolve_shared_ptm(
            site_key, list(candidates), profiles, timeseries, conditions
        )
        replicated = normalized_ratios(solve_nnls(design, target)[0])
        for position, name in enumerate(names):
            deviation = abs(float(production.get(name, 0.0)) - float(replicated[position]))
            max_ratio_deviation = max(max_ratio_deviation, deviation)

    frozen = freeze_site_inputs(site_inputs)
    fixture: Dict[str, Any] = {
        "schema": FIXTURE_SCHEMA,
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
        "n_shared_sites": len(all_shared),
        "site_list_truncated": truncated_sites,
        "n_kinases_with_truncated_substrate_list": n_truncated,
        "production_ratio_max_deviation": max_ratio_deviation,
        "assumptions": {
            "relative_noise": relative_noise,
            "n_bootstrap": n_bootstrap,
            "seed": seed,
        },
        "columns": frozen["columns"],
        "sites": frozen["sites"],
    }
    print(
        f"  order {order['id']:>3} | {order['order_code']}"
        f" | sites {len(site_inputs)} | distinct columns {len(frozen['columns'])}"
        f" | production deviation {max_ratio_deviation:.2e}"
    )
    return fixture


def compare(replayed: Mapping[str, Any], published: Mapping[str, Any]) -> List[str]:
    """재생 통합 표를 참조 산출물과 대조해 어긋난 항목을 사람이 읽을 형태로 반환한다.

    구현 대상: docs/chapter2_audit_protocol_v1.md §4 (표류 진단)
    해석 한계: 불일치는 "재생이 틀렸다"는 뜻일 수도 있고 "감사 입력이 그 사이에 바뀌었다"는
              뜻일 수도 있다. 둘을 구별하는 것은 이 함수가 아니라 오더별 메타데이터
              대조(n_kinases, n_shared_sites)다.
    """
    problems: List[str] = []

    def check(label: str, left: Any, right: Any) -> None:
        if isinstance(left, float) and isinstance(right, float):
            if not np.isclose(left, right, rtol=0.0, atol=1e-12):
                problems.append(f"{label}: replay={left!r} published={right!r}")
        elif left != right:
            problems.append(f"{label}: replay={left!r} published={right!r}")

    for key in ("n_orders", "n_sites"):
        check(key, replayed.get(key), published.get(key))
    for key in (
        "structurally_underdetermined_rate",
        "rank_one_design_rate",
        "explains_nothing_rate",
        "top1_in_ambiguity_set_rate",
        "top1_from_prior_rate",
        "equal_weight_fallback_rate",
    ):
        check(key, replayed.get(key), published.get(key))
    for label in set(replayed.get("verdicts", {})) | set(published.get("verdicts", {})):
        check(f"verdicts.{label}", replayed["verdicts"].get(label), published["verdicts"].get(label))

    left_attr = replayed.get("attribution") or {}
    right_attr = published.get("attribution") or {}
    for key in (
        "n_sites",
        "per_kinase_ratios_published",
        "estimable_group_shares",
        "n_supported",
    ):
        check(f"attribution.{key}", left_attr.get(key), right_attr.get(key))
    for label in set(left_attr.get("reduced_verdicts", {})) | set(
        right_attr.get("reduced_verdicts", {})
    ):
        check(
            f"attribution.reduced_verdicts.{label}",
            left_attr.get("reduced_verdicts", {}).get(label),
            right_attr.get("reduced_verdicts", {}).get(label),
        )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--order-ids", default="48,47,45,36,33,28")
    parser.add_argument("--relative-noise", type=float, default=DEFAULT_RELATIVE_NOISE)
    parser.add_argument("--bootstrap", type=int, default=DEFAULT_BOOTSTRAP)
    parser.add_argument("--max-sites", type=int, default=4000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--outputs-root", default="/app/data/outputs")
    parser.add_argument("--fixture-dir", default=DEFAULT_FIXTURE_DIR)
    parser.add_argument(
        "--reference-summary",
        default=None,
        help="이전 산출물 경로. 주면 표류를 진단해 drift_vs_reference.json 으로 기록한다."
        f" 2026-08-18 산출물은 {SUPERSEDED_SUMMARY_2026_08_18}",
    )
    parser.add_argument(
        "--require-match",
        action="store_true",
        help="참조와 불일치하면 실패로 처리한다. 표류가 이미 설명된 경우에는 쓰지 않는다.",
    )
    args = parser.parse_args()

    order_ids = [int(token) for token in args.order_ids.split(",") if token.strip()]
    orders = asyncio.run(load_orders(order_ids))
    if not orders:
        print("No orders with stored kinase results were found.")
        return 1

    fixture_dir = Path(args.fixture_dir)
    fixture_dir.mkdir(parents=True, exist_ok=True)

    print(f"Freezing {len(orders)} order(s); relative_noise={args.relative_noise}")
    entries: List[Dict[str, Any]] = []
    reports: List[Dict[str, Any]] = []
    for order in orders:
        fixture = freeze_order(
            order,
            output_root=Path(args.outputs_root),
            relative_noise=args.relative_noise,
            n_bootstrap=args.bootstrap,
            max_sites=args.max_sites,
            seed=args.seed,
        )
        if fixture is None:
            continue
        name = f"order_{fixture['order_id']:03d}_{fixture['order_code']}.json"
        path = fixture_dir / name
        path.write_text(json.dumps(fixture, indent=1, sort_keys=False), encoding="utf-8")
        entries.append(
            {
                "order_id": fixture["order_id"],
                "order_code": fixture["order_code"],
                "file": name,
                "sha256": fixture_digest(path),
                "n_sites": len(fixture["sites"]),
                "n_distinct_columns": len(fixture["columns"]),
                "production_ratio_max_deviation": fixture["production_ratio_max_deviation"],
            }
        )
        reports.append(replay_order(fixture))

    if not entries:
        print("\nNo order produced a freezable design matrix.")
        return 1

    replayed = combine(reports)
    manifest = {
        "schema": FIXTURE_SCHEMA,
        "frozen_at": "2026-08-21",
        "source": "live MySQL orders + data/outputs TSV (neither is version controlled)",
        "audit_published_at": "2026-08-18",
        "assumptions": {
            "relative_noise": args.relative_noise,
            "n_bootstrap": args.bootstrap,
            "seed": args.seed,
            "max_sites": args.max_sites,
        },
        "determinism": solver_provenance(),
        "orders": entries,
    }
    (fixture_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=1), encoding="utf-8"
    )
    # 동결 이후 논문에 실리는 유일한 권위 있는 수치. fixture 만으로 재생 가능하다.
    (fixture_dir / "pooled_summary.json").write_text(
        json.dumps(replayed, indent=1), encoding="utf-8"
    )
    print(
        f"\n=== pooled from fixture ==="
        f"\n  orders {replayed['n_orders']} | sites {replayed['n_sites']}"
        f"\n  identifiable {replayed['verdict_fractions'].get('identifiable', 0.0):.4f}"
        f" | equal-weight fallback {replayed.get('equal_weight_fallback_rate'):.4f}"
        f" | top-1 from prior {replayed.get('top1_from_prior_rate'):.4f}"
    )

    exit_code = 0
    if args.reference_summary:
        reference_path = Path(args.reference_summary)
        if not reference_path.exists():
            print(f"\n[warn] reference summary missing at {reference_path}")
            return 1
        reference = json.loads(reference_path.read_text(encoding="utf-8"))
        problems = compare(replayed, reference)
        (fixture_dir / "drift_vs_reference.json").write_text(
            json.dumps(
                {
                    "reference": str(reference_path),
                    "n_mismatches": len(problems),
                    "mismatches": problems,
                },
                indent=1,
            ),
            encoding="utf-8",
        )
        print(f"\n=== replay vs reference ({reference_path.name}) ===")
        if problems:
            for line in problems:
                print(f"  DRIFT {line}")
            print(
                f"\n{len(problems)} field(s) drifted."
                " 오더별 n_kinases·n_shared_sites 를 대조해 입력 변경인지 확인할 것."
            )
            if args.require_match:
                exit_code = 2
        else:
            print("  identical on every compared field")

    print(f"\nFixture written to {fixture_dir}")
    print(f"  determinism: {json.dumps(manifest['determinism'])}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
