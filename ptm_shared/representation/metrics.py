"""Additive secondary fields derived from the L4 learned embedding.

Every quantity here is *additive*: it annotates existing evidence and never
replaces a canonical co-wave membership, a TMM contribution coefficient, or a
kinase ranking.  A learned neighbourhood is reported as "temporal multi-view
neighbourhood agrees with reference module X", not as proof of a direct
kinase-substrate relationship.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from ptm_shared.representation.feature_contract import MultiViewTemporalInput
from ptm_shared.representation.layers import ADDITIVE_FIELDS, CONTRACT_VERSION


DEFAULT_METRIC_CONFIG: Dict[str, Any] = {
    "neighbors": 10,
    "supported_agreement_min": 0.50,
    "discordant_agreement_max": 0.10,
    "stability_min_for_discordance": 0.60,
    "peak_tolerance_steps": 1,
    "low_quality_error_percentile": 90.0,
}


def _merged_config(config: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    merged = dict(DEFAULT_METRIC_CONFIG)
    for key, value in dict(config or {}).items():
        if key in merged and value is not None:
            merged[key] = value
    merged["neighbors"] = max(1, int(merged["neighbors"]))
    merged["peak_tolerance_steps"] = max(0, int(merged["peak_tolerance_steps"]))
    merged["supported_agreement_min"] = float(np.clip(merged["supported_agreement_min"], 0.0, 1.0))
    merged["discordant_agreement_max"] = float(np.clip(merged["discordant_agreement_max"], 0.0, 1.0))
    merged["stability_min_for_discordance"] = float(
        np.clip(merged["stability_min_for_discordance"], 0.0, 1.0)
    )
    merged["low_quality_error_percentile"] = float(
        np.clip(merged["low_quality_error_percentile"], 50.0, 100.0)
    )
    return merged


def standardize_rows(matrix: np.ndarray) -> np.ndarray:
    """Row-wise z-scoring so neighbour search compares shape, not amplitude."""
    values = np.asarray(matrix, dtype=float)
    if values.size == 0:
        return values
    values = np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0)
    centred = values - values.mean(axis=1, keepdims=True)
    norm = np.linalg.norm(centred, axis=1, keepdims=True)
    norm[norm < 1e-12] = 1.0
    return centred / norm


def top_k_neighbors(embedding: np.ndarray, k: int) -> np.ndarray:
    """Return ``(n_sites, k)`` neighbour indices under cosine similarity."""
    normalized = standardize_rows(embedding)
    n_rows = normalized.shape[0]
    if n_rows == 0 or normalized.shape[1] == 0:
        return np.zeros((n_rows, 0), dtype=int)
    neighbours = min(int(k), max(n_rows - 1, 0))
    if neighbours == 0:
        return np.zeros((n_rows, 0), dtype=int)
    similarity = normalized @ normalized.T
    np.fill_diagonal(similarity, -np.inf)
    ordered = np.argsort(-similarity, axis=1, kind="stable")
    return ordered[:, :neighbours]


def embedding_neighbor_stability(
    embedding: np.ndarray,
    perturbed_embeddings: Sequence[np.ndarray],
    *,
    k: int = 10,
) -> np.ndarray:
    """Mean top-k neighbour overlap between the fit and its perturbed refits."""
    n_rows = int(np.asarray(embedding).shape[0]) if np.asarray(embedding).size else 0
    if n_rows == 0:
        return np.zeros(0, dtype=float)
    if not perturbed_embeddings:
        return np.full(n_rows, np.nan, dtype=float)

    reference = top_k_neighbors(embedding, k)
    if reference.shape[1] == 0:
        return np.full(n_rows, np.nan, dtype=float)

    reference_sets = [set(row.tolist()) for row in reference]
    accumulated = np.zeros(n_rows, dtype=float)
    used = 0
    for candidate in perturbed_embeddings:
        candidate = np.asarray(candidate, dtype=float)
        if candidate.shape[0] != n_rows or candidate.size == 0:
            continue
        neighbours = top_k_neighbors(candidate, k)
        if neighbours.shape[1] == 0:
            continue
        used += 1
        for row in range(n_rows):
            other = set(neighbours[row].tolist())
            union = reference_sets[row] | other
            if union:
                accumulated[row] += len(reference_sets[row] & other) / len(union)
    if used == 0:
        return np.full(n_rows, np.nan, dtype=float)
    return accumulated / used


def _peak_and_direction(
    multiview: MultiViewTemporalInput,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Observed Track 2 peak index, peak direction, and validity per site."""
    values = np.nan_to_num(multiview.target.values, nan=0.0)
    observed = multiview.target.observed
    masked = np.where(observed, np.abs(values), -np.inf)
    valid = observed.any(axis=1)
    peak_index = np.zeros(multiview.n_sites, dtype=int)
    direction = np.zeros(multiview.n_sites, dtype=float)
    if multiview.n_sites and multiview.n_timepoints:
        candidate = np.argmax(masked, axis=1)
        peak_index = np.where(valid, candidate, 0)
        rows = np.arange(multiview.n_sites)
        direction = np.where(valid, np.sign(values[rows, peak_index]), 0.0)
    return peak_index, direction, valid


