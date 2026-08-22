"""Gene-block inference for C1 — E1b 기하 중복도와 (탐색적) E3 예측 타당도.

구현 대상: docs/c1_prereg_v1.md §6.2–6.5 (E1b), §7.2–7.4 (E3), §7.3.1 (집계·seed)
사전등록: E1b 규칙은 2026-08-20 동결(외부 검토 반영), 교차적합은 2026-08-21 동결,
          집계 규칙과 bootstrap seed 는 2026-08-22 확정(E3 산정 전).
          §3.5.1 에서 **E3 는 primary 에서 강등**되었으므로 이 모듈이 내는 p-value 는
          확증 판정이 아니다.
해석 한계: E1b 는 p-value 를 산출하지 않는다(§6.5). 기술 통계와 CI 만 낸다.
          E3 는 탐색적이며 "통과/실패" 라벨을 붙이지 않는다(§3.5.2).
          블록 = 유전자이며 gene 별칭은 해결되지 않는다 — 별칭이 있으면 블록이 쪼개진다.
주장 금지: E1b 로 "τ 가 기존 기하 지표와 다르다"를 증명했다고 쓰지 않는다. 단순 비교자를
          이기는 것이 목적이 아니라 중복도를 기술하는 것이 목적이다(§6.3).
          E3 결과로 C1 성공을 선언하지 않는다(§6.6 OR 경로 금지, §3.5.2).
          미평가와 실패를 구별한다(§3.5.1).
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

N_FOLDS = 5
FOLD_SALT = "c1-prereg-v1"
"""fold 배정 = `sha256(정규화 유전자 기호 + "c1-prereg-v1") mod 5`.

docs/c1_prereg_v1.md §7.2 `C1_GENE_BLOCK_CROSSFIT_V1` 에서 2026-08-21 선언. τ 산정 전.
sha256 을 쓰는 이유는 프로세스 재시작에 불변이어야 하기 때문이다 — 파이썬 `hash()` 는
`PYTHONHASHSEED` 없이는 불변이 아니며, 그 결함이 공정 프로브에서 이미 발견되었다
(`ptm_shared/representation/fair_probe.py`). **측정 후 변경 금지.**
"""

RIDGE_PENALTY_GRID = (0.01, 0.1, 1.0, 10.0, 100.0)
"""E1b primary 모형의 penalty 격자.

docs/c1_prereg_v1.md §6.3 에서 2026-08-20 선언(외부 검토 반영). τ 산정 전.
**격자를 늘리거나 줄이지 않는다** — 늘리면 저용량 비교자라는 전제가 깨진다.
"""

QUANTILE_LOW = 20.0
QUANTILE_HIGH = 80.0
"""`tau_low`/`tau_high` 임계는 **training fold 분포의 q20/q80** 이다. 절대값이 아니다.

docs/c1_prereg_v1.md §7.3 에서 2026-08-21 선언. τ 산정 전. **측정 후 변경 금지.**
"""

MIN_BLOCKS_PER_GROUP = 5
"""fold 평가 가능성 하한. 어느 fold 의 held-out high 군 또는 low 군이 5 블록 미만이면
그 fold 는 non-evaluable 이며 제외 사실과 개수를 보고한다.

docs/c1_prereg_v1.md §7.2 저빈도 규칙에서 2026-08-21 선언. τ 산정 전.
**대체 분할을 탐색하지 않는다** — 그 문서가 이것을 "핵심 금지 사항"으로 적었다.
"""

N_PERMUTATIONS = 10_000
N_BOOTSTRAP = 10_000
INFERENCE_SEED = 20260820
"""순열검정·bootstrap 의 반복수와 seed.

docs/c1_prereg_v1.md §7.4 (순열 10,000회·양측·seed 20260820) 와 §7.3.1 (bootstrap 동일 상수).
전자는 2026-08-20, 후자는 2026-08-22 확정. 둘 다 해당 산정 전.
"""

E1B_PREDICTORS = (
    "log10_design_condition_number",
    "log10_active_condition_number",
    "active_sigma_min",
    "max_column_coherence",
    "design_rank",
    "n_redundant",
)
"""방향 무관 예측자 집합 `X`.

