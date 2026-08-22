"""Measure the three quantities C2 pre-registration must fix before freezing.

구현 대상: docs/c2_prereg_v1.md §14 동결 전 필수 완료 항목
          §2.3 (induced 표적 영값 편중), §1.3 (다중 seed 출발점), §14.1 (차원 민감도)
사전등록: 2026-08-21. 이 스크립트는 **adversary 도입 전 상태**를 측정한다. 판정 임계는
          이미 §14.2에서 승인·동결되었고 여기서 새 임계를 도입하지 않는다. 측정되는 값은
          C2 실험의 **비교 기준선**이며 C2 성공/실패 판정이 아니다.
해석 한계: 측정되는 것은 배포된 gate 지표가 seed 실현과 임베딩 차원에 얼마나 민감한지,
          그리고 회귀 표적이 무엇으로 구성되어 있는지다. 표현이 좋은지 나쁜지는 다루지 않는다.
          차원 민감도 대조는 주성분 절단이라는 특정 방식의 차원 축소만 다루며, arm A와
          arm D의 차이를 차원으로 설명할 수 있는지에 대한 **필요조건 검사**일 뿐이다.
주장 금지: 이 측정으로 coverage 분리가 개선되었다고 서술하지 않는다. adversary는 아직 없다.
          seed 간 변동이 작다는 것을 gate 의 타당성 근거로 쓰지 않는다.

정본 환경 — scipy 가 필요하므로 preprocessing worker 안에서 실행한다:

    docker exec -i ptm-worker-preprocessing env PYTHONPATH=/app:/opt python - \
        --order-code Insulin_Signaling_Phosphoproteomics_HIRc-B \
        < scripts/measure_c2_prefreeze.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path[:0] = ["/app", "/opt"]

import numpy as np

# §14.2 에서 승인·동결된 값. 여기서 바꾸지 않는다.
GATE_INDUCED_R2_MAX = 0.25
"""missingness_validity 의 coverage 하위 조건 임계.

docs/c2_prereg_v1.md §1.1 에서 인용, 원 선언은 benchmark.py DEFAULT_BENCHMARK_CONFIG.
2026-08-21 승인. 변경 금지 — 변경하면 (a) 판정이 무효가 된다.
"""

GATE_RETENTION_ARI_MIN = 0.20
"""missingness_validity 의 패턴 보존 하위 조건 임계. 출처·지위는 위와 동일."""

EVAL_SEEDS = (0, 1, 2, 3, 4)
"""INDUCED_MASK_SEED_SET_V1.

docs/c2_prereg_v1.md §1.3 에서 2026-08-21 선언. C2 측정 착수 전.
seed 를 늘려 재판정하는 것을 금지한다.
"""

TRUNCATION_RANKS = (4, 8, 12, 16)
"""차원 민감도 대조의 절단 차원.

docs/c2_prereg_v1.md §14.1 에서 2026-08-21 선언. 12 는 arm A 의 차원, 16 은 절단 없음.
"""

ARM_A_INDUCED_R2 = 0.007345
"""arm A(track2_trajectory_only, 12차원)의 induced R². 비교 기준.

