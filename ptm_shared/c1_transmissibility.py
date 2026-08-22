"""Transmissibility (τ) of an upstream representation change through a fixed dictionary.

구현 대상: docs/c1_prereg_v1.md §4 (τ 정의), §5 (E1 출력·요약), §7.4 (Δẑ 정의),
          §8.1 (E3b 개입 I1–I4)
사전등록: 2026-08-20 동결, 2026-08-22 선행 확인 완료. **이 모듈은 τ 를 처음 계산하는 코드이며
          어떤 임계도 새로 도입하지 않는다.** 모든 규칙은 위 문서의 절을 인용한다.
해석 한계: τ 는 **전달 가능성의 필요조건**이며 하류 개선의 상한이 아니다. 그리고 τ 는
          "표현 변화의 전달성"이 아니라 **"대입 채움을 포함한 표현 변화의 전달성"**이다
          (§2.1.3) — 인코더 재구성은 모든 시점에 값을 내는데 NNLS 는 미관측을 0 으로
          대입하므로, `d` 는 NNLS 가 단단한 0 을 본 자리에 비영 성분을 갖는다.
          영값 대입은 평가 가능한 site 의 10.1% 에서 top-1 을 뒤집으므로 이 성분은 무해하지 않다.
          `d` 는 실제 production 변화가 아니라 **반사실 섭동**이다 (§2.2).
주장 금지: 이 값으로 kinase 귀속 정확도를 논하지 않는다. "표현 개선이 귀속을 개선한다/
          개선하지 않는다"고 쓰지 않는다. "τ 가 낮으므로 표현 학습이 무용하다"고 쓰지 않는다 —
          퇴화는 하류 사전(dictionary)의 성질이고 상류 표현의 성질이 아니다 (§2.2).

선행 연구 고지 (필수. §4.1)
--------------------------
`τ_col = dᵀ R_data d / dᵀ d` 이며 `R_data = A A⁺` 는 선형 역문제의 **data resolution matrix**
(Backus–Gilbert 1968; Wiggins 1972; Jackson 1972)다. 즉 `τ_col` 은 신규 양이 아니라 확립된
대상의 방향별 Rayleigh 몫이다. **`τ_act` 의 활성집합 사용만이 NNLS 특유의 증분이다.**
`integrated_research_design_v2.md` §9.1.1 을 함께 인용한다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from ptm_shared.tmm_identifiability import (
    _numerical_rank,
    normalized_ratios,
    solve_nnls,
)

CONTRACT_VERSION = "c1_transmissibility.v1"

D_NORM_FLOOR = 1e-12
"""`|| d_i || <= 1e-12` 이면 τ 미정의. 분석 제외하고 개수를 보고한다.

docs/c1_prereg_v1.md §4.3 경계 규약에서 2026-08-20 선언. τ 계산 전.
**측정 후 변경 금지** — 변경하면 제외 집합이 달라져 E1 요약이 무효가 된다.
"""

ACTIVE_COEFFICIENT_FLOOR = 0.0
"""활성집합 = NNLS 해에서 계수가 **양인** 열.

docs/c1_prereg_v1.md §4.1 에서 선언(`active_i` = 계수가 양인 열 집합, 기존 `n_active` 정의 재사용).
`> 0.0` 을 쓰며 별도 tolerance 를 도입하지 않는다 — tolerance 를 도입하면 그것이 사전등록에
없는 임계가 된다.
"""

ACTIVE_INSTABILITY_LIMIT = 0.30
"""`active_stable = False` 비율이 이 값을 넘으면 τ_col 을 primary 로 승격한다.

docs/c1_prereg_v1.md §4.2 에서 2026-08-20 선언. τ 계산 전.
"이 승격 규칙은 지금 확정된 것이며 사후 선택이 아니다"가 그 문서의 문구다.
**측정 후 변경 금지.**
"""

BASELINE_ZERO_IMPUTED_TRAJECTORY = "zero_imputed_l1_trajectory"
"""`d` 의 baseline — NNLS 가 실제로 소비하는 영값 대입 궤적 `y_i`.

docs/c1_prereg_v1.md §2.1.3 에서 2026-08-22 확정. τ 계산 전.

