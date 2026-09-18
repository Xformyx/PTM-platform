"""Read a full quantitative snapshot for API, workers and analysis manifests."""
import csv
import hashlib
from pathlib import Path
from ptm_shared.vector_plot import normalize_plot_records, project_plot_row
from ptm_shared.tabular_import import validate_tabular_header

def load_vector_snapshot(output_dir, suffix):
    rows, quarantine, count = [], [], 0
    for name in (f"ptm_vector_data_normalized{suffix}.tsv", f"ptm_vector_data_with_motifs{suffix}.tsv"):
        path = Path(output_dir) / name
        if not path.is_file():
            continue
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024*1024), b""):
                digest.update(block)
        revision = "vector-sha256:" + digest.hexdigest()
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            validate_tabular_header(reader.fieldnames)
            for raw in reader:
                count += 1
                locator = {"artifact": name, "line": reader.line_num, "revision": revision}
                if None in raw or any(v is None for v in raw.values()):
                    quarantine.append({"locator": locator, "reason": "malformed_source_row", "raw": raw})
                    continue
                raw["source_row_lineage"] = [locator]
                projected = project_plot_row(raw)
                projected["source_record"] = raw
                rows.append(projected)
        return {"rows": normalize_plot_records(rows), "measurement_revision": revision,
                "source_rows": count, "quarantine": quarantine}
    return {"rows": [], "measurement_revision": None, "source_rows": 0, "quarantine": []}



def attach_full_motif_annotations(snapshot, output_dir, suffix):
    """Exact measurement-ID join of the full precursor motif table, never RAG.

    The normalized vector remains the quantitative authority. Conflicting motif
    assertions are withheld and recorded instead of taking the last row.
    """
    from .report_revision import file_sha256
    path = Path(output_dir)/f"ptm_vector_data_with_motifs{suffix}.tsv"
    if not path.is_file():
        snapshot["candidate_sources"] = {"motif": {"status": "unavailable"}}
        return snapshot
    annotations = {}
    fields = ("Motif_Evidence_Policy", "Predicted_Regulator", "Matched_Motifs")
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        validate_tabular_header(reader.fieldnames)
        for raw in reader:
            if None in raw or any(v is None for v in raw.values()):
                continue
            projected = project_plot_row(raw)
            if not projected.get("feature_id"):
                continue
            value = tuple(raw.get(key) or "" for key in fields)
            annotations.setdefault(projected["feature_id"], set()).add(value)
    conflict = 0
    for row in snapshot["rows"]:
        values = annotations.get(row.get("feature_id"), set())
        if len(values) == 1:
            row["source_record"] = {**row.get("source_record", {}), **dict(zip(fields, next(iter(values))))}
        elif len(values) > 1:
            conflict += 1
            row["source_record"] = {**row.get("source_record", {}), "Motif_Evidence_Policy": "conflicting_assertions"}
    snapshot["candidate_sources"] = {"motif": {"status": "partial" if conflict else "available",
        "sha256": file_sha256(path), "conflicting_feature_condition_rows": conflict}}
    return snapshot
