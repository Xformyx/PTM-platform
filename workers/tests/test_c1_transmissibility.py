"""Regression tests that lock C1 의 τ 수식·경계 규약·추론 상수.

구현 대상: docs/c1_prereg_v1.md §4 (τ), §6 (E1b), §7 (E3), §8 (E3b)
사전등록: 이 테스트는 판정 규칙을 **잠근다.** 사전등록 상수를 조용히 바꾸면 여기서 실패한다.
          `.cursor/rules/research-code-provenance.mdc` §2 가 요구하는 "측정 후 변경 금지"의
          기계적 집행 수단이다.
해석 한계: 수치 정확성만 검사한다. 생물학적 타당도나 τ 의 해석은 테스트 대상이 아니다.
주장 금지: 이 테스트가 통과한다고 τ 가 유효한 진단이라는 뜻이 아니다.

실행 (pytest 가 이미지에 없으므로 임시 설치가 필요하다 — chapter2_audit_protocol_v1.md §7 미결):

    docker exec ptm-worker-preprocessing pip install -q pytest
    docker exec -e PYTHONPATH=/app:/opt ptm-worker-preprocessing \
        python -m pytest /app/tests/test_c1_transmissibility.py -q
"""

from __future__ import annotations

import numpy as np
import pytest

from ptm_shared.c1_inference import (
    E1B_PREDICTORS,
    E3B_SIGN_AGREEMENT_MIN,
    E3B_SIGN_TEST_ALPHA,
    INFERENCE_SEED,
    MIN_BLOCKS_PER_GROUP,
    N_BOOTSTRAP,
    N_FOLDS,
    N_PERMUTATIONS,
    QUANTILE_HIGH,
    QUANTILE_LOW,
    RIDGE_PENALTY_GRID,
    exact_sign_test,
    fold_of,
    kendall_tau_b,
    normalized_inversion_fraction,
    run_e1b,
    run_e3,
    spearman,
)
from ptm_shared.c1_transmissibility import (
    ACTIVE_INSTABILITY_LIMIT,
    DUPLICATE_COHERENCE_LIMIT,
    D_NORM_FLOOR,
    STATUS_EVALUATED,
    STATUS_NO_COLUMNS,
    STATUS_ZERO_DIRECTION,
    STATUS_ZERO_RANK,
    active_columns,
    augment_rank,
    column_space_projector,
    downstream_response,
    drop_prior_columns,
    merge_duplicate_columns,
    primary_tau_field,
    quantile_summary,
    site_transmissibility,
    transmissibility,
    truncate_rank,
)


# ---------------------------------------------------------------------------
# 사전등록 상수 — 문서에 선언된 값과 코드가 일치하는지
# ---------------------------------------------------------------------------


def test_frozen_thresholds_match_the_preregistration() -> None:
    """docs/c1_prereg_v1.md 에 선언된 값. 바꾸려면 문서를 먼저 고쳐야 한다."""
    assert D_NORM_FLOOR == 1e-12  # §4.3
    assert ACTIVE_INSTABILITY_LIMIT == 0.30  # §4.2
    assert DUPLICATE_COHERENCE_LIMIT == 0.9999  # §8.1 I1
    assert N_FOLDS == 5  # §7.2
    assert RIDGE_PENALTY_GRID == (0.01, 0.1, 1.0, 10.0, 100.0)  # §6.3
    assert (QUANTILE_LOW, QUANTILE_HIGH) == (20.0, 80.0)  # §7.3
    assert MIN_BLOCKS_PER_GROUP == 5  # §7.2 저빈도 규칙
    assert N_PERMUTATIONS == 10_000 and N_BOOTSTRAP == 10_000  # §7.4, §7.3.1
    assert INFERENCE_SEED == 20260820  # §7.4
    assert E3B_SIGN_AGREEMENT_MIN == 0.80 and E3B_SIGN_TEST_ALPHA == 0.05  # §8.2
    assert len(E1B_PREDICTORS) == 6  # §6.2 — 성분을 빼거나 더하지 않는다


