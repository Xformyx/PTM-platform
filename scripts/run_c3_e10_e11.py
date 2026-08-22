"""E10·E11 — 제약이 C2 gate 지표에 미치는 영향과 C2 × C3 독립성.

구현 대상: docs/c3_prereg_v1.md §8 (E10, E11), §8 의 "E11 의 판정 규칙",
          §13.2 (`C3_E11_C2_ARM_V1` — C2 arm λ), §7.1 (`C3_BOOTSTRAP_V1`)
사전등록: E11 의 C2 arm λ 는 2026-08-22 §13.2 에서 **E11 착수 전** 선언되었다
          (primary 0.50, 민감도 5.00). 선택 규칙은 C2 의 공표된 E4/E5 수치만 참조하며
          C3 나 E11 의 결과를 보지 않았다.
          E11 판정 규칙(C2+C3 대 C2 단독, 짝지은 부트스트랩, 구간이 0 을 포함하면 흡수)은
          문서 동결(2026-08-22) 시점에 확정되어 있었다.
해석 한계: **E10 은 기술 통계이며 판정이 아니다.** retention ARI 는 §12.6.1 때문에 판정에
          쓰지 않는다 — arm D 에서 seed 잡음과 구별되지 않는다.
          E11 의 false merge 는 induced masking 을 고려하지 않은 하한이다 (§3.2).
          C2 는 자신의 인증서를 통과하지 못했으므로(`c2_prereg_v1.md` §13.1), 여기서
          "C2 arm" 은 **성공한 방법이 아니라 사전등록된 격자 점**이다.
주장 금지: "C3 가 C2 보다 우수하다" — 두 기여의 판정량이 다르므로 순위를 매기지 않는다.
          "C2+C3 가 gate 를 통과한다" — gate 판정은 `c2_prereg_v1.md` §5 의 규칙이며
          이 스크립트는 그 판정을 내리지 않는다.
          "비교 불가 쌍은 서로 다르다".

정본 환경:

    docker cp scripts/run_c3_e10_e11.py ptm-worker-preprocessing:/tmp/c3e1011.py
    docker exec -i ptm-worker-preprocessing env PYTHONPATH=/app:/opt python /tmp/c3e1011.py \
        --order-code Insulin_Signaling_Phosphoproteomics_HIRc-B
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path[:0] = ["/app", "/opt"]

import numpy as np

from ptm_shared.representation.comparability import (  # noqa: E402
    comparability_matrix,
    false_merge,
    pair_restricted_ari,
)
from ptm_shared.representation.comparability_constraint import (  # noqa: E402
    CONSTRAINT_LAMBDA_PRIMARY,
    CONSTRAINT_NEIGHBORS,
    CONSTRAINT_TEMPERATURE,
    MODE_CONSTRAINED,
)
from ptm_shared.representation.coverage_adversary import (  # noqa: E402
    ADVERSARY_MODE_BEST_RESPONSE,
    ADVERSARY_SEED,
)
from ptm_shared.representation.replicate_stratum import replicate_stratum_mask  # noqa: E402

sys.path[:0] = []

T_MIN_PRIMARY = 4
JUDGED_ARM = "D"
ENCODER_BASE = {"latent_dim": 16, "hidden_dim": 64, "epochs": 150, "n_perturbations": 0}
BENCHMARK_OVERRIDES = {"neighbors": 10, "leave_one_out": False, "minimum_sites": 8}
ENCODER_SEED = 0
"""`c2_prereg_v1.md` §12 의 고정 인코더 seed. C3 이 새로 정하지 않는다."""

C2_LAMBDA_PRIMARY = 0.50
"""E11 의 C2 arm. docs/c3_prereg_v1.md §13.2 에서 2026-08-22 선언. E11 착수 전.

