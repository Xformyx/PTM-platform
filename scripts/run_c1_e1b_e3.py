"""E1b (기하 중복도 기술) 와 탐색적 E3 (예측 타당도) 를 E1 산출물에서 계산한다.

구현 대상: docs/c1_prereg_v1.md §6 (E1b), §7 (E3), §3.5.1–3.5.2 (강등과 탐색적 지위)
사전등록: 판정 규칙은 2026-08-20~22 동결. 이 스크립트는 `ptm_shared/c1_inference.py` 의
          인용된 상수만 쓰고 새 임계를 도입하지 않는다.
해석 한계: E1b 는 p-value 를 내지 않는다(§6.5). E3 는 **primary 에서 강등되었고**(§3.5.1)
          결과에 "통과/실패" 라벨을 붙이지 않는다(§3.5.2).
          모집단은 `S-EVAL` 이며 `S-DEAD` 는 `Δẑ ≡ 0` 이 구조적으로 강제되어 제외된다(§7.5).
주장 금지: E1b 로 τ 의 신규성을 증명했다고 쓰지 않는다. E3 로 C1 성공을 선언하지 않는다.
          검정력 미달의 **미평가**를 예측 **실패**로 쓰지 않는다(§3.5.1).

실행 (호스트에서 가능. τ JSON 만 읽으며 DB·scipy 를 쓰지 않는다):

    python scripts/run_c1_e1b_e3.py \
        --tau-json data/outputs/_diagnostics/c1_e1_v1/tau.json \
        --output data/outputs/_diagnostics/c1_e1_v1/e1b_e3.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO_ROOT), "/app", "/opt"]

from ptm_shared.c1_inference import (  # noqa: E402
    descriptive_association,
    provenance as inference_provenance,
    run_e1b,
    run_e3,
)
from ptm_shared.c1_transmissibility import STATUS_EVALUATED  # noqa: E402

TAU_FIELDS = ("tau_act", "tau_col")
"""두 τ 를 모두 보고한다.

