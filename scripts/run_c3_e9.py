"""E9 — 비교가능성 제약의 primary 판정. 3-기준선 설계.

구현 대상: docs/c3_prereg_v1.md §8 (E9), §5.3 판정 결합, §6.2 3-기준선, §6.3 함수형,
          §6.3.2 자명성 검사, §7.1–§7.2 클러스터 부트스트랩
사전등록: 동결 2026-08-22. **판정 규칙과 임계 5개가 이 실행 전에 확정되었다.**
          FM_precision(primary), G1a ≥ 0.0237, G1b ≥ 0.0237, G2 ≥ 0.50, G3 ≥ 0.01355.
          이 스크립트는 임계를 선언하지 않고 모듈에서 인용한다.
해석 한계: primary 대조는 **처리 대 기준선 1**(무제약 대조 손실)이다. 기준선 0(대조 항 없음)
          과의 비교는 "대조 항을 추가한 효과"를 포함하므로 C3 의 기여가 아니다.
          단일 코호트(HIRc-B, T = 6, form 단위). 외부 일반화 미평가.
          `O_ij = 0` 은 유사성 판단 근거의 부재이며 비유사성의 증거가 아니다.
          E9 의 false merge 는 induced masking 을 고려하지 않은 하한이다 (§3.2).
주장 금지: "제약이 kinase 예측을 개선한다".
          "FM 이 낮아졌으므로 표현 품질이 높아졌다" — §5.2 동반 지표 없이는 성립하지 않는다.
          "비교 불가 쌍은 서로 다르다".

정본 환경:

    docker cp scripts/run_c3_e9.py ptm-worker-preprocessing:/tmp/c3e9.py
    docker exec -i ptm-worker-preprocessing env PYTHONPATH=/app:/opt python /tmp/c3e9.py \
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
    removal_precision,
)
from ptm_shared.representation.comparability_constraint import (  # noqa: E402
    CONSTRAINT_LAMBDA_PRIMARY,
    CONSTRAINT_NEIGHBORS,
    CONSTRAINT_TEMPERATURE,
    EMPTY_POSITIVE_ROW_MAX,
    MODE_CONSTRAINED,
    MODE_UNCONSTRAINED,
)
from ptm_shared.representation.replicate_stratum import replicate_stratum_mask  # noqa: E402

T_MIN_PRIMARY = 4
"""docs/c3_prereg_v1.md §2.1."""

JUDGED_ARM = "D"
"""판정 대상 arm. `layers.PRIMARY_ARM_PREFERENCE` 의 primary 이며 C3 이 새로 정하지 않는다."""

ENCODER_BASE = {"latent_dim": 16, "hidden_dim": 64, "epochs": 150, "n_perturbations": 0}
BENCHMARK_OVERRIDES = {"neighbors": 10, "leave_one_out": False, "minimum_sites": 8}
"""c2_prereg_v1.md §1.1 의 ablation 설정을 인용한다. `n_perturbations = 0` 은 E9 가 섭동
임베딩을 쓰지 않기 때문이며, 군집·FM 지표는 섭동에 의존하지 않는다.
"""

ENCODER_SEEDS = (0, 1)
"""docs/c3_prereg_v1.md §6.3.1. G1b 가 조건별 2회 적합을 요구한다."""

G1_THRESHOLD = 0.0237
"""G1a·G1b 임계. docs/c3_prereg_v1.md §5.2 에서 2026-08-22 확정. E9 실행 전.

§12.4 에서 실측한 arm D 의 seed 간 비교 가능 쌍 ARI 하한(0.0237–0.0373 중 최솟값)이다.
이보다 낮은 임계는 seed 잡음과 구별되지 않는다. **약한 기준임을 §5.2 에 명시했다** —
같은 seed 의 제약 대 무제약은 초기화를 공유하므로 제약이 아무 일도 하지 않아도 통과한다.
그 약함을 메우기 위해 G1b 를 함께 판정한다. 측정 후 변경 금지.
"""

G2_THRESHOLD = 0.50
"""G2 제거 표적성 임계. docs/c3_prereg_v1.md §5.2 에서 2026-08-22 확정. E9 실행 전.