docs/c1_prereg_v1.md §6.2 에서 2026-08-20 선언. τ 산정 전.
**결과 확인 후 성분을 빼거나 더하지 않는다**(§6.5). 순서도 그 문서의 나열 순서다.
"""


def fold_of(gene: str) -> int:
    """유전자 블록의 fold 번호. docs/c1_prereg_v1.md §7.2."""
    digest = hashlib.sha256(f"{str(gene).strip().upper()}{FOLD_SALT}".encode("utf-8"))
    return int.from_bytes(digest.digest()[:8], "big") % N_FOLDS


def design_from_records(records: Sequence[Mapping[str, Any]]) -> Tuple[np.ndarray, List[int]]:
    """`X` 행렬과 사용 가능한 행 인덱스. 비유한 성분이 있는 행은 제외하고 계수는 호출자가 보고한다.

    구현 대상: docs/c1_prereg_v1.md §6.2
    해석 한계: `cond` 이 `inf` 인 행은 `S-EVAL` 정의상 나오지 않아야 한다(§3.1). 나오면
              계층 배정과 X 계산이 어긋난 것이므로 개수를 보고해야 한다.
    """
    rows: List[List[float]] = []
    keep: List[int] = []
    for index, record in enumerate(records):
        values = [
            np.log10(max(float(record.get("design_condition_number") or np.nan), 1e-300)),
            np.log10(max(float(record.get("active_condition_number") or np.nan), 1e-300)),
            float(record.get("active_sigma_min") or np.nan),
            float(record.get("max_column_coherence") or np.nan),
            float(record.get("design_rank") or np.nan),
            float(record.get("n_redundant") or 0.0),
        ]
        if all(np.isfinite(value) for value in values):
            rows.append(values)
            keep.append(index)
    matrix = np.asarray(rows, dtype=float) if rows else np.zeros((0, len(E1B_PREDICTORS)))
    return matrix, keep


def _ridge_fit(
    features: np.ndarray, response: np.ndarray, penalty: float
) -> Tuple[np.ndarray, float, np.ndarray, np.ndarray]:
    """표준화된 ridge 적합. 절편은 penalty 를 받지 않는다."""
    center = features.mean(axis=0)
    spread = features.std(axis=0)
    spread = np.where(spread > 1e-12, spread, 1.0)
    scaled = (features - center) / spread
    intercept = float(response.mean())
    centered = response - intercept
    gram = scaled.T @ scaled + penalty * np.eye(scaled.shape[1])
    weights = np.linalg.solve(gram, scaled.T @ centered)
    return weights, intercept, center, spread


def _ridge_predict(
    features: np.ndarray,
    weights: np.ndarray,
    intercept: float,
    center: np.ndarray,
    spread: np.ndarray,
) -> np.ndarray:
    return ((features - center) / spread) @ weights + intercept


def spearman(first: Sequence[float], second: Sequence[float]) -> Optional[float]:
    """동점 평균 순위 Spearman. scipy 에 의존하지 않는다(결정성 확보)."""
    a = np.asarray(first, dtype=float)
    b = np.asarray(second, dtype=float)
    if a.size < 3 or a.size != b.size:
        return None
    ranked_a = _average_ranks(a)
    ranked_b = _average_ranks(b)
    if np.std(ranked_a) < 1e-12 or np.std(ranked_b) < 1e-12:
        return None
    return float(np.corrcoef(ranked_a, ranked_b)[0, 1])


def _average_ranks(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="stable")
    ranks = np.empty(values.size, dtype=float)
    position = 0
    while position < values.size:
        stop = position
        while stop + 1 < values.size and values[order[stop + 1]] == values[order[position]]:
            stop += 1
        mean_rank = (position + stop) / 2.0 + 1.0
        for index in range(position, stop + 1):
            ranks[order[index]] = mean_rank
        position = stop + 1
    return ranks


def normalized_inversion_fraction(
    truth: Sequence[float], predicted: Sequence[float]
) -> Optional[Dict[str, float]]:
    """`D_inv` — primary 재순서화 측도. 동점 쌍은 half-credit.

    구현 대상: docs/c1_prereg_v1.md §6.4 (`D_inv` primary 확정, `disc` 제거)
    해석 한계: 절단점이 없으므로 `disc` 와 달리 두 임계에 민감하지 않다. 그러나 여전히
              **기술 통계**이며 판정에 쓰지 않는다(§6.1).
    """
    a = np.asarray(truth, dtype=float)
    b = np.asarray(predicted, dtype=float)
    if a.size < 2 or a.size != b.size:
        return None
    n_discordant = 0.0
    n_comparable = 0
    for i in range(a.size):
        for j in range(i + 1, a.size):
            if a[i] == a[j]:
                continue  # τ 동점 쌍은 비교 불가 — 분모에서 제외한다
            n_comparable += 1
            product = (a[i] - a[j]) * (b[i] - b[j])
            if product < 0:
                n_discordant += 1.0
            elif product == 0:
                n_discordant += 0.5  # 예측 동점 = half-credit (§6.4)
    if n_comparable == 0:
        return None
    return {
        "d_inv": n_discordant / n_comparable,
        "n_comparable_pairs": float(n_comparable),
    }


def kendall_tau_b(first: Sequence[float], second: Sequence[float]) -> Optional[float]:
    """동점 보정 Kendall tau-b. **redundant 지표이며 primary 가 아니다**(§6.4)."""
    a = np.asarray(first, dtype=float)
    b = np.asarray(second, dtype=float)
    if a.size < 2 or a.size != b.size:
        return None
    concordant = discordant = tie_a = tie_b = 0
    for i in range(a.size):
        for j in range(i + 1, a.size):
            da = a[i] - a[j]
            db = b[i] - b[j]
            if da == 0 and db == 0:
                tie_a += 1
                tie_b += 1
            elif da == 0:
                tie_a += 1
            elif db == 0:
                tie_b += 1
            elif da * db > 0:
                concordant += 1
            else:
                discordant += 1
    n_pairs = a.size * (a.size - 1) / 2
    denominator = np.sqrt((n_pairs - tie_a) * (n_pairs - tie_b))
    if denominator <= 0:
        return None
    return float((concordant - discordant) / denominator)


def run_e1b(
    records: Sequence[Mapping[str, Any]], *, tau_field: str = "tau_act"
) -> Dict[str, Any]:
    """E1b — `X` 가 τ 를 얼마나 설명하는지 out-of-fold 로 기술한다.

    구현 대상: docs/c1_prereg_v1.md §6.2 (X), §6.3 (ridge primary·내부 CV), §6.4 (D_inv),
              §6.5 (편향 방지)
    해석 한계: **판정 관문이 아니다.** 어떤 임계로도 C1 을 기각하지 않는다(§6.3 결정 행).
              p-value 를 내지 않는다(§6.5). 반환값에 p-value 필드가 없는 것이 그 이유다.
    주장 금지: 높은 `oof_r2` 를 "τ 는 기존 지표의 재포장"의 증명으로, 낮은 값을 "τ 는
              신규 정보"의 증명으로 쓰지 않는다. 둘 다 이 설계가 지지하지 않는 강한 주장이다.
    """
    matrix, keep = design_from_records(records)
    n_dropped = len(records) - len(keep)
    if matrix.shape[0] < 10:
        return {
            "status": "insufficient_rows",
            "n_rows": int(matrix.shape[0]),
            "n_dropped_nonfinite": n_dropped,
            "tau_field": tau_field,
        }

    used = [records[index] for index in keep]
    response = np.asarray([float(row.get(tau_field) or 0.0) for row in used], dtype=float)
    genes = [str(row.get("gene") or "") for row in used]
    folds = np.asarray([fold_of(gene) for gene in genes], dtype=int)

    predictions = np.full(response.size, np.nan, dtype=float)
    chosen_penalties: List[float] = []
    for outer in range(N_FOLDS):
        test = folds == outer
        train = ~test
        if test.sum() == 0 or train.sum() < 10:
            continue
        penalty = _select_penalty(matrix[train], response[train], folds[train])
        chosen_penalties.append(penalty)
        weights, intercept, center, spread = _ridge_fit(
            matrix[train], response[train], penalty
        )
        predictions[test] = _ridge_predict(
            matrix[test], weights, intercept, center, spread
        )

    evaluated = np.isfinite(predictions)
    if evaluated.sum() < 10:
        return {
            "status": "insufficient_oof",
            "n_oof": int(evaluated.sum()),
            "tau_field": tau_field,
        }

    truth = response[evaluated]
    predicted = predictions[evaluated]
    block_labels = [genes[index] for index in np.flatnonzero(evaluated)]

    residual = truth - predicted
    total = truth - truth.mean()
    oof_r2 = float(1.0 - (residual @ residual) / max(total @ total, 1e-12))
    rho = spearman(truth, predicted)
    inversion = normalized_inversion_fraction(truth, predicted)

    return {
        "status": "measured",
        "tau_field": tau_field,
        "predictors": list(E1B_PREDICTORS),
        "n_rows": int(matrix.shape[0]),
        "n_dropped_nonfinite": n_dropped,
        "n_oof": int(evaluated.sum()),
        "n_blocks": len(set(block_labels)),
        "penalties_selected": chosen_penalties,
        "oof_spearman": rho,
        "oof_spearman_ci95": _block_bootstrap_ci(
            truth, predicted, block_labels, statistic="spearman"
        ),
        "oof_r2": oof_r2,
        "oof_r2_ci95": _block_bootstrap_ci(
            truth, predicted, block_labels, statistic="r2"
        ),
        "d_inv_primary": inversion,
        "kendall_tau_b_redundant": kendall_tau_b(truth, predicted),
        "note": "기술 통계. p-value 없음 (§6.5). C1 판정에 쓰지 않는다 (§6.1)",
    }


def _select_penalty(
    features: np.ndarray, response: np.ndarray, folds: np.ndarray
) -> float:
    """내부 유전자 블록 CV 로 penalty 를 고른다. docs/c1_prereg_v1.md §6.3·§6.5."""
    best_penalty = RIDGE_PENALTY_GRID[0]
    best_error = np.inf
    inner_folds = sorted(set(int(value) for value in folds))
    for penalty in RIDGE_PENALTY_GRID:
        errors: List[float] = []
        for inner in inner_folds:
            test = folds == inner
            train = ~test
            if test.sum() == 0 or train.sum() < 5:
                continue
            weights, intercept, center, spread = _ridge_fit(
                features[train], response[train], penalty
            )
            prediction = _ridge_predict(
                features[test], weights, intercept, center, spread
            )
            errors.append(float(np.mean((response[test] - prediction) ** 2)))
        if errors and float(np.mean(errors)) < best_error:
            best_error = float(np.mean(errors))
            best_penalty = penalty
    return best_penalty


def _block_bootstrap_ci(
    truth: np.ndarray,
    predicted: np.ndarray,
    blocks: Sequence[str],
    *,
    statistic: str,
) -> Optional[List[float]]:
    """유전자 블록 bootstrap 95% CI. docs/c1_prereg_v1.md §6.3 (primary 통계량 행), §7.3.1 (seed)."""
    unique = sorted(set(blocks))
    if len(unique) < 5:
        return None
    index_by_block: Dict[str, List[int]] = {label: [] for label in unique}
    for position, label in enumerate(blocks):
        index_by_block[label].append(position)

    rng = np.random.default_rng(INFERENCE_SEED)
    draws: List[float] = []
    for _ in range(N_BOOTSTRAP):
        picked = rng.choice(len(unique), size=len(unique), replace=True)
        rows: List[int] = []
        for position in picked:
            rows.extend(index_by_block[unique[position]])
        sample_truth = truth[rows]
        sample_predicted = predicted[rows]
        if statistic == "spearman":
            value = spearman(sample_truth, sample_predicted)
        else:
            residual = sample_truth - sample_predicted
            centred = sample_truth - sample_truth.mean()
            denominator = float(centred @ centred)
            value = (
                float(1.0 - (residual @ residual) / denominator)
                if denominator > 1e-12
                else None
            )
        if value is not None and np.isfinite(value):
            draws.append(float(value))
    if len(draws) < 100:
        return None
    return [
        float(np.percentile(draws, 2.5)),
        float(np.percentile(draws, 97.5)),
    ]


def cliffs_delta(first: Sequence[float], second: Sequence[float]) -> Optional[float]:
    """Cliff's delta. docs/c1_prereg_v1.md §7.4 (블록 단위 효과크기)."""
    a = np.asarray(first, dtype=float)
    b = np.asarray(second, dtype=float)
    if a.size == 0 or b.size == 0:
        return None
    greater = int((a[:, None] > b[None, :]).sum())
    lesser = int((a[:, None] < b[None, :]).sum())
    return float((greater - lesser) / (a.size * b.size))


