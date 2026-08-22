"""비교가능성 제약 대조 손실 (C3, M1 마스킹형).

구현 대상: docs/c3_prereg_v1.md §6.1 (M1 = 마스킹형), §6.2 (M1-loss, 3-기준선),
          §6.3 (InfoNCE 함수형), §6.3.1 (초모수), §6.3.2 (자명성 검사)
사전등록: 함수형과 초모수는 2026-08-22 §6.3 에서 **구현 착수 전** 선언되었다. λ·T·k 를
          이 모듈에서 새로 정하지 않는다 — 기본값은 §6.3.1 을 인용하며, 판정은 기준선 1과
          처리가 **같은 λ** 를 쓰는 짝지은 대조다.
해석 한계: 이 항은 `O_ij = 0` 쌍에 대해 **아무 방향도 주지 않는다.** 멀리 밀지 않는다.
          `O_ij = 0` 은 유사성 판단 근거의 부재이며 비유사성의 증거가 아니므로(§1.1),
          비교 불가 쌍을 능동적으로 밀어내는 벌점형(M2)은 primary 가 아니다.
          양성은 **관측 데이터의 거리**로 정한다. 임베딩으로 정하면 손실이 자기 자신을
          강화하는 되먹임이 되어 아무것도 학습하지 않는다.
주장 금지: "제약이 kinase 예측을 개선한다".
          "비교 불가 쌍은 서로 다르다".
          "이 항이 표현 품질을 높인다" — 낮추는 것은 근거 없는 병합이며 품질의 한 축이다.

결정성: float64. 쌍 열거는 전체 행렬이며 대각은 후보에서 제외한다. `d_obs` 는 공유 관측
        시점에서만 계산하고 공유가 없으면 `+inf` 로 두어 양성이 될 수 없게 한다.
        양성 선택은 `np.argpartition` 후 안정 정렬로 동순위를 인덱스 순으로 깬다.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import numpy as np

CONTRACT_VERSION = "ptm_comparability_constraint.v1"

CONSTRAINT_TEMPERATURE = 0.5
"""InfoNCE 온도 T. docs/c3_prereg_v1.md §6.3.1 에서 2026-08-22 선언. 구현 착수 전.
관례값이며 C3 이 탐색하지 않는다. 변경하면 기준선 1과 처리를 함께 재실행해야 한다.
"""

CONSTRAINT_NEIGHBORS = 10
"""양성 수 k. `c2_prereg_v1.md` §1.1 의 `neighbors` = 10 을 인용한다(§6.3.1).
C3 이 새 값을 도입하지 않는다 — 도입하면 회수율 지표와 비교할 수 없다.
"""

CONSTRAINT_LAMBDA_PRIMARY = 1.0
"""대조 항 가중 λ 의 primary 값. §6.3.1 에서 2026-08-22 선언.

**λ 는 판정 대상이 아니다.** 기준선 1(무제약 대조)과 처리(제약 대조)가 같은 λ 를 쓰므로
C3 이 검정하는 것은 "그 항에서 비교 불가 쌍을 뺀 효과"다. 민감도 {0.3, 3.0} 은 결론이 λ 에
뒤집히는지만 본다.
"""

CONSTRAINT_LAMBDA_SENSITIVITY = (0.3, 3.0)

MODE_UNCONSTRAINED = "unconstrained"
"""기준선 1 — 대조 항은 있으나 `O_ij = 0` 쌍도 포함한다."""

MODE_CONSTRAINED = "constrained"
"""처리 — 양성과 후보에서 `O_ij = 0` 쌍을 뺀다."""

CONSTRAINT_MODES = (MODE_UNCONSTRAINED, MODE_CONSTRAINED)

EMPTY_POSITIVE_ROW_MAX = 0.20
"""자명성 검사 S2 임계. docs/c3_prereg_v1.md §6.3.2 에서 2026-08-22 선언. E9 착수 전.

