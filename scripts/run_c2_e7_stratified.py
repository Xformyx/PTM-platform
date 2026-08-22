"""E7 — 층화 진단. 전체 요약이 층 구조를 가리고 있는가.

구현 대상: docs/c2_prereg_v1.md §9 (E7), §9.1 (`C2_E7_STRATIFICATION_V1` — 층·지표 정의),
          §11 (E7 은 기술적 보고), docs/core_ab_p2_frozen_contract_v1.md §0.1 (universe)
사전등록: 층과 지표는 2026-08-22 §9.1 에서 **측정 착수 전** 선언되었다.
          **임계는 선언되지 않았고 이 스크립트는 판정하지 않는다.** 의도된 것이다 — 층을
          사후에 고를 수 있으므로 층별 판정을 허용하면 다중 비교가 된다.
해석 한계: 층 경계는 core_ab_p2_frozen_contract_v1.md §0.1 을 인용하며 이 스크립트가 정하지
          않는다. §0.1 의 공표 수치(2,420/302/313)는 다른 모집단이므로 여기 수와 다르다.
          M1(층 내 재적합 R²)은 층 크기가 작을수록 분산이 크다 — 층별 n 을 항상 병기한다.
          M3/M4 의 쌍 제한은 양 종단이 층 안인 쌍만 쓰므로, 층 간 쌍은 어느 층에도 없다.
주장 금지: "층 X 에서 인증서가 충족되므로 C2 는 성공이다" — §11 이 명시적으로 금지한다.
          "U-confirmatory 가 더 정확한 데이터다" — baseline 신뢰도 층이며 품질 순위가 아니다.
          "낮은 회수 R² 는 독립성의 증명이다" (coverage_probes 의 주장 금지 조항).

정본 환경:

    docker cp scripts/run_c2_e7_stratified.py ptm-worker-preprocessing:/tmp/c2e7.py
    docker exec -i ptm-worker-preprocessing env PYTHONPATH=/app:/opt python /tmp/c2e7.py \
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
from ptm_shared.representation.coverage_probes import (  # noqa: E402
    PREDICTOR_FAMILY,
    residual_mask_recoverability,
)
from ptm_shared.representation.replicate_stratum import (  # noqa: E402
    UNIVERSE_ORDER,
    replicate_stratum_mask,
    universe_assignment,
)

T_MIN_PRIMARY = 4
JUDGED_ARM = "D"
ENCODER_BASE = {"latent_dim": 16, "hidden_dim": 64, "epochs": 150, "seed": 0, "n_perturbations": 0}
BENCHMARK_OVERRIDES = {"neighbors": 10, "leave_one_out": False, "minimum_sites": 8}

OBSERVED_TIMEPOINT_STRATA = (3, 4, 5, 6)
"""docs/c2_prereg_v1.md §9.1 층 (2).

