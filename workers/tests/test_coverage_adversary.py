"""Regression tests for the C2 coverage adversary.

구현 대상: docs/c2_prereg_v1.md §3.1 (구조·표적), §3.2 (결정성), §7.1 (λ=0 재현 대조),
          §12 ("induced mask 가 학습 경로에 도달하지 않음을 테스트로 검증한다")
사전등록: 2026-08-21. §12 는 이 테스트 없이 결과를 보고하지 말 것을 요구한다. 여기서 고정하는
          것은 **불변식**이며 측정값이 아니다 — 어떤 임계도 이 파일에서 도입하지 않는다.
해석 한계: 이 테스트는 "구현이 사전등록된 구조와 같다"만 보장한다. adversary 가 결측 정보를
          제거하는지는 조건 (c) 의 예측기族이 판정하며 이 파일이 아니다.
주장 금지: 테스트 통과를 coverage 분리의 근거로 서술하지 않는다.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from ptm_shared.representation.coverage_adversary import (  # noqa: E402
    ADVERSARY_MODE_BEST_RESPONSE,
    ADVERSARY_MODE_CONCURRENT,
    ADVERSARY_RFF_DIM,
    ADVERSARY_SEED,
    CoverageAdversary,
    assess_convergence,
    coverage_target,
    standardize_rows_with_norm,
)
from ptm_shared.representation.coverage_probes import RFF_DIM  # noqa: E402
from ptm_shared.representation.encoder import fit_masked_temporal_encoder  # noqa: E402
from ptm_shared.representation.feature_contract import build_multiview_input  # noqa: E402
from ptm_shared.representation.metrics import standardize_rows  # noqa: E402


N_SITES = 60
TIMEPOINTS = ["1min", "5min", "15min", "30min", "60min", "120min"]
BASE_CONFIG = {"epochs": 25, "latent_dim": 8, "hidden_dim": 24, "n_perturbations": 0, "seed": 0}


@pytest.fixture(scope="module")
def multiview():
    """Small synthetic cohort with heterogeneous per-site coverage.

    실데이터가 아니라 합성 입력을 쓴다. 이 파일이 고정하는 것은 불변식이므로 특정 코호트의
    수치를 재현할 필요가 없고, 그래야 테스트가 데이터 표류에 영향받지 않는다.
    """
    rng = np.random.default_rng(11)
    rows = []
    for index in range(N_SITES):
        phase = rng.uniform(0.0, 2.0 * np.pi)
        trajectory = np.sin(np.linspace(0.0, 2.0 * np.pi, len(TIMEPOINTS)) + phase) * 2.0
        # 사이트별로 결측 시점 수를 달리해 coverage 가 이질적이 되게 한다. 동질적이면
        # adversary 표적에 분산이 없어 §3.1 의 표적 자체가 정의되지 않는다.
        hidden = set(rng.choice(len(TIMEPOINTS), size=index % 3, replace=False).tolist())
        for time_index, timepoint in enumerate(TIMEPOINTS):
            if time_index in hidden:
                continue
            rows.append(
                {
                    "Protein.Group": f"P{index:05d}",
                    "Gene.Name": f"G{index}",
                    "PTM_Position": "S100",
                    "Modified.Sequence": f"AAAS{index}TSK",
                    "PTM_Type": "Phosphorylation",
                    "Condition": timepoint,
                    "Comparison": f"{timepoint}_vs_Control",
                    "PTM_Relative_Log2FC": float(trajectory[time_index]),
                    "Protein_Log2FC": 0.1 * float(trajectory[time_index]),
                    "q_value": 0.01,
                    "p_value": 0.005,
                    "Quantification_Track": "protein_normalized_relative_ptm",
                    "Occupancy_Logit_Delta": float("nan"),
                    "Pair_Quality_Tier": "O0",
                    "Pair_Missingness": 0.0,
                }
            )
    return build_multiview_input(rows)


def _fit(multiview, **overrides):
    config = {**BASE_CONFIG, **overrides}
    return fit_masked_temporal_encoder(multiview, config=config)


def test_adversary_features_match_the_predictor_family_features():
    """§3.1 — adversary 와 조건 (c) 는 **같은 특징**을 보아야 한다.

    다르면 "adversary 가 판정 대상을 겨냥한다"는 서술이 방어되지 않는다.
    """
    latent = np.random.default_rng(3).normal(size=(25, 7))
    mine, norm = standardize_rows_with_norm(latent)
    assert np.array_equal(mine, standardize_rows(latent))
    assert norm.shape == (25, 1)
    assert np.allclose(np.linalg.norm(mine, axis=1), 1.0)


def test_adversary_rff_dimension_equals_the_predictor_family_dimension():
    """§3.1 개정 — 헤드 2 는 P4 와 같은 사상을 써야 한다."""
    assert ADVERSARY_RFF_DIM == RFF_DIM


def test_adversary_is_disabled_by_default(multiview):
    """기본값이 켜져 있으면 공표된 A–E arm 수치가 조용히 바뀐다."""
    result = _fit(multiview)
    assert result.provenance["config"]["use_coverage_adversary"] is False
    assert result.provenance["config"]["adversary_lambda"] == 0.0
    assert "coverage_adversary" not in result.provenance


def test_lambda_zero_reproduces_the_adversary_free_fit(multiview):
    """§7.1 — λ = 0 은 D 재현 대조다. 비트 단위로 같아야 한다.

    같지 않으면 λ sweep 의 원점이 D 가 아니게 되고 frontier 전체의 해석이 무너진다.
    """
    without = _fit(multiview)
    with_lambda_zero = _fit(multiview, use_coverage_adversary=True, adversary_lambda=0.0)
    assert np.array_equal(without.embedding, with_lambda_zero.embedding)
    assert np.array_equal(without.reconstruction, with_lambda_zero.reconstruction)
    # λ = 0 에서도 헤드는 학습되므로 진단은 기록된다 (판정에는 쓰이지 않는다).
    assert with_lambda_zero.provenance["coverage_adversary"]["status"] == "active"
    assert with_lambda_zero.provenance["coverage_adversary"]["lambda"] == 0.0


def test_positive_lambda_changes_the_embedding(multiview):
    """λ > 0 이 아무 효과가 없으면 gradient reversal 이 연결되지 않은 것이다."""
    baseline = _fit(multiview, use_coverage_adversary=True, adversary_lambda=0.0)
    penalised = _fit(multiview, use_coverage_adversary=True, adversary_lambda=1.0)
    assert not np.array_equal(baseline.embedding, penalised.embedding)


def test_reversal_pushes_the_adversary_loss_up(multiview):
    """부호 방향 — 인코더는 adversary 손실을 **올려야** 한다.

    부호가 뒤집혀 있으면 결측률을 더 잘 인코딩하도록 학습되며, 그 결과는 조용히 그럴듯하다.
    이것이 이 파일에서 가장 중요한 테스트다.
    """
    baseline = _fit(multiview, use_coverage_adversary=True, adversary_lambda=0.0)
    penalised = _fit(multiview, use_coverage_adversary=True, adversary_lambda=5.0)
    without = baseline.training_history[-1]["adversary_loss"]
    against = penalised.training_history[-1]["adversary_loss"]
    assert against > without


def test_adversary_target_is_the_input_missingness_rate(multiview):
    """§3.1 — 표적은 입력의 관측 행렬에서만 나온다."""
    expected = 1.0 - multiview.target.observed.mean(axis=1)
    assert np.array_equal(coverage_target(multiview.target.observed), expected)


def test_induced_mask_reaches_training_only_through_the_input(multiview):
    """§12 필수 테스트 — induced 배열이 학습 경로에 직접 도달하지 않는다.

    마스킹 재적합에서 adversary 표적은 natural + induced 결측률과 **같다**. 즉 induced 는
    입력의 관측 행렬을 통해서만 들어오며, 배열 자체는 어떤 손실에도 들어가지 않는다.
    이 동일성이 성립하는 한 gate 는 자기 표적을 최적화한 결과가 아니다.
    """
    masked, induced = multiview.with_additional_target_masking(fraction=0.15, seed=0)
    assert int(induced.sum()) > 0
    natural = coverage_target(multiview.target.observed)
    combined = coverage_target(masked.target.observed)
    assert np.allclose(combined, natural + induced.mean(axis=1))

    # 인코더는 induced 를 인자로 받지 않는다. 표적은 masked 입력만으로 재구성된다.
    fitted = _fit(masked, use_coverage_adversary=True, adversary_lambda=0.5)
    adversary = fitted.provenance["coverage_adversary"]
    assert adversary["induced_mask_used"] is False
    assert adversary["target"] == "input_target_observed_missingness_rate"
    rebuilt = CoverageAdversary(8, combined, seed=ADVERSARY_SEED)
    assert round(rebuilt.target_mean, 8) == adversary["target_mean"]
    assert round(rebuilt.target_scale, 8) == adversary["target_scale"]


def test_encoder_seed_and_adversary_seed_are_recorded_separately(multiview):
    """§3.2·§12 — 두 seed 가 구분되어 기록되어야 한다."""
    result = _fit(multiview, use_coverage_adversary=True, adversary_lambda=1.0, seed=0)
    assert result.provenance["config"]["seed"] == 0
    assert result.provenance["coverage_adversary"]["seed"] == ADVERSARY_SEED
    assert ADVERSARY_SEED != 0


def test_fit_is_deterministic_under_the_adversary(multiview):
    """결정성 — 같은 설정은 같은 임베딩을 낸다. 재현 불가한 수치는 논문에 쓸 수 없다."""
    first = _fit(multiview, use_coverage_adversary=True, adversary_lambda=1.0)
    second = _fit(multiview, use_coverage_adversary=True, adversary_lambda=1.0)
    assert np.array_equal(first.embedding, second.embedding)


def test_history_records_the_three_losses(multiview):
    """§3.2 — epoch 별 recon / smooth / adversary loss 를 남긴다."""
    result = _fit(multiview, use_coverage_adversary=True, adversary_lambda=1.0)
    entry = result.training_history[-1]
    for key in ("reconstruction_loss", "smoothness_loss", "adversary_loss"):
        assert key in entry
    assert "adversary_loss_rff_head" in entry
    assert "adversary_loss_linear_head" in entry


def test_best_response_is_the_default_mode(multiview):
    """§3.1 최적반응 개정 — 동시하강은 판정 대상보다 구조적으로 약하다."""
    result = _fit(multiview, use_coverage_adversary=True, adversary_lambda=1.0)
    adversary = result.provenance["coverage_adversary"]
    assert adversary["mode"] == ADVERSARY_MODE_BEST_RESPONSE
    assert adversary["estimation"] == "in_sample"
    assert adversary["heads"] == ["ols_intercept", "rff_ridge"]
    # 결정성 기록: solver 경로가 남아야 재현 가능하다.
    assert adversary["head_solver"]["linear"] == "numpy.linalg.lstsq"


def test_best_response_head_beats_the_concurrent_head(multiview):
    """같은 임베딩에서 최적반응 손실이 더 낮아야 한다. 아니면 '최적'이 아니다.

    이 부등식이 개정의 근거다 — gate 지표와 예측기族은 최적반응 적합이므로, 동시하강 헤드로
    학습한 인코더는 판정 대상을 실제로 겪지 않은 채 손실만 올릴 수 있다.
    """
    latent = _fit(multiview).embedding
    target = coverage_target(multiview.target.observed)
    concurrent = CoverageAdversary(
        latent.shape[1], target, mode=ADVERSARY_MODE_CONCURRENT
    )
    best = CoverageAdversary(latent.shape[1], target, mode=ADVERSARY_MODE_BEST_RESPONSE)
    assert best.loss_and_latent_gradient(latent)[0] < concurrent.loss_and_latent_gradient(latent)[0]


def test_best_response_mode_trains_no_head_parameters(multiview):
    """최적반응은 닫힌 형태로 풀리므로 학습할 헤드 파라미터가 없다."""
    latent = _fit(multiview).embedding
    best = CoverageAdversary(latent.shape[1], coverage_target(multiview.target.observed))
    _, _, _, gradients = best.loss_and_latent_gradient(latent)
    assert gradients == {}


def test_rff_bandwidth_is_frozen_after_the_first_call(multiview):
    """대역폭이 매 호출 재추정되면 사상이 잠재값의 함수가 되어 기울기가 틀린다."""
    target = coverage_target(multiview.target.observed)
    best = CoverageAdversary(8, target)
    first = best.loss_and_latent_gradient(np.random.default_rng(0).normal(size=(target.size, 8)))
    frozen = best.last_bandwidth
    assert np.isfinite(frozen)
    best.loss_and_latent_gradient(np.random.default_rng(1).normal(size=(target.size, 8)) * 7.0)
    assert best.last_bandwidth == frozen
    assert first[1]["adversary_rff_bandwidth"] == round(frozen, 8)


def test_unknown_adversary_mode_is_rejected():
    """조용히 기본값으로 넘어가면 어떤 방법을 썼는지 기록이 거짓이 된다."""
    with pytest.raises(ValueError):
        CoverageAdversary(8, np.linspace(0.0, 0.5, 30), mode="whatever")


def test_convergence_verdict_is_recorded(multiview):
    """§3.3 — 발산 판정 결과가 산출 레코드에 남아야 한다."""
    result = _fit(multiview, use_coverage_adversary=True, adversary_lambda=1.0)
    verdict = result.provenance["coverage_adversary"]["convergence"]
    assert verdict["status"] == "evaluated"
    assert isinstance(verdict["converged"], bool)


def test_divergence_is_detected_when_reconstruction_blows_up():
    """§3.3 판정식이 실제로 발산을 잡는지 — 합성 history 로 확인한다."""
    history = [{"reconstruction_loss": 1.0} for _ in range(50)]
    history += [{"reconstruction_loss": 9.0} for _ in range(50)]
    verdict = assess_convergence(history)
    assert verdict["diverged"] is True
    assert verdict["reason"] == "reconstruction_loss_exceeded_2x_initial"


def test_negative_lambda_is_clamped(multiview):
    """음수 λ 는 결측률을 더 잘 인코딩하도록 학습시키는 것이며 §3.1 의 방법이 아니다."""
    result = _fit(multiview, use_coverage_adversary=True, adversary_lambda=-1.0)
    assert result.provenance["config"]["adversary_lambda"] == 0.0


def test_adversary_stands_down_on_a_degenerate_target():
    """표적에 분산이 없으면 적용하지 않고 그 사실을 기록한다."""
    adversary = CoverageAdversary(8, np.full(30, 0.25))
    assert adversary.active is False
    assert adversary.status == "not_applied_target_has_no_variance"
    loss, detail, gradient, gradients = adversary.loss_and_latent_gradient(np.zeros((30, 8)))
    assert loss == 0.0 and not detail and not gradients
    assert np.array_equal(gradient, np.zeros((30, 8)))


def test_adversary_stands_down_below_the_minimum_latent_dimension():
    """차원 1 에서 행 표준화는 항상 0 이므로 adversary 는 정의되지 않는다."""
    adversary = CoverageAdversary(1, np.linspace(0.0, 0.5, 30))
    assert adversary.active is False
    assert adversary.status == "not_applied_latent_dim_below_minimum"
