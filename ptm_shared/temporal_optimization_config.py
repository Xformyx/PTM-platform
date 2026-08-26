"""Frozen truth-free temporal configuration selected by nested validation.

Selection used only replicate holdout stability, Wave structure, TMM holdout
reconstruction, and parsimony.  No locked benchmark truth was available to the
selector.  The ordinary production defaults remain unchanged; strict benchmark
runs opt in explicitly while the configuration undergoes server confirmation.
"""

from __future__ import annotations

import hashlib
import json


CONTRACT_VERSION = "truth_free_temporal_optimized.v1"
SELECTION_RECORD_SHA256 = "2c625933b8fdab6fe59f7bc48eee00ee1698b1f4f253df86e1099fb79f618c62"

SITE_AGGREGATION = "median"

WAVE_CONFIG = {
    "correlation_threshold": 0.70,
    "minimum_variance": 0.30,
    "minimum_amplitude": 0.40,
    "minimum_cluster_size": 2,
    "maximum_waves": 8,
    "compute_directionality": True,
    "threshold_source": CONTRACT_VERSION,
}

TMM_CONFIG = {
    "profile_min_exclusive": 5,
    "gaussian_sigma_log": 0.80,
    "target_transform": "magnitude",
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
        "selection_objective": "truth_free_nested_replicate_stability_and_reconstruction",
        "truth_used_for_selection": False,
        "replicate_outer_folds": 3,
        "site_aggregation": SITE_AGGREGATION,
        "wave": dict(WAVE_CONFIG),
        "tmm": dict(TMM_CONFIG),
    }


if __name__ == "__main__":
    print(json.dumps(provenance(), ensure_ascii=False, indent=2))
