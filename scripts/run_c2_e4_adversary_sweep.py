"""E4 / E5 / E6 — coverage adversary 강도 sweep과 인증서 판정.

구현 대상: docs/c2_prereg_v1.md §6 (E4, primary), §7 (E5 격자·frontier·λ* 규칙),
          §8 (E6 예측기族 표). adversary 구현은 `ptm_shared/representation/coverage_adversary.py`.
사전등록: 2026-08-21 동결. λ 격자 8 점(§7.1), λ* 선택 규칙(§7.3), 임계 4 종(§14.2),
          seed(§12)가 모두 이 실행 **전에** 확정되었다. 실행 후 어느 것도 바꾸지 않는다.
          adversary 헤드 구성은 §3.1 의 2026-08-21 개정분이며 그 개정도 이 실행 전이다.
해석 한계: E4 가 C2 의 **유일한 primary 판정**이다(§11). E5 의 어느 한 점이 (a)+(b) 를
          만족한다는 것으로 C2 성공을 주장하는 것은 §7.3 을 우회하는 사후 선택이므로 금지된다.
          단일 코호트(HIRc-B, T=6, form 단위)이며 다른 코호트로 일반화하지 않는다.
          λ 가 커지면 잠재 기하가 변하므로 R² 절대값을 arm 간에 직접 비교하지 않는다.
주장 금지: adversary loss 상승을 "coverage 로부터 독립인 표현"으로 서술하지 않는다.
          이 실행으로 kinase 예측이 개선되었다고 서술하지 않는다.

정본 환경 (scipy 필요, NumPy 2.4.6):

    docker cp scripts/run_c2_e4_adversary_sweep.py ptm-worker-preprocessing:/tmp/e4.py
    docker exec -i ptm-worker-preprocessing env PYTHONPATH=/app:/opt python /tmp/e4.py \
        --order-code Insulin_Signaling_Phosphoproteomics_HIRc-B
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path[:0] = ["/app", "/opt"]

import numpy as np

# ---------------------------------------------------------------------------
# 동결된 판정 임계. docs/c2_prereg_v1.md §14.2 에서 2026-08-21 승인. 변경 금지.
# 변경하면 (a)–(d) 판정이 무효가 되고 E4 는 primary 자격을 잃는다.
# ---------------------------------------------------------------------------

GATE_INDUCED_R2_MAX = 0.25
GATE_RETENTION_ARI_MIN = 0.20
FAMILY_R2_MAX = 0.25
PROBE_DELTA_R2_MIN = 0.01355
PROBE_P_MAX = 0.05
EVAL_SEEDS = (0, 1, 2, 3, 4)

LAMBDA_GRID = (0.0, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0)
"""docs/c2_prereg_v1.md §7.1 에서 2026-08-21 선언. **격자 밖 값 사용 금지.**

λ = 0 은 D 재현 대조다. §2 의 D 실측치를 재현하지 않으면 구현 오류다.
"""

ABLATION_ENCODER_BASE = {"latent_dim": 16, "hidden_dim": 64, "epochs": 150, "seed": 0,
                         "n_perturbations": 5}
ABLATION_BENCHMARK_CONFIG = {"neighbors": 10, "leave_one_out": False, "minimum_sites": 8,
                             "seed": 0}

PUBLISHED_D_SEED0 = {"pattern_retention_ari": 0.035002, "induced_missingness_r2": 0.462393}
"""λ = 0 재현 대조의 기준값 (§7.1). **seed 0 의 값이며 5 seed 중위수가 아니다.**

