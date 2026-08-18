"""R1.5 Representation A-E ablation and the R2/R3 adoption gates.

The benchmark answers one question: does a learned temporal representation
improve the reproducibility and profile quality of the raw co-wave/TMM evidence?
It is not a kinase prediction contest, and it never rewrites a primary score.

``evaluate_adoption_gates`` implements the six gates from the integration review.
``production_influence_allowed`` is False unless every gate passes, which is what
keeps the learned layer out of the production kinase ranking by default.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

from ptm_shared.representation.baselines import (
    RepresentationResult,
    handcrafted_representation,
    run_r0_baselines,
)
from ptm_shared.representation.encoder import fit_masked_temporal_encoder
from ptm_shared.representation.feature_contract import MultiViewTemporalInput
from ptm_shared.representation.layers import (
    ADOPTION_GATES,
    CONTRACT_VERSION,
    PRIMARY_ARM_PREFERENCE,
    PRIMARY_SCORE_INPUTS_LOCKED,
    RepresentationVariant,
    resolve_variant,
    select_primary_variant,
    variant_order,
)
from ptm_shared.representation.metrics import (
    embedding_neighbor_stability,
    representation_track_concordance,
    standardize_rows,
    top_k_neighbors,
)


DEFAULT_BENCHMARK_CONFIG: Dict[str, Any] = {
    "neighbors": 10,
    "cluster_distance_threshold": 0.30,
    "minimum_cluster_size": 2,
    "bootstrap_rounds": 10,
    "bootstrap_site_fraction": 0.80,
    "leave_one_out": True,
    "leave_one_out_epoch_scale": 0.25,
    "baseline_components": 4,
    "seed": 0,
    # Gate thresholds.
    "time_validity_margin": 0.01,
    "missingness_r2_max": 0.25,
    "raw_concordance_min": 0.50,
    "minimum_sites": 8,
    # Missingness-validity gate: artificial masking probe.
    "artificial_mask_fraction": 0.15,
    "missingness_pattern_ari_min": 0.20,
}


def _merged_config(config: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    merged = dict(DEFAULT_BENCHMARK_CONFIG)
    for key, value in dict(config or {}).items():
        if key in merged and value is not None:
            merged[key] = value
    merged["neighbors"] = max(1, int(merged["neighbors"]))
    merged["bootstrap_rounds"] = max(0, int(merged["bootstrap_rounds"]))
    merged["minimum_cluster_size"] = max(2, int(merged["minimum_cluster_size"]))
    merged["baseline_components"] = max(1, int(merged["baseline_components"]))
    merged["minimum_sites"] = max(2, int(merged["minimum_sites"]))
    merged["bootstrap_site_fraction"] = float(np.clip(merged["bootstrap_site_fraction"], 0.1, 1.0))
    merged["artificial_mask_fraction"] = float(np.clip(merged["artificial_mask_fraction"], 0.0, 0.5))
    merged["missingness_pattern_ari_min"] = float(np.clip(merged["missingness_pattern_ari_min"], 0.0, 1.0))
    merged["cluster_distance_threshold"] = float(np.clip(merged["cluster_distance_threshold"], 0.0, 2.0))
    merged["leave_one_out"] = bool(merged["leave_one_out"])
    merged["seed"] = int(merged["seed"])
    return merged


# ---------------------------------------------------------------------------
# Clustering and agreement helpers (no scikit-learn dependency)
# ---------------------------------------------------------------------------


def cluster_representation(
    embedding: np.ndarray,
    *,
    distance_threshold: float = 0.30,
    minimum_cluster_size: int = 2,
) -> np.ndarray:
    """Average-linkage clustering on cosine distance of row-standardized rows.

    Mirrors the canonical wave engine's structure (average linkage on a
    correlation-style distance) so that cluster stability is comparable between
    handcrafted and learned representations.
    """
    normalized = standardize_rows(embedding)
    n_rows = normalized.shape[0]
    if n_rows < 2 or normalized.shape[1] == 0:
        return np.zeros(n_rows, dtype=int)
    similarity = np.clip(normalized @ normalized.T, -1.0, 1.0)
    distance = np.maximum(1.0 - similarity, 0.0)
    distance = (distance + distance.T) / 2.0
    np.fill_diagonal(distance, 0.0)
    labels = fcluster(
        linkage(squareform(distance, checks=False), method="average"),
        t=float(distance_threshold),
        criterion="distance",
    )
    labels = np.asarray(labels, dtype=int)
    counts = {label: int(np.sum(labels == label)) for label in np.unique(labels)}
    return np.array(
        [label if counts[label] >= minimum_cluster_size else 0 for label in labels],
        dtype=int,
    )


def adjusted_rand_index(left: Sequence[int], right: Sequence[int]) -> float:
    """Adjusted Rand Index between two labelings."""
    a = np.asarray(list(left))
    b = np.asarray(list(right))
    if a.size != b.size or a.size < 2:
        return float("nan")
    a_labels, a_index = np.unique(a, return_inverse=True)
    b_labels, b_index = np.unique(b, return_inverse=True)
    table = np.zeros((a_labels.size, b_labels.size), dtype=float)
    np.add.at(table, (a_index, b_index), 1.0)

    def _pairs(counts: np.ndarray) -> float:
        return float(np.sum(counts * (counts - 1.0) / 2.0))

    index = _pairs(table)
    expected_a = _pairs(table.sum(axis=1))
    expected_b = _pairs(table.sum(axis=0))
    total = float(a.size * (a.size - 1) / 2.0)
    expected = expected_a * expected_b / total if total else 0.0
    maximum = (expected_a + expected_b) / 2.0
    if abs(maximum - expected) < 1e-12:
        return 1.0 if abs(index - expected) < 1e-12 else 0.0
    return float((index - expected) / (maximum - expected))


def neighbor_label_enrichment(
    embedding: np.ndarray,
    labels: Sequence[Optional[str]],
    *,
    k: int = 10,
) -> Optional[float]:
    """Mean fraction of top-k neighbours sharing the reference label."""
    neighbours = top_k_neighbors(embedding, k)
    if neighbours.shape[1] == 0:
        return None
    scores: List[float] = []
    for row, label in enumerate(labels):
        if label is None:
            continue
        partners = [index for index in neighbours[row] if labels[index] is not None]
        if not partners:
            continue
        scores.append(float(np.mean([1.0 if labels[index] == label else 0.0 for index in partners])))
    return round(float(np.mean(scores)), 6) if scores else None


def cluster_purity(predicted: Sequence[int], reference: Sequence[Optional[str]]) -> Optional[float]:
    """Weighted purity of predicted clusters against reference labels."""
    pairs = [
        (int(cluster), label)
        for cluster, label in zip(predicted, reference)
        if label is not None and int(cluster) != 0
    ]
    if not pairs:
        return None
    grouped: Dict[int, List[str]] = {}
    for cluster, label in pairs:
        grouped.setdefault(cluster, []).append(label)
    total = sum(len(items) for items in grouped.values())
    dominant = sum(max(items.count(label) for label in set(items)) for items in grouped.values())
    return round(dominant / total, 6) if total else None


def _missingness_r2(embedding: np.ndarray, missingness: np.ndarray) -> Optional[float]:
    """R^2 of predicting the per-site missingness rate from the embedding.

    A high value means the representation encodes coverage rather than temporal
    biology, which is exactly what the missingness-validity gate rejects.
    """
    features = standardize_rows(embedding)
    target = np.asarray(missingness, dtype=float)
    if features.size == 0 or target.size < 3 or float(np.var(target)) < 1e-12:
        return None
    design = np.column_stack([features, np.ones(features.shape[0])])
    solution, *_ = np.linalg.lstsq(design, target, rcond=None)
    residual = target - design @ solution
    denominator = float(np.sum((target - target.mean()) ** 2))
    if denominator <= 0:
        return None
    return round(float(1.0 - np.sum(residual ** 2) / denominator), 6)


# ---------------------------------------------------------------------------
# Variant fitting
# ---------------------------------------------------------------------------


@dataclass
class VariantFit:
    """One evaluated ablation arm with a common interface."""

    variant_id: str
    variant_name: str
    learned: bool
    embedding: np.ndarray
    reconstruction_error: np.ndarray
    perturbed_embeddings: List[np.ndarray] = field(default_factory=list)
    heldout_reconstruction_error: Optional[float] = None
    provenance: Dict[str, Any] = field(default_factory=dict)


def fit_variant(
    multiview: MultiViewTemporalInput,
    variant: str | RepresentationVariant,
    *,
    encoder_config: Optional[Mapping[str, Any]] = None,
    config: Optional[Mapping[str, Any]] = None,
) -> VariantFit:
    """Fit or assemble one Representation A-E arm."""
    effective = _merged_config(config)
    arm = variant if isinstance(variant, RepresentationVariant) else resolve_variant(variant)

    if not arm.learned:
        result: RepresentationResult = handcrafted_representation(multiview, arm)
        return VariantFit(
            variant_id=arm.variant_id,
            variant_name=arm.name,
            learned=False,
            embedding=result.embedding,
            reconstruction_error=(
                result.reconstruction_error
                if result.reconstruction_error is not None
                else np.zeros(multiview.n_sites, dtype=float)
            ),
            provenance={**result.provenance, "method": result.method},
        )

    merged_encoder = dict(encoder_config or {})
    merged_encoder.update(dict(arm.encoder_options))
    merged_encoder.setdefault("seed", effective["seed"])
    fitted = fit_masked_temporal_encoder(multiview, config=merged_encoder)
    return VariantFit(
        variant_id=arm.variant_id,
        variant_name=arm.name,
        learned=True,
        embedding=fitted.embedding,
        reconstruction_error=fitted.reconstruction_error,
        perturbed_embeddings=list(fitted.perturbed_embeddings),
        heldout_reconstruction_error=fitted.heldout_reconstruction_error,
        provenance={
            **fitted.provenance,
            "method": fitted.method,
            "train_reconstruction_error": fitted.train_reconstruction_error,
            "training_history": fitted.training_history[-3:],
        },
    )


def _subsample_neighbor_stability(
    embedding: np.ndarray,
    *,
    rounds: int,
    fraction: float,
    k: int,
    seed: int,
) -> Optional[float]:
    """Top-k neighbour retention when sites are bootstrapped out."""
    n_rows = embedding.shape[0]
    if n_rows < 4 or rounds <= 0 or embedding.shape[1] == 0:
        return None
    full = top_k_neighbors(embedding, k)
    if full.shape[1] == 0:
        return None
    rng = np.random.default_rng(int(seed))
    scores: List[float] = []
    for round_index in range(rounds):
        size = max(3, int(round(n_rows * fraction)))
        chosen = np.sort(rng.choice(n_rows, size=min(size, n_rows), replace=False))
        position = {int(index): order for order, index in enumerate(chosen)}
        subset_neighbours = top_k_neighbors(embedding[chosen], k)
        if subset_neighbours.shape[1] == 0:
            continue
        round_scores: List[float] = []
        for order, index in enumerate(chosen):
            reference = {int(other) for other in full[index] if int(other) in position}
            if not reference:
                continue
            candidate = {int(chosen[other]) for other in subset_neighbours[order]}
            union = reference | candidate
            if union:
                round_scores.append(len(reference & candidate) / len(union))
        if round_scores:
            scores.append(float(np.mean(round_scores)))
    return round(float(np.mean(scores)), 6) if scores else None


def _leave_one_timepoint_out_stability(
    multiview: MultiViewTemporalInput,
    arm: RepresentationVariant,
    reference_labels: np.ndarray,
    *,
    encoder_config: Optional[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> Optional[float]:
    """Cluster ARI when each timepoint is dropped in turn."""
    if multiview.n_timepoints < 4 or multiview.n_sites < 4:
        return None
    scores: List[float] = []
    for dropped in range(multiview.n_timepoints):
        keep = [index for index in range(multiview.n_timepoints) if index != dropped]
        reduced = _drop_timepoints(multiview, keep)
        loop_encoder = dict(encoder_config or {})
        if arm.learned:
            epochs = int(loop_encoder.get("epochs", 300) * float(config["leave_one_out_epoch_scale"]))
            loop_encoder["epochs"] = max(30, epochs)
            loop_encoder["n_perturbations"] = 0
        fitted = fit_variant(reduced, arm, encoder_config=loop_encoder, config=config)
        labels = cluster_representation(
            fitted.embedding,
            distance_threshold=config["cluster_distance_threshold"],
            minimum_cluster_size=config["minimum_cluster_size"],
        )
        score = adjusted_rand_index(reference_labels, labels)
        if np.isfinite(score):
            scores.append(float(score))
    return round(float(np.mean(scores)), 6) if scores else None


def _drop_timepoints(multiview: MultiViewTemporalInput, keep: Sequence[int]) -> MultiViewTemporalInput:
    """Return a copy restricted to the given timepoint indices."""
    from ptm_shared.representation.feature_contract import TemporalViewMatrix

    indices = list(keep)

    def _sub(view: TemporalViewMatrix) -> TemporalViewMatrix:
        return TemporalViewMatrix(
            name=view.name,
            role=view.role,
            values=view.values[:, indices],
            observed=view.observed[:, indices],
            fill_policy=view.fill_policy,
        )

    minutes = multiview.time_minutes[indices]
    deltas = np.zeros(len(indices), dtype=float)
    if len(indices) > 1:
        deltas[1:] = np.diff(np.where(np.isfinite(minutes), minutes, 0.0))
    provenance = dict(multiview.provenance)
    provenance["timepoint_subset"] = [multiview.timepoints[index] for index in indices]
    track1 = _sub(multiview.track1)
    return MultiViewTemporalInput(
        site_keys=list(multiview.site_keys),
        timepoints=[multiview.timepoints[index] for index in indices],
        time_minutes=minutes,
        delta_minutes=deltas,
        time_encoding=multiview.time_encoding[indices],
        target=_sub(multiview.target),
        protein_context=_sub(multiview.protein_context),
        track1=track1,
        track1_available=track1.observed.any(axis=1),
        quality_weight=multiview.quality_weight[:, indices],
        eligible=multiview.eligible,
        site_metadata=multiview.site_metadata,
        motif_features=multiview.motif_features,
        motif_labels=multiview.motif_labels,
        provenance=provenance,
    )


def evaluate_variant(
    multiview: MultiViewTemporalInput,
    fit: VariantFit,
    *,
    arm: RepresentationVariant,
    reference_labels: Optional[Mapping[str, str]] = None,
    encoder_config: Optional[Mapping[str, Any]] = None,
    config: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Compute the pre-registered metric set for one arm."""
    effective = _merged_config(config)
    labels = cluster_representation(
        fit.embedding,
        distance_threshold=effective["cluster_distance_threshold"],
        minimum_cluster_size=effective["minimum_cluster_size"],
    )
    concordance = representation_track_concordance(fit.embedding, multiview, config=effective)
    track_scores = concordance["representation_track_concordance"]
    finite_track = track_scores[np.isfinite(track_scores)]

    reference_by_row: List[Optional[str]] = []
    for key in multiview.site_keys:
        meta = multiview.site_metadata.get(key, {})
        site_key = str(meta.get("site_key") or key)
        value = (reference_labels or {}).get(site_key, (reference_labels or {}).get(key))
        reference_by_row.append(None if value is None else str(value))

    stability = (
        embedding_neighbor_stability(fit.embedding, fit.perturbed_embeddings, k=effective["neighbors"])
        if fit.perturbed_embeddings
        else np.zeros(0, dtype=float)
    )
    finite_stability = stability[np.isfinite(stability)] if stability.size else stability

    metrics: Dict[str, Any] = {
        "variant_id": fit.variant_id,
        "variant_name": fit.variant_name,
        "learned": fit.learned,
        "n_sites": multiview.n_sites,
        "n_timepoints": multiview.n_timepoints,
        "embedding_dim": int(fit.embedding.shape[1]) if fit.embedding.size else 0,
        "n_clusters": int(len({label for label in labels.tolist() if label != 0})),
        "unclustered_sites": int(np.sum(labels == 0)),
        "wave_stability_bootstrap_neighbor_retention": _subsample_neighbor_stability(
            fit.embedding,
            rounds=effective["bootstrap_rounds"],
            fraction=effective["bootstrap_site_fraction"],
            k=effective["neighbors"],
            seed=effective["seed"],
        ),
        "raw_evidence_concordance": round(float(np.mean(finite_track)), 6) if finite_track.size else None,
        "mask_perturbation_neighbor_stability": (
            round(float(np.mean(finite_stability)), 6) if finite_stability.size else None
        ),
        "heldout_reconstruction_error": (
            None
            if fit.heldout_reconstruction_error is None or not np.isfinite(fit.heldout_reconstruction_error)
            else round(float(fit.heldout_reconstruction_error), 6)
        ),
        "missingness_r2": _missingness_r2(fit.embedding, multiview.missingness_rate()),
        "known_grouping_neighbor_enrichment": neighbor_label_enrichment(
            fit.embedding, reference_by_row, k=effective["neighbors"]
        ),
        "known_grouping_cluster_purity": cluster_purity(labels, reference_by_row),
        "known_grouping_adjusted_rand_index": (
            adjusted_rand_index(
                labels,
                [hash(label) if label is not None else -1 for label in reference_by_row],
            )
            if any(label is not None for label in reference_by_row)
            else None
        ),
        "uses_prior_features": arm.uses_prior_features,
        "guardrails": list(arm.guardrails),
    }

    if effective["leave_one_out"]:
        metrics["timepoint_leave_one_out_ari"] = _leave_one_timepoint_out_stability(
            multiview,
            arm,
            labels,
            encoder_config=encoder_config,
            config=effective,
        )
    else:
        metrics["timepoint_leave_one_out_ari"] = None

    # Missingness validity: re-fit under extra artificial masking and check that
    # the representation still tracks the temporal pattern rather than coverage.
    masked_input, induced = multiview.with_additional_target_masking(
        fraction=effective["artificial_mask_fraction"], seed=effective["seed"]
    )
    if int(induced.sum()) > 0:
        masked_encoder = dict(encoder_config or {})
        masked_encoder["n_perturbations"] = 0
        masked_fit = fit_variant(masked_input, arm, encoder_config=masked_encoder, config=effective)
        masked_labels = cluster_representation(
            masked_fit.embedding,
            distance_threshold=effective["cluster_distance_threshold"],
            minimum_cluster_size=effective["minimum_cluster_size"],
        )
        retention = adjusted_rand_index(labels, masked_labels)
        metrics["artificial_masking_probe"] = {
            "n_masked_entries": int(induced.sum()),
            "mask_fraction": effective["artificial_mask_fraction"],
            "pattern_retention_ari": None if not np.isfinite(retention) else round(float(retention), 6),
            "induced_missingness_r2": _missingness_r2(masked_fit.embedding, induced.mean(axis=1)),
        }
    else:
        metrics["artificial_masking_probe"] = {
            "n_masked_entries": 0,
            "status": "not_evaluated_insufficient_observed_entries",
        }

    # Time validity is only meaningful for arms that claim to use temporal order.
    if fit.learned:
        permuted_input = multiview.with_permuted_time_order(seed=effective["seed"])
        permuted_encoder = dict(encoder_config or {})
        permuted_encoder["n_perturbations"] = 0
        permuted_fit = fit_variant(permuted_input, arm, encoder_config=permuted_encoder, config=effective)
        permuted_labels = cluster_representation(
            permuted_fit.embedding,
            distance_threshold=effective["cluster_distance_threshold"],
            minimum_cluster_size=effective["minimum_cluster_size"],
        )
        permuted_concordance = representation_track_concordance(
            permuted_fit.embedding, permuted_input, config=effective
        )
        permuted_track = permuted_concordance["representation_track_concordance"]
        permuted_finite = permuted_track[np.isfinite(permuted_track)]
        metrics["time_permutation"] = {
            "permuted_heldout_reconstruction_error": (
                None
                if permuted_fit.heldout_reconstruction_error is None
                or not np.isfinite(permuted_fit.heldout_reconstruction_error)
                else round(float(permuted_fit.heldout_reconstruction_error), 6)
            ),
            "permuted_raw_evidence_concordance": (
                round(float(np.mean(permuted_finite)), 6) if permuted_finite.size else None
            ),
            "cluster_ari_true_vs_permuted": adjusted_rand_index(labels, permuted_labels),
        }
    else:
        metrics["time_permutation"] = None

    return metrics