def run_e3(
    records: Sequence[Mapping[str, Any]], *, tau_field: str
) -> Dict[str, Any]:
    """E3 — τ 의 held-out 예측 타당도. **§3.5.1 에서 primary 에서 강등. 탐색적.**

    구현 대상: docs/c1_prereg_v1.md §7.2 (교차적합), §7.3 (training fold 에서만 정하는 것),
              §7.3.1 (블록 집계 = median, seed), §7.4 (판정 수식), §3.5.2 (탐색적 지위)
    사전등록: 절차는 2026-08-21 동결. **탐색적이라는 이유로 절차를 느슨하게 하지 않는다**(§3.5.2).
    해석 한계: 모집단은 baseline 기준 `S-EVAL` 만이다(§7.5 조건부 estimand). `S-DEAD` 는
              `Δẑ ≡ 0` 이 구조적으로 강제되므로 포함하면 검정력과 해석이 모두 나빠진다.
              반환값의 `p_permutation` 은 **확증 판정이 아니다.**
    주장 금지: 이 결과로 C1 성공을 선언하지 않는다(§6.6 OR 경로 금지). "통과/실패" 라벨을
              붙이지 않는다(§3.5.2). 검정력 미달로 인한 미평가를 "예측 실패"로 쓰지 않는다.
    """
    usable = [
        row
        for row in records
        if row.get(tau_field) is not None and row.get("downstream_response") is not None
    ]
    aggregation = "median (C1_BLOCK_AGGREGATION_V1, §7.3.1)"
    if len(usable) < 10:
        return {
            "status": "insufficient_rows",
            "n_rows": len(usable),
            "tau_field": tau_field,
            "aggregation": aggregation,
        }

    blocks: Dict[str, Dict[str, List[float]]] = {}
    for row in usable:
        gene = str(row.get("gene") or "")
        block = blocks.setdefault(gene, {"tau": [], "response": []})
        block["tau"].append(float(row[tau_field]))
        block["response"].append(float(row["downstream_response"]))

    block_names = sorted(blocks)
    block_tau = np.asarray(
        [float(np.median(blocks[name]["tau"])) for name in block_names], dtype=float
    )
    block_response = np.asarray(
        [float(np.median(blocks[name]["response"])) for name in block_names], dtype=float
    )
    block_folds = np.asarray([fold_of(name) for name in block_names], dtype=int)

    labels = np.zeros(len(block_names), dtype=int)  # 0 = 중간(미사용), 1 = high, -1 = low
    fold_reports: List[Dict[str, Any]] = []
    for outer in range(N_FOLDS):
        test = block_folds == outer
        train = ~test
        if test.sum() == 0 or train.sum() < 5:
            fold_reports.append(
                {
                    "fold": outer,
                    "status": "non_evaluable_training_too_small",
                    "n_heldout_blocks": int(test.sum()),
                }
            )
            continue
        low_cut = float(np.percentile(block_tau[train], QUANTILE_LOW))
        high_cut = float(np.percentile(block_tau[train], QUANTILE_HIGH))
        assigned = np.zeros(len(block_names), dtype=int)
        assigned[test & (block_tau <= low_cut)] = -1
        assigned[test & (block_tau >= high_cut)] = 1
        n_low = int((assigned == -1).sum())
        n_high = int((assigned == 1).sum())
        if n_low < MIN_BLOCKS_PER_GROUP or n_high < MIN_BLOCKS_PER_GROUP:
            fold_reports.append(
                {
                    "fold": outer,
                    "status": "non_evaluable_low_count",
                    "n_heldout_blocks": int(test.sum()),
                    "n_low": n_low,
                    "n_high": n_high,
                    "tau_low_cut": low_cut,
                    "tau_high_cut": high_cut,
                }
            )
            continue
        labels = labels + assigned
        fold_reports.append(
            {
                "fold": outer,
                "status": "evaluable",
                "n_heldout_blocks": int(test.sum()),
                "n_low": n_low,
                "n_high": n_high,
                "tau_low_cut": low_cut,
                "tau_high_cut": high_cut,
            }
        )

    high = block_response[labels == 1]
    low = block_response[labels == -1]
    n_evaluable_folds = sum(1 for item in fold_reports if item["status"] == "evaluable")
    if high.size < MIN_BLOCKS_PER_GROUP or low.size < MIN_BLOCKS_PER_GROUP:
        return {
            "status": "non_evaluable",
            "reason": "pooled high or low group below the pre-registered block floor",
            "tau_field": tau_field,
            "n_blocks": len(block_names),
            "n_high_blocks": int(high.size),
            "n_low_blocks": int(low.size),
            "n_evaluable_folds": n_evaluable_folds,
            "folds": fold_reports,
            "aggregation": aggregation,
            "note": (
                "미평가다. 실패가 아니다 (§3.5.1). 대체 분할을 탐색하지 않는다 (§7.2) — "
                "이 결과를 얻으려고 다른 분할을 시도하는 것이 사전등록 위반이다"
            ),
        }

    observed = float(np.median(high) - np.median(low))
    pooled = np.concatenate([high, low])
    group = np.concatenate([np.ones(high.size, dtype=int), np.zeros(low.size, dtype=int)])
    rng = np.random.default_rng(INFERENCE_SEED)
    extreme = 0
    for _ in range(N_PERMUTATIONS):
        shuffled = rng.permutation(group)
        candidate = float(
            np.median(pooled[shuffled == 1]) - np.median(pooled[shuffled == 0])
        )
        if abs(candidate) >= abs(observed) - 1e-12:
            extreme += 1
    p_value = (extreme + 1) / (N_PERMUTATIONS + 1)

    return {
        "status": "measured_exploratory",
        "tau_field": tau_field,
        "n_sites": len(usable),
        "n_blocks": len(block_names),
        "n_high_blocks": int(high.size),
        "n_low_blocks": int(low.size),
        "n_evaluable_folds": n_evaluable_folds,
        "median_response_high": float(np.median(high)),
        "median_response_low": float(np.median(low)),
        "observed_difference": observed,
        "direction_matches_prediction": bool(observed > 0),
        "p_permutation": float(p_value),
        "cliffs_delta": cliffs_delta(high, low),
        "folds": fold_reports,
        "aggregation": aggregation,
        "note": (
            "탐색적. primary 승격 영구 금지 (§3.5.2). 통과/실패 라벨을 붙이지 않는다. "
            "이 p-value 로 C1 성공을 선언하지 않는다 (§6.6)"
        ),
    }


