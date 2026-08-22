"""C3 비교가능성 관계와 pair 지표의 회귀 테스트.

정본 환경에서 실행:

    docker exec ptm-worker-preprocessing python -m pytest tests/test_comparability.py -q

이 파일이 잠그는 것은 **정의**다. docs/c3_prereg_v1.md 를 고치지 않고 코드만 바꾸면
실패하도록 사전등록 규약(§3.3 미배정 규약, §4.1 primary 지표, §4.2 미정의 처리)을 상수로
고정한다. 테스트 통과가 지표의 타당성을 뜻하지는 않는다.
"""

import numpy as np
import pytest

from ptm_shared.representation.comparability import (
    comparability_matrix,
    describe,
    distance_rank_agreement,
    false_merge,
    kish_n_eff,
    pair_restricted_ari,
    removal_precision,
    same_cluster_matrix,
    subspace_alignment,
    upper_triangle,
)


def test_comparability_counts_shared_observed_timepoints():
    observed = np.array(
        [
            [1, 1, 1, 1, 0, 0],
            [1, 1, 1, 1, 0, 0],
            [0, 0, 1, 1, 1, 1],
        ],
        dtype=bool,
    )
    at_four = comparability_matrix(observed, 4)
    assert at_four[0, 1] and at_four[1, 0]
    # rows 0 and 2 share only timepoints 2 and 3.
    assert not at_four[0, 2]
    assert comparability_matrix(observed, 2)[0, 2]


def test_comparability_is_symmetric_and_reflexive_but_not_transitive():
    observed = np.array(
        [
            [1, 1, 1, 1, 0, 0],
            [0, 1, 1, 1, 1, 0],
            [0, 0, 1, 1, 1, 1],
        ],
        dtype=bool,
    )
    matrix = comparability_matrix(observed, 3)
    assert np.array_equal(matrix, matrix.T)
    assert matrix.diagonal().all()
    # 0-1 and 1-2 comparable, 0-2 not: the relation is not an equivalence, so the
    # constraint cannot be implemented as a partition (c3_prereg_v1.md §2.1).
    assert matrix[0, 1] and matrix[1, 2] and not matrix[0, 2]


def test_comparability_rejects_a_meaningless_threshold():
    with pytest.raises(ValueError):
        comparability_matrix(np.ones((3, 3), dtype=bool), 0)


def test_unassigned_points_are_not_merged_with_each_other():
    # docs/c3_prereg_v1.md §3.3.  Without this convention, raising the unassigned
    # count alone would make merged pairs explode.
    labels = np.array([0, 0, 1, 1])
    same = same_cluster_matrix(labels)
    assert not same[0, 1]
    assert same[2, 3]


def test_upper_triangle_excludes_self_pairs():
    matrix = np.arange(9).reshape(3, 3)
    assert upper_triangle(matrix).tolist() == [1, 2, 5]


def test_false_merge_precision_is_over_merged_pairs():
    labels = np.array([1, 1, 1])
    comparable = np.array(
        [
            [True, True, False],
            [True, True, True],
            [False, True, True],
        ]
    )
    result = false_merge(labels, comparable)
    assert result["n_merged_pairs"] == 3
    assert result["n_non_comparable_pairs"] == 1
    assert result["n_false_merges"] == 1
    assert result["fm_precision"] == pytest.approx(1 / 3)
    assert result["fm_exposure"] == pytest.approx(1.0)


def test_undefined_false_merge_rates_stay_none():
    # docs/c3_prereg_v1.md §4.2.  Filling 0.0 would read as "improved".
    singletons = false_merge(np.zeros(3, dtype=int), np.ones((3, 3), dtype=bool))
    assert singletons["n_merged_pairs"] == 0
    assert singletons["fm_precision"] is None
    assert singletons["fm_exposure"] is None


def test_splitting_every_cluster_makes_precision_undefined_not_zero():
    # The trivial-success path §5.1 warns about: it must not read as a perfect score.
    comparable = np.zeros((4, 4), dtype=bool)
    np.fill_diagonal(comparable, True)
    assert false_merge(np.zeros(4, dtype=int), comparable)["fm_precision"] is None


