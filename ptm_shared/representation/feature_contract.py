"""L1 -> L2/L3 input contract for PTM representation learning.

This module converts the preserved L1 Quantitative PTM Feature Vector rows into
the ordered-timepoint structures that the R0 baselines and the R1 encoder
consume.  It reads L1 without modifying it.

Four contract rules are enforced here rather than left to the model:

* Track 2 (``PTM_Relative_Log2FC``) is the primary observed trajectory and the
  primary reconstruction target.
* Track 1 (``Occupancy_Logit_Delta``) is an optional gated branch carried with an
  availability mask.  A missing counterpart is never zero-filled, because zero
  is a meaningful occupancy change.
* q-values enter as quality weights and eligibility masks, never as biological
  feature dimensions, so statistical confidence cannot become a latent axis.
* Irregular timepoint spacing (0.5, 1, 2.5, 5, 10, 15, 30, 60 min) is preserved
  through minute-based time encoding instead of positional indices.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from ptm_shared.directed_temporal_relationship import timepoint_to_minutes
from ptm_shared.representation.layers import (
    CONTRACT_VERSION,
    LAYER_L2,
    LAYER_L3,
)


#: Track 1 tiers that carry usable paired-occupancy evidence.
QUALIFIED_PAIR_TIERS: Tuple[str, ...] = ("O1", "O2")

DEFAULT_CONFIG: Dict[str, Any] = {
    # site/form key level; "form" keeps Modified.Sequence resolution.
    "key_level": "form",
    "minimum_observed_timepoints": 3,
    "minimum_timepoints": 3,
    # q -> weight mapping; q=0 gives 1.0 and q=1 gives quality_weight_floor.
    "quality_weight_floor": 0.2,
    "missing_quality_weight": 0.5,
    # Eligibility on q is disabled by default to protect unbiased discovery.
    "eligibility_q_max": 1.0,
    "qualified_pair_tiers": list(QUALIFIED_PAIR_TIERS),
    "include_motif_side_feature": False,
}

_TARGET_KEYS = ("PTM_Relative_Log2FC", "ptm_relative_log2fc", "log2fc")
_PROTEIN_KEYS = ("Protein_Log2FC", "protein_log2fc")
_TRACK1_KEYS = ("Occupancy_Logit_Delta", "occupancy_logit_delta")
_TIER_KEYS = ("Pair_Quality_Tier", "pair_quality_tier")
_QVALUE_KEYS = ("q_value", "Q_Value", "qvalue")
_CONDITION_KEYS = ("Condition", "condition")
_GENE_KEYS = ("Gene.Name", "gene", "gene_name")
_POSITION_KEYS = ("PTM_Position", "position", "site")
_FORM_KEYS = ("Modified.Sequence", "modified_sequence")
_PROTEIN_GROUP_KEYS = ("Protein.Group", "protein_group")
_PTM_TYPE_KEYS = ("PTM_Type", "ptm_type")
_MOTIF_KEYS = ("Matched_Motifs", "matched_motifs")
_TRACK_KEYS = ("Quantification_Track", "quantification_track")
_MISSINGNESS_KEYS = ("Pair_Missingness", "pair_missingness")


def _first(row: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in row:
            value = row[key]
            if value is not None:
                return value
    return None


def _as_float(value: Any) -> float:
    """Parse to float, mapping unparsable/non-finite input to NaN."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return parsed if np.isfinite(parsed) else float("nan")


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none"} else text


