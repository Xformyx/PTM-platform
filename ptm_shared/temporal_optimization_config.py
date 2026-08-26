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
    }


if __name__ == "__main__":
    print(json.dumps(provenance(), ensure_ascii=False, indent=2))
