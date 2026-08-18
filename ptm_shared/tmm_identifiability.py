"""Identifiability diagnostics for the temporal mixture model (TMM).

The platform attributes a shared PTM site's trajectory to candidate kinases by
solving a non-negative least squares problem

    minimize  ||A a - y||_2    subject to  a >= 0,

where ``y`` is the site trajectory over the ordered conditions and the columns
of ``A`` are per-kinase temporal activity profiles.  The reported contribution
ratio is ``a / sum(a)``.

Nothing in the current pipeline checks whether ``a`` is *recoverable* from
``y``.  With few timepoints and smooth unimodal profiles the columns of ``A``
are frequently near-collinear, and then many different ``a`` explain ``y``
equally well: the reported ratio is one arbitrary point inside a set of equally
good solutions.  This module measures that.

It is diagnostic only and never modifies scores.  Three independent lines of
evidence are produced, deliberately ordered from strongest to weakest in terms
of the assumptions they need:

1. Structural, assumption-free - rank, condition number, and pairwise coherence
   of ``A``.  A rank-deficient or highly coherent design cannot identify ``a``
   at any noise level, regardless of the data.
2. Local sensitivity - the smallest singular value of the active-set submatrix
   bounds how far ``a`` can move under a perturbation of ``y`` of size
   ``epsilon``, which yields an ambiguity radius on the reported ratio scale.
3. Leave-one-kinase-out - refitting without a candidate shows whether the data
   can detect its absence at all.  A candidate carrying a large reported ratio
   whose removal does not raise the residual above the noise floor is not
   supported by the data.

``epsilon`` is an explicit, recorded assumption rather than a hidden constant:
callers supply an absolute noise scale, or a relative one applied to ``||y||``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

try:  # scipy is present in the API and worker images; the fallback keeps this module portable
    from scipy.optimize import nnls as _scipy_nnls

    _HAS_SCIPY = True
except ImportError:  # pragma: no cover - exercised only in stripped environments
    _scipy_nnls = None
    _HAS_SCIPY = False


DEFAULT_RELATIVE_NOISE = 0.10
DEFAULT_BOOTSTRAP = 64

# A reported ratio whose ambiguity radius exceeds this is not a measurement.
RATIO_AMBIGUITY_BROKEN = 0.50
RATIO_AMBIGUITY_WEAK = 0.15
# Two profile columns this aligned are mutually substitutable at any noise level.
COHERENCE_SUBSTITUTABLE = 0.99
# Ratios below this are not worth adjudicating.
MIN_REPORTED_RATIO = 0.05

_EPSILON = 1e-12

VERDICT_IDENTIFIABLE = "identifiable"
VERDICT_WEAK = "weakly_identifiable"
VERDICT_NON_IDENTIFIABLE = "non_identifiable"
VERDICT_NO_SIGNAL = "no_signal"
VERDICT_EQUAL_WEIGHT_FALLBACK = "equal_weight_fallback"


def default_thresholds() -> Dict[str, float]:
    """Return the recorded decision thresholds so reports stay self-describing."""
    return {
        "ratio_ambiguity_broken": RATIO_AMBIGUITY_BROKEN,
        "ratio_ambiguity_weak": RATIO_AMBIGUITY_WEAK,
        "coherence_substitutable": COHERENCE_SUBSTITUTABLE,
        "min_reported_ratio": MIN_REPORTED_RATIO,
    }


# ----------------------------------------------------------------------------
# Solver
# ----------------------------------------------------------------------------


def _projected_gradient_nnls(
    design: np.ndarray,
    target: np.ndarray,
    *,
    max_iterations: int = 500,
    tolerance: float = 1e-11,
) -> np.ndarray:
    gram = design.T @ design
    correlation = design.T @ target
    step = float(np.linalg.norm(gram, 2))
    if not np.isfinite(step) or step <= _EPSILON:
        return np.zeros(design.shape[1], dtype=float)
    coefficients = np.zeros(design.shape[1], dtype=float)
    for _ in range(max_iterations):
        gradient = gram @ coefficients - correlation
        updated = np.maximum(coefficients - gradient / step, 0.0)
        if np.max(np.abs(updated - coefficients)) < tolerance:
            return updated
        coefficients = updated
    return coefficients


def solve_nnls(design: np.ndarray, target: np.ndarray) -> Tuple[np.ndarray, float]:
    """Solve the non-negative least squares problem and return (coefficients, RSS)."""
    if design.size == 0 or design.shape[1] == 0:
        return np.zeros(0, dtype=float), float(target @ target)
    if _HAS_SCIPY:
        try:
            coefficients, residual_norm = _scipy_nnls(design, target)
            return np.asarray(coefficients, dtype=float), float(residual_norm) ** 2
        except Exception:
            pass
    coefficients = _projected_gradient_nnls(design, target)
    residual = design @ coefficients - target
    return coefficients, float(residual @ residual)


def normalized_ratios(coefficients: np.ndarray) -> np.ndarray:
    """Reproduce the reported contribution ratio, or uniform weights on collapse.

    The uniform branch mirrors the production fallback: when every coefficient
    is numerically zero the pipeline reports equal contributions, which looks
    like a measurement but carries no evidence.
    """
    total = float(coefficients.sum())
    if coefficients.size == 0:
        return coefficients
    if total <= 1e-9:
        return np.full(coefficients.shape, 1.0 / coefficients.size, dtype=float)
    return coefficients / total


# ----------------------------------------------------------------------------
# Structural geometry
# ----------------------------------------------------------------------------


def _singular_values(matrix: np.ndarray) -> np.ndarray:
    if matrix.size == 0 or min(matrix.shape) == 0:
        return np.zeros(0, dtype=float)
    try:
        return np.linalg.svd(matrix, compute_uv=False)
    except np.linalg.LinAlgError:  # pragma: no cover - numerically pathological input
        return np.zeros(0, dtype=float)


def _condition_number(matrix: np.ndarray) -> float:
    values = _singular_values(matrix)
    if values.size == 0:
        return float("inf")
    largest = float(values[0])
    smallest = float(values[-1])
    if smallest <= _EPSILON * max(largest, 1.0):
        return float("inf")
    return largest / smallest


def _numerical_rank(matrix: np.ndarray) -> int:
    values = _singular_values(matrix)
    if values.size == 0:
        return 0
    cutoff = float(values[0]) * max(matrix.shape) * np.finfo(float).eps
    return int((values > cutoff).sum())


def max_column_coherence(design: np.ndarray) -> Tuple[float, List[Tuple[int, int, float]]]:
    """Return the largest pairwise |cosine| between profile columns and all pairs.

    Coherence is scale-free, so it is unaffected by the max-normalisation the
    profile builder applies.  Two columns with coherence near 1 span almost the
    same direction: no amount of data separates their coefficients.
    """
    if design.shape[1] < 2:
        return 0.0, []
    norms = np.linalg.norm(design, axis=0)
    safe = np.where(norms > _EPSILON, norms, 1.0)
    unit = design / safe
    gram = np.abs(unit.T @ unit)
    np.fill_diagonal(gram, 0.0)
    pairs: List[Tuple[int, int, float]] = []
    n_columns = design.shape[1]
    for i in range(n_columns):
        for j in range(i + 1, n_columns):
            pairs.append((i, j, float(gram[i, j])))
    return float(gram.max()) if gram.size else 0.0, pairs


# ----------------------------------------------------------------------------
# Per-site diagnosis
# ----------------------------------------------------------------------------


@dataclass
class SiteIdentifiability:
    """Whether one site's kinase attribution is recoverable, and how wide it is."""

    site_key: str
    verdict: str
    n_timepoints: int
    n_candidates: int
    kinase_names: Tuple[str, ...] = ()
    reported_ratios: Dict[str, float] = field(default_factory=dict)
    top1_kinase: Optional[str] = None
    top1_ratio: float = 0.0

    noise_scale: float = 0.0
    relative_residual: float = 0.0

    design_rank: int = 0
    design_condition_number: float = float("inf")
    max_column_coherence: float = 0.0
    structurally_underdetermined: bool = False

    n_active: int = 0
    active_rank: int = 0
    active_sigma_min: float = 0.0
    active_condition_number: float = float("inf")
    unique_solution: bool = False

    coefficient_ambiguity_radius: float = float("inf")
    ratio_ambiguity_radius: float = float("inf")

    leave_one_out: List[Dict[str, Any]] = field(default_factory=list)
    n_redundant: int = 0
    ambiguity_set: Tuple[str, ...] = ()
    substitutable_pairs: List[Dict[str, Any]] = field(default_factory=list)

    top1_stability: float = float("nan")
    top1_ratio_std: float = float("nan")

    equal_weight_fallback: bool = False
    y_negative_fraction: float = 0.0
    prior_column_fraction: float = 0.0
    top1_from_prior: bool = False

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "site_key": self.site_key,
            "verdict": self.verdict,
            "n_timepoints": self.n_timepoints,
            "n_candidates": self.n_candidates,
            "kinase_names": list(self.kinase_names),
            "reported_ratios": self.reported_ratios,
            "top1_kinase": self.top1_kinase,
            "top1_ratio": self.top1_ratio,
            "noise_scale": self.noise_scale,
            "relative_residual": self.relative_residual,
            "design_rank": self.design_rank,
            "design_condition_number": self.design_condition_number,
            "max_column_coherence": self.max_column_coherence,
            "structurally_underdetermined": self.structurally_underdetermined,
            "n_active": self.n_active,
            "active_rank": self.active_rank,
            "active_sigma_min": self.active_sigma_min,
            "active_condition_number": self.active_condition_number,
            "unique_solution": self.unique_solution,
            "coefficient_ambiguity_radius": self.coefficient_ambiguity_radius,
            "ratio_ambiguity_radius": self.ratio_ambiguity_radius,
            "leave_one_out": self.leave_one_out,
            "n_redundant": self.n_redundant,
            "ambiguity_set": list(self.ambiguity_set),
            "substitutable_pairs": self.substitutable_pairs,
            "top1_stability": self.top1_stability,
            "top1_ratio_std": self.top1_ratio_std,
            "equal_weight_fallback": self.equal_weight_fallback,
            "y_negative_fraction": self.y_negative_fraction,
            "prior_column_fraction": self.prior_column_fraction,
            "top1_from_prior": self.top1_from_prior,
        }
        return _json_safe(payload)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        if np.isnan(number):
            return None
        if np.isinf(number):
            return "inf" if number > 0 else "-inf"
        return number
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    return value