def representation_track_concordance(
    embedding: np.ndarray,
    multiview: MultiViewTemporalInput,
    *,
    config: Optional[Mapping[str, Any]] = None,
) -> Dict[str, np.ndarray]:
    """Agreement between latent neighbours and raw peak/direction evidence.

    This is deliberately computed against the raw observed trajectories, so a
    high score means the learned neighbourhood reproduces evidence that a human
    can inspect in the L1/L2 values.
    """
    effective = _merged_config(config)
    neighbours = top_k_neighbors(embedding, effective["neighbors"])
    peak_index, direction, valid = _peak_and_direction(multiview)
    track1_direction = np.zeros(multiview.n_sites, dtype=float)
    if multiview.track1.observed.any():
        track1_values = np.nan_to_num(multiview.track1.values, nan=0.0)
        masked = np.where(multiview.track1.observed, np.abs(track1_values), -np.inf)
        rows = np.arange(multiview.n_sites)
        track1_peak = np.where(multiview.track1_available, np.argmax(masked, axis=1), 0)
        track1_direction = np.where(
            multiview.track1_available, np.sign(track1_values[rows, track1_peak]), 0.0
        )

    tolerance = effective["peak_tolerance_steps"]
    track2_score = np.full(multiview.n_sites, np.nan, dtype=float)
    track1_score = np.full(multiview.n_sites, np.nan, dtype=float)

    for row in range(multiview.n_sites):
        if not valid[row] or neighbours.shape[1] == 0:
            continue
        partners = neighbours[row]
        usable = [index for index in partners if valid[index]]
        if usable:
            agreements = [
                1.0
                if (
                    direction[row] == direction[index]
                    and abs(int(peak_index[row]) - int(peak_index[index])) <= tolerance
                )
                else 0.0
                for index in usable
            ]
            track2_score[row] = float(np.mean(agreements))
        if multiview.track1_available[row]:
            paired = [index for index in partners if multiview.track1_available[index]]
            if paired:
                track1_score[row] = float(
                    np.mean([1.0 if track1_direction[row] == track1_direction[index] else 0.0 for index in paired])
                )

    combined = np.where(np.isfinite(track1_score), (track2_score + track1_score) / 2.0, track2_score)
    return {
        "representation_track_concordance": combined,
        "track2_peak_direction_concordance": track2_score,
        "track1_direction_concordance": track1_score,
    }


