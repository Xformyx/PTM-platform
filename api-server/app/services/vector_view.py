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


def load_classic_top_n_plot(output_dir, suffix, report_options=None, *, design=None):
    """Restore the pre-vector_view.v2 Top N Time-series payload.

    구현 대상: 원본 GET /vector-plot-data (0ac2338 도입, b150a01 선정).
    사전등록: 표시 복원. 2026-09-21. 결과 열람 후 exploratory. primary 금지.
    해석 한계: RAG가 Top N만 쓰던 시절의 화면이다. 전수 enriched JSON은
    조건별 Top N 합집합보다 크면 TSV 순위로 되돌린다. 값을 합치지 않는다.
    주장 금지: 이 선정으로 kinase 예측이 좋아졌다고 쓰지 않는다.
    """
    from ptm_shared.quantitative_fields import axis_evidence
    snapshot = load_vector_snapshot(output_dir, suffix)
    rows = snapshot["rows"]
    annotations, source = load_annotations(output_dir, suffix)
    n = (report_options or {}).get("top_n_ptms", CLASSIC_TOP_N_DEFAULT)
    if n == 9999 or not isinstance(n, int) or isinstance(n, bool) or n < 1:
        n = CLASSIC_TOP_N_DEFAULT
    for row in rows:
        for current_axis, prefix in (("unadjusted", "ptm_unadjusted"), ("protein", "protein"), ("adjusted", "ptm_protein_adjusted")):
            support = axis_evidence(row, current_axis, design or {})
            for arm in ("control", "treatment"):
                row[f"{prefix}_{arm}_biological_n"] = support[f"{arm}_biological_n"]
    conditions = {row.get("condition") for row in rows if row.get("condition")}
    sites = _classic_annotation_sites(annotations)
    # Historical RAG files *were* the Top N set. A full-inventory RAG file is not.
    use_enriched = bool(sites) and len(sites) <= n * max(len(conditions), 1)
    if use_enriched:
        selected_keys = sites
        selection_source = "enriched_top_n"
        payload_source = "enriched"
    else:
        selected_keys = set()
        for cond in conditions:
            cond_rows = [row for row in rows if row.get("condition") == cond]
            cond_rows.sort(
                key=lambda row: (
                    _classic_rank_score(row),
                    str(row.get("feature_id") or ""),
                    str(row.get("gene") or ""),
                    str(row.get("position") or ""),
                ),
                reverse=True,
            )
            for row in cond_rows[:n]:
                selected_keys.add(_classic_site_key(row.get("gene"), row.get("position")))
        selection_source = "tsv_per_condition_ranking"
        payload_source = "preprocessing"
    selected_rows = [
        row for row in rows
        if _classic_site_key(row.get("gene"), row.get("position")) in selected_keys
    ]
    features = plot_feature_metadata(selected_rows, annotations)
    by_site = {}
    for ptm in annotations:
        gene = ptm.get("gene") or ptm.get("Gene.Name") or ""
        pos = ptm.get("position") or ptm.get("PTM_Position") or ""
        by_site.setdefault(_classic_site_key(gene, pos), ptm)
    display_keys = (
        "denovo_confidence", "detection_control", "detection_pattern", "lod_relative_log2",
        "peak_condition", "onset_condition", "reliable_onset_condition", "shared_peptide",
        "p1_pattern", "protein_class",
    )
    for feature in features:
        src = by_site.get(_classic_site_key(feature.get("gene"), feature.get("position")), {})
        for key in display_keys:
            if feature.get(key) in (None, "") and src.get(key) not in (None, ""):
                feature[key] = src[key]
        if src.get("conventional_log2fc_na") or src.get("control_pseudocount_used") or src.get("Conventional_Log2FC_NA"):
            feature["conventional_log2fc_na"] = True
    return jsonable_classic_payload({
        "vector_data": selected_rows,
        "top_n_ptms": features,
        "top_n_setting": n,
        "suggested_n": None,
        "source": payload_source,
        "classic_selection_source": selection_source,
        "annotation_source": source,
        "measurement_revision": snapshot["measurement_revision"],
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
