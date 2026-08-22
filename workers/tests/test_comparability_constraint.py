"""C3 비교가능성 제약 대조 항의 회귀 테스트.

정본 환경에서 실행:

    docker exec ptm-worker-preprocessing python -m pytest tests/test_comparability_constraint.py -q

이 파일이 잠그는 것은 두 가지다.

1. **기울기가 손실의 실제 기울기인가** — 유한차분 대조. 해석적 기울기가 틀리면 학습은
   조용히 다른 목적함수를 최적화하고, 그 결과로 나온 E9 판정은 무의미하다.
2. **제약이 선언된 의미를 갖는가** — `O_ij = 0` 쌍에 대해 항이 아무 방향도 주지 않는다는
   것(docs/c3_prereg_v1.md §1.1·§6.1)과, 기본값이 꺼져 있어 기존 수치가 보존된다는 것.

테스트 통과는 **지표의 타당성이나 방법의 성공을 뜻하지 않는다.**
"""

import numpy as np
import pytest

from ptm_shared.representation.comparability import comparability_matrix
from ptm_shared.representation.comparability_constraint import (
    CONSTRAINT_LAMBDA_PRIMARY,
    CONSTRAINT_NEIGHBORS,
    CONSTRAINT_TEMPERATURE,
    EMPTY_POSITIVE_ROW_MAX,
    MODE_CONSTRAINED,
    MODE_UNCONSTRAINED,
    ComparabilityContrastive,
    describe,
    observed_distance_matrix,
    positive_mask,
)


def _trajectories(n_per_shape: int = 6, n_timepoints: int = 6, seed: int = 0):
    """두 개의 뚜렷한 모양 + 잡음. 양성이 모양 안에서 잡히도록 만든 입력."""
    rng = np.random.default_rng(seed)
    time = np.linspace(0.0, 1.0, n_timepoints)
    rising = np.tile(time, (n_per_shape, 1))
    falling = np.tile(1.0 - time, (n_per_shape, 1))
    values = np.vstack([rising, falling]) + rng.normal(scale=0.02, size=(2 * n_per_shape, n_timepoints))
    observed = np.ones_like(values, dtype=bool)
    return values, observed


# ---------------------------------------------------------------------------
# 관측 거리
# ---------------------------------------------------------------------------


def test_observed_distance_uses_only_shared_timepoints():
    values = np.array([[0.0, 10.0, 0.0], [0.0, -10.0, 0.0]])
    observed = np.array([[True, False, True], [True, False, True]])
    # The only disagreeing timepoint is unobserved in both rows, so it must not count.
    distance = observed_distance_matrix(values, observed)
    assert distance[0, 1] == pytest.approx(0.0)


def test_observed_distance_is_infinite_without_shared_timepoints():
    values = np.zeros((2, 4))
    observed = np.array([[True, True, False, False], [False, False, True, True]])
    assert np.isinf(observed_distance_matrix(values, observed)[0, 1])


def test_observed_distance_is_symmetric_with_an_infinite_diagonal():
    values, observed = _trajectories()
    distance = observed_distance_matrix(values, observed)
    finite = np.isfinite(distance)
    assert np.allclose(distance[finite], distance.T[finite])
    assert np.all(np.isinf(np.diag(distance)))


def test_observed_distance_matches_a_direct_pairwise_computation():
    rng = np.random.default_rng(3)
    values = rng.normal(size=(7, 5))
    observed = rng.random((7, 5)) > 0.3
    distance = observed_distance_matrix(values, observed)
    for i in range(7):
        for j in range(i + 1, 7):
            shared = observed[i] & observed[j]
            if not shared.any():
                assert np.isinf(distance[i, j])
                continue
            expected = np.sqrt(np.mean((values[i, shared] - values[j, shared]) ** 2))
            assert distance[i, j] == pytest.approx(expected, abs=1e-9)


# ---------------------------------------------------------------------------
# 양성 선택
# ---------------------------------------------------------------------------


