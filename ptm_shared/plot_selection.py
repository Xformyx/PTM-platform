"""Deterministic display selection; no discovery/statistical eligibility thresholds."""
from collections import Counter, defaultdict
import hashlib
import json
import math
import re
from typing import Literal, TypedDict

DEFAULT_VIEW_TOP_N = 50
VIEW_CONTRACT_VERSION = "vector_view.v2"
SelectionMode = Literal["per_condition_top_n", "global_top_n", "all_observed", "rag_only"]
AXES = {"adjusted": "ptm_protein_adjusted", "unadjusted": "ptm_unadjusted", "protein": "protein"}
REPRESENTATIONS = {"conventional_log2_contrast", "lod_relative_log2", "normalized_log2_intensity", "occupancy_logit_delta"}


class Selection(TypedDict):
    mode: SelectionMode
    n: int | None
    axis: str
    representation: str
    selected_feature_ids: list[str]
    selection_status: str


def representation_value(row, axis="adjusted", representation="conventional_log2_contrast"):
    if row.get("conflicting_row_count"):
        return None
    if representation == "conventional_log2_contrast":
        if row.get("axis_eligibility", {}).get(axis, {}).get("eligible") is False:
            return None
        value = row.get(f"{AXES[axis]}_log2fc")
    else:
        value = row.get(representation)
    return float(value) if isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value) else None


def ordered_conditions(rows, declared_conditions=()):
    times = defaultdict(set)
    for row in rows:
        condition = row.get("condition")
        if condition:
            times[condition]
            if isinstance(row.get("time_minutes"), (int, float)) and math.isfinite(row["time_minutes"]):
                times[condition].add(float(row["time_minutes"]))
    declared = {str(c): i for i, c in enumerate(declared_conditions)}
    for c in declared:
        times[c]
    def key(c):
        if c in declared:
            return (0, declared[c], c)
        if len(times[c]) == 1:
            return (1, next(iter(times[c])), c)
        # Explicit units in a label are usable; arbitrary numbers are not times.
        parsed = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(s|sec|min|m|h|hr)\s*", c, re.I)
        if parsed and not times[c]:
            scale = {"s": 1/60, "sec": 1/60, "min": 1, "m": 1, "h": 60, "hr": 60}[parsed[2].lower()]
            return (1, float(parsed[1]) * scale, c)
        return (2, 0, c)
    return sorted(times, key=key)


def select_plot_features(rows, *, mode="per_condition_top_n", n=DEFAULT_VIEW_TOP_N,
                         axis="adjusted", representation="conventional_log2_contrast",
                         ranking_metric="abs_effect", annotation_matches=None, annotation_status="missing"):
    if mode not in {"per_condition_top_n", "global_top_n", "all_observed", "rag_only"}:
        raise ValueError("unknown selection mode")
    if axis not in AXES or representation not in REPRESENTATIONS:
        raise ValueError("unknown axis or representation")
    if ranking_metric not in {"abs_effect", "legacy_ranking_score"}:
        raise ValueError("unknown ranking metric")
    if mode in {"per_condition_top_n", "global_top_n"}:
        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            raise ValueError("Top N requires a positive integer")
    elif n is not None:
        raise ValueError("all_observed and rag_only require n=null")
    by_condition, scores = defaultdict(dict), {}
    for row in rows:
        fid = row.get("feature_id")
        value = representation_value(row, axis, representation)
        if not fid or value is None:
            continue
        score = abs(value) if ranking_metric == "abs_effect" else row.get("ranking_score")
        if not isinstance(score, (float, int)) or not math.isfinite(score):
            continue
        by_condition[row["condition"]][fid] = score
        scores[fid] = max(scores.get(fid, -math.inf), score)
    ordered = sorted(scores, key=lambda fid: (-scores[fid], fid))
    per_condition = {c: sorted(values, key=lambda fid: (-values[fid], fid))[:n]
                     for c, values in sorted(by_condition.items())} if mode == "per_condition_top_n" else {}
    status, reasons = "ready", []
    if mode == "per_condition_top_n":
        chosen = set(fid for ids in per_condition.values() for fid in ids)
    elif mode == "global_top_n":
        chosen = set(ordered[:n])
    elif mode == "rag_only":
        if annotation_status in {"missing", "failed", "unavailable"}:
            status, reasons = "unavailable", [f"annotation_{annotation_status}"]
        chosen = {fid for fid, match in (annotation_matches or {}).items() if fid in scores
                  and match["status"] == "matched" and match["match_scope"] in {"feature", "site_context"}}
        if status == "unavailable":
            chosen = set()
    else:
        chosen = set(ordered)
    if not chosen and status == "ready":
        status = "empty_selection"
    ids = [fid for fid in ordered if fid in chosen]
    selection = {"mode": mode, "n": n, "axis": axis, "representation": representation,
                 "unit": "modified_precursor_feature", "ranking_metric": ranking_metric,
                 "ranking_version": "plot_rank.v1", "tie_break": "feature_id_ascending",
                 "eligibility_order": "axis_before_selection", "selection_status": status,
                 "reason_codes": reasons, "selected_feature_ids": ids,
                 "per_condition_selected_count": {c: len(v) for c, v in per_condition.items()},
                 "per_condition_selected_ids": per_condition,
                 "union_feature_count": len(ids), "axis_eligible_feature_count": len(scores)}
    selection["selection_hash"] = hashlib.sha256(json.dumps(selection, sort_keys=True).encode()).hexdigest()
    return selection


