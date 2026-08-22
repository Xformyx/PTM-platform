"""Exploratory — is the low-dimension regime a usable starting point for C2?

구현 대상: 없음. `docs/c2_prereg_v1.md` 에 사전등록된 실험이 아니다.
사전등록: **없음. 결과 열람 후 착수한 탐색적(exploratory) 진단이다.**
          E8 (§10) 결과를 본 뒤 그 해석을 위해 실행한다. 사전등록 규칙(§0, §11)에 따라
          **primary 판정으로 승격할 수 없으며 C2 성공/실패의 근거로 쓸 수 없다.**
          이 사실을 결과와 함께 반드시 표기한다.
해석 한계: E8 에서 latent_dim = 8 구성이 coverage 하위 조건(induced R² ≤ 0.25)은 통과하고
          retention ARI 조건에서만 실패했다. 이 진단이 묻는 것은 두 가지다 —
          (1) 그 구성에서 예측력(조건 b)이 남아 있는가,
          (2) gate 의 선형 지표가 통과했을 때 예측기族(조건 c)도 통과하는가.
          단일 구성·단일 seed 진단이며 격자 전체를 대표하지 않는다.
주장 금지: 이 결과로 latent_dim 을 낮추는 것이 해법이라고 서술하지 않는다.
          C2 의 방법 기여에 대한 어떤 주장도 이 진단에 근거하지 않는다.

정본 환경:

    docker exec -i ptm-worker-preprocessing env PYTHONPATH=/app:/opt python - \
        --order-code Insulin_Signaling_Phosphoproteomics_HIRc-B \
        < scripts/probe_c2_low_dimension_regime.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path[:0] = ["/app", "/opt"]

import numpy as np

# E8 에서 retention ARI 가 가장 높았던 구성. l2 축은 E8 에서 효과가 없었다.
PROBE_CONFIGS = (
    {"latent_dim": 8, "l2": 1e-4, "input_mask_fraction": 0.30},
    {"latent_dim": 8, "l2": 1e-4, "input_mask_fraction": 0.15},
    {"latent_dim": 16, "l2": 1e-4, "input_mask_fraction": 0.30},
)

ABLATION_ENCODER_BASE = {"hidden_dim": 64, "epochs": 150, "seed": 0, "n_perturbations": 5}
ABLATION_BENCHMARK_CONFIG = {"neighbors": 10, "leave_one_out": False, "minimum_sites": 8,
                             "seed": 0}

# 동결 임계 (docs/c2_prereg_v1.md §14.2). 참조용이며 여기서 판정하지 않는다.
FAMILY_R2_MAX = 0.25
PROBE_DELTA_R2_MIN = 0.01355
PROBE_P_MAX = 0.05


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--order-code", required=True)
    parser.add_argument("--data-root", default="/app/data")
    parser.add_argument(
        "--skip-family",
        action="store_true",
        help="예측기族을 다시 계산하지 않는다 (이미 측정된 경우)",
    )
    args = parser.parse_args(argv)

    import pandas as pd

    from ptm_shared.representation import build_multiview_input
    from ptm_shared.representation import fair_probe as fair_probe_module
    from ptm_shared.representation.benchmark import (
        DEFAULT_BENCHMARK_CONFIG,
        _missingness_r2,
        fit_variant,
    )
    from ptm_shared.representation.coverage_probes import residual_mask_recoverability
    from ptm_shared.representation.layers import resolve_variant

    vector = (
        Path(args.data_root) / "outputs" / args.order_code
        / "ptm_vector_data_normalized_phospho.tsv"
    )
    frame = pd.read_csv(vector, sep="\t", low_memory=False)
    multiview = build_multiview_input(
        frame.to_dict("records"),
        config={"key_level": "form", "minimum_observed_timepoints": 3},
    ).eligible_subset()

    arm = resolve_variant("D")
    config = dict(DEFAULT_BENCHMARK_CONFIG)
    config.update(ABLATION_BENCHMARK_CONFIG)

    print("탐색적 진단 — 사전등록 없음. primary 판정 승격 금지.")
    print(f"n_sites = {multiview.n_sites}   T = {multiview.n_timepoints}")
    print()

    records = []
    for setting in PROBE_CONFIGS:
        encoder_config = dict(ABLATION_ENCODER_BASE)
        encoder_config.update(setting)
        label = (f"latent={setting['latent_dim']}"
                 f" in_mask={setting['input_mask_fraction']:.2f}")
        print("=" * 78)
        print(label)
        print("=" * 78)

        masked_input, induced = multiview.with_additional_target_masking(
            fraction=config["artificial_mask_fraction"], seed=0
        )
        masked_encoder = dict(encoder_config)
        masked_encoder["n_perturbations"] = 0
        masked_fit = fit_variant(
            masked_input, arm, encoder_config=masked_encoder, config=config
        )
        rate = induced.mean(axis=1)
        linear_r2 = _missingness_r2(masked_fit.embedding, rate)
        print(f"  gate 지표 P1 (표본 내 선형)  = {linear_r2}")
        family: dict = {}
        family_max = None
        if not args.skip_family:
            family = residual_mask_recoverability(masked_fit.embedding, rate)
            family_max = family.get("family_max_out_of_sample_r2")
            for name, values in (family.get("per_predictor") or {}).items():
                print(f"  {name:<22} = {values['out_of_sample_r2']}")
            print(f"  族 최대                      = {family_max}"
                  f"   (임계 {FAMILY_R2_MAX} → {'통과' if family_max is not None and family_max <= FAMILY_R2_MAX else '미충족'})")

        probe = fair_probe_module.run_heldout_timepoint_probe(
            multiview,
            encoder_config=encoder_config,
            config={"arms": ("B", "D"), "baseline_arm": "B"},
        )
        summary = {}
        if probe.get("status") == "evaluated":
            summary = (probe.get("comparisons") or {}).get("arms", {}).get("D", {})
            delta = summary.get("mean_r2_difference")
            p_value = summary.get("sign_flip_p_value")
            keeps = (
                delta is not None and p_value is not None
                and float(delta) >= PROBE_DELTA_R2_MIN and float(p_value) < PROBE_P_MAX
            )
            print(f"  프로브 ΔR² (B 대비)          = {delta}"
                  f"   p = {p_value}   우세 fold = {summary.get('fraction_of_folds_better')}")
            print(f"  조건 (b) 기준 ΔR² ≥ {PROBE_DELTA_R2_MIN} 및 p < {PROBE_P_MAX}"
                  f" → {'충족' if keeps else '미충족'}")
        else:
            print(f"  프로브 status = {probe.get('status')}")
        print()
        records.append(
            {
                "setting": setting,
                "gate_linear_r2": linear_r2,
                "family": family,
                "probe": summary,
            }
        )

    print("=" * 78)
    print(json.dumps(records, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