def _merged_config(config: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    merged = dict(DEFAULT_CONFIG)
    for key, value in dict(config or {}).items():
        if key in merged and value is not None:
            merged[key] = value
    merged["minimum_observed_timepoints"] = max(2, int(merged["minimum_observed_timepoints"]))
    merged["minimum_timepoints"] = max(2, int(merged["minimum_timepoints"]))
    merged["quality_weight_floor"] = float(np.clip(_as_float(merged["quality_weight_floor"]), 0.0, 1.0))
    merged["missing_quality_weight"] = float(np.clip(_as_float(merged["missing_quality_weight"]), 0.0, 1.0))
    merged["eligibility_q_max"] = float(np.clip(_as_float(merged["eligibility_q_max"]), 0.0, 1.0))
    merged["qualified_pair_tiers"] = [str(tier).upper() for tier in merged["qualified_pair_tiers"]]
    merged["key_level"] = "form" if str(merged["key_level"]).lower() == "form" else "site"
    merged["include_motif_side_feature"] = bool(merged["include_motif_side_feature"])
    return merged


def _config_sha(config: Mapping[str, Any]) -> str:
    serialized = json.dumps(config, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TemporalViewMatrix:
    """One ``(n_sites, n_timepoints)`` view with an explicit observation mask."""

    name: str
    role: str
    values: np.ndarray
    observed: np.ndarray
    fill_policy: str = "masked_not_zero_filled"

    def filled(self, fill: float = 0.0) -> np.ndarray:
        """Return values with unobserved entries replaced by ``fill``.

        The fill is a numerical placeholder only.  Callers must multiply by
        ``observed`` (or restrict the loss to observed entries) so that an
        absent measurement is never treated as an observed value of ``fill``.
        """
        filled = np.array(self.values, dtype=float, copy=True)
        filled[~self.observed] = float(fill)
        return filled

    @property
    def observed_fraction(self) -> np.ndarray:
        if self.observed.size == 0:
            return np.zeros(self.observed.shape[0], dtype=float)
        return self.observed.mean(axis=1)


@dataclass
class MultiViewTemporalInput:
    """L3 Multi-view Temporal PTM Input for a single dataset/order."""

    site_keys: List[str]
    timepoints: List[str]
    time_minutes: np.ndarray
    delta_minutes: np.ndarray
    time_encoding: np.ndarray
    target: TemporalViewMatrix
    protein_context: TemporalViewMatrix
    track1: TemporalViewMatrix
    track1_available: np.ndarray
    quality_weight: np.ndarray
    eligible: np.ndarray
    site_metadata: Dict[str, Dict[str, Any]]
    motif_features: Optional[np.ndarray] = None
    motif_labels: Tuple[str, ...] = ()
    provenance: Dict[str, Any] = field(default_factory=dict)

    @property
    def n_sites(self) -> int:
        return len(self.site_keys)

    @property
    def n_timepoints(self) -> int:
        return len(self.timepoints)

    @property
    def view_names(self) -> Tuple[str, ...]:
        """Feature views only.  q-value is deliberately absent from this list."""
        names = [self.target.name, self.protein_context.name, self.track1.name]
        if self.motif_features is not None:
            names.append("motif_static")
        return tuple(names)

    def subset(self, mask: np.ndarray) -> "MultiViewTemporalInput":
        """Return a row-subset view, keeping timepoints and provenance intact."""
        selector = np.asarray(mask, dtype=bool)
        keys = [key for key, keep in zip(self.site_keys, selector) if keep]

        def _sub(view: TemporalViewMatrix) -> TemporalViewMatrix:
            return TemporalViewMatrix(
                name=view.name,
                role=view.role,
                values=view.values[selector],
                observed=view.observed[selector],
                fill_policy=view.fill_policy,
            )

        return MultiViewTemporalInput(
            site_keys=keys,
            timepoints=list(self.timepoints),
            time_minutes=self.time_minutes,
            delta_minutes=self.delta_minutes,
            time_encoding=self.time_encoding,
            target=_sub(self.target),
            protein_context=_sub(self.protein_context),
            track1=_sub(self.track1),
            track1_available=self.track1_available[selector],
            quality_weight=self.quality_weight[selector],
            eligible=self.eligible[selector],
            site_metadata={key: self.site_metadata.get(key, {}) for key in keys},
            motif_features=None if self.motif_features is None else self.motif_features[selector],
            motif_labels=self.motif_labels,
            provenance=dict(self.provenance),
        )

    def eligible_subset(self) -> "MultiViewTemporalInput":
        return self.subset(self.eligible)

    def with_permuted_time_order(self, seed: int = 0) -> "MultiViewTemporalInput":
        """Return a copy whose timepoint order is shuffled.

        Used by the time-validity gate: a representation that genuinely uses
        temporal structure must degrade when the true order is destroyed.
        """
        rng = np.random.default_rng(int(seed))
        order = rng.permutation(self.n_timepoints)

        def _perm(view: TemporalViewMatrix) -> TemporalViewMatrix:
            return TemporalViewMatrix(
                name=view.name,
                role=view.role,
                values=view.values[:, order],
                observed=view.observed[:, order],
                fill_policy=view.fill_policy,
            )

        provenance = dict(self.provenance)
        provenance["time_order"] = "permuted"
        provenance["time_permutation_seed"] = int(seed)
        return MultiViewTemporalInput(
            site_keys=list(self.site_keys),
            timepoints=[self.timepoints[index] for index in order],
            time_minutes=self.time_minutes,
            delta_minutes=self.delta_minutes,
            time_encoding=self.time_encoding,
            target=_perm(self.target),
            protein_context=_perm(self.protein_context),
            track1=_perm(self.track1),
            track1_available=self.track1_available,
            quality_weight=self.quality_weight[:, order],
            eligible=self.eligible,
            site_metadata=self.site_metadata,
            motif_features=self.motif_features,
            motif_labels=self.motif_labels,
            provenance=provenance,
        )

    def missingness_rate(self) -> np.ndarray:
        """Fraction of unobserved Track 2 timepoints per site."""
        return 1.0 - self.target.observed_fraction

    def with_additional_target_masking(
        self,
        *,
        fraction: float = 0.15,
        seed: int = 0,
        heterogeneous: bool = True,
        minimum_remaining: int = 3,
    ) -> Tuple["MultiViewTemporalInput", np.ndarray]:
        """Hide extra observed Track 2 entries and report what was hidden.

        Used by the missingness-validity gate.  Per-site masking rates vary so
        that induced coverage differs across sites; a representation that encodes
        coverage rather than temporal pattern becomes detectable.
        """
        rng = np.random.default_rng(int(seed))
        induced = np.zeros((self.n_sites, self.n_timepoints), dtype=bool)
        for row in range(self.n_sites):
            columns = np.flatnonzero(self.target.observed[row])
            if columns.size <= minimum_remaining:
                continue
            rate = float(rng.uniform(0.0, 2.0 * fraction)) if heterogeneous else float(fraction)
            count = int(round(columns.size * min(max(rate, 0.0), 1.0)))
            count = min(count, columns.size - minimum_remaining)
            if count < 1:
                continue
            induced[row, rng.choice(columns, size=count, replace=False)] = True

        masked_input = self.with_hidden_target_entries(
            induced,
            provenance_key="artificial_masking",
            provenance_detail={
                "fraction": float(fraction),
                "heterogeneous": bool(heterogeneous),
                "seed": int(seed),
                "n_masked_entries": int(induced.sum()),
            },
        )
        return masked_input, induced

    def with_hidden_timepoint(self, index: int) -> "MultiViewTemporalInput":
        """Return a copy with one timepoint blanked across **every** view.

        Hiding only the Track 2 entry is not enough for a held-out prediction
        benchmark.  At a given timepoint the protein-context value and the Track 1
        occupancy are computed from the same measurement pair as the Track 2 value,
        so a representation that reads them can recover the withheld number
        algebraically rather than by learning temporal structure.  Blanking the
        whole column turns the benchmark into a clean question: what happened at
        this timepoint, given only the other timepoints?
        """
        if not 0 <= int(index) < self.n_timepoints:
            raise ValueError(
                f"timepoint index {index} is out of range for {self.n_timepoints} timepoints"
            )
        position = int(index)

        def _blank(view: TemporalViewMatrix) -> TemporalViewMatrix:
            values = np.array(view.values, dtype=float, copy=True)
            values[:, position] = np.nan
            observed = np.array(view.observed, dtype=bool, copy=True)
            observed[:, position] = False
            return TemporalViewMatrix(
                name=view.name,
                role=view.role,
                values=values,
                observed=observed,
                fill_policy=view.fill_policy,
            )

        quality = np.array(self.quality_weight, dtype=float, copy=True)
        quality[:, position] = 0.0

        provenance = dict(self.provenance)
        provenance["hidden_timepoint"] = {
            "timepoint": self.timepoints[position],
            "index": position,
            "views_blanked": ["target", "protein_context", "track1", "quality_weight"],
        }
        return MultiViewTemporalInput(
            site_keys=list(self.site_keys),
            timepoints=list(self.timepoints),
            time_minutes=self.time_minutes,
            delta_minutes=self.delta_minutes,
            time_encoding=self.time_encoding,
            target=_blank(self.target),
            protein_context=_blank(self.protein_context),
            track1=_blank(self.track1),
            track1_available=self.track1_available,
            quality_weight=quality,
            eligible=self.eligible,
            site_metadata=self.site_metadata,
            motif_features=self.motif_features,
            motif_labels=self.motif_labels,
            provenance=provenance,
        )

    def with_hidden_target_entries(
        self,
        hidden: np.ndarray,
        *,
        provenance_key: str = "hidden_target_entries",
        provenance_detail: Optional[Dict[str, Any]] = None,
    ) -> "MultiViewTemporalInput":
        """Return a copy with the given Track 2 entries hidden from every consumer.

        Hiding clears the value, the observed flag, and the quality weight, so no
        representation arm can read a hidden measurement through any channel.
        This is what makes a held-out prediction benchmark fair: arms that carry
        raw values verbatim lose the answer exactly as the learned arms do.
        """
        hidden = np.asarray(hidden, dtype=bool)
        if hidden.shape != self.target.observed.shape:
            raise ValueError(
                f"hidden mask shape {hidden.shape} does not match the target view "
                f"shape {self.target.observed.shape}"
            )

        values = np.array(self.target.values, dtype=float, copy=True)
        values[hidden] = np.nan
        masked_target = TemporalViewMatrix(
            name=self.target.name,
            role=self.target.role,
            values=values,
            observed=self.target.observed & ~hidden,
            fill_policy=self.target.fill_policy,
        )
        provenance = dict(self.provenance)
        provenance[provenance_key] = {
            **(dict(provenance_detail) if provenance_detail else {}),
            "n_hidden_entries": int(hidden.sum()),
        }
        return MultiViewTemporalInput(
            site_keys=list(self.site_keys),
            timepoints=list(self.timepoints),
            time_minutes=self.time_minutes,
            delta_minutes=self.delta_minutes,
            time_encoding=self.time_encoding,
            target=masked_target,
            protein_context=self.protein_context,
            track1=self.track1,
            track1_available=self.track1_available,
            quality_weight=np.where(masked_target.observed, self.quality_weight, 0.0),
            eligible=self.eligible,
            site_metadata=self.site_metadata,
            motif_features=self.motif_features,
            motif_labels=self.motif_labels,
            provenance=provenance,
        )


def _time_encoding(minutes: np.ndarray) -> np.ndarray:
    """Encode irregular timepoint spacing from actual minutes.

    Positional indices would make 0->1 min and 30->60 min look identical, so the
    encoding is built from log-minutes, min-max minute position, and the
    normalized gap to the previous timepoint.
    """
    count = minutes.shape[0]
    if count == 0:
        return np.zeros((0, 5), dtype=float)

    finite = np.isfinite(minutes)
    safe = np.where(finite, minutes, 0.0).astype(float)
    log_minutes = np.log1p(np.clip(safe, 0.0, None))
    log_span = float(log_minutes.max() - log_minutes.min())
    log_scaled = (log_minutes - log_minutes.min()) / log_span if log_span > 0 else np.zeros(count)

    span = float(safe.max() - safe.min())
    linear_scaled = (safe - safe.min()) / span if span > 0 else np.zeros(count)

    gaps = np.zeros(count, dtype=float)
    if count > 1:
        gaps[1:] = np.diff(safe)
    gap_max = float(np.max(gaps)) if count > 1 else 0.0
    gap_scaled = gaps / gap_max if gap_max > 0 else np.zeros(count)

    return np.column_stack(
        [
            log_scaled,
            linear_scaled,
            gap_scaled,
            np.sin(np.pi * log_scaled),
            np.cos(np.pi * log_scaled),
        ]
    )


def _quality_weight(q_value: float, config: Mapping[str, Any]) -> float:
    floor = float(config["quality_weight_floor"])
    if not np.isfinite(q_value):
        return float(config["missing_quality_weight"])
    clipped = float(np.clip(q_value, 0.0, 1.0))
    return float(1.0 - clipped * (1.0 - floor))


def _site_key(row: Mapping[str, Any], key_level: str) -> Tuple[str, str, Dict[str, Any]]:
    gene = _as_text(_first(row, _GENE_KEYS))
    position = _as_text(_first(row, _POSITION_KEYS))
    form = _as_text(_first(row, _FORM_KEYS))
    site_key = f"{gene} {position}".strip()
    key = f"{site_key}|{form}" if key_level == "form" and form else site_key
    metadata = {
        "gene": gene,
        "position": position,
        "site_key": site_key,
        "modified_sequence": form,
        "protein_group": _as_text(_first(row, _PROTEIN_GROUP_KEYS)),
        "ptm_type": _as_text(_first(row, _PTM_TYPE_KEYS)),
    }
    return key, site_key, metadata


def build_multiview_input(
    rows: Iterable[Mapping[str, Any]],
    *,
    config: Optional[Mapping[str, Any]] = None,
    species_context: Optional[Mapping[str, Any]] = None,
) -> MultiViewTemporalInput:
    """Assemble the L3 encoder input from L1 Quantitative PTM Feature Vector rows.

    ``species_context`` is recorded as model/domain metadata only.  It is never
    turned into an input feature, so the encoder cannot become a species
    classifier across custom references such as ``rat_hir``.
    """
    effective = _merged_config(config)
    key_level = effective["key_level"]
    tiers = set(effective["qualified_pair_tiers"])

    target_values: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    protein_values: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    track1_values: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    q_values: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    motif_terms: Dict[str, set] = defaultdict(set)
    metadata: Dict[str, Dict[str, Any]] = {}
    timepoint_set: set = set()

    for row in rows:
        condition = _as_text(_first(row, _CONDITION_KEYS))
        if not condition or condition.lower() == "control":
            continue
        key, _site_only, meta = _site_key(row, key_level)
        if not key.strip():
            continue
        timepoint_set.add(condition)
        stored = metadata.setdefault(key, meta)
        stored.setdefault("quantification_track", _as_text(_first(row, _TRACK_KEYS)))

        target = _as_float(_first(row, _TARGET_KEYS))
        if np.isfinite(target):
            target_values[key][condition].append(target)

        protein = _as_float(_first(row, _PROTEIN_KEYS))
        if np.isfinite(protein):
            protein_values[key][condition].append(protein)

        tier = _as_text(_first(row, _TIER_KEYS)).upper()
        occupancy = _as_float(_first(row, _TRACK1_KEYS))
        # Track 1 enters only through qualified pairs; an unqualified or absent
        # pair stays unobserved instead of being filled with 0.
        if tier in tiers and np.isfinite(occupancy):
            track1_values[key][condition].append(occupancy)
            stored["track1_tier"] = tier
            missingness = _as_float(_first(row, _MISSINGNESS_KEYS))
            if np.isfinite(missingness):
                stored["track1_missingness"] = float(missingness)

        q_value = _as_float(_first(row, _QVALUE_KEYS))
        if np.isfinite(q_value):
            q_values[key][condition].append(q_value)

        if effective["include_motif_side_feature"]:
            motif_text = _as_text(_first(row, _MOTIF_KEYS))
            for term in motif_text.replace("|", ";").replace(",", ";").split(";"):
                term = term.strip()
                if term:
                    motif_terms[key].add(term)

    timepoints = sorted(timepoint_set, key=lambda label: (timepoint_to_minutes(label), label))
    site_keys = sorted(target_values)
    n_sites = len(site_keys)
    n_time = len(timepoints)

    minutes = np.array([timepoint_to_minutes(label) for label in timepoints], dtype=float)
    deltas = np.zeros(n_time, dtype=float)
    if n_time > 1:
        deltas[1:] = np.diff(np.where(np.isfinite(minutes), minutes, 0.0))

    def _matrix(
        source: Mapping[str, Mapping[str, List[float]]],
        name: str,
        role: str,
    ) -> TemporalViewMatrix:
        values = np.full((n_sites, n_time), np.nan, dtype=float)
        observed = np.zeros((n_sites, n_time), dtype=bool)
        for row_index, key in enumerate(site_keys):
            per_condition = source.get(key, {})
            for col_index, timepoint in enumerate(timepoints):
                samples = per_condition.get(timepoint) or []
                if samples:
                    values[row_index, col_index] = float(np.mean(samples))
                    observed[row_index, col_index] = True
        return TemporalViewMatrix(name=name, role=role, values=values, observed=observed)

    target_view = _matrix(target_values, "track2_ptm_relative_log2fc", "primary_target")
    protein_view = _matrix(protein_values, "protein_context_log2fc", "context")
    track1_view = _matrix(track1_values, "track1_apparent_paired_occupancy_logit_delta", "gated_optional")

    quality = np.full((n_sites, n_time), float(effective["missing_quality_weight"]), dtype=float)
    min_q = np.ones(n_sites, dtype=float)
    for row_index, key in enumerate(site_keys):
        per_condition = q_values.get(key, {})
        observed_q: List[float] = []
        for col_index, timepoint in enumerate(timepoints):
            samples = per_condition.get(timepoint) or []
            q_value = float(np.min(samples)) if samples else float("nan")
            quality[row_index, col_index] = _quality_weight(q_value, effective)
            if np.isfinite(q_value):
                observed_q.append(q_value)
        min_q[row_index] = float(np.min(observed_q)) if observed_q else 1.0
    # Unobserved target entries contribute no loss regardless of their weight.
    quality = np.where(target_view.observed, quality, 0.0)

    track1_available = track1_view.observed.any(axis=1)
    observed_counts = target_view.observed.sum(axis=1)
    eligible = observed_counts >= int(effective["minimum_observed_timepoints"])
    if float(effective["eligibility_q_max"]) < 1.0:
        eligible = eligible & (min_q <= float(effective["eligibility_q_max"]))

    motif_features: Optional[np.ndarray] = None
    motif_labels: Tuple[str, ...] = ()
    if effective["include_motif_side_feature"]:
        vocabulary = sorted({term for terms in motif_terms.values() for term in terms})
        motif_labels = tuple(vocabulary)
        motif_features = np.zeros((n_sites, len(vocabulary)), dtype=float)
        index_of = {term: index for index, term in enumerate(vocabulary)}
        for row_index, key in enumerate(site_keys):
            for term in motif_terms.get(key, ()):  # static prior, ablation-only
                motif_features[row_index, index_of[term]] = 1.0

    for row_index, key in enumerate(site_keys):
        meta = metadata.setdefault(key, {})
        meta["observed_timepoints"] = int(observed_counts[row_index])
        meta["track1_available"] = bool(track1_available[row_index])
        meta["min_q_value"] = float(min_q[row_index])
        meta["eligible"] = bool(eligible[row_index])

    provenance = {
        "contract_version": CONTRACT_VERSION,
        "layers": [LAYER_L2, LAYER_L3],
        "config": effective,
        "config_sha256": _config_sha(effective),
        "key_level": key_level,
        "timepoints": list(timepoints),
        "time_minutes": [None if not np.isfinite(value) else float(value) for value in minutes],
        "time_order": "observed",
        "time_encoding_features": [
            "log_minutes_scaled",
            "linear_minutes_scaled",
            "previous_gap_scaled",
            "sin_log_minutes",
            "cos_log_minutes",
        ],
        "track1_policy": "availability_masked_never_zero_filled",
        "qvalue_policy": "quality_weight_and_eligibility_mask_not_feature",
        "protein_policy": "context_branch_does_not_replace_ptm_target",
        "sequence_policy": "plm_and_raw_sequence_excluded_at_this_stage",
        "species_context": dict(species_context or {}),
        "species_policy": "model_domain_metadata_not_input_feature",
        "n_sites": n_sites,
        "n_timepoints": n_time,
        "n_eligible_sites": int(eligible.sum()),
        "n_track1_available_sites": int(track1_available.sum()),
    }

    return MultiViewTemporalInput(
        site_keys=site_keys,
        timepoints=list(timepoints),
        time_minutes=minutes,
        delta_minutes=deltas,
        time_encoding=_time_encoding(minutes),
        target=target_view,
        protein_context=protein_view,
        track1=track1_view,
        track1_available=track1_available,
        quality_weight=quality,
        eligible=eligible,
        site_metadata=metadata,
        motif_features=motif_features,
        motif_labels=motif_labels,
        provenance=provenance,
    )


def build_trajectory_vectors(
    multiview: MultiViewTemporalInput,
    *,
    view: str = "track2",
    site_level: bool = True,
) -> Tuple[Dict[str, Dict[str, float]], List[str], Dict[str, Dict[str, Any]]]:
    """Return L2 trajectories in canonical Temporal Wave Contract input form.

    ``site_level`` collapses form-level keys to ``"GENE POSITION"`` so the result
    can be compared directly against canonical co-wave memberships.
    """
    if view == "track2":
        matrix = multiview.target
    elif view == "track1":
        matrix = multiview.track1
    else:
        raise ValueError(f"Unknown trajectory view '{view}'. Use 'track2' or 'track1'.")

    grouped: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    metadata: Dict[str, Dict[str, Any]] = {}
    for row_index, key in enumerate(multiview.site_keys):
        meta = multiview.site_metadata.get(key, {})
        output_key = str(meta.get("site_key") or key) if site_level else key
        for col_index, timepoint in enumerate(multiview.timepoints):
            if matrix.observed[row_index, col_index]:
                grouped[output_key][timepoint].append(float(matrix.values[row_index, col_index]))
        stored = metadata.setdefault(output_key, {})
        stored.setdefault("gene", meta.get("gene", ""))
        stored.setdefault("site", meta.get("position", ""))
        stored.setdefault("q_value", meta.get("min_q_value"))
        stored.setdefault("forms", [])
        if key not in stored["forms"]:
            stored["forms"].append(key)

    series = {
        key: {timepoint: float(np.mean(values)) for timepoint, values in per_condition.items()}
        for key, per_condition in grouped.items()
    }
    return series, list(multiview.timepoints), metadata


def validate_multiview_input(multiview: MultiViewTemporalInput) -> List[str]:
    """Return contract violations; an empty list means a valid L3 input."""
    errors: List[str] = []
    provenance = multiview.provenance or {}
    if provenance.get("contract_version") != CONTRACT_VERSION:
        errors.append("invalid_contract_version")
    if provenance.get("track1_policy") != "availability_masked_never_zero_filled":
        errors.append("invalid_track1_policy")
    if provenance.get("qvalue_policy") != "quality_weight_and_eligibility_mask_not_feature":
        errors.append("invalid_qvalue_policy")
    if multiview.n_timepoints and multiview.time_encoding.shape[0] != multiview.n_timepoints:
        errors.append("time_encoding_shape_mismatch")

    shape = (multiview.n_sites, multiview.n_timepoints)
    for view in (multiview.target, multiview.protein_context, multiview.track1):
        if view.values.shape != shape or view.observed.shape != shape:
            errors.append(f"view_shape_mismatch:{view.name}")
        if np.any(np.isfinite(view.values) & ~view.observed):
            errors.append(f"observed_mask_inconsistent:{view.name}")
    if np.any(multiview.quality_weight[~multiview.target.observed] != 0.0):
        errors.append("unobserved_target_carries_quality_weight")
    if "q_value" in multiview.view_names:
        errors.append("qvalue_used_as_feature_view")
    return errors
