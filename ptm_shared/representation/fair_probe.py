"""A held-out prediction benchmark that no representation arm can game.

The R1.5 ablation metrics cannot rank the arms against each other.  Two of them
are structurally biased:

* ``raw_evidence_concordance`` asks whether embedding neighbours share the raw
  peak time and direction, while arm B's embedding *is* the raw trajectory.  The
  arm that carries the answer verbatim wins by construction, so the metric is a
  floor check for a learned arm, not a competition.
* ``missingness_r2`` is an unadjusted coefficient of determination, which grows
  with the number of predictors, so a 30-dimensional arm and a 16-dimensional arm
  are not comparable on it.

This module implements the comparison those metrics cannot make.  One timepoint is
blanked across every view for *every* arm, each arm builds its representation from
what remains, and a ridge probe predicts the hidden Track 2 value on sites the
probe never saw.  No arm can read the target, all arms face the same task, and the
probe is the same model class with its regularisation tuned per arm, so a wider
representation gains no automatic advantage.

Blanking the whole timepoint column matters: the protein-context value and the
Track 1 occupancy at a timepoint derive from the same measurement pair as the
Track 2 value, so hiding Track 2 alone lets an arm that carries the other views
recover the withheld number algebraically.  The noise control test in
``workers/tests/test_representation_fair_probe.py`` pins this down; it reached
R^2 = 1.0 on pure noise before the other views were blanked.

Reported per arm: out-of-sample R^2 over folds, a permutation null obtained by
shuffling the probe target, and paired differences against a chosen baseline arm
with a sign-flip test.  A win is only claimed when it survives both.

Determinism: the probe split RNG is seeded from ``(config seed, hidden timepoint,
arm, encoder seed, split index)``.  Until 2026-08-22 the arm component was
``hash(arm)``, which the interpreter salts per process, so **probe numbers produced
before that date are not comparable across runs** — the paired comparison inside a
single run is unaffected because both arms shared that run's splits.  See
``_arm_seed_component``.

The setup is transductive: every arm builds its representation from all sites,
including the sites the probe is later scored on, and only the hidden *values*
are withheld.  That is the same condition for all arms and so does not bias the
comparison, but it means the numbers describe representation quality within one
cohort and not generalisation to a new dataset, which remains untested.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from zlib import crc32

import numpy as np

from .benchmark import fit_variant
from .feature_contract import MultiViewTemporalInput

CONTRACT_VERSION = "ptm_representation_fair_probe.v1"

DEFAULT_CONFIG: Dict[str, Any] = {
    "arms": ("A", "B", "D", "E"),
    "baseline_arm": "B",
    "alphas": (0.01, 0.1, 1.0, 10.0, 100.0, 1000.0),
    "inner_folds": 3,
    "probe_test_fraction": 0.3,
    "n_encoder_seeds": 5,
    "n_probe_splits": 4,
    "n_permutations": 100,
    "minimum_probe_sites": 40,
    "max_sites": 3000,
    "seed": 0,
}

_EPSILON = 1e-12


def _arm_seed_component(arm: str) -> int:
    """Map an arm name to a split-seed component that survives process restarts.

    구현 대상: docs/c2_prereg_v1.md §12 결정성. 2026-08-22 결함 수정.
    사전등록: 결함 발견 시점이 C2 판정 후이므로 이 수정은 **탐색적이 아니라 결정성 복구**다.
      측정량의 정의는 바뀌지 않으며 분할 배정만 실행 간 고정된다.
    해석 한계: 이 수정 이전에 산출된 프로브 수치는 실행마다 다른 분할에서 나온 값이므로
      **수정 이후 수치와 절대값으로 비교할 수 없다.** 수정 전 단일 실행 내부의 짝지은
      비교(같은 분할을 공유)는 여전히 유효하다.
    주장 금지: 이 수정으로 과거 공표값이 재현된다고 서술하지 않는다. 재현되지 않는다.

    ``hash(str)`` is salted per interpreter unless ``PYTHONHASHSEED`` is set, and the
    canonical container does not set it, so the previous ``hash(arm) % 9973`` drew a
    different probe split on every run.  ``crc32`` is a fixed function of the bytes.
    """
    return crc32(arm.encode("utf-8")) % 9973


def _merged_config(config: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    merged = dict(DEFAULT_CONFIG)
    if config:
        merged.update({key: value for key, value in config.items() if key in DEFAULT_CONFIG})
    merged["inner_folds"] = max(2, int(merged["inner_folds"]))
    merged["n_encoder_seeds"] = max(1, int(merged["n_encoder_seeds"]))
    merged["n_probe_splits"] = max(1, int(merged["n_probe_splits"]))
    merged["n_permutations"] = max(0, int(merged["n_permutations"]))
    merged["probe_test_fraction"] = float(np.clip(merged["probe_test_fraction"], 0.1, 0.5))
    return merged


# ---------------------------------------------------------------------------
# Ridge probe
# ---------------------------------------------------------------------------


def _standardize(train: np.ndarray, other: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Z-score columns using training statistics only."""
    center = train.mean(axis=0)
    scale = train.std(axis=0)
    scale = np.where(scale < 1e-9, 1.0, scale)
    return (train - center) / scale, (other - center) / scale