def diagnose_site(
    site_key: str,
    trajectory: Sequence[float] | np.ndarray,
    design: np.ndarray,
    kinase_names: Sequence[str],
    *,
    relative_noise: float = DEFAULT_RELATIVE_NOISE,
    absolute_noise: Optional[float] = None,
    n_bootstrap: int = DEFAULT_BOOTSTRAP,
    seed: int = 0,
    prior_columns: Optional[Sequence[bool]] = None,
    thresholds: Optional[Mapping[str, float]] = None,
) -> SiteIdentifiability:
    """Diagnose whether one site's NNLS kinase attribution is identifiable.

    ``design`` and ``trajectory`` must be exactly what the production solver
    receives, including any zero-imputed timepoints, so that the diagnosis
    describes the deployed estimator rather than an idealised one.
    """
    limits = dict(default_thresholds())
    if thresholds:
        limits.update(thresholds)

    target = np.asarray(trajectory, dtype=float).ravel()
    matrix = np.asarray(design, dtype=float)
    if matrix.ndim == 1:
        matrix = matrix.reshape(-1, 1)
    names = tuple(str(name) for name in kinase_names)
    n_timepoints, n_candidates = matrix.shape if matrix.size else (target.size, 0)

    result = SiteIdentifiability(
        site_key=site_key,
        verdict=VERDICT_NO_SIGNAL,
        n_timepoints=int(n_timepoints),
        n_candidates=int(n_candidates),
        kinase_names=names,
    )
    if prior_columns is not None and len(prior_columns) == n_candidates and n_candidates:
        result.prior_column_fraction = float(np.mean([bool(flag) for flag in prior_columns]))

    target_norm = float(np.linalg.norm(target))
    noise_scale = (
        float(absolute_noise)
        if absolute_noise is not None
        else float(relative_noise) * target_norm
    )
    result.noise_scale = noise_scale
    if target.size:
        result.y_negative_fraction = float(np.mean(target < 0.0))

    if n_candidates == 0 or target_norm <= _EPSILON:
        return result

    coefficients, rss = solve_nnls(matrix, target)
    result.equal_weight_fallback = bool(coefficients.sum() <= 1e-9)
    ratios = normalized_ratios(coefficients)
    result.reported_ratios = {names[i]: float(ratios[i]) for i in range(n_candidates)}
    result.relative_residual = float(np.sqrt(max(rss, 0.0)) / max(target_norm, _EPSILON))

    top_index = int(np.argmax(ratios))
    result.top1_kinase = names[top_index]
    result.top1_ratio = float(ratios[top_index])
    if prior_columns is not None and len(prior_columns) == n_candidates:
        result.top1_from_prior = bool(prior_columns[top_index])

    result.design_rank = _numerical_rank(matrix)
    result.design_condition_number = _condition_number(matrix)
    result.structurally_underdetermined = bool(n_candidates > result.design_rank)
    coherence, pairs = max_column_coherence(matrix)
    result.max_column_coherence = coherence

    if result.equal_weight_fallback:
        result.verdict = VERDICT_EQUAL_WEIGHT_FALLBACK
        result.ambiguity_set = names
        result.substitutable_pairs = _substitutable_pairs(pairs, names, ratios, limits)
        return result

    active = np.flatnonzero(coefficients > 1e-9)
    result.n_active = int(active.size)
    if active.size:
        active_matrix = matrix[:, active]
        active_values = _singular_values(active_matrix)
        result.active_rank = _numerical_rank(active_matrix)
        result.active_sigma_min = float(active_values[-1]) if active_values.size else 0.0
        result.active_condition_number = _condition_number(active_matrix)
        result.unique_solution = bool(result.active_rank == active.size)

    if result.active_sigma_min > _EPSILON:
        result.coefficient_ambiguity_radius = noise_scale / result.active_sigma_min
    total = float(coefficients.sum())
    if total > _EPSILON and np.isfinite(result.coefficient_ambiguity_radius):
        result.ratio_ambiguity_radius = result.coefficient_ambiguity_radius / total

    result.leave_one_out = _leave_one_out(matrix, target, names, ratios, rss, noise_scale)
    result.n_redundant = sum(
        1
        for entry in result.leave_one_out
        if not entry["required"] and entry["ratio"] >= limits["min_reported_ratio"]
    )
    ambiguous = {
        entry["kinase"]
        for entry in result.leave_one_out
        if not entry["required"] and entry["ratio"] >= limits["min_reported_ratio"]
    }
    result.substitutable_pairs = _substitutable_pairs(pairs, names, ratios, limits)
    for pair in result.substitutable_pairs:
        ambiguous.update({pair["kinase_a"], pair["kinase_b"]})
    result.ambiguity_set = tuple(sorted(ambiguous))

    if n_bootstrap > 0:
        stability, ratio_std = _bootstrap_top1(
            matrix, target, noise_scale, top_index, n_bootstrap=n_bootstrap, seed=seed
        )
        result.top1_stability = stability
        result.top1_ratio_std = ratio_std

    result.verdict = _verdict(result, limits)
    return result