`c2_prereg_v1.md` §7.2.1 격자에서 retention ARI 가 최대(0.067)인 점이다. E11 의 판정량이
군집 기반 false-merge 지표이므로 군집이 퇴화하지 않는 λ 여야 한다 — λ ≥ 1 에서 retention
ARI 가 0 또는 음수가 되고, 그 위에서 계산한 false merge 로는 C3 의 효과를 잴 수 없다.
측정 후 변경 금지 — 변경하면 독립성 판정이 사후 선택이 된다.
"""

C2_LAMBDA_SENSITIVITY = 5.00
"""같은 격자의 최강 coverage 제거 점(induced R² 0.0419). retention ARI 는 −0.0064 로 퇴화한다.
E9 에서 λ 의존성에 걸린 뒤이므로 E11 의 결론이 C2 의 λ 에 의존하는지 확인한다 (§13.2).
"""

BOOTSTRAP_REPLICATES = 2000
BOOTSTRAP_SEED = 20260822


# ---------------------------------------------------------------------------
# 4 조합
# ---------------------------------------------------------------------------


def combinations(c2_lambda: float) -> List[Dict[str, Any]]:
    """docs/c3_prereg_v1.md §8 E11 의 4조합.

    `neither` 는 현행 arm D 다. E9 의 기준선 0 과 같은 설정이므로 값이 재현되어야 한다.
    """
    return [
        {"name": "neither", "c2": False, "c3": False},
        {"name": "c2_only", "c2": True, "c3": False},
        {"name": "c3_only", "c2": False, "c3": True},
        {"name": "c2_and_c3", "c2": True, "c3": True},
    ]


def encoder_config(
    combination: Dict[str, Any],
    stratum: np.ndarray,
    *,
    c2_lambda: float,
    c3_lambda: float = CONSTRAINT_LAMBDA_PRIMARY,
    seed: int = ENCODER_SEED,
) -> Dict[str, Any]:
    config = dict(ENCODER_BASE)
    config["seed"] = int(seed)
    if combination["c2"]:
        config.update(
            {
                "use_coverage_adversary": True,
                "adversary_lambda": float(c2_lambda),
                "adversary_seed": ADVERSARY_SEED,
                "adversary_mode": ADVERSARY_MODE_BEST_RESPONSE,
            }
        )
    if combination["c3"]:
        config.update(
            {
                "use_comparability_constraint": True,
                "comparability_lambda": float(c3_lambda),
                "comparability_mode": MODE_CONSTRAINED,
                "comparability_neighbors": CONSTRAINT_NEIGHBORS,
                "comparability_temperature": CONSTRAINT_TEMPERATURE,
                "comparability_t_min": T_MIN_PRIMARY,
                "comparability_mask": stratum,
            }
        )
    return config


# ---------------------------------------------------------------------------
# 짝지은 부트스트랩 (E9 와 같은 정의)
# ---------------------------------------------------------------------------


def paired_bootstrap_fm_difference(
    labels_left: np.ndarray,
    labels_right: np.ndarray,
    comparable: np.ndarray,
    *,
    replicates: int = BOOTSTRAP_REPLICATES,
    seed: int = BOOTSTRAP_SEED,
) -> Dict[str, Any]:
    """`FM_precision(left) − FM_precision(right)` 의 95% 구간. feature 단위 복원 추출.

    docs/c3_prereg_v1.md §7.1. `run_c3_e9.py` 와 같은 정의다 — 두 실험이 다른 부트스트랩을
    쓰면 E9 와 E11 의 구간을 나란히 읽을 수 없다.
    """
    from ptm_shared.representation.comparability import same_cluster_matrix

    merged_left = same_cluster_matrix(labels_left)
    merged_right = same_cluster_matrix(labels_right)
    non_comparable = ~np.asarray(comparable, dtype=bool)
    np.fill_diagonal(non_comparable, False)

    n_rows = merged_left.shape[0]
    rng = np.random.default_rng(int(seed))
    differences = np.empty(replicates, dtype=float)
    valid = 0
    for _ in range(replicates):
        counts = np.bincount(rng.integers(0, n_rows, size=n_rows), minlength=n_rows).astype(float)
        outer = np.outer(counts, counts)
        np.fill_diagonal(outer, 0.0)
        values = []
        for merged in (merged_left, merged_right):
            denominator = float((outer * merged).sum())
            numerator = float((outer * (merged & non_comparable)).sum())
            values.append(numerator / denominator if denominator > 0 else np.nan)
        if np.isfinite(values[0]) and np.isfinite(values[1]):
            differences[valid] = values[0] - values[1]
            valid += 1
    sample = differences[:valid]
    if sample.size == 0:
        return {"status": "undefined", "n_replicates": 0}
    low, high = np.percentile(sample, [2.5, 97.5])
    return {
        "status": "evaluated",
        "n_replicates": int(sample.size),
        "mean_difference": round(float(sample.mean()), 8),
        "ci95_low": round(float(low), 8),
        "ci95_high": round(float(high), 8),
        "left_lower": bool(high < 0.0),
        "left_higher": bool(low > 0.0),
        "interval_contains_zero": bool(low <= 0.0 <= high),
    }


def absorption_verdict(test: Dict[str, Any]) -> Dict[str, Any]:
    """docs/c3_prereg_v1.md §8 의 E11 판정 규칙을 적용한다.

    **동결된 규칙은 두 분기만 열거했다** — 구간이 0 아래면 독립 기여, 0 을 포함하면 흡수.
    구간이 **전부 0 위**인 경우, 즉 C2+C3 가 C2 단독보다 유의하게 **나쁜** 경우는 열거되지
    않았다. 그 경우를 "흡수"로 적으면 사전등록 규칙보다 관대하게 읽는 것이다 — 흡수는
    "C3 가 아무것도 더하지 않는다"이고, 이것은 "C3 가 해를 끼친다"이므로 다른 결론이다.
    따라서 세 번째 분기를 명시하고 그것이 규칙 밖임을 기록한다.
    """
    if test.get("status") != "evaluated":
        return {"branch": "undefined", "preregistered": True, "label": "판정 불가"}
    if test["left_lower"]:
        return {
            "branch": "independent_contribution",
            "preregistered": True,
            "label": "독립 기여 성립",
        }
    if test["interval_contains_zero"]:
        return {
            "branch": "absorbed",
            "preregistered": True,
            "label": "흡수 — C2 의 구현 세부로 강등 (§7.5 사전 허용)",
        }
    return {
        "branch": "antagonistic",
        "preregistered": False,
        "label": "적대적 — C2 단독보다 유의하게 나쁘다. **동결 규칙이 열거하지 않은 경우**",
    }


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------


def load_population(vector_path: Path):
    import pandas as pd

    from ptm_shared.representation import build_multiview_input, validate_multiview_input

    frame = pd.read_csv(vector_path, sep="\t", low_memory=False)
    multiview = build_multiview_input(
        frame.to_dict("records"),
        config={"key_level": "form", "minimum_observed_timepoints": 3},
    )
    errors = validate_multiview_input(multiview)
    if errors:
        raise RuntimeError(f"L3 input contract violations: {errors}")
    return multiview.eligible_subset()


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--order-code", required=True)
    parser.add_argument("--data-root", default="/app/data")
    parser.add_argument(
        "--c2-lambda",
        type=float,
        default=C2_LAMBDA_PRIMARY,
        help="§13.2 primary = 0.50. 5.00 은 민감도 전용",
    )
    parser.add_argument("--output", default="")
    args = parser.parse_args(argv)

    from ptm_shared.representation.benchmark import (
        DEFAULT_BENCHMARK_CONFIG,
        cluster_representation,
        evaluate_variant,
        fit_variant,
    )
    from ptm_shared.representation.layers import resolve_variant

    data_root = Path(args.data_root)
    vector = data_root / "outputs" / args.order_code / "ptm_vector_data_normalized_phospho.tsv"
    raw_matrix = data_root / "inputs" / args.order_code / "report.pr_matrix.tsv"
    for path in (vector, raw_matrix):
        if not path.exists():
            print(f"FATAL: {path} 없음", file=sys.stderr)
            return 2

    multiview = load_population(vector)
    config = dict(DEFAULT_BENCHMARK_CONFIG)
    config.update(BENCHMARK_OVERRIDES)
    arm = resolve_variant(JUDGED_ARM)
    stratum, join = replicate_stratum_mask(multiview, raw_matrix, minimum_replicates=2)
    comparable = comparability_matrix(stratum, T_MIN_PRIMARY)

    c2_lambda = float(args.c2_lambda)
    is_primary = c2_lambda == C2_LAMBDA_PRIMARY
    print(f"order      = {args.order_code}")
    print(f"arm        = {JUDGED_ARM}   n = {multiview.n_sites}   T = {multiview.n_timepoints}")
    print(f"계층       = rep≥2 (결합률 {join['join_rate']:.4f})   T_min = {T_MIN_PRIMARY}")
    print(f"C2 λ       = {c2_lambda}   {'primary (§13.2)' if is_primary else 'SENSITIVITY'}")
    print(f"C3 λ       = {CONSTRAINT_LAMBDA_PRIMARY}   인코더 seed = {ENCODER_SEED}\n")

    results: Dict[str, Any] = {
        "experiments": ["E10", "E11"],
        "declaration": "docs/c3_prereg_v1.md",
        "order_code": args.order_code,
        "arm": JUDGED_ARM,
        "n_sites": int(multiview.n_sites),
        "stratum": "rep>=2",
        "t_min": T_MIN_PRIMARY,
        "c2_lambda": c2_lambda,
        "c2_lambda_is_primary": is_primary,
        "c3_lambda": CONSTRAINT_LAMBDA_PRIMARY,
        "encoder_seed": ENCODER_SEED,
    }

    # ---- 적합 + E10 지표 ---------------------------------------------------
    print("=" * 100)
    print("E10 — 제약이 gate 지표에 미치는 영향.  **기술 통계이며 판정이 아니다**")
    print("=" * 100)
    print(f"  {'조합':<12} {'군집':>5} {'induced R²':>11} {'retention ARI':>14} "
          f"{'natural R²':>11} {'병합쌍':>11} {'FM_prec':>9}")
    fits: Dict[str, Dict[str, Any]] = {}
    started = time.time()
    for combination in combinations(c2_lambda):
        settings = encoder_config(combination, stratum, c2_lambda=c2_lambda)
        fit = fit_variant(multiview, arm, encoder_config=settings, config=config)
        metrics = evaluate_variant(
            multiview, fit, arm=arm, encoder_config=settings, config=config
        )
        labels = cluster_representation(
            fit.embedding,
            distance_threshold=config["cluster_distance_threshold"],
            minimum_cluster_size=config["minimum_cluster_size"],
        )
        fm = false_merge(labels, comparable)
        probe = dict(metrics.get("artificial_masking_probe") or {})
        fits[combination["name"]] = {
            "labels": labels,
            "false_merge": fm,
            "induced_missingness_r2": probe.get("induced_missingness_r2"),
            "pattern_retention_ari": probe.get("pattern_retention_ari"),
            "natural_missingness_r2": metrics.get("missingness_r2"),
            "n_clusters": int(len({int(x) for x in labels.tolist() if x != 0})),
        }
        entry = fits[combination["name"]]
        print(
            f"  {combination['name']:<12} {entry['n_clusters']:>5} "
            f"{_fmt(entry['induced_missingness_r2']):>11} "
            f"{_fmt(entry['pattern_retention_ari']):>14} "
            f"{_fmt(entry['natural_missingness_r2']):>11} "
            f"{fm['n_merged_pairs']:>11,} {_fmt(fm['fm_precision']):>9}"
        )
    print(f"\n  소요 {time.time() - started:.0f}s")
    print("  retention ARI 는 §12.6.1 때문에 판정에 쓰지 않는다 — seed 잡음과 구별되지 않는다\n")

    results["e10"] = {
        name: {key: value for key, value in entry.items() if key != "labels"}
        for name, entry in fits.items()
    }

    # ---- E11 판정 ----------------------------------------------------------
    print("=" * 100)
    print("E11 — 독립성 판정.  C2+C3 의 FM_precision 이 C2 단독보다 유의하게 낮은가")
    print("=" * 100)
    started = time.time()
    absorption = paired_bootstrap_fm_difference(
        fits["c2_and_c3"]["labels"], fits["c2_only"]["labels"], comparable
    )
    # 병기: C3 단독 대 무제약. E9 와 다른 대조다(E9 는 무제약 **대조 손실** 기준선).
    c3_vs_neither = paired_bootstrap_fm_difference(
        fits["c3_only"]["labels"], fits["neither"]["labels"], comparable
    )
    print(f"  primary  C2+C3 {_fmt(fits['c2_and_c3']['false_merge']['fm_precision'])}"
          f"  대  C2 단독 {_fmt(fits['c2_only']['false_merge']['fm_precision'])}")
    verdict = absorption_verdict(absorption)
    if absorption["status"] == "evaluated":
        print(f"    평균 차이 {absorption['mean_difference']:+.6f}"
              f"   95% 구간 [{absorption['ci95_low']:+.6f}, {absorption['ci95_high']:+.6f}]")
        print(f"    판정  {verdict['label']}")
        if not verdict["preregistered"]:
            print("          동결된 §8 규칙은 '0 아래(독립)' 와 '0 포함(흡수)' 만 열거했다.")
            print("          이 결과를 흡수로 적으면 규칙보다 관대하게 읽는 것이므로 그렇게 적지 않는다.")
    print(f"\n  병기     C3 단독 {_fmt(fits['c3_only']['false_merge']['fm_precision'])}"
          f"  대  무제약 {_fmt(fits['neither']['false_merge']['fm_precision'])}")
    if c3_vs_neither["status"] == "evaluated":
        print(f"    평균 차이 {c3_vs_neither['mean_difference']:+.6f}"
              f"   95% 구간 [{c3_vs_neither['ci95_low']:+.6f}, {c3_vs_neither['ci95_high']:+.6f}]")
        print("    이 대조는 E9 의 primary 가 아니다 — E9 는 무제약 **대조 손실**을 기준선으로 쓴다")
    print(f"  소요 {time.time() - started:.0f}s\n")

    structure = pair_restricted_ari(
        fits["c2_and_c3"]["labels"], fits["c2_only"]["labels"], comparable
    )
    results["e11"] = {
        "absorption_test": absorption,
        "verdict": verdict,
        "c3_only_vs_neither": c3_vs_neither,
        "c3_only_differs_from_current_arm_d": bool(
            c3_vs_neither.get("left_lower", False) or c3_vs_neither.get("left_higher", False)
        ),
        "c2c3_vs_c2_pair_restricted_ari": (
            round(structure, 6) if structure is not None else None
        ),
        "independent_contribution": bool(absorption.get("left_lower", False)),
        "absorbed": bool(absorption.get("interval_contains_zero", False)),
        "judgement_is_primary": is_primary,
    }
    if not is_primary:
        print(f"  ** C2 λ = {c2_lambda} 는 민감도다. 판정에 쓰이지 않는다 (§13.2) **\n")

    payload = json.dumps(results, ensure_ascii=False, default=str)
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
        print(f"산출 기록: {args.output}")
    else:
        print(payload)
    return 0


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.5f}"


if __name__ == "__main__":
    raise SystemExit(main())