def test_positives_are_the_nearest_candidates_only():
    distance = np.array(
        [
            [np.inf, 1.0, 2.0, 3.0],
            [1.0, np.inf, 5.0, 6.0],
            [2.0, 5.0, np.inf, 0.5],
            [3.0, 6.0, 0.5, np.inf],
        ]
    )
    candidate = ~np.eye(4, dtype=bool)
    positives = positive_mask(distance, candidate, 1)
    assert positives[0].tolist() == [False, True, False, False]
    assert positives[2].tolist() == [False, False, False, True]


def test_positives_never_include_an_infinite_distance():
    distance = np.full((3, 3), np.inf)
    distance[0, 1] = distance[1, 0] = 2.0
    positives = positive_mask(distance, ~np.eye(3, dtype=bool), 2)
    # Row 2 shares nothing with anyone, so it gets no positives at all.
    assert positives[2].sum() == 0
    assert positives[0].sum() == 1


def test_positives_respect_the_candidate_restriction():
    values, observed = _trajectories()
    distance = observed_distance_matrix(values, observed)
    candidate = ~np.eye(distance.shape[0], dtype=bool)
    restricted = candidate.copy()
    restricted[0, 1] = restricted[1, 0] = False
    assert positive_mask(distance, candidate, 11)[0, 1]
    assert not positive_mask(distance, restricted, 11)[0, 1]


# ---------------------------------------------------------------------------
# 기울기 — 이 절이 이 파일의 핵심
# ---------------------------------------------------------------------------


def _finite_difference(term: ComparabilityContrastive, latent: np.ndarray, step: float = 1e-6):
    numeric = np.zeros_like(latent)
    for row in range(latent.shape[0]):
        for column in range(latent.shape[1]):
            forward = latent.copy()
            backward = latent.copy()
            forward[row, column] += step
            backward[row, column] -= step
            high, _, _ = term.loss_and_latent_gradient(forward)
            low, _, _ = term.loss_and_latent_gradient(backward)
            numeric[row, column] = (high - low) / (2.0 * step)
    return numeric


@pytest.mark.parametrize("mode", [MODE_UNCONSTRAINED, MODE_CONSTRAINED])
def test_analytic_gradient_matches_finite_differences(mode):
    """해석적 기울기가 틀리면 학습은 다른 목적함수를 최적화한다.

    E9 의 primary 대조가 성립하기 위한 최소 조건이므로 두 모드 모두 검사한다.
    """
    values, observed = _trajectories(n_per_shape=5, seed=1)
    observed[0, 3] = observed[1, 4] = observed[2, 0] = False
    comparable = comparability_matrix(observed, 4)
    term = ComparabilityContrastive(
        values,
        observed,
        comparability=comparable if mode == MODE_CONSTRAINED else None,
        mode=mode,
        n_positives=3,
    )
    rng = np.random.default_rng(11)
    latent = rng.normal(size=(values.shape[0], 4))

    _, _, analytic = term.loss_and_latent_gradient(latent)
    numeric = _finite_difference(term, latent)

    assert np.max(np.abs(analytic - numeric)) < 1e-7
    assert np.linalg.norm(analytic) > 0.0


def test_gradient_is_orthogonal_to_the_latent_rows():
    """손실은 방향에만 의존하므로 반경 방향 성분이 0 이어야 한다.

    행 정규화 야코비안 `(I − u uᵀ)/‖z‖` 를 빠뜨리면 이 검사가 실패한다.
    """
    values, observed = _trajectories(seed=2)
    term = ComparabilityContrastive(values, observed, mode=MODE_UNCONSTRAINED, n_positives=3)
    rng = np.random.default_rng(5)
    latent = rng.normal(size=(values.shape[0], 3))

    _, _, gradient = term.loss_and_latent_gradient(latent)

    assert np.max(np.abs(np.sum(gradient * latent, axis=1))) < 1e-9


def test_loss_is_scale_invariant_in_the_latent():
    values, observed = _trajectories(seed=4)
    term = ComparabilityContrastive(values, observed, mode=MODE_UNCONSTRAINED, n_positives=3)
    rng = np.random.default_rng(6)
    latent = rng.normal(size=(values.shape[0], 3))

    base, _, _ = term.loss_and_latent_gradient(latent)
    scaled, _, _ = term.loss_and_latent_gradient(latent * 7.0)

    assert scaled == pytest.approx(base, abs=1e-10)


