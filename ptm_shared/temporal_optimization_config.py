"""Frozen truth-free temporal configuration selected by nested validation.

Selection used only replicate holdout stability, Wave structure, TMM holdout
reconstruction, and parsimony.  No locked benchmark truth was available to the
selector.  The ordinary production defaults remain unchanged; strict benchmark
runs opt in explicitly while the configuration undergoes server confirmation.
"""

from __future__ import annotations

import hashlib
import json


CONTRACT_VERSION = "truth_free_temporal_optimized.v2"
SELECTION_RECORD_SHA256 = "2a6c7c728b2b931cb00f275e39be721a4ed904f95c566077219c3f5c254201e1"
SELECTION_LAST_RECORD_SHA256 = "f535cb2e319de574395b7e108216832ba5154d1c4a0bf4f415321f6db59f1b7a"

SITE_AGGREGATION = "median"

WAVE_CONFIG = {
    "correlation_threshold": 0.70,
    "minimum_variance": 0.30,
    "minimum_amplitude": 0.40,
    "minimum_cluster_size": 2,
    "maximum_waves": 8,
    "compute_directionality": True,
    "bootstrap_repeats": 25,
    "soft_membership_threshold": 0.60,
    "threshold_source": CONTRACT_VERSION,
}

TMM_CONFIG = {
    "profile_min_exclusive": 5,
    "gaussian_sigma_log": 0.80,
    "target_transform": "magnitude",
    "activity_metric": "shrunken_mean",
    "shrinkage_prior_support": 10.0,
    "candidate_prior_strength": 5.0,
    "candidate_hierarchy_mode": "family_guard",
    "iterative_profile_rounds": 0,
    "iterative_min_top1_probability": 0.80,
    "iterative_min_shared_support": 3,
    "iterative_profile_blend": 0.50,
    "dual_track_correlation_threshold": 0.50,
    "dual_track_peak_index_tolerance": 2,
    "dual_track_magnitude_log2_ratio_threshold": 1.0,
    "uncertainty_bootstrap_repeats": 50,
    "uncertainty_loto_enabled": True,
    "uncertainty_seed": 20260826,
}

ADDITIVE_V2_CONTRACT_VERSION = "enrichment_free_temporal_mechanism.v2"
ADDITIVE_V2_SELECTION_LEDGER_SHA256 = "818b7ef4e9ea27b61791ad85f919ab3b1812284edf80c267c078a637cd2ee114"
ADDITIVE_V2_SELECTION_LAST_RECORD_SHA256 = "8464787a5bd1d43feecaf072de74fe283956f294812be431f68f72c7f7b092b0"
CROSS_LAYER_CONFIG = {
    "minimum_absolute_change": 0.30,
    "minimum_lag_aware_similarity": 0.40,
    "minimum_loto_stability": 0.60,
    "maximum_candidates_per_wave": 200,
    "bootstrap_iterations": 0,
    "permutation_iterations": 0,
    "random_seed": 20260827,
}
DYNAMIC_COWAVE_CONTRACT_VERSION = "dynamic_co_wave_transition.v2"
DYNAMIC_COWAVE_SELECTION_LEDGER_SHA256 = "02ab551eb3c345250fa1e76758599e18026fa6b8c72889d95b7c533ebede882e"
DYNAMIC_COWAVE_SELECTION_RECORD_SHA256 = "2d12157f12eed4a3322a9a0253257352003e84044534d53dec03336770b1a08e"
DYNAMIC_COWAVE_LEDGER_TAIL_RECORD_SHA256 = "baf6849198616b6771358cc3e6936c2ac83b7c2c5f558741600345322aefdf51"
DYNAMIC_COWAVE_CONFIG = {
    "activity_threshold_fc": 0.40,
    "minimum_observed_timepoints": 4,
    "membership_universe": "retained_canonical_wave_members_only",
    "pair_scope": "same_static_wave_only",
    "site_event_policy": "record_noninert_transitions_only",
    "lotto": "leave_one_timepoint_out",
    "maximum_pair_transition_examples": 500,
    "maximum_site_transition_examples": 500,
    "maximum_membership_examples": 250,
}
_ADDITIVE_V2_CONFIG = {
    "contract_version": ADDITIVE_V2_CONTRACT_VERSION,
    "cross_layer": CROSS_LAYER_CONFIG,
    "dynamic_cowave": DYNAMIC_COWAVE_CONFIG,
}
ADDITIVE_V2_CONFIG_SHA256 = hashlib.sha256(
    json.dumps(_ADDITIVE_V2_CONFIG, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()

_CANONICAL_CONFIG = {
    "contract_version": CONTRACT_VERSION,
    "site_aggregation": SITE_AGGREGATION,
    "wave": WAVE_CONFIG,
    "tmm": TMM_CONFIG,
}
CONFIG_SHA256 = hashlib.sha256(
    json.dumps(_CANONICAL_CONFIG, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()


def provenance() -> dict[str, object]:
    return {
        "contract_version": CONTRACT_VERSION,
        "config_sha256": CONFIG_SHA256,
        "selection_record_sha256": SELECTION_RECORD_SHA256,
        "selection_last_record_sha256": SELECTION_LAST_RECORD_SHA256,
        "selection_objective": "truth_free_nested_replicate_stability_and_reconstruction",
        "truth_used_for_selection": False,
        "replicate_outer_folds": 3,
        "selection_trial_count": 7,
        "iterative_profile_decision": "rejected_rounds_zero_retained",
        "site_aggregation": SITE_AGGREGATION,
        "wave": dict(WAVE_CONFIG),
        "tmm": dict(TMM_CONFIG),
        "additive_v2": {
            "contract_version": ADDITIVE_V2_CONTRACT_VERSION,
            "config_sha256": ADDITIVE_V2_CONFIG_SHA256,
            "selection_ledger_sha256": ADDITIVE_V2_SELECTION_LEDGER_SHA256,
            "selection_last_record_sha256": ADDITIVE_V2_SELECTION_LAST_RECORD_SHA256,
            "selection_trial_count": 9,
            "truth_used_for_selection": False,
            "cross_layer": dict(CROSS_LAYER_CONFIG),
            "dynamic_cowave": {
                "contract_version": DYNAMIC_COWAVE_CONTRACT_VERSION,
                "configuration": dict(DYNAMIC_COWAVE_CONFIG),
                "selection_ledger_sha256": DYNAMIC_COWAVE_SELECTION_LEDGER_SHA256,
                "selection_record_sha256": DYNAMIC_COWAVE_SELECTION_RECORD_SHA256,
                "ledger_tail_record_sha256": DYNAMIC_COWAVE_LEDGER_TAIL_RECORD_SHA256,
                "selection_trial_count": 3,
                "truth_used_for_selection": False,
                "selection_objective": "0.45_pair_loto_jaccard + 0.25_site_loto_jaccard + 0.20_active_pair_coverage + 0.10_transition_resolution",
            },
            "protein_replicate_stability_status": "unavailable_condition_level_only",
        },
    }


if __name__ == "__main__":
    print(json.dumps(provenance(), ensure_ascii=False, indent=2))
