"""Finite-difference check of the coverage adversary's hand-written backward pass.

구현 대상: docs/c2_prereg_v1.md §3.1 구현의 정확성 확인. 사전등록된 실험이 아니다.
사전등록: 해당 없음 — 판정에 쓰이는 수치를 생산하지 않는다. 구현 검증 도구다.
해석 한계: 기울기가 맞다는 것은 **최적화가 의도한 목적을 내려간다**는 뜻일 뿐이며
          adversary 가 결측 정보를 제거한다는 뜻이 아니다. 그 판정은 조건 (c) 가 한다.
주장 금지: 이 검증 통과를 C2 의 어떤 주장 근거로도 쓰지 않는다.

수동 역전파는 논문 수치의 신뢰를 좌우한다. 부호 하나가 틀리면 gradient reversal 이 사실은
결측률을 **더 잘** 인코딩하도록 학습시키게 되고, 그 결과는 조용히 그럴듯해 보인다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ptm_shared.representation.coverage_adversary import (  # noqa: E402
    ADVERSARY_MODE_BEST_RESPONSE,
    ADVERSARY_MODE_CONCURRENT,
    CoverageAdversary,
    standardize_rows_with_norm,
)
from ptm_shared.representation.metrics import standardize_rows  # noqa: E402

EPSILON = 1e-6
TOLERANCE = 1e-6


def _loss(adversary: CoverageAdversary, latent: np.ndarray) -> float:
    return adversary.loss_and_latent_gradient(latent)[0]


def main() -> int:
    rng = np.random.default_rng(20260821)
    n_rows, latent_dim = 40, 6
    latent = rng.normal(size=(n_rows, latent_dim))
    target = rng.integers(0, 3, size=n_rows).astype(float) / 6.0

    print("=== standardize_rows 일치 (adversary 입력 == 예측기族 입력) ===")
    mine, _ = standardize_rows_with_norm(latent)
    theirs = standardize_rows(latent)
    deviation = float(np.max(np.abs(mine - theirs)))
    print(f"max |차이| = {deviation:.3e}   {'OK' if deviation < 1e-12 else 'MISMATCH'}")
    if deviation >= 1e-12:
        return 1

    adversary = CoverageAdversary(
        latent_dim, target, seed=1, hidden_dim=5, rff_dim=16, mode=ADVERSARY_MODE_CONCURRENT
    )
    if not adversary.active:
        print(f"adversary 비활성: {adversary.status}")
        return 1

    # RFF 헤드 가중치를 0 이 아닌 값으로 채운다. 초기값 0 이면 RFF 경로의 기울기가 항상 0 이라
    # 그 경로를 검증하지 못한다 — 대역폭 의존성 버그를 놓친 원인이 정확히 이것이었다.
    adversary.params["wr"] = rng.normal(scale=0.3, size=adversary.params["wr"].shape)
    adversary.params["br"] = np.array([0.2])

    print("\n=== concurrent 모드: d(loss)/d(latent) 유한차분 (RFF 가중치 비영) ===")
    _, _, analytic, param_grads = adversary.loss_and_latent_gradient(latent)
    numeric = np.zeros_like(latent)
    for row in range(n_rows):
        for column in range(latent_dim):
            shifted = latent.copy()
            shifted[row, column] += EPSILON
            plus = _loss(adversary, shifted)
            shifted[row, column] -= 2.0 * EPSILON
            minus = _loss(adversary, shifted)
            numeric[row, column] = (plus - minus) / (2.0 * EPSILON)
    scale = max(float(np.max(np.abs(numeric))), 1e-12)
    error = float(np.max(np.abs(analytic - numeric))) / scale
    print(f"상대 최대 오차 = {error:.3e}   {'OK' if error < TOLERANCE * 1e3 else 'MISMATCH'}")
    if error >= TOLERANCE * 1e3:
        return 1

    print("\n=== d(loss)/d(파라미터) 유한차분 ===")
    failures = 0
    for key, analytic_grad in param_grads.items():
        flat = adversary.params[key].reshape(-1)
        numeric_grad = np.zeros_like(flat)
        for index in range(flat.size):
            original = flat[index]
            flat[index] = original + EPSILON
            plus = _loss(adversary, latent)
            flat[index] = original - EPSILON
            minus = _loss(adversary, latent)
            flat[index] = original
            numeric_grad[index] = (plus - minus) / (2.0 * EPSILON)
        reference = max(float(np.max(np.abs(numeric_grad))), 1e-12)
        relative = float(np.max(np.abs(analytic_grad.reshape(-1) - numeric_grad))) / reference
        verdict = "OK" if relative < TOLERANCE * 1e3 else "MISMATCH"
        if verdict != "OK":
            failures += 1
        print(f"  {key:5s}  상대 최대 오차 = {relative:.3e}   {verdict}")
    if failures:
        return 1

    print("\n=== 부호 방향: adversary 갱신이 손실을 내리는가 ===")
    before = _loss(adversary, latent)
    for _ in range(30):
        _, _, _, gradients = adversary.loss_and_latent_gradient(latent)
        adversary.apply_update(gradients)
    after = _loss(adversary, latent)
    print(f"loss {before:.6f} → {after:.6f}   {'OK' if after < before else 'WRONG SIGN'}")
    if after >= before:
        return 1

    # -------------------------------------------------------------- best_response
    # 여기서 검증하는 것은 envelope theorem 이다. 헤드가 최적해에 있으므로 L*(U) 의 전미분은
    # w 를 고정한 편미분과 같아야 한다. 유한차분은 **매번 헤드를 다시 최적화**하므로
    # 전미분을 재고, 해석 기울기는 편미분을 낸다. 두 값이 일치하면 정리가 성립하는 것이다.
    best = CoverageAdversary(
        latent_dim, target, seed=1, rff_dim=16, mode=ADVERSARY_MODE_BEST_RESPONSE
    )
    print("\n=== best_response 모드: envelope theorem 검증 ===")
    _, _, analytic_best, empty = best.loss_and_latent_gradient(latent)
    if empty:
        print("최적반응 모드에서 학습할 헤드 파라미터가 남아 있다 — 구현 오류")
        return 1
    numeric_best = np.zeros_like(latent)
    for row in range(n_rows):
        for column in range(latent_dim):
            shifted = latent.copy()
            shifted[row, column] += EPSILON
            plus = _loss(best, shifted)
            shifted[row, column] -= 2.0 * EPSILON
            minus = _loss(best, shifted)
            numeric_best[row, column] = (plus - minus) / (2.0 * EPSILON)
    reference = max(float(np.max(np.abs(numeric_best))), 1e-12)
    error = float(np.max(np.abs(analytic_best - numeric_best))) / reference
    print(f"상대 최대 오차 = {error:.3e}   {'OK' if error < 1e-3 else 'MISMATCH'}")
    if error >= 1e-3:
        return 1

    print("\n=== 최적반응이 동시하강보다 강한가 (같은 임베딩에서) ===")
    concurrent_loss = _loss(adversary, latent)
    best_loss = _loss(best, latent)
    print(f"concurrent {concurrent_loss:.6f}   best_response {best_loss:.6f}"
          f"   {'OK' if best_loss < concurrent_loss else 'UNEXPECTED'}")

    print("\n모든 검증 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
