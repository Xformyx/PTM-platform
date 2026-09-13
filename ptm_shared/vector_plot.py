"""Vector API presentation adapter. Null is an observation state, never zero."""
from .vector_projection import project_report_vector_row, _optional_float, _optional_bool, _text
from .quantitative_fields import project_axis_fields
import json
from copy import deepcopy
import hashlib
from .feature_identity import FEATURE_IDENTITY_VERSION


def quantitative_cache_key(rows):
    """Cache only identical measured inputs, independent of TSV row ordering."""
    records = sorted(json.dumps(row, sort_keys=True, allow_nan=False) for row in rows)
    return hashlib.sha256(json.dumps([FEATURE_IDENTITY_VERSION, records]).encode()).hexdigest()


def normalize_plot_records(rows):
    """Deduplicate identical exports and withhold conflicting condition values."""
    grouped = {}
    for row in rows:
        key = (row.get("feature_id"), row["condition"])
        # Unresolved identities remain diagnostic rows, never combined by site.
        if not key[0]:
            key = (json.dumps(row, sort_keys=True), row["condition"])
        grouped.setdefault(key, {})[json.dumps(row, sort_keys=True)] = row
    output = []
    for key, variants in sorted(grouped.items()):
        row = deepcopy(variants[sorted(variants)[0]])
        if len(variants) > 1:
            row.update(project_axis_fields({}))
            row.update(ptm_relative_log2fc=None, ptm_absolute_log2fc=None, p_value=None, q_value=None,
                       lod_relative_log2=None, normalized_log2_intensity=None, conflicting_row_count=len(variants))
            for axis, prefix in (("unadjusted", "ptm_unadjusted"), ("protein", "protein"), ("adjusted", "ptm_protein_adjusted")):
                row[f"{prefix}_missing_reason"] = "conflicting_feature_condition"
                row["axis_eligibility"][axis] = {"eligible": False, "missing_reason": "conflicting_feature_condition"}
        output.append(row)
    return output


def project_plot_row(row):
    result = project_report_vector_row(row)
    for name, raw in (("control_pseudocount_used", "Control_Pseudocount_Used"),
                      ("conventional_log2fc_na", "Conventional_Log2FC_NA"), ("shared_peptide", "Shared_Peptide")):
        result[name] = bool(_optional_bool(row, name, raw))
    for name in ("denovo_confidence", "detection_control", "detection_treatment", "detection_pattern",
                 "peak_condition", "onset_condition", "reliable_onset_condition", "quantification_track",
                 "paired_peptide_key", "paired_form_level", "occupancy_calibration_type", "pair_quality_tier"):
        raw = "DeNovo_Confidence" if name == "denovo_confidence" else "_".join(p.capitalize() for p in name.split("_"))
        result[name] = _text(row, name, raw) or ""
    for name in ("lod_relative_log2", "lod_intensity", "normalized_log2_intensity", "ranking_score", "detection_n",
                 "detection_expected", "occupancy_fraction", "occupancy_percent", "occupancy_delta_pp",
                 "occupancy_logit_delta", "pair_missingness", "occupancy_p_value", "occupancy_q_value"):
        raw = "_".join({"lod": "LOD", "pp": "PP", "log2": "Log2"}.get(p, p.capitalize()) for p in name.split("_"))
        result[name] = _optional_float(row, name, raw)
    # Compatibility names have exactly the canonical axis semantics.
    result["ptm_relative_log2fc"] = result["ptm_protein_adjusted_log2fc"]
    result["ptm_absolute_log2fc"] = result["ptm_reconstructed_log2fc"]
    result["p_value"] = result["ptm_protein_adjusted_p_value"]
    result["q_value"] = result["ptm_protein_adjusted_q_value"]
    result["axis_eligibility"] = {
        axis: {"eligible": result[f"{prefix}_log2fc"] is not None and not (
            axis in {"unadjusted", "adjusted"} and result["conventional_log2fc_na"]),
               "missing_reason": result.get(f"{prefix}_missing_reason")}
        for axis, prefix in (("unadjusted", "ptm_unadjusted"), ("protein", "protein"), ("adjusted", "ptm_protein_adjusted"))
    }
    return result


def plot_feature_metadata(rows, annotations):
    """Expand site annotations to identified forms; never aggregate their values."""
    by_site = {(str(p.get("gene", "")), str(p.get("position", ""))): p for p in annotations}
    selected = {}
    for row in sorted(rows, key=lambda r: (r.get("feature_id") or "", r["condition"])):
        fid = row.get("feature_id")
        site = (row["gene"], row["position"])
        if not fid or (by_site and site not in by_site):
            continue
        if fid not in selected:
            selected[fid] = {**by_site.get(site, {}), **{k: row.get(k) for k in (
                "gene", "position", "feature_id", "feature_identity_version", "precursor_id", "precursor_charge",
                "modified_sequence", "protein_group", "conventional_log2fc_na", "denovo_confidence")},
                "label": f"{row['gene']} {row['position']} · {row['reader_feature_id']}",
                "p1_pattern": None, "annotation_scope": "gene_site_context_not_feature_measurement"}
    return list(selected.values())
