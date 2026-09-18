"""Vector view orchestration shared by routes; annotation failure is non-blocking."""
import csv
import hashlib
import json
from pathlib import Path
from ptm_shared.plot_selection import DEFAULT_VIEW_TOP_N, build_vector_view
from ptm_shared.vector_plot import normalize_plot_records, project_plot_row


from ptm_shared.vector_snapshot import load_vector_snapshot


def load_annotations(output_dir, suffix):
    path = Path(output_dir) / f"enriched_ptm_data{suffix}.json"
    source = {"kind": "rag", "status": "missing", "revision": None}
    if not path.is_file():
        return [], source
    raw = path.read_bytes()
    source["revision"] = "annotation-sha256:" + hashlib.sha256(raw).hexdigest()
    try:
        payload = json.loads(raw)
        if not isinstance(payload, list):
            raise ValueError("annotation root must be an array")
        valid = [r for r in payload if isinstance(r, dict)]
        source["status"] = "partial" if len(valid) != len(payload) else "available" if valid else "empty"
        source["invalid_records"] = len(payload) - len(valid)
        return valid, source
    except (ValueError, UnicodeError):
        source.update(status="failed", failure_reason="annotation_parse_failure")
        return [], source


def resolve_view_options(report_options, *, mode, n, axis, representation, ranking_metric):
    if n is None and mode in {"per_condition_top_n", "global_top_n"}:
        n = (report_options or {}).get("top_n_ptms", DEFAULT_VIEW_TOP_N)
        # An old All sentinel is not a new display policy.
        if n == 9999:
            mode, n = "all_observed", None
    return dict(mode=mode, n=n, axis=axis, representation=representation, ranking_metric=ranking_metric)


def load_vector_view(output_dir, suffix, report_options=None, *, mode="per_condition_top_n", n=None,
                     axis="adjusted", representation="conventional_log2_contrast", ranking_metric="abs_effect",
                     design=None, declared_conditions=()):
    from ptm_shared.quantitative_fields import axis_evidence
    options = resolve_view_options(report_options, mode=mode, n=n, axis=axis, representation=representation, ranking_metric=ranking_metric)
    counts = None
    if (Path(output_dir)/f"vector_columnar{suffix}.json").is_file() and mode != "rag_only" and representation == "conventional_log2_contrast" and ranking_metric == "abs_effect":
        from ptm_shared.vector_columnar import VectorColumnar
        store = VectorColumnar(output_dir, suffix)
        try:
            counts = store.manifest_counts()
            statistics = store.selection_statistics(axis)
            ids = store.select_ids(mode=options["mode"], n=options["n"], axis=axis)
            selected_rows = []
            for start in range(0, len(ids), 1000):
                selected_rows.extend(store.trajectories(ids[start:start+1000]))
            snapshot = {"rows":selected_rows,"measurement_revision":counts["measurement_revision"],
                "source_rows":counts["source_rows"],"quarantine":[]}
            declared_conditions = declared_conditions or counts["conditions"]
        finally:
            store.close()
    else:
        snapshot = load_vector_snapshot(output_dir, suffix)
    annotations, source = load_annotations(output_dir, suffix)
    for row in snapshot["rows"]:
        for current_axis, prefix in (("unadjusted", "ptm_unadjusted"), ("protein", "protein"), ("adjusted", "ptm_protein_adjusted")):
            support = axis_evidence(row, current_axis, design or {})
            for arm in ("control", "treatment"):
                row[f"{prefix}_{arm}_biological_n"] = support[f"{arm}_biological_n"]
    options = resolve_view_options(report_options, mode=mode, n=n, axis=axis, representation=representation, ranking_metric=ranking_metric)
    view = build_vector_view(snapshot["rows"], annotations, measurement_revision=snapshot["measurement_revision"],
                             source_rows=snapshot["source_rows"], quarantine_count=len(snapshot["quarantine"]),
                             annotation_source=source, declared_conditions=declared_conditions, **options)
    if counts:
        view["coverage"].update(identified_features=counts["identified_features"],
            identity_unresolved_rows=counts["identity_unresolved_rows"], quarantined_rows=counts["malformed_source_rows"])
        view["selection"]["axis_eligible_feature_count"] = statistics["axis_eligible_feature_count"]
        view["selection"]["selection_hash"] = hashlib.sha256(json.dumps({k:v for k,v in view["selection"].items() if k != "selection_hash"},sort_keys=True).encode()).hexdigest()
        view["coverage"]["selection_reasons"] = {"outside_top_n":statistics["axis_eligible_feature_count"]-len(ids)}
        view["coverage"]["malformed_source_rows"] = counts["malformed_source_rows"]
        view["suggestion"].update(threshold=statistics["threshold"],feature_count=statistics["feature_count"])
        view["suggested_n"] = statistics["feature_count"]
    return view