무작위 제거의 기대값은 기저 FM_precision(arm D 에서 0.1042)이므로 0.50 은 그 약 4.8 배다.
제거된 병합의 절반 이상이 false merge 여야 한다는 뜻이다. 측정 후 변경 금지.
"""

G3_THRESHOLD = 0.01355
"""G3 공정 프로브 ΔR² 임계. `c2_prereg_v1.md` §7.2 의 동결 임계를 **인용**한다.
C3 이 새 임계를 만들지 않는다.
"""

SEED_NOISE_ARI_RANGE = (0.0237, 0.0373)
"""§12.4 실측. S1 자명성 검사의 대조 범위 — 기준선 1과 기준선 0 의 차이가 이 범위 안이면
λ 가 너무 약하다는 뜻이다 (§6.3.2 S1).
"""

BOOTSTRAP_REPLICATES = 2000
BOOTSTRAP_SEED = 20260822
"""docs/c3_prereg_v1.md §7.1 `C3_BOOTSTRAP_V1`. feature 단위 복원 추출, percentile 95%."""


# ---------------------------------------------------------------------------
# 조건
# ---------------------------------------------------------------------------


def arm_configurations() -> List[Dict[str, Any]]:
    """docs/c3_prereg_v1.md §6.2 의 3-기준선.

    primary 대조는 `treatment` 대 `baseline1` 이다. `baseline0` 은 대조 항 자체의 효과를
    분리하기 위해 병기하며 C3 의 판정에 들어가지 않는다.
    """
    return [
        {"name": "baseline0_no_contrastive", "use": False, "mode": None},
        {"name": "baseline1_unconstrained", "use": True, "mode": MODE_UNCONSTRAINED},
        {"name": "treatment_constrained", "use": True, "mode": MODE_CONSTRAINED},
    ]


def encoder_config(
    condition: Dict[str, Any],
    seed: int,
    stratum: np.ndarray,
    lam: float,
    t_min: int = T_MIN_PRIMARY,
) -> Dict[str, Any]:
    config = dict(ENCODER_BASE)
    config["seed"] = int(seed)
    if condition["use"]:
        config.update(
            {
                "use_comparability_constraint": True,
                "comparability_lambda": float(lam),
                "comparability_mode": condition["mode"],
                "comparability_neighbors": CONSTRAINT_NEIGHBORS,
                "comparability_temperature": CONSTRAINT_TEMPERATURE,
                "comparability_t_min": int(t_min),
                "comparability_mask": stratum,
            }
        )
    return config


# ---------------------------------------------------------------------------
# 부트스트랩
# ---------------------------------------------------------------------------


def paired_bootstrap_fm_difference(
    labels_treatment: np.ndarray,
    labels_baseline: np.ndarray,
    comparable: np.ndarray,
    *,
    replicates: int = BOOTSTRAP_REPLICATES,
    seed: int = BOOTSTRAP_SEED,
) -> Dict[str, Any]:
    """feature 복원 추출로 FM_precision 차이의 95% 구간을 낸다.

    docs/c3_prereg_v1.md §7.1–§7.2. 쌍은 독립이 아니다 — 한 feature 가 수천 쌍의 종단이므로
    쌍 단위 부트스트랩은 구간을 과소추정한다. 추출된 feature 가 **양 종단인** 쌍으로 지표를
    재계산한다.

    짝지은 설계다. 두 조건이 같은 점 집합에서 계산되므로 같은 feature 재표본에서 두 지표를
    함께 재고 그 차이를 본다. 방향은 §7.2 에서 단측으로 고정되어 있다 —
    처리의 FM_precision 이 더 **낮아야** 개선이다.
    """
    from ptm_shared.representation.comparability import same_cluster_matrix

    merged_treatment = same_cluster_matrix(labels_treatment)
    merged_baseline = same_cluster_matrix(labels_baseline)
    non_comparable = ~np.asarray(comparable, dtype=bool)
    np.fill_diagonal(non_comparable, False)

    n_rows = merged_treatment.shape[0]
    rng = np.random.default_rng(int(seed))
    differences = np.empty(replicates, dtype=float)
    valid = 0
    for index in range(replicates):
        rows = rng.integers(0, n_rows, size=n_rows)
        counts = np.bincount(rows, minlength=n_rows).astype(float)
        # 쌍 (i,j) 의 재표본 가중치는 두 종단의 추출 횟수의 곱이다. 상삼각만 세기 위해
        # 대각(자기 쌍)을 뺀 뒤 절반으로 나눈다.
        outer = np.outer(counts, counts)
        np.fill_diagonal(outer, 0.0)
        values = []
        for merged in (merged_treatment, merged_baseline):
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
        # 방향은 사전 고정. 처리가 더 낮아야 개선이다 (§7.2).
        "improves": bool(high < 0.0),
        "fraction_of_replicates_improving": round(float(np.mean(sample < 0.0)), 6),
    }


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------


def load_population(vector_path: Path):
    """docs/c3_prereg_v1.md §2.2 `C3_POPULATION_V1`."""
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
        "--lambda-value",
        type=float,
        default=CONSTRAINT_LAMBDA_PRIMARY,
        help="§6.3.1 primary = 1.0. 민감도 {0.3, 3.0} 은 sensitivity 전용",
    )
    parser.add_argument(
        "--t-min",
        type=int,
        default=T_MIN_PRIMARY,
        help="§2.1 primary = 4. {3, 5} 는 E12 민감도 전용",
    )
    parser.add_argument("--skip-probe", action="store_true", help="G3 생략 (진단 실행용)")
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
    if not vector.exists():
        print(f"FATAL: {vector} 없음", file=sys.stderr)
        return 2
    if not raw_matrix.exists():
        print(f"FATAL: {raw_matrix} 없음 — rep≥2 계층을 만들 수 없다", file=sys.stderr)
        return 2

    multiview = load_population(vector)
    config = dict(DEFAULT_BENCHMARK_CONFIG)
    config.update(BENCHMARK_OVERRIDES)
    arm = resolve_variant(JUDGED_ARM)

    stratum, join = replicate_stratum_mask(multiview, raw_matrix, minimum_replicates=2)
    if not join["path_a_viable"]:
        print(f"FATAL: 결합률 {join['join_rate']} < {join['join_rate_floor']} — §3.1 경로 (a) 폐기")
        return 3
    t_min = int(args.t_min)
    comparable = comparability_matrix(stratum, t_min)

    lam = float(args.lambda_value)
    # primary 는 λ 와 T_min 이 **둘 다** 사전등록 값일 때만 성립한다 (§6.3.1, §2.1).
    is_primary = lam == CONSTRAINT_LAMBDA_PRIMARY and t_min == T_MIN_PRIMARY
    print(f"order      = {args.order_code}")
    print(f"arm        = {JUDGED_ARM}   n = {multiview.n_sites}   T = {multiview.n_timepoints}")
    print(f"계층       = rep≥2  (결합률 {join['join_rate']:.4f})   T_min = {t_min}"
          f"{'' if t_min == T_MIN_PRIMARY else '  (E12 SENSITIVITY)'}")
    print(f"λ          = {lam}   {'primary' if is_primary else 'SENSITIVITY (판정 아님)'}")
    print(f"seed       = {list(ENCODER_SEEDS)}   epochs = {ENCODER_BASE['epochs']}")
    print(f"대조 항    = InfoNCE  T = {CONSTRAINT_TEMPERATURE}  k = {CONSTRAINT_NEIGHBORS}\n")

    results: Dict[str, Any] = {
        "experiment": "E9",
        "declaration": "docs/c3_prereg_v1.md",
        "order_code": args.order_code,
        "arm": JUDGED_ARM,
        "n_sites": int(multiview.n_sites),
        "stratum": "rep>=2",
        "t_min": t_min,
        "lambda": lam,
        "lambda_is_primary": lam == CONSTRAINT_LAMBDA_PRIMARY,
        "t_min_is_primary": t_min == T_MIN_PRIMARY,
        "judgement_is_primary": is_primary,
        "encoder_seeds": list(ENCODER_SEEDS),
        "replicate_join": join,
        "thresholds": {
            "g1a_min": G1_THRESHOLD,
            "g1b_min": G1_THRESHOLD,
            "g2_min": G2_THRESHOLD,
            "g3_min": G3_THRESHOLD,
            "empty_positive_row_max": EMPTY_POSITIVE_ROW_MAX,
        },
    }

    # ---- 적합 ---------------------------------------------------------------
    print("=" * 92)
    print("적합 — 3 조건 × seed 2")
    print("=" * 92)
    fits: Dict[Tuple[str, int], Dict[str, Any]] = {}
    started = time.time()
    for condition in arm_configurations():
        for seed in ENCODER_SEEDS:
            begin = time.time()
            fit = fit_variant(
                multiview,
                arm,
                encoder_config=encoder_config(condition, seed, stratum, lam, t_min),
                config=config,
            )
            labels = cluster_representation(
                fit.embedding,
                distance_threshold=config["cluster_distance_threshold"],
                minimum_cluster_size=config["minimum_cluster_size"],
            )
            metrics = false_merge(labels, comparable)
            record = (fit.provenance or {}).get("comparability_constraint")
            fits[(condition["name"], seed)] = {
                "embedding": fit.embedding,
                "labels": labels,
                "false_merge": metrics,
                "constraint": record,
                "n_clusters": int(len({int(x) for x in labels.tolist() if x != 0})),
            }
            precision = metrics["fm_precision"]
            print(
                f"  {condition['name']:<26} seed {seed}  "
                f"군집 {fits[(condition['name'], seed)]['n_clusters']:>4}  "
                f"병합쌍 {metrics['n_merged_pairs']:>10,}  "
                f"FM_prec {(f'{precision:.5f}' if precision is not None else 'n/a'):>9}  "
                f"({time.time() - begin:.0f}s)"
            )
    print(f"\n  총 소요 {time.time() - started:.0f}s\n")

    baseline0 = fits[("baseline0_no_contrastive", ENCODER_SEEDS[0])]
    baseline1 = fits[("baseline1_unconstrained", ENCODER_SEEDS[0])]
    treatment = fits[("treatment_constrained", ENCODER_SEEDS[0])]

    results["conditions"] = {
        f"{name}|seed{seed}": {
            "n_clusters": value["n_clusters"],
            "false_merge": value["false_merge"],
            "constraint": value["constraint"],
        }
        for (name, seed), value in fits.items()
    }

    # ---- 자명성 검사 (판정 전) ---------------------------------------------
    print("=" * 92)
    print("자명성 검사 — docs/c3_prereg_v1.md §6.3.2. 판정 전에 확인한다")
    print("=" * 92)
    s1_ari = pair_restricted_ari(baseline1["labels"], baseline0["labels"], comparable)
    s1_within_noise = (
        s1_ari is not None and SEED_NOISE_ARI_RANGE[0] <= s1_ari <= SEED_NOISE_ARI_RANGE[1]
    )
    constraint_record = treatment["constraint"] or {}
    empty_fraction = constraint_record.get("empty_positive_fraction")
    s2_survives = bool(constraint_record.get("loss_survives", False))
    print(f"  S1  기준선1 대 기준선0 비교가능 ARI = "
          f"{(f'{s1_ari:.6f}' if s1_ari is not None else 'n/a')}"
          f"   seed 잡음 범위 {SEED_NOISE_ARI_RANGE}")
    print(f"      → 대조 항이 {'구별되지 않는다 (λ 너무 약함)' if s1_within_noise else '임베딩을 바꿨다'}")
    print(f"  S2  제약 후 양성 빈 행 비율 = {empty_fraction}   임계 {EMPTY_POSITIVE_ROW_MAX}")
    print(f"      → {'손실이 살아 있다' if s2_survives else '데이터 삭제. E9 를 판정에 쓰지 않는다'}")
    print(f"      제약이 제거한 후보 쌍 = "
          f"{constraint_record.get('n_candidate_pairs_removed_by_constraint'):,}")
    print(f"      유효 행 = {constraint_record.get('n_valid_rows'):,}"
          f"   양성/행 평균 = {constraint_record.get('mean_positives_per_row')}\n")
    results["triviality"] = {
        "s1_contrastive_changed_embedding": bool(not s1_within_noise),
        "s1_baseline1_vs_baseline0_ari": (round(s1_ari, 6) if s1_ari is not None else None),
        "s1_seed_noise_range": list(SEED_NOISE_ARI_RANGE),
        "s2_loss_survives": s2_survives,
        "s2_empty_positive_fraction": empty_fraction,
    }

    # ---- primary 판정 ------------------------------------------------------
    print("=" * 92)
    print("primary — 처리 대 기준선 1 (무제약 대조 손실).  기준선 0 과의 비교는 C3 의 기여가 아니다")
    print("=" * 92)
    treated_metrics = treatment["false_merge"]
    baseline_metrics = baseline1["false_merge"]
    print(f"  FM_precision   기준선1 {baseline_metrics['fm_precision']}"
          f"   →  처리 {treated_metrics['fm_precision']}")
    print(f"  병합 쌍        기준선1 {baseline_metrics['n_merged_pairs']:,}"
          f"   →  처리 {treated_metrics['n_merged_pairs']:,}")
    print(f"  false merge    기준선1 {baseline_metrics['n_false_merges']:,}"
          f"   →  처리 {treated_metrics['n_false_merges']:,}")

    started = time.time()
    bootstrap = paired_bootstrap_fm_difference(
        treatment["labels"], baseline1["labels"], comparable
    )
    results["primary"] = {
        "baseline1": baseline_metrics,
        "treatment": treated_metrics,
        "bootstrap": bootstrap,
    }
    if bootstrap["status"] == "evaluated":
        print(f"\n  짝지은 부트스트랩 ({bootstrap['n_replicates']} 반복, feature 단위)")
        print(f"    평균 차이  {bootstrap['mean_difference']:+.6f}   (음수 = 개선)")
        print(f"    95% 구간   [{bootstrap['ci95_low']:+.6f}, {bootstrap['ci95_high']:+.6f}]")
        print(f"    개선 판정  {'예' if bootstrap['improves'] else '아니오 (구간이 0 을 포함)'}")
    print(f"  소요 {time.time() - started:.0f}s\n")

    # ---- 동반 지표 ---------------------------------------------------------
    print("=" * 92)
    print("동반 지표 — docs/c3_prereg_v1.md §5.2. FM 과 **동시에** 판정한다")
    print("=" * 92)
    g1a = pair_restricted_ari(treatment["labels"], baseline1["labels"], comparable)
    g1b = pair_restricted_ari(
        fits[("treatment_constrained", ENCODER_SEEDS[0])]["labels"],
        fits[("treatment_constrained", ENCODER_SEEDS[1])]["labels"],
        comparable,
    )
    baseline1_seed_ari = pair_restricted_ari(
        fits[("baseline1_unconstrained", ENCODER_SEEDS[0])]["labels"],
        fits[("baseline1_unconstrained", ENCODER_SEEDS[1])]["labels"],
        comparable,
    )
    g2 = removal_precision(baseline_metrics, treated_metrics)
    guards = {
        "g1a_structure_preservation": {
            "value": (round(g1a, 6) if g1a is not None else None),
            "threshold": G1_THRESHOLD,
            "passed": bool(g1a is not None and g1a >= G1_THRESHOLD),
        },
        "g1b_identifiability_non_regression": {
            "value": (round(g1b, 6) if g1b is not None else None),
            "threshold": G1_THRESHOLD,
            "passed": bool(g1b is not None and g1b >= G1_THRESHOLD),
            "baseline1_seed_ari": (
                round(baseline1_seed_ari, 6) if baseline1_seed_ari is not None else None
            ),
        },
        "g2_removal_precision": {
            **g2,
            "threshold": G2_THRESHOLD,
            "passed": bool(
                g2["status"] == "no_shrinkage"
                or (g2.get("removal_precision") or 0.0) >= G2_THRESHOLD
            ),
        },
    }
    print(f"  G1a 구조 보존      {guards['g1a_structure_preservation']['value']}"
          f"   ≥ {G1_THRESHOLD}   "
          f"{'통과' if guards['g1a_structure_preservation']['passed'] else '미달'}")
    print(f"  G1b 식별성 비퇴행  {guards['g1b_identifiability_non_regression']['value']}"
          f"   ≥ {G1_THRESHOLD}   "
          f"{'통과' if guards['g1b_identifiability_non_regression']['passed'] else '미달'}"
          f"   (기준선1 의 같은 값 {baseline1_seed_ari})")
    print(f"  G2  제거 표적성    {g2.get('removal_precision')}   ≥ {G2_THRESHOLD}   "
          f"{'통과' if guards['g2_removal_precision']['passed'] else '미달'}")
    print(f"      제거된 병합 {g2.get('delta_merged_pairs'):,}"
          f"   그중 false merge {g2.get('delta_false_merges'):,}"
          f"   무작위 기대 {g2.get('random_removal_expectation')}")

    if args.skip_probe:
        guards["g3_fair_probe"] = {"status": "skipped", "threshold": G3_THRESHOLD, "passed": False}
        print("  G3  공정 프로브    생략 (--skip-probe)\n")
    else:
        started = time.time()
        from ptm_shared.representation.fair_probe import run_heldout_timepoint_probe

        probe = run_heldout_timepoint_probe(
            multiview,
            encoder_config=encoder_config(
                {"use": True, "mode": MODE_CONSTRAINED}, ENCODER_SEEDS[0], stratum, lam, t_min
            ),
            config={"arms": ("B", JUDGED_ARM), "baseline_arm": "B"},
        )
        comparison = (probe.get("comparisons", {}).get("arms", {}) or {}).get(JUDGED_ARM, {})
        delta = comparison.get("mean_r2_difference")
        guards["g3_fair_probe"] = {
            "status": probe.get("status"),
            "mean_r2_difference": delta,
            "sign_flip_p_value": comparison.get("sign_flip_p_value"),
            "n_paired_folds": comparison.get("n_paired_folds"),
            "verdict": comparison.get("verdict"),
            "threshold": G3_THRESHOLD,
            "passed": bool(delta is not None and delta >= G3_THRESHOLD),
        }
        print(f"  G3  공정 프로브 ΔR² {delta}   ≥ {G3_THRESHOLD}   "
              f"{'통과' if guards['g3_fair_probe']['passed'] else '미달'}"
              f"   (p = {comparison.get('sign_flip_p_value')}, "
              f"{comparison.get('n_paired_folds')} fold, {time.time() - started:.0f}s)\n")

    results["guards"] = guards

    # ---- 결합 판정 ---------------------------------------------------------
    print("=" * 92)
    print("결합 판정 — docs/c3_prereg_v1.md §5.3. 논리곱이며 OR 성공은 금지된다")
    print("=" * 92)
    primary_improves = bool(bootstrap.get("improves", False))
    all_guards = all(entry["passed"] for entry in guards.values())
    blocked = (not s2_survives) or (not is_primary)
    verdict = {
        "primary_fm_improves": primary_improves,
        "all_guards_passed": all_guards,
        "evaluable": bool(s2_survives and is_primary),
        "c3_success": bool(primary_improves and all_guards and not blocked),
    }
    results["verdict"] = verdict
    for name, entry in guards.items():
        print(f"  {'통과' if entry['passed'] else '미달'}  {name}")
    print(f"  {'통과' if primary_improves else '미달'}  primary FM_precision 개선")
    if not is_primary:
        detail = []
        if lam != CONSTRAINT_LAMBDA_PRIMARY:
            detail.append(f"λ = {lam} (§6.3.1)")
        if t_min != T_MIN_PRIMARY:
            detail.append(f"T_min = {t_min} (§2.1)")
        print(f"\n  ** {', '.join(detail)} 는 sensitivity 다. 이 실행은 판정에 쓰이지 않는다 **")
    elif not s2_survives:
        print("\n  ** S2 미달 — 처리는 제약이 아니라 데이터 삭제다. 판정 불가 (§6.3.2) **")
    else:
        print(f"\n  C3 = {'성공' if verdict['c3_success'] else '실패'}"
              f"   (§5.3 의 다섯 조건 논리곱)")
    print()

    payload = json.dumps(results, ensure_ascii=False, default=str)
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
        print(f"산출 기록: {args.output}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
