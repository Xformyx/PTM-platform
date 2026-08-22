"""E2 (축소 수행) 와 E3b (합성 개입 양성 대조) — dictionary 개입에 대한 τ 반응.

구현 대상: docs/c1_prereg_v1.md §8.1 (개입 I1–I4), §8.2 (판정), §3.5.3 (E2 축소 사유),
          §2.1.4 (`d` 구성)
사전등록: 개입 목록과 판정은 2026-08-20 동결. E2 축소는 2026-08-22 확정(국소 KSA 라이브러리
          부재로 버전 교체 축 실행 불가). E3b 는 §6.6 에서 **탐색적**으로 지정되었다.
해석 한계: **허용 주장은 diagnostic sensitivity proof 뿐이다**(§8.2). 합성 rank 증강/감축 열은
          어떤 kinase 도 나타내지 않으며, τ 가 rank 를 따라 움직인다는 것은 진단이 기하에
          반응한다는 뜻일 뿐 귀속이 옳아졌다는 뜻이 아니다.
          E2 는 prior-free 한 축만 보므로 dictionary 조작 일반에 대한 민감도가 아니다(§3.5.3).
주장 금지: individual kinase accuracy proof, 귀속 정확도 개선(§8.2 명시). "prior 열을 빼면
          귀속이 좋아진다"고 쓰지 않는다 — 측정한 것은 τ 의 이동이며 정확도가 아니다.
          "E2 통과"라고 쓰지 않는다(§3.5.3).

정본 환경:

    docker exec -e PYTHONPATH=/app:/opt:/app/scripts -e PYTHONHASHSEED=0 ptm-api-server \
        python /app/scripts/run_c1_e2_e3b.py --order-ids 52 \
        --l3-fixture-dir /app/tests/fixtures/tmm_audit_v1 \
        --output /app/data/outputs/_diagnostics/c1_e1_v1/e2_e3b.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

sys.path[:0] = ["/app", "/opt", "/app/scripts"]

from ptm_shared.c1_inference import (  # noqa: E402
    E3B_SIGN_AGREEMENT_MIN,
    E3B_SIGN_TEST_ALPHA,
    exact_sign_test,
    provenance as inference_provenance,
    spearman,
)
from ptm_shared.c1_transmissibility import (  # noqa: E402
    ACTIVE_COEFFICIENT_FLOOR,
    active_columns,
    augment_rank,
    drop_prior_columns,
    merge_duplicate_columns,
    provenance as tau_provenance,
    quantile_summary,
    transmissibility,
    truncate_rank,
)
from ptm_shared.tmm_identifiability import _numerical_rank  # noqa: E402

RANK_STEPS = 3
"""I3/I4 의 rank 단계 수. docs/c1_prereg_v1.md §8.1 은 "단계적으로" 만 규정하고 수를 정하지 않았다.