def _leave_one_out(
    matrix: np.ndarray,
    target: np.ndarray,
    names: Sequence[str],
    ratios: np.ndarray,
    rss_full: float,
    noise_scale: float,
) -> List[Dict[str, Any]]:
    """Per candidate, the residual increase caused by removing it from the design.

    The noise floor is ``epsilon**2`` on the same scale as the residual sum of
    squares: a removal that does not raise RSS by at least that much is not
    detectable, so the data does not require the candidate.
    """
    floor = noise_scale ** 2
    entries: List[Dict[str, Any]] = []
    n_candidates = matrix.shape[1]
    for index in range(n_candidates):
        if n_candidates == 1:
            reduced_rss = float(target @ target)
        else:
            reduced = np.delete(matrix, index, axis=1)
            _, reduced_rss = solve_nnls(reduced, target)
        delta = float(reduced_rss - rss_full)
        entries.append(
            {
                "kinase": str(names[index]),
                "ratio": float(ratios[index]),
                "delta_rss": delta,
                "detection_floor": float(floor),
                "required": bool(delta > floor),
            }
        )
    return entries


def _substitutable_pairs(
    pairs: Sequence[Tuple[int, int, float]],
    names: Sequence[str],
    ratios: np.ndarray,
    limits: Mapping[str, float],
) -> List[Dict[str, Any]]:
    threshold = limits["coherence_substitutable"]
    minimum = limits["min_reported_ratio"]
    found: List[Dict[str, Any]] = []
    for i, j, coherence in pairs:
        if coherence < threshold:
            continue
        if max(float(ratios[i]), float(ratios[j])) < minimum:
            continue
        found.append(
            {
                "kinase_a": str(names[i]),
                "kinase_b": str(names[j]),
                "coherence": float(coherence),
            }
        )
    return found