def test_loss_falls_when_positives_are_pulled_together():
    """손실이 겨냥하는 방향을 실제로 겨냥하는가."""
    values, observed = _trajectories(n_per_shape=8, seed=7)
    term = ComparabilityContrastive(values, observed, mode=MODE_UNCONSTRAINED, n_positives=4)
    rng = np.random.default_rng(8)
    random_latent = rng.normal(size=(values.shape[0], 3))
    # An embedding that already encodes the two shapes should score better than noise.
    shape_latent = np.zeros((values.shape[0], 3))
    shape_latent[:8, 0] = 1.0
    shape_latent[8:, 1] = 1.0

    aligned, _, _ = term.loss_and_latent_gradient(shape_latent)
    noisy, _, _ = term.loss_and_latent_gradient(random_latent)

    assert aligned < noisy


# ---------------------------------------------------------------------------
# 제약의 의미
# ---------------------------------------------------------------------------


def test_constraint_gives_no_direction_to_non_comparable_pairs():
    """docs/c3_prereg_v1.md §1.1 — 증거 부재는 비유사성의 증거가 아니다.

    제약 모드에서 비교 불가 쌍은 양성에서도 후보에서도 빠지므로, 그 쌍만 움직이는 섭동이
    손실을 바꾸면 안 된다. 벌점형(M2)을 잘못 구현하면 이 검사가 실패한다.
    """
    values, observed = _trajectories(n_per_shape=5, seed=9)
    # Make rows 0 and 1 non-comparable with everything else, but comparable to each other.
    observed[:] = True
    observed[0, 2:] = False
    observed[1, 2:] = False
    comparable = comparability_matrix(observed, 4)
    assert not comparable[0, 5]

    term = ComparabilityContrastive(
        values, observed, comparability=comparable, mode=MODE_CONSTRAINED, n_positives=2
    )
    assert not term.candidate[0, 5]
    assert not term.positives[0, 5]


def test_unconstrained_mode_keeps_the_pairs_the_constraint_removes():
    values, observed = _trajectories(n_per_shape=5, seed=9)
    observed[:] = True
    observed[0, 2:] = False
    comparable = comparability_matrix(observed, 4)

    constrained = ComparabilityContrastive(
        values, observed, comparability=comparable, mode=MODE_CONSTRAINED, n_positives=2
    )
    unconstrained = ComparabilityContrastive(
        values, observed, mode=MODE_UNCONSTRAINED, n_positives=2
    )

    assert unconstrained.candidate.sum() > constrained.candidate.sum()
    removed = unconstrained.provenance()["n_candidate_pairs_removed_by_constraint"]
    assert removed == 0
    assert constrained.provenance()["n_candidate_pairs_removed_by_constraint"] > 0


def test_constrained_mode_requires_a_comparability_matrix():
    values, observed = _trajectories()
    with pytest.raises(ValueError, match="comparability"):
        ComparabilityContrastive(values, observed, mode=MODE_CONSTRAINED)


def test_unknown_mode_is_rejected_rather_than_silently_treated_as_a_baseline():
    values, observed = _trajectories()
    with pytest.raises(ValueError, match="mode"):
        ComparabilityContrastive(values, observed, mode="whatever")


def test_rows_left_without_positives_are_reported_not_hidden():
    """S2 자명성 검사의 입력. 제약이 손실을 비우면 그것은 데이터 삭제다 (§6.3.2)."""
    values = np.zeros((4, 6))
    observed = np.zeros((4, 6), dtype=bool)
    observed[0, :3] = True
    observed[1, 3:] = True
    observed[2, :3] = True
    observed[3, 3:] = True
    comparable = comparability_matrix(observed, 3)
    term = ComparabilityContrastive(
        values, observed, comparability=comparable, mode=MODE_CONSTRAINED, n_positives=2
    )

    check = term.triviality_check()
    # Each row has exactly one comparable partner, which is also its only candidate, so
    # -log(A/B) is identically zero and the row cannot inform the loss.
    assert check["n_valid_rows"] == 0
    loss, detail, gradient = term.loss_and_latent_gradient(np.eye(4, 3))
    assert loss == 0.0
    assert detail["n_valid_rows"] == 0
    assert not gradient.any()


