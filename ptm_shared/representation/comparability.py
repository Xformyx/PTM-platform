"""부분 비교가능성 관계 `O` 와 그 위에서의 pair 수준 지표 (C3).

구현 대상: docs/c3_prereg_v1.md §1.2 계산 경로, §2.1 `O` 정의, §4.1 false-merge,
          §5.2 자명한 성공 차단 동반 지표
사전등록: `O` 정의와 지표 정의는 2026-08-22 §12 실측 착수 전 확정. 판정 임계는 §13 에서
          **무제약 기저 대비 상대값**으로 선언되며 이 모듈은 임계를 담지 않는다 —
          임계를 여기 두면 문서를 고치지 않고 코드만 바꿀 수 있다.
해석 한계: `O_ij = 0` 은 **유사성 판단 근거의 부재**이며 비유사성의 증거가 아니다.
          따라서 이 모듈의 지표는 "표현이 근거 없는 유사성을 얼마나 주장하는가"를 재며,
          비교 불가 쌍이 실제로 다른지에 대해 아무 말도 하지 않는다.
          단일 코호트(HIRc-B, T = 6)에서만 실측되었다.
주장 금지: "FM 이 낮은 arm 이 우수하다" — FM 은 군집을 잘게 쪼개 낮출 수 있으므로 §5.2
          동반 지표 없이는 비교 근거가 되지 않는다.
          "비교 불가 쌍은 서로 다르다".
          "제약이 kinase 예측을 개선한다".

결정성: 정수 비교만 사용하며 부동소수 tolerance 를 두지 않는다. 쌍 열거는 상삼각(i < j)이고
        자기 쌍은 제외한다. `label 0`(미배정)은 서로 같은 군집이 아니다 (§3.3).
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import numpy as np

from .metrics import standardize_rows

CONTRACT_VERSION = "ptm_comparability.v1"


def comparability_matrix(observed: np.ndarray, t_min: int) -> np.ndarray:
    """`O_ij = 1 ⟺ 공유 관측 시점 수 ≥ t_min`. docs/c3_prereg_v1.md §2.1.

    `O` 는 대칭·반사적이나 **추이적이 아니다.** i–j 와 j–k 가 비교 가능해도 i–k 는 비교
    불가일 수 있다. 이 비추이성 때문에 제약을 동치류 분할로 구현할 수 없다 (§6.1 M3 주석).
    """
    if int(t_min) < 1:
        raise ValueError("t_min must be at least 1")
    mask = np.asarray(observed, dtype=bool).astype(np.int32)
    return (mask @ mask.T) >= int(t_min)


def upper_triangle(matrix: np.ndarray) -> np.ndarray:
    """상삼각 원소를 1차원으로. 자기 쌍(k=0)은 포함하지 않는다."""
    return matrix[np.triu_indices(matrix.shape[0], k=1)]


def same_cluster_matrix(labels: np.ndarray) -> np.ndarray:
    """같은 군집 여부. `label 0`(미배정) 쌍은 병합이 아니다 (docs/c3_prereg_v1.md §3.3).

    이 규약을 어기면 미배정 점을 늘리는 것만으로 병합 쌍이 폭증해 보인다.
    """
    array = np.asarray(labels)
    assigned = array > 0
    same = array[:, None] == array[None, :]
    return same & assigned[:, None] & assigned[None, :]


def false_merge(labels: np.ndarray, comparable: np.ndarray) -> Dict[str, Any]:
    """FM_precision(primary) 과 FM_exposure(secondary). docs/c3_prereg_v1.md §4.1.

    primary 가 FM_precision 인 이유는 분모가 **표현이 실제로 주장한 것**이기 때문이다.
    미정의 값은 `None` 으로 남긴다 — 0.0 으로 채우면 "개선됨"으로 오독된다 (§4.2).
    """
    merged = upper_triangle(same_cluster_matrix(labels))
    non_comparable = upper_triangle(~np.asarray(comparable, dtype=bool))
    n_merged = int(merged.sum())
    n_non_comparable = int(non_comparable.sum())
    n_false = int((merged & non_comparable).sum())
    return {
        "n_merged_pairs": n_merged,
        "n_non_comparable_pairs": n_non_comparable,
        "n_false_merges": n_false,
        "fm_precision": (n_false / n_merged) if n_merged else None,
        "fm_exposure": (n_false / n_non_comparable) if n_non_comparable else None,
    }


def removal_precision(
    baseline: Dict[str, Any], treated: Dict[str, Any]
) -> Dict[str, Any]:
    """제거된 병합 중 false merge 의 비율 — G2 (docs/c3_prereg_v1.md §5.2).

    자명한 성공(군집을 잘게 쪼개 FM 을 낮추는 것)을 직접 막는 양이다. 무작위 제거의
    기대값은 기저 FM_precision 이므로, 이 값이 그보다 크게 높아야 제거가 표적화된 것이다.

    병합 쌍이 줄지 않았는데 FM 이 개선되면 구조를 축소하지 않고 개선한 것이므로
    `status = "no_shrinkage"` 로 통과 처리한다 (§5.2 의 미정의 규약).
    """
    delta_merged = int(baseline["n_merged_pairs"]) - int(treated["n_merged_pairs"])
    delta_false = int(baseline["n_false_merges"]) - int(treated["n_false_merges"])
    if delta_merged <= 0:
        return {
            "status": "no_shrinkage",
            "delta_merged_pairs": delta_merged,
            "delta_false_merges": delta_false,
            "removal_precision": None,
            "random_removal_expectation": baseline.get("fm_precision"),
        }
    return {
        "status": "evaluated",
        "delta_merged_pairs": delta_merged,
        "delta_false_merges": delta_false,
        "removal_precision": delta_false / delta_merged,
        "random_removal_expectation": baseline.get("fm_precision"),
    }


def pair_restricted_ari(
    labels_a: np.ndarray,
    labels_b: np.ndarray,
    pair_mask: Optional[np.ndarray] = None,
) -> Optional[float]:
    """쌍 부분집합 위의 ARI. 계수 형태이므로 임의의 pair mask 에 적용된다.

    docs/c3_prereg_v1.md §5.2 G1 은 **비교 가능 쌍만** 대상으로 한다. 제약이 비교 불가 쌍의
    처리를 바꾸는 것은 의도된 변화이므로, 전체 쌍에서 재면 의도된 변화가 구조 파괴로 잡힌다.

    해석 한계: 이 코호트의 arm D 에서 **seed 만 바꾼 두 적합 사이의 값이 0.024–0.037** 이다
    (§12.4 실측). 즉 절대 임계로 쓸 수 없다. 임계는 그 잡음 하한 대비 상대값이어야 한다.
    """
    same_a = upper_triangle(same_cluster_matrix(labels_a))
    same_b = upper_triangle(same_cluster_matrix(labels_b))
    if pair_mask is not None:
        keep = upper_triangle(np.asarray(pair_mask, dtype=bool))
        same_a = same_a[keep]
        same_b = same_b[keep]
    a = float((same_a & same_b).sum())
    b = float((same_a & ~same_b).sum())
    c = float((~same_a & same_b).sum())
    d = float((~same_a & ~same_b).sum())
    denominator = (a + b) * (b + d) + (a + c) * (c + d)
    if denominator <= 0:
        return None
    return float(2.0 * (a * d - b * c) / denominator)


def cosine_distances(embedding: np.ndarray, *, standardize: bool = True) -> np.ndarray:
    """`cluster_representation` 과 같은 전처리의 쌍거리. 군집 지표와 짝을 맞추기 위한 것."""
    matrix = standardize_rows(embedding) if standardize else np.asarray(embedding, dtype=float)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    unit = matrix / norms
    return 1.0 - unit @ unit.T


def distance_rank_agreement(
    left: np.ndarray,
    right: np.ndarray,
    pair_mask: Optional[np.ndarray] = None,
    *,
    standardize: bool = True,
) -> Optional[float]:
    """비교 가능 쌍 쌍거리 순위의 Spearman 일치도.

    docs/c3_prereg_v1.md §5.2 에서 G1 의 대안으로 검토되었고 **기각되었다** — arm D 에서
    seed 만 바꾼 두 적합의 값이 0.0025–0.0056 으로 사실상 0 이다(§12.4). 행 표준화 인공물이
    아님을 `standardize=False` 대조로 확인했다(0.0023–0.0054).
    진단 지표로만 남긴다.
    """
    if pair_mask is None:
        keep = None
    else:
        keep = upper_triangle(np.asarray(pair_mask, dtype=bool))
        if keep.sum() < 3:
            return None
    ranked = []
    for embedding in (left, right):
        vector = upper_triangle(cosine_distances(embedding, standardize=standardize))
        if keep is not None:
            vector = vector[keep]
        order = np.argsort(vector, kind="stable")
        ranks = np.empty(vector.size, dtype=float)
        ranks[order] = np.arange(vector.size, dtype=float)
        ranked.append(ranks)
    if ranked[0].size < 3 or ranked[0].std() == 0 or ranked[1].std() == 0:
        return None
    return float(np.corrcoef(ranked[0], ranked[1])[0, 1])


def subspace_alignment(left: np.ndarray, right: np.ndarray) -> Optional[float]:
    """두 임베딩 열공간의 정렬도 — 정준상관 제곱의 평균.

    쌍거리 순위와 함께 보면 "부분공간은 같은데 미세 기하만 흔들리는가"와 "부분공간 자체가
    seed 마다 다른가"를 구별한다. 공정 프로브는 열공간에만 의존하므로(회전 불변) 전자라면
    프로브 재현성과 기하 불안정이 동시에 성립할 수 있다.

    실측(§12.4): arm D, seed 쌍 3개에서 0.178–0.195. 무작위 부분공간의 기대값
    (16/2744 ≈ 0.006)보다 크지만 1.0 과는 멀다.
    """
    left_array = np.asarray(left, dtype=float)
    right_array = np.asarray(right, dtype=float)
    if left_array.size == 0 or right_array.size == 0:
        return None
    q_left, _ = np.linalg.qr(left_array - left_array.mean(axis=0, keepdims=True))
    q_right, _ = np.linalg.qr(right_array - right_array.mean(axis=0, keepdims=True))
    singular = np.linalg.svd(q_left.T @ q_right, compute_uv=False)
    if singular.size == 0:
        return None
    return float(np.mean(np.clip(singular, 0.0, 1.0) ** 2))


def kish_n_eff(degrees: np.ndarray) -> Dict[str, Any]:
    """feature 를 cluster 로 보는 Kish 실효 표본 수. docs/c3_prereg_v1.md §7.3.

    비교 불가 그래프의 feature 별 degree `m_i` 에 대해 `n_eff = (Σ m_i)² / Σ m_i²`.
    쌍은 독립이 아니다 — 한 feature 가 수천 쌍의 종단이므로 쌍 단위 부트스트랩은 구간을
    과소추정한다.

    해석 한계: `integrated_research_design_v2.md` §7.3 의 432 는 Core A/B 트랙 모집단의
    값이며 이 모집단의 값이 아니다. 이 모집단(form, eligible, rep≥2, T_min=4)에서는 995.2 다.
    """
    array = np.asarray(degrees, dtype=float)
    positive = array[array > 0]
    if positive.size == 0:
        return {"n_features_with_edges": 0, "total_degree": 0, "n_eff": None}
    total = float(positive.sum())
    return {
        "n_features_with_edges": int(positive.size),
        "total_degree": int(total),
        "n_eff": float(total * total / float((positive**2).sum())),
        "max_degree": int(positive.max()),
        "mean_degree": float(positive.mean()),
    }


def describe() -> Dict[str, Any]:
    """Methods 절과 산출 레코드용 기계 판독 요약."""
    return {
        "contract_version": CONTRACT_VERSION,
        "primary_metric": "fm_precision",
        "secondary_metric": "fm_exposure",
        "triviality_guards": ["pair_restricted_ari", "removal_precision", "fair_probe_delta_r2"],
        "rejected_guard": "distance_rank_agreement",
        "declaration": "docs/c3_prereg_v1.md",
        "unassigned_label_convention": "label 0 pairs are not merges",
    }
