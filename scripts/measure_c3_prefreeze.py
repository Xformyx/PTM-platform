"""C3 동결 전 실측 4건 — 기술 통계만. 판정 임계를 만들지 않는다.

구현 대상: docs/c3_prereg_v1.md §12.1 (replicate 계층 결합), §12.2 (기저 FM_precision),
          §12.3 (n_eff 재측정), §12.4 (병합 규모 기저)
사전등록: 2026-08-22 초안. **이 스크립트는 무제약 기저만 측정한다.** 제약 적용 후의 값을
          보지 않으므로, 여기서 나온 값에 근거해 §13 에서 G1·G2 임계를 정하는 것은
          사후 선택이 아니다 (§12.5 의 논거).
해석 한계: 단일 코호트(HIRc-B, T = 6, form 단위). 여기서 나오는 FM 값은 **무제약 표현이
          근거 없는 유사성을 얼마나 주장하는가**이며 표현 품질의 종합 평가가 아니다.
          `O_ij = 0` 은 유사성 판단 근거의 부재이고 비유사성의 증거가 아니다 (§1.1).
주장 금지: "arm X 의 FM 이 낮으므로 X 가 우수하다". FM 단독은 군집을 잘게 쪼개 낮출 수
          있으므로 §5 동반 지표 없이는 비교 근거가 되지 않는다.
          "비교 불가 쌍이 서로 다르다".

정본 환경:

    docker cp scripts/measure_c3_prefreeze.py ptm-worker-preprocessing:/tmp/c3pre.py
    docker exec -i ptm-worker-preprocessing env PYTHONPATH=/app:/opt python /tmp/c3pre.py \
        --order-code Insulin_Signaling_Phosphoproteomics_HIRc-B
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path[:0] = ["/app", "/opt"]

import numpy as np

T_MIN_GRID = (3, 4, 5)
T_MIN_PRIMARY = 4
"""docs/c3_prereg_v1.md §2.1. primary = 4, 나머지는 sensitivity 전용."""

ARMS = ("A", "B", "D", "E")

ENCODER_BASE = {"latent_dim": 16, "hidden_dim": 64, "epochs": 150, "seed": 0,
                "n_perturbations": 5}
BENCHMARK_OVERRIDES = {"neighbors": 10, "leave_one_out": False, "minimum_sites": 8}
"""c2_prereg_v1.md §1.1 의 ablation 설정. C3 이 새로 정하지 않고 인용한다."""

G1_NOISE_SEEDS = (0, 1, 2)
"""G1(비교 가능 쌍 ARI) 의 잡음 하한을 재기 위한 인코더 seed. 제약 없이 seed 만 바꾼
두 적합 사이의 ARI 가 G1 임계의 하한을 정한다 — 그보다 낮은 임계는 잡음과 구별되지 않는다.
"""


from ptm_shared.representation.comparability import (  # noqa: E402
    comparability_matrix,
    distance_rank_agreement,
    false_merge,
    kish_n_eff,
    pair_restricted_ari,
    subspace_alignment,
    upper_triangle as _upper_triangle,
)
from ptm_shared.representation.replicate_stratum import (  # noqa: E402
    JOIN_RATE_FLOOR,
    replicate_stratum_mask,
)


# ---------------------------------------------------------------------------
# §12.1  replicate 계층 결합
# ---------------------------------------------------------------------------


def measure_replicate_join(multiview, matrix_path: Path) -> Tuple[np.ndarray, Dict[str, Any]]:
    """§12.1 — replicate 계층을 표현 입력에 결합할 수 있는가.

    정의는 `ptm_shared.representation.replicate_stratum` 에 있다. 이 스크립트가 사본을 갖지
    않는 이유: E9 실행기도 같은 계층을 만들어야 하고, 두 곳에 사본이 있으면 한쪽만 고쳐도
    아무 테스트가 실패하지 않는다.
    """
    return replicate_stratum_mask(multiview, matrix_path, minimum_replicates=2)


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------


def load_population(vector_path: Path):
    """docs/c3_prereg_v1.md §2.2 `C3_POPULATION_V1` = c2_prereg_v1.md §1.1 과 동일."""
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--order-code", required=True)
    parser.add_argument("--data-root", default="/app/data")
    parser.add_argument("--skip-arms", action="store_true",
                        help="§12.1·12.3 만 측정 (arm 적합 생략)")
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

    multiview = load_population(vector)
    observed = multiview.target.observed
    n_sites = observed.shape[0]
    config = dict(DEFAULT_BENCHMARK_CONFIG)
    config.update(BENCHMARK_OVERRIDES)

    print(f"order   = {args.order_code}")
    print(f"단위    = form (C3_POPULATION_V1)   n = {n_sites}   T = {multiview.n_timepoints}")
    print(f"시점    = {list(multiview.timepoints)}")
    print(f"T_min   = {list(T_MIN_GRID)}  (primary {T_MIN_PRIMARY})")
    print()

    results: Dict[str, Any] = {
        "order_code": args.order_code,
        "n_sites": int(n_sites),
        "n_timepoints": int(multiview.n_timepoints),
        "timepoints": list(multiview.timepoints),
        "t_min_grid": list(T_MIN_GRID),
        "t_min_primary": T_MIN_PRIMARY,
    }

    # ---- §12.1  replicate 계층 결합 ------------------------------------
    print("=" * 88)
    print("§12.1  replicate 계층 결합 가능성 (A7)")
    print("=" * 88)
    rep2_mask: Optional[np.ndarray] = None
    if not raw_matrix.exists():
        print(f"  원 matrix 없음: {raw_matrix}")
        print("  → 경로 (a) 검증 불가. §3.1 (c) 로 이동해야 한다")
        results["replicate_join"] = {"status": "raw_matrix_missing", "path": str(raw_matrix)}
    else:
        started = time.time()
        rep2_mask, join = measure_replicate_join(multiview, raw_matrix)
        results["replicate_join"] = join
        source = join["source"]
        print(f"  전구체 행            {source['n_precursor_rows']:,}")
        print(f"  distinct form        {source['n_distinct_modified_sequences']:,}")
        print(f"  시점별 run 수        {source['runs_per_timepoint']}")
        if source["timepoints_without_runs"]:
            print(f"  run 없는 시점        {source['timepoints_without_runs']}")
        if source["unmatched_columns_ignored"]:
            print(f"  무시된 run 그룹      {source['unmatched_columns_ignored']}")
        print(f"  결합률               {join['join_rate']:.4f}"
              f"  (하한 {JOIN_RATE_FLOOR})   → 경로 (a) "
              f"{'가능' if join['path_a_viable'] else '폐기'}")
        print(f"  결합 {join['n_joined']:,} / 탈락 {join['n_dropped']:,}")
        print(f"  탈락 form 평균 관측  {join['dropped_mean_observed_timepoints']}"
              f"   (결합 form {join['joined_mean_observed_timepoints']})")
        print(f"  observed vs rep≥1 불일치율   {join['observed_vs_rep1_disagreement']}")
        print(f"  관측 중 rep≥2 비율           {join['rep2_share_of_observed']}")
        print(f"  평균 관측 시점  rep≥1 {join['mean_observed_timepoints_rep1']}"
              f"   rep≥2 {join['mean_observed_timepoints_rep2']}")
        print(f"  소요 {time.time() - started:.0f}s")
    print()

    # ---- §12.3  n_eff ---------------------------------------------------
    print("=" * 88)
    print("§12.3  n_eff 재측정 — 비교 불가 그래프의 Kish 실효 cluster 수")
    print("=" * 88)
    n_pairs_total = n_sites * (n_sites - 1) // 2
    strata: List[Tuple[str, np.ndarray]] = [("rep>=1", observed)]
    if rep2_mask is not None:
        # §7.3 이 "유일하게 판정 가능"하다고 선언한 계층. rep>=1 은 사용 금지 계층이다.
        strata.append(("rep>=2", rep2_mask))
    comparability: Dict[Tuple[str, int], np.ndarray] = {}
    n_eff_records: List[Dict[str, Any]] = []
    print(f"{'계층':>8} {'T_min':>6} {'비교불가쌍':>12} {'전역비율':>10} {'edge feat':>10}"
          f" {'n_eff':>9} {'max deg':>8} {'상관(deg,관측)':>15}")
    for stratum_name, mask in strata:
        observed_counts = mask.sum(axis=1)
        for t_min in T_MIN_GRID:
            comparable = comparability_matrix(mask, t_min)
            comparability[(stratum_name, t_min)] = comparable
            non_comparable = ~comparable
            np.fill_diagonal(non_comparable, False)
            degrees = non_comparable.sum(axis=1)
            stats = kish_n_eff(degrees)
            n_non_comparable = int(_upper_triangle(non_comparable).sum())
            correlation = (
                float(np.corrcoef(degrees.astype(float), observed_counts.astype(float))[0, 1])
                if degrees.std() > 0 else None
            )
            # 집중 구조 (integrated_research_design_v2.md §7.2 와 같은 형태)
            order = np.argsort(-degrees)
            top1 = max(1, int(round(0.01 * n_sites)))
            top5 = max(1, int(round(0.05 * n_sites)))
            endpoint_total = float(degrees.sum())
            record = {
                "stratum": stratum_name,
                "t_min": t_min,
                "n_non_comparable_pairs": n_non_comparable,
                "global_fraction": (
                    round(n_non_comparable / n_pairs_total, 6) if n_pairs_total else None
                ),
                "correlation_degree_vs_observed": (
                    round(correlation, 4) if correlation is not None else None
                ),
                "top1pct_endpoint_share": (
                    round(float(degrees[order[:top1]].sum()) / endpoint_total, 4)
                    if endpoint_total > 0 else None
                ),
                "top5pct_mean_observed": round(float(observed_counts[order[:top5]].mean()), 4),
                "rest_mean_observed": round(float(observed_counts[order[top5:]].mean()), 4),
                **stats,
            }
            n_eff_records.append(record)
            print(f"{stratum_name:>8} {t_min:>6} {n_non_comparable:>12,}"
                  f" {record['global_fraction']:>10} {stats['n_features_with_edges']:>10,}"
                  f" {(stats['n_eff'] if stats['n_eff'] is not None else float('nan')):>9.1f}"
                  f" {stats['max_degree']:>8,} {record['correlation_degree_vs_observed']:>15}")
    results["comparability"] = n_eff_records
    print()
    print("  필요 표본 (integrated_research_design_v2.md §7.3, α=.05 power=.80 ψ=0.75):")
    print("    불일치율 5% → 578,  10% → 289,  20% → 145")
    print("  §7.3 은 rep>=1 계층 사용을 금지한다(검정력 미달). 판정 계층은 rep>=2 다.")
    print()
    judged = "rep>=2" if rep2_mask is not None else "rep>=1"
    results["judged_stratum"] = judged

    if args.skip_arms:
        print(json.dumps(results, ensure_ascii=False))
        return 0

    # ---- §12.2 / §12.4  기저 FM 과 병합 규모 -----------------------------
    print("=" * 88)
    print("§12.2 / §12.4  무제약 arm 의 기저 FM 과 병합 규모")
    print("=" * 88)
    print(f"  판정 계층 = {judged}   (§7.3)")
    print(f"{'arm':>4} {'T_min':>6} {'군집':>6} {'미배정':>8} {'병합쌍':>12}"
          f" {'false merge':>12} {'FM_prec':>9} {'FM_expo':>9}")
    arm_records: List[Dict[str, Any]] = []
    started = time.time()
    for arm_id in ARMS:
        arm = resolve_variant(arm_id)
        if arm.uses_prior_features and multiview.motif_features is None:
            print(f"{arm_id:>4}  motif 특징 없음 — 건너뜀")
            continue
        fit = fit_variant(multiview, arm, encoder_config=ENCODER_BASE, config=config)
        labels = cluster_representation(
            fit.embedding,
            distance_threshold=config["cluster_distance_threshold"],
            minimum_cluster_size=config["minimum_cluster_size"],
        )
        n_clusters = int(len({int(x) for x in labels.tolist() if x != 0}))
        unassigned = float((labels == 0).mean())
        sizes = np.bincount(labels[labels > 0]) if (labels > 0).any() else np.array([0])
        for t_min in T_MIN_GRID:
            metrics = false_merge(labels, comparability[(judged, t_min)])
            record = {
                "arm": arm_id,
                "stratum": judged,
                "t_min": t_min,
                "n_clusters": n_clusters,
                "unassigned_fraction": round(unassigned, 6),
                "max_cluster_size": int(sizes.max()),
                "mean_cluster_size": round(float(sizes[sizes > 0].mean()), 4) if (sizes > 0).any() else None,
                "embedding_dim": int(fit.embedding.shape[1]),
                **metrics,
            }
            arm_records.append(record)
            precision = record["fm_precision"]
            exposure = record["fm_exposure"]
            print(f"{arm_id:>4} {t_min:>6} {n_clusters:>6} {unassigned:>8.4f}"
                  f" {record['n_merged_pairs']:>12,} {record['n_false_merges']:>12,}"
                  f" {(f'{precision:.5f}' if precision is not None else 'n/a'):>9}"
                  f" {(f'{exposure:.5f}' if exposure is not None else 'n/a'):>9}")
    results["arm_baselines"] = arm_records
    print(f"\n  소요 {time.time() - started:.0f}s")
    print()

    # ---- G1 잡음 하한 ----------------------------------------------------
    print("=" * 88)
    print("G1 잡음 하한 — 제약 없이 인코더 seed 만 바꾼 두 적합 사이의 비교 가능 쌍 ARI")
    print("=" * 88)
    arm_d = resolve_variant("D")
    primary_comparable = comparability[(judged, T_MIN_PRIMARY)]
    seed_labels: Dict[int, np.ndarray] = {}
    seed_embeddings: Dict[int, np.ndarray] = {}
    for seed in G1_NOISE_SEEDS:
        encoder = dict(ENCODER_BASE)
        encoder["seed"] = seed
        fit = fit_variant(multiview, arm_d, encoder_config=encoder, config=config)
        seed_embeddings[seed] = fit.embedding
        seed_labels[seed] = cluster_representation(
            fit.embedding,
            distance_threshold=config["cluster_distance_threshold"],
            minimum_cluster_size=config["minimum_cluster_size"],
        )
    noise: List[Dict[str, Any]] = []
    print(f"{'seed 쌍':>10} {'전체 ARI':>10} {'비교가능 ARI':>14} {'거리순위(표준화)':>18}"
          f" {'거리순위(원본)':>16} {'열공간 정렬':>13}")
    for index, left in enumerate(G1_NOISE_SEEDS):
        for right in G1_NOISE_SEEDS[index + 1:]:
            full = pair_restricted_ari(seed_labels[left], seed_labels[right])
            restricted = pair_restricted_ari(
                seed_labels[left], seed_labels[right], primary_comparable
            )
            rank_standardized = distance_rank_agreement(
                seed_embeddings[left], seed_embeddings[right], primary_comparable
            )
            rank_raw = distance_rank_agreement(
                seed_embeddings[left], seed_embeddings[right], primary_comparable,
                standardize=False,
            )
            span = subspace_alignment(seed_embeddings[left], seed_embeddings[right])

            def _round(value):
                return round(value, 6) if value is not None else None

            noise.append(
                {
                    "seeds": [left, right],
                    "ari_all_pairs": _round(full),
                    "ari_comparable_pairs": _round(restricted),
                    "distance_rank_agreement": _round(rank_standardized),
                    "distance_rank_agreement_raw": _round(rank_raw),
                    "subspace_alignment": _round(span),
                }
            )

            def _show(value, width):
                return f"{value:.4f}".rjust(width) if value is not None else "n/a".rjust(width)

            print(f"{f'{left}-{right}':>10} {_show(full, 10)} {_show(restricted, 14)}"
                  f" {_show(rank_standardized, 18)} {_show(rank_raw, 16)} {_show(span, 13)}")
    results["g1_noise_floor"] = noise
    values = [row["ari_all_pairs"] for row in noise if row["ari_all_pairs"] is not None]
    if values:
        print(f"\n  전체 쌍 ARI 범위       {min(values):.4f} – {max(values):.4f}")
        restricted_values = [
            row["ari_comparable_pairs"] for row in noise if row["ari_comparable_pairs"] is not None
        ]
        print(f"  비교 가능 쌍 ARI 범위  {min(restricted_values):.4f} – {max(restricted_values):.4f}")
        rank_values = [
            row["distance_rank_agreement"] for row in noise
            if row["distance_rank_agreement"] is not None
        ]
        if rank_values:
            print(f"  거리순위 일치도 범위   {min(rank_values):.4f} – {max(rank_values):.4f}")
        print("  → G1 임계는 이 범위보다 높아야 한다. 그보다 낮으면 seed 잡음과 구별되지 않는다.")
        print("     군집 ARI 와 거리순위 중 어느 쪽이 사용 가능한지는 위 두 범위가 결정한다.")
    print()

    # ---- gate ARI 의 잡음 대조 (C2 진단) --------------------------------
    # C2 의 retention ARI 는 **같은 seed** 에서 마스킹 전후를 비교한다. 위의 seed 잡음과
    # 크기가 같다면 그 지표는 마스킹 취약성이 아니라 군집 불안정을 재고 있다.
    print("=" * 88)
    print("gate retention ARI 대 seed 잡음 — 같은 축에서의 대조 (arm D)")
    print("=" * 88)
    masked_input, _induced = multiview.with_additional_target_masking(
        fraction=config["artificial_mask_fraction"], seed=config["seed"]
    )
    masked_encoder = dict(ENCODER_BASE)
    masked_encoder["n_perturbations"] = 0
    masked_fit = fit_variant(masked_input, arm_d, encoder_config=masked_encoder, config=config)
    masked_cluster = cluster_representation(
        masked_fit.embedding,
        distance_threshold=config["cluster_distance_threshold"],
        minimum_cluster_size=config["minimum_cluster_size"],
    )
    retention = pair_restricted_ari(seed_labels[0], masked_cluster)
    same_seed_no_mask = pair_restricted_ari(seed_labels[0], seed_labels[0])
    comparison = {
        "retention_ari_same_seed_masked": round(retention, 6) if retention is not None else None,
        "seed_noise_ari_range": [round(min(values), 6), round(max(values), 6)] if values else None,
        "self_ari_sanity": round(same_seed_no_mask, 6) if same_seed_no_mask is not None else None,
    }
    results["gate_ari_noise_contrast"] = comparison
    print(f"  마스킹 전후 (seed 고정)  ARI = {comparison['retention_ari_same_seed_masked']}")
    print(f"  seed 만 변경 (마스킹 X)  ARI = {comparison['seed_noise_ari_range']}")
    print(f"  자기 대조 (건전성 검사)  ARI = {comparison['self_ari_sanity']}   (1.0 이어야 함)")
    print()
    print(json.dumps(results, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