# ---------------------------------------------------------------------------
# 동결된 선언값
# ---------------------------------------------------------------------------


def test_declared_hyperparameters_hold_their_documented_values():
    """docs/c3_prereg_v1.md §6.3.1. 문서를 고치지 않고 코드만 바꾸면 여기서 실패한다."""
    assert CONSTRAINT_TEMPERATURE == 0.5
    assert CONSTRAINT_NEIGHBORS == 10
    assert CONSTRAINT_LAMBDA_PRIMARY == 1.0
    assert EMPTY_POSITIVE_ROW_MAX == 0.20


def test_contract_summary_names_the_mechanism_and_its_declaration():
    summary = describe()
    assert summary["functional_form"] == "infonce_cosine"
    assert summary["mechanism"] == "M1_masking"
    assert summary["modes"] == [MODE_UNCONSTRAINED, MODE_CONSTRAINED]
    assert summary["declaration"] == "docs/c3_prereg_v1.md §6.3"


# ---------------------------------------------------------------------------
# 인코더 배선
# ---------------------------------------------------------------------------


TIMEPOINTS = ["1min", "2.5min", "5min", "15min", "30min", "60min"]
SHAPES = {"early": [1.8, 2.4, 2.0, 0.9, 0.3, 0.1], "late": [0.1, 0.2, 0.5, 1.4, 2.3, 2.6]}


def _multiview(n_per_shape: int = 12, seed: int = 0):
    """`test_representation_fair_probe.py` 와 같은 L1 행 형식. 두 모양이 분리 가능하다."""
    from ptm_shared.representation import build_multiview_input

    rng = np.random.default_rng(seed)
    rows = []
    site_index = 0
    for shape, base in SHAPES.items():
        for member in range(n_per_shape):
            jitter = rng.normal(0.0, 0.15, size=len(TIMEPOINTS))
            profile = [value + float(shift) for value, shift in zip(base, jitter)]
            for time_index, timepoint in enumerate(TIMEPOINTS):
                rows.append(
                    {
                        "Protein.Group": f"P{site_index:05d}",
                        "Gene.Name": f"{shape.upper()}{member}",
                        "PTM_Position": "S100",
                        "Modified.Sequence": f"AAA{shape[0].upper()}{member}TSK",
                        "PTM_Type": "Phosphorylation",
                        "Condition": timepoint,
                        "Comparison": f"{timepoint}_vs_Control",
                        "PTM_Relative_Log2FC": profile[time_index],
                        "Protein_Log2FC": 0.1 * profile[time_index],
                        "q_value": 0.01,
                        "p_value": 0.005,
                        "Quantification_Track": "protein_normalized_relative_ptm",
                        "Occupancy_Logit_Delta": float("nan"),
                        "Pair_Quality_Tier": "O0",
                        "Pair_Missingness": 0.0,
                    }
                )
            site_index += 1
    return build_multiview_input(rows)


_FAST_ENCODER = {"latent_dim": 4, "hidden_dim": 8, "epochs": 12, "seed": 0, "n_perturbations": 0}


def test_encoder_default_keeps_the_constraint_off():
    """기본값이 꺼짐이어야 기존 arm·gate 수치가 보존된다."""
    from ptm_shared.representation import DEFAULT_ENCODER_CONFIG

    assert DEFAULT_ENCODER_CONFIG["use_comparability_constraint"] is False
    assert DEFAULT_ENCODER_CONFIG["comparability_lambda"] == 0.0
    assert DEFAULT_ENCODER_CONFIG["comparability_mode"] == MODE_CONSTRAINED
    assert DEFAULT_ENCODER_CONFIG["comparability_neighbors"] == CONSTRAINT_NEIGHBORS
    assert DEFAULT_ENCODER_CONFIG["comparability_temperature"] == CONSTRAINT_TEMPERATURE
    assert DEFAULT_ENCODER_CONFIG["comparability_t_min"] == 4


