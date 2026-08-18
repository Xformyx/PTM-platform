"""PTM representation layer contract v1.

This module is the naming authority for the four PTM representation layers and
for the Representation A-E ablation variants.  It contains no numeric work so
that API, workers, docs, and benchmarks all cite identical layer identifiers.

The layer separation exists because "PTM Vector" previously named several
different objects at once.  L1 is the already-shipped handcrafted quantitative
representation and is preserved unchanged: nothing in this package rewrites
``create_ptm_vector_data`` or its TSV schema.  L4 never replaces L1/L2; a
conclusion supported by L4 must remain traceable to L1/L2 raw values, wave
evidence, TMM contribution, and Track 1/Track 2 status.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple


CONTRACT_VERSION = "ptm_representation_contract.v1"

LAYER_L1 = "quantitative_ptm_feature_vector"
LAYER_L2 = "temporal_ptm_trajectory_vector"
LAYER_L3 = "multiview_temporal_ptm_input"
LAYER_L4 = "learned_temporal_ptm_embedding"


@dataclass(frozen=True)
class RepresentationLayer:
    """One named representation layer with its provenance and guarantees."""

    layer_id: str
    name: str
    display_name: str
    unit: str
    interpretability: str
    produced_by: str
    artifact: str
    contents: Tuple[str, ...]
    aliases: Tuple[str, ...] = ()
    replaces_lower_layers: bool = False
    description: str = ""

    @property
    def method_id(self) -> str:
        """Stable identifier for benchmark tables and Methods sections."""
        return f"{self.layer_id}_{self.name}.v1"


# L1 is the currently shipped implementation.  It keeps its exact producer,
# artifact name, and column contract; this registry only gives it a stable
# academic name so later comparisons can reference it explicitly.
_L1 = RepresentationLayer(
    layer_id="L1",
    name=LAYER_L1,
    display_name="Quantitative PTM Feature Vector",
    unit="site/form x timepoint",
    interpretability="high",
    produced_by=(
        "workers.preprocessing.core.ptm_quantification."
        "PTMQuantificationAnalyzer.create_ptm_vector_data"
    ),
    artifact="ptm_vector_data_normalized{file_suffix}.tsv",
    contents=(
        "PTM_Relative_Log2FC",
        "Protein_Log2FC",
        "p_value",
        "q_value",
        "Quantification_Track",
        "Occupancy_Logit_Delta",
        "Pair_Quality_Tier",
        "Pair_Missingness",
    ),
    aliases=("ptm_vector", "ptm_vector_data_normalized", "handcrafted_ptm_vector"),
    description=(
        "Structured feature representation assembled from protein-normalized "
        "modification changes, protein abundance changes, statistical evidence, "
        "and paired modified/unmodified measurements.  Preserved unchanged."
    ),
)

_L2 = RepresentationLayer(
    layer_id="L2",
    name=LAYER_L2,
    display_name="Temporal PTM Trajectory Vector",
    unit="site/form",
    interpretability="high",
    produced_by="ptm_shared.representation.feature_contract.build_trajectory_vectors",
    artifact="derived_in_memory",
    contents=("track2_trajectory", "track1_optional_trajectory"),
    aliases=("temporal_vector",),
    description=(
        "Ordered-timepoint Track 2 trajectory with an optional Track 1 "
        "trajectory.  Primary input of canonical co-wave and TMM."
    ),
)

_L3 = RepresentationLayer(
    layer_id="L3",
    name=LAYER_L3,
    display_name="Multi-view Temporal PTM Input",
    unit="site/form x timepoint x view",
    interpretability="medium",
    produced_by="ptm_shared.representation.feature_contract.build_multiview_input",
    artifact="derived_in_memory",
    contents=(
        "track2_primary",
        "protein_context",
        "track1_availability_masked",
        "time_encoding",
        "quality_weight",
    ),
    description=(
        "Encoder input only.  Track 1 absence is represented by an availability "
        "mask and is never zero-filled; q-values enter as quality weight and "
        "eligibility mask rather than as biological feature dimensions."
    ),
)

_L4 = RepresentationLayer(
    layer_id="L4",
    name=LAYER_L4,
    display_name="Learned Temporal PTM Embedding",
    unit="site/form",
    interpretability="low_requires_raw_evidence_traceback",
    produced_by="ptm_shared.representation.encoder.fit_masked_temporal_encoder",
    artifact="ptm_representation_embeddings{file_suffix}.tsv",
    contents=(
        "latent_vector",
        "representation_reconstruction_error",
        "embedding_neighbor_stability",
        "embedding_uncertainty",
    ),
    aliases=("learned_ptm_embedding",),
    description=(
        "Latent representation learned from quantitative PTM vectors across "
        "ordered timepoints and molecular context.  Secondary evidence only."
    ),
)

LAYERS: Dict[str, RepresentationLayer] = {
    layer.layer_id: layer for layer in (_L1, _L2, _L3, _L4)
}

_LAYER_BY_NAME: Dict[str, RepresentationLayer] = {}
for _layer in LAYERS.values():
    _LAYER_BY_NAME[_layer.name] = _layer
    for _alias in _layer.aliases:
        _LAYER_BY_NAME[_alias] = _layer


def resolve_layer(label: str) -> RepresentationLayer:
    """Resolve a layer id, canonical name, or legacy alias without guessing."""
    raw = str(label or "").strip()
    if raw.upper() in LAYERS:
        return LAYERS[raw.upper()]
    canonical = raw.lower().replace("-", "_").replace(" ", "_")
    if canonical in _LAYER_BY_NAME:
        return _LAYER_BY_NAME[canonical]
    raise ValueError(
        f"Unknown PTM representation layer '{label}'. "
        f"Known layers: {', '.join(sorted(LAYERS))} "
        f"({', '.join(layer.name for layer in LAYERS.values())})."
    )


def preserved_baseline_layer() -> RepresentationLayer:
    """Return the named, unchanged current PTM Vector implementation (L1)."""
    return LAYERS["L1"]


# ---------------------------------------------------------------------------
# Representation A-E ablation variants
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RepresentationVariant:
    """One pre-registered comparison arm of the A-E ablation."""

    variant_id: str
    name: str
    display_name: str
    layers: Tuple[str, ...]
    views: Tuple[str, ...]
    learned: bool
    guardrails: Tuple[str, ...]
    description: str = ""
    encoder_options: Mapping[str, Any] = field(default_factory=dict)

    @property
    def uses_prior_features(self) -> bool:
        """True when the arm injects motif/sequence priors that can leak labels."""
        return "motif" in self.views


VARIANTS: Dict[str, RepresentationVariant] = {
    "A": RepresentationVariant(
        variant_id="A",
        name="track2_trajectory_only",
        display_name="A: Track 2 temporal trajectory only",
        layers=(LAYER_L2,),
        views=("track2",),
        learned=False,
        guardrails=("canonical_signed_pearson_tmm_baseline",),
        description="Canonical baseline: the raw Track 2 trajectory itself.",
    ),
    "B": RepresentationVariant(
        variant_id="B",
        name="handcrafted_quantitative_vector",
        display_name="B: current handcrafted L1 vector",
        layers=(LAYER_L1, LAYER_L2),
        views=("track2", "protein_context", "quality"),
        learned=False,
        guardrails=("protein_context_and_quality_incremental_value",),
        description=(
            "The preserved current PTM Vector used as a representation, so the "
            "learned arms must beat it rather than replace it by assumption."
        ),
    ),
    "C": RepresentationVariant(
        variant_id="C",
        name="handcrafted_plus_motif",
        display_name="C: B + motif/static sequence descriptors",
        layers=(LAYER_L1, LAYER_L2),
        views=("track2", "protein_context", "quality", "motif"),
        learned=False,
        guardrails=(
            "motif_prior_dominance_check",
            "held_out_kinase_family_leakage_check",
        ),
        description="Static prior arm; requires strict family holdout to interpret.",
    ),
    "D": RepresentationVariant(
        variant_id="D",
        name="learned_temporal_representation",
        display_name="D: learned temporal representation",
        layers=(LAYER_L3, LAYER_L4),
        views=("track2",),
        learned=True,
        guardrails=(
            "time_order_permutation",
            "masked_reconstruction",
            "wave_stability",
        ),
        description="Mask-aware self-supervised encoder on the Track 2 view only.",
        encoder_options={"use_protein_context": False, "use_track1": False},
    ),
    "E": RepresentationVariant(
        variant_id="E",
        name="learned_multiview_representation",
        display_name="E: learned multi-view representation",
        layers=(LAYER_L3, LAYER_L4),
        views=("track2", "protein_context", "track1_masked"),
        learned=True,
        guardrails=(
            "track1_track2_availability_bias",
            "protein_abundance_confounding",
            "cross_dataset_stability",
        ),
        description=(
            "Track 2 primary branch, protein context branch, and Track 1 "
            "availability-masked gated branch."
        ),
        encoder_options={"use_protein_context": True, "use_track1": True},
    ),
}


def resolve_variant(label: str) -> RepresentationVariant:
    """Resolve an ablation arm by id (``"A"``) or canonical name."""
    raw = str(label or "").strip()
    if raw.upper() in VARIANTS:
        return VARIANTS[raw.upper()]
    canonical = raw.lower().replace("-", "_").replace(" ", "_")
    for variant in VARIANTS.values():
        if variant.name == canonical:
            return variant
    raise ValueError(
        f"Unknown representation variant '{label}'. "
        f"Known variants: {', '.join(sorted(VARIANTS))}."
    )


def variant_order() -> List[str]:
    """Pre-registered evaluation order for the ablation table."""
    return sorted(VARIANTS)


# ---------------------------------------------------------------------------
# Additive secondary fields (R2) and adoption gates
# ---------------------------------------------------------------------------

ADDITIVE_FIELDS: Dict[str, str] = {
    "profile_representational_dispersion": (
        "Embedding dispersion of exclusive substrates assigned to a candidate "
        "kinase; heterogeneous-profile warning candidate."
    ),
    "embedding_neighbor_stability": (
        "Top-k neighbour overlap under bootstrap/mask perturbation."
    ),
    "representation_reconstruction_error": (
        "Held-out observed-value reconstruction error; low-quality embedding flag."
    ),
    "representation_track_concordance": (
        "Agreement between latent neighbours and Track 1/Track 2 peak and "
        "direction evidence."
    ),
    "representation_supported": (
        "Latent neighbourhood agrees with raw co-wave evidence."
    ),
    "representation_discordant": (
        "Bootstrap-stable disagreement between raw co-wave/TMM and the latent "
        "neighbourhood; review queue, not a score change."
    ),
}

ADOPTION_GATES: Tuple[str, ...] = (
    "time_validity",
    "missingness_validity",
    "raw_evidence_concordance",
    "generalization",
    "no_prior_leakage",
    "interpretability",
)

#: TMM coefficients and canonical co-wave membership stay on raw Track 2.
PRIMARY_SCORE_INPUTS_LOCKED: Tuple[str, ...] = (
    "canonical_co_wave_membership",
    "tmm_contribution_coefficients",
    "kinase_ranking",
)


def describe_contract() -> Dict[str, Any]:
    """Machine-readable contract summary for manifests and Methods sections."""
    return {
        "contract_version": CONTRACT_VERSION,
        "layers": [
            {
                "layer_id": layer.layer_id,
                "name": layer.name,
                "method_id": layer.method_id,
                "display_name": layer.display_name,
                "unit": layer.unit,
                "interpretability": layer.interpretability,
                "produced_by": layer.produced_by,
                "artifact": layer.artifact,
                "replaces_lower_layers": layer.replaces_lower_layers,
            }
            for layer in LAYERS.values()
        ],
        "variants": [
            {
                "variant_id": variant.variant_id,
                "name": variant.name,
                "display_name": variant.display_name,
                "learned": variant.learned,
                "views": list(variant.views),
                "guardrails": list(variant.guardrails),
            }
            for variant in (VARIANTS[key] for key in variant_order())
        ],
        "additive_fields": dict(ADDITIVE_FIELDS),
        "adoption_gates": list(ADOPTION_GATES),
        "primary_score_inputs_locked": list(PRIMARY_SCORE_INPUTS_LOCKED),
        "preserved_baseline": preserved_baseline_layer().method_id,
    }