def _bootstrap_top1(
    matrix: np.ndarray,
    target: np.ndarray,
    noise_scale: float,
    top_index: int,
    *,
    n_bootstrap: int,
    seed: int,
) -> Tuple[float, float]:
    """Fraction of noise replicates that keep the nominal top-1 kinase."""
    if noise_scale <= _EPSILON or target.size == 0:
        return 1.0, 0.0
    generator = np.random.default_rng(seed)
    per_component = noise_scale / np.sqrt(target.size)
    agreements = 0
    top_ratios: List[float] = []
    for _ in range(n_bootstrap):
        perturbed = target + generator.normal(0.0, per_component, size=target.size)
        coefficients, _ = solve_nnls(matrix, perturbed)
        ratios = normalized_ratios(coefficients)
        if ratios.size == 0:
            continue
        top_ratios.append(float(ratios[top_index]))
        if int(np.argmax(ratios)) == top_index:
            agreements += 1
    if not top_ratios:
        return float("nan"), float("nan")
    return agreements / len(top_ratios), float(np.std(top_ratios))


def _verdict(result: SiteIdentifiability, limits: Mapping[str, float]) -> str:
    if result.structurally_underdetermined or not result.unique_solution:
        return VERDICT_NON_IDENTIFIABLE
    if result.ratio_ambiguity_radius >= limits["ratio_ambiguity_broken"]:
        return VERDICT_NON_IDENTIFIABLE
    if result.top1_kinase is not None and result.top1_kinase in result.ambiguity_set:
        return VERDICT_NON_IDENTIFIABLE
    if result.ratio_ambiguity_radius >= limits["ratio_ambiguity_weak"] or result.n_redundant > 0:
        return VERDICT_WEAK
    if result.substitutable_pairs:
        return VERDICT_WEAK
    return VERDICT_IDENTIFIABLE


