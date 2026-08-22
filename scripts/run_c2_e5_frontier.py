"""E5 frontier 의 예측력 축 — λ 격자 8 점의 공정 프로브 ΔR².

구현 대상: docs/c2_prereg_v1.md §7.2 (frontier. "보고 8 점 전부. 중간 점 보간 금지")
사전등록: 2026-08-21 동결. λ 격자·임계·프로브 설정이 실행 전에 확정되었다.
해석 한계: **frontier 는 판정이 아니다.** §7.3 의 λ\* 규칙은 (a)+(c) 로만 선택하며 ΔR² 로
          고르지 않는다. 어느 한 점이 (a)+(b) 를 만족한다는 것으로 C2 성공을 주장하는 것은
          §11 에서 명시적으로 금지된다. 이 표의 역할은 **대가의 정량화**다.
          baseline 이 이미 R² ≈ 0.924 인 과제에서의 차이이므로 상대 이득이 작다는 사실을
          항상 병기한다 (§5.2).
주장 금지: ΔR² 이 유지되었다는 것을 "coverage 를 제거하고도 예측력을 지켰다"로 서술하지
          않는다. (a)·(c) 가 충족되지 않은 격자점에서는 애초에 제거가 성립하지 않았다.

정본 환경:

    docker cp scripts/run_c2_e5_frontier.py ptm-worker-preprocessing:/tmp/frontier.py
    docker exec -i ptm-worker-preprocessing env PYTHONPATH=/app:/opt python /tmp/frontier.py \
        --order-code Insulin_Signaling_Phosphoproteomics_HIRc-B
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

sys.path[:0] = ["/app", "/opt"]

PROBE_DELTA_R2_MIN = 0.01355
PROBE_P_MAX = 0.05
"""조건 (b) 임계. docs/c2_prereg_v1.md §5.2, §14.2 승인. 여기서 도입하지 않고 인용한다."""

LAMBDA_GRID = (0.0, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0)
ABLATION_ENCODER_BASE = {"latent_dim": 16, "hidden_dim": 64, "epochs": 150, "seed": 0,
                         "n_perturbations": 5}


def _number(value: Any, width: int, digits: int) -> str:
    if value is None:
        return f"{'n/a':>{width}}"
    return f"{float(value):>{width}.{digits}f}"


def load_eligible(vector_path: Path, key_level: str = "form", *, eligible_only: bool = True):
    import pandas as pd

    from ptm_shared.representation import build_multiview_input, validate_multiview_input

    frame = pd.read_csv(vector_path, sep="\t", low_memory=False)
    multiview = build_multiview_input(
        frame.to_dict("records"),
        config={"key_level": key_level, "minimum_observed_timepoints": 3},
    )
    errors = validate_multiview_input(multiview)
    if errors:
        raise RuntimeError(f"L3 input contract violations: {errors}")
    return multiview.eligible_subset() if eligible_only else multiview


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--order-code", required=True)
    parser.add_argument("--data-root", default="/app/data")
    parser.add_argument("--arm", default="D")
    parser.add_argument(
        "--epochs",
        type=int,
        default=ABLATION_ENCODER_BASE["epochs"],
        help="인코더 epoch. 기본 150 은 ablation 재현값(§1.3). 공표 ΔR² 의 교정 확인용으로만 변경한다.",
    )
    parser.add_argument(
        "--only-lambda",
        type=float,
        default=None,
        help="격자 중 한 점만 실행한다. 진단용이며 frontier 보고에는 쓰지 않는다(§7.2 는 8 점 전부).",
    )
    parser.add_argument(
        "--probe-arms",
        default="B,D",
        help="프로브에 포함할 arm. 공표값은 A,B,D,E 로 측정되었다.",
    )
    parser.add_argument(
        "--key-level",
        default="form",
        choices=("form", "site"),
        help=(
            "C2 gate 수치는 form(2,744) 에서 나왔고 공표 프로브 표는 site(2,447) 에서 나왔다"
            " (c1_alignment_check_2026-08-21.md §5). 교정 확인용으로만 변경한다."
        ),
    )
    parser.add_argument(
        "--no-adversary",
        action="store_true",
        help="adversary 를 아예 구성하지 않는다. 공표값은 adversary 도입 이전 코드에서 나왔다.",
    )
    parser.add_argument(
        "--no-eligible-filter",
        action="store_true",
        help=(
            "eligible_subset() 을 적용하지 않는다. C2 gate 수치는 적격 부분집합(2,744)에서"
            " 나왔으나 공표 프로브 표의 '2,447 site' 는 필터 이전 수치와 일치한다."
        ),
    )
    args = parser.parse_args(argv)

    from ptm_shared.representation import fair_probe as fair_probe_module

    vector = (
        Path(args.data_root) / "outputs" / args.order_code
        / "ptm_vector_data_normalized_phospho.tsv"
    )
    if not vector.exists():
        print(f"FATAL: {vector} 없음", file=sys.stderr)
        return 2

    multiview = load_eligible(
        vector, args.key_level, eligible_only=not args.no_eligible_filter
    )
    probe_arms = tuple(part.strip() for part in args.probe_arms.split(",") if part.strip())
    grid = LAMBDA_GRID if args.only_lambda is None else (float(args.only_lambda),)
    print(f"order   = {args.order_code}   key_level = {args.key_level}")
    print(f"n_sites = {multiview.n_sites}   T = {multiview.n_timepoints}")
    print(f"arm     = {args.arm}   baseline = B   프로브 arm = {list(probe_arms)}")
    print(f"epochs  = {args.epochs}   λ = {list(grid)}")
    print(f"임계    = ΔR² ≥ {PROBE_DELTA_R2_MIN}  AND  p < {PROBE_P_MAX}  (§5.2 인용)")
    print()
    print("=" * 88)
    print(f"{'lambda':>7} {'ΔR²':>10} {'우세/짝':>9} {'p':>9} {'(b)':>6}")
    print("=" * 88)

    records: List[Dict[str, Any]] = []
    last_per_arm: Dict[str, Any] = {}
    started = time.time()
    for lambda_value in grid:
        encoder_config = dict(ABLATION_ENCODER_BASE)
        encoder_config["epochs"] = args.epochs
        if not args.no_adversary:
            encoder_config["use_coverage_adversary"] = True
            encoder_config["adversary_lambda"] = lambda_value
        probe = fair_probe_module.run_heldout_timepoint_probe(
            multiview,
            encoder_config=encoder_config,
            config={"arms": probe_arms, "baseline_arm": "B"},
        )
        last_per_arm = probe.get("per_arm") or {}
        summary = (probe.get("comparisons") or {}).get("arms", {}).get(args.arm, {})
        delta = summary.get("mean_r2_difference")
        p_value = summary.get("sign_flip_p_value")
        fraction = summary.get("fraction_of_folds_better")
        pairs = summary.get("n_paired_folds")
        passed = bool(
            delta is not None
            and p_value is not None
            and float(delta) >= PROBE_DELTA_R2_MIN
            and float(p_value) < PROBE_P_MAX
        )
        records.append(
            {
                "lambda": lambda_value,
                "mean_r2_difference": delta,
                "sign_flip_p_value": p_value,
                "fraction_of_folds_better": fraction,
                "n_paired_folds": pairs,
                "sd_r2_difference": summary.get("sd_r2_difference"),
                "condition_b": passed,
                "probe_status": probe.get("status"),
            }
        )
        wins = None if fraction is None or pairs is None else int(round(fraction * pairs))
        print(
            f"{lambda_value:>7.2f}"
            f" {('       n/a' if delta is None else f'{delta:>10.5f}')}"
            f" {f'{wins}/{pairs}':>9}"
            f" {('      n/a' if p_value is None else f'{p_value:>9.4f}')}"
            f" {'PASS' if passed else 'fail':>6}"
        )

    if args.only_lambda is not None and last_per_arm:
        # 단일 점 진단: 공표 프로브 표(ptm_representation_learning_contract_v1.md §R1.6)와
        # arm 단위로 대조할 수 있게 per_arm 을 그대로 보여준다. 판정에 쓰지 않는다.
        print()
        print("per_arm (공표 표 대조용. 판정 아님)")
        print(f"  {'arm':<4} {'dim':>4} {'mean R²':>10} {'sd':>8} {'귀무 R²':>9} {'fold':>5}")
        for arm in sorted(last_per_arm):
            block = last_per_arm[arm]
            cells = [
                f"  {arm:<4}",
                f"{int(block.get('embedding_dim') or 0):>4}",
                _number(block.get("mean_r2"), 10, 4),
                _number(block.get("sd_r2"), 8, 3),
                _number(block.get("mean_null_r2"), 9, 4),
                f"{int(block.get('n_folds') or 0):>5}",
            ]
            print(" ".join(cells))

    print()
    print(f"소요 {time.time() - started:.0f}s")
    print()
    print("판정 아님 (§11). λ* 는 (a)+(c) 로만 선택한다 — ΔR² 로 고르는 것은 사후 선택이다.")
    print()
    print(json.dumps({"frontier": records}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