def profile_representational_dispersion(
    embedding: np.ndarray,
    exclusive_members: Mapping[str, Sequence[int]],
) -> Dict[str, Dict[str, Any]]:
    """Embedding dispersion of each candidate kinase's exclusive substrates.

    High dispersion is a heterogeneous-profile warning about the TMM profile that
    was built from those substrates; it does not modify the TMM coefficient.
    """
    normalized = standardize_rows(embedding)
    dispersion: Dict[str, Dict[str, Any]] = {}
    for kinase, indices in (exclusive_members or {}).items():
        rows = [int(index) for index in indices if 0 <= int(index) < normalized.shape[0]]
        if len(rows) < 2:
            dispersion[str(kinase)] = {
                "profile_representational_dispersion": None,
                "n_exclusive_members": len(rows),
                "status": "insufficient_exclusive_members",
            }
            continue
        block = normalized[rows]
        similarity = block @ block.T
        upper = similarity[np.triu_indices(len(rows), k=1)]
        dispersion[str(kinase)] = {
            "profile_representational_dispersion": round(float(np.mean(1.0 - upper)), 6),
            "n_exclusive_members": len(rows),
            "status": "computed",
        }
    return dispersion


def _wave_agreement(
    neighbours: np.ndarray,
    wave_of_row: Sequence[Optional[str]],
) -> np.ndarray:
    n_rows = len(wave_of_row)
    agreement = np.full(n_rows, np.nan, dtype=float)
    if neighbours.shape[1] == 0:
        return agreement
    for row in range(n_rows):
        wave = wave_of_row[row]
        if wave is None:
            continue
        partners = [index for index in neighbours[row] if wave_of_row[index] is not None]
        if not partners:
            continue
        agreement[row] = float(
            np.mean([1.0 if wave_of_row[index] == wave else 0.0 for index in partners])
        )
    return agreement


@dataclass
class AdditiveFieldResult:
    """Per-site additive fields plus a machine-readable summary."""

    site_fields: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    kinase_fields: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    summary: Dict[str, Any] = field(default_factory=dict)
    provenance: Dict[str, Any] = field(default_factory=dict)