# ----------------------------------------------------------------------------
# Zero-imputation bias
# ----------------------------------------------------------------------------


def group_parallel_columns(
    design: np.ndarray,
    *,
    coherence_threshold: float = COHERENCE_SUBSTITUTABLE,
) -> Tuple[List[List[int]], List[int]]:
    """Partition candidates into sets whose profile columns point the same way.

    Two candidates whose columns are parallel contribute the same shape, so only
    their summed coefficient is determined by the data; the split between them is
    chosen by the solver.  Grouping is transitive so that a chain of mutually
    parallel columns becomes one set.

    Returns the groups and, separately, the indices of all-zero columns, which
    carry no shape at all.
    """
    n_columns = design.shape[1]
    norms = np.linalg.norm(design, axis=0)
    empty = [index for index in range(n_columns) if norms[index] <= _EPSILON]
    live = [index for index in range(n_columns) if norms[index] > _EPSILON]

    parent = {index: index for index in live}

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    if live:
        unit = design[:, live] / norms[live]
        gram = np.abs(unit.T @ unit)
        for i in range(len(live)):
            for j in range(i + 1, len(live)):
                if gram[i, j] >= coherence_threshold:
                    union(live[i], live[j])

    grouped: Dict[int, List[int]] = {}
    for index in live:
        grouped.setdefault(find(index), []).append(index)
    groups = [sorted(members) for _, members in sorted(grouped.items())]
    return groups, empty


@dataclass
class AmbiguityGroup:
    """A set of candidates the data cannot tell apart, with their shared share."""

    group_id: int
    members: Tuple[str, ...]
    ratio: float
    required: bool
    delta_rss: float
    within_group_norm_spread: float

    @property
    def ambiguous(self) -> bool:
        return len(self.members) > 1

    def to_dict(self) -> Dict[str, Any]:
        return _json_safe(
            {
                "group_id": self.group_id,
                "members": list(self.members),
                "ratio": self.ratio,
                "required": self.required,
                "delta_rss": self.delta_rss,
                "within_group_norm_spread": self.within_group_norm_spread,
                "ambiguous": self.ambiguous,
            }
        )


