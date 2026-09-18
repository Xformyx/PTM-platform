"""Versioned feature-wide allocation result, separate from per-kinase scores."""
import hashlib

ALLOCATION_VERSION = "tmm_feature_allocation.v2"
LEGACY_ALLOCATION_VERSION = "tmm_feature_allocation.v1"
RNG_POLICY_VERSION = "feature_sha256_seed.v1"


class TMMScoreResults(dict):
    """Dict-compatible scorer return; callers persist the ledger separately once."""
    def __init__(self, *args, allocation_ledger=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.allocation_ledger = allocation_ledger or {}


def feature_seed(seed, feature_id):
    return (int(seed) + int(hashlib.sha256(str(feature_id).encode()).hexdigest()[:8], 16)) % (2**32)


def allocation_record(feature_id, candidates, attribution, observed, raw_ratios):
    if attribution is None or not attribution.attribution_supported:
        return {"feature_id": feature_id, "candidates": candidates, "evaluation_status": "not_evaluable",
                "reason": getattr(attribution, "unsupported_reason", None) or "attribution_failed",
                "allocations": [], "allocated_total": None, "observed": observed,
                "raw_numerical_fit": raw_ratios}
    allocations = []
    seen = set()
    for name in candidates:
        entry = attribution.per_kinase.get(name) or {}
        if not entry.get("attribution_supported"):
            continue
        group = tuple(sorted(entry.get("group_members") or [name]))
        if group in seen:
            continue
        seen.add(group)
        ratio = float(entry.get("group_ratio", entry.get("ratio", 0)))
        allocations.append({"entity_type": "kinase_group" if len(group) > 1 else "kinase",
                            "members": list(group), "ratio": ratio,
                            "individual_ratios_evaluable": len(group) == 1,
                            "weighted_observations": {c: v * ratio for c, v in observed.items()}})
    total = sum(a["ratio"] for a in allocations)
    if allocations and abs(total - 1) > 1e-6:
        raise ValueError(f"allocation conservation failed for {feature_id}: {total}")
    return {"feature_id": feature_id, "candidates": candidates, "evaluation_status": "evaluated",
            "allocations": allocations, "allocated_total": total, "observed": observed,
            "raw_numerical_fit": raw_ratios, "residual_is_biological_probability": False}