출처: data/outputs/.../ptm_representation_benchmark_phospho.json (2026-08-20 이전 산출).
재측정하지 않는다.
"""

STORED_D_INDUCED_R2 = 0.462393
STORED_D_RETENTION_ARI = 0.035002
"""seed 0 의 공표값. 재현 확인용 — 불일치하면 이 스크립트가 gate 경로를 잘못 재현한 것이다."""


def load_multiview(vector_path: Path):
    import pandas as pd

    from ptm_shared.representation import build_multiview_input, validate_multiview_input

    frame = pd.read_csv(vector_path, sep="\t", low_memory=False)
    if frame.empty:
        raise RuntimeError(f"{vector_path} is empty")
    multiview = build_multiview_input(
        frame.to_dict("records"),
        # 공표 산출물의 config 와 동일. key_level="form" 이 DEFAULT_CONFIG 값이다.
        config={"key_level": "form", "minimum_observed_timepoints": 3},
    )
    errors = validate_multiview_input(multiview)
    if errors:
        raise RuntimeError(f"L3 input contract violations: {errors}")
    return multiview


def truncate_to_rank(embedding: np.ndarray, rank: int) -> np.ndarray:
    """Keep the top-``rank`` principal components of ``embedding``."""
    values = np.nan_to_num(np.asarray(embedding, dtype=float), nan=0.0)
    if rank >= values.shape[1]:
        return values
    centred = values - values.mean(axis=0, keepdims=True)
    _, _, vt = np.linalg.svd(centred, full_matrices=False)
    return centred @ vt[:rank].T


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--order-code", required=True)
    parser.add_argument("--data-root", default="/app/data")
    parser.add_argument("--arm", default="D")
    args = parser.parse_args(argv)

    from ptm_shared.representation.benchmark import (
        DEFAULT_BENCHMARK_CONFIG,
        _missingness_r2,
        adjusted_rand_index,
        cluster_representation,
        fit_variant,
    )
    from ptm_shared.representation.layers import resolve_variant

    outputs = Path(args.data_root) / "outputs" / args.order_code
    # 공표 산출물의 source_vector_file 과 동일한 파일을 쓴다. 다른 파일을 쓰면 재현이 아니다.
    vector = outputs / "ptm_vector_data_normalized_phospho.tsv"
    if not vector.exists():
        print(f"FATAL: {vector} 없음. 공표 산출물의 source_vector_file 과 불일치", file=sys.stderr)
        return 2

    print(f"order      = {args.order_code}")
    print(f"vector     = {vector}")
    multiview = load_multiview(vector)
    # 공표 산출물은 적격 site 만 평가했다 (n_sites_total 2819 → n_sites_eligible 2744).
    # 이 축소를 건너뛰면 gate 수치가 재현되지 않는다.
    print(f"n_sites    = {multiview.n_sites} (전체) → ", end="")
    multiview = multiview.eligible_subset()
    print(f"{multiview.n_sites} (적격)   T = {multiview.n_timepoints}")
    print(f"key_level  = {multiview.provenance.get('key_level')}")
    print(f"numpy      = {np.__version__}")
    print()

    # 공표 산출물을 만든 호출과 **동일한** 인자.
    # 출처: workers/preprocessing/core/ptm_representation_learning.py
    #       _run_bounded_ablation() + DEFAULT_CONFIG
    # epochs 는 benchmark_epochs = 150 이며 주 인코더의 300 이 아니다.
    # 이 값을 바꾸면 공표 gate 수치가 재현되지 않는다.
    ablation_encoder_config = {
        "latent_dim": 16,
        "hidden_dim": 64,
        "epochs": 150,
        "seed": 0,
        "n_perturbations": 5,
    }
    config = dict(DEFAULT_BENCHMARK_CONFIG)
    config.update({"neighbors": 10, "leave_one_out": False, "minimum_sites": 8, "seed": 0})

    arm = resolve_variant(args.arm)
    reference = fit_variant(
        multiview, arm, encoder_config=ablation_encoder_config, config=config
    )
    reference_labels = cluster_representation(
        reference.embedding,
        distance_threshold=config["cluster_distance_threshold"],
        minimum_cluster_size=config["minimum_cluster_size"],
    )
    print(
        f"unmasked fit: dim={reference.embedding.shape[1]}"
        f" clusters={len({x for x in reference_labels.tolist() if x != 0})}"
    )
    print()

    # ---------------------------------------------------------------- §2.3 + §1.3
    print("=" * 78)
    print("§2.3 induced 표적 영값 편중  /  §1.3 다중 seed 출발점")
    print("=" * 78)
    header = (
        f"{'seed':>4} {'masked_sites':>12} {'zero_sites':>10} {'zero_frac':>9}"
        f" {'entries':>8} {'ret_ARI':>9} {'induced_R2':>10} {'gate':>6}"
    )
    print(header)

    per_seed = []
    masked_fits = {}
    for seed in EVAL_SEEDS:
        masked_input, induced = multiview.with_additional_target_masking(
            fraction=config["artificial_mask_fraction"], seed=seed
        )
        rate = induced.mean(axis=1)
        n_zero = int(np.sum(rate <= 0.0))
        n_masked_sites = int(rate.size - n_zero)

        # gate 경로와 동일: 호출자 encoder_config 를 복사하고 n_perturbations 만 0 으로.
        masked_encoder = dict(ablation_encoder_config)
        masked_encoder["n_perturbations"] = 0
        masked_fit = fit_variant(masked_input, arm, encoder_config=masked_encoder, config=config)
        masked_labels = cluster_representation(
            masked_fit.embedding,
            distance_threshold=config["cluster_distance_threshold"],
            minimum_cluster_size=config["minimum_cluster_size"],
        )
        retention = adjusted_rand_index(reference_labels, masked_labels)
        induced_r2 = _missingness_r2(masked_fit.embedding, rate)
        passed = (
            retention is not None
            and induced_r2 is not None
            and float(retention) >= GATE_RETENTION_ARI_MIN
            and float(induced_r2) <= GATE_INDUCED_R2_MAX
        )
        masked_fits[seed] = (masked_fit.embedding, rate)
        per_seed.append(
            {
                "seed": seed,
                "n_masked_sites": n_masked_sites,
                "n_zero_sites": n_zero,
                "zero_fraction": round(n_zero / max(rate.size, 1), 6),
                "n_masked_entries": int(induced.sum()),
                "pattern_retention_ari": None if retention is None else round(float(retention), 6),
                "induced_missingness_r2": induced_r2,
                "passed": bool(passed),
                "target_nonzero_quantiles": (
                    [round(float(q), 6) for q in np.percentile(rate[rate > 0], [25, 50, 75])]
                    if n_masked_sites
                    else None
                ),
            }
        )
        row = per_seed[-1]
        print(
            f"{seed:>4} {row['n_masked_sites']:>12} {row['n_zero_sites']:>10}"
            f" {row['zero_fraction']:>9.4f} {row['n_masked_entries']:>8}"
            f" {row['pattern_retention_ari']:>9} {row['induced_missingness_r2']:>10}"
            f" {'PASS' if row['passed'] else 'FAIL':>6}"
        )

    ari_values = [r["pattern_retention_ari"] for r in per_seed if r["pattern_retention_ari"] is not None]
    r2_values = [r["induced_missingness_r2"] for r in per_seed if r["induced_missingness_r2"] is not None]
    n_pass = sum(1 for r in per_seed if r["passed"])
    median_ari = float(np.median(ari_values))
    median_r2 = float(np.median(r2_values))
    print()
    print(
        f"retention ARI  median={median_ari:.6f}  min={min(ari_values):.6f}  max={max(ari_values):.6f}"
    )
    print(
        f"induced R2     median={median_r2:.6f}  min={min(r2_values):.6f}  max={max(r2_values):.6f}"
    )
    print(f"개별 통과 {n_pass}/{len(per_seed)}   중위수 통과 = "
          f"{median_ari >= GATE_RETENTION_ARI_MIN and median_r2 <= GATE_INDUCED_R2_MAX}")
    print()

    seed0 = next(r for r in per_seed if r["seed"] == 0)
    d_ari = abs((seed0["pattern_retention_ari"] or 0.0) - STORED_D_RETENTION_ARI)
    d_r2 = abs((seed0["induced_missingness_r2"] or 0.0) - STORED_D_INDUCED_R2)
    print(f"공표값 재현 확인 (seed 0): |Δ ARI| = {d_ari:.6g}   |Δ R²| = {d_r2:.6g}")
    print(f"  공표 ARI {STORED_D_RETENTION_ARI}  R² {STORED_D_INDUCED_R2}")
    if max(d_ari, d_r2) > 1e-6:
        print("  ** 불일치 — gate 경로 재현이 정확하지 않다. 아래 결과를 신뢰하지 말 것 **")
    else:
        print("  일치")
    print()

    # ------------------------------------------------------- §2.3 구조 (seed 0)
    print("=" * 78)
    print("§2.3 induced 표적의 구조 — 관측 시점 수와의 교란 (seed 0)")
    print("=" * 78)
    _, rate0 = masked_fits[0]
    observed_counts = multiview.target.observed.sum(axis=1)
    values, counts = np.unique(np.round(rate0 * multiview.n_timepoints).astype(int), return_counts=True)
    print("표적이 취하는 값 (마스킹된 항목 수):")
    for value, count in zip(values.tolist(), counts.tolist()):
        print(f"  {value} 개 → 표적 {value}/{multiview.n_timepoints} :"
              f" {count:>5} site ({count / multiview.n_sites:.4f})")
    print()
    print(f"{'관측 시점':>9} {'site':>6} {'표적=0':>8} {'표적=0 비율':>12} {'평균 표적':>10}")
    strata = []
    for n_obs in sorted(set(observed_counts.tolist())):
        selector = observed_counts == n_obs
        n_stratum = int(selector.sum())
        n_zero_stratum = int(np.sum(rate0[selector] <= 0.0))
        strata.append(
            {
                "observed_timepoints": int(n_obs),
                "n_sites": n_stratum,
                "n_zero_target": n_zero_stratum,
                "zero_fraction": round(n_zero_stratum / max(n_stratum, 1), 6),
                "mean_target": round(float(rate0[selector].mean()), 6),
            }
        )
        row = strata[-1]
        print(
            f"{n_obs:>9} {n_stratum:>6} {n_zero_stratum:>8}"
            f" {row['zero_fraction']:>12.4f} {row['mean_target']:>10.4f}"
        )
    print()
    print("해석: 마스킹 자격이 관측 시점 수에 의존한다(minimum_remaining=3). 따라서 induced")
    print("      표적은 natural coverage 와 구조적으로 상관되며, 두 지표는 독립이 아니다.")
    print()

    # ------------------------------------------------------------------- §14.1
    print("=" * 78)
    print("§14.1 차원 민감도 대조 — D 임베딩 주성분 절단 (seed 0)")
    print("=" * 78)
    embedding, rate = masked_fits[0]
    print(f"{'rank':>5} {'induced_R2':>11}   비교: arm A(12차원) = {ARM_A_INDUCED_R2}")
    truncation = []
    for rank in TRUNCATION_RANKS:
        value = _missingness_r2(truncate_to_rank(embedding, rank), rate)
        truncation.append({"rank": rank, "induced_missingness_r2": value})
        print(f"{rank:>5} {value:>11}")
    at_12 = next(t["induced_missingness_r2"] for t in truncation if t["rank"] == 12)
    print()
    if at_12 is not None and at_12 > 4.0 * ARM_A_INDUCED_R2:
        print(f"판정: rank 12 에서 R² = {at_12} 로 arm A({ARM_A_INDUCED_R2}) 근처로 내려가지 않았다.")
        print("      → §2.1 관찰 유지. 0.007 대 0.462 는 차원 차이로 설명되지 않는다.")
    else:
        print(f"판정: rank 12 에서 R² = {at_12} 로 arm A 수준에 접근했다.")
        print("      → §2.1 의 (1)·(2) 를 철회하고 차원 효과로 재서술해야 한다.")
    print()

    # -------------------------------------------------------------------- §4.1
    print("=" * 78)
    print("§4.1 예측기族 P2–P5 — 구현 확인 및 adversary 도입 전 기준선 (seed 0)")
    print("=" * 78)
    from ptm_shared.representation.coverage_probes import residual_mask_recoverability

    family = residual_mask_recoverability(embedding, rate)
    if family.get("status") != "evaluated":
        print(f"  status={family.get('status')} — {family.get('detail')}")
    else:
        print(f"{'predictor':>22} {'OOS R2':>9} {'null mean':>10} {'null max':>9} {'excess':>9}")
        for name, values in family["per_predictor"].items():
            print(
                f"{name:>22} {values['out_of_sample_r2']:>9} {values['permutation_null_mean']:>10}"
                f" {values['permutation_null_max']:>9} {values['excess_over_null']:>9}"
            )
        maximum = family["family_max_out_of_sample_r2"]
        print()
        print(f"族 최대 표본 외 R² = {maximum}   임계 {GATE_INDUCED_R2_MAX}"
              f"  → (c) {'통과' if maximum is not None and maximum <= GATE_INDUCED_R2_MAX else '미충족'}")
        print(f"참고: P1 표본 내 선형 = {seed0['induced_missingness_r2']} (gate 지표)")
    print()

    print("=" * 78)
    print(
        json.dumps(
            {
                "per_seed": per_seed,
                "target_strata": strata,
                "truncation": truncation,
                "predictor_family": family,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
