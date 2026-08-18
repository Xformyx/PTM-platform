"""PTM representation learning contract v1 (L1-L4).

Layer summary:

* ``L1`` Quantitative PTM Feature Vector - the already-shipped handcrafted
  representation produced by ``create_ptm_vector_data``.  Preserved unchanged and
  named here so later comparisons can cite it explicitly.
* ``L2`` Temporal PTM Trajectory Vector - ordered-timepoint Track 2 trajectory;
  remains the primary input of canonical co-wave and TMM.
* ``L3`` Multi-view Temporal PTM Input - encoder input only.
* ``L4`` Learned Temporal PTM Embedding - secondary evidence only.

The architecture is parallel, not serial: raw Track 2 keeps driving co-wave and
TMM while the learned layer contributes additive stability, concordance, and
profile-quality fields that must be traceable back to L1/L2 values.
"""

from ptm_shared.representation.baselines import (
    RepresentationResult,
    fpca_lite,
    handcrafted_representation,
    mask_aware_nmf,
    mask_aware_pca,
    run_r0_baselines,
    smooth_trajectories,
)
from ptm_shared.representation.benchmark import (
    VariantFit,
    adjusted_rand_index,
    cluster_representation,
    evaluate_adoption_gates,
    evaluate_variant,
    fit_variant,
    run_ablation,
)
from ptm_shared.representation.encoder import (
    DEFAULT_ENCODER_CONFIG,
    ENCODER_VERSION,
    EncoderResult,
    fit_masked_temporal_encoder,
)
from ptm_shared.representation.fair_probe import (
    ProbeFold,
    compare_to_baseline,
    run_heldout_timepoint_probe,
    summarize_arms,
)
from ptm_shared.representation.feature_contract import (
    MultiViewTemporalInput,
    TemporalViewMatrix,
    build_multiview_input,
    build_trajectory_vectors,
    validate_multiview_input,
)
from ptm_shared.representation.layers import (
    ADDITIVE_FIELDS,
    ADOPTION_GATES,
    CONTRACT_VERSION,
    LAYER_L1,
    LAYER_L2,
    LAYER_L3,
    LAYER_L4,
    LAYERS,
    PRIMARY_SCORE_INPUTS_LOCKED,
    VARIANTS,
    RepresentationLayer,
    RepresentationVariant,
    describe_contract,
    preserved_baseline_layer,
    resolve_layer,
    resolve_variant,
    variant_order,
)
from ptm_shared.representation.metrics import (
    AdditiveFieldResult,
    build_additive_fields,
    embedding_neighbor_stability,
    profile_representational_dispersion,
    representation_track_concordance,
    top_k_neighbors,
)

__all__ = [
    "ADDITIVE_FIELDS",
    "ADOPTION_GATES",
    "AdditiveFieldResult",
    "CONTRACT_VERSION",
    "DEFAULT_ENCODER_CONFIG",
    "ENCODER_VERSION",
    "EncoderResult",
    "LAYERS",
    "LAYER_L1",
    "LAYER_L2",
    "LAYER_L3",
    "LAYER_L4",
    "MultiViewTemporalInput",
    "PRIMARY_SCORE_INPUTS_LOCKED",
    "ProbeFold",
    "RepresentationLayer",
    "RepresentationResult",
    "RepresentationVariant",
    "TemporalViewMatrix",
    "VARIANTS",
    "VariantFit",
    "adjusted_rand_index",
    "build_additive_fields",
    "build_multiview_input",
    "build_trajectory_vectors",
    "cluster_representation",
    "compare_to_baseline",
    "describe_contract",
    "embedding_neighbor_stability",
    "evaluate_adoption_gates",
    "evaluate_variant",
    "fit_masked_temporal_encoder",
    "fit_variant",
    "fpca_lite",
    "handcrafted_representation",
    "mask_aware_nmf",
    "mask_aware_pca",
    "preserved_baseline_layer",
    "profile_representational_dispersion",
    "representation_track_concordance",
    "resolve_layer",
    "resolve_variant",
    "run_ablation",
    "run_heldout_timepoint_probe",
    "run_r0_baselines",
    "smooth_trajectories",
    "summarize_arms",
    "top_k_neighbors",
    "validate_multiview_input",
    "variant_order",
]