출처는 `scripts/measure_c2_prefreeze.py` 의 `STORED_D_RETENTION_ARI` ·
`STORED_D_INDUCED_R2` 로, 2026-08-21 에 |Δ| = 0 으로 재현 확인된 공표 D arm seed 0 값이다.
λ = 0 이 이 값을 내지 않으면 adversary 배선이 λ = 0 에서 중립이 아니라는 뜻이며
sweep 전체가 무효다. 중위수(ARI 0.036437)와 혼동하지 않는다 — 중위수는 §1.3 의 값이다.
"""


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
    """Condition (a) across INDUCED_MASK_SEED_SET_V1 (§1.3)."""
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
    adversary_provenance = (reference.provenance or {}).get("coverage_adversary")

    per_seed: List[Dict[str, Any]] = []
    embeddings: Dict[int, Any] = {}
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
        # 진단 — adversary 가 **자기 표적**(입력의 결합 결측률)에 대해 실제로 회수율을 낮추는가.
        # 이것이 낮아지지 않으면 최적화가 실패한 것이고, 낮아지는데 induced R² 이 그대로면
        # 표적 대리(proxy)가 느슨한 것이다. 두 경우의 처방이 정반대이므로 반드시 구분한다.
        own_target = 1.0 - masked_input.target.observed.mean(axis=1)
        masked_history = ((masked_fit.provenance or {}).get("training_history") or [{}])[-1]
        per_seed.append(
            {
                "seed": seed,
                "pattern_retention_ari": None if retention is None else round(float(retention), 6),
                "induced_missingness_r2": r2,
                "adversary_own_target_r2": missingness_r2(masked_fit.embedding, own_target),
                "adversary_final_loss": masked_history.get("adversary_loss"),
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
    own = [r["adversary_own_target_r2"] for r in per_seed if r["adversary_own_target_r2"] is not None]
    losses = [r["adversary_final_loss"] for r in per_seed if r["adversary_final_loss"] is not None]
    median_ari = float(np.median(aris)) if aris else float("nan")
    median_r2 = float(np.median(r2s)) if r2s else float("nan")
    n_pass = sum(1 for r in per_seed if r["passed"])
    return {
        "per_seed": per_seed,
        "median_retention_ari": round(median_ari, 6),
        "median_induced_r2": round(median_r2, 6),
        "median_own_target_r2": round(float(np.median(own)), 6) if own else None,
        "median_adversary_loss": round(float(np.median(losses)), 6) if losses else None,
        "n_seeds_passed": n_pass,
        "condition_a": bool(
            median_ari >= GATE_RETENTION_ARI_MIN
            and median_r2 <= GATE_INDUCED_R2_MAX
            and n_pass >= 4
        ),
        "embeddings": embeddings,
        "n_clusters": int(len({x for x in reference_labels.tolist() if x != 0})),
        "adversary": adversary_provenance,
        "effective_rank": _effective_rank(reference.embedding),
    }


def _effective_rank(embedding: np.ndarray) -> Optional[int]:
    """차원 수 중 특이값 에너지 99% 도달 지점 (§6 병기 항목).

    λ 가 커지면 인코더가 차원을 붕괴시켜 gate 를 통과할 수 있다. 그 경우 낮은 induced R² 은
    coverage 제거가 아니라 **표현 붕괴**의 결과이며, 유효 rank 없이는 두 경우를 구분할 수 없다.
    """
    matrix = np.asarray(embedding, dtype=float)
    if matrix.size == 0:
        return None
    centred = matrix - matrix.mean(axis=0, keepdims=True)
    singular = np.linalg.svd(centred, compute_uv=False) ** 2
    total = float(singular.sum())
    if total <= 0:
        return 0
    return int(np.searchsorted(np.cumsum(singular) / total, 0.99) + 1)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--order-code", required=True)
    parser.add_argument("--data-root", default="/app/data")
    parser.add_argument(
        "--skip-family",
        action="store_true",
        help="E6 예측기族(비용 큼)을 생략하고 (a)·(b) 만 낸다. 판정은 불완전해진다.",
    )
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

    vector = (
        Path(args.data_root) / "outputs" / args.order_code
        / "ptm_vector_data_normalized_phospho.tsv"
    )
    if not vector.exists():
        print(f"FATAL: {vector} 없음", file=sys.stderr)
        return 2

    multiview = load_eligible(vector)
    arm = resolve_variant("D")
    config = dict(DEFAULT_BENCHMARK_CONFIG)
    config.update(ABLATION_BENCHMARK_CONFIG)

    print(f"order   = {args.order_code}")
    print(f"n_sites = {multiview.n_sites}   T = {multiview.n_timepoints}")
    print(f"λ 격자  = {list(LAMBDA_GRID)}   ({len(LAMBDA_GRID)} 점, §7.1)")
    print()

    # adversary 표적(결합 결측률)과 gate 표적(induced 결측률)이 얼마나 다른가.
    # §3.1 은 adversary 가 induced 를 직접 보는 것을 금지하므로 이 괴리는 설계상 불가피하다.
    # 괴리가 크면 "표적을 이겨도 gate 는 안 움직인다"가 예상되는 결과이며, 그 경우
    # 원인은 최적화 실패가 아니라 대리 표적의 느슨함이다. 미리 정량화해 둔다.
    natural = 1.0 - multiview.target.observed.mean(axis=1)
    _, induced0 = multiview.with_additional_target_masking(
        fraction=config["artificial_mask_fraction"], seed=0
    )
    induced_rate = induced0.mean(axis=1)
    combined = natural + induced_rate
    correlation = float(np.corrcoef(combined, induced_rate)[0, 1])
    print("표적 괴리 진단 (seed 0)")
    print(f"  natural  결측률 분산 = {float(np.var(natural)):.6f}")
    print(f"  induced  결측률 분산 = {float(np.var(induced_rate)):.6f}")
    print(f"  결합 표적 대 induced 상관 = {correlation:.4f}"
          f"  (adversary 는 결합을, gate 는 induced 를 본다)")
    print()
    print("=" * 104)
    print("E5 Stage 1 — 조건 (a) 를 λ 격자 전체에서 (5 seed)")
    print("=" * 104)
    print(
        f"{'lambda':>7} {'rank':>5} {'clust':>6} {'med ARI':>9} {'med R2':>9}"
        f" {'own R2':>8} {'adv loss':>9} {'pass/5':>7} {'수렴':>6} {'(a)':>5}"
    )

    results: List[Dict[str, Any]] = []
    started = time.time()
    for lambda_value in LAMBDA_GRID:
        encoder_config = dict(ABLATION_ENCODER_BASE)
        encoder_config["use_coverage_adversary"] = True
        encoder_config["adversary_lambda"] = lambda_value
        gate = evaluate_gate(multiview, arm, encoder_config, config, benchmark=benchmark)
        embeddings = gate.pop("embeddings")
        adversary = gate.pop("adversary") or {}
        convergence = adversary.get("convergence") or {}
        record = {
            "lambda": lambda_value,
            "adversary_status": adversary.get("status"),
            "converged": convergence.get("converged"),
            "divergence_reason": convergence.get("reason"),
            "rff_bandwidth_final": adversary.get("rff_bandwidth_final"),
            **gate,
        }
        results.append(record)
        record["_embeddings"] = embeddings
        own = gate["median_own_target_r2"]
        loss = gate["median_adversary_loss"]
        print(
            f"{lambda_value:>7.2f} {str(gate['effective_rank']):>5} {gate['n_clusters']:>6}"
            f" {gate['median_retention_ari']:>9.4f} {gate['median_induced_r2']:>9.4f}"
            f" {('     n/a' if own is None else f'{own:>8.4f}')}"
            f" {('      n/a' if loss is None else f'{loss:>9.4f}')}"
            f" {gate['n_seeds_passed']:>7}"
            f" {('yes' if convergence.get('converged') else 'NO'):>6}"
            f" {'PASS' if record['condition_a'] else 'fail':>5}"
        )
    print()
    print(f"Stage 1 소요 {time.time() - started:.0f}s")

    # ------------------------------------------------------- λ = 0 재현 대조 (§7.1)
    zero = next(record for record in results if record["lambda"] == 0.0)
    seed0 = next(entry for entry in zero["per_seed"] if entry["seed"] == 0)
    delta_ari = abs(seed0["pattern_retention_ari"] - PUBLISHED_D_SEED0["pattern_retention_ari"])
    delta_r2 = abs(seed0["induced_missingness_r2"] - PUBLISHED_D_SEED0["induced_missingness_r2"])
    reproduced = delta_ari < 1e-6 and delta_r2 < 1e-6
    print()
    print(f"λ = 0 재현 대조 (§7.1): |Δ ARI| = {delta_ari:.2e}  |Δ R²| = {delta_r2:.2e}"
          f"  → {'재현' if reproduced else '불일치 — 구현 오류'}")
    if not reproduced:
        print("FATAL: λ = 0 이 공표 D 값을 재현하지 않는다. sweep 결과를 보고하지 않는다.",
              file=sys.stderr)
        return 3

    # -------------------------------------------------- E6: 예측기族을 전 격자에 (§8)
    if not args.skip_family:
        print()
        print("=" * 104)
        print("E6 — 예측기族을 λ 격자 전체에 (§8). seed 0 임베딩 기준")
        print("=" * 104)
        print(f"{'lambda':>7} {'P1 gate':>9} {'P2 ridge':>9} {'P3 kNN':>9}"
              f" {'P4 RFF':>9} {'P5 quad':>9} {'族 최대':>9} {'(c)':>5}")
        for record in results:
            embedding, rate = record["_embeddings"][0]
            family = residual_mask_recoverability(embedding, rate)
            record["condition_c_detail"] = family
            family_max = family.get("family_max_out_of_sample_r2")
            record["condition_c"] = bool(family_max is not None and family_max <= FAMILY_R2_MAX)
            per = family.get("per_predictor") or {}

            def _show(key: str) -> str:
                value = (per.get(key) or {}).get("out_of_sample_r2")
                return "     n/a" if value is None else f"{value:>9.4f}"

            print(
                f"{record['lambda']:>7.2f} {record['per_seed'][0]['induced_missingness_r2']:>9.4f}"
                f" {_show('P2_ridge')} {_show('P3_knn')} {_show('P4_rff_kernel_ridge')}"
                f" {_show('P5_quadratic_ridge')}"
                f" {('     n/a' if family_max is None else f'{family_max:>9.4f}')}"
                f" {'PASS' if record['condition_c'] else 'fail':>5}"
            )

    # -------------------------------------------------------------- λ* 선택 (§7.3)
    print()
    print("=" * 104)
    print("λ* 선택 (§7.3) — (a) 와 (c) 를 충족하는 격자점 중 **가장 작은** λ")
    print("=" * 104)
    eligible = [
        record
        for record in results
        if record["condition_a"] and (args.skip_family or record.get("condition_c"))
    ]
    if not eligible:
        print("(a)+(c) 를 동시 충족하는 격자점 없음 → **λ* 없음. C2 실패. 대체 규칙 없음** (§7.3).")
        print()
        print("남는 것 (§13): frontier 형태 자체가 결과다. (b) 를 최대화하는 λ 를 고르지 않는다 —")
        print("그것은 결과를 보고 고르는 것이며 (b) 검정을 무효화한다.")
        chosen = None
    else:
        chosen = min(eligible, key=lambda record: record["lambda"])
        print(f"λ* = {chosen['lambda']}")

    # --------------------------------------------- 조건 (b): λ* 에서만 판정 (§7.3)
    if chosen is not None:
        print()
        print("=" * 104)
        print("E4 — λ* 에서 조건 (b)·(d) 판정 (primary)")
        print("=" * 104)
        encoder_config = dict(ABLATION_ENCODER_BASE)
        encoder_config["use_coverage_adversary"] = True
        encoder_config["adversary_lambda"] = chosen["lambda"]
        probe = fair_probe_module.run_heldout_timepoint_probe(
            multiview,
            encoder_config=encoder_config,
            config={"arms": ("B", "D"), "baseline_arm": "B"},
        )
        arm_summary = (probe.get("comparisons") or {}).get("arms", {}).get("D", {})
        delta = arm_summary.get("mean_r2_difference")
        p_value = arm_summary.get("sign_flip_p_value")
        chosen["condition_b_detail"] = arm_summary
        chosen["condition_b"] = bool(
            delta is not None
            and p_value is not None
            and float(delta) >= PROBE_DELTA_R2_MIN
            and float(p_value) < PROBE_P_MAX
        )
        chosen["condition_d"] = bool(
            chosen["condition_b"]
            and chosen["median_retention_ari"] >= GATE_RETENTION_ARI_MIN
        )
        print(f"ΔR² = {delta}  (임계 {PROBE_DELTA_R2_MIN})   p = {p_value}  (임계 < {PROBE_P_MAX})")
        print(f"(b) {chosen['condition_b']}   (d) {chosen['condition_d']}")
        print()
        success = bool(
            chosen["condition_a"]
            and chosen["condition_b"]
            and chosen.get("condition_c")
            and chosen["condition_d"]
        )
        print("=" * 104)
        print(f"C2 성공 (§5.5) = {success}")
        print("=" * 104)
        print("주의: E8 veto 는 2026-08-21 에 발동하지 않았다(§10.4). 따라서 §5.5 의 두 번째")
        print("      조건은 충족되어 있다. 성공 판정은 (a)(b)(c)(d) 동시 충족에만 달려 있다.")

    payload = [
        {key: value for key, value in record.items() if not key.startswith("_")}
        for record in results
    ]
    print()
    print(json.dumps({"lambda_sweep": payload}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