**왜 이것인가.** §2.1.3 은 "NNLS 는 미관측 조건을 0 으로 대입하고 인코더 reconstruction 은
모든 시점에 값을 내므로 `d_i` 는 NNLS 가 단단한 0 을 본 자리에 비영 성분을 갖는다"고 쓴다.
이 서술은 baseline 이 **영값 대입된 `y_i` 그 자체**일 때만 성립한다. 따라서 사전등록이
전제한 baseline 은 이것이며, 여기서 새로 고르는 것이 아니다.

설계 문서 §5.5 의 "baseline L1 표현"에서 `L1` 은 **표현 층 이름**(`ptm_vector_data_normalized*.tsv`,
site×timepoint 정량 벡터)이며 §3.3 의 모집단 수준 `L1`(HIRc-B 확증 universe)과 다른 뜻이다.
두 문서를 함께 읽을 때 혼동하지 않는다.
"""

BASELINE_OBSERVED_ONLY = "observed_only"
"""secondary — `d` 를 관측 시점에만 남기고 미관측 성분을 0 으로 만든 변형.

docs/c1_prereg_v1.md §2.1.3 의 해석 한계를 **측정 가능하게** 만들기 위해 2026-08-22 선언.
τ 계산 전이므로 사전등록된 secondary 이며, primary 는 아니다.

`τ(d_full)` 과 `τ(d_obs)` 의 차이가 §2.1.3 이 경고한 "대입 채움 방향"의 기여분이다.
두 값을 함께 보고하면 τ 를 (1) 실제 궤적 변화와 (2) 대입 채움으로 분해해 서술할 수 있다.
**분해가 완전하다고 주장하지 않는다** — 두 성분은 직교하지 않는다.
"""


def column_space_projector(matrix: np.ndarray) -> Tuple[np.ndarray, int]:
    """열공간 정사영 행렬과 수치 rank 를 돌려준다.

    구현 대상: docs/c1_prereg_v1.md §4.1 (`P_col`, "수치 rank 기준, §1의 rank 규칙 재사용")
    해석 한계: rank 규칙은 `tmm_identifiability._numerical_rank` 를 **재사용**한다.
              여기서 새 절단 규칙을 정의하면 감사 수치와 τ 가 다른 rank 개념을 쓰게 된다.
    """
    if matrix.size == 0 or matrix.shape[1] == 0:
        n_rows = int(matrix.shape[0]) if matrix.ndim == 2 else 0
        return np.zeros((n_rows, n_rows), dtype=float), 0

    rank = _numerical_rank(matrix)
    if rank == 0:
        n_rows = int(matrix.shape[0])
        return np.zeros((n_rows, n_rows), dtype=float), 0

    left, _, _ = np.linalg.svd(np.asarray(matrix, dtype=float), full_matrices=False)
    basis = left[:, :rank]
    return basis @ basis.T, rank


def transmissibility(matrix: np.ndarray, direction: np.ndarray) -> Optional[float]:
    """섭동 방향이 행렬의 열공간에 보이는 에너지 비율.

    구현 대상: docs/c1_prereg_v1.md §4.1
    해석 한계: **보존 에너지 비율이며 하류 개선의 상한이 아니다.** 전달 가능성의 필요조건이다.
              `[0, 1]` 로 clip 하지 않는다 — 범위 밖 값은 수치 오류이므로 그대로 보고한다(§4.3).
    주장 금지: 이 값으로 귀속 정확도를 논하지 않는다.
    """
    vector = np.asarray(direction, dtype=float)
    denominator = float(vector @ vector)
    if denominator <= D_NORM_FLOOR**2:
        return None
    projector, rank = column_space_projector(matrix)
    if rank == 0:
        return 0.0
    projected = projector @ vector
    return float((projected @ projected) / denominator)


def active_columns(matrix: np.ndarray, target: np.ndarray) -> np.ndarray:
    """NNLS 해에서 계수가 양인 열의 인덱스.

    구현 대상: docs/c1_prereg_v1.md §4.1 (`active_i`)
    해석 한계: 활성집합은 `target` 에 의존하므로 `y` 와 `y + d` 에서 달라질 수 있다.
              그 불변성을 §4.2 의 `active_stable` 로 검사한다.
    """
    if matrix.size == 0 or matrix.shape[1] == 0:
        return np.zeros(0, dtype=int)
    coefficients, _ = solve_nnls(matrix, np.asarray(target, dtype=float))
    return np.flatnonzero(coefficients > ACTIVE_COEFFICIENT_FLOOR)


def downstream_response(
    matrix: np.ndarray, target: np.ndarray, direction: np.ndarray
) -> Optional[float]:
    """`Δẑ` — 보고 ratio 벡터의 total variation.

    구현 대상: docs/c1_prereg_v1.md §7.4 (`|| ratio(y + d) − ratio(y) ||_1`)
    사전등록: 2026-08-20 동결. E3 의 응답변수이며 여기서 정의를 바꾸지 않는다.
    해석 한계: `normalized_ratios` 는 해가 붕괴하면 균등 ratio 를 돌려준다. 따라서
              `constant-output-by-construction` site 에서는 `Δẑ ≡ 0` 이 **구조적으로 강제**되며
              그것이 §7.5 가 그 계층을 조건부 estimand 에서 분리하는 이유다.
    주장 금지: `Δẑ` 를 "귀속이 개선된 정도"로 읽지 않는다. 출력이 움직인 크기이며 방향의
              옳음과 무관하다.
    """
    if matrix.size == 0 or matrix.shape[1] == 0:
        return None
    base = np.asarray(target, dtype=float)
    perturbed = base + np.asarray(direction, dtype=float)
    ratio_base = normalized_ratios(solve_nnls(matrix, base)[0])
    ratio_perturbed = normalized_ratios(solve_nnls(matrix, perturbed)[0])
    if ratio_base.size == 0 or ratio_base.size != ratio_perturbed.size:
        return None
    return float(np.abs(ratio_perturbed - ratio_base).sum())


@dataclass
class SiteTransmissibility:
    """한 site 의 τ 레코드. 필드 구성은 docs/c1_prereg_v1.md §5.1 을 따른다."""

    site_key: str
    status: str
    tau_act: Optional[float] = None
    tau_col: Optional[float] = None
    tau_dd: Optional[float] = None
    tau_act_observed_only: Optional[float] = None
    tau_col_observed_only: Optional[float] = None
    active_stable: Optional[bool] = None
    downstream_response: Optional[float] = None
    d_norm: float = 0.0
    d_norm_observed_only: float = 0.0
    y_norm: float = 0.0
    n_timepoints: int = 0
    n_candidates: int = 0
    n_active: int = 0
    active_rank: int = 0
    design_rank: int = 0
    n_data_driven_columns: int = 0
    n_observed: int = 0
    gene: str = ""
    notes: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        record = asdict(self)
        record["notes"] = list(self.notes)
        return record


STATUS_EVALUATED = "evaluated"
STATUS_ZERO_DIRECTION = "excluded_zero_direction"
STATUS_ZERO_RANK = "excluded_zero_rank"
STATUS_NO_COLUMNS = "excluded_no_candidate_columns"
"""제외 사유 라벨. docs/c1_prereg_v1.md §4.3 의 세 경계 규약에 하나씩 대응한다.