@dataclass
class AmbiguityAwareAttribution:
    """Kinase attribution reported at the resolution the data actually supports."""

    site_key: str
    attribution_supported: bool
    unsupported_reason: Optional[str]
    n_candidates: int
    n_groups: int
    relative_residual: float
    groups: List[AmbiguityGroup] = field(default_factory=list)
    per_kinase: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    reduced_diagnosis: Optional[SiteIdentifiability] = None
    empty_profile_members: Tuple[str, ...] = ()

    @property
    def resolved_ratios(self) -> Dict[str, float]:
        """Backward-compatible per-kinase ratios, split evenly inside each group."""
        return {name: float(entry["ratio"]) for name, entry in self.per_kinase.items()}

    def to_dict(self) -> Dict[str, Any]:
        return _json_safe(
            {
                "site_key": self.site_key,
                "attribution_supported": self.attribution_supported,
                "unsupported_reason": self.unsupported_reason,
                "n_candidates": self.n_candidates,
                "n_groups": self.n_groups,
                "relative_residual": self.relative_residual,
                "groups": [group.to_dict() for group in self.groups],
                "per_kinase": self.per_kinase,
                "empty_profile_members": list(self.empty_profile_members),
                "reduced_diagnosis": (
                    self.reduced_diagnosis.to_dict() if self.reduced_diagnosis else None
                ),
            }
        )


def ambiguity_aware_attribution(
    site_key: str,
    trajectory: Sequence[float] | np.ndarray,
    design: np.ndarray,
    kinase_names: Sequence[str],
    *,
    coherence_threshold: float = COHERENCE_SUBSTITUTABLE,
    relative_noise: float = DEFAULT_RELATIVE_NOISE,
    absolute_noise: Optional[float] = None,
    n_bootstrap: int = 0,
    seed: int = 0,
) -> AmbiguityAwareAttribution:
    """Attribute a site to candidate kinases only as finely as the data allows.

    Candidates sharing a profile direction are merged before fitting, so the
    reported quantity is the group's share, which is estimable, instead of a
    per-kinase split, which is not.  When no non-negative combination explains
    the trajectory the result is marked unsupported rather than being returned as
    uniform weights that look like a measurement.
    """
    target = np.asarray(trajectory, dtype=float).ravel()
    matrix = np.asarray(design, dtype=float)
    if matrix.ndim == 1:
        matrix = matrix.reshape(-1, 1)
    names = [str(name) for name in kinase_names]
    n_candidates = matrix.shape[1]

    result = AmbiguityAwareAttribution(
        site_key=site_key,
        attribution_supported=False,
        unsupported_reason="no_candidates",
        n_candidates=n_candidates,
        n_groups=0,
        relative_residual=0.0,
    )
    if n_candidates == 0:
        return result

    target_norm = float(np.linalg.norm(target))
    if target_norm <= _EPSILON:
        result.unsupported_reason = "no_signal"
        return result

    groups, empty = group_parallel_columns(matrix, coherence_threshold=coherence_threshold)
    result.empty_profile_members = tuple(names[index] for index in empty)
    if not groups:
        result.unsupported_reason = "all_profiles_empty"
        return result

    representatives = []
    spreads = []
    for members in groups:
        block = matrix[:, members]
        representatives.append(block.mean(axis=1))
        norms = np.linalg.norm(block, axis=0)
        spreads.append(float(norms.max() / norms.min() - 1.0) if norms.min() > _EPSILON else float("inf"))
    reduced = np.column_stack(representatives)
    group_labels = [f"G{index}" for index in range(len(groups))]

    coefficients, rss = solve_nnls(reduced, target)
    result.relative_residual = float(np.sqrt(max(rss, 0.0)) / max(target_norm, _EPSILON))
    noise_scale = (
        float(absolute_noise)
        if absolute_noise is not None
        else float(relative_noise) * target_norm
    )

    if coefficients.sum() <= 1e-9:
        result.unsupported_reason = "no_non_negative_explanation"
        result.n_groups = len(groups)
        result.groups = [
            AmbiguityGroup(
                group_id=index,
                members=tuple(names[member] for member in members),
                ratio=0.0,
                required=False,
                delta_rss=0.0,
                within_group_norm_spread=spreads[index],
            )
            for index, members in enumerate(groups)
        ]
        result.per_kinase = {
            names[member]: {
                "ratio": 0.0,
                "group_id": index,
                "ambiguous": len(members) > 1,
                "group_ratio": 0.0,
                "group_members": [names[other] for other in members],
                "attribution_supported": False,
            }
            for index, members in enumerate(groups)
            for member in members
        }
        return result

    ratios = normalized_ratios(coefficients)
    leave_out = _leave_one_out(reduced, target, group_labels, ratios, rss, noise_scale)
    result.reduced_diagnosis = diagnose_site(
        site_key,
        target,
        reduced,
        group_labels,
        relative_noise=relative_noise,
        absolute_noise=absolute_noise,
        n_bootstrap=n_bootstrap,
        seed=seed,
    )

    result.attribution_supported = True
    result.unsupported_reason = None
    result.n_groups = len(groups)
    for index, members in enumerate(groups):
        group_ratio = float(ratios[index])
        member_names = tuple(names[member] for member in members)
        result.groups.append(
            AmbiguityGroup(
                group_id=index,
                members=member_names,
                ratio=group_ratio,
                required=bool(leave_out[index]["required"]),
                delta_rss=float(leave_out[index]["delta_rss"]),
                within_group_norm_spread=spreads[index],
            )
        )
        for name in member_names:
            result.per_kinase[name] = {
                "ratio": group_ratio / len(member_names),
                "group_id": index,
                "ambiguous": len(member_names) > 1,
                "group_ratio": group_ratio,
                "group_members": list(member_names),
                "required": bool(leave_out[index]["required"]),
                "attribution_supported": True,
            }
    for index in empty:
        result.per_kinase[names[index]] = {
            "ratio": 0.0,
            "group_id": None,
            "ambiguous": False,
            "group_ratio": 0.0,
            "group_members": [names[index]],
            "required": False,
            "attribution_supported": False,
            "reason": "empty_profile",
        }
    return result


