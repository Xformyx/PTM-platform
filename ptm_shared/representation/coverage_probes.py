"""Pre-registered predictor family for the C2 residual-mask-recoverability test.

구현 대상: docs/c2_prereg_v1.md §4 (조건 c 의 예측기族 P2–P5), §8 (E6)
사전등록: 2026-08-21. 族 목록·판정 규칙·임계(0.25)는 adversary 구현 전에 §4·§14.2 에서
          확정·승인되었다. 이 모듈은 그 목록을 구현할 뿐 族을 늘리거나 줄이지 않는다.
          **결과를 본 뒤 예측기를 추가하는 것을 금지한다** (§14.3).
해석 한계: 이 모듈이 재는 것은 "사전등록된 族 중 어느 것이 임베딩에서 마스크를 회수하는가"다.
          族은 선형(P2)·국소(P3)·매끄러운 비선형(P4)·2차 상호작용(P5)을 덮고
          **축 정렬 분할 앙상블(tree/GBM)을 덮지 않는다.** scikit-learn 미의존 결정(§14.3)의
          대가이며, 통과가 "마스크 회수 불가능"을 뜻하지 않는다.
주장 금지: 낮은 R² 를 "표현이 coverage 로부터 독립이다"로 서술하지 않는다.
          이 값으로 kinase 예측 정확도나 생물학적 타당도를 논하지 않는다.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ptm_shared.representation.metrics import standardize_rows

N_FOLDS = 5
"""외부 교차검증 fold 수.

docs/c2_prereg_v1.md §4.1 에서 2026-08-21 선언. C2 측정 착수 전. 변경 금지.
"""

RIDGE_PENALTY_GRID: Tuple[float, ...] = (1e-4, 1e-3, 1e-2, 1e-1, 1.0, 10.0)
"""P2·P4·P5 의 벌점 격자. training fold 내부 CV 로만 선택한다 (§4.1).

docs/c2_prereg_v1.md §4.1 에서 2026-08-21 선언. 격자 밖 값 사용 금지.
"""

KNN_GRID: Tuple[int, ...] = (5, 10, 20)
"""P3 의 이웃 수 격자. docs/c2_prereg_v1.md §4.1 에서 선언."""

RFF_DIM = 512
"""P4 의 random Fourier feature 차원.

정확한 kernel ridge 는 n ≈ 2,700 에서 O(n³) 이라 5-fold × 내부 CV 에 부적합하다.
RBF 커널을 RFF 로 근사한다. **차원과 seed 를 고정하므로 결정적이다.**
docs/c2_prereg_v1.md §4.1 구현 확인 단계(2026-08-21)에서 선언. adversary 측정 전.
해석 한계: 근사이므로 정확한 RBF kernel ridge 보다 표현력이 낮을 수 있다.
"""

N_PERMUTATIONS = 20
"""귀무분포 순열 횟수. docs/c2_prereg_v1.md §4.1 에서 선언."""

FEATURE_SEED = 0
"""RFF 및 fold 분할 seed. docs/c2_prereg_v1.md §12 에서 선언."""


FAIR_PROBE_COMPARISON_KEY = "comparisons"
"""`run_heldout_timepoint_probe` 결과에서 짝지은 대조가 담기는 키.

