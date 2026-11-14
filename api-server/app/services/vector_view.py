"""Vector view orchestration shared by routes; annotation failure is non-blocking."""
import csv
import hashlib
import json
import math
from pathlib import Path
from ptm_shared.plot_selection import DEFAULT_VIEW_TOP_N, build_vector_view
from ptm_shared.vector_plot import normalize_plot_records, plot_feature_metadata, project_plot_row


from ptm_shared.vector_snapshot import load_vector_snapshot

CLASSIC_TOP_N_DEFAULT = 20
"""Historical Top N Time-series default when report_options.top_n_ptms is absent.

구현 대상: 원본 GET /vector-plot-data (0ac2338, 선정 규칙은 b150a01까지 유지).
사전등록: 2026-02 표시 경로. 측정 공식 변경 아님. 2026-09-21 표시 복원.
해석 한계: 화면 선정이다. identity-projected vector_view.v2 선정이 아니고
kinase 귀속 정확도를 말하지 않는다.
주장 금지: 이 N으로 예측이 좋아졌다고 쓰지 않는다.
측정 후 변경 금지 — 바꾸면 고전 Top N 도형이 다른 모집단을 그린다.
"""


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


def _classic_rank_score(row):
    score = row.get("ranking_score")
    if isinstance(score, (int, float)) and not isinstance(score, bool) and math.isfinite(score):
        return float(score)
    if row.get("conventional_log2fc_na") or row.get("control_pseudocount_used"):
        return 0.0
    value = row.get("ptm_relative_log2fc")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return abs(float(value))
    return 0.0


def _classic_site_key(gene, pos):
    return (str(gene or "").strip().upper(), str(pos or "").strip().upper())


def _classic_annotation_sites(annotations):
    sites = set()
    for ptm in annotations:
        gene = ptm.get("gene") or ptm.get("Gene.Name") or ""
        pos = ptm.get("position") or ptm.get("PTM_Position") or ""
        key = _classic_site_key(gene, pos)
        if key[0] or key[1]:
            sites.add(key)
    return sites


def load_classic_top_n_plot(output_dir, suffix, report_options=None, *, design=None,
                            mode="per_condition_top_n", n=None, axis="adjusted",
                            representation="conventional_log2_contrast", ranking_metric="abs_effect"):
    """Classic renderer consumes the common identity/eligibility selection."""
    options = {"top_n_ptms": CLASSIC_TOP_N_DEFAULT, **(report_options or {})}
    view = load_vector_view(output_dir, suffix, options, mode=mode, n=n, axis=axis,
                            representation=representation, ranking_metric=ranking_metric, design=design)
    return jsonable_classic_payload({
        **view, "vector_data": view["observations"], "top_n_ptms": view["features"],
        "top_n_setting": view["selection"]["n"], "source": "preprocessing",
        "classic_selection_source": "canonical_eligible_feature_selection",
    })


def jsonable_classic_payload(value):
    """Drop bulk provenance and replace non-finite floats so Starlette can encode.

    구현 대상: 고전 Top N HTTP 표시. Starlette JSONResponse는 allow_nan=False.
    사전등록: 해당 없음 (직렬화). 2026-09-21. 측정값 변경 아님.
    해석 한계: NaN/Inf는 미기입이다. 0이나 결측 증거가 아니다.
    주장 금지: 정제를 정량 보정으로 쓰지 않는다.
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: jsonable_classic_payload(item) for key, item in value.items()
                if key not in {"source_record", "source_row_lineage"}}
    if isinstance(value, list):
        return [jsonable_classic_payload(item) for item in value]
    if isinstance(value, tuple):
        return [jsonable_classic_payload(item) for item in value]
    return value