def zero_imputation_bias(
    site_key: str,
    trajectory: Sequence[float] | np.ndarray,
    design: np.ndarray,
    kinase_names: Sequence[str],
    observed: Sequence[bool] | np.ndarray,
    *,
    minimum_observed: int = 2,
) -> Dict[str, Any]:
    """Compare the deployed zero-imputed fit against an observed-rows-only fit.

    The production solver fills unmeasured timepoints with 0.0, which asserts
    "no change" at exactly the timepoints where nothing was measured.  Dropping
    those rows instead changes nothing about the model, only about which
    residuals are counted, so any disagreement is imputation-induced bias.
    """
    target = np.asarray(trajectory, dtype=float).ravel()
    matrix = np.asarray(design, dtype=float)
    if matrix.ndim == 1:
        matrix = matrix.reshape(-1, 1)
    mask = np.asarray(observed, dtype=bool).ravel()
    names = [str(name) for name in kinase_names]

    payload: Dict[str, Any] = {
        "site_key": site_key,
        "n_timepoints": int(target.size),
        "n_observed": int(mask.sum()),
        "missing_fraction": float(1.0 - mask.mean()) if mask.size else 0.0,
        "evaluated": False,
        "ratio_total_variation": None,
        "top1_changed": None,
        "top1_zero_imputed": None,
        "top1_observed_only": None,
    }
    if matrix.shape[1] == 0 or mask.sum() < minimum_observed or mask.all():
        return payload

    imputed_coefficients, _ = solve_nnls(matrix, target)
    masked_coefficients, _ = solve_nnls(matrix[mask, :], target[mask])
    imputed_ratios = normalized_ratios(imputed_coefficients)
    masked_ratios = normalized_ratios(masked_coefficients)
    if imputed_ratios.size == 0 or masked_ratios.size == 0:
        return payload

    top_imputed = names[int(np.argmax(imputed_ratios))]
    top_masked = names[int(np.argmax(masked_ratios))]
    payload.update(
        {
            "evaluated": True,
            "ratio_total_variation": float(0.5 * np.abs(imputed_ratios - masked_ratios).sum()),
            "top1_changed": bool(top_imputed != top_masked),
            "top1_zero_imputed": top_imputed,
            "top1_observed_only": top_masked,
        }
    )
    return payload


# ----------------------------------------------------------------------------
# Aggregation
# ----------------------------------------------------------------------------


def _quantiles(values: Sequence[float], points: Sequence[int] = (10, 50, 90)) -> Dict[str, Any]:
    finite = np.asarray([v for v in values if v is not None and np.isfinite(v)], dtype=float)
    summary: Dict[str, Any] = {
        "n": int(finite.size),
        "n_non_finite": int(len(values) - finite.size),
    }
    if finite.size == 0:
        summary.update({f"p{point}": None for point in points})
        summary["max"] = None
        return summary
    for point in points:
        summary[f"p{point}"] = float(np.percentile(finite, point))
    summary["max"] = float(finite.max())
    return summary