def test_fold_assignment_survives_process_restarts() -> None:
    """sha256 기반이므로 `PYTHONHASHSEED` 와 무관하게 같은 fold 가 나온다.

    공정 프로브에서 `hash()` 결정성 결함이 발견된 뒤 같은 실수를 막기 위한 잠금이다.
    """
    assert [fold_of(gene) for gene in ("LMNA", "SRRM2", "CAD", "AHNAK")] == [
        fold_of("lmna"),
        fold_of(" srrm2 "),
        fold_of("Cad"),
        fold_of("ahnak"),
    ]
    assert fold_of("LMNA") == 0
    assert fold_of("SRRM2") == 4
    assert fold_of("AHNAK") == 2
    assert all(0 <= fold_of(f"GENE{index}") < N_FOLDS for index in range(50))


# ---------------------------------------------------------------------------
# τ 수식 (§4.1)
# ---------------------------------------------------------------------------


def test_direction_inside_the_column_space_transmits_fully() -> None:
    design = np.array([[1.0, 0.0], [0.0, 1.0], [0.0, 0.0]])
    assert transmissibility(design, np.array([3.0, 4.0, 0.0])) == pytest.approx(1.0)


def test_direction_orthogonal_to_the_column_space_transmits_nothing() -> None:
    design = np.array([[1.0, 0.0], [0.0, 1.0], [0.0, 0.0]])
    assert transmissibility(design, np.array([0.0, 0.0, 5.0])) == pytest.approx(0.0)


def test_partially_aligned_direction_returns_the_energy_fraction() -> None:
    design = np.array([[1.0], [0.0]])
    value = transmissibility(design, np.array([1.0, 1.0]))
    assert value == pytest.approx(0.5)


def test_tau_col_is_never_below_tau_act() -> None:
    """활성집합 열공간은 전체 열공간의 부분공간이므로 τ_col >= τ_act 이다."""
    rng = np.random.default_rng(0)
    for _ in range(25):
        design = rng.standard_normal((5, 4))
        target = np.abs(rng.standard_normal(5))
        direction = rng.standard_normal(5)
        record = site_transmissibility("S", design, target, direction)
        if record.tau_act is None or record.tau_col is None:
            continue
        assert record.tau_col >= record.tau_act - 1e-9


def test_projector_rank_matches_the_shared_numerical_rank_rule() -> None:
    design = np.column_stack([np.array([1.0, 0.0, 0.0]), np.array([2.0, 0.0, 0.0])])
    projector, rank = column_space_projector(design)
    assert rank == 1
    assert projector @ np.array([1.0, 0.0, 0.0]) == pytest.approx(np.array([1.0, 0.0, 0.0]))


# ---------------------------------------------------------------------------
# 경계 규약 (§4.3)
# ---------------------------------------------------------------------------


def test_zero_direction_is_excluded_rather_than_scored_zero() -> None:
    design = np.array([[1.0, 0.0], [0.0, 1.0]])
    record = site_transmissibility("S", design, np.array([1.0, 1.0]), np.zeros(2))
    assert record.status == STATUS_ZERO_DIRECTION
    assert record.tau_act is None and record.tau_col is None


def test_empty_and_zero_rank_designs_are_excluded_with_distinct_labels() -> None:
    empty = site_transmissibility(
        "S", np.zeros((3, 0)), np.zeros(3), np.array([1.0, 0.0, 0.0])
    )
    assert empty.status == STATUS_NO_COLUMNS
    degenerate = site_transmissibility(
        "S", np.zeros((3, 2)), np.zeros(3), np.array([1.0, 0.0, 0.0])
    )
    assert degenerate.status == STATUS_ZERO_RANK


