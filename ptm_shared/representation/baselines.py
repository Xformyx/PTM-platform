"""R0 baseline representations for the PTM representation benchmark.

These baselines exist so that a learned encoder must beat something honest.
They are mask-aware: an unobserved timepoint contributes no residual and is
never silently treated as a measured zero.

Included:

* ``handcrafted_representation`` - Representation A/B/C arms built directly from
  the preserved L1 vector, with no fitting at all.
* ``mask_aware_pca`` - EM-style truncated SVD with missing entries re-imputed
  from the current low-rank fit.
* ``mask_aware_nmf`` - masked multiplicative-update NMF on a shifted
  non-negative matrix.
* ``fpca_lite`` - minute-space Gaussian smoothing followed by mask-aware PCA,
  which respects irregular timepoint spacing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ptm_shared.representation.feature_contract import MultiViewTemporalInput
from ptm_shared.representation.layers import RepresentationVariant, resolve_variant


_EPSILON = 1e-9


@dataclass
class RepresentationResult:
    """A fitted or assembled representation with reconstruction diagnostics."""

    method: str
    embedding: np.ndarray
    reconstruction: Optional[np.ndarray] = None
    reconstruction_error: Optional[np.ndarray] = None
    feature_labels: Tuple[str, ...] = ()
    provenance: Dict[str, Any] = field(default_factory=dict)

    @property
    def n_components(self) -> int:
        return 0 if self.embedding.size == 0 else int(self.embedding.shape[1])


def _masked_error(
    values: np.ndarray,
    observed: np.ndarray,
    reconstruction: np.ndarray,
) -> np.ndarray:
    """Per-row RMSE over observed entries only."""
    residual = np.where(observed, values - reconstruction, 0.0)
    counts = observed.sum(axis=1)
    squared = (residual ** 2).sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        rmse = np.sqrt(np.divide(squared, counts, out=np.full_like(squared, np.nan), where=counts > 0))
    return rmse


def _column_means(values: np.ndarray, observed: np.ndarray) -> np.ndarray:
    counts = observed.sum(axis=0)
    totals = np.where(observed, values, 0.0).sum(axis=0)
    means = np.zeros(values.shape[1], dtype=float)
    valid = counts > 0
    means[valid] = totals[valid] / counts[valid]
    return means


def _initial_fill(values: np.ndarray, observed: np.ndarray) -> np.ndarray:
    filled = np.array(values, dtype=float, copy=True)
    means = _column_means(values, observed)
    for column in range(values.shape[1]):
        missing = ~observed[:, column]
        filled[missing, column] = means[column]
    return np.nan_to_num(filled, nan=0.0, posinf=0.0, neginf=0.0)


def handcrafted_representation(
    multiview: MultiViewTemporalInput,
    variant: str | RepresentationVariant = "B",
) -> RepresentationResult:
    """Assemble a non-learned Representation A/B/C arm from the L1 vector.

    Arm A is the Track 2 trajectory alone.  Arm B adds the protein-context
    trajectory and the handcrafted quality features that the current PTM Vector
    already carries.  Arm C adds static motif descriptors, which is the arm that
    must be checked for prior dominance and kinase-family leakage.
    """
    arm = variant if isinstance(variant, RepresentationVariant) else resolve_variant(variant)
    if arm.learned:
        raise ValueError(
            f"Variant {arm.variant_id} is a learned arm; use the encoder instead of "
            "handcrafted_representation."
        )

    blocks: List[np.ndarray] = []
    labels: List[str] = []
    timepoints = multiview.timepoints

    target = multiview.target.filled(0.0)
    blocks.append(target)
    labels.extend(f"track2::{timepoint}" for timepoint in timepoints)
    blocks.append(multiview.target.observed.astype(float))
    labels.extend(f"track2_observed::{timepoint}" for timepoint in timepoints)

    if "protein_context" in arm.views:
        blocks.append(multiview.protein_context.filled(0.0))
        labels.extend(f"protein_context::{timepoint}" for timepoint in timepoints)
        blocks.append(multiview.protein_context.observed.astype(float))
        labels.extend(f"protein_observed::{timepoint}" for timepoint in timepoints)

    if "quality" in arm.views:
        # Quality enters as an explicit handcrafted feature here because arm B is
        # by definition the current L1 vector.  The learned arms keep q-values
        # out of the latent input and use them as loss weights instead.
        blocks.append(multiview.quality_weight)
        labels.extend(f"quality_weight::{timepoint}" for timepoint in timepoints)

    if "motif" in arm.views and multiview.motif_features is not None:
        blocks.append(multiview.motif_features)
        labels.extend(f"motif::{term}" for term in multiview.motif_labels)

    embedding = (
        np.concatenate(blocks, axis=1)
        if blocks
        else np.zeros((multiview.n_sites, 0), dtype=float)
    )
    return RepresentationResult(
        method=f"handcrafted_{arm.name}",
        embedding=embedding,
        reconstruction=target,
        reconstruction_error=np.zeros(multiview.n_sites, dtype=float),
        feature_labels=tuple(labels),
        provenance={
            "variant_id": arm.variant_id,
            "variant_name": arm.name,
            "learned": False,
            "views": list(arm.views),
            "quality_as_feature": "quality" in arm.views,
            "motif_as_feature": "motif" in arm.views,
            "n_features": int(embedding.shape[1]) if embedding.size else 0,
        },
    )


def mask_aware_pca(
    values: np.ndarray,
    observed: np.ndarray,
    *,
    n_components: int = 4,
    max_iterations: int = 60,
    tolerance: float = 1e-6,
) -> RepresentationResult:
    """Truncated SVD with EM imputation of unobserved entries."""
    values = np.asarray(values, dtype=float)
    observed = np.asarray(observed, dtype=bool)
    n_rows, n_columns = values.shape
    rank = int(max(1, min(n_components, min(n_rows, n_columns))))
    if n_rows == 0 or n_columns == 0:
        return RepresentationResult(
            method="mask_aware_pca",
            embedding=np.zeros((n_rows, 0), dtype=float),
            provenance={"n_components": 0, "converged": True, "iterations": 0},
        )

    working = _initial_fill(values, observed)
    mean = working.mean(axis=0, keepdims=True)
    scores = np.zeros((n_rows, rank), dtype=float)
    components = np.zeros((rank, n_columns), dtype=float)
    previous = np.inf
    iterations = 0
    converged = False

    for iterations in range(1, max_iterations + 1):
        centered = working - mean
        left, singular, right = np.linalg.svd(centered, full_matrices=False)
        scores = left[:, :rank] * singular[:rank]
        components = right[:rank]
        reconstruction = scores @ components + mean
        working = np.where(observed, values, reconstruction)
        working = np.nan_to_num(working, nan=0.0, posinf=0.0, neginf=0.0)
        mean = working.mean(axis=0, keepdims=True)
        error = float(np.nanmean(_masked_error(values, observed, reconstruction) ** 2))
        if not np.isfinite(error):
            break
        if abs(previous - error) <= tolerance * max(1.0, abs(previous)):
            converged = True
            previous = error
            break
        previous = error

    reconstruction = scores @ components + mean
    explained = float(np.sum(np.var(scores, axis=0)))
    total = float(np.sum(np.var(np.where(observed, values, reconstruction), axis=0)))
    return RepresentationResult(
        method="mask_aware_pca",
        embedding=scores,
        reconstruction=reconstruction,
        reconstruction_error=_masked_error(values, observed, reconstruction),
        feature_labels=tuple(f"pc{index + 1}" for index in range(rank)),
        provenance={
            "n_components": rank,
            "iterations": int(iterations),
            "converged": bool(converged),
            "explained_variance_ratio": round(explained / total, 6) if total > 0 else None,
            "missing_policy": "em_imputed_from_low_rank_fit",
        },
    )


def mask_aware_nmf(
    values: np.ndarray,
    observed: np.ndarray,
    *,
    n_components: int = 4,
    max_iterations: int = 250,
    tolerance: float = 1e-7,
    seed: int = 0,
) -> RepresentationResult:
    """Masked multiplicative-update NMF on a shift-to-non-negative matrix."""
    values = np.asarray(values, dtype=float)
    observed = np.asarray(observed, dtype=bool)
    n_rows, n_columns = values.shape
    rank = int(max(1, min(n_components, min(n_rows, n_columns) or 1)))
    if n_rows == 0 or n_columns == 0 or not observed.any():
        return RepresentationResult(
            method="mask_aware_nmf",
            embedding=np.zeros((n_rows, 0), dtype=float),
            provenance={"n_components": 0, "converged": True, "iterations": 0},
        )

    observed_values = values[observed]
    shift = float(min(0.0, np.min(observed_values)))
    target = np.where(observed, values - shift, 0.0)
    mask = observed.astype(float)

    rng = np.random.default_rng(int(seed))
    scale = float(np.sqrt(np.mean(observed_values - shift) / rank)) if rank else 1.0
    scale = scale if np.isfinite(scale) and scale > 0 else 1.0
    left = np.abs(rng.normal(loc=scale, scale=scale * 0.1, size=(n_rows, rank))) + _EPSILON
    right = np.abs(rng.normal(loc=scale, scale=scale * 0.1, size=(rank, n_columns))) + _EPSILON

    previous = np.inf
    iterations = 0
    converged = False
    for iterations in range(1, max_iterations + 1):
        estimate = mask * (left @ right)
        right *= (left.T @ target) / (left.T @ estimate + _EPSILON)
        estimate = mask * (left @ right)
        left *= (target @ right.T) / (estimate @ right.T + _EPSILON)
        estimate = mask * (left @ right)
        error = float(np.sum((mask * (target - estimate)) ** 2))
        if abs(previous - error) <= tolerance * max(1.0, abs(previous)):
            converged = True
            previous = error
            break
        previous = error

    reconstruction = left @ right + shift
    return RepresentationResult(
        method="mask_aware_nmf",
        embedding=left,
        reconstruction=reconstruction,
        reconstruction_error=_masked_error(values, observed, reconstruction),
        feature_labels=tuple(f"nmf{index + 1}" for index in range(rank)),
        provenance={
            "n_components": rank,
            "iterations": int(iterations),
            "converged": bool(converged),
            "non_negative_shift": shift,
            "seed": int(seed),
            "missing_policy": "masked_out_of_multiplicative_updates",
        },
    )


def smooth_trajectories(
    values: np.ndarray,
    observed: np.ndarray,
    time_minutes: np.ndarray,
    *,
    bandwidth: Optional[float] = None,
) -> np.ndarray:
    """Gaussian-kernel smoothing in log-minute space over observed entries.

    Smoothing happens in minute space so that a 30 to 60 minute gap is not
    treated like a 0.5 to 1 minute gap.
    """
    values = np.asarray(values, dtype=float)
    observed = np.asarray(observed, dtype=bool)
    minutes = np.asarray(time_minutes, dtype=float)
    if values.size == 0:
        return np.zeros_like(values)

    axis = np.log1p(np.clip(np.where(np.isfinite(minutes), minutes, 0.0), 0.0, None))
    if bandwidth is None:
        gaps = np.diff(np.sort(axis))
        positive = gaps[gaps > 0]
        bandwidth = float(np.median(positive)) if positive.size else 1.0
    bandwidth = float(bandwidth) if bandwidth and bandwidth > 0 else 1.0

    distance = axis[:, None] - axis[None, :]
    kernel = np.exp(-0.5 * (distance / bandwidth) ** 2)

    weights = observed.astype(float) @ kernel
    weighted = np.where(observed, values, 0.0) @ kernel
    smoothed = np.zeros_like(values)
    usable = weights > _EPSILON
    smoothed[usable] = weighted[usable] / weights[usable]
    return smoothed


def fpca_lite(
    values: np.ndarray,
    observed: np.ndarray,
    time_minutes: np.ndarray,
    *,
    n_components: int = 4,
    bandwidth: Optional[float] = None,
) -> RepresentationResult:
    """Functional-PCA-style baseline: minute-space smoothing then PCA."""
    smoothed = smooth_trajectories(values, observed, time_minutes, bandwidth=bandwidth)
    fitted = mask_aware_pca(
        smoothed,
        np.ones_like(observed, dtype=bool),
        n_components=n_components,
    )
    provenance = dict(fitted.provenance)
    provenance.update(
        {
            "smoothing": "gaussian_kernel_in_log_minute_space",
            "bandwidth": bandwidth,
            "missing_policy": "kernel_weighted_over_observed_only",
        }
    )
    return RepresentationResult(
        method="fpca_lite",
        embedding=fitted.embedding,
        reconstruction=fitted.reconstruction,
        reconstruction_error=_masked_error(values, observed, fitted.reconstruction),
        feature_labels=tuple(f"fpc{index + 1}" for index in range(fitted.n_components)),
        provenance=provenance,
    )


def run_r0_baselines(
    multiview: MultiViewTemporalInput,
    *,
    n_components: int = 4,
    seed: int = 0,
) -> Dict[str, RepresentationResult]:
    """Fit the full R0 baseline set on the Track 2 view."""
    values = multiview.target.values
    observed = multiview.target.observed
    return {
        "mask_aware_pca": mask_aware_pca(values, observed, n_components=n_components),
        "mask_aware_nmf": mask_aware_nmf(values, observed, n_components=n_components, seed=seed),
        "fpca_lite": fpca_lite(values, observed, multiview.time_minutes, n_components=n_components),
    }
