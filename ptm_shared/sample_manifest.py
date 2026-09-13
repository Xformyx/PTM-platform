"""Explicit study units; filenames never imply biological replication or pairing."""
import math
from collections import defaultdict

SAMPLE_MANIFEST_VERSION = "sample_manifest.v1"


def validate_sample_manifest(manifest, condition_map=None, pr_columns=None, pg_columns=None):
    if not manifest or (manifest.get("schema_version") == SAMPLE_MANIFEST_VERSION
                        and manifest.get("status") == "unavailable" and not manifest.get("samples")):
        return {"schema_version": SAMPLE_MANIFEST_VERSION, "status": "unavailable", "samples": [], "conditions": [],
                "statistical_unit": "sample_observation_biological_design_unavailable"}
    result = dict(manifest)
    samples = manifest.get("samples") or []
    if not samples:
        raise ValueError("sample_manifest.samples is required")
    seen = set()
    for sample in samples:
        sid = sample.get("sample_id")
        if not sid or sid in seen or not sample.get("condition") or not sample.get("biological_unit"):
            raise ValueError("Each sample requires a unique sample_id, condition and biological_unit")
        seen.add(sid)
        if condition_map is not None and (sid not in condition_map or sample["condition"] != condition_map[sid]):
            raise ValueError("Sample manifest does not match sample_config conditions")
        if pr_columns is not None and sid not in pr_columns:
            raise ValueError("Sample manifest sample is absent from PR columns")
        if pg_columns is not None and sid not in pg_columns:
            raise ValueError("Sample manifest sample is absent from PG columns")
    if condition_map and seen != set(condition_map):
        raise ValueError("Sample manifest must cover configured samples exactly")
    pairing = manifest.get("pairing", "unpaired")
    if pairing not in {"paired", "unpaired"}:
        raise ValueError("pairing must be paired or unpaired")
    for condition in manifest.get("conditions") or []:
        if not condition.get("condition"):
            raise ValueError("Condition label is required")
        for key in ("time_minutes", "elapsed_time"):
            if condition.get(key) is not None and not math.isfinite(float(condition[key])):
                raise ValueError("Condition time must be finite")
    return {**result, "schema_version": SAMPLE_MANIFEST_VERSION, "status": "validated", "pairing": pairing}


def unit_test_inputs(control, treatment, manifest=None):
    """Reduce technical observations within each biological unit for testing only.

    The reported U/A sample-ratio estimators remain unchanged. No CI is invented.
    """
    clean = lambda values: {k: float(v) for k, v in values.items() if v is not None and math.isfinite(float(v))}
    control, treatment = clean(control), clean(treatment)
    base = {"control_sample_n": len(control), "treatment_sample_n": len(treatment), "aggregation_rule": "none"}
    if not manifest or not manifest.get("samples"):
        return {**base, "control": list(control.values()), "treatment": list(treatment.values()),
                "statistical_unit": "sample_observation_biological_design_unavailable", "test": "welch", "status": "legacy_design_unavailable"}
    samples = {s["sample_id"]: s for s in manifest["samples"]}
    groups = []
    for values in (control, treatment):
        units = defaultdict(list)
        for sid, value in values.items():
            unit = samples.get(sid, {}).get("biological_unit")
            if not unit:
                return {**base, "control": [], "treatment": [], "statistical_unit": "unavailable", "test": "unavailable", "status": "unresolved_biological_unit"}
            units[str(unit)].append(value)
        groups.append({u: sum(v) / len(v) for u, v in units.items()})
    c, t = groups
    base.update(control_biological_n=len(c), treatment_biological_n=len(t),
                statistical_unit="biological_unit", aggregation_rule="arithmetic_mean_within_biological_unit")
    paired = manifest.get("pairing") == "paired"
    if paired:
        units = sorted(c.keys() & t.keys())
        return {**base, "control": [c[u] for u in units], "treatment": [t[u] for u in units],
                "paired_units": units, "test": "paired", "status": "eligible" if len(units) >= 2 else "insufficient_biological_units"}
    if c.keys() & t.keys():
        return {**base, "control": [], "treatment": [], "test": "unavailable", "status": "shared_units_require_explicit_paired_design"}
    return {**base, "control": [c[u] for u in sorted(c)], "treatment": [t[u] for u in sorted(t)],
            "test": "welch", "status": "eligible" if min(len(c), len(t)) >= 2 else "insufficient_biological_units"}


def compare_sample_units(control, treatment, manifest=None):
    from scipy import stats
    inputs = unit_test_inputs(control, treatment, manifest)
    p = None
    if min(len(inputs["control"]), len(inputs["treatment"])) >= 2 and inputs["test"] != "unavailable":
        result = (stats.ttest_rel(inputs["control"], inputs["treatment"]) if inputs["test"] == "paired"
                  else stats.ttest_ind(inputs["control"], inputs["treatment"], equal_var=False))
        p = float(result.pvalue) if math.isfinite(float(result.pvalue)) else None
    return {**inputs, "p_value": p, "method": inputs["test"] + "; " + inputs["statistical_unit"] + "; " + inputs["aggregation_rule"],
            "status": inputs["status"] if p is not None else inputs["status"] + ":test_unavailable"}