fair_probe.py L358. 조건 (b) 판정이 이 키를 읽는다.
"""


def _fold_assignment(n: int, *, n_folds: int = N_FOLDS, seed: int = FEATURE_SEED) -> np.ndarray:
    """Deterministic fold labels for ``n`` rows."""
    rng = np.random.default_rng(int(seed))
    order = rng.permutation(n)
    folds = np.empty(n, dtype=int)
    folds[order] = np.arange(n) % int(n_folds)
    return folds


def _ridge_fit_predict(
    train_x: np.ndarray, train_y: np.ndarray, test_x: np.ndarray, penalty: float
) -> np.ndarray:
    """Closed-form ridge with an unpenalised intercept."""
    mean_x = train_x.mean(axis=0, keepdims=True)
    mean_y = float(train_y.mean())
    centred = train_x - mean_x
    gram = centred.T @ centred + float(penalty) * np.eye(centred.shape[1])
    coefficients = np.linalg.solve(gram, centred.T @ (train_y - mean_y))
    return (test_x - mean_x) @ coefficients + mean_y


def _select_penalty(train_x: np.ndarray, train_y: np.ndarray, *, seed: int) -> float:
    """Pick the ridge penalty by an inner split of the training fold only."""
    inner = _fold_assignment(train_x.shape[0], n_folds=3, seed=seed)
    best_penalty, best_error = RIDGE_PENALTY_GRID[0], np.inf
    for penalty in RIDGE_PENALTY_GRID:
        errors = []
        for fold in range(3):
            hold = inner == fold
            if hold.all() or not hold.any():
                continue
            predicted = _ridge_fit_predict(train_x[~hold], train_y[~hold], train_x[hold], penalty)
            errors.append(float(np.mean((predicted - train_y[hold]) ** 2)))
        error = float(np.mean(errors)) if errors else np.inf
        if error < best_error:
            best_penalty, best_error = penalty, error
    return best_penalty


def _knn_predict(
    train_x: np.ndarray, train_y: np.ndarray, test_x: np.ndarray, k: int
) -> np.ndarray:
    """Distance-weighted k-nearest-neighbour regression."""
    predictions = np.empty(test_x.shape[0], dtype=float)
    block = 256
    for start in range(0, test_x.shape[0], block):
        chunk = test_x[start : start + block]
        distances = np.sqrt(
            np.maximum(
                (chunk ** 2).sum(axis=1, keepdims=True)
                - 2.0 * chunk @ train_x.T
                + (train_x ** 2).sum(axis=1)[None, :],
                0.0,
            )
        )
        effective_k = min(int(k), train_x.shape[0])
        nearest = np.argpartition(distances, effective_k - 1, axis=1)[:, :effective_k]
        rows = np.arange(chunk.shape[0])[:, None]
        weights = 1.0 / np.maximum(distances[rows, nearest], 1e-9)
        weights /= weights.sum(axis=1, keepdims=True)
        predictions[start : start + block] = (weights * train_y[nearest]).sum(axis=1)
    return predictions


def _select_k(train_x: np.ndarray, train_y: np.ndarray, *, seed: int) -> int:
    inner = _fold_assignment(train_x.shape[0], n_folds=3, seed=seed)
    best_k, best_error = KNN_GRID[0], np.inf
    for k in KNN_GRID:
        errors = []
        for fold in range(3):
            hold = inner == fold
            if hold.all() or not hold.any():
                continue
            predicted = _knn_predict(train_x[~hold], train_y[~hold], train_x[hold], k)
            errors.append(float(np.mean((predicted - train_y[hold]) ** 2)))
        error = float(np.mean(errors)) if errors else np.inf
        if error < best_error:
            best_k, best_error = k, error
    return best_k


def _random_fourier_features(features: np.ndarray, *, bandwidth: float, seed: int) -> np.ndarray:
    """RBF feature map with a fixed projection, so the map is reproducible."""
    rng = np.random.default_rng(int(seed))
    projection = rng.normal(0.0, 1.0 / max(bandwidth, 1e-9), size=(features.shape[1], RFF_DIM // 2))
    offset = features @ projection
    return np.concatenate([np.cos(offset), np.sin(offset)], axis=1) * np.sqrt(2.0 / RFF_DIM)


def _median_bandwidth(features: np.ndarray, *, seed: int, sample: int = 512) -> float:
    """Median pairwise distance on a deterministic subsample."""
    rng = np.random.default_rng(int(seed))
    n = features.shape[0]
    index = rng.choice(n, size=min(sample, n), replace=False)
    subset = features[index]
    distances = np.sqrt(
        np.maximum(
            (subset ** 2).sum(axis=1, keepdims=True)
            - 2.0 * subset @ subset.T
            + (subset ** 2).sum(axis=1)[None, :],
            0.0,
        )
    )
    upper = distances[np.triu_indices_from(distances, k=1)]
    median = float(np.median(upper)) if upper.size else 1.0
    return median if median > 1e-9 else 1.0


def _quadratic_expansion(features: np.ndarray) -> np.ndarray:
    """Append squared terms and pairwise interactions."""
    rows, columns = features.shape
    pieces = [features]
    for i in range(columns):
        pieces.append(features[:, i : i + 1] * features[:, i:])
    return np.concatenate(pieces, axis=1)


def _out_of_sample_r2(predicted: np.ndarray, target: np.ndarray) -> Optional[float]:
    denominator = float(np.sum((target - target.mean()) ** 2))
    if denominator <= 0:
        return None
    return round(float(1.0 - np.sum((target - predicted) ** 2) / denominator), 6)


def _cross_fit(
    features: np.ndarray, target: np.ndarray, predictor: str, *, seed: int
) -> np.ndarray:
    """Out-of-fold predictions for one predictor family."""
    folds = _fold_assignment(features.shape[0], seed=seed)
    predicted = np.empty(features.shape[0], dtype=float)
    for fold in range(N_FOLDS):
        hold = folds == fold
        train_x, train_y, test_x = features[~hold], target[~hold], features[hold]
        if predictor == "P2_ridge":
            penalty = _select_penalty(train_x, train_y, seed=seed)
            predicted[hold] = _ridge_fit_predict(train_x, train_y, test_x, penalty)
        elif predictor == "P3_knn":
            k = _select_k(train_x, train_y, seed=seed)
            predicted[hold] = _knn_predict(train_x, train_y, test_x, k)
        elif predictor == "P4_rff_kernel_ridge":
            bandwidth = _median_bandwidth(train_x, seed=seed)
            mapped_train = _random_fourier_features(train_x, bandwidth=bandwidth, seed=seed)
            mapped_test = _random_fourier_features(test_x, bandwidth=bandwidth, seed=seed)
            penalty = _select_penalty(mapped_train, train_y, seed=seed)
            predicted[hold] = _ridge_fit_predict(mapped_train, train_y, mapped_test, penalty)
        elif predictor == "P5_quadratic_ridge":
            expanded_train = _quadratic_expansion(train_x)
            expanded_test = _quadratic_expansion(test_x)
            penalty = _select_penalty(expanded_train, train_y, seed=seed)
            predicted[hold] = _ridge_fit_predict(expanded_train, train_y, expanded_test, penalty)
        else:
            raise ValueError(f"unknown predictor {predictor!r}")
    return predicted


PREDICTOR_FAMILY: Tuple[str, ...] = (
    "P2_ridge",
    "P3_knn",
    "P4_rff_kernel_ridge",
    "P5_quadratic_ridge",
)
"""조건 (c) 판정에 쓰는 族. docs/c2_prereg_v1.md §4.1. 추가·삭제 금지."""


def residual_mask_recoverability(
    embedding: np.ndarray,
    induced_rate: np.ndarray,
    *,
    seed: int = FEATURE_SEED,
    n_permutations: int = N_PERMUTATIONS,
) -> Dict[str, Any]:
    """Out-of-sample R² of recovering the induced mask rate, per predictor family.

    구현 대상: docs/c2_prereg_v1.md §4.2 (조건 c 판정), §8 (E6)
    사전등록: 2026-08-21. 임계 0.25 는 §14.2 에서 승인된 값이며 여기서 도입하지 않는다.
    해석 한계: 특징은 gate 와 동일하게 행 단위 표준화된 임베딩이다. 따라서 site 별 평균과
              크기는 제거된 상태이며, 회수 가능성은 임베딩 **형태**에 대한 것이다.
    주장 금지: 낮은 값을 독립성의 증명으로 서술하지 않는다.
    """
    features = standardize_rows(np.asarray(embedding, dtype=float))
    target = np.asarray(induced_rate, dtype=float)
    if features.shape[0] != target.size or target.size < N_FOLDS * 2:
        return {"status": "not_evaluated", "detail": "insufficient rows for cross-fitting"}
    if float(np.var(target)) < 1e-12:
        return {"status": "not_evaluated", "detail": "induced rate has no variance"}

    rng = np.random.default_rng(int(seed))
    per_predictor: Dict[str, Any] = {}
    for predictor in PREDICTOR_FAMILY:
        observed = _out_of_sample_r2(_cross_fit(features, target, predictor, seed=seed), target)
        nulls: List[float] = []
        for _ in range(int(n_permutations)):
            shuffled = target[rng.permutation(target.size)]
            value = _out_of_sample_r2(
                _cross_fit(features, shuffled, predictor, seed=seed), shuffled
            )
            if value is not None:
                nulls.append(value)
        per_predictor[predictor] = {
            "out_of_sample_r2": observed,
            "permutation_null_mean": round(float(np.mean(nulls)), 6) if nulls else None,
            "permutation_null_max": round(float(np.max(nulls)), 6) if nulls else None,
            "excess_over_null": (
                None
                if observed is None or not nulls
                else round(float(observed - float(np.mean(nulls))), 6)
            ),
        }

    finite = [
        value["out_of_sample_r2"]
        for value in per_predictor.values()
        if value["out_of_sample_r2"] is not None
    ]
    return {
        "status": "evaluated",
        "n_sites": int(target.size),
        "n_folds": N_FOLDS,
        "n_permutations": int(n_permutations),
        "seed": int(seed),
        "per_predictor": per_predictor,
        "family_max_out_of_sample_r2": round(float(max(finite)), 6) if finite else None,
    }