def test_tau_is_not_clipped_into_the_unit_interval() -> None:
    """§4.3 은 범위 밖 값을 수치 오류로 **보고**하라고 하고 clip 을 금지한다."""
    design = np.array([[1.0, 0.0], [0.0, 1.0]])
    record = site_transmissibility("S", design, np.array([1.0, 1.0]), np.array([1.0, 1.0]))
    assert record.tau_col == pytest.approx(1.0)
    assert record.tau_col <= 1.0 + 1e-9


def test_dead_site_reports_zero_active_transmissibility_not_none() -> None:
    """활성집합이 비면 τ_act = 0 이다. `constant-output-by-construction` (§7.5)."""
    design = np.array([[-1.0], [-1.0]])
    record = site_transmissibility("S", design, np.array([1.0, 1.0]), np.array([1.0, 0.0]))
    assert record.n_active == 0
    assert record.tau_act == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 활성집합·하류 응답 (§4.1, §7.4)
# ---------------------------------------------------------------------------


def test_active_columns_are_exactly_the_positive_nnls_coefficients() -> None:
    design = np.array([[1.0, 0.0], [0.0, 1.0]])
    assert active_columns(design, np.array([1.0, 0.0])).tolist() == [0]
    assert active_columns(design, np.array([1.0, 1.0])).tolist() == [0, 1]


def test_downstream_response_is_zero_for_a_zero_perturbation() -> None:
    design = np.array([[1.0, 0.0], [0.0, 1.0]])
    assert downstream_response(design, np.array([1.0, 2.0]), np.zeros(2)) == pytest.approx(0.0)


def test_downstream_response_is_a_total_variation_bounded_by_two() -> None:
    design = np.array([[1.0, 0.0], [0.0, 1.0]])
    value = downstream_response(design, np.array([1.0, 0.001]), np.array([-0.999, 0.999]))
    assert value is not None and 0.0 <= value <= 2.0 + 1e-9


def test_active_stability_flag_detects_a_support_change() -> None:
    design = np.array([[1.0, 0.0], [0.0, 1.0]])
    stable = site_transmissibility(
        "S", design, np.array([1.0, 1.0]), np.array([0.01, 0.01])
    )
    assert stable.active_stable is True
    flipped = site_transmissibility(
        "S", design, np.array([1.0, 1.0]), np.array([0.0, -2.0])
    )
    assert flipped.active_stable is False


def test_promotion_rule_switches_the_primary_field_above_the_frozen_limit() -> None:
    """§4.2 — 불안정 비율이 0.30 을 넘으면 primary 가 τ_col 로 바뀐다."""
    assert primary_tau_field(0.29) == "tau_act"
    assert primary_tau_field(0.30) == "tau_act"
    assert primary_tau_field(0.31) == "tau_col"
    assert primary_tau_field(None) == "tau_act"


# ---------------------------------------------------------------------------
# E3b 개입 (§8.1)
# ---------------------------------------------------------------------------


def test_merging_duplicate_columns_keeps_the_column_space_and_tau() -> None:
    column = np.array([1.0, 2.0, 3.0])
    design = np.column_stack([column, column * 2.0, np.array([0.0, 1.0, 0.0])])
    reduced, groups = merge_duplicate_columns(design)
    assert reduced.shape[1] == 2
    assert [len(group) for group in groups] == [2, 1]
    direction = np.array([1.0, 1.0, 1.0])
    assert transmissibility(reduced, direction) == pytest.approx(
        transmissibility(design, direction)
    )


def test_dropping_prior_columns_can_empty_the_design_and_reports_the_count() -> None:
    design = np.array([[1.0, 0.0], [0.0, 1.0]])
    reduced, n_dropped = drop_prior_columns(design, [True, False])
    assert reduced.shape[1] == 1 and n_dropped == 1
    emptied, n_all = drop_prior_columns(design, [True, True])
    assert emptied.shape[1] == 0 and n_all == 2


