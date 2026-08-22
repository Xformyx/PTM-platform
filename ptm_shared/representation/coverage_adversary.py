"""Gradient-reversal coverage adversary for the C2 encoder.

구현 대상: docs/c2_prereg_v1.md §3.1 (구조. 2026-08-21 헤드 강화 개정 포함), §3.2 (결정성)
사전등록: 2026-08-21 동결. 구조·표적·seed·격자가 E4 착수 **전에** 확정되었다.
          두 번째 헤드(RFF)는 §10.5 탐색적 진단을 본 뒤 추가한 **방법 개정**이며
          판정 규칙(§5 의 (a)–(d), §14.2 임계)은 바뀌지 않았다. 개정은 §15 에 기록.
해석 한계: 이 adversary 가 겨냥하는 것은 임베딩의 **행 표준화된 형태**에서 선형·매끄러운
          비선형으로 회수되는 결측률 성분이다. kNN 이 이용하는 국소 구조에 직접 대응하는
          미분 가능한 헤드는 없으므로, **두 헤드를 이겼다는 것이 결측 정보가 제거되었음을
          뜻하지 않는다.** 그 판정은 조건 (c) 의 예측기族(`coverage_probes.py`)이 한다.
주장 금지: adversary loss 가 올라간 것을 "coverage 로부터 독립인 표현을 얻었다"로 서술하지
          않는다. 이 모듈로 kinase 예측 정확도나 생물학적 타당도를 논하지 않는다.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np


ADVERSARY_HIDDEN_DIM = 16
"""헤드 1 의 tanh 은닉 폭.

docs/c2_prereg_v1.md §3.1 에서 2026-08-20 선언, 2026-08-21 동결. E4 측정 착수 전.
"""

ADVERSARY_RFF_DIM = 512
"""헤드 2 의 random Fourier feature 차원.

docs/c2_prereg_v1.md §3.1 헤드 강화 개정(2026-08-21)에서 선언. 조건 (c) 의 P4 와 **같은 값**을
쓴다(`coverage_probes.RFF_DIM`). 서로 다른 차원을 쓰면 adversary 가 P4 를 겨냥한다는 서술이
방어되지 않는다. 변경 시 두 곳을 함께 바꾸고 사유를 §15 에 남긴다.
"""

ADVERSARY_SEED = 1
"""adversary 파라미터·RFF 사상 초기화 seed.

docs/c2_prereg_v1.md §12 에서 2026-08-21 선언. **인코더 seed(0)와 분리한다** — 같은 값이면
adversary 초기화가 인코더 초기화와 상관되어 결정성 기록의 의미가 흐려진다.
"""

BEST_RESPONSE_RIDGE = 1e-3
"""헤드 2 의 최적반응 해에 쓰는 고정 ridge 벌점.

docs/c2_prereg_v1.md §3.1 최적반응 개정(2026-08-21)에서 선언. E4 재실행 **전**이다.
매 epoch 내부 CV 를 돌 수 없으므로 고정값을 쓴다. 조건 (c) 의 P4 는 벌점을 내부 CV 로
고르므로(§4.1) adversary 가 P4 와 **정확히 같은 예측기를 겨냥하지는 않는다.** 이 괴리는
해석 한계이며, adversary 를 이긴 것이 P4 를 이긴 것을 뜻하지 않는 이유 중 하나다.
"""

ADVERSARY_MODE_BEST_RESPONSE = "best_response"
ADVERSARY_MODE_CONCURRENT = "concurrent"
"""adversary 헤드의 학습 방식.

`concurrent`  헤드도 Adam 으로 함께 내려간다. §3.1 의 최초 명세(2026-08-20).
`best_response` 매 epoch 헤드의 **정확한 최소해**를 닫힌 형태로 구한다. 2026-08-21 개정.