E3B_SIGN_AGREEMENT_MIN = 0.80
"""E3b 통과 임계 — 부호가 예측과 일치하는 site 비율.

docs/c1_prereg_v1.md §8.2 에서 2026-08-20 선언. τ 산정 전.
E3b 는 §6.6 에서 **탐색적**으로 지정되었으므로 이 임계는 C1 판정을 바꾸지 않는다.
**측정 후 변경 금지.**
"""

E3B_SIGN_TEST_ALPHA = 0.05
"""E3b 부호검정의 양측 유의수준. docs/c1_prereg_v1.md §8.2 에서 2026-08-20 선언."""


def exact_sign_test(n_positive: int, n_total: int) -> Optional[float]:
    """부호검정 양측 p-value (정확 이항, p0 = 0.5). scipy 에 의존하지 않는다.

    구현 대상: docs/c1_prereg_v1.md §8.2 (부호검정, 양측 p < 0.05)
    해석 한계: 동점(ρ = 0 또는 미정의) site 는 호출자가 `n_total` 에서 제외해야 한다.
              부호검정의 표준 관례이며 여기서 임계를 새로 정하지 않는다.
    """
    from math import comb

    if n_total <= 0 or not (0 <= n_positive <= n_total):
        return None
    probabilities = [comb(n_total, k) for k in range(n_total + 1)]
    total = float(sum(probabilities))
    observed = probabilities[n_positive] / total
    tail = sum(
        value / total for value in probabilities if value / total <= observed + 1e-15
    )
    return float(min(tail, 1.0))