def test_rank_augmentation_raises_rank_and_cannot_lower_tau_col() -> None:
    design = np.array([[1.0], [0.0], [0.0]])
    direction = np.array([1.0, 1.0, 0.0])
    augmented = augment_rank(design, 1, seed=20260820)
    assert np.linalg.matrix_rank(augmented) == 2
    assert transmissibility(augmented, direction) >= transmissibility(design, direction)


def test_rank_augmentation_stops_at_the_ambient_dimension() -> None:
    design = np.eye(3)
    assert augment_rank(design, 5, seed=20260820).shape == (3, 3)


def test_rank_truncation_lowers_the_numerical_rank() -> None:
    design = np.diag([3.0, 2.0, 1.0])
    truncated = truncate_rank(design, 2)
    assert np.linalg.matrix_rank(truncated) == 2


def test_exact_sign_test_matches_known_binomial_tails() -> None:
    assert exact_sign_test(5, 5) == pytest.approx(2 / 32)
    assert exact_sign_test(0, 5) == pytest.approx(2 / 32)
    assert exact_sign_test(3, 6) == pytest.approx(1.0)
    assert exact_sign_test(1, 0) is None


# ---------------------------------------------------------------------------
# E1b 통계 (§6.3–6.5)
# ---------------------------------------------------------------------------


def test_normalized_inversion_fraction_is_zero_for_a_perfect_ranking() -> None:
    result = normalized_inversion_fraction([1.0, 2.0, 3.0], [10.0, 20.0, 30.0])
    assert result is not None and result["d_inv"] == pytest.approx(0.0)


def test_normalized_inversion_fraction_is_one_for_a_reversed_ranking() -> None:
    result = normalized_inversion_fraction([1.0, 2.0, 3.0], [30.0, 20.0, 10.0])
    assert result is not None and result["d_inv"] == pytest.approx(1.0)


def test_constant_prediction_gets_half_credit_on_every_pair() -> None:
    """§6.4 — 예측 동점은 half-credit 이다. 상수 예측기는 정확히 0.5 가 된다."""
    result = normalized_inversion_fraction([1.0, 2.0, 3.0], [7.0, 7.0, 7.0])
    assert result is not None and result["d_inv"] == pytest.approx(0.5)


def test_kendall_tau_b_is_one_for_a_perfect_ranking() -> None:
    assert kendall_tau_b([1.0, 2.0, 3.0], [5.0, 6.0, 7.0]) == pytest.approx(1.0)


