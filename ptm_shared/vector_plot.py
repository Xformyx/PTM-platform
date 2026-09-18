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


def vector_tsv_cache_fingerprint(output_dir, file_suffix: str) -> str:
    """Hash the first available vector TSV so TMM cache follows preprocessing.

    구현 대상: docs/official_temporal_terminology_contract.md § TMM heatmap cache
    사전등록: 2026-09-14 표시/캐시 계약. 결과 열람 후 임계 변경 아님.
    해석 한계: 파일 hash는 관측 규칙이 TSV에 기록된 뒤에만 무효화된다.
    주장 금지: 재계산을 하류 개선이나 kinase 정확도 향상으로 해석하지 않는다.
    """
    from pathlib import Path

    destination = Path(output_dir)
    for name in (f"ptm_vector_data_normalized{file_suffix}.tsv", f"ptm_vector_data_with_motifs{file_suffix}.tsv"):
        path = destination / name
        if not path.is_file():
            continue
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return f"{FEATURE_IDENTITY_VERSION}:{name}:{digest.hexdigest()}"
    return f"{FEATURE_IDENTITY_VERSION}:missing"


def normalize_plot_records(rows):
    """Deduplicate identical exports and withhold conflicting condition values."""
    grouped = {}
    for row in rows:
        key = (row.get("feature_id"), row["condition"])
        # Unresolved identities remain diagnostic rows, never combined by site.
        if not key[0]:
            key = (json.dumps(row, sort_keys=True), row["condition"])
        grouped.setdefault(key, []).append(row)
    output = []
    for key, members in sorted(grouped.items()):
        members = sorted(members, key=lambda r: json.dumps(r, sort_keys=True))
        row = deepcopy(members[0])
        variants = {json.dumps(measurement_signature(r), sort_keys=True) for r in members}
        row["source_row_lineage"] = [locator for r in members for locator in r.get("source_row_lineage", [])]
        row["source_labels"] = sorted({str(r.get("source_gene_label") or r.get("gene") or "") for r in members})
        row["source_row_count"] = sum(r.get("source_row_count", 1) for r in members)
        if len(variants) > 1:
            row.update(project_axis_fields({}))
            row.update(ptm_relative_log2fc=None, ptm_absolute_log2fc=None, p_value=None, q_value=None,
                       lod_relative_log2=None, normalized_log2_intensity=None, conflicting_row_count=len(variants))
            for axis, prefix in (("unadjusted", "ptm_unadjusted"), ("protein", "protein"), ("adjusted", "ptm_protein_adjusted")):
                row[f"{prefix}_missing_reason"] = "conflicting_feature_condition"
                row["axis_eligibility"][axis] = {"eligible": False, "missing_reason": "conflicting_feature_condition"}
        output.append(row)
    return output


def measurement_signature(row):
    """Labels/locators may differ; observation units and quantitative support may not."""
    prefixes = ("ptm_unadjusted_", "ptm_protein_adjusted_", "protein_", "ptm_reconstructed_")
    names = {"feature_id", "condition", "time_minutes", "reference_id", "sample_id", "biological_unit",
             "source_observation_id", "axis_eligibility", "lod_relative_log2", "normalized_log2_intensity",
             "conventional_log2fc_na", "control_pseudocount_used", "detection_control", "detection_treatment",
             "detection_n", "detection_expected", "occupancy_fraction", "occupancy_logit_delta", "pair_quality_tier"}
    return {k: v for k, v in row.items() if k in names or k.startswith(prefixes)}


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


def plot_feature_metadata(rows, annotations, selected_feature_ids=None):
    """Expand site annotations to identified forms; never aggregate their values."""
    from .annotation_context import AnnotationIndex
    index = AnnotationIndex(annotations)
    allowed = set(selected_feature_ids) if selected_feature_ids is not None else None
    selected = {}
    for row in sorted(rows, key=lambda r: (r.get("feature_id") or "", r["condition"])):
        fid = row.get("feature_id")
        if not fid or (allowed is not None and fid not in allowed):
            continue
        if fid not in selected:
            match = index.match(row)
            selected[fid] = {**{k: row.get(k) for k in (
                "gene", "position", "feature_id", "feature_identity_version", "precursor_id", "precursor_charge",
                "modified_sequence", "protein_group", "fasta_taxonomy_id", "isoform", "accession",
                "source_gene_label", "source_position_label", "conventional_log2fc_na", "denovo_confidence")},
                "label": f"{str(row.get('source_gene_label') or row['gene']).strip()} {row['position']} · {row['reader_feature_id']}",
                "p1_pattern": None, "annotation_scope": match["match_scope"], "annotation_match": match}
    return list(selected.values())