`tau_act` 가 §4.1 의 primary 이지만 §4.2 의 승격 규칙(활성집합 불안정 비율 > 0.30)이 발동하면
사전등록된 primary 는 `tau_col` 로 바뀐다. 승격 여부는 E1 산출물의 `primary_tau_field` 에 있고
이 스크립트가 다시 판단하지 않는다.
"""


def s_eval_records(payload: Mapping[str, Any], *, scope: str) -> List[Dict[str, Any]]:
    """분석 모집단. docs/c1_prereg_v1.md §7.5 (baseline 기준 S-EVAL 조건부 estimand)."""
    records: List[Dict[str, Any]] = []
    for order in payload.get("orders", []):
        if scope != "pool" and order.get("order_code") != scope:
            continue
        for site in order.get("sites", []):
            if site.get("stratum") == "S-EVAL" and site.get("status") == STATUS_EVALUATED:
                records.append(dict(site))
    return records


def show(value: Any, digits: int = 4) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def print_e1b(block: Mapping[str, Any]) -> None:
    if block.get("status") != "measured":
        print(f"    [{block.get('status')}] {json.dumps(block, ensure_ascii=False)}")
        return
    ci_rho = block.get("oof_spearman_ci95")
    ci_r2 = block.get("oof_r2_ci95")
    inversion = block.get("d_inv_primary") or {}
    print(
        f"    n_oof {block['n_oof']:>4} | 블록 {block['n_blocks']:>4}"
        f" | 비유한 제외 {block['n_dropped_nonfinite']}"
        f" | penalty {sorted(set(block['penalties_selected']))}"
    )
    print(
        f"    OOF Spearman  {show(block['oof_spearman'])}"
        f"  95% CI [{show(ci_rho[0]) if ci_rho else '—'}, {show(ci_rho[1]) if ci_rho else '—'}]"
    )
    print(
        f"    OOF R²        {show(block['oof_r2'])}"
        f"  95% CI [{show(ci_r2[0]) if ci_r2 else '—'}, {show(ci_r2[1]) if ci_r2 else '—'}]"
    )
    print(
        f"    D_inv (primary) {show(inversion.get('d_inv'))}"
        f"  비교 가능 쌍 {int(inversion.get('n_comparable_pairs') or 0)}"
        f"  | Kendall tau-b (redundant) {show(block['kendall_tau_b_redundant'])}"
    )


def print_e3(block: Mapping[str, Any]) -> None:
    status = block.get("status")
    if status not in {"measured_exploratory"}:
        print(f"    [{status}] {block.get('reason') or ''}")
        print(
            f"    블록 {block.get('n_blocks')} | high {block.get('n_high_blocks')}"
            f" | low {block.get('n_low_blocks')}"
            f" | 평가 가능 fold {block.get('n_evaluable_folds')}"
        )
        return
    print(
        f"    블록 {block['n_blocks']:>4} | high {block['n_high_blocks']:>3}"
        f" | low {block['n_low_blocks']:>3} | 평가 가능 fold {block['n_evaluable_folds']}/5"
    )
    print(
        f"    Δẑ 중앙값  high {show(block['median_response_high'])}"
        f"  low {show(block['median_response_low'])}"
        f"  차이 {show(block['observed_difference'])}"
        f"  (방향 예측 일치 {block['direction_matches_prediction']})"
    )
    print(
        f"    순열 p {show(block['p_permutation'], 5)}"
        f"  | Cliff's delta {show(block['cliffs_delta'])}"
        f"  | **탐색적. 통과/실패 라벨 없음**"
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tau-json", required=True)
    parser.add_argument("--output", default=None)
    args = parser.parse_args(argv)

    payload = json.loads(Path(args.tau_json).read_text(encoding="utf-8"))
    scopes: List[str] = [
        str(order["order_code"]) for order in payload.get("orders", [])
    ] + ["pool"]

    print("=" * 100)
    print("E1b (기하 중복도 기술) · 탐색적 E3 (예측 타당도)")
    print("E1b 는 판정 관문이 아니며 p-value 를 내지 않는다 (c1_prereg_v1.md §6.1·§6.5)")
    print("E3 는 §3.5.1 에서 primary 에서 강등되었다. 결과는 탐색적이다 (§3.5.2)")
    print("=" * 100)
    print(f"inference = {json.dumps(inference_provenance(), ensure_ascii=False)}")

    results: Dict[str, Any] = {
        "contract": "C1_E1B_E3_V1",
        "measured_at": "2026-08-22",
        "source_tau_json": str(args.tau_json),
        "prereg_branch": "(i) 강등 + (iii) 탐색적 7 오더 pool (§3.5.1)",
        "inference_provenance": inference_provenance(),
        "by_scope": {},
    }

    for scope in scopes:
        records = s_eval_records(payload, scope=scope)
        label = "7 오더 pool (탐색적 모집단, §3.5.2)" if scope == "pool" else scope
        print()
        print("-" * 100)
        print(f"{label}  |  S-EVAL 평가 가능 site {len(records)}")
        if len(records) < 10:
            print("    [건너뜀] site 10 미만 — 기술 통계조차 무의미하다")
            results["by_scope"][scope] = {"n_s_eval": len(records), "status": "skipped"}
            continue

        block: Dict[str, Any] = {"n_s_eval": len(records)}
        for tau_field in TAU_FIELDS:
            print()
            print(f"  E1b — {tau_field}")
            e1b = run_e1b(records, tau_field=tau_field)
            print_e1b(e1b)
            print(f"  E3 (탐색적) — {tau_field}")
            e3 = run_e3(records, tau_field=tau_field)
            print_e3(e3)
            association = descriptive_association(records, tau_field=tau_field)
            print(
                f"    [§7.1 기각 대상. 근거 아님] 동일 표본 Spearman(τ, Δẑ)"
                f"  site {show(association.get('site_level_spearman'))}"
                f"  블록 {show(association.get('block_level_spearman'))}"
            )
            block[tau_field] = {"e1b": e1b, "e3": e3, "descriptive": association}
        results["by_scope"][scope] = block

    print()
    print("=" * 100)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"기록 → {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