def test_spearman_handles_ties_with_average_ranks() -> None:
    assert spearman([1.0, 1.0, 2.0, 3.0], [1.0, 1.0, 2.0, 3.0]) == pytest.approx(1.0)
    assert spearman([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None


def test_e1b_reports_no_p_value_by_construction() -> None:
    """§6.5 — E1b 는 p-value 를 산출하지 않는다. 필드가 없어야 한다."""
    rng = np.random.default_rng(1)
    records = [
        {
            "gene": f"GENE{index % 17}",
            "tau_act": float(rng.random()),
            "design_condition_number": float(10 ** rng.uniform(0, 4)),
            "active_condition_number": float(10 ** rng.uniform(0, 2)),
            "active_sigma_min": float(rng.random()),
            "max_column_coherence": float(rng.random()),
            "design_rank": int(rng.integers(2, 6)),
            "n_redundant": int(rng.integers(0, 3)),
        }
        for index in range(80)
    ]
    result = run_e1b(records)
    assert result["status"] == "measured"
    assert not any("p_value" in key or key.endswith("_p") for key in result)
    assert result["oof_spearman_ci95"] is not None


def test_e1b_drops_nonfinite_predictor_rows_and_reports_the_count() -> None:
    rng = np.random.default_rng(2)
    records = [
        {
            "gene": f"GENE{index % 15}",
            "tau_act": float(rng.random()),
            "design_condition_number": float("inf") if index == 0 else 10.0,
            "active_condition_number": 5.0,
            "active_sigma_min": 0.5,
            "max_column_coherence": 0.4,
            "design_rank": 3,
            "n_redundant": 1,
        }
        for index in range(60)
    ]
    result = run_e1b(records)
    assert result["n_dropped_nonfinite"] == 1


# ---------------------------------------------------------------------------
# E3 저빈도 규칙 (§7.2)
# ---------------------------------------------------------------------------


def test_e3_declares_non_evaluable_instead_of_reshuffling_the_split() -> None:
    """§7.2 는 대체 분할 탐색을 **핵심 금지 사항**으로 적었다. 부족하면 미평가로 끝난다."""
    records = [
        {
            "gene": f"GENE{index}",
            "tau_act": float(index),
            "downstream_response": float(index) * 0.1,
        }
        for index in range(12)
    ]
    result = run_e3(records, tau_field="tau_act")
    assert result["status"] in {"non_evaluable", "measured_exploratory"}
    if result["status"] == "non_evaluable":
        assert result["n_high_blocks"] < MIN_BLOCKS_PER_GROUP or (
            result["n_low_blocks"] < MIN_BLOCKS_PER_GROUP
        )


def test_e3_result_never_carries_a_pass_fail_label() -> None:
    """§3.5.2 — 탐색적 E3 는 통과/실패 라벨을 붙이지 않는다."""
    rng = np.random.default_rng(3)
    records = [
        {
            "gene": f"GENE{index}",
            "tau_act": float(rng.random()),
            "downstream_response": float(rng.random()),
        }
        for index in range(400)
    ]
    result = run_e3(records, tau_field="tau_act")
    assert "passes" not in result and "verdict" not in result
    assert "탐색적" in result["note"] or "미평가" in result["note"]


def test_e3_uses_median_block_aggregation() -> None:
    """§7.3.1 — 블록 집계는 median 이며 대안을 탐색하지 않는다."""
    records = [
        {"gene": "G", "tau_act": 0.0, "downstream_response": 0.0},
        {"gene": "G", "tau_act": 1.0, "downstream_response": 100.0},
        {"gene": "G", "tau_act": 0.5, "downstream_response": 1.0},
    ] + [
        {
            "gene": f"H{index}",
            "tau_act": float(index) / 40.0,
            "downstream_response": float(index),
        }
        for index in range(40)
    ]
    result = run_e3(records, tau_field="tau_act")
    assert result["aggregation"].startswith("median")


# ---------------------------------------------------------------------------
# 요약 통계 (§5.2)
# ---------------------------------------------------------------------------


def test_quantile_summary_marks_the_mean_as_not_primary() -> None:
    """§5.2 — 평균은 primary 가 아니다. 필드 이름이 그것을 강제한다."""
    summary = quantile_summary([0.0, 0.5, 1.0, None])
    assert summary["n"] == 3
    assert summary["p50"] == pytest.approx(0.5)
    assert "mean_not_primary" in summary


def test_quantile_summary_survives_an_all_missing_input() -> None:
    summary = quantile_summary([None, float("nan")])
    assert summary["n"] == 0 and summary["p50"] is None


def test_site_record_exposes_every_field_the_preregistration_lists() -> None:
    """§5.1 이 나열한 site 레코드 필드가 존재하는지."""
    design = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
    record = site_transmissibility(
        "GENE_S1",
        design,
        np.array([1.0, 1.0, 2.0]),
        np.array([0.1, 0.0, 0.0]),
        observed_mask=[True, True, False],
        prior_flags=[True, False],
        gene="GENE",
    ).to_dict()
    for field in (
        "tau_act",
        "tau_col",
        "tau_dd",
        "active_stable",
        "n_active",
        "active_rank",
        "design_rank",
        "d_norm",
        "y_norm",
        "n_timepoints",
        "n_candidates",
        "downstream_response",
    ):
        assert field in record
    assert record["status"] == STATUS_EVALUATED
    assert record["tau_dd"] is not None  # 데이터 유래 열이 활성이면 τ_dd 가 정의된다
