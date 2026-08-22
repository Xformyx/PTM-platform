"""Contract tests for the held-out timepoint fair probe (R1.6).

The probe exists because the R1.5 metrics cannot rank arms against each other:
``raw_evidence_concordance`` is won by construction by the arm whose embedding is
the raw trajectory, and unadjusted ``missingness_r2`` grows with dimensionality.
These tests fix the properties that make the probe a fair comparison instead.

Run from the repository root:

    python -m pytest workers/tests/test_representation_fair_probe.py -v
"""

import json

import numpy as np
import pytest

from ptm_shared.representation import build_multiview_input, handcrafted_representation
from ptm_shared.representation.fair_probe import (
    _arm_seed_component,
    _sign_flip_p_value,
    compare_to_baseline,
    run_heldout_timepoint_probe,
)

TIMEPOINTS = ["1min", "2.5min", "5min", "15min", "30min", "60min"]
SHAPES = {
    "early": [1.8, 2.4, 2.0, 0.9, 0.3, 0.1],
    "late": [0.1, 0.2, 0.5, 1.4, 2.3, 2.6],
    "down": [-0.4, -0.9, -1.6, -2.1, -1.8, -1.2],
}

FAST_CONFIG = {
    "arms": ("A", "B"),
    "baseline_arm": "B",
    "n_encoder_seeds": 1,
    "n_probe_splits": 2,
    "n_permutations": 20,
    "minimum_probe_sites": 30,
}


def _rows(*, n_per_shape: int = 24, noise_only: bool = False, seed: int = 0) -> list[dict]:
    """Synthetic L1 vector rows: separable temporal shapes, or pure noise."""
    rng = np.random.default_rng(seed)
    rows: list[dict] = []
    site_index = 0
    for shape, base in SHAPES.items():
        for member in range(n_per_shape):
            if noise_only:
                profile = rng.normal(0.0, 1.0, size=len(TIMEPOINTS)).tolist()
            else:
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
                        "q_value": 0.01 if abs(profile[time_index]) > 1.0 else 0.4,
                        "p_value": 0.005,
                        "Quantification_Track": "protein_normalized_relative_ptm",
                        "Occupancy_Logit_Delta": float("nan"),
                        "Pair_Quality_Tier": "O0",
                        "Pair_Missingness": 0.0,
                    }
                )
            site_index += 1
    return rows


def _multiview(**kwargs):
    return build_multiview_input(_rows(**kwargs))


# ---------------------------------------------------------------------------
# The fairness precondition
# ---------------------------------------------------------------------------


def test_hidden_timepoint_is_blanked_across_every_view():
    """Track 1 and protein context at a timepoint share its measurement pair.

    Hiding Track 2 alone lets an arm that carries the other views recover the
    withheld value algebraically, which is how the noise control below once
    reached a perfect score.
    """
    multiview = _multiview(n_per_shape=12)
    index = 3

    masked = multiview.with_hidden_timepoint(index)

    for view in (masked.target, masked.protein_context, masked.track1):
        assert not view.observed[:, index].any()
        assert np.isnan(view.values[:, index]).all()
    assert np.allclose(masked.quality_weight[:, index], 0.0)
    # The value survives in the untouched original, so the probe has a target.
    assert np.isfinite(multiview.target.values[:, index]).any()

    embedding = handcrafted_representation(masked, "B").embedding
    original_values = multiview.target.values[:, index]
    rows = np.isfinite(original_values)
    for column in range(embedding.shape[1]):
        assert not np.allclose(embedding[rows, column], original_values[rows])


def test_other_timepoints_are_left_intact_by_hiding():
    multiview = _multiview(n_per_shape=12)

    masked = multiview.with_hidden_timepoint(2)

    kept = [index for index in range(multiview.n_timepoints) if index != 2]
    assert np.array_equal(masked.target.observed[:, kept], multiview.target.observed[:, kept])
    assert np.allclose(
        np.nan_to_num(masked.target.values[:, kept]),
        np.nan_to_num(multiview.target.values[:, kept]),
    )


