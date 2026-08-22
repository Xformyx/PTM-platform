"""공정 프로브 ΔR² 이 분할 salt 에 얼마나 흔들리는가.

구현 대상: docs/c2_prereg_v1.md §12 결정성 — 2026-08-22 발견된 `hash(arm)` salt 결함의 영향
          범위 정량화. 조건 (b) 임계(§5.2)가 재현 불가한 값(0.0271)에 정박되어 있으므로
          그 정박점과 실측값의 차이가 salt 만으로 설명되는지 확인한다.
사전등록: **탐색적.** C2 판정(2026-08-21) 이후에 착수했다. 이 결과로 §5.2 임계를 바꾸지
          않으며 (b) 판정을 재선언하지도 않는다 — 사전등록은 단방향이다(§0).
          용도는 오직 **공표값의 해석 한계를 정량적으로 서술하는 것**이다.
해석 한계: 한 λ 점(λ = 0)·한 코호트·저비용 설정(epochs 150, arm B·D)에서의 흩어짐이다.
          공표값이 나온 설정(epochs 300, arm A·B·D·E)의 흩어짐과 같다고 가정하지 않는다.
          fold 는 인코더 적합을 공유하므로 서로 독립이 아니며, fold sd 를 √n 으로 나눈 값은
          실행 간 흩어짐의 추정치가 아니다. 그것이 이 측정을 하는 이유다.
주장 금지: 흩어짐이 차이를 "설명한다"고 단정하지 않는다. salt 만으로 관측된 간격이 덮이는지
          여부를 보고할 뿐이며, 덮이지 않으면 원인 미상으로 남긴다.

정본 환경:

    docker cp scripts/quantify_probe_split_sensitivity.py ptm-worker-preprocessing:/tmp/salt.py
    docker exec -i ptm-worker-preprocessing env PYTHONPATH=/app:/opt python /tmp/salt.py \
        --order-code Insulin_Signaling_Phosphoproteomics_HIRc-B
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

sys.path[:0] = ["/app", "/opt"]

PUBLISHED_DELTA_R2 = 0.0271
"""docs/ptm_representation_learning_contract_v1.md 의 arm D 공표 ΔR².

§5.2 의 임계 0.01355 가 이 값의 절반으로 선언되었다. 2026-08-22 현재 **어떤 설정에서도
재현되지 않았다** — epochs 150·arm B·D 에서 0.01597, epochs 300·arm A·B·D·E 에서 0.01697.
여기서 도입하는 값이 아니라 인용이며, 이 스크립트는 이 값을 목표로 최적화하지 않는다.
"""

SALTS = (0, 1, 2, 3)
"""임의 salt. 결함 이전 구현에서 프로세스마다 뽑히던 `hash(arm) % 9973` 을 대신한다.

탐색적 진단이므로 사전등록된 seed 집합이 아니다. 4 점은 흩어짐의 규모를 보기 위한 최소치다.
"""

ABLATION_ENCODER_BASE = {"latent_dim": 16, "hidden_dim": 64, "epochs": 150, "seed": 0,
                         "n_perturbations": 5}


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
    parser.add_argument("--arm", default="D")
    parser.add_argument("--epochs", type=int, default=ABLATION_ENCODER_BASE["epochs"])
    parser.add_argument("--probe-arms", default="B,D")
    parser.add_argument("--lambda-value", type=float, default=0.0)
    args = parser.parse_args(argv)

    from ptm_shared.representation import fair_probe as fair_probe_module

    vector = (
        Path(args.data_root) / "outputs" / args.order_code
        / "ptm_vector_data_normalized_phospho.tsv"
    )
    if not vector.exists():
        print(f"FATAL: {vector} 없음", file=sys.stderr)
        return 2

    multiview = load_eligible(vector)
    probe_arms = tuple(part.strip() for part in args.probe_arms.split(",") if part.strip())
    original = fair_probe_module._arm_seed_component
    fixed_component = {arm: original(arm) for arm in probe_arms}

    print(f"order   = {args.order_code}")
    print(f"n_sites = {multiview.n_sites}   T = {multiview.n_timepoints}")
    print(f"arm     = {args.arm}   baseline = B   프로브 arm = {list(probe_arms)}")
    print(f"epochs  = {args.epochs}   λ = {args.lambda_value}")
    print(f"고정 salt(crc32) = {fixed_component}")
    print(f"공표값 인용 = {PUBLISHED_DELTA_R2}  (재현되지 않음)")
    print()
    print("=" * 72)
    print(f"{'salt':>6} {'ΔR²':>10} {'우세/짝':>9} {'p':>9} {'fold sd':>9}")
    print("=" * 72)

    records: List[Dict[str, Any]] = []
    started = time.time()
    for salt in SALTS:
        # 결함 이전 구현의 프로세스별 salt 를 명시적으로 재현한다.
        fair_probe_module._arm_seed_component = (
            lambda arm, _salt=salt: (original(arm) + _salt * 1009) % 9973
        )
        try:
            encoder_config = dict(ABLATION_ENCODER_BASE)
            encoder_config["epochs"] = args.epochs
            encoder_config["use_coverage_adversary"] = True
            encoder_config["adversary_lambda"] = args.lambda_value
            probe = fair_probe_module.run_heldout_timepoint_probe(
                multiview,
                encoder_config=encoder_config,
                config={"arms": probe_arms, "baseline_arm": "B"},
            )
        finally:
            fair_probe_module._arm_seed_component = original

        summary = (probe.get("comparisons") or {}).get("arms", {}).get(args.arm, {})
        delta = summary.get("mean_r2_difference")
        p_value = summary.get("sign_flip_p_value")
        fraction = summary.get("fraction_of_folds_better")
        pairs = summary.get("n_paired_folds")
        fold_sd = summary.get("sd_r2_difference")
        records.append(
            {
                "salt": salt,
                "mean_r2_difference": delta,
                "sign_flip_p_value": p_value,
                "fraction_of_folds_better": fraction,
                "n_paired_folds": pairs,
                "sd_r2_difference": fold_sd,
            }
        )
        wins = None if fraction is None or pairs is None else int(round(fraction * pairs))
        print(
            f"{salt:>6}"
            f" {('       n/a' if delta is None else f'{delta:>10.5f}')}"
            f" {f'{wins}/{pairs}':>9}"
            f" {('      n/a' if p_value is None else f'{p_value:>9.4f}')}"
            f" {('      n/a' if fold_sd is None else f'{fold_sd:>9.5f}')}"
        )

    deltas = [r["mean_r2_difference"] for r in records if r["mean_r2_difference"] is not None]
    print()
    if len(deltas) >= 2:
        spread = max(deltas) - min(deltas)
        across_run_sd = statistics.stdev(deltas)
        gap = PUBLISHED_DELTA_R2 - max(deltas)
        print(f"실행 간 범위 = [{min(deltas):.5f}, {max(deltas):.5f}]   폭 {spread:.5f}")
        print(f"실행 간 sd   = {across_run_sd:.5f}   (fold sd 와 다른 양이다)")
        print(f"공표값까지 남은 간격 = {gap:+.5f}")
        print()
        if gap <= 0:
            print("salt 흩어짐이 공표값을 포함한다 → 간격은 분할 배정으로 설명된다.")
        else:
            print("salt 흩어짐이 공표값에 닿지 않는다 → 원인 미상. 다른 설정 차이가 남아 있다.")
    print()
    print(f"소요 {time.time() - started:.0f}s")
    print()
    print(json.dumps({"split_sensitivity": records}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