def descriptive_association(
    records: Sequence[Mapping[str, Any]], *, tau_field: str
) -> Dict[str, Any]:
    """τ 와 `Δẑ` 의 **동일 표본** 연관. 근거가 아니라 감사 수치다.

    구현 대상: docs/c1_prereg_v1.md §7.1 (회피 대상)
    사전등록: E3 가 평가 불가로 확정된 뒤(2026-08-22) 추가한 기술 통계다. 따라서
              **영구 탐색적**이며 primary 승격이 불가능하다. 그 사실을 여기 기록한다.
    해석 한계: §7.1 이 이 상관을 명시적으로 기각한다 — τ 와 `Δẑ` 는 같은 `A_i`·같은 `d_i` 에서
              나오므로 상관은 **NNLS 정사영 성질의 재진술**이며 기계적으로 발생한다.
              held-out 이 아니므로 예측 타당도의 증거가 전혀 아니다.
    주장 금지: 이 값으로 "τ 가 하류 민감도를 예측한다"고 쓰지 않는다. E3 의 대체물이 아니다.
              심사에서 물어올 것이 확실하므로 **미리 보고하고 스스로 기각**하기 위해 낸다.
    """
    usable = [
        row
        for row in records
        if row.get(tau_field) is not None and row.get("downstream_response") is not None
    ]
    if len(usable) < 10:
        return {"status": "insufficient_rows", "n_rows": len(usable)}

    blocks: Dict[str, Dict[str, List[float]]] = {}
    for row in usable:
        block = blocks.setdefault(str(row.get("gene") or ""), {"tau": [], "response": []})
        block["tau"].append(float(row[tau_field]))
        block["response"].append(float(row["downstream_response"]))
    names = sorted(blocks)
    block_tau = [float(np.median(blocks[name]["tau"])) for name in names]
    block_response = [float(np.median(blocks[name]["response"])) for name in names]

    return {
        "status": "descriptive_only_never_evidence",
        "tau_field": tau_field,
        "n_sites": len(usable),
        "n_blocks": len(names),
        "site_level_spearman": spearman(
            [float(row[tau_field]) for row in usable],
            [float(row["downstream_response"]) for row in usable],
        ),
        "block_level_spearman": spearman(block_tau, block_response),
        "n_sites_with_zero_response": sum(
            1 for row in usable if abs(float(row["downstream_response"])) < 1e-12
        ),
        "note": (
            "§7.1 이 이 상관을 근거로 인정하지 않는다 — 동일 표본이며 NNLS 정사영 성질의 "
            "재진술이다. E3 의 대체물이 아니고 예측 타당도의 증거가 아니다"
        ),
    }


