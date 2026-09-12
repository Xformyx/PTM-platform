"""Feature-preserving temporal input; no implicit gene/site aggregation.

Numbers are supplied by quantification. This builder neither estimates missing
values nor combines precursor forms, p/q values, or replicate counts.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict


CONTRACT_VERSION = "temporal_feature_input.v1"


def finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _text(value):
    text = str(value or "").strip()
    return "" if text.lower() in {"nan", "none", "null", "n/a"} else text


def site_key(row):
    return f"{_text(row.get('gene')).upper()}_{_text(row.get('position')).upper()}"


def member_key(member):
    return str(member.get("temporal_feature_key") or site_key(member)) if isinstance(member, dict) else str(member)


def build_temporal_feature_inputs(rows):
    grouped = defaultdict(lambda: defaultdict(list))
    identities = {}
    conditions = set()
    rejected = []
    for row in rows:
        condition = _text(row.get("condition"))
        if not condition:
            continue
        conditions.add(condition)
        identity = {field: _text(row.get(field)) for field in (
            "precursor_id", "modified_sequence", "precursor_charge", "protein_group",
        )}
        identity.update(gene=_text(row.get("gene")).upper(), position=_text(row.get("position")).upper())
        # Sequence alone may conflate charges/forms. Keep unresolved rows in the
        # audit without assigning them an apparently unique quantitative trajectory.
        if not identity["precursor_id"] and not (identity["modified_sequence"] and identity["precursor_charge"]):
            rejected.append({"site_key": site_key(row), "condition": condition, "reason": "precursor_identity_unavailable"})
            continue
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:20].upper()
        key = f"{site_key(row)}__PF-{digest}"
        identities[key] = {**identity, "feature_id": key, "site_key": site_key(row),
                           "measurement_unit": "modified_precursor"}
        clean = {name: (finite(value) if isinstance(value, float) else value) for name, value in row.items()}
        grouped[key][condition].append(clean)

    result = {name: {} for name in (
        "ptm_timeseries", "ptm_qvalues", "ptm_is_denovo", "occupancy_timeseries",
        "occupancy_qvalues", "features", "sites",
    )}
    for key in sorted(grouped):
        measurements = {}
        for condition, variants in sorted(grouped[key].items()):
            unique = {json.dumps(row, sort_keys=True, allow_nan=False): row for row in variants}
            if len(unique) > 1:
                measurements[condition] = {
                    "status": "conflicting_duplicate_feature_condition",
                    "source_rows": [unique[k] for k in sorted(unique)],
                }
            else:
                measurements[condition] = {"status": "recorded", "source": next(iter(unique.values()))}
        records = {c: m["source"] for c, m in measurements.items() if m["status"] == "recorded"}
        # Preserve the existing fail-closed conventional/LOD representation boundary
        # within a feature, without allowing another precursor to change its class.
        is_denovo = any(bool(row.get("is_de_novo_representation", row.get("is_denovo", False))) for row in records.values())
        selected = {c: row for c, row in records.items() if not is_denovo or row.get("is_de_novo_representation", row.get("is_denovo", False))}
        result["ptm_timeseries"][key] = {c: finite(row.get("log2fc")) for c, row in selected.items() if finite(row.get("log2fc")) is not None}
        result["ptm_qvalues"][key] = {c: finite(selected[c].get("q_value")) for c in result["ptm_timeseries"][key]}
        result["ptm_is_denovo"][key] = is_denovo
        occupancy = {c: row for c, row in records.items() if row.get("pair_quality_tier") in {"O1", "O2"} and finite(row.get("occupancy_logit_delta")) is not None}
        if occupancy:
            result["occupancy_timeseries"][key] = {c: finite(row.get("occupancy_logit_delta")) for c, row in occupancy.items()}
            result["occupancy_qvalues"][key] = {c: finite(row.get("occupancy_q_value")) for c, row in occupancy.items()}
        result["features"][key] = {**identities[key], "measurements": measurements,
            "representation": "detection_lod" if is_denovo else "protein_adjusted_relative_ptm_log2_contrast",
            "observed_conditions": sorted(result["ptm_timeseries"][key]),
            "missing_conditions": sorted(conditions - result["ptm_timeseries"][key].keys())}
        site = identities[key]["site_key"]
        result["sites"].setdefault(site, {"constituent_features": [], "aggregation_rule": "none_feature_level_only"})["constituent_features"].append(key)
    for site in result["sites"].values():
        conflicts = []
        for condition in sorted(conditions):
            values = [result["ptm_timeseries"][key][condition] for key in site["constituent_features"] if condition in result["ptm_timeseries"][key]]
            if any(v > 0 for v in values) and any(v < 0 for v in values):
                conflicts.append(condition)
        site["opposite_form_conditions"] = conflicts
    result.update(contract_version=CONTRACT_VERSION, conditions=sorted(conditions),
                  rejected_rows=sorted(rejected, key=lambda r: (r["site_key"], r["condition"])))
    result["input_sha256"] = hashlib.sha256(json.dumps(result, sort_keys=True, allow_nan=False).encode()).hexdigest()
    return result


def bind_modules_to_features(modules, packet):
    """Expand site-level candidate membership without merging observed forms.

    These are candidate links at the original reference scope, not evidence of
    direct modification of each precursor or independent biological replicates.
    """
    output = []
    for module in modules:
        members = {}
        for member in module.get("ptms", []):
            for key in packet["sites"].get(site_key(member), {}).get("constituent_features", []):
                identity = packet["features"][key]
                precursor = _text(member.get("precursor_id") or member.get("Precursor.Id"))
                if precursor and precursor != identity["precursor_id"]:
                    continue
                members[key] = {**member, "temporal_feature_key": key,
                                "site_key": identity["site_key"], "precursor_id": identity["precursor_id"]}
        output.append({**module, "ptms": [members[key] for key in sorted(members)]})
    return output