def summarize_diagnostics(
    diagnostics: Sequence[SiteIdentifiability],
    *,
    thresholds: Optional[Mapping[str, float]] = None,
) -> Dict[str, Any]:
    """Aggregate per-site diagnoses into the distribution-level report."""
    limits = dict(default_thresholds())
    if thresholds:
        limits.update(thresholds)

    total = len(diagnostics)
    summary: Dict[str, Any] = {
        "n_sites": total,
        "thresholds": limits,
        "verdicts": {},
        "verdict_fractions": {},
    }
    if total == 0:
        return summary

    verdicts = [item.verdict for item in diagnostics]
    for name in (
        VERDICT_IDENTIFIABLE,
        VERDICT_WEAK,
        VERDICT_NON_IDENTIFIABLE,
        VERDICT_EQUAL_WEIGHT_FALLBACK,
        VERDICT_NO_SIGNAL,
    ):
        count = verdicts.count(name)
        summary["verdicts"][name] = count
        summary["verdict_fractions"][name] = count / total

    scored = [item for item in diagnostics if item.verdict != VERDICT_NO_SIGNAL]
    summary["n_scored"] = len(scored)
    if not scored:
        return summary

    summary["distributions"] = {
        "n_candidates": _quantiles([item.n_candidates for item in scored]),
        "design_rank": _quantiles([item.design_rank for item in scored]),
        "y_negative_fraction": _quantiles([item.y_negative_fraction for item in scored]),
        "relative_residual": _quantiles([item.relative_residual for item in scored]),
        "design_condition_number": _quantiles([item.design_condition_number for item in scored]),
        "max_column_coherence": _quantiles([item.max_column_coherence for item in scored]),
        "active_sigma_min": _quantiles([item.active_sigma_min for item in scored]),
        "ratio_ambiguity_radius": _quantiles([item.ratio_ambiguity_radius for item in scored]),
        "top1_stability": _quantiles([item.top1_stability for item in scored]),
        "top1_ratio": _quantiles([item.top1_ratio for item in scored]),
    }
    summary["rates"] = {
        "structurally_underdetermined": _fraction(
            [item.structurally_underdetermined for item in scored]
        ),
        # A rank-one design offers a single shape to every candidate, so the
        # coefficients carry no kinase-specific information whatsoever.
        "rank_one_design": _fraction([item.design_rank <= 1 for item in scored]),
        "duplicate_columns": _fraction([item.max_column_coherence >= 0.9999 for item in scored]),
        # A fit this poor is no better than reporting zero contribution.
        "explains_nothing": _fraction([item.relative_residual >= 0.999 for item in scored]),
        "non_unique_solution": _fraction([not item.unique_solution for item in scored]),
        "equal_weight_fallback": _fraction([item.equal_weight_fallback for item in scored]),
        "has_redundant_candidate": _fraction([item.n_redundant > 0 for item in scored]),
        "has_substitutable_pair": _fraction([bool(item.substitutable_pairs) for item in scored]),
        "top1_in_ambiguity_set": _fraction(
            [
                item.top1_kinase is not None and item.top1_kinase in item.ambiguity_set
                for item in scored
            ]
        ),
        "top1_from_prior_profile": _fraction([item.top1_from_prior for item in scored]),
    }
    summary["mean_ambiguity_set_size"] = float(
        np.mean([len(item.ambiguity_set) for item in scored])
    )
    return summary


def _fraction(flags: Sequence[bool]) -> float:
    if not flags:
        return 0.0
    return float(np.mean([bool(flag) for flag in flags]))


def summarize_bias(records: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Aggregate the zero-imputation comparison across sites."""
    evaluated = [record for record in records if record.get("evaluated")]
    summary: Dict[str, Any] = {
        "n_records": len(records),
        "n_evaluated": len(evaluated),
        "n_complete_or_too_sparse": len(records) - len(evaluated),
    }
    if not evaluated:
        return summary
    summary["top1_reversal_rate"] = _fraction(
        [bool(record.get("top1_changed")) for record in evaluated]
    )
    summary["ratio_total_variation"] = _quantiles(
        [float(record.get("ratio_total_variation") or 0.0) for record in evaluated]
    )
    summary["missing_fraction"] = _quantiles(
        [float(record.get("missing_fraction") or 0.0) for record in evaluated]
    )
    return summary