def test_hidden_timepoint_index_is_validated():
    multiview = _multiview(n_per_shape=12)
    with pytest.raises(ValueError, match="out of range"):
        multiview.with_hidden_timepoint(multiview.n_timepoints)


def test_entry_level_hidden_mask_shape_is_validated():
    multiview = _multiview(n_per_shape=12)
    with pytest.raises(ValueError, match="does not match"):
        multiview.with_hidden_target_entries(np.zeros((3, 3), dtype=bool))


# ---------------------------------------------------------------------------
# Does the probe measure anything?
# ---------------------------------------------------------------------------


def test_probe_finds_skill_when_trajectories_are_structured():
    report = run_heldout_timepoint_probe(_multiview(n_per_shape=24), config=FAST_CONFIG)

    assert report["status"] == "evaluated"
    assert report["task"] == "hidden_timepoint_value_prediction"
    for arm in ("A", "B"):
        summary = report["per_arm"][arm]
        assert summary["mean_r2"] > 0.5, f"arm {arm} should predict a held-out timepoint"
        assert summary["mean_r2"] > summary["mean_null_r2"]
        assert summary["fraction_beating_null_at_0.05"] == pytest.approx(1.0)


def test_probe_reports_no_skill_on_noise():
    report = run_heldout_timepoint_probe(
        _multiview(n_per_shape=24, noise_only=True, seed=7), config=FAST_CONFIG
    )

    assert report["status"] == "evaluated"
    for arm in ("A", "B"):
        summary = report["per_arm"][arm]
        assert summary["mean_r2"] < 0.2, f"arm {arm} should not predict noise"


def test_permutation_null_is_centred_below_real_skill():
    report = run_heldout_timepoint_probe(_multiview(n_per_shape=24), config=FAST_CONFIG)

    for arm in ("A", "B"):
        summary = report["per_arm"][arm]
        # Shuffling the target must destroy skill, leaving a null near or below zero.
        assert summary["mean_null_r2"] < 0.1


def test_embedding_dimension_is_recorded_for_each_arm():
    report = run_heldout_timepoint_probe(_multiview(n_per_shape=24), config=FAST_CONFIG)

    # Arm A is Track 2 values plus its mask; arm B adds protein context and quality.
    assert report["per_arm"]["A"]["embedding_dim"] == 2 * len(TIMEPOINTS)
    assert report["per_arm"]["B"]["embedding_dim"] > report["per_arm"]["A"]["embedding_dim"]


# ---------------------------------------------------------------------------
# Paired comparison
# ---------------------------------------------------------------------------


def test_arm_compared_against_itself_shows_no_difference():
    report = run_heldout_timepoint_probe(
        _multiview(n_per_shape=24), config={**FAST_CONFIG, "baseline_arm": "A"}
    )
    folds = report["folds"]
    from ptm_shared.representation.fair_probe import ProbeFold

    restored = [ProbeFold(**{key: fold[key] for key in fold}) for fold in folds]
    same_arm = [fold for fold in restored if fold.arm == "A"]
    duplicated = same_arm + [
        ProbeFold(**{**fold.to_dict(), "arm": "A_copy"}) for fold in same_arm
    ]

    comparison = compare_to_baseline(duplicated, baseline_arm="A")["arms"]["A_copy"]

    assert comparison["mean_r2_difference"] == pytest.approx(0.0, abs=1e-12)
    assert comparison["verdict"] == "no_detectable_difference"


def test_comparison_pairs_only_matching_folds():
    report = run_heldout_timepoint_probe(_multiview(n_per_shape=24), config=FAST_CONFIG)
    comparison = report["comparisons"]

    assert comparison["baseline_arm"] == "B"
    entry = comparison["arms"]["A"]
    assert entry["n_paired_folds"] > 0
    assert 0.0 <= entry["fraction_of_folds_better"] <= 1.0
    assert entry["verdict"] in {
        "better_than_baseline",
        "worse_than_baseline",
        "no_detectable_difference",
    }