def provenance() -> Dict[str, Any]:
    """결정성 정보. `.cursor/rules/research-code-provenance.mdc` §5."""
    return {
        "numpy": np.__version__,
        "dtype": "float64",
        "n_folds": N_FOLDS,
        "fold_rule": f"sha256(gene + {FOLD_SALT!r}) mod {N_FOLDS}",
        "ridge_penalty_grid": list(RIDGE_PENALTY_GRID),
        "quantiles": [QUANTILE_LOW, QUANTILE_HIGH],
        "min_blocks_per_group": MIN_BLOCKS_PER_GROUP,
        "n_permutations": N_PERMUTATIONS,
        "n_bootstrap": N_BOOTSTRAP,
        "seed": INFERENCE_SEED,
        "rng": "numpy.random.default_rng (PCG64)",
        "scipy_used": False,
    }


__all__ = [
    "E1B_PREDICTORS",
    "E3B_SIGN_AGREEMENT_MIN",
    "E3B_SIGN_TEST_ALPHA",
    "INFERENCE_SEED",
    "exact_sign_test",
    "MIN_BLOCKS_PER_GROUP",
    "N_BOOTSTRAP",
    "N_FOLDS",
    "N_PERMUTATIONS",
    "QUANTILE_HIGH",
    "QUANTILE_LOW",
    "RIDGE_PENALTY_GRID",
    "cliffs_delta",
    "descriptive_association",
    "design_from_records",
    "fold_of",
    "kendall_tau_b",
    "normalized_inversion_fraction",
    "provenance",
    "run_e1b",
    "run_e3",
    "spearman",
]