제약으로 양성이 빈 행의 비율이 이 값을 넘으면 처리는 "제약"이 아니라 **데이터 삭제**이며
E9 를 판정에 쓰지 않는다. 근거는 §12.3 — `rep≥2`·`T_min=4` 에서 비교 불가 쌍이 전역 20.2%
이므로 양성 후보가 그보다 크게 더 많이 사라지면 손실이 겨냥하는 구조가 남지 않는다.
측정 후 변경 금지 — 변경하면 "제약이 작동했다"를 사후에 정의하게 된다.
"""


def observed_distance_matrix(values: np.ndarray, observed: np.ndarray) -> np.ndarray:
    """공유 관측 시점에서의 RMS 궤적 거리. 공유가 없으면 `+inf`.

    docs/c3_prereg_v1.md §6.3. **행 표준화를 적용하지 않는다** — 표준화 통계량이 관측 마스크에
    의존하므로 표준화하면 거리 자체가 coverage 의 함수가 되고, C2 가 겨냥한 문제를 대조 항에
    다시 들여온다.
    """
    mask = np.asarray(observed, dtype=bool)
    filled = np.where(mask, np.nan_to_num(np.asarray(values, dtype=float), nan=0.0), 0.0)
    mask_float = mask.astype(float)
    squared = filled**2
    shared = mask_float @ mask_float.T
    # Σ_t m_it m_jt (x_it − x_jt)² 를 세 곱으로 전개한다. 쌍 루프를 돌지 않기 위한 것이다.
    total = squared @ mask_float.T + mask_float @ squared.T - 2.0 * (filled @ filled.T)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.divide(total, shared, out=np.full_like(total, np.inf), where=shared > 0)
    distance = np.sqrt(np.clip(mean, 0.0, None))
    distance[shared <= 0] = np.inf
    np.fill_diagonal(distance, np.inf)
    return distance


def positive_mask(
    distance: np.ndarray, candidate: np.ndarray, n_positives: int
) -> np.ndarray:
    """후보 중 관측 거리가 가장 가까운 `n_positives` 개를 양성으로 표시한다.

    동순위는 인덱스 순으로 깬다(안정 정렬). `+inf` 거리는 선택되지 않는다 — 공유 관측이 없는
    쌍을 양성으로 두면 근거 없는 유사성을 손실에 직접 새겨 넣는 것이 된다.
    """
    n_rows = distance.shape[0]
    keep = np.asarray(candidate, dtype=bool)
    scores = np.where(keep, distance, np.inf)
    positives = np.zeros((n_rows, n_rows), dtype=bool)
    k = int(n_positives)
    if k <= 0:
        return positives
    for row in range(n_rows):
        finite = np.flatnonzero(np.isfinite(scores[row]))
        if finite.size == 0:
            continue
        if finite.size <= k:
            positives[row, finite] = True
            continue
        values = scores[row, finite]
        cut = np.argpartition(values, k - 1)[:k]
        chosen = finite[cut[np.argsort(values[cut], kind="stable")]]
        positives[row, chosen] = True
    return positives


class ComparabilityContrastive:
    """`O` 를 존중하는 InfoNCE 항. 인코더의 잠재 표현에 대한 손실과 기울기를 준다.

    docs/c3_prereg_v1.md §6.2 의 3-기준선 중 두 개를 이 클래스가 만든다 —
    `mode = "unconstrained"` 가 기준선 1, `mode = "constrained"` 가 처리다. 기준선 0(대조 항
    없음)은 이 클래스를 쓰지 않는 실행이다.

    **제약은 항을 더하지 않고 뺀다.** `constrained` 에서 `O_ij = 0` 인 j 는 양성에서도
    후보에서도 제거되므로, 손실은 그 쌍에 대해 아무 방향도 주지 않는다.
    """

    def __init__(
        self,
        values: np.ndarray,
        observed: np.ndarray,
        *,
        comparability: Optional[np.ndarray] = None,
        mode: str = MODE_CONSTRAINED,
        n_positives: int = CONSTRAINT_NEIGHBORS,
        temperature: float = CONSTRAINT_TEMPERATURE,
    ) -> None:
        if mode not in CONSTRAINT_MODES:
            raise ValueError(f"mode must be one of {CONSTRAINT_MODES}, got {mode!r}")
        if float(temperature) <= 0.0:
            raise ValueError("temperature must be positive")
        self.mode = str(mode)
        self.temperature = float(temperature)
        self.n_positives = int(n_positives)

        n_rows = np.asarray(observed).shape[0]
        self.n_rows = int(n_rows)
        candidate = ~np.eye(n_rows, dtype=bool)
        self._constrained_pairs_removed = 0
        if self.mode == MODE_CONSTRAINED:
            if comparability is None:
                raise ValueError("constrained mode requires a comparability matrix")
            comparable = np.asarray(comparability, dtype=bool)
            if comparable.shape != (n_rows, n_rows):
                raise ValueError("comparability must be square and match the input rows")
            before = int(candidate.sum())
            candidate = candidate & comparable
            self._constrained_pairs_removed = before - int(candidate.sum())

        self.candidate = candidate
        distance = observed_distance_matrix(values, observed)
        self.positives = positive_mask(distance, candidate, self.n_positives)
        # 후보가 양성뿐인 행은 −log(A/B) = 0 이고 기울기도 0 이다. 손실에 기여하지 않으므로
        # 유효 행에서 제외한다 — 포함하면 분모만 키워 손실을 인공적으로 낮춘다.
        positive_counts = self.positives.sum(axis=1)
        candidate_counts = candidate.sum(axis=1)
        self.valid_rows = (positive_counts > 0) & (candidate_counts > positive_counts)
        self._empty_positive_rows = int((positive_counts == 0).sum())
        self._positive_counts = positive_counts
        self._candidate_counts = candidate_counts

    # -- 자명성 검사 -------------------------------------------------------

    @property
    def empty_positive_fraction(self) -> float:
        """양성이 하나도 없는 행의 비율. docs/c3_prereg_v1.md §6.3.2 S2."""
        return float(self._empty_positive_rows / self.n_rows) if self.n_rows else 0.0

    def triviality_check(self) -> Dict[str, Any]:
        """S2 — 제약이 손실을 비워버렸는가. 판정은 호출자가 임계와 비교해서 한다."""
        fraction = self.empty_positive_fraction
        return {
            "empty_positive_fraction": round(fraction, 6),
            "empty_positive_row_max": EMPTY_POSITIVE_ROW_MAX,
            "loss_survives": bool(fraction <= EMPTY_POSITIVE_ROW_MAX),
            "n_valid_rows": int(self.valid_rows.sum()),
            "mean_positives_per_row": round(float(self._positive_counts.mean()), 4),
            "mean_candidates_per_row": round(float(self._candidate_counts.mean()), 4),
        }

    # -- 손실 -------------------------------------------------------------

    def loss_and_latent_gradient(
        self, latent: np.ndarray
    ) -> Tuple[float, Dict[str, float], np.ndarray]:
        """InfoNCE 손실과 `∂L/∂z`. docs/c3_prereg_v1.md §6.3 의 식 그대로.

        행 정규화 `u = z / ‖z‖` 를 통과한 기울기를 돌려주므로, 호출자는 `grad_latent` 에
        `λ` 를 곱해 **더한다**(인코더가 이 항을 최소화한다). adversary 와 부호가 반대인 것은
        adversary 만 기울기 반전을 쓰기 때문이다.
        """
        matrix = np.asarray(latent, dtype=float)
        gradient = np.zeros_like(matrix)
        n_valid = int(self.valid_rows.sum())
        if n_valid == 0 or matrix.size == 0:
            return 0.0, {"n_valid_rows": 0}, gradient

        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        safe = np.where(norms > 0, norms, 1.0)
        unit = matrix / safe
        similarity = (unit @ unit.T) / self.temperature

        candidate = self.candidate
        positives = self.positives
        # 행별 최대를 빼서 exp 를 안정화한다. 상수는 −log A + log B 에서 소거된다.
        shifted = np.where(candidate, similarity, -np.inf)
        row_max = np.max(shifted, axis=1, keepdims=True)
        row_max = np.where(np.isfinite(row_max), row_max, 0.0)
        exponentials = np.where(candidate, np.exp(similarity - row_max), 0.0)

        positive_sum = (exponentials * positives).sum(axis=1)
        candidate_sum = exponentials.sum(axis=1)
        valid = self.valid_rows & (positive_sum > 0) & (candidate_sum > 0)
        n_valid = int(valid.sum())
        if n_valid == 0:
            return 0.0, {"n_valid_rows": 0}, gradient

        per_row = np.zeros(self.n_rows, dtype=float)
        per_row[valid] = -np.log(positive_sum[valid]) + np.log(candidate_sum[valid])
        loss = float(per_row[valid].sum() / n_valid)

        safe_positive = np.where(valid, positive_sum, 1.0).reshape(-1, 1)
        safe_candidate = np.where(valid, candidate_sum, 1.0).reshape(-1, 1)
        attribution = np.where(
            valid.reshape(-1, 1),
            exponentials / safe_candidate - (exponentials * positives) / safe_positive,
            0.0,
        )
        attribution /= float(n_valid)

        # s_ij 는 u_i 와 u_j 에 모두 의존하므로 대칭화한다.
        unit_gradient = ((attribution + attribution.T) @ unit) / self.temperature
        # 행 정규화의 야코비안: (I − u uᵀ) / ‖z‖.
        projected = unit_gradient - unit * np.sum(unit * unit_gradient, axis=1, keepdims=True)
        gradient = projected / safe

        detail = {
            "contrastive_loss": round(loss, 8),
            "n_valid_rows": n_valid,
            "mean_positive_similarity": round(
                float(
                    (similarity[positives].mean() * self.temperature) if positives.any() else 0.0
                ),
                6,
            ),
        }
        return loss, detail, gradient

    # -- 산출 레코드 -------------------------------------------------------

    def provenance(self) -> Dict[str, Any]:
        """Methods 절과 산출 레코드용 기계 판독 요약."""
        return {
            "contract_version": CONTRACT_VERSION,
            "mode": self.mode,
            "n_positives": self.n_positives,
            "temperature": self.temperature,
            "n_rows": self.n_rows,
            "n_candidate_pairs_removed_by_constraint": int(self._constrained_pairs_removed),
            "positive_source": "observed_trajectory_distance",
            "declaration": "docs/c3_prereg_v1.md §6.3",
            **self.triviality_check(),
        }


def describe() -> Dict[str, Any]:
    """동결된 선언값 요약. 문서와 코드가 어긋나면 회귀 테스트가 잡는다."""
    return {
        "contract_version": CONTRACT_VERSION,
        "functional_form": "infonce_cosine",
        "temperature": CONSTRAINT_TEMPERATURE,
        "n_positives": CONSTRAINT_NEIGHBORS,
        "lambda_primary": CONSTRAINT_LAMBDA_PRIMARY,
        "lambda_sensitivity": list(CONSTRAINT_LAMBDA_SENSITIVITY),
        "modes": list(CONSTRAINT_MODES),
        "empty_positive_row_max": EMPTY_POSITIVE_ROW_MAX,
        "mechanism": "M1_masking",
        "declaration": "docs/c3_prereg_v1.md §6.3",
    }