def test_lambda_zero_reproduces_the_term_free_fit_exactly():
    """docs/c3_prereg_v1.md §6.2 기준선 0 대조.

    λ = 0 이 항 없는 적합과 **비트 단위로** 같아야, 기준선 0 과 기준선 1 의 차이를 "대조 항을
    추가한 효과"로 읽을 수 있다. 조금이라도 다르면 그 차이에 배선 부작용이 섞인다.
    """
    from ptm_shared.representation import fit_masked_temporal_encoder

    multiview = _multiview()
    without = fit_masked_temporal_encoder(multiview, config=_FAST_ENCODER)
    with_zero = fit_masked_temporal_encoder(
        multiview,
        config={
            **_FAST_ENCODER,
            "use_comparability_constraint": True,
            "comparability_lambda": 0.0,
            "comparability_mode": MODE_UNCONSTRAINED,
        },
    )

    assert np.array_equal(without.embedding, with_zero.embedding)


def test_positive_lambda_changes_the_embedding():
    """λ > 0 이 아무것도 바꾸지 않으면 E9 의 대조가 공허하다 (§6.3.2 S1 의 동기)."""
    from ptm_shared.representation import fit_masked_temporal_encoder

    multiview = _multiview()
    without = fit_masked_temporal_encoder(multiview, config=_FAST_ENCODER)
    with_term = fit_masked_temporal_encoder(
        multiview,
        config={
            **_FAST_ENCODER,
            "use_comparability_constraint": True,
            "comparability_lambda": 1.0,
            "comparability_mode": MODE_UNCONSTRAINED,
        },
    )

    assert not np.allclose(without.embedding, with_term.embedding)


def test_provenance_records_the_constraint_and_its_mask_source():
    from ptm_shared.representation import fit_masked_temporal_encoder

    multiview = _multiview()
    stratum = multiview.target.observed.copy()
    stratum[0, 0] = False
    result = fit_masked_temporal_encoder(
        multiview,
        config={
            **_FAST_ENCODER,
            "use_comparability_constraint": True,
            "comparability_lambda": 1.0,
            "comparability_mask": stratum,
        },
    )

    record = result.provenance["comparability_constraint"]
    assert record["mode"] == MODE_CONSTRAINED
    assert record["lambda"] == 1.0
    assert record["t_min"] == 4
    assert record["mask_source"] == "supplied_stratum"
    assert record["declaration"] == "docs/c3_prereg_v1.md §6.3"
    assert "empty_positive_fraction" in record


def test_supplied_mask_is_digested_not_stringified_into_the_config():
    """마스크를 `str()` 로 넣으면 잘려서 서로 다른 마스크가 같은 해시를 갖는다."""
    from ptm_shared.representation import fit_masked_temporal_encoder

    multiview = _multiview()
    first = multiview.target.observed.copy()
    second = multiview.target.observed.copy()
    second[3, 2] = not second[3, 2]

    digests = []
    for mask in (first, second):
        result = fit_masked_temporal_encoder(
            multiview,
            config={
                **_FAST_ENCODER,
                "use_comparability_constraint": True,
                "comparability_lambda": 1.0,
                "comparability_mask": mask,
            },
        )
        assert "comparability_mask" not in result.provenance["config"]
        digests.append(result.provenance["config"]["comparability_mask_sha256"])

    assert digests[0] != digests[1]


def test_training_history_reports_the_contrastive_loss():
    from ptm_shared.representation import fit_masked_temporal_encoder

    result = fit_masked_temporal_encoder(
        _multiview(),
        config={
            **_FAST_ENCODER,
            "use_comparability_constraint": True,
            "comparability_lambda": 1.0,
            "comparability_mode": MODE_UNCONSTRAINED,
        },
    )

    assert all("contrastive_loss" in entry for entry in result.training_history)
    assert result.training_history[0]["n_valid_rows"] > 0


def test_negative_lambda_is_clamped_rather_than_reversing_the_term():
    """음수 λ 는 관측상 가까운 쌍을 밀어내는 항이 되고 §6.3 이 정의한 것이 아니다."""
    from ptm_shared.representation.encoder import _merged_config

    assert _merged_config({"comparability_lambda": -3.0})["comparability_lambda"] == 0.0
