"""E8 — can hyperparameters alone do what the coverage adversary is supposed to do?

구현 대상: docs/c2_prereg_v1.md §10 (E8, veto 실험). 설계 근거는
          docs/integrated_research_design_v2.md §6.5 세 번째 반증 조건.
사전등록: 2026-08-21 동결. 격자(§10.1), 예산 동등성(§10.2), 판정(§10.3), 임계(§14.2)가
          모두 이 실행 **전에** 확정되었다. adversary 는 아직 구현되지 않았다.
해석 한계: E8 은 **C2 를 실패시킬 수만 있고 성공시킬 수 없다.** 어떤 구성이 (a)+(b)+(c) 를
          충족하면 adversary 가 불필요했다는 뜻이고, 충족하지 못하면 "이 격자에서는 안 된다"는
          뜻일 뿐 adversary 가 성공한다는 뜻이 아니다.
          latent_dim 이 변하므로 R² 절대값을 E4 와 직접 비교하지 않는다 (§10.1). gate 통과
          여부로만 판정한다.
주장 금지: E8 실패를 C2 방법 기여의 근거로 서술하지 않는다. 필요조건일 뿐이다.
          이 실행으로 coverage 분리가 개선되었다고 서술하지 않는다.

정본 환경:

    docker exec -i ptm-worker-preprocessing env PYTHONPATH=/app:/opt python - \
        --order-code Insulin_Signaling_Phosphoproteomics_HIRc-B \
        < scripts/run_c2_e8_hyperparameter_control.py
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

# ---------------------------------------------------------------------------
# 동결된 판정 임계. docs/c2_prereg_v1.md §14.2 에서 2026-08-21 승인. 변경 금지.
# ---------------------------------------------------------------------------

GATE_INDUCED_R2_MAX = 0.25
GATE_RETENTION_ARI_MIN = 0.20
FAMILY_R2_MAX = 0.25
"""조건 (c) 임계. gate 값을 표본 외 R² 에 재사용한다 (§4.2, §14.2 승인)."""

PROBE_DELTA_R2_MIN = 0.01355
"""조건 (b) 임계 = 0.5 × 0.0271 (D 의 공표 이득의 절반). §5.2, §14.2 승인."""

PROBE_P_MAX = 0.05
"""조건 (b) 의 짝지은 sign-flip 검정 유의수준. §5.2."""

EVAL_SEEDS = (0, 1, 2, 3, 4)
"""INDUCED_MASK_SEED_SET_V1. §1.3."""

# ---------------------------------------------------------------------------
# 격자. docs/c2_prereg_v1.md §10.1 에서 2026-08-21 선언. 격자 밖 값 사용 금지.
# ---------------------------------------------------------------------------

LATENT_DIMS = (8, 16, 32)
L2_MULTIPLIERS = (0.1, 1.0, 10.0)
INPUT_MASK_MULTIPLIERS = (0.0, 1.0, 2.0)

BASE_L2 = 1e-4
BASE_INPUT_MASK_FRACTION = 0.15
"""DEFAULT_ENCODER_CONFIG 의 기본값. 배수의 기준점."""

# ablation 재현 설정. docs/c2_prereg_v1.md §1.3 참조. epochs 는 benchmark_epochs = 150.
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


def evaluate_gate(multiview, arm, encoder_config, config, *, benchmark) -> Dict[str, Any]:
    """Condition (a) across the pre-registered induced-mask seeds."""
    fit_variant = benchmark["fit_variant"]
    cluster = benchmark["cluster_representation"]
    ari = benchmark["adjusted_rand_index"]
    missingness_r2 = benchmark["_missingness_r2"]

    reference = fit_variant(multiview, arm, encoder_config=encoder_config, config=config)
    reference_labels = cluster(
        reference.embedding,
        distance_threshold=config["cluster_distance_threshold"],
        minimum_cluster_size=config["minimum_cluster_size"],
    )

    per_seed: List[Dict[str, Any]] = []
    embeddings = {}
    for seed in EVAL_SEEDS:
        masked_input, induced = multiview.with_additional_target_masking(
            fraction=config["artificial_mask_fraction"], seed=seed
        )
        masked_encoder = dict(encoder_config)
        masked_encoder["n_perturbations"] = 0
        masked_fit = fit_variant(masked_input, arm, encoder_config=masked_encoder, config=config)
        masked_labels = cluster(
            masked_fit.embedding,
            distance_threshold=config["cluster_distance_threshold"],
            minimum_cluster_size=config["minimum_cluster_size"],
        )
        rate = induced.mean(axis=1)
        retention = ari(reference_labels, masked_labels)
        r2 = missingness_r2(masked_fit.embedding, rate)
        embeddings[seed] = (masked_fit.embedding, rate)
        per_seed.append(
            {
                "seed": seed,
                "pattern_retention_ari": None if retention is None else round(float(retention), 6),
                "induced_missingness_r2": r2,
                "passed": bool(
                    retention is not None
                    and r2 is not None
                    and float(retention) >= GATE_RETENTION_ARI_MIN
                    and float(r2) <= GATE_INDUCED_R2_MAX
                ),
            }
        )

    aris = [r["pattern_retention_ari"] for r in per_seed if r["pattern_retention_ari"] is not None]
    r2s = [r["induced_missingness_r2"] for r in per_seed if r["induced_missingness_r2"] is not None]
    median_ari = float(np.median(aris)) if aris else float("nan")
    median_r2 = float(np.median(r2s)) if r2s else float("nan")
    n_pass = sum(1 for r in per_seed if r["passed"])
    return {
        "per_seed": per_seed,
        "median_retention_ari": round(median_ari, 6),
        "median_induced_r2": round(median_r2, 6),
        "n_seeds_passed": n_pass,
        # §1.3: 중위수 충족 AND 5 중 4 이상 개별 통과
        "condition_a": bool(
            median_ari >= GATE_RETENTION_ARI_MIN
            and median_r2 <= GATE_INDUCED_R2_MAX
            and n_pass >= 4
        ),
        "embeddings": embeddings,
        "n_clusters": int(len({x for x in reference_labels.tolist() if x != 0})),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--order-code", required=True)
    parser.add_argument("--data-root", default="/app/data")
    args = parser.parse_args(argv)

    from ptm_shared.representation import fair_probe as fair_probe_module
    from ptm_shared.representation.benchmark import (
        DEFAULT_BENCHMARK_CONFIG,
        _missingness_r2,
        adjusted_rand_index,
        cluster_representation,
        fit_variant,
    )
    from ptm_shared.representation.coverage_probes import residual_mask_recoverability
    from ptm_shared.representation.layers import resolve_variant

    benchmark = {
        "fit_variant": fit_variant,
        "cluster_representation": cluster_representation,
        "adjusted_rand_index": adjusted_rand_index,
        "_missingness_r2": _missingness_r2,
    }

    vector = Path(args.data_root) / "outputs" / args.order_code / "ptm_vector_data_normalized_phospho.tsv"
    if not vector.exists():
        print(f"FATAL: {vector} 없음", file=sys.stderr)
        return 2

    multiview = load_eligible(vector)
    arm = resolve_variant("D")
    config = dict(DEFAULT_BENCHMARK_CONFIG)
    config.update(ABLATION_BENCHMARK_CONFIG)

    print(f"order   = {args.order_code}")
    print(f"n_sites = {multiview.n_sites}   T = {multiview.n_timepoints}")
    print(f"격자    = {len(LATENT_DIMS)} × {len(L2_MULTIPLIERS)} × {len(INPUT_MASK_MULTIPLIERS)}"
          f" = {len(LATENT_DIMS) * len(L2_MULTIPLIERS) * len(INPUT_MASK_MULTIPLIERS)} 구성")
    print(f"        E5 격자 점 수 8 이상 → 예산 동등성 충족 (§10.2)")
    print()
    print("=" * 96)
    print("Stage 1 — 조건 (a): gate 재판정 (5 seed)")
    print("=" * 96)
    header = (
        f"{'latent':>7} {'l2':>9} {'in_mask':>8} {'clust':>6}"
        f" {'med ARI':>9} {'med R2':>9} {'pass/5':>7} {'(a)':>5}"
    )
    print(header)

    results: List[Dict[str, Any]] = []
    started = time.time()
    for latent_dim in LATENT_DIMS:
        for l2_multiplier in L2_MULTIPLIERS:
            for mask_multiplier in INPUT_MASK_MULTIPLIERS:
                encoder_config = dict(ABLATION_ENCODER_BASE)
                encoder_config["latent_dim"] = latent_dim
                encoder_config["l2"] = BASE_L2 * l2_multiplier
                encoder_config["input_mask_fraction"] = (
                    BASE_INPUT_MASK_FRACTION * mask_multiplier
                )
                gate = evaluate_gate(
                    multiview, arm, encoder_config, config, benchmark=benchmark
                )
                embeddings = gate.pop("embeddings")
                record = {
                    "latent_dim": latent_dim,
                    "l2_multiplier": l2_multiplier,
                    "l2": encoder_config["l2"],
                    "input_mask_multiplier": mask_multiplier,
                    "input_mask_fraction": encoder_config["input_mask_fraction"],
                    **gate,
                }
                results.append(record)
                if record["condition_a"]:
                    record["_embeddings"] = embeddings
                print(
                    f"{latent_dim:>7} {encoder_config['l2']:>9.1e}"
                    f" {encoder_config['input_mask_fraction']:>8.3f} {gate['n_clusters']:>6}"
                    f" {gate['median_retention_ari']:>9.4f} {gate['median_induced_r2']:>9.4f}"
                    f" {gate['n_seeds_passed']:>7} {'PASS' if record['condition_a'] else 'fail':>5}"
                )
    print()
    print(f"Stage 1 소요 {time.time() - started:.0f}s")

    passers = [record for record in results if record["condition_a"]]
    print(f"조건 (a) 통과 구성: {len(passers)} / {len(results)}")
    print()

    if not passers:
        print("=" * 96)
        print("E8 판정 — (a) 통과 구성 없음")
        print("=" * 96)
        print("이 격자의 하이퍼파라미터 조정만으로는 missingness_validity gate 를 통과할 수 없다.")
        print("→ C2 의 방법 기여가 **소멸하지 않았다.** veto 발동하지 않음 (§10.3).")
        print("주의: 이것은 필요조건일 뿐이며 adversary 가 성공한다는 뜻이 아니다.")
        print()
        print(json.dumps({"stage1": [
            {k: v for k, v in record.items() if not k.startswith("_")} for record in results
        ]}, ensure_ascii=False))
        return 0

    # ------------------------------------------------------ Stage 2: (b) and (c)
    print("=" * 96)
    print("Stage 2 — (a) 통과 구성에 대해 조건 (c) 예측기族, 조건 (b) 공정 프로브")
    print("=" * 96)
    for record in passers:
        embeddings = record.pop("_embeddings")
        embedding, rate = embeddings[0]
        family = residual_mask_recoverability(embedding, rate)
        record["condition_c_detail"] = family
        family_max = family.get("family_max_out_of_sample_r2")
        record["condition_c"] = bool(family_max is not None and family_max <= FAMILY_R2_MAX)

        encoder_config = dict(ABLATION_ENCODER_BASE)
        encoder_config["latent_dim"] = record["latent_dim"]
        encoder_config["l2"] = record["l2"]
        encoder_config["input_mask_fraction"] = record["input_mask_fraction"]
        probe = fair_probe_module.run_heldout_timepoint_probe(
            multiview,
            encoder_config=encoder_config,
            config={"arms": ("B", "D"), "baseline_arm": "B"},
        )
        if probe.get("status") != "evaluated":
            record["condition_b"] = False
            record["condition_b_detail"] = {"status": probe.get("status")}
        else:
            arm_summary = (probe.get("comparisons") or {}).get("arms", {}).get("D", {})
            delta = arm_summary.get("mean_r2_difference")
            p_value = arm_summary.get("sign_flip_p_value")
            record["condition_b_detail"] = arm_summary
            record["condition_b"] = bool(
                delta is not None
                and p_value is not None
                and float(delta) >= PROBE_DELTA_R2_MIN
                and float(p_value) < PROBE_P_MAX
            )
        record["all_conditions"] = bool(
            record["condition_a"] and record["condition_b"] and record["condition_c"]
        )
        print(
            f"latent={record['latent_dim']} l2={record['l2']:.1e}"
            f" in_mask={record['input_mask_fraction']:.3f}"
            f" | (c) family_max={family_max} → {record['condition_c']}"
            f" | (b) ΔR²={record['condition_b_detail'].get('mean_r2_difference')}"
            f" p={record['condition_b_detail'].get('sign_flip_p_value')}"
            f" → {record['condition_b']}"
            f" | 전체 {record['all_conditions']}"
        )

    print()
    print("=" * 96)
    print("E8 판정")
    print("=" * 96)
    winners = [record for record in passers if record["all_conditions"]]
    if winners:
        print(f"** (a)+(b)+(c) 를 모두 충족하는 구성 {len(winners)}개 **")
        for record in winners:
            print(f"   latent_dim={record['latent_dim']} l2={record['l2']:.1e}"
                  f" input_mask_fraction={record['input_mask_fraction']:.3f}")
        print("→ adversary 없이 달성되었다. **C2 의 방법 기여 소멸** (§10.3).")
        print("→ 그 사실을 보고하고 C2 를 방법 장에서 강등한다.")
    else:
        print("(a) 는 통과하나 (b) 또는 (c) 에서 탈락. veto 발동하지 않음.")
        print("주의: 필요조건일 뿐이며 adversary 가 성공한다는 뜻이 아니다.")
    print()
    print(json.dumps({"stage1": [
        {k: v for k, v in record.items() if not k.startswith("_")} for record in results
    ]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