제외는 **은폐가 아니라 계수 보고 대상**이다. §4.3 이 "분석 제외, 개수 보고"를 요구한다.
"""


def site_transmissibility(
    site_key: str,
    design: np.ndarray,
    target: np.ndarray,
    direction: np.ndarray,
    *,
    observed_mask: Optional[Sequence[bool]] = None,
    prior_flags: Optional[Sequence[bool]] = None,
    gene: str = "",
) -> SiteTransmissibility:
    """한 site 의 τ 와 부수 진단을 계산한다.

    구현 대상: docs/c1_prereg_v1.md §4.1 (τ_act·τ_col·τ_dd), §4.2 (국소성), §4.3 (경계),
              §5.1 (출력 필드), §7.4 (Δẑ)
    해석 한계: `tau_dd` 는 데이터 유래 열만의 부분행렬에 대한 값이며 **primary 가 아니다** —
              데이터 유래 열이 오더당 0–5개에 불과해 계층이 지나치게 작다(§4.1).
    주장 금지: `active_stable = False` site 를 "τ 가 틀린 site"로 서술하지 않는다. 국소
              선형화 전제가 깨진 site 이며 그 사실 자체가 보고 대상이다.
    """
    matrix = np.asarray(design, dtype=float)
    y = np.asarray(target, dtype=float)
    d = np.asarray(direction, dtype=float)
    notes: List[str] = []

    n_time = int(matrix.shape[0]) if matrix.ndim == 2 else 0
    n_candidates = int(matrix.shape[1]) if matrix.ndim == 2 else 0
    d_norm = float(np.linalg.norm(d))
    y_norm = float(np.linalg.norm(y))
    mask = (
        np.ones(n_time, dtype=bool)
        if observed_mask is None
        else np.asarray(observed_mask, dtype=bool)
    )
    d_observed = np.where(mask, d, 0.0)

    base = SiteTransmissibility(
        site_key=site_key,
        status=STATUS_EVALUATED,
        d_norm=d_norm,
        d_norm_observed_only=float(np.linalg.norm(d_observed)),
        y_norm=y_norm,
        n_timepoints=n_time,
        n_candidates=n_candidates,
        n_observed=int(mask.sum()),
        gene=gene,
    )

    if n_candidates == 0:
        base.status = STATUS_NO_COLUMNS
        return base

    design_rank = _numerical_rank(matrix)
    base.design_rank = design_rank
    if design_rank == 0:
        base.status = STATUS_ZERO_RANK
        return base

    if d_norm <= D_NORM_FLOOR:
        base.status = STATUS_ZERO_DIRECTION
        return base

    active = active_columns(matrix, y)
    base.n_active = int(active.size)
    active_matrix = matrix[:, active] if active.size else np.zeros((n_time, 0))
    base.active_rank = _numerical_rank(active_matrix) if active.size else 0

    base.tau_act = transmissibility(active_matrix, d) if active.size else 0.0
    base.tau_col = transmissibility(matrix, d)
    base.tau_act_observed_only = (
        transmissibility(active_matrix, d_observed) if active.size else 0.0
    )
    base.tau_col_observed_only = transmissibility(matrix, d_observed)

    if prior_flags is not None:
        flags = np.asarray(prior_flags, dtype=bool)
        data_driven = np.flatnonzero(~flags)
        base.n_data_driven_columns = int(data_driven.size)
        if data_driven.size:
            # τ_dd 는 활성집합과 데이터 유래 열의 교집합에서 계산한다 — τ_act 의 정의를
            # 유지하면서 prior 열 의존도만 떼어내기 위해서다 (§4.1).
            dd_active = np.intersect1d(active, data_driven, assume_unique=False)
            if dd_active.size:
                base.tau_dd = transmissibility(matrix[:, dd_active], d)
            else:
                notes.append("tau_dd_undefined_no_active_data_driven_column")
        else:
            notes.append("tau_dd_undefined_no_data_driven_column")

    perturbed_active = active_columns(matrix, y + d)
    base.active_stable = bool(
        active.size == perturbed_active.size and np.array_equal(active, perturbed_active)
    )
    base.downstream_response = downstream_response(matrix, y, d)
    base.notes = tuple(notes)
    return base


def quantile_summary(values: Sequence[Optional[float]]) -> Dict[str, Any]:
    """중앙값과 10/50/90 분위. docs/c1_prereg_v1.md §5.2 가 요구하는 형태.

    §5.2 는 **평균을 primary 로 쓰지 않는다** — 0 과 1 근처에 질량이 몰릴 것으로 예상되어
    평균이 대표성을 잃는다. 평균은 참고용으로만 함께 낸다.
    """
    finite = np.asarray(
        [float(value) for value in values if value is not None and np.isfinite(value)],
        dtype=float,
    )
    if finite.size == 0:
        return {"n": 0, "p10": None, "p50": None, "p90": None, "mean_not_primary": None}
    return {
        "n": int(finite.size),
        "p10": float(np.percentile(finite, 10)),
        "p50": float(np.percentile(finite, 50)),
        "p90": float(np.percentile(finite, 90)),
        "mean_not_primary": float(finite.mean()),
    }


def summarize_by_stratum(
    records: Sequence[Mapping[str, Any]], *, stratum_key: str = "stratum"
) -> Dict[str, Any]:
    """계층별 τ_act 요약. docs/c1_prereg_v1.md §5.2.

    해석 한계: 계층 라벨은 `c1_prereg_v1.md` §3.1 에서 오고 이 함수가 정의하지 않는다.
    """
    grouped: Dict[str, List[Mapping[str, Any]]] = {}
    for record in records:
        grouped.setdefault(str(record.get(stratum_key)), []).append(record)

    summary: Dict[str, Any] = {}
    for stratum, items in sorted(grouped.items()):
        evaluated = [item for item in items if item.get("status") == STATUS_EVALUATED]
        stable = [
            item for item in evaluated if item.get("active_stable") is not None
        ]
        n_unstable = sum(1 for item in stable if not item["active_stable"])
        summary[stratum] = {
            "n_sites": len(items),
            "n_evaluated": len(evaluated),
            "tau_act": quantile_summary([item.get("tau_act") for item in evaluated]),
            "tau_col": quantile_summary([item.get("tau_col") for item in evaluated]),
            "tau_dd": quantile_summary([item.get("tau_dd") for item in evaluated]),
            "tau_act_observed_only": quantile_summary(
                [item.get("tau_act_observed_only") for item in evaluated]
            ),
            "downstream_response": quantile_summary(
                [item.get("downstream_response") for item in evaluated]
            ),
            "active_unstable_fraction": (
                n_unstable / len(stable) if stable else None
            ),
        }
    return summary


def primary_tau_field(active_unstable_fraction: Optional[float]) -> str:
    """§4.2 의 승격 규칙을 적용해 primary τ 필드 이름을 돌려준다.

    구현 대상: docs/c1_prereg_v1.md §4.2
    사전등록: 승격 임계 0.30 은 2026-08-20 선언(τ 계산 전). **결과를 보고 바꾸지 않는다.**
    해석 한계: 승격이 일어나면 primary 가 `τ_col` 이 되므로 **활성집합 국소 해석을 철회**한
              것이며, τ 가 더 정확해진 것이 아니다.
    """
    if active_unstable_fraction is None:
        return "tau_act"
    if float(active_unstable_fraction) > ACTIVE_INSTABILITY_LIMIT:
        return "tau_col"
    return "tau_act"


# ---------------------------------------------------------------------------
# E3b — 기전 양성 대조 개입 (docs/c1_prereg_v1.md §8.1)
# ---------------------------------------------------------------------------

DUPLICATE_COHERENCE_LIMIT = 0.9999
"""I1 의 중복 열 판정 임계. docs/c1_prereg_v1.md §8.1 에서 2026-08-20 선언. τ 계산 전."""


def merge_duplicate_columns(design: np.ndarray) -> Tuple[np.ndarray, List[List[int]]]:
    """I1 — coherence ≥ 0.9999 열 군집을 대표열로 축약한다.

    구현 대상: docs/c1_prereg_v1.md §8.1 I1
    해석 한계: 대표열은 군집의 **첫 열**이며 평균이 아니다. 평균을 쓰면 새 방향이 생겨
              "중복 제거"가 아니라 "설계 변경"이 된다.
    """
    matrix = np.asarray(design, dtype=float)
    if matrix.shape[1] < 2:
        return matrix, [[index] for index in range(matrix.shape[1])]

    norms = np.linalg.norm(matrix, axis=0)
    safe = np.where(norms > 1e-12, norms, 1.0)
    unit = matrix / safe
    gram = np.abs(unit.T @ unit)

    assigned: Dict[int, int] = {}
    groups: List[List[int]] = []
    for index in range(matrix.shape[1]):
        if index in assigned:
            continue
        group = [index]
        assigned[index] = len(groups)
        for other in range(index + 1, matrix.shape[1]):
            if other not in assigned and gram[index, other] >= DUPLICATE_COHERENCE_LIMIT:
                group.append(other)
                assigned[other] = len(groups)
        groups.append(group)

    reduced = np.column_stack([matrix[:, group[0]] for group in groups])
    return reduced, groups


def drop_prior_columns(
    design: np.ndarray, prior_flags: Sequence[bool]
) -> Tuple[np.ndarray, int]:
    """I2 — prior 유래 열을 제거한다.

    구현 대상: docs/c1_prereg_v1.md §8.1 I2
    해석 한계: 열을 전부 제거하면 설계가 비어 τ 가 미정의가 된다. 그 site 수를 보고한다.
    """
    matrix = np.asarray(design, dtype=float)
    keep = np.flatnonzero(~np.asarray(prior_flags, dtype=bool))
    if keep.size == 0:
        return np.zeros((matrix.shape[0], 0), dtype=float), int(matrix.shape[1])
    return matrix[:, keep], int(matrix.shape[1] - keep.size)


def augment_rank(design: np.ndarray, n_added: int, *, seed: int) -> np.ndarray:
    """I3 — 열공간에 직교하는 성분을 추가해 rank 를 올린다.

    구현 대상: docs/c1_prereg_v1.md §8.1 I3
    사전등록: 추가 열의 스케일은 기존 열의 평균 노름으로 맞춘다 — 스케일이 다르면 rank 는
              올라가도 정사영이 수치적으로 무의미해진다. seed 는 호출자가 넘긴다.
    해석 한계: 추가 열은 **합성**이며 어떤 kinase 도 나타내지 않는다. I3 의 τ 증가를
              "그 kinase 를 찾았다"로 읽지 않는다.
    """
    matrix = np.asarray(design, dtype=float)
    if n_added <= 0 or matrix.shape[0] == 0:
        return matrix

    projector, rank = column_space_projector(matrix)
    room = int(matrix.shape[0] - rank)
    if room <= 0:
        return matrix

    rng = np.random.default_rng(int(seed))
    scale = float(np.mean(np.linalg.norm(matrix, axis=0))) if matrix.shape[1] else 1.0
    identity = np.eye(matrix.shape[0])
    added: List[np.ndarray] = []
    for _ in range(min(int(n_added), room)):
        candidate = rng.standard_normal(matrix.shape[0])
        candidate = (identity - projector) @ candidate
        for existing in added:
            candidate = candidate - (candidate @ existing) / (existing @ existing) * existing
        norm = float(np.linalg.norm(candidate))
        if norm <= 1e-10:
            break
        added.append(candidate / norm * scale)

    if not added:
        return matrix
    return np.column_stack([matrix] + added)


def truncate_rank(design: np.ndarray, target_rank: int) -> np.ndarray:
    """I4 — 특이값을 절단해 rank 를 내린다.

    구현 대상: docs/c1_prereg_v1.md §8.1 I4
    해석 한계: 절단된 설계는 열 하나가 kinase 하나에 대응하지 않게 된다. I4 는 기하 민감도
              검정 전용이며 귀속 해석에 쓰지 않는다.
    """
    matrix = np.asarray(design, dtype=float)
    if matrix.size == 0 or target_rank <= 0:
        return np.zeros_like(matrix)
    left, values, right = np.linalg.svd(matrix, full_matrices=False)
    keep = min(int(target_rank), int(values.size))
    truncated = np.zeros_like(values)
    truncated[:keep] = values[:keep]
    return left @ np.diag(truncated) @ right


def provenance() -> Dict[str, Any]:
    """수치를 재현하려면 알아야 하는 상태. `.cursor/rules/research-code-provenance.mdc` §5."""
    from ptm_shared import tmm_identifiability

    record: Dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "numpy": np.__version__,
        "dtype": "float64",
        "nnls_path": "scipy.optimize.nnls"
        if getattr(tmm_identifiability, "_HAS_SCIPY", False)
        else "projected_gradient_fallback",
        "rank_rule": "tmm_identifiability._numerical_rank (sigma > sigma_0 * max(shape) * eps)",
        "baseline": BASELINE_ZERO_IMPUTED_TRAJECTORY,
        "d_norm_floor": D_NORM_FLOOR,
        "active_coefficient_floor": ACTIVE_COEFFICIENT_FLOOR,
        "active_instability_limit": ACTIVE_INSTABILITY_LIMIT,
    }
    try:
        import scipy

        record["scipy"] = scipy.__version__
    except Exception:
        record["scipy"] = None
    return record


__all__ = [
    "ACTIVE_INSTABILITY_LIMIT",
    "BASELINE_OBSERVED_ONLY",
    "BASELINE_ZERO_IMPUTED_TRAJECTORY",
    "CONTRACT_VERSION",
    "DUPLICATE_COHERENCE_LIMIT",
    "D_NORM_FLOOR",
    "STATUS_EVALUATED",
    "STATUS_NO_COLUMNS",
    "STATUS_ZERO_DIRECTION",
    "STATUS_ZERO_RANK",
    "SiteTransmissibility",
    "active_columns",
    "augment_rank",
    "column_space_projector",
    "downstream_response",
    "drop_prior_columns",
    "merge_duplicate_columns",
    "primary_tau_field",
    "provenance",
    "quantile_summary",
    "site_transmissibility",
    "summarize_by_stratum",
    "transmissibility",
    "truncate_rank",
]