개정 사유(측정 기반, E4 판정 전): `concurrent` 로 λ 격자를 돌린 결과 adversary 손실은
λ 와 함께 올라갔는데(1.36 → 2.06, 헤드가 평균 예측 수준으로 무력화) **같은 임베딩에
최소제곱을 다시 적합하면 같은 표적의 R² 이 0.72–0.85 로 그대로였다.** 즉 헤드는 움직이는
인코더를 뒤쫓지 못해 최적해에 도달하지 못했고, 인코더는 정보를 제거할 필요가 없었다.
gate 지표와 예측기族은 **최적반응 적합**이므로, 동시 하강 헤드는 판정 대상보다 구조적으로
약하다. 기본값을 `best_response` 로 둔다.
"""

MINIMUM_LATENT_DIM = 2
"""adversary 가 평가 가능한 최소 잠재 차원.

행 표준화(중심화 후 L2 정규화)는 차원 1 에서 항상 0 을 낸다. 따라서 latent_dim < 2 에서는
adversary 를 적용하지 않고 그 사실을 기록한다. 임계가 아니라 정의역 제약이다.
"""

BANDWIDTH_SUBSAMPLE = 512
"""RFF 대역폭의 median heuristic 에 쓰는 행 부표본 크기.

`coverage_probes._median_bandwidth` 와 같은 값. 부표본 색인은 학습 시작 시 한 번 뽑아
고정하므로 epoch 간 대역폭 변화는 잠재공간 변화만 반영한다(결정적).
"""


def standardize_rows_with_norm(matrix: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Row-centre and L2-normalise, returning the norms needed for the backward pass.

    `metrics.standardize_rows` 와 **수치적으로 같은 결과**를 내야 한다. 조건 (c) 의 예측기族이
    보는 특징과 adversary 가 보는 특징이 달라지면 "adversary 가 판정 대상을 겨냥한다"는 서술이
    방어되지 않는다. 두 구현의 일치는 회귀 테스트로 고정한다.
    """
    values = np.nan_to_num(np.asarray(matrix, dtype=float), nan=0.0, posinf=0.0, neginf=0.0)
    centred = values - values.mean(axis=1, keepdims=True)
    norm = np.linalg.norm(centred, axis=1, keepdims=True)
    norm = np.where(norm < 1e-12, 1.0, norm)
    return centred / norm, norm


def _standardize_rows_backward(
    upstream: np.ndarray, standardized: np.ndarray, norm: np.ndarray
) -> np.ndarray:
    """Backward pass of row centring plus L2 normalisation.

    u = (z - mean(z)) / ||z - mean(z)|| 에 대해
    dL/dz = (g - mean(g) - u * <g, u>) / ||z - mean(z)||   (행별)

    이 항이 있어야 인코더가 **잠재 크기를 키워 adversary 를 무력화하는 우회**를 할 수 없다.
    행 정규화가 크기를 제거하므로 그 우회 경로 자체가 닫힌다.
    """
    row_mean = upstream.mean(axis=1, keepdims=True)
    projection = (upstream * standardized).sum(axis=1, keepdims=True)
    return (upstream - row_mean - standardized * projection) / norm


def _median_bandwidth(features: np.ndarray, index: np.ndarray) -> float:
    """Median pairwise distance on a fixed row subsample."""
    subset = features[index]
    squared = (subset ** 2).sum(axis=1)
    distances = np.sqrt(
        np.maximum(squared[:, None] - 2.0 * subset @ subset.T + squared[None, :], 0.0)
    )
    upper = distances[np.triu_indices_from(distances, k=1)]
    median = float(np.median(upper)) if upper.size else 1.0
    return median if median > 1e-9 else 1.0


def coverage_target(observed: np.ndarray) -> np.ndarray:
    """Per-site missingness rate of the input the encoder was actually given.

    구현 대상: docs/c2_prereg_v1.md §3.1 (표적 정의)
    사전등록: 2026-08-21. **`induced` 배열을 인자로 받지 않는다.** 표적은 입력의 관측 행렬
              하나에서만 계산된다. 마스킹 재적합에서는 그 행렬이 이미 natural + induced 를
              반영하므로, adversary 는 induced 를 따로 보지 않으면서 gate 가 재는 양을 겨냥한다.
    해석 한계: 관측 시점 수가 4–6 이므로 표적은 3–4 개 값만 갖는 이산량이다
              (§2.3 영값 편중 30.36%). 연속 회귀처럼 해석하지 않는다.
    주장 금지: 이 표적을 "결측 메커니즘"이라 부르지 않는다. 관측 비율의 사이트별 요약이다.
    """
    matrix = np.asarray(observed, dtype=bool)
    if matrix.size == 0:
        return np.zeros(matrix.shape[0], dtype=float)
    return 1.0 - matrix.mean(axis=1)