def evaluate_adoption_gates(
    variant_metrics: Mapping[str, Mapping[str, Any]],
    *,
    primary_variant: str = PRIMARY_ARM_PREFERENCE[0],
    baseline_variant: str = "B",
    external_evaluations: Optional[Sequence[Mapping[str, Any]]] = None,
    config: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Evaluate the six adoption gates for the learned representation.

    Returns ``production_influence_allowed=False`` unless all gates pass, so a
    prototype cannot silently start affecting kinase ranking.
    """
    effective = _merged_config(config)
    primary = dict(variant_metrics.get(primary_variant) or {})
    baseline = dict(variant_metrics.get(baseline_variant) or {})
    gates: Dict[str, Dict[str, Any]] = {}

    permutation = dict(primary.get("time_permutation") or {})
    observed_error = primary.get("heldout_reconstruction_error")
    permuted_error = permutation.get("permuted_heldout_reconstruction_error")
    if observed_error is None or permuted_error is None:
        gates["time_validity"] = {
            "passed": False,
            "status": "not_evaluated",
            "detail": "held-out reconstruction error unavailable for true or permuted order",
        }
    else:
        margin = float(permuted_error) - float(observed_error)
        gates["time_validity"] = {
            "passed": bool(margin >= float(effective["time_validity_margin"])),
            "status": "evaluated",
            "observed_heldout_error": observed_error,
            "permuted_heldout_error": permuted_error,
            "margin": round(margin, 6),
            "required_margin": effective["time_validity_margin"],
        }

    # The gate is the artificial-masking probe: under induced masking the
    # representation must keep reflecting the temporal pattern (ARI retention)
    # without encoding the induced coverage rate.  The natural missingness
    # association is reported alongside it as a diagnostic.
    probe = dict(primary.get("artificial_masking_probe") or {})
    retention = probe.get("pattern_retention_ari")
    induced_r2 = probe.get("induced_missingness_r2")
    natural_r2 = primary.get("missingness_r2")
    if retention is None or induced_r2 is None:
        gates["missingness_validity"] = {
            "passed": False,
            "status": "not_evaluated",
            "detail": "artificial masking probe unavailable or had no entries to mask",
            "natural_missingness_r2": natural_r2,
        }
    else:
        retention_ok = float(retention) >= float(effective["missingness_pattern_ari_min"])
        coverage_ok = float(induced_r2) <= float(effective["missingness_r2_max"])
        gates["missingness_validity"] = {
            "passed": bool(retention_ok and coverage_ok),
            "status": "evaluated",
            "pattern_retention_ari": retention,
            "minimum_pattern_retention_ari": effective["missingness_pattern_ari_min"],
            "induced_missingness_r2": induced_r2,
            "maximum_induced_missingness_r2": effective["missingness_r2_max"],
            "natural_missingness_r2": natural_r2,
        }

    concordance = primary.get("raw_evidence_concordance")
    if concordance is None:
        gates["raw_evidence_concordance"] = {
            "passed": False,
            "status": "not_evaluated",
            "detail": "no site had both a latent neighbourhood and raw peak/direction evidence",
        }
    else:
        gates["raw_evidence_concordance"] = {
            "passed": bool(float(concordance) >= float(effective["raw_concordance_min"])),
            "status": "evaluated",
            "raw_evidence_concordance": concordance,
            "minimum_required": effective["raw_concordance_min"],
        }

    external = list(external_evaluations or [])
    if not external:
        gates["generalization"] = {
            "passed": False,
            "status": "not_evaluated",
            "detail": (
                "requires a held-out external dataset; a single discovery cohort "
                "cannot establish cross-dataset generalization"
            ),
        }
    else:
        improved = [
            bool(entry.get("improves_baseline"))
            for entry in external
            if entry.get("improves_baseline") is not None
        ]
        gates["generalization"] = {
            "passed": bool(improved) and all(improved),
            "status": "evaluated",
            "n_external_datasets": len(external),
            "datasets": [str(entry.get("dataset", "unknown")) for entry in external],
        }

    prior_arms = [
        key for key, metrics in variant_metrics.items() if bool((metrics or {}).get("uses_prior_features"))
    ]
    if not bool(primary.get("uses_prior_features")):
        gates["no_prior_leakage"] = {
            "passed": True,
            "status": "not_applicable",
            "detail": "primary arm uses no motif/KSA/PPI-derived prior features",
            "prior_feature_arms": prior_arms,
        }
    else:
        feature_free = variant_metrics.get("A") or variant_metrics.get("D")
        gates["no_prior_leakage"] = {
            "passed": bool(feature_free),
            "status": "evaluated" if feature_free else "not_evaluated",
            "detail": "prior-feature arm must be compared against a feature-free temporal baseline",
            "prior_feature_arms": prior_arms,
        }

    traceable = bool(primary.get("n_sites")) and bool(primary.get("embedding_dim"))
    gates["interpretability"] = {
        "passed": traceable,
        "status": "evaluated" if traceable else "not_evaluated",
        "detail": (
            "each reported site retains gene, position, form, observed timepoints, "
            "Track1/Track2 status, and raw values for traceback"
        ),
        "primary_score_inputs_locked": list(PRIMARY_SCORE_INPUTS_LOCKED),
    }

    passed = {name: bool(gates.get(name, {}).get("passed")) for name in ADOPTION_GATES}
    baseline_concordance = baseline.get("raw_evidence_concordance")
    return {
        "contract_version": CONTRACT_VERSION,
        "primary_variant": primary_variant,
        "baseline_variant": baseline_variant,
        "gates": gates,
        "gates_passed": passed,
        "n_gates_passed": int(sum(passed.values())),
        "n_gates_total": len(ADOPTION_GATES),
        "production_influence_allowed": bool(all(passed.values())),
        "stage": "R1.5_benchmark",
        "baseline_raw_evidence_concordance": baseline_concordance,
        "primary_raw_evidence_concordance": concordance,
        "note": (
            "production_influence_allowed=False keeps canonical co-wave, TMM "
            "coefficients, and kinase ranking on raw Track 2 evidence."
        ),
    }


def run_ablation(
    multiview: MultiViewTemporalInput,
    *,
    variants: Optional[Sequence[str]] = None,
    encoder_config: Optional[Mapping[str, Any]] = None,
    reference_labels: Optional[Mapping[str, str]] = None,
    external_evaluations: Optional[Sequence[Mapping[str, Any]]] = None,
    include_r0_baselines: bool = True,
    config: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Run the Representation A-E ablation plus the R0 baselines and gates."""
    effective = _merged_config(config)
    requested = list(variants or variant_order())

    if multiview.n_sites < effective["minimum_sites"] or multiview.n_timepoints < 3:
        return {
            "contract_version": CONTRACT_VERSION,
            "status": "insufficient_data",
            "n_sites": multiview.n_sites,
            "n_timepoints": multiview.n_timepoints,
            "minimum_sites": effective["minimum_sites"],
            "variants": {},
            "adoption_gates": {
                "production_influence_allowed": False,
                "status": "not_evaluated",
            },
        }

    fits: Dict[str, VariantFit] = {}
    metrics: Dict[str, Dict[str, Any]] = {}
    for key in requested:
        arm = resolve_variant(key)
        if arm.uses_prior_features and multiview.motif_features is None:
            metrics[arm.variant_id] = {
                "variant_id": arm.variant_id,
                "variant_name": arm.name,
                "learned": arm.learned,
                "status": "skipped_motif_features_unavailable",
                "uses_prior_features": True,
                "guardrails": list(arm.guardrails),
            }
            continue
        fit = fit_variant(multiview, arm, encoder_config=encoder_config, config=effective)
        fits[arm.variant_id] = fit
        metrics[arm.variant_id] = evaluate_variant(
            multiview,
            fit,
            arm=arm,
            reference_labels=reference_labels,
            encoder_config=encoder_config,
            config=effective,
        )
        metrics[arm.variant_id]["status"] = "evaluated"

    baseline_metrics: Dict[str, Any] = {}
    if include_r0_baselines:
        for name, result in run_r0_baselines(
            multiview,
            n_components=effective["baseline_components"],
            seed=effective["seed"],
        ).items():
            labels = cluster_representation(
                result.embedding,
                distance_threshold=effective["cluster_distance_threshold"],
                minimum_cluster_size=effective["minimum_cluster_size"],
            )
            errors = (
                result.reconstruction_error
                if result.reconstruction_error is not None
                else np.zeros(multiview.n_sites)
            )
            finite = errors[np.isfinite(errors)]
            concordance = representation_track_concordance(result.embedding, multiview, config=effective)
            scores = concordance["representation_track_concordance"]
            finite_scores = scores[np.isfinite(scores)]
            baseline_metrics[name] = {
                "method": result.method,
                "n_components": result.n_components,
                "n_clusters": int(len({label for label in labels.tolist() if label != 0})),
                "mean_reconstruction_error": round(float(np.mean(finite)), 6) if finite.size else None,
                "raw_evidence_concordance": (
                    round(float(np.mean(finite_scores)), 6) if finite_scores.size else None
                ),
                "missingness_r2": _missingness_r2(result.embedding, multiview.missingness_rate()),
                "provenance": result.provenance,
            }

    learned_arms = [key for key, entry in metrics.items() if entry.get("learned") and entry.get("status") == "evaluated"]
    primary_variant = select_primary_variant(learned_arms)
    gates = evaluate_adoption_gates(
        metrics,
        primary_variant=primary_variant,
        baseline_variant="B" if "B" in metrics else next(iter(metrics), "B"),
        external_evaluations=external_evaluations,
        config=effective,
    )

    return {
        "contract_version": CONTRACT_VERSION,
        "status": "evaluated",
        "stage": "R1.5",
        "config": effective,
        "input_provenance": multiview.provenance,
        "variants": metrics,
        "r0_baselines": baseline_metrics,
        "adoption_gates": gates,
        "primary_arm_preference": list(PRIMARY_ARM_PREFERENCE),
        "primary_score_inputs_locked": list(PRIMARY_SCORE_INPUTS_LOCKED),
    }