def build_vector_view(rows, annotations=(), *, measurement_revision, annotation_source,
                      source_rows=None, quarantine_count=0, declared_conditions=(), **options):
    from .vector_plot import plot_feature_metadata
    features = plot_feature_metadata(rows, annotations)
    matches = {p["feature_id"]: p["annotation_match"] for p in features}
    selection = select_plot_features(rows, annotation_matches=matches,
                                    annotation_status=annotation_source["status"], **options)
    ids = set(selection["selected_feature_ids"])
    lookup = {f["feature_id"]: f for f in features}
    features = [lookup[fid] for fid in selection["selected_feature_ids"]]
    observations = [r for r in rows if r.get("feature_id") in ids]
    matched = Counter(p["annotation_match"]["status"] for p in features)
    axis, representation = selection["axis"], selection["representation"]
    eligible = {r.get("feature_id") for r in observations if representation_value(r, axis, representation) is not None}
    finite = sum(representation_value(r, axis, representation) is not None for r in observations)
    identified = {r["feature_id"] for r in rows if r.get("feature_id")}
    axis_reasons = Counter()
    for row in observations:
        if representation_value(row, axis, representation) is None:
            reason = ("conflicting_feature_condition" if row.get("conflicting_row_count") else
                      row.get(f"{AXES[axis]}_missing_reason") if representation == "conventional_log2_contrast" else
                      "missing_lod_representation" if representation == "lod_relative_log2" else "representation_not_applicable")
            axis_reasons[reason or "axis_value_missing"] += 1
    coverage = {"source_rows": source_rows if source_rows is not None else sum(r.get("source_row_count", 1) for r in rows),
                "malformed_source_rows": quarantine_count, "identified_features": len(identified),
                "identity_unresolved_rows": sum(r.get("source_row_count", 1) for r in rows if not r.get("feature_id")),
                "selected_features": len(ids), "identity_valid_selected_features": len(ids),
                "axis_eligible_selected_features": len(eligible), "finite_observations": finite,
                **{f"annotation_{state}_features": matched[state] for state in ("matched", "unmatched", "ambiguous")},
                "selection_reasons": {"outside_explicit_rag_scope" if selection["mode"] == "rag_only" else "outside_top_n":
                                      selection["axis_eligible_feature_count"] - len(ids)},
                "axis_observation_reasons": dict(axis_reasons),
                "annotation_is_selection_gate": selection["mode"] == "rag_only"}
    all_values = [(r.get("feature_id"), representation_value(r, axis, representation)) for r in rows if r.get("feature_id")]
    values = [abs(v) for _, v in all_values if v is not None]
    threshold = None
    if values:
        mean = sum(values) / len(values)
        threshold = mean + 2 * math.sqrt(sum((v-mean)**2 for v in values) / len(values))
    suggestion = {"method": "mean_abs_effect_plus_2_population_sd", "scope": "all_identified_axis_observations",
                  "axis": axis, "representation": representation, "threshold": threshold,
                  "feature_count": len({fid for fid, v in all_values if v is not None and threshold is not None and abs(v) >= threshold}),
                  "applied_to_selection": False}
    return {"contract_version": VIEW_CONTRACT_VERSION, "measurement_revision": measurement_revision,
            "selection": selection, "sources": {"measurements": {"kind": "preprocessing_vector", "revision": measurement_revision},
                                                "annotations": annotation_source},
            "coverage": coverage, "features": features, "observations": observations,
            "conditions": ordered_conditions(rows, declared_conditions), "suggestion": suggestion,
            "vector_data": observations, "top_n_ptms": features, "source": "preprocessing",
            "top_n_setting": selection["n"], "suggested_n": suggestion["feature_count"]}