class CoverageAdversary:
    """Two-head missingness predictor trained against the encoder via gradient reversal.

    구현 대상: docs/c2_prereg_v1.md §3.1
    사전등록: 2026-08-21 동결. λ 격자는 §7.1 의 8 점이며 이 클래스는 격자를 정의하지 않는다.
    해석 한계: 두 헤드는 전역 선형·매끄러운 비선형만 덮는다(§3.1 개정 주석).
    주장 금지: 헤드를 이긴 것을 독립성의 증거로 서술하지 않는다.
    """

    def __init__(
        self,
        latent_dim: int,
        target: np.ndarray,
        *,
        seed: int = ADVERSARY_SEED,
        hidden_dim: int = ADVERSARY_HIDDEN_DIM,
        rff_dim: int = ADVERSARY_RFF_DIM,
        learning_rate: float = 0.01,
        mode: str = ADVERSARY_MODE_BEST_RESPONSE,
    ) -> None:
        self.latent_dim = int(latent_dim)
        self.hidden_dim = int(hidden_dim)
        self.rff_dim = int(rff_dim) - int(rff_dim) % 2
        self.learning_rate = float(learning_rate)
        self.seed = int(seed)
        self.mode = str(mode)
        if self.mode not in (ADVERSARY_MODE_BEST_RESPONSE, ADVERSARY_MODE_CONCURRENT):
            raise ValueError(f"unknown adversary mode {mode!r}")
        self.status = "active"

        raw_target = np.asarray(target, dtype=float)
        spread = float(np.std(raw_target)) if raw_target.size else 0.0
        if self.latent_dim < MINIMUM_LATENT_DIM:
            self.status = "not_applied_latent_dim_below_minimum"
        elif spread < 1e-12:
            self.status = "not_applied_target_has_no_variance"

        # 표적을 단위 분산으로 맞춘다. 그래야 MSE 가 (1 − R²) 와 같은 눈금이 되고 λ 의 의미가
        # 결측률의 임의 눈금에 얽히지 않는다. 이 정규화는 §3.1 표적 정의를 바꾸지 않는다.
        self.target_mean = float(np.mean(raw_target)) if raw_target.size else 0.0
        self.target_scale = spread if spread >= 1e-12 else 1.0
        self.target = (raw_target - self.target_mean) / self.target_scale

        rng = np.random.default_rng(self.seed)

        def _init(rows: int, columns: int) -> np.ndarray:
            limit = float(np.sqrt(6.0 / max(rows + columns, 1)))
            return rng.uniform(-limit, limit, size=(rows, columns))

        self.params: Dict[str, np.ndarray] = {
            "Wh1": _init(self.latent_dim, self.hidden_dim),
            "bh1": np.zeros(self.hidden_dim),
            "wh2": _init(self.hidden_dim, 1).reshape(-1),
            "bh2": np.zeros(1),
            "wr": np.zeros(self.rff_dim),
            "br": np.zeros(1),
        }
        self._moment1 = {key: np.zeros_like(value) for key, value in self.params.items()}
        self._moment2 = {key: np.zeros_like(value) for key, value in self.params.items()}
        self._step = 0

        # RFF 사상은 학습되지 않는다. 고정된 무작위 사영이므로 seed 만으로 재현된다.
        self.projection = rng.normal(0.0, 1.0, size=(self.latent_dim, self.rff_dim // 2))
        n_rows = int(raw_target.size)
        sample = min(BANDWIDTH_SUBSAMPLE, max(n_rows, 1))
        self._bandwidth_index = (
            rng.choice(n_rows, size=sample, replace=False) if n_rows else np.zeros(0, dtype=int)
        )
        self.last_bandwidth = float("nan")

    @property
    def active(self) -> bool:
        return self.status == "active"

    def _features(self, standardized: np.ndarray) -> Tuple[np.ndarray, np.ndarray, float]:
        """RFF map with a bandwidth frozen at the first call.

        **대역폭을 매 epoch 다시 추정하면 사상이 잠재값의 함수가 되어 기울기가 틀린다.**
        median heuristic 은 미분 경로에서 상수로 취급되므로, 재추정하면 해석 기울기가
        전미분과 어긋난다(유한차분 상대오차 0.13 으로 실측). 첫 호출에서 동결해 사상을
        U 의 고정된 함수로 만든다. 입력이 행 단위 단위노름이므로 쌍거리는 [0, 2] 로 유계이고
        중위수는 안정적이다 — λ 격자 8 점 전체에서 1.368–1.416 에 머물렀다(√2 ≈ 1.414).
        """
        if not np.isfinite(self.last_bandwidth):
            self.last_bandwidth = _median_bandwidth(standardized, self._bandwidth_index)
        bandwidth = self.last_bandwidth
        offset = standardized @ (self.projection / bandwidth)
        scale = float(np.sqrt(2.0 / self.rff_dim))
        mapped = np.concatenate([np.cos(offset), np.sin(offset)], axis=1) * scale
        return mapped, offset, bandwidth

    def loss_and_latent_gradient(
        self, latent: np.ndarray
    ) -> Tuple[float, Dict[str, float], np.ndarray, Dict[str, np.ndarray]]:
        """Adversary loss, per-head detail, d(loss)/d(latent), and head gradients.

        반환되는 잠재 기울기는 **adversary 손실의 기울기**다. 인코더에 부호를 뒤집어 더하는
        일(gradient reversal)은 호출자가 λ 와 함께 수행한다. 이 분리는 λ = 0 이
        adversary 없는 학습과 비트 단위로 같아야 한다는 §7.1 재현 대조를 위한 것이다.
        """
        if not self.active:
            return 0.0, {}, np.zeros_like(latent), {}
        if self.mode == ADVERSARY_MODE_BEST_RESPONSE:
            return self._best_response(latent)

        standardized, norm = standardize_rows_with_norm(latent)
        n_rows = max(standardized.shape[0], 1)

        pre_hidden = standardized @ self.params["Wh1"] + self.params["bh1"]
        hidden = np.tanh(pre_hidden)
        predicted_smooth = hidden @ self.params["wh2"] + self.params["bh2"][0]

        mapped, offset, bandwidth = self._features(standardized)
        predicted_rff = mapped @ self.params["wr"] + self.params["br"][0]

        residual_smooth = predicted_smooth - self.target
        residual_rff = predicted_rff - self.target
        loss_smooth = float(np.mean(residual_smooth ** 2))
        loss_rff = float(np.mean(residual_rff ** 2))

        upstream_smooth = 2.0 * residual_smooth / n_rows
        gradients: Dict[str, np.ndarray] = {
            "wh2": hidden.T @ upstream_smooth,
            "bh2": np.array([float(upstream_smooth.sum())]),
        }
        grad_hidden = upstream_smooth[:, None] * self.params["wh2"][None, :]
        grad_pre_hidden = grad_hidden * (1.0 - hidden ** 2)
        gradients["Wh1"] = standardized.T @ grad_pre_hidden
        gradients["bh1"] = grad_pre_hidden.sum(axis=0)
        grad_standardized = grad_pre_hidden @ self.params["Wh1"].T

        upstream_rff = 2.0 * residual_rff / n_rows
        gradients["wr"] = mapped.T @ upstream_rff
        gradients["br"] = np.array([float(upstream_rff.sum())])
        grad_mapped = upstream_rff[:, None] * self.params["wr"][None, :]
        half = self.rff_dim // 2
        scale = float(np.sqrt(2.0 / self.rff_dim))
        grad_offset = scale * (
            -np.sin(offset) * grad_mapped[:, :half] + np.cos(offset) * grad_mapped[:, half:]
        )
        grad_standardized += grad_offset @ (self.projection / bandwidth).T

        grad_latent = _standardize_rows_backward(grad_standardized, standardized, norm)
        detail = {
            "adversary_loss_smooth_head": round(loss_smooth, 8),
            "adversary_loss_rff_head": round(loss_rff, 8),
            "adversary_rff_bandwidth": round(bandwidth, 8),
        }
        return loss_smooth + loss_rff, detail, grad_latent, gradients

    def _best_response(
        self, latent: np.ndarray
    ) -> Tuple[float, Dict[str, float], np.ndarray, Dict[str, np.ndarray]]:
        """Exact minimiser of each head, then the envelope-theorem latent gradient.

        구현 대상: docs/c2_prereg_v1.md §3.1 최적반응 개정 (2026-08-21)
        사전등록: E4 판정 **전**의 방법 개정이다. 판정 규칙·임계는 바뀌지 않았다.
        해석 한계: 헤드가 최적해에 있으므로 ∂L/∂w = 0 이고, 따라서 L*(U) 의 전미분은
                  w 를 고정한 편미분과 같다(envelope theorem). 이 등식이 성립하기 때문에
                  헤드 파라미터를 학습시키지 않아도 올바른 상승 방향을 얻는다.
                  두 헤드는 **표본 내** 적합이다. 조건 (c) 의 P2–P5 는 표본 외 교차적합이므로
                  둘은 같은 양이 아니며, 표본 내를 이긴 것이 표본 외를 이긴 것을 뜻하지 않는다.
        주장 금지: 최적반응 헤드를 이긴 것을 결측 정보 제거의 증명으로 서술하지 않는다.
        """
        standardized, norm = standardize_rows_with_norm(latent)
        n_rows = max(standardized.shape[0], 1)

        # 헤드 1 — gate 지표와 **같은 함수형**(절편 포함 무벌점 최소제곱)의 최적해.
        design = np.column_stack([standardized, np.ones(standardized.shape[0])])
        weights, *_ = np.linalg.lstsq(design, self.target, rcond=None)
        residual_linear = design @ weights - self.target
        loss_linear = float(np.mean(residual_linear ** 2))
        upstream_linear = 2.0 * residual_linear / n_rows
        grad_standardized = upstream_linear[:, None] * weights[: self.latent_dim][None, :]

        # 헤드 2 — RFF 사상 위 ridge 최적해. 절편은 열 중심화로 처리한다.
        mapped, offset, bandwidth = self._features(standardized)
        centre = mapped.mean(axis=0, keepdims=True)
        centred = mapped - centre
        gram = centred.T @ centred + BEST_RESPONSE_RIDGE * np.eye(centred.shape[1])
        coefficients = np.linalg.solve(gram, centred.T @ self.target)
        residual_rff = centred @ coefficients - self.target
        # **벌점항을 포함해 보고한다.** envelope theorem 은 헤드가 최소화하는 목적함수의
        # 최소해에서만 성립한다. ridge 해는 (잔차² + 벌점·‖w‖²) 를 최소화하므로, MSE 만
        # 보고하면 ∂L/∂w = 0 이 아닌 양을 미분하는 것이 되어 기울기가 틀린다(실측 상대오차 0.11).
        # 벌점항은 U 에 의존하지 않으므로 잠재 기울기 식은 바뀌지 않는다.
        penalty_term = BEST_RESPONSE_RIDGE * float(coefficients @ coefficients) / n_rows
        loss_rff = float(np.mean(residual_rff ** 2)) + penalty_term
        upstream_rff = 2.0 * residual_rff / n_rows
        # 열 중심화 때문에 d(pred_i)/d(mapped_jk) = (δ_ij − 1/n) · coefficients_k 이다.
        grad_mapped = (upstream_rff - upstream_rff.mean())[:, None] * coefficients[None, :]
        half = self.rff_dim // 2
        scale = float(np.sqrt(2.0 / self.rff_dim))
        grad_offset = scale * (
            -np.sin(offset) * grad_mapped[:, :half] + np.cos(offset) * grad_mapped[:, half:]
        )
        grad_standardized = grad_standardized + grad_offset @ (self.projection / bandwidth).T

        grad_latent = _standardize_rows_backward(grad_standardized, standardized, norm)
        detail = {
            "adversary_loss_linear_head": round(loss_linear, 8),
            "adversary_loss_rff_head": round(loss_rff, 8),
            "adversary_rff_bandwidth": round(bandwidth, 8),
        }
        # 최적반응이므로 학습할 헤드 파라미터가 없다. 빈 기울기를 돌려 `apply_update` 를 무동작으로.
        return loss_linear + loss_rff, detail, grad_latent, {}

    def apply_update(self, gradients: Dict[str, np.ndarray]) -> None:
        """Adam step that **minimises** the adversary loss (no reversal here)."""
        if not self.active or not gradients:
            return
        self._step += 1
        for key, gradient in gradients.items():
            self._moment1[key] = 0.9 * self._moment1[key] + 0.1 * gradient
            self._moment2[key] = 0.999 * self._moment2[key] + 0.001 * (gradient ** 2)
            corrected1 = self._moment1[key] / (1.0 - 0.9 ** self._step)
            corrected2 = self._moment2[key] / (1.0 - 0.999 ** self._step)
            self.params[key] -= self.learning_rate * corrected1 / (np.sqrt(corrected2) + 1e-8)

    def provenance(self) -> Dict[str, Any]:
        best_response = self.mode == ADVERSARY_MODE_BEST_RESPONSE
        return {
            "status": self.status,
            "mode": self.mode,
            "seed": self.seed,
            "hidden_dim": self.hidden_dim,
            "rff_dim": self.rff_dim,
            "heads": (
                ["ols_intercept", "rff_ridge"] if best_response
                else ["linear_tanh_hidden", "rff_linear"]
            ),
            "head_solver": (
                {"linear": "numpy.linalg.lstsq", "rff": "numpy.linalg.solve",
                 "rff_ridge_penalty": BEST_RESPONSE_RIDGE}
                if best_response
                else {"optimizer": "adam", "learning_rate": self.learning_rate}
            ),
            "estimation": "in_sample" if best_response else "concurrent_descent",
            "target": "input_target_observed_missingness_rate",
            "target_standardized": True,
            "target_mean": round(self.target_mean, 8),
            "target_scale": round(self.target_scale, 8),
            "features": "row_centred_l2_normalised_latent",
            "induced_mask_used": False,
            "rff_bandwidth_final": (
                None if not np.isfinite(self.last_bandwidth) else round(self.last_bandwidth, 8)
            ),
        }


def assess_convergence(
    history: List[Dict[str, float]],
    *,
    window: int = 50,
) -> Dict[str, Any]:
    """Divergence verdict for the min-max training run.

    구현 대상: docs/c2_prereg_v1.md §3.3 (발산 판정)
    사전등록: 2026-08-21. 판정식과 window = 50 이 E4 착수 전에 §3.3 에서 확정되었다.
              측정 후 변경 금지 — 변경하면 대안 경로 전환의 근거가 무효가 된다.
    해석 한계: `converged` 는 "발산 판정에 걸리지 않았다"는 뜻이며 min-max 균형 도달의
              증명이 아니다. NumPy 전용 full-batch 환경에서 균형 판정은 하지 않는다.
    주장 금지: 수렴을 표현 품질의 근거로 서술하지 않는다.
    """
    recon = [float(entry["reconstruction_loss"]) for entry in history if "reconstruction_loss" in entry]
    adversary = [
        float(entry["adversary_loss"]) for entry in history if entry.get("adversary_loss") is not None
    ]
    if len(recon) < 4:
        return {"status": "not_evaluated", "detail": "too few recorded epochs"}

    span = max(1, min(window, len(recon) // 2))
    early = float(np.mean(recon[:span]))
    late = float(np.mean(recon[-span:]))
    blew_up = bool(late > 2.0 * early) if early > 0 else False

    # "adversary loss 가 단조 증가하며 recon 이 개선되지 않음" (§3.3)
    stalled = False
    if len(adversary) >= 4:
        tail = adversary[-span:]
        monotone = bool(np.all(np.diff(tail) >= 0.0)) if len(tail) >= 2 else False
        stalled = bool(monotone and late >= early)

    diverged = bool(blew_up or stalled)
    return {
        "status": "evaluated",
        "converged": not diverged,
        "diverged": diverged,
        "reason": (
            "reconstruction_loss_exceeded_2x_initial"
            if blew_up
            else "adversary_loss_monotone_increasing_without_reconstruction_gain"
            if stalled
            else None
        ),
        "window": span,
        "early_reconstruction_loss": round(early, 8),
        "late_reconstruction_loss": round(late, 8),
    }