def build_additive_fields(
    multiview: MultiViewTemporalInput,
    embedding: np.ndarray,
    *,
    reconstruction_error: Optional[np.ndarray] = None,
    perturbed_embeddings: Optional[Sequence[np.ndarray]] = None,
    embedding_uncertainty: Optional[np.ndarray] = None,
    wave_membership: Optional[Mapping[str, Any]] = None,
    exclusive_members: Optional[Mapping[str, Sequence[int]]] = None,
    config: Optional[Mapping[str, Any]] = None,
) -> AdditiveFieldResult:
    """Assemble every additive field for one fitted representation.

    ``wave_membership`` maps a canonical co-wave site key (``"GENE POSITION"``)
    to its wave id.  Sites outside any wave are skipped rather than assumed to
    disagree.
    """
    effective = _merged_config(config)
    n_sites = multiview.n_sites
    neighbours = top_k_neighbors(embedding, effective["neighbors"])
    stability = embedding_neighbor_stability(
        embedding, list(perturbed_embeddings or []), k=effective["neighbors"]
    )
    concordance = representation_track_concordance(embedding, multiview, config=effective)

    errors = (
        np.asarray(reconstruction_error, dtype=float)
        if reconstruction_error is not None
        else np.full(n_sites, np.nan, dtype=float)
    )
    finite_errors = errors[np.isfinite(errors)]
    error_cutoff = (
        float(np.percentile(finite_errors, effective["low_quality_error_percentile"]))
        if finite_errors.size
        else float("nan")
    )

    uncertainty = (
        np.asarray(embedding_uncertainty, dtype=float)
        if embedding_uncertainty is not None
        else np.full(n_sites, np.nan, dtype=float)
    )

    wave_lookup = {str(key): value for key, value in (wave_membership or {}).items()}
    wave_of_row: List[Optional[str]] = []
    for key in multiview.site_keys:
        meta = multiview.site_metadata.get(key, {})
        site_key = str(meta.get("site_key") or key)
        wave = wave_lookup.get(site_key, wave_lookup.get(key))
        wave_of_row.append(None if wave is None else str(wave))
    agreement = _wave_agreement(neighbours, wave_of_row)

    site_fields: Dict[str, Dict[str, Any]] = {}
    supported_count = 0
    discordant_count = 0
    for row, key in enumerate(multiview.site_keys):
        meta = multiview.site_metadata.get(key, {})
        row_agreement = agreement[row]
        row_stability = stability[row] if stability.size else float("nan")
        supported = bool(
            np.isfinite(row_agreement)
            and row_agreement >= effective["supported_agreement_min"]
        )
        # Discordance is only claimed when the latent neighbourhood is itself
        # stable; an unstable embedding is low quality, not novel biology.
        discordant = bool(
            np.isfinite(row_agreement)
            and row_agreement <= effective["discordant_agreement_max"]
            and np.isfinite(row_stability)
            and row_stability >= effective["stability_min_for_discordance"]
        )
        supported_count += int(supported)
        discordant_count += int(discordant)
        site_fields[key] = {
            "site_key": meta.get("site_key", key),
            "gene": meta.get("gene", ""),
            "position": meta.get("position", ""),
            "modified_sequence": meta.get("modified_sequence", ""),
            "co_wave_id": wave_of_row[row],
            "embedding_neighbor_stability": None if not np.isfinite(row_stability) else round(float(row_stability), 6),
            "representation_reconstruction_error": None
            if not np.isfinite(errors[row])
            else round(float(errors[row]), 6),
            "representation_track_concordance": None
            if not np.isfinite(concordance["representation_track_concordance"][row])
            else round(float(concordance["representation_track_concordance"][row]), 6),
            "track2_peak_direction_concordance": None
            if not np.isfinite(concordance["track2_peak_direction_concordance"][row])
            else round(float(concordance["track2_peak_direction_concordance"][row]), 6),
            "track1_direction_concordance": None
            if not np.isfinite(concordance["track1_direction_concordance"][row])
            else round(float(concordance["track1_direction_concordance"][row]), 6),
            "co_wave_neighbor_agreement": None if not np.isfinite(row_agreement) else round(float(row_agreement), 6),
            "embedding_uncertainty": None if not np.isfinite(uncertainty[row]) else round(float(uncertainty[row]), 6),
            "representation_supported": supported,
            "representation_discordant": discordant,
            "low_quality_embedding": bool(
                np.isfinite(errors[row]) and np.isfinite(error_cutoff) and errors[row] > error_cutoff
            ),
            "track1_available": bool(multiview.track1_available[row]),
            "observed_timepoints": int(meta.get("observed_timepoints", 0)),
        }

    kinase_fields = profile_representational_dispersion(embedding, exclusive_members or {})

    def _mean(values: np.ndarray) -> Optional[float]:
        finite = values[np.isfinite(values)] if values.size else values
        return round(float(np.mean(finite)), 6) if finite.size else None

    summary = {
        "n_sites": n_sites,
        "n_neighbors": int(neighbours.shape[1]),
        "mean_embedding_neighbor_stability": _mean(stability),
        "mean_representation_reconstruction_error": _mean(errors),
        "mean_representation_track_concordance": _mean(concordance["representation_track_concordance"]),
        "mean_co_wave_neighbor_agreement": _mean(agreement),
        "n_representation_supported": supported_count,
        "n_representation_discordant": discordant_count,
        "n_sites_with_co_wave": int(sum(1 for wave in wave_of_row if wave is not None)),
        "low_quality_error_cutoff": None if not np.isfinite(error_cutoff) else round(error_cutoff, 6),
    }

    provenance = {
        "contract_version": CONTRACT_VERSION,
        "config": effective,
        "field_definitions": dict(ADDITIVE_FIELDS),
        "role": "additive_secondary_evidence",
        "changes_primary_scores": False,
        "interpretation_limit": (
            "latent neighbourhood agreement with a reference module is not proof of "
            "a direct kinase-substrate relationship or causality"
        ),
    }
    return AdditiveFieldResult(
        site_fields=site_fields,
        kinase_fields=kinase_fields,
        summary=summary,
        provenance=provenance,
    )
