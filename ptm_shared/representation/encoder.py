"""R1 mask-aware self-supervised temporal PTM encoder.

The encoder learns an L4 Learned Temporal PTM Embedding from the L3 multi-view
input.  It is intentionally small, dependency-light (NumPy only), and seeded, so
that benchmark results are reproducible and so that adding representation
learning does not add an undeclared PyTorch/CUDA requirement to the workers.

Design constraints inherited from the integration review:

* Track 2 is the primary reconstruction target; protein context and Track 1 are
  auxiliary branches that never replace it.
* Track 1 enters through an availability-gated branch.  Sites without a
  qualified pair contribute no Track 1 residual and are not fed a fabricated 0.
* q-values are loss weights, not input dimensions.
* Irregular timepoint spacing enters through minute-based time encoding and a
  gap-aware smoothness penalty, so a shuffled time order is not equivalent.
* Self-supervision is masked reconstruction: entries hidden from the input must
  still be predicted, and a disjoint held-out set is never trained on.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

import numpy as np

from ptm_shared.representation.feature_contract import MultiViewTemporalInput
from ptm_shared.representation.layers import CONTRACT_VERSION, LAYER_L4


ENCODER_VERSION = "1.0.0"

DEFAULT_ENCODER_CONFIG: Dict[str, Any] = {
    "latent_dim": 16,
    "hidden_dim": 64,
    "epochs": 300,
    "learning_rate": 0.01,
    "l2": 1e-4,
    "input_mask_fraction": 0.15,
    "holdout_fraction": 0.10,
    "auxiliary_weight": 0.30,
    "smoothness_weight": 0.05,
    "n_perturbations": 5,
    "perturbation_mask_fraction": 0.15,
    "seed": 0,
    "use_protein_context": True,
    "use_track1": True,
    "standardize_inputs": True,
}


def _merged_config(config: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    merged = dict(DEFAULT_ENCODER_CONFIG)
    for key, value in dict(config or {}).items():
        if key in merged and value is not None:
            merged[key] = value
    merged["latent_dim"] = max(1, int(merged["latent_dim"]))
    merged["hidden_dim"] = max(merged["latent_dim"], int(merged["hidden_dim"]))
    merged["epochs"] = max(1, int(merged["epochs"]))
    merged["n_perturbations"] = max(0, int(merged["n_perturbations"]))
    merged["learning_rate"] = float(merged["learning_rate"])
    merged["l2"] = float(merged["l2"])
    merged["input_mask_fraction"] = float(np.clip(merged["input_mask_fraction"], 0.0, 0.9))
    merged["holdout_fraction"] = float(np.clip(merged["holdout_fraction"], 0.0, 0.5))
    merged["perturbation_mask_fraction"] = float(np.clip(merged["perturbation_mask_fraction"], 0.0, 0.9))
    merged["auxiliary_weight"] = max(0.0, float(merged["auxiliary_weight"]))
    merged["smoothness_weight"] = max(0.0, float(merged["smoothness_weight"]))
    merged["seed"] = int(merged["seed"])
    merged["use_protein_context"] = bool(merged["use_protein_context"])
    merged["use_track1"] = bool(merged["use_track1"])
    merged["standardize_inputs"] = bool(merged["standardize_inputs"])
    return merged


@dataclass
class EncoderResult:
    """Fitted L4 embedding plus the diagnostics required for secondary use."""

    embedding: np.ndarray
    reconstruction: np.ndarray
    reconstruction_error: np.ndarray
    heldout_reconstruction_error: float
    train_reconstruction_error: float
    embedding_uncertainty: np.ndarray
    perturbed_embeddings: List[np.ndarray] = field(default_factory=list)
    site_keys: List[str] = field(default_factory=list)
    training_history: List[Dict[str, float]] = field(default_factory=list)
    provenance: Dict[str, Any] = field(default_factory=dict)

    @property
    def method(self) -> str:
        return "masked_temporal_encoder"

    @property
    def n_components(self) -> int:
        return 0 if self.embedding.size == 0 else int(self.embedding.shape[1])


def _view_stack(
    multiview: MultiViewTemporalInput,
    config: Mapping[str, Any],
) -> Tuple[List[str], List[np.ndarray], List[np.ndarray]]:
    """Return the ordered view names, values, and observation masks."""
    names = [multiview.target.name]
    values = [multiview.target.values]
    masks = [multiview.target.observed]
    if config["use_protein_context"]:
        names.append(multiview.protein_context.name)
        values.append(multiview.protein_context.values)
        masks.append(multiview.protein_context.observed)
    if config["use_track1"]:
        names.append(multiview.track1.name)
        values.append(multiview.track1.values)
        masks.append(multiview.track1.observed)
    return names, values, masks


def _build_design_matrix(
    values: List[np.ndarray],
    masks: List[np.ndarray],
    input_masks: List[np.ndarray],
    time_encoding: np.ndarray,
    extra_scalars: Optional[np.ndarray],
) -> np.ndarray:
    """Assemble ``(n_sites, n_timepoints * block + extras)`` encoder input.

    Each timepoint block carries, per view, the masked value and its observation
    indicator, followed by the shared minute-based time encoding.  Values hidden
    by ``input_masks`` are removed from the input but may remain in the loss.
    """
    n_rows = values[0].shape[0]
    n_time = values[0].shape[1]
    blocks: List[np.ndarray] = []
    for time_index in range(n_time):
        for view_values, view_mask, view_input_mask in zip(values, masks, input_masks):
            visible = view_mask[:, time_index] & view_input_mask[:, time_index]
            column = np.where(visible, np.nan_to_num(view_values[:, time_index], nan=0.0), 0.0)
            blocks.append(column.reshape(-1, 1))
            blocks.append(visible.astype(float).reshape(-1, 1))
        if time_encoding.size:
            encoding = np.repeat(time_encoding[time_index].reshape(1, -1), n_rows, axis=0)
            blocks.append(encoding)
    if extra_scalars is not None and extra_scalars.size:
        blocks.append(extra_scalars)
    if not blocks:
        return np.zeros((n_rows, 0), dtype=float)
    return np.concatenate(blocks, axis=1)


def _split_masks(
    observed: np.ndarray,
    holdout_fraction: float,
    rng: np.random.Generator,
) -> Tuple[np.ndarray, np.ndarray]:
    """Split observed Track 2 entries into training and held-out sets.

    Rows keep at least two training entries so that no site is represented only
    by held-out values.  Short time courses still yield one held-out entry, which
    is what makes the time-validity gate evaluable.
    """
    holdout = np.zeros_like(observed, dtype=bool)
    if holdout_fraction <= 0.0:
        return observed.copy(), holdout
    for row in range(observed.shape[0]):
        columns = np.flatnonzero(observed[row])
        if columns.size < 4:
            continue
        count = max(1, int(np.floor(columns.size * holdout_fraction)))
        count = min(count, columns.size - 2)
        if count < 1:
            continue
        chosen = rng.choice(columns, size=count, replace=False)
        holdout[row, chosen] = True
    return observed & ~holdout, holdout


def _smoothness_weights(delta_minutes: np.ndarray) -> np.ndarray:
    """Gap-aware smoothness weights: wide gaps are penalised less."""
    deltas = np.asarray(delta_minutes, dtype=float)
    if deltas.size <= 1:
        return np.zeros(max(deltas.size - 1, 0), dtype=float)
    gaps = np.clip(deltas[1:], 0.0, None)
    scale = float(np.median(gaps[gaps > 0])) if np.any(gaps > 0) else 1.0
    scale = scale if scale > 0 else 1.0
    return 1.0 / (1.0 + gaps / scale)


def fit_masked_temporal_encoder(
    multiview: MultiViewTemporalInput,
    *,
    config: Optional[Mapping[str, Any]] = None,
) -> EncoderResult:
    """Fit the L4 encoder on an L3 multi-view input.

    The returned embedding is secondary evidence.  It must not be substituted for
    Track 2 trajectories in canonical co-wave detection or TMM deconvolution.
    """
    effective = _merged_config(config)
    n_sites = multiview.n_sites
    n_time = multiview.n_timepoints
    view_names, view_values, view_masks = _view_stack(multiview, effective)
    n_views = len(view_names)

    provenance: Dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "layer": LAYER_L4,
        "encoder_version": ENCODER_VERSION,
        "config": effective,
        "config_sha256": hashlib.sha256(
            json.dumps(effective, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest(),
        "views": view_names,
        "primary_target": multiview.target.name,
        "track1_branch": "availability_gated" if effective["use_track1"] else "disabled",
        "qvalue_role": "loss_weight_only",
        "time_order": (multiview.provenance or {}).get("time_order", "observed"),
        "timepoints": list(multiview.timepoints),
        "n_sites": n_sites,
        "n_timepoints": n_time,
        "secondary_use_only": True,
        "primary_scores_unchanged": True,
    }

    if n_sites == 0 or n_time == 0:
        return EncoderResult(
            embedding=np.zeros((n_sites, 0), dtype=float),
            reconstruction=np.zeros((n_sites, n_time), dtype=float),
            reconstruction_error=np.zeros(n_sites, dtype=float),
            heldout_reconstruction_error=float("nan"),
            train_reconstruction_error=float("nan"),
            embedding_uncertainty=np.zeros(n_sites, dtype=float),
            site_keys=list(multiview.site_keys),
            provenance={**provenance, "status": "empty_input"},
        )

    rng = np.random.default_rng(effective["seed"])
    train_target_mask, holdout_target_mask = _split_masks(
        multiview.target.observed, effective["holdout_fraction"], rng
    )

    # Loss masks: Track 2 uses the training split; auxiliary views use their own
    # observation masks so that unavailable Track 1 pairs contribute nothing.
    loss_masks = [train_target_mask]
    for index in range(1, n_views):
        loss_masks.append(view_masks[index])

    # Input masks hide the held-out Track 2 entries from the encoder input.
    base_input_masks = [~holdout_target_mask]
    for _ in range(1, n_views):
        base_input_masks.append(np.ones((n_sites, n_time), dtype=bool))

    weight = np.where(train_target_mask, multiview.quality_weight, 0.0)
    # Only the Track 1 gate is passed as a site-level scalar, and only when that
    # branch is active.  Aggregate coverage statistics are deliberately withheld:
    # they would let the embedding encode missingness rate instead of temporal
    # pattern, which is exactly what the missingness-validity gate rejects.
    extra_scalars = (
        multiview.track1_available.astype(float).reshape(-1, 1)
        if effective["use_track1"]
        else None
    )

    reference_matrix = _build_design_matrix(
        view_values, view_masks, base_input_masks, multiview.time_encoding, extra_scalars
    )
    if effective["standardize_inputs"] and reference_matrix.size:
        centre = reference_matrix.mean(axis=0, keepdims=True)
        spread = reference_matrix.std(axis=0, keepdims=True)
        spread[spread < 1e-8] = 1.0
    else:
        centre = np.zeros((1, reference_matrix.shape[1]), dtype=float)
        spread = np.ones((1, max(reference_matrix.shape[1], 1)), dtype=float)

    def _standardize(matrix: np.ndarray) -> np.ndarray:
        if not matrix.size:
            return matrix
        return (matrix - centre) / spread

    input_dim = reference_matrix.shape[1]
    output_dim = n_time * n_views
    latent_dim = min(effective["latent_dim"], max(1, input_dim))
    hidden_dim = max(latent_dim, min(effective["hidden_dim"], max(latent_dim, input_dim)))

    def _init(rows: int, columns: int) -> np.ndarray:
        limit = float(np.sqrt(6.0 / max(rows + columns, 1)))
        return rng.uniform(-limit, limit, size=(rows, columns))

    params: Dict[str, np.ndarray] = {
        "W1": _init(input_dim, hidden_dim),
        "b1": np.zeros(hidden_dim),
        "W2": _init(hidden_dim, latent_dim),
        "b2": np.zeros(latent_dim),
        "W3": _init(latent_dim, hidden_dim),
        "b3": np.zeros(hidden_dim),
        "W4": _init(hidden_dim, output_dim),
        "b4": np.zeros(output_dim),
    }
    moment1 = {key: np.zeros_like(value) for key, value in params.items()}
    moment2 = {key: np.zeros_like(value) for key, value in params.items()}

    targets = [np.nan_to_num(values, nan=0.0) for values in view_values]
    view_weights = [np.where(loss_masks[0], weight, 0.0)]
    for index in range(1, n_views):
        view_weights.append(loss_masks[index].astype(float) * effective["auxiliary_weight"])
    weight_totals = [float(matrix.sum()) for matrix in view_weights]

    smooth_weights = _smoothness_weights(multiview.delta_minutes)
    smooth_scale = effective["smoothness_weight"]

    def _forward(matrix: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        pre1 = matrix @ params["W1"] + params["b1"]
        hidden1 = np.tanh(pre1)
        latent = hidden1 @ params["W2"] + params["b2"]
        pre3 = latent @ params["W3"] + params["b3"]
        hidden3 = np.tanh(pre3)
        output = hidden3 @ params["W4"] + params["b4"]
        return hidden1, latent, hidden3, output

    history: List[Dict[str, float]] = []
    learning_rate = effective["learning_rate"]
    step = 0

    for epoch in range(effective["epochs"]):
        # Mask-aware self-supervision: hide a random subset of visible Track 2
        # entries from the input while still requiring their reconstruction.
        epoch_input_masks = [mask.copy() for mask in base_input_masks]
        if effective["input_mask_fraction"] > 0.0:
            corruption = rng.random((n_sites, n_time)) < effective["input_mask_fraction"]
            epoch_input_masks[0] = epoch_input_masks[0] & ~(corruption & train_target_mask)
        design = _standardize(
            _build_design_matrix(
                view_values, view_masks, epoch_input_masks, multiview.time_encoding, extra_scalars
            )
        )

        hidden1, latent, hidden3, output = _forward(design)
        grad_output = np.zeros_like(output)
        recon_loss = 0.0
        for index in range(n_views):
            columns = slice(index * n_time, (index + 1) * n_time)
            predicted = output[:, columns]
            residual = (predicted - targets[index]) * view_weights[index]
            total = weight_totals[index]
            if total <= 0.0:
                continue
            recon_loss += float(np.sum(residual * (predicted - targets[index]))) / total
            grad_output[:, columns] += 2.0 * residual / total

        smooth_loss = 0.0
        if smooth_scale > 0.0 and smooth_weights.size:
            predicted = output[:, 0:n_time]
            differences = predicted[:, 1:] - predicted[:, :-1]
            weighted = differences * smooth_weights.reshape(1, -1)
            norm = float(n_sites * max(smooth_weights.size, 1))
            smooth_loss = smooth_scale * float(np.sum(weighted * differences)) / norm
            gradient = 2.0 * smooth_scale * weighted / norm
            grad_output[:, 1:n_time] += gradient
            grad_output[:, 0 : n_time - 1] -= gradient

        grad_W4 = hidden3.T @ grad_output
        grad_b4 = grad_output.sum(axis=0)
        grad_hidden3 = grad_output @ params["W4"].T
        grad_pre3 = grad_hidden3 * (1.0 - hidden3 ** 2)
        grad_W3 = latent.T @ grad_pre3
        grad_b3 = grad_pre3.sum(axis=0)
        grad_latent = grad_pre3 @ params["W3"].T
        grad_W2 = hidden1.T @ grad_latent
        grad_b2 = grad_latent.sum(axis=0)
        grad_hidden1 = grad_latent @ params["W2"].T
        grad_pre1 = grad_hidden1 * (1.0 - hidden1 ** 2)
        grad_W1 = design.T @ grad_pre1
        grad_b1 = grad_pre1.sum(axis=0)

        gradients = {
            "W1": grad_W1 + 2.0 * effective["l2"] * params["W1"],
            "b1": grad_b1,
            "W2": grad_W2 + 2.0 * effective["l2"] * params["W2"],
            "b2": grad_b2,
            "W3": grad_W3 + 2.0 * effective["l2"] * params["W3"],
            "b3": grad_b3,
            "W4": grad_W4 + 2.0 * effective["l2"] * params["W4"],
            "b4": grad_b4,
        }

        step += 1
        for key, gradient in gradients.items():
            moment1[key] = 0.9 * moment1[key] + 0.1 * gradient
            moment2[key] = 0.999 * moment2[key] + 0.001 * (gradient ** 2)
            corrected1 = moment1[key] / (1.0 - 0.9 ** step)
            corrected2 = moment2[key] / (1.0 - 0.999 ** step)
            params[key] -= learning_rate * corrected1 / (np.sqrt(corrected2) + 1e-8)

        if epoch % 10 == 0 or epoch == effective["epochs"] - 1:
            history.append(
                {
                    "epoch": int(epoch),
                    "reconstruction_loss": round(float(recon_loss), 8),
                    "smoothness_loss": round(float(smooth_loss), 8),
                }
            )

    design = _standardize(
        _build_design_matrix(
            view_values, view_masks, base_input_masks, multiview.time_encoding, extra_scalars
        )
    )
    _, latent, _, output = _forward(design)
    reconstruction = output[:, 0:n_time]

    def _rmse(mask: np.ndarray) -> np.ndarray:
        residual = np.where(mask, reconstruction - targets[0], 0.0)
        counts = mask.sum(axis=1)
        squared = (residual ** 2).sum(axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.sqrt(
                np.divide(squared, counts, out=np.full_like(squared, np.nan), where=counts > 0)
            )

    train_rmse = _rmse(train_target_mask)
    holdout_rmse = _rmse(holdout_target_mask)
    site_error = np.where(np.isfinite(holdout_rmse), holdout_rmse, train_rmse)

    def _mean_finite(values: np.ndarray) -> float:
        finite = values[np.isfinite(values)] if values.size else values
        return float(np.mean(finite)) if finite.size else float("nan")

    perturbed: List[np.ndarray] = []
    for index in range(effective["n_perturbations"]):
        perturb_rng = np.random.default_rng(effective["seed"] + 1000 + index)
        masks = [mask.copy() for mask in base_input_masks]
        corruption = perturb_rng.random((n_sites, n_time)) < effective["perturbation_mask_fraction"]
        masks[0] = masks[0] & ~(corruption & train_target_mask)
        perturbed_design = _standardize(
            _build_design_matrix(view_values, view_masks, masks, multiview.time_encoding, extra_scalars)
        )
        _, perturbed_latent, _, _ = _forward(perturbed_design)
        perturbed.append(perturbed_latent)

    if perturbed:
        stacked = np.stack(perturbed, axis=0)
        uncertainty = stacked.std(axis=0).mean(axis=1)
    else:
        uncertainty = np.zeros(n_sites, dtype=float)

    provenance.update(
        {
            "latent_dim": int(latent.shape[1]),
            "hidden_dim": int(hidden_dim),
            "input_dim": int(input_dim),
            "output_dim": int(output_dim),
            "n_train_entries": int(train_target_mask.sum()),
            "n_heldout_entries": int(holdout_target_mask.sum()),
            "n_track1_observed_entries": int(multiview.track1.observed.sum()) if effective["use_track1"] else 0,
            "self_supervision": "masked_reconstruction_with_disjoint_holdout",
        }
    )

    return EncoderResult(
        embedding=latent,
        reconstruction=reconstruction,
        reconstruction_error=site_error,
        heldout_reconstruction_error=_mean_finite(holdout_rmse),
        train_reconstruction_error=_mean_finite(train_rmse),
        embedding_uncertainty=uncertainty,
        perturbed_embeddings=perturbed,
        site_keys=list(multiview.site_keys),
        training_history=history,
        provenance=provenance,
    )