def test_sign_flip_test_separates_consistent_from_null_differences():
    consistent = np.full(40, 0.2)
    null_like = np.array([0.1, -0.1] * 20)

    assert _sign_flip_p_value(consistent, n_permutations=2000, seed=1) < 0.01
    assert _sign_flip_p_value(null_like, n_permutations=2000, seed=1) > 0.2
    assert _sign_flip_p_value(np.zeros(10), n_permutations=500, seed=1) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------------


def test_insufficient_data_is_reported_not_guessed():
    report = run_heldout_timepoint_probe(_multiview(n_per_shape=2), config=FAST_CONFIG)

    assert report["status"] == "insufficient_data"
    assert "per_arm" not in report


def test_report_is_json_safe():
    report = run_heldout_timepoint_probe(_multiview(n_per_shape=24), config=FAST_CONFIG)

    encoded = json.dumps(report)

    assert "NaN" not in encoded
    assert "Infinity" not in encoded


def test_arm_seed_component_survives_process_restarts():
    """분할 배정이 `PYTHONHASHSEED` 에 의존하면 프로브 절대값이 실행마다 달라진다.

    2026-08-22 까지 이 성분은 ``hash(arm)`` 이었고, 정본 컨테이너가 `PYTHONHASHSEED` 를
    설정하지 않으므로 같은 seed·같은 입력이 실행마다 다른 train/test 분할을 뽑았다.
    상세와 흩어짐 정량화는 docs/c2_prereg_v1.md §12.1.

    아래 값은 crc32 의 고정 출력이다. 값이 바뀌면 과거 프로브 수치와 비교할 수 없게 되므로
    갱신하기 전에 그 사실을 §12.1 에 기록해야 한다.
    """
    assert _arm_seed_component("A") == 6924
    assert _arm_seed_component("B") == 6706
    assert _arm_seed_component("C") == 4862
    assert _arm_seed_component("D") == 9741
    assert _arm_seed_component("E") == 733


def test_encoder_seed_set_is_contiguous_from_the_encoder_seed():
    """Methods 절에 적을 seed 집합이 산출 레코드에 남아야 한다.

    2026-08-22 까지 k > 0 의 seed 는 `config["seed"] + k` 였고 k = 0 은 호출자의
    `encoder_config["seed"]` 였다. 두 값이 다르면 seed 집합이 두 계열의 혼합이 되어
    Methods 절에 진술할 수 없다. 정본 경로(둘 다 0)에서는 두 규칙이 같은 집합을 내므로
    **기존 공표 수치는 바뀌지 않는다.**
    """
    report = run_heldout_timepoint_probe(
        _multiview(n_per_shape=24),
        encoder_config={"latent_dim": 4, "hidden_dim": 8, "epochs": 5, "seed": 11},
        config={**FAST_CONFIG, "arms": ("A", "D"), "n_encoder_seeds": 3, "seed": 0},
    )

    assert report["encoder_seed_set"] == [11, 12, 13]
    assert {fold["encoder_seed"] for fold in report["folds"] if fold["arm"] == "D"} == {0, 1, 2}


def test_learned_arm_folds_collapse_over_encoder_seeds_in_the_comparison():
    """seed 를 평균하는 것은 초기화 잡음이 짝지은 관측 수를 부풀리지 않게 한다.

    평균하지 않으면 학습 arm 이 seed 배수만큼 관측을 갖게 되어 sign-flip 검정의 표본이
    비학습 arm 과 어긋난다. docs/c3_prereg_v1.md §12.6.1 이 이 장치에 의존한다.
    """
    report = run_heldout_timepoint_probe(
        _multiview(n_per_shape=24),
        encoder_config={"latent_dim": 4, "hidden_dim": 8, "epochs": 5, "seed": 0},
        config={**FAST_CONFIG, "arms": ("A", "D"), "n_encoder_seeds": 3, "baseline_arm": "A"},
    )

    learned_folds = [fold for fold in report["folds"] if fold["arm"] == "D"]
    baseline_folds = [fold for fold in report["folds"] if fold["arm"] == "A"]
    assert len(learned_folds) == 3 * len(baseline_folds)
    # The paired comparison sees one observation per (timepoint, probe split).
    assert report["comparisons"]["arms"]["D"]["n_paired_folds"] == len(baseline_folds)