def _ridge_weights(features: np.ndarray, target: np.ndarray, alpha: float) -> np.ndarray:
    n_features = features.shape[1]
    gram = features.T @ features + float(alpha) * np.eye(n_features)
    return np.linalg.solve(gram, features.T @ target)


def _ridge_predict(
    train_features: np.ndarray,
    train_target: np.ndarray,
    test_features: np.ndarray,
    alpha: float,
) -> Tuple[np.ndarray, float]:
    """Fit ridge on the training rows and predict the test rows.

    Returns the predictions and the training mean, which also serves as the
    reference for the out-of-sample skill score.
    """
    scaled_train, scaled_test = _standardize(train_features, test_features)
    offset = float(train_target.mean())
    weights = _ridge_weights(scaled_train, train_target - offset, alpha)
    return scaled_test @ weights + offset, offset


def _tune_alpha(
    features: np.ndarray,
    target: np.ndarray,
    alphas: Sequence[float],
    folds: int,
    rng: np.random.Generator,
) -> float:
    """Pick the ridge penalty by inner cross-validation on the training rows."""
    n_rows = features.shape[0]
    if n_rows < folds * 2:
        return float(alphas[len(alphas) // 2])
    order = rng.permutation(n_rows)
    splits = np.array_split(order, folds)
    best_alpha, best_error = float(alphas[0]), np.inf
    for alpha in alphas:
        errors: List[float] = []
        for index in range(folds):
            test_rows = splits[index]
            train_rows = np.concatenate([splits[j] for j in range(folds) if j != index])
            if train_rows.size < 2 or test_rows.size < 1:
                continue
            prediction, _ = _ridge_predict(
                features[train_rows], target[train_rows], features[test_rows], alpha
            )
            errors.append(float(np.mean((target[test_rows] - prediction) ** 2)))
        if errors:
            mean_error = float(np.mean(errors))
            if mean_error < best_error:
                best_alpha, best_error = float(alpha), mean_error
    return best_alpha


def _out_of_sample_r2(truth: np.ndarray, prediction: np.ndarray, reference: float) -> float:
    """Skill against the training mean, so knowing the test mean is no advantage."""
    denominator = float(np.sum((truth - reference) ** 2))
    if denominator <= _EPSILON:
        return float("nan")
    return float(1.0 - np.sum((truth - prediction) ** 2) / denominator)


# ---------------------------------------------------------------------------
# Folds
# ---------------------------------------------------------------------------


@dataclass
class ProbeFold:
    """One (arm, hidden timepoint, encoder seed, probe split) evaluation."""

    arm: str
    timepoint: str
    timepoint_index: int
    encoder_seed: int
    probe_split: int
    embedding_dim: int
    n_train: int
    n_test: int
    alpha: float
    r2: float
    rmse: float
    permutation_p_value: Optional[float] = None
    null_r2_mean: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _hide_timepoint(
    multiview: MultiViewTemporalInput, index: int
) -> Tuple[MultiViewTemporalInput, np.ndarray]:
    """Blank one timepoint across all views; report which sites had it observed.

    All views are blanked, not just Track 2, because the protein context and the
    Track 1 occupancy at a timepoint come from the same measurement pair as the
    Track 2 value and would otherwise hand the answer to any arm that carries
    them.
    """
    evaluable = multiview.target.observed[:, index].copy()
    return multiview.with_hidden_timepoint(index), evaluable


def _evaluate_split(
    embedding: np.ndarray,
    target: np.ndarray,
    rows: np.ndarray,
    *,
    effective: Mapping[str, Any],
    rng: np.random.Generator,
) -> Optional[Dict[str, Any]]:
    """Split the evaluable sites, tune ridge, score, and run the permutation null."""
    n_rows = rows.size
    n_test = int(round(n_rows * float(effective["probe_test_fraction"])))
    if n_rows < int(effective["minimum_probe_sites"]) or n_test < 5 or n_rows - n_test < 10:
        return None

    shuffled = rng.permutation(rows)
    test_rows, train_rows = shuffled[:n_test], shuffled[n_test:]
    train_features, test_features = embedding[train_rows], embedding[test_rows]
    train_target, test_target = target[train_rows], target[test_rows]
    if float(np.std(train_target)) < 1e-9:
        return None

    alpha = _tune_alpha(
        train_features, train_target, effective["alphas"], int(effective["inner_folds"]), rng
    )
    prediction, reference = _ridge_predict(train_features, train_target, test_features, alpha)
    r2 = _out_of_sample_r2(test_target, prediction, reference)
    rmse = float(np.sqrt(np.mean((test_target - prediction) ** 2)))

    null_p: Optional[float] = None
    null_mean: Optional[float] = None
    n_permutations = int(effective["n_permutations"])
    if n_permutations > 0 and np.isfinite(r2):
        null_scores: List[float] = []
        for _ in range(n_permutations):
            shuffled_target = rng.permutation(train_target)
            null_prediction, null_reference = _ridge_predict(
                train_features, shuffled_target, test_features, alpha
            )
            null_scores.append(_out_of_sample_r2(test_target, null_prediction, null_reference))
        finite_null = np.asarray([value for value in null_scores if np.isfinite(value)])
        if finite_null.size:
            null_mean = float(finite_null.mean())
            null_p = float((1 + int(np.sum(finite_null >= r2))) / (1 + finite_null.size))

    return {
        "r2": r2,
        "rmse": rmse,
        "alpha": alpha,
        "permutation_p_value": null_p,
        "null_r2_mean": null_mean,
        "n_train": int(train_rows.size),
        "n_test": int(test_rows.size),
    }


def run_heldout_timepoint_probe(
    multiview: MultiViewTemporalInput,
    *,
    encoder_config: Optional[Mapping[str, Any]] = None,
    config: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Compare representation arms on predicting a hidden timepoint.

    Learned arms are refit once per (hidden timepoint, encoder seed); the cheap
    probe splits reuse that fit.  Non-learned arms are deterministic, so they are
    fit once per hidden timepoint and evaluated over the same probe splits, which
    keeps the paired comparison aligned fold for fold.

    구현 대상: docs/ptm_representation_learning_contract_v1.md §R1.6 공정 프로브
    사전등록: seed 파생 규칙 명시화는 2026-08-22. **정본 경로의 수치는 바뀌지 않는다** —
      `encoder_config["seed"] = 0` 이고 `config["seed"] = 0` 인 기존 실행에서 두 규칙이
      같은 집합 {0,1,2,3,4} 를 내기 때문이다. 두 값이 다를 때만 달라진다.
    해석 한계: seed 를 평균하는 것은 초기화 잡음이 짝지은 관측 수를 부풀리지 않게 하는
      장치이며, 인코더가 seed 에 대해 식별된다는 뜻이 아니다. arm D 의 군집 기하는
      seed 에 대해 식별되지 않는다 (docs/c3_prereg_v1.md §12.6.1). 프로브가 그와
      양립하는 것은 프로브가 열공간에만 의존하기 때문이다.
    주장 금지: seed 평균이 기하 불안정을 해결한다고 서술하지 않는다. 우회할 뿐이다.
    """
    effective = _merged_config(config)
    arms = [str(arm) for arm in effective["arms"]]
    n_timepoints = multiview.n_timepoints
    if multiview.n_sites < int(effective["minimum_probe_sites"]) or n_timepoints < 3:
        return {
            "contract_version": CONTRACT_VERSION,
            "status": "insufficient_data",
            "n_sites": multiview.n_sites,
            "n_timepoints": n_timepoints,
        }

    truth = np.nan_to_num(multiview.target.values, nan=0.0)
    folds: List[ProbeFold] = []
    skipped: Dict[str, str] = {}
    # Derive the seed sweep from the encoder's own seed so the set stays contiguous.
    # Deriving it from ``effective["seed"]`` instead would mix two seed families
    # whenever the caller's encoder seed differs from the probe seed, leaving the
    # recorded seed set impossible to state in a methods section.
    encoder_base_seed = int((encoder_config or {}).get("seed", effective["seed"]))

    for timepoint_index in range(n_timepoints):
        masked, evaluable = _hide_timepoint(multiview, timepoint_index)
        rows = np.flatnonzero(evaluable)
        if rows.size < int(effective["minimum_probe_sites"]):
            continue
        target = truth[:, timepoint_index]

        for arm in arms:
            probe_arm = fit_variant(masked, arm, encoder_config=encoder_config, config=effective)
            learned = bool(probe_arm.learned)
            if probe_arm.embedding.size == 0 or probe_arm.embedding.shape[1] == 0:
                skipped[arm] = "empty_embedding"
                continue

            seeds = range(int(effective["n_encoder_seeds"])) if learned else range(1)
            for encoder_seed in seeds:
                if learned and encoder_seed > 0:
                    seeded = dict(encoder_config or {})
                    seeded["seed"] = encoder_base_seed + encoder_seed
                    fit = fit_variant(masked, arm, encoder_config=seeded, config=effective)
                else:
                    fit = probe_arm
                embedding = np.asarray(fit.embedding, dtype=float)

                for probe_split in range(int(effective["n_probe_splits"])):
                    rng = np.random.default_rng(
                        (
                            int(effective["seed"]),
                            timepoint_index,
                            _arm_seed_component(arm),
                            encoder_seed,
                            probe_split,
                        )
                    )
                    outcome = _evaluate_split(
                        embedding, target, rows, effective=effective, rng=rng
                    )
                    if outcome is None:
                        continue
                    folds.append(
                        ProbeFold(
                            arm=arm,
                            timepoint=multiview.timepoints[timepoint_index],
                            timepoint_index=timepoint_index,
                            encoder_seed=encoder_seed,
                            probe_split=probe_split,
                            embedding_dim=int(embedding.shape[1]),
                            n_train=outcome["n_train"],
                            n_test=outcome["n_test"],
                            alpha=outcome["alpha"],
                            r2=outcome["r2"],
                            rmse=outcome["rmse"],
                            permutation_p_value=outcome["permutation_p_value"],
                            null_r2_mean=outcome["null_r2_mean"],
                        )
                    )

    if not folds:
        return {
            "contract_version": CONTRACT_VERSION,
            "status": "no_evaluable_folds",
            "n_sites": multiview.n_sites,
            "n_timepoints": n_timepoints,
            "skipped_arms": skipped,
        }

    return {
        "contract_version": CONTRACT_VERSION,
        "status": "evaluated",
        "stage": "R1.6_fair_probe",
        "task": "hidden_timepoint_value_prediction",
        "n_sites": multiview.n_sites,
        "n_timepoints": n_timepoints,
        "config": {
            key: (list(value) if isinstance(value, tuple) else value)
            for key, value in effective.items()
        },
        # Recorded so the methods section can state the seed set rather than infer it.
        "encoder_seed_set": [
            encoder_base_seed + offset for offset in range(int(effective["n_encoder_seeds"]))
        ],
        "per_arm": summarize_arms(folds),
        "comparisons": compare_to_baseline(folds, baseline_arm=str(effective["baseline_arm"])),
        "skipped_arms": skipped,
        "folds": [fold.to_dict() for fold in folds],
    }


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def summarize_arms(folds: Sequence[ProbeFold]) -> Dict[str, Any]:
    """Per-arm mean skill, spread, and how often it beat its permutation null."""
    grouped: Dict[str, List[ProbeFold]] = {}
    for fold in folds:
        grouped.setdefault(fold.arm, []).append(fold)

    summary: Dict[str, Any] = {}
    for arm, arm_folds in grouped.items():
        scores = np.asarray([fold.r2 for fold in arm_folds], dtype=float)
        finite = scores[np.isfinite(scores)]
        p_values = [
            fold.permutation_p_value
            for fold in arm_folds
            if fold.permutation_p_value is not None
        ]
        nulls = np.asarray(
            [fold.null_r2_mean for fold in arm_folds if fold.null_r2_mean is not None],
            dtype=float,
        )
        summary[arm] = {
            "n_folds": len(arm_folds),
            "embedding_dim": int(arm_folds[0].embedding_dim),
            "mean_r2": round(float(finite.mean()), 6) if finite.size else None,
            "sd_r2": round(float(finite.std(ddof=1)), 6) if finite.size > 1 else None,
            "median_r2": round(float(np.median(finite)), 6) if finite.size else None,
            "mean_rmse": round(
                float(np.mean([fold.rmse for fold in arm_folds])), 6
            ),
            "mean_null_r2": round(float(nulls.mean()), 6) if nulls.size else None,
            "fraction_beating_null_at_0.05": (
                round(float(np.mean([value <= 0.05 for value in p_values])), 6)
                if p_values
                else None
            ),
            "median_alpha": float(np.median([fold.alpha for fold in arm_folds])),
        }
    return summary


def _sign_flip_p_value(
    differences: np.ndarray, *, n_permutations: int = 10000, seed: int = 0
) -> float:
    """Two-sided paired test that makes no distributional assumption."""
    if differences.size == 0:
        return float("nan")
    observed = abs(float(differences.mean()))
    rng = np.random.default_rng(int(seed))
    signs = rng.choice((-1.0, 1.0), size=(int(n_permutations), differences.size))
    null = np.abs((signs * differences).mean(axis=1))
    return float((1 + int(np.sum(null >= observed))) / (1 + int(n_permutations)))


def compare_to_baseline(
    folds: Sequence[ProbeFold], *, baseline_arm: str = "B"
) -> Dict[str, Any]:
    """Paired arm-versus-baseline differences on identically constructed folds.

    Pairing is by (hidden timepoint, probe split) so both arms saw the same hidden
    entries and the same probe rows.  Learned arms contribute the mean over their
    encoder seeds for that pair, which keeps initialisation noise from inflating
    the number of paired observations.
    """
    keyed: Dict[Tuple[str, Tuple[int, int]], List[float]] = {}
    for fold in folds:
        if not np.isfinite(fold.r2):
            continue
        keyed.setdefault((fold.arm, (fold.timepoint_index, fold.probe_split)), []).append(fold.r2)
    collapsed = {key: float(np.mean(values)) for key, values in keyed.items()}

    baseline_pairs = {
        pair: score for (arm, pair), score in collapsed.items() if arm == baseline_arm
    }
    if not baseline_pairs:
        return {"baseline_arm": baseline_arm, "status": "baseline_absent"}

    comparisons: Dict[str, Any] = {"baseline_arm": baseline_arm, "arms": {}}
    arms = sorted({arm for arm, _ in collapsed})
    for arm in arms:
        if arm == baseline_arm:
            continue
        shared = [
            (collapsed[(arm, pair)], baseline_score)
            for pair, baseline_score in baseline_pairs.items()
            if (arm, pair) in collapsed
        ]
        if not shared:
            comparisons["arms"][arm] = {"status": "no_shared_folds"}
            continue
        differences = np.asarray([arm_score - base for arm_score, base in shared], dtype=float)
        p_value = _sign_flip_p_value(differences)
        comparisons["arms"][arm] = {
            "n_paired_folds": int(differences.size),
            "mean_r2_difference": round(float(differences.mean()), 6),
            "sd_r2_difference": (
                round(float(differences.std(ddof=1)), 6) if differences.size > 1 else None
            ),
            "fraction_of_folds_better": round(float(np.mean(differences > 0)), 6),
            "sign_flip_p_value": round(p_value, 6),
            "verdict": _verdict(differences.mean(), p_value),
        }
    return comparisons


def _verdict(mean_difference: float, p_value: float) -> str:
    if not np.isfinite(p_value) or p_value > 0.05:
        return "no_detectable_difference"
    return "better_than_baseline" if mean_difference > 0 else "worse_than_baseline"