여기서 3 으로 고정하는 이유: `T` 가 3–9 이므로 증강 여지(`T − rank`)와 감축 여지(`rank − 1`)가
대개 1–4 다. 3 단계면 Spearman 이 계산 가능한 최소 길이(4 점: 원본 + 3 단계)를 확보하면서
`T = 4` 오더에서도 포화하지 않는다. **결과를 보기 전에 정했고 이후 바꾸지 않는다.**
여지가 부족한 site 는 가능한 단계까지만 쓰고, 점이 3 개 미만이면 그 site 를 제외하고 계수한다.
"""

AUGMENT_SEED = 20260820
"""I3 합성 직교 열의 seed. §7.4 의 추론 seed 와 같은 상수를 쓴다(§7.3.1 의 이유와 동일)."""


def tau_act_of(design: np.ndarray, target: np.ndarray, direction: np.ndarray) -> Optional[float]:
    """개입된 설계에서 `τ_act` 를 다시 계산한다.

    구현 대상: docs/c1_prereg_v1.md §4.1
    해석 한계: 활성집합을 **개입 후 설계에서 다시 구한다.** 원본 활성집합을 재사용하면
              개입이 활성집합을 바꾸는 효과가 사라져 민감도가 과소평정된다.
    """
    if design.size == 0 or design.shape[1] == 0:
        return None
    active = active_columns(design, target)
    if active.size == 0:
        return 0.0
    return transmissibility(design[:, active], direction)


def rank_sweep(
    design: np.ndarray,
    target: np.ndarray,
    direction: np.ndarray,
    *,
    mode: str,
) -> List[Tuple[int, float]]:
    """rank 단계별 `(rank, τ_act)`. `mode` 는 `augment`(I3) 또는 `truncate`(I4)."""
    base_rank = _numerical_rank(design)
    points: List[Tuple[int, float]] = []
    base = tau_act_of(design, target, direction)
    if base is not None:
        points.append((base_rank, float(base)))

    for step in range(1, RANK_STEPS + 1):
        if mode == "augment":
            candidate = augment_rank(design, step, seed=AUGMENT_SEED)
        else:
            candidate = truncate_rank(design, base_rank - step)
        rank = _numerical_rank(candidate)
        if any(rank == existing for existing, _ in points):
            continue
        value = tau_act_of(candidate, target, direction)
        if value is None:
            continue
        points.append((rank, float(value)))
    return sorted(points)


def summarize_sign_test(
    correlations: Sequence[Optional[float]],
) -> Dict[str, Any]:
    """부호 일치 비율과 정확 이항 검정. docs/c1_prereg_v1.md §8.2."""
    usable = [value for value in correlations if value is not None and np.isfinite(value)]
    nonzero = [value for value in usable if abs(value) > 1e-12]
    n_positive = sum(1 for value in nonzero if value > 0)
    fraction = n_positive / len(nonzero) if nonzero else None
    p_value = exact_sign_test(n_positive, len(nonzero)) if nonzero else None
    meets = (
        fraction is not None
        and p_value is not None
        and fraction >= E3B_SIGN_AGREEMENT_MIN
        and p_value < E3B_SIGN_TEST_ALPHA
    )
    return {
        "n_sites_with_correlation": len(usable),
        "n_sites_nonzero": len(nonzero),
        "n_sites_positive": n_positive,
        "fraction_positive": fraction,
        "sign_test_p_two_sided": p_value,
        "meets_prereg_criterion_exploratory": meets,
        "criterion": (
            f"fraction >= {E3B_SIGN_AGREEMENT_MIN} and p < {E3B_SIGN_TEST_ALPHA} (§8.2)"
        ),
        "note": "E3b 는 탐색적이다 (§6.6). 이 판정은 C1 채택 여부를 바꾸지 않는다",
    }


def run_interventions(
    site_inputs: Sequence[Any],
    directions: Mapping[str, np.ndarray],
    strata: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """I1·I2(=E2 축소)·I3·I4 를 `S-EVAL` 에서 실행한다.

    해석 한계: 모집단은 `S-EVAL` 이다. `S-DEAD` 는 출력이 상수이므로 개입 반응을 재도
              `constant-output-by-construction` 의 재확인일 뿐이다(§7.5).
    """
    i1_delta: List[float] = []
    i1_n_merged: List[int] = []
    i2_delta: List[float] = []
    i2_dropped_all = 0
    i2_no_prior = 0
    i3_rho: List[Optional[float]] = []
    i4_rho: List[Optional[float]] = []
    i3_insufficient = 0
    i4_insufficient = 0
    per_site: List[Dict[str, Any]] = []

    for site in site_inputs:
        if strata.get(site.site_key, {}).get("stratum") != "S-EVAL":
            continue
        direction = directions.get(site.site_key)
        if direction is None:
            continue
        design = np.asarray(site.design, dtype=float)
        target = np.asarray(site.target, dtype=float)
        base = tau_act_of(design, target, direction)
        if base is None:
            continue

        merged, groups = merge_duplicate_columns(design)
        n_merged = int(design.shape[1] - merged.shape[1])
        merged_tau = tau_act_of(merged, target, direction)
        if merged_tau is not None:
            i1_delta.append(float(merged_tau - base))
            i1_n_merged.append(n_merged)

        prior_flags = list(site.prior_flags)
        if not any(prior_flags):
            i2_no_prior += 1
            prior_tau = None
        else:
            reduced, n_dropped = drop_prior_columns(design, prior_flags)
            if reduced.shape[1] == 0:
                i2_dropped_all += 1
                prior_tau = None
            else:
                prior_tau = tau_act_of(reduced, target, direction)
                if prior_tau is not None:
                    i2_delta.append(float(prior_tau - base))

        augment_points = rank_sweep(design, target, direction, mode="augment")
        truncate_points = rank_sweep(design, target, direction, mode="truncate")
        if len(augment_points) >= 3:
            i3_rho.append(
                spearman([r for r, _ in augment_points], [t for _, t in augment_points])
            )
        else:
            i3_insufficient += 1
        if len(truncate_points) >= 3:
            i4_rho.append(
                spearman([r for r, _ in truncate_points], [t for _, t in truncate_points])
            )
        else:
            i4_insufficient += 1

        per_site.append(
            {
                "site_key": site.site_key,
                "tau_act_base": float(base),
                "i1_n_columns_merged": n_merged,
                "i1_tau_act": None if merged_tau is None else float(merged_tau),
                "i2_prior_column_fraction": float(np.mean(prior_flags)) if prior_flags else 0.0,
                "i2_tau_act": None if prior_tau is None else float(prior_tau),
                "i3_points": augment_points,
                "i4_points": truncate_points,
            }
        )

    return {
        "n_s_eval_sites": len(per_site),
        "i1_duplicate_merge": {
            "delta_tau_act": quantile_summary(i1_delta),
            "n_sites_with_merge": sum(1 for value in i1_n_merged if value > 0),
            "n_columns_merged": quantile_summary([float(v) for v in i1_n_merged]),
        },
        "i2_prior_free_is_e2_reduced": {
            "delta_tau_act": quantile_summary(i2_delta),
            "n_sites_evaluated": len(i2_delta),
            "n_sites_without_prior_columns": i2_no_prior,
            "n_sites_losing_every_column": i2_dropped_all,
            "scope": "prior-free 축만. KSA 버전 교체 축은 실행 불가 (§3.5.3)",
        },
        "i3_rank_augmentation": {
            **summarize_sign_test(i3_rho),
            "n_sites_insufficient_steps": i3_insufficient,
            "prediction": "rank 증가 → τ_act 증가 (§8.2)",
        },
        "i4_rank_truncation": {
            **summarize_sign_test(i4_rho),
            "n_sites_insufficient_steps": i4_insufficient,
            "prediction": "rank 감축 → τ_act 감소 (§8.2)",
        },
        "sites": per_site,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--order-ids", default="52")
    parser.add_argument("--data-root", default="/app/data")
    parser.add_argument("--max-sites", type=int, default=4000)
    parser.add_argument("--l3-fixture-dir", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args(argv)

    from measure_c1_strata import (  # type: ignore
        assemble_site_inputs,
        classify_strata,
        strata_from_fixture,
    )
    from run_c1_e1_transmissibility import (  # type: ignore
        build_direction,
        fit_site_level_encoder,
        load_order,
    )

    output_root = Path(args.data_root) / "outputs"
    order_ids = [int(part) for part in str(args.order_ids).split(",") if part.strip()]

    print("=" * 100)
    print("E2 (축소) · E3b (합성 개입 양성 대조)")
    print("허용 주장은 diagnostic sensitivity proof 뿐이다 (c1_prereg_v1.md §8.2)")
    print("E2 는 prior-free 축만 본다 — KSA 버전 교체 축은 실행 불가 (§3.5.3)")
    print("=" * 100)

    payload: Dict[str, Any] = {
        "contract": "C1_E2_E3B_V1",
        "measured_at": "2026-08-22",
        "rank_steps": RANK_STEPS,
        "augment_seed": AUGMENT_SEED,
        "active_coefficient_floor": ACTIVE_COEFFICIENT_FLOOR,
        "tau_module": tau_provenance(),
        "inference": inference_provenance(),
        "orders": [],
    }
    pooled_i3: List[Optional[float]] = []
    pooled_i4: List[Optional[float]] = []
    pooled_i1: List[float] = []
    pooled_i2: List[float] = []
    pooled_sites = 0

    def handle(
        label: str,
        code: str,
        ptm_type: str,
        conditions: Sequence[str],
        site_inputs: Sequence[Any],
        strata: Mapping[str, Mapping[str, Any]],
    ) -> None:
        nonlocal pooled_sites
        suffix = "_phospho" if ptm_type == "phosphorylation" else "_ubi"
        vector = output_root / code / f"ptm_vector_data_normalized{suffix}.tsv"
        if not vector.exists():
            print(f"[skip] {label}: vector TSV 없음")
            return
        encoder = fit_site_level_encoder(vector)
        directions: Dict[str, np.ndarray] = {}
        for site in site_inputs:
            block = encoder["by_site"].get(site.site_key)
            if block is None:
                continue
            direction, _observed, _mismatch, _absent = build_direction(
                site, conditions, encoder["timepoints"], block
            )
            directions[site.site_key] = direction

        result = run_interventions(site_inputs, directions, strata)
        if result["n_s_eval_sites"] == 0:
            print(f"[skip] {label}: S-EVAL 0")
            return
        pooled_sites += result["n_s_eval_sites"]
        for site in result["sites"]:
            if site["i1_tau_act"] is not None:
                pooled_i1.append(site["i1_tau_act"] - site["tau_act_base"])
            if site["i2_tau_act"] is not None:
                pooled_i2.append(site["i2_tau_act"] - site["tau_act_base"])
            if len(site["i3_points"]) >= 3:
                pooled_i3.append(
                    spearman(
                        [r for r, _ in site["i3_points"]],
                        [t for _, t in site["i3_points"]],
                    )
                )
            if len(site["i4_points"]) >= 3:
                pooled_i4.append(
                    spearman(
                        [r for r, _ in site["i4_points"]],
                        [t for _, t in site["i4_points"]],
                    )
                )

        print("-" * 100)
        print(f"{label} | {code} | S-EVAL {result['n_s_eval_sites']}")
        i1 = result["i1_duplicate_merge"]
        i2 = result["i2_prior_free_is_e2_reduced"]
        print(
            f"  I1 중복 병합    Δτ_act p50 {i1['delta_tau_act']['p50']}"
            f" | 병합 발생 site {i1['n_sites_with_merge']}"
        )
        print(
            f"  I2 prior 제거   Δτ_act p50 {i2['delta_tau_act']['p50']}"
            f" | 평가 {i2['n_sites_evaluated']}"
            f" | prior 없음 {i2['n_sites_without_prior_columns']}"
            f" | 전열 소실 {i2['n_sites_losing_every_column']}"
        )
        for key in ("i3_rank_augmentation", "i4_rank_truncation"):
            block = result[key]
            print(
                f"  {key[:2].upper()} {block['prediction'][:22]:<24}"
                f" 부호 일치 {block['fraction_positive']}"
                f" ({block['n_sites_positive']}/{block['n_sites_nonzero']})"
                f" | p {block['sign_test_p_two_sided']}"
                f" | 기준 충족 {block['meets_prereg_criterion_exploratory']}"
                f" | 단계 부족 {block['n_sites_insufficient_steps']}"
            )
        payload["orders"].append({"label": label, "order_code": code, **result})

    for order_id in order_ids:
        order = asyncio.run(load_order(order_id))
        if order is None:
            print(f"[skip] order {order_id}: heatmap 없음")
            continue
        site_inputs, meta = assemble_site_inputs(
            order, output_root, max_sites=args.max_sites
        )
        handle(
            f"order {order_id} (live)",
            meta["order_code"],
            meta["ptm_type"],
            meta["conditions"],
            site_inputs,
            {record["site_key"]: record for record in classify_strata(site_inputs)},
        )

    if args.l3_fixture_dir:
        from ptm_shared.tmm_audit import FIXTURE_SCHEMA, fixture_digest, thaw_site_inputs

        fixture_dir = Path(args.l3_fixture_dir)
        manifest = json.loads((fixture_dir / "manifest.json").read_text(encoding="utf-8"))
        fixture_strata = {
            (record["order_code"], record["site_key"]): record
            for record in strata_from_fixture(fixture_dir)
        }
        for entry in manifest["orders"]:
            path = fixture_dir / entry["file"]
            block = json.loads(path.read_text(encoding="utf-8"))
            if block.get("schema") != FIXTURE_SCHEMA:
                raise ValueError(f"{path.name}: unexpected schema")
            if fixture_digest(path) != entry["sha256"]:
                raise ValueError(f"{path.name}: sha256 mismatch — fixture was modified")
            code = str(block["order_code"])
            handle(
                f"L3 fixture order {block['order_id']}",
                code,
                str(block.get("ptm_type") or ""),
                [str(c) for c in block["conditions"]],
                thaw_site_inputs(block),
                {
                    site_key: record
                    for (order_code, site_key), record in fixture_strata.items()
                    if order_code == code
                },
            )

    print("=" * 100)
    print(f"7 오더 pool 합산 — S-EVAL {pooled_sites}")
    print(
        f"  I1 Δτ_act p50 {quantile_summary(pooled_i1)['p50']}"
        f" | I2 Δτ_act p50 {quantile_summary(pooled_i2)['p50']}"
    )
    pool_i3 = summarize_sign_test(pooled_i3)
    pool_i4 = summarize_sign_test(pooled_i4)
    for name, block in (("I3 rank 증강", pool_i3), ("I4 rank 감축", pool_i4)):
        print(
            f"  {name}  부호 일치 {block['fraction_positive']}"
            f" ({block['n_sites_positive']}/{block['n_sites_nonzero']})"
            f" | p {block['sign_test_p_two_sided']}"
            f" | 기준 충족 {block['meets_prereg_criterion_exploratory']}"
        )
    payload["pool"] = {
        "n_s_eval_sites": pooled_sites,
        "i1_delta_tau_act": quantile_summary(pooled_i1),
        "i2_delta_tau_act": quantile_summary(pooled_i2),
        "i3_rank_augmentation": pool_i3,
        "i4_rank_truncation": pool_i4,
        "status": "exploratory (§6.6). E2 는 축소 수행 (§3.5.3)",
    }

    print()
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"기록 → {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
