"""4-arm 대조 — A·B·D·E 의 다중 seed gate 값.

구현 대상: docs/c2_prereg_v1.md §2.1 (4-arm 패턴), §5.4 (d) 의 필수 병기 표,
          §6 E4 의 "4-arm 패턴에 따른 추가 대조 (필수 병기, 판정 아님)"
사전등록: 2026-08-21. **보고가 요구된 대조이며 새 판정 기준을 도입하지 않는다.** 임계는
          §14.2 동결분(ARI ≥ 0.20, induced R² ≤ 0.25)을 그대로 인용해 표시만 한다.
          공표 산출물은 seed 0 단일값이었으므로 §1.3 의 5 seed 규칙으로 다시 측정한다.
해석 한계: **판정이 아니다.** C2 성공/실패는 E4(§6)가 정하며 이 표가 아니다. 이 표가 답하는
          것은 "C2 arm 이 어느 기존 arm 도 하지 못한 조합을 달성했는가"이며, 그 비교 없이는
          adversary 의 기여를 원 궤적(arm A)의 기여와 구분할 수 없다.
          단일 코호트(HIRc-B, T = 6, form 단위)다.
주장 금지: 어느 arm 의 낮은 induced R² 도 "coverage 로부터 독립"으로 서술하지 않는다.

정본 환경:

    docker cp scripts/measure_c2_arm_baselines.py ptm-worker-preprocessing:/tmp/arms.py
    docker exec -i ptm-worker-preprocessing env PYTHONPATH=/app:/opt python /tmp/arms.py \
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

import numpy as np

GATE_INDUCED_R2_MAX = 0.25
GATE_RETENTION_ARI_MIN = 0.20
"""docs/c2_prereg_v1.md §14.2 동결 임계. 여기서 도입하지 않고 인용한다."""

EVAL_SEEDS = (0, 1, 2, 3, 4)
ARMS = ("A", "B", "D", "E")

ABLATION_ENCODER_BASE = {"latent_dim": 16, "hidden_dim": 64, "epochs": 150, "seed": 0,
                         "n_perturbations": 5}
ABLATION_BENCHMARK_CONFIG = {"neighbors": 10, "leave_one_out": False, "minimum_sites": 8,
                             "seed": 0}


def load_eligible(vector_path: Path):
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
    args = parser.parse_args(argv)

    from ptm_shared.representation.benchmark import (
        DEFAULT_BENCHMARK_CONFIG,
        _missingness_r2,
        adjusted_rand_index,
        cluster_representation,
        fit_variant,
    )
    from ptm_shared.representation.layers import resolve_variant

    vector = (
        Path(args.data_root) / "outputs" / args.order_code
        / "ptm_vector_data_normalized_phospho.tsv"
    )
    if not vector.exists():
        print(f"FATAL: {vector} 없음", file=sys.stderr)
        return 2

    multiview = load_eligible(vector)
    config = dict(DEFAULT_BENCHMARK_CONFIG)
    config.update(ABLATION_BENCHMARK_CONFIG)

    print(f"order   = {args.order_code}")
    print(f"n_sites = {multiview.n_sites}   T = {multiview.n_timepoints}")
    print(f"seed    = {list(EVAL_SEEDS)}  (§1.3)")
    print(f"임계    = ARI ≥ {GATE_RETENTION_ARI_MIN}  AND  induced R² ≤ {GATE_INDUCED_R2_MAX}"
          f"  (§14.2 인용)")
    print()
    print("=" * 92)
    print(f"{'arm':>4} {'학습':>5} {'clust':>6} {'med ARI':>9} {'ARI 범위':>17}"
          f" {'med R2':>9} {'R2 범위':>17} {'(a)':>5}")
    print("=" * 92)

    # 마스킹은 arm 과 무관하므로 seed 별 입력을 한 번만 만든다. arm 간 비교가 같은 마스크
    # 위에서 이루어져야 대조가 성립한다.
    masked_inputs = {}
    for seed in EVAL_SEEDS:
        masked_input, induced = multiview.with_additional_target_masking(
            fraction=config["artificial_mask_fraction"], seed=seed
        )
        masked_inputs[seed] = (masked_input, induced.mean(axis=1))

    records: List[Dict[str, Any]] = []
    started = time.time()
    for arm_id in ARMS:
        arm = resolve_variant(arm_id)
        if arm.uses_prior_features and multiview.motif_features is None:
            print(f"{arm_id:>4}  motif 특징 없음 — 건너뜀")
            continue
        reference = fit_variant(
            multiview, arm, encoder_config=ABLATION_ENCODER_BASE, config=config
        )
        reference_labels = cluster_representation(
            reference.embedding,
            distance_threshold=config["cluster_distance_threshold"],
            minimum_cluster_size=config["minimum_cluster_size"],
        )
        aris: List[float] = []
        r2s: List[float] = []
        for seed in EVAL_SEEDS:
            masked_input, rate = masked_inputs[seed]
            masked_encoder = dict(ABLATION_ENCODER_BASE)
            masked_encoder["n_perturbations"] = 0
            masked_fit = fit_variant(
                masked_input, arm, encoder_config=masked_encoder, config=config
            )
            masked_labels = cluster_representation(
                masked_fit.embedding,
                distance_threshold=config["cluster_distance_threshold"],
                minimum_cluster_size=config["minimum_cluster_size"],
            )
            retention = adjusted_rand_index(reference_labels, masked_labels)
            r2 = _missingness_r2(masked_fit.embedding, rate)
            if retention is not None:
                aris.append(float(retention))
            if r2 is not None:
                r2s.append(float(r2))
        median_ari = float(np.median(aris)) if aris else float("nan")
        median_r2 = float(np.median(r2s)) if r2s else float("nan")
        n_pass = sum(
            1
            for ari_value, r2_value in zip(aris, r2s)
            if ari_value >= GATE_RETENTION_ARI_MIN and r2_value <= GATE_INDUCED_R2_MAX
        )
        condition_a = bool(
            median_ari >= GATE_RETENTION_ARI_MIN
            and median_r2 <= GATE_INDUCED_R2_MAX
            and n_pass >= 4
        )
        records.append(
            {
                "arm": arm_id,
                "learned": bool(arm.learned),
                "median_retention_ari": round(median_ari, 6),
                "retention_ari_range": [round(min(aris), 6), round(max(aris), 6)] if aris else None,
                "median_induced_r2": round(median_r2, 6),
                "induced_r2_range": [round(min(r2s), 6), round(max(r2s), 6)] if r2s else None,
                "n_seeds_passed": n_pass,
                "condition_a": condition_a,
                "n_clusters": int(len({x for x in reference_labels.tolist() if x != 0})),
                "embedding_dim": int(reference.embedding.shape[1]),
            }
        )
        row = records[-1]
        print(
            f"{arm_id:>4} {('yes' if arm.learned else 'no'):>5} {row['n_clusters']:>6}"
            f" {median_ari:>9.4f} {str(row['retention_ari_range']):>17}"
            f" {median_r2:>9.4f} {str(row['induced_r2_range']):>17}"
            f" {'PASS' if condition_a else 'fail':>5}"
        )

    print()
    print(f"소요 {time.time() - started:.0f}s")
    print()
    best = max(records, key=lambda record: record["median_retention_ari"]) if records else None
    if best is not None:
        print(f"retention ARI 최대 arm = {best['arm']}"
              f" ({'학습' if best['learned'] else '비학습'}), 중위수 {best['median_retention_ari']:.4f}")
        if best["median_retention_ari"] < GATE_RETENTION_ARI_MIN:
            print(f"→ **어느 arm 도 ARI 임계 {GATE_RETENTION_ARI_MIN} 에 도달하지 못한다.**")
            print("   임계는 §14.2 동결분이며 여기서 바꾸지 않는다. 이 관찰은 조건 (a) 의 ARI")
            print("   하위 조건이 이 코호트에서 표현 품질보다 **마스킹 취약성**을 재고 있을")
            print("   가능성을 뜻한다. T = 6, minimum_remaining = 3 이므로 사이트당 마스킹")
            print("   가능 시점이 최대 3 개다. 해석은 §13 의 반증 분기로 다룬다.")
    print()
    print(json.dumps({"arm_baselines": records}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