**§9 원문은 4·5·6 만 적었다.** 모집단 필터가 `minimum_observed_timepoints = 3` 이므로 3 이
존재할 수 있고 빼면 층화가 모집단을 덮지 못한다. 3 을 추가한 것은 §9.1 에서 측정 전에
선언되었다.
"""

MINIMUM_STRATUM_SITES = 20
"""층별 지표를 산출할 최소 site 수. §9.1 이 임계를 선언하지 않았으므로 **판정 임계가 아니다** —
이 값 미만이면 지표를 `None` 으로 두고 n 만 보고한다. 작은 층에서 나온 R² 를 숫자로 적으면
읽는 사람이 그것을 비교 가능한 값으로 취급하게 된다.
"""


def quartile_labels(values: np.ndarray) -> Tuple[np.ndarray, List[float]]:
    """모집단 내 사분위 라벨. 경계는 이 모집단에서 계산한다 (§9.1 층 (3))."""
    finite = np.asarray(values, dtype=float)
    edges = [float(np.quantile(finite, q)) for q in (0.25, 0.50, 0.75)]
    labels = np.full(finite.size, "Q1", dtype=object)
    labels[finite > edges[0]] = "Q2"
    labels[finite > edges[1]] = "Q3"
    labels[finite > edges[2]] = "Q4"
    return labels, edges


def stratum_metrics(
    embedding: np.ndarray,
    induced_rate: np.ndarray,
    labels: np.ndarray,
    masked_labels: np.ndarray,
    comparable: np.ndarray,
    selector: np.ndarray,
    *,
    with_family: bool,
) -> Dict[str, Any]:
    """§9.1 의 M1–M4 를 부분 모집단에 적용한다. 정의는 전부 기존 함수를 그대로 호출한다."""
    from ptm_shared.representation.benchmark import _missingness_r2

    count = int(selector.sum())
    result: Dict[str, Any] = {"n_sites": count}
    if count < MINIMUM_STRATUM_SITES:
        result.update(
            {
                "status": "too_small",
                "induced_missingness_r2": None,
                "family_max_recovery_r2": None,
                "fm_precision": None,
                "non_comparable_base_rate": None,
                "fm_precision_over_base_rate": None,
                "retention_ari": None,
            }
        )
        return result

    result["status"] = "evaluated"
    result["induced_missingness_r2"] = _missingness_r2(
        embedding[selector], induced_rate[selector]
    )

    if with_family:
        family = residual_mask_recoverability(
            embedding[selector], induced_rate[selector], n_permutations=20
        )
        result["family_max_recovery_r2"] = family.get("family_max_out_of_sample_r2")
        result["family_status"] = family.get("status")
        result["per_predictor_r2"] = {
            name: (family.get("per_predictor", {}).get(name) or {}).get("out_of_sample_r2")
            for name in PREDICTOR_FAMILY
        }
    else:
        result["family_max_recovery_r2"] = None
        result["family_status"] = "skipped"

    # M3·M4 는 양 종단이 층 안인 쌍으로 제한한다 (§9.1). 부분행렬을 취하는 것이 그 정의이며,
    # 층 간 쌍은 어느 층의 분모에도 들어가지 않는다.
    inside = np.ix_(selector, selector)
    fm = false_merge(labels[selector], comparable[inside])
    result["fm_precision"] = fm["fm_precision"]
    result["n_merged_pairs"] = fm["n_merged_pairs"]
    result["n_false_merges"] = fm["n_false_merges"]
    # 층 내 비교 불가 기저율. **첫 E7 실행 뒤에 추가했다** — 층별 FM_precision 만으로는 해석이
    # 불가능했기 때문이다. 관측 시점이 적은 층에서는 층 내 쌍 대부분이 애초에 비교 불가이므로
    # FM_precision 이 1 에 가까운 것이 군집의 성질이 아니라 층의 정의에서 나온다.
    # 임계가 없는 기술 통계이므로 어떤 primary 판정도 이 추가에 영향받지 않는다 (§9.1).
    total_pairs = count * (count - 1) // 2
    base_rate = (fm["n_non_comparable_pairs"] / total_pairs) if total_pairs else None
    result["non_comparable_base_rate"] = base_rate
    result["fm_precision_over_base_rate"] = (
        (fm["fm_precision"] / base_rate)
        if (base_rate not in (None, 0.0) and fm["fm_precision"] is not None)
        else None
    )
    result["retention_ari"] = pair_restricted_ari(
        labels[selector], masked_labels[selector], comparable[inside]
    )
    return result


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
        "--skip-family",
        action="store_true",
        help="M2 (족 회수 R²) 생략. 교차적합 + 순열이 층마다 반복되어 느리다",
    )
    parser.add_argument("--output", default="")
    args = parser.parse_args(argv)

    from ptm_shared.representation.benchmark import (
        DEFAULT_BENCHMARK_CONFIG,
        cluster_representation,
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

    stratum, _ = replicate_stratum_mask(multiview, raw_matrix, minimum_replicates=2)
    comparable = comparability_matrix(stratum, T_MIN_PRIMARY)
    universe, universe_meta = universe_assignment(multiview, raw_matrix)
    observed_counts = multiview.target.observed.sum(axis=1)
    natural_rate = multiview.missingness_rate()
    quartiles, quartile_edges = quartile_labels(natural_rate)

    print(f"order      = {args.order_code}")
    print(f"arm        = {JUDGED_ARM}   n = {multiview.n_sites}   T = {multiview.n_timepoints}")
    print(f"universe   = {universe_meta['counts']}   미결합 {universe_meta['n_unjoined']}")
    print(f"             control run {universe_meta['n_control_runs']}개, "
          f"평균 replicate {universe_meta['mean_control_replicates']}")
    print(f"관측 시점   = {dict(zip(*np.unique(observed_counts, return_counts=True)))}")
    print(f"결측률 사분위 경계 = {[round(edge, 4) for edge in quartile_edges]}")
    print("\n**임계 없음. 이 실행은 판정하지 않는다 (§11) **\n")

    # ---- 단일 적합 + 마스킹 적합 -------------------------------------------
    started = time.time()
    fit = fit_variant(multiview, arm, encoder_config=ENCODER_BASE, config=config)
    labels = cluster_representation(
        fit.embedding,
        distance_threshold=config["cluster_distance_threshold"],
        minimum_cluster_size=config["minimum_cluster_size"],
    )
    masked_input, induced = multiview.with_additional_target_masking(
        fraction=config["artificial_mask_fraction"], seed=config["seed"]
    )
    masked_fit = fit_variant(
        masked_input, arm, encoder_config={**ENCODER_BASE, "n_perturbations": 0}, config=config
    )
    masked_labels = cluster_representation(
        masked_fit.embedding,
        distance_threshold=config["cluster_distance_threshold"],
        minimum_cluster_size=config["minimum_cluster_size"],
    )
    induced_rate = induced.mean(axis=1)
    print(f"적합 완료 ({time.time() - started:.0f}s). "
          f"induced 항목 {int(induced.sum()):,}, 마스킹 비율 {config['artificial_mask_fraction']}\n")

    with_family = not args.skip_family
    all_sites = np.ones(multiview.n_sites, dtype=bool)
    pooled = stratum_metrics(
        masked_fit.embedding, induced_rate, labels, masked_labels, comparable, all_sites,
        with_family=with_family,
    )

    results: Dict[str, Any] = {
        "experiment": "E7",
        "declaration": "docs/c2_prereg_v1.md §9.1",
        "judgement": "none_by_design",
        "order_code": args.order_code,
        "arm": JUDGED_ARM,
        "n_sites": int(multiview.n_sites),
        "universe_source": universe_meta,
        "quartile_edges": [round(edge, 6) for edge in quartile_edges],
        "observed_timepoint_strata": list(OBSERVED_TIMEPOINT_STRATA),
        "minimum_stratum_sites": MINIMUM_STRATUM_SITES,
        "pooled": pooled,
        "strata": {},
    }

    axes: List[Tuple[str, List[Tuple[str, np.ndarray]]]] = [
        ("universe", [(name, universe == name) for name in UNIVERSE_ORDER]),
        (
            "observed_timepoints",
            [(str(count), observed_counts == count) for count in OBSERVED_TIMEPOINT_STRATA],
        ),
        (
            "natural_missingness_quartile",
            [(name, quartiles == name) for name in ("Q1", "Q2", "Q3", "Q4")],
        ),
    ]

    header = (
        f"  {'층':<18} {'n':>6} {'induced R²':>11} {'族 최대 R²':>11} "
        f"{'FM_prec':>9} {'비교불가율':>10} {'비(倍)':>7} {'retention':>10}"
    )
    for axis_name, groups in axes:
        print("=" * 112)
        print(f"층 축: {axis_name}")
        print("=" * 112)
        print(header)
        print(f"  {'(전체)':<18} {pooled['n_sites']:>6} "
              f"{_fmt(pooled['induced_missingness_r2']):>11} "
              f"{_fmt(pooled['family_max_recovery_r2']):>11} "
              f"{_fmt(pooled['fm_precision']):>9} "
              f"{_fmt(pooled['non_comparable_base_rate']):>10} "
              f"{_ratio(pooled['fm_precision_over_base_rate']):>7} "
              f"{_fmt(pooled['retention_ari']):>10}")
        axis_results: Dict[str, Any] = {}
        for name, selector in groups:
            metrics = stratum_metrics(
                masked_fit.embedding, induced_rate, labels, masked_labels, comparable, selector,
                with_family=with_family,
            )
            axis_results[name] = metrics
            note = "  (n 부족)" if metrics["status"] == "too_small" else ""
            print(f"  {name:<18} {metrics['n_sites']:>6} "
                  f"{_fmt(metrics['induced_missingness_r2']):>11} "
                  f"{_fmt(metrics['family_max_recovery_r2']):>11} "
                  f"{_fmt(metrics['fm_precision']):>9} "
                  f"{_fmt(metrics['non_comparable_base_rate']):>10} "
                  f"{_ratio(metrics['fm_precision_over_base_rate']):>7} "
                  f"{_fmt(metrics['retention_ari']):>10}{note}")
        results["strata"][axis_name] = axis_results
        spread = _spread(axis_results, "induced_missingness_r2")
        if spread is not None:
            print(f"\n  induced R² 층 간 범위 {spread[0]:.4f} – {spread[1]:.4f}"
                  f"   전체 {_fmt(pooled['induced_missingness_r2'])}")
        print()

    payload = json.dumps(results, ensure_ascii=False, default=str)
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
        print(f"산출 기록: {args.output}")
    else:
        print(payload)
    return 0


def _spread(axis: Dict[str, Any], key: str) -> Optional[Tuple[float, float]]:
    values = [
        float(entry[key])
        for entry in axis.values()
        if entry.get(key) is not None
    ]
    return (min(values), max(values)) if len(values) >= 2 else None


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.5f}"


def _ratio(value: Any) -> str:
    """FM_precision ÷ 비교 불가 기저율. 1 이면 군집이 비교가능성에 무관하다는 뜻이다."""
    if value is None:
        return "n/a"
    return f"{float(value):.2f}"


if __name__ == "__main__":
    raise SystemExit(main())