def test_removal_precision_compares_against_random_removal():
    baseline = {"n_merged_pairs": 1000, "n_false_merges": 100, "fm_precision": 0.1}
    targeted = {"n_merged_pairs": 900, "n_false_merges": 20}
    result = removal_precision(baseline, targeted)
    assert result["status"] == "evaluated"
    assert result["delta_merged_pairs"] == 100
    assert result["delta_false_merges"] == 80
    assert result["removal_precision"] == pytest.approx(0.8)
    # Random removal would have removed false merges at the baseline rate.
    assert result["random_removal_expectation"] == 0.1


def test_removal_precision_reports_no_shrinkage_instead_of_dividing_by_zero():
    baseline = {"n_merged_pairs": 1000, "n_false_merges": 100, "fm_precision": 0.1}
    unchanged = {"n_merged_pairs": 1000, "n_false_merges": 60}
    result = removal_precision(baseline, unchanged)
    assert result["status"] == "no_shrinkage"
    assert result["removal_precision"] is None


def test_pair_restricted_ari_is_one_for_identical_labels():
    labels = np.array([1, 1, 2, 2, 3])
    assert pair_restricted_ari(labels, labels) == pytest.approx(1.0)


def test_pair_restricted_ari_ignores_disagreement_outside_the_mask():
    # The point of restricting to comparable pairs (§5.2 G1): a disagreement that
    # only lives on excluded pairs must not count as structure loss.
    left = np.array([1, 1, 2, 2, 3, 3])
    right = np.array([1, 1, 2, 2, 1, 1])
    mask = np.ones((6, 6), dtype=bool)
    for row in (0, 1):
        for column in (4, 5):
            mask[row, column] = mask[column, row] = False
    assert pair_restricted_ari(left, right) == pytest.approx(0.444444, abs=1e-6)
    assert pair_restricted_ari(left, right, mask) == pytest.approx(1.0)


def test_pair_restricted_ari_returns_none_when_the_table_is_degenerate():
    # Two pairs that are both same-cluster in both labelings leave no variation.
    left = np.array([1, 1, 2, 2])
    right = np.array([1, 1, 1, 1])
    mask = np.zeros((4, 4), dtype=bool)
    for row, column in ((0, 1), (2, 3)):
        mask[row, column] = mask[column, row] = True
    assert pair_restricted_ari(left, right, mask) is None


def test_subspace_alignment_is_rotation_invariant():
    rng = np.random.default_rng(0)
    base = rng.normal(size=(40, 4))
    rotation, _ = np.linalg.qr(rng.normal(size=(4, 4)))
    assert subspace_alignment(base, base @ rotation) == pytest.approx(1.0, abs=1e-8)


def test_subspace_alignment_is_small_for_unrelated_subspaces():
    rng = np.random.default_rng(1)
    left = rng.normal(size=(400, 3))
    right = rng.normal(size=(400, 3))
    value = subspace_alignment(left, right)
    assert value is not None and value < 0.05


def test_distance_rank_agreement_is_one_for_a_rescaled_copy():
    rng = np.random.default_rng(2)
    embedding = rng.normal(size=(30, 5))
    mask = np.ones((30, 30), dtype=bool)
    agreement = distance_rank_agreement(embedding, embedding * 3.0, mask)
    assert agreement == pytest.approx(1.0, abs=1e-8)


def test_kish_n_eff_equals_cluster_count_for_equal_degrees():
    assert kish_n_eff(np.array([5, 5, 5, 5]))["n_eff"] == pytest.approx(4.0)


def test_kish_n_eff_shrinks_when_one_cluster_dominates():
    stats = kish_n_eff(np.array([100, 1, 1, 1]))
    assert stats["n_eff"] < 2.0
    assert stats["n_features_with_edges"] == 4


def test_kish_n_eff_handles_an_empty_graph():
    stats = kish_n_eff(np.zeros(5))
    assert stats["n_eff"] is None
    assert stats["n_features_with_edges"] == 0


def test_contract_summary_names_the_primary_metric_and_the_rejected_guard():
    summary = describe()
    assert summary["primary_metric"] == "fm_precision"
    assert summary["secondary_metric"] == "fm_exposure"
    # Rejected because its arm-D seed-to-seed floor was 0.0025-0.0056 (§12.4).
    assert summary["rejected_guard"] == "distance_rank_agreement"
    assert "removal_precision" in summary["triviality_guards"]
    assert summary["declaration"] == "docs/c3_prereg_v1.md"
