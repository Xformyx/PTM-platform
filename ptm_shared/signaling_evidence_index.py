"""Immutable, derived Explorer index. None of its projections feed computation."""
import base64
import json
import os
from pathlib import Path
import duckdb
from .analysis_universe import signature
from .report_revision import _atomic_json
from .pathway_membership_index import build_pathway_result, read_pathway_reference
from .analysis_validation_registry import build_validation_registry
from .temporal_feature_input import finite

VERSION = "signaling_explorer.v1"
KINDS = {"features", "pathways", "members", "kinases", "contributions", "evidence", "source-runs", "model-results", "report-claims",
         "unmapped-modules", "validations", "model-comparisons", "mechanism-hypotheses", "experiment-suggestions"}
OBSERVATION_TRACKS = ("relative", "unadjusted", "occupancy")
EXPLORER_COPY_MEMORY_DEFAULT = "512MB"
"""DuckDB COPY ceiling after streaming flatten.

docs/BUILD_AND_DEPLOY.md §5.1, 2026-09-21. Not a measurement threshold.
"""

EXPLORER_JSONL_CHUNK_BYTES = 32 * 1024 * 1024
"""Max jsonl bytes per DuckDB COPY.

docs/BUILD_AND_DEPLOY.md §5.1, 2026-09-21. Order 80 records jsonl is 806MB.
"""


def write_explorer_observation_jsonl(records_jsonl, dest):
    """Flatten feature trajectories one jsonl line at a time.

    구현 대상: docs/BUILD_AND_DEPLOY.md §5.1
    사전등록: 해당 없음 (인덱스 작성 경로, 2026-09-21).
    해석 한계: Explorer 조회용 숫자 투영이다. TMM 점수 입력이 아니다.
    주장 금지: 이 파일로 kinase 활성이나 τ를 논하지 않는다.
    """
    count = 0
    with Path(records_jsonl).open(encoding="utf-8") as src, Path(dest).open("w", encoding="utf-8") as out:
        for line in src:
            row = json.loads(line)
            if row.get("kind") != "features":
                continue
            payload = json.loads(row["record_json"])
            feature_id = row.get("feature_id") or payload.get("feature_id") or ""
            trajectories = payload.get("trajectories") or {}
            for track in OBSERVATION_TRACKS:
                series = trajectories.get(track)
                if not isinstance(series, dict):
                    continue
                for condition, value in series.items():
                    if value is None or isinstance(value, (dict, list)):
                        continue
                    try:
                        number = float(value)
                    except (TypeError, ValueError):
                        continue
                    if number != number:
                        continue
                    out.write(json.dumps({
                        "feature_id": feature_id,
                        "track": track,
                        "condition": str(condition),
                        "value": number,
                    }, allow_nan=False) + "\n")
                    count += 1
    return count


def _duckdb_copy_config(spill=None):
    config = {"threads": 1, "memory_limit": os.getenv("EXPLORER_INDEX_MEMORY_LIMIT", EXPLORER_COPY_MEMORY_DEFAULT)}
    if spill is not None:
        Path(spill).mkdir(parents=True, exist_ok=True)
        config["temp_directory"] = str(spill)
    return config


def split_jsonl_by_bytes(jsonl, dest_dir, max_bytes=EXPLORER_JSONL_CHUNK_BYTES):
    """Split jsonl on line boundaries so each DuckDB COPY stays under max_bytes."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    parts = []
    handle = None
    size = 0
    index = 0

    def rotate():
        nonlocal handle, size, index
        if handle is not None:
            handle.close()
        path = dest_dir / f"part-{index:05d}.jsonl"
        parts.append(path)
        handle = path.open("w", encoding="utf-8")
        size = 0
        index += 1

    rotate()
    with Path(jsonl).open(encoding="utf-8") as src:
        for line in src:
            encoded = line if line.endswith("\n") else line + "\n"
            nbytes = len(encoded.encode("utf-8"))
            if size and size + nbytes > max_bytes:
                rotate()
            handle.write(encoded)
            size += nbytes
    if handle is not None:
        handle.close()
    return parts


def _copy_one_jsonl_to_parquet(jsonl, parquet, columns, *, spill=None):
    with duckdb.connect(config=_duckdb_copy_config(spill)) as db:
        db.execute("SET preserve_insertion_order=false")
        db.read_json(str(jsonl), format="newline_delimited", columns=columns).create_view("src")
        db.execute(
            "COPY (SELECT * FROM src) TO ? (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 4096)",
            [str(parquet)],
        )


def parquet_files_for_index(path):
    """Prefer sibling part parquet files. Do not merge them in DuckDB."""
    path = Path(path)
    parts = sorted(path.parent.glob(f"{path.stem}-part-*.parquet"))
    if parts:
        return [str(part) for part in parts]
    return [str(path)]


def explorer_record_parquet_files(directory):
    """Parquet sources for Explorer pages. Prefer parts; do not merge them."""
    return parquet_files_for_index(Path(directory) / "explorer_records.parquet")


def _write_records_layout(parquet, part_count):
    parquet = Path(parquet)
    payload = json.dumps({"part_count": part_count, "part_glob": f"{parquet.stem}-part-*.parquet"})
    with duckdb.connect(config=_duckdb_copy_config()) as db:
        db.execute(
            """
            CREATE TABLE layout(
              kind VARCHAR, record_id VARCHAR, feature_id VARCHAR,
              pathway_key VARCHAR, kinase VARCHAR, track VARCHAR, record_json VARCHAR
            )
            """
        )
        db.execute(
            "INSERT INTO layout VALUES ('layout','parts','','','','',?)",
            [payload],
        )
        db.execute(
            "COPY layout TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
            [str(parquet)],
        )


def _copy_jsonl_to_parquet(jsonl, parquet, columns, *, spill=None):
    """Copy jsonl to parquet in bounded chunks. Page queries sort.

    구현 대상: docs/BUILD_AND_DEPLOY.md §5.1 EXPLORER_JSONL_CHUNK_BYTES
    사전등록: 해당 없음 (인덱스 작성, 2026-09-21).
    해석 한계: Explorer 파일 레이아웃만 나눈다. TMM 입력이 아니다.
    주장 금지: 청크 수로 분석 규모를 주장하지 않는다.
    """
    jsonl = Path(jsonl)
    parquet = Path(parquet)
    if jsonl.stat().st_size <= EXPLORER_JSONL_CHUNK_BYTES:
        _copy_one_jsonl_to_parquet(jsonl, parquet, columns, spill=spill)
        return
    parts_dir = jsonl.parent / f"{jsonl.stem}-parts"
    parts = split_jsonl_by_bytes(jsonl, parts_dir, EXPLORER_JSONL_CHUNK_BYTES)
    for i, part in enumerate(parts):
        _copy_one_jsonl_to_parquet(
            part,
            parquet.parent / f"{parquet.stem}-part-{i:05d}.parquet",
            columns,
            spill=spill,
        )
    _write_records_layout(parquet, len(parts))


def iter_explorer_records(directory, *, report_index=None):
    """Stream the same complete, joined inventory used by page queries."""
    files = explorer_record_parquet_files(directory)
    if report_index:
        files.extend(parquet_files_for_index(report_index))
    with duckdb.connect(config={"threads": 1, "memory_limit": "256MB"}) as db:
        db.read_parquet(files).create_view("all_records")
        where = " WHERE NOT (kind='source-runs' AND record_id='literature')" if report_index else ""
        query = db.execute("SELECT kind,record_id,feature_id,pathway_key,kinase,track,record_json FROM all_records" + where)
        while rows := query.fetchmany(256):
            for row in rows:
                yield {**dict(zip(("kind", "record_id", "feature_id", "pathway_key", "kinase", "track"), row[:6])),
                       "record": json.loads(row[6])}


def build_explorer_index(directory, manifest, inputs, scores, sidecar, result, *, pathway_reference=None, comparison=None):
    root = Path(directory)
    pathways, source = read_pathway_reference(pathway_reference)
    pathway = build_pathway_result(manifest, inputs, pathways, source)
    _atomic_json(root/"pathway_result.json", pathway)
    registry = build_validation_registry(scores, sidecar)
    hypotheses=sidecar.get("hypothesis_evidence_packets") or []
    from .experiment_suggestions import suggest_discriminating_interventions
    suggestions=suggest_discriminating_interventions(hypotheses)
    models = (comparison or {}).get("models", [])
    completed_models = sum(m.get("status") == "completed" for m in models)
    comparison_status = ("not_requested" if not models else "completed" if completed_models == len(models)
                         else "partial" if completed_models else "unavailable")
    _atomic_json(root/"validation_registry.json", registry)
    path_for_feature = {}
    for member in pathway["memberships"]:
        path_for_feature.setdefault(member["feature_id"], set()).add(member["pathway_key"])
    with (root/"explorer_records.jsonl").open("x", encoding="utf-8") as stream:
        def emit(kind, identity, record, feature_id="", pathway_key="", kinase="", track=""):
            stream.write(json.dumps(dict(kind=kind, record_id=identity, feature_id=feature_id,
                pathway_key=pathway_key, kinase=kinase, track=track, record_json=json.dumps(record, allow_nan=False)), allow_nan=False)+"\n")
        for fid, identity in sorted(inputs["features"].items()):
            measurements = identity.get("measurements", {})
            record = {**identity, "feature_id": fid, "conditions": manifest["conditions"],
                "pathway_keys": sorted(path_for_feature.get(fid, [])),
                "trajectories": {"relative": inputs["ptm_timeseries"].get(fid, {}), "occupancy": inputs["occupancy_timeseries"].get(fid, {})},
                "q_values": {"relative": inputs["ptm_qvalues"].get(fid, {}), "occupancy": inputs["occupancy_qvalues"].get(fid, {})},
                "observations": measurements}
            record["trajectories"]["unadjusted"] = {c:v for c,m in measurements.items()
                if m.get("status")=="recorded" and (v:=finite(m.get("source",{}).get("ptm_unadjusted_log2fc"))) is not None
                and not m.get("source",{}).get("conventional_log2fc_na")}
            emit("features", fid, record, feature_id=fid)
        for row in pathway["pathways"]:
            emit("pathways", row["pathway_key"], row, pathway_key=row["pathway_key"], track="relative")
        for row in pathway["memberships"]:
            emit("members", signature(row), row, feature_id=row["feature_id"], pathway_key=row["pathway_key"])
        for row in result["kinase_scores"]:
            emit("kinases", row["canonical"], row, kinase=row["canonical"], track="relative")
        for track in ("relative", "occupancy"):
            for kinase, score in scores[track].items():
                for detail in score.get("contribution_details", []):
                    fid = detail["ptm_key"]
                    record = {**detail, "feature_id": fid, "kinase": kinase, "track": track,
                        "ratio_scope": "whole_trajectory", "score_rule": {k:scores["effective_config"].get(k) for k in ("fc_threshold", "q_threshold")},
                        "profile_provenance": score.get("kinase_profile_provenance"),
                        "profile_peak_condition": score.get("profile_peak_condition"),
                        "footprint": score.get("_weighted_site_profiles_for_diagnostics", {}).get(fid)}
                    emit("contributions", signature([track, kinase, fid]), record, feature_id=fid, kinase=kinase, track=track)
        for module in manifest["candidate_modules"]:
            for member in module["members"]:
                record = {**member, "kinase": module["canonical"], "source_type": "candidate_relation",
                          "interpretation": "candidate_not_causal_validation"}
                emit("evidence", signature(record), record, feature_id=member["key"], kinase=module["canonical"])
        emit("source-runs", "pathway_reference", {"source": "canonical_pathway_reference", **source})
        for name, status in manifest.get("reference_snapshots", {}).items():
            emit("source-runs", name, {"source": name, "status": "unavailable" if status == "unavailable" else "available", "snapshot_hash": status})
        emit("source-runs", "literature", {"source": "literature", "status": "not_requested", "reason": "annotation_snapshot_not_bound"})
        for record in registry["records"]:
            emit("validations", record["name"], record)
        for packet in hypotheses:
            emit("mechanism-hypotheses",packet["packet_id"],{**packet,
                "evidence_role":"observational_hypothesis","causality_status":"not_tested",
                "computation_scope":"existing_retained_wave_cross_layer_candidate_policy",
                "signed_network_validation":"not_performed"},kinase=(packet.get("observation") or {}).get("kinase") or "")
        for proposal in suggestions:
            emit("experiment-suggestions",proposal["suggestion_id"],proposal,kinase=proposal["candidate"])
        for model in (comparison or {}).get("models", []):
            summary = {k:v for k,v in model.items() if k not in {"records", "group_crosswalk", "allocation_ledger"}}
            summary["result_record_count"] = len(model.get("records", []))
            summary["detail_artifact"] = "model_comparisons"
            emit("model-comparisons", model["model_id"], summary)
            for i, record in enumerate(model.get("records", [])):
                emit("model-results", model["model_id"]+":"+str(i).zfill(12), {**record,"model_id":model["model_id"]},
                     feature_id=record.get("feature_id", ""), kinase=record.get("kinase", ""))
        wave = sidecar.get("temporal_wave_contract", {})
        unmapped = set(pathway["unmapped_feature_ids"])
        for i, row in enumerate(wave.get("all_evaluated_waves", wave.get("waves", []))):
            members = sorted(set(row.get("members", [])) & unmapped)
            if members:
                emit("unmapped-modules", f"wave-{i}", {**row, "members": members,
                    "module_id": f"wave-{i}", "membership_scope": "pathway_unmapped" if source["status"] in {"available", "empty"} else "pathway_mapping_not_evaluable",
                    "interpretation": "temporal_response_module_not_new_pathway"})
    # docs/BUILD_AND_DEPLOY.md §5.1 — stream flatten, then COPY without ORDER BY.
    observation_jsonl = root / "explorer_observations.jsonl"
    write_explorer_observation_jsonl(root / "explorer_records.jsonl", observation_jsonl)
    spill = root / "explorer-spill"
    spill.mkdir(exist_ok=True)
    _copy_jsonl_to_parquet(
        root / "explorer_records.jsonl",
        root / "explorer_records.parquet",
        {k: "VARCHAR" for k in ("kind", "record_id", "feature_id", "pathway_key", "kinase", "track", "record_json")},
        spill=spill,
    )
    _copy_jsonl_to_parquet(
        observation_jsonl,
        root / "explorer_observations.parquet",
        {"feature_id": "VARCHAR", "track": "VARCHAR", "condition": "VARCHAR", "value": "DOUBLE"},
        spill=spill,
    )
    return {"schema_version": VERSION, "coverage": {**result["coverage"], **pathway["coverage"]},
            "inference_mode":manifest.get("config",{}).get("inference_mode","legacy_unrecorded"),
            "pathway_source": source, "conditions": manifest["conditions"], "analysis_scope": manifest["analysis_scope"],
            "input_scope": manifest.get("input_scope", {}), "index_artifact": "explorer_records.parquet",
            "components": {"pathway": {"evaluation_status": pathway["coverage"]["mapping_evaluation_status"], "source_status": source["status"]},
                "annotation": {"status": "not_requested", "reason": "annotation_snapshot_not_bound"},
                "report": {"status": "not_requested", "reason": "report_revision_not_bound"},
                "model-comparisons":{"status":comparison_status, "requested_count":len(models),
                    "completed_count":completed_models,
                    "model_statuses":{m["model_id"]:{"status":m.get("status"), "reason":m.get("reason"),
                        "evaluation_status":m.get("evaluation_status", "per_record")} for m in models}},
                "mechanism-hypotheses":{"status":"available" if hypotheses else "not_evaluable",
                    "reason":None if hypotheses else "no_existing_hypothesis_packets","signed_network_validation":"not_performed"},
                "experiment-suggestions":{"status":"proposed_not_tested" if suggestions else "not_evaluable",
                    "reason":None if suggestions else "no_competing_hypotheses_with_discriminating_intervention"}},
            "wave_scope": {"input_projection": wave.get("input_projection_provenance"),
                "all_evaluated": len(wave.get("all_evaluated_waves", [])), "retained": len(wave.get("waves", [])),
                "downstream_wave_ids":[w["wave_id"] for w in wave.get("waves",[])],
                "cross_layer":sidecar.get("provenance",{}).get("cross_layer"),
                "unit": "precursor_feature", "downstream_policy": "existing_frozen_retained_scope"}}


def explorer_page(directory, bundle_id, *, kind, pathway_key=None, feature_id=None, kinase=None, track=None, module_id=None, model_id=None, cursor=None, limit=100, mode="inventory", n=None, report_index=None):
    if kind not in KINDS or not 1 <= limit <= 500:
        raise ValueError("invalid_explorer_query")
    if mode not in {"inventory","all_observed","global_top_n","per_condition_top_n"}:
        raise ValueError("invalid_view_selection")
    if mode.endswith("top_n") and (not isinstance(n,int) or isinstance(n,bool) or n<1):
        raise ValueError("top_n_requires_positive_integer")
    if not mode.endswith("top_n") and n is not None: raise ValueError("n_requires_top_n_mode")
    if model_id is not None and kind not in {"model-results", "model-comparisons"}:
        raise ValueError("model_filter_requires_comparison_records")
    filters = dict(pathway_key=pathway_key, feature_id=feature_id, kinase=kinase, track=track, module_id=module_id, model_id=model_id)
    binding = signature(dict(bundle_id=bundle_id, kind=kind, filters=filters, sort="record_id", unit="record",mode=mode,n=n))
    after = ""
    if cursor:
        try:
            token = json.loads(base64.urlsafe_b64decode(cursor))
            if token["binding"] != binding: raise ValueError()
            after = token["after"]
        except Exception as exc:
            raise ValueError("cursor_scope_mismatch") from exc
    clauses, params = ["kind=?"], [kind]
    for field, value in filters.items():
        if value is not None:
            if field == "track" and kind == "features": continue
            if field == "model_id":
                clauses.append("json_extract_string(record_json,'$.model_id')=?")
            elif field == "module_id":
                clauses.append("feature_id IN (SELECT json_extract_string(j.value,'$') FROM records r,json_each(r.record_json,'$.members') j WHERE r.kind='unmapped-modules' AND r.record_id=?)")
            elif field == "kinase" and kind == "features":
                clauses.append("feature_id IN (SELECT feature_id FROM records WHERE kind IN ('evidence','contributions') AND kinase=?)")
            elif field == "pathway_key" and kind in {"features", "contributions", "evidence","report-claims"}:
                clauses.append("feature_id IN (SELECT feature_id FROM records WHERE kind='members' AND pathway_key=?)")
            else:
                clauses.append(f"{field}=?")
            params.append(value)
    where = " AND ".join(clauses)
    with duckdb.connect(config={"threads":1,"memory_limit":"256MB"}) as db:
        files=explorer_record_parquet_files(directory)
        if report_index: files.extend(parquet_files_for_index(report_index))
        db.read_parquet(files).create_view("all_records")
        # The base run did not request literature. Its descendant's actual
        # sealed retrieval ledger supersedes that placeholder, not the results.
        db.execute("CREATE VIEW records AS SELECT * FROM all_records"+(
            " WHERE NOT (kind='source-runs' AND record_id='literature')" if report_index else ""))
        universe = db.execute(f"SELECT count(*) FROM records WHERE {where}", params).fetchone()[0]
        if kind == "features" and mode != "inventory":
            axis=track or "relative"
            if axis not in {"relative","unadjusted","occupancy"}: raise ValueError("unsupported_trajectory_track")
            numeric_path=Path(directory)/"explorer_observations.parquet"
            if numeric_path.is_file():
                db.read_parquet(str(numeric_path)).create_view("observations")
                numeric=f"SELECT feature_id,condition,abs(value) AS effect FROM observations WHERE track='{axis}' AND feature_id IN (SELECT feature_id FROM records WHERE {where})"
            else:
                numeric=f"SELECT r.feature_id,j.key AS condition,abs(CAST(j.value AS DOUBLE)) AS effect FROM records r, json_each(r.record_json,'$.trajectories.{axis}') j WHERE {where} AND j.type NOT IN ('NULL','OBJECT','ARRAY')"
            if mode == "global_top_n":
                selected=f"SELECT feature_id FROM ({numeric}) GROUP BY feature_id ORDER BY max(effect) DESC,feature_id LIMIT ?"
                selection_params=[*params,n]
            elif mode == "per_condition_top_n":
                selected=f"SELECT DISTINCT feature_id FROM (SELECT feature_id,row_number() OVER(PARTITION BY condition ORDER BY effect DESC,feature_id) AS ranking FROM ({numeric})) WHERE ranking<=?"
                selection_params=[*params,n]
            else:
                selected=f"SELECT DISTINCT feature_id FROM ({numeric})";selection_params=params.copy()
            where+=f" AND feature_id IN ({selected})";params.extend(selection_params)
        total = db.execute(f"SELECT count(*) FROM records WHERE {where}", params).fetchone()[0]
        rows = db.execute(f"SELECT record_id,record_json FROM records WHERE {where} AND record_id>? ORDER BY record_id LIMIT ?", [*params,after,limit+1]).fetchall()
    next_cursor = base64.urlsafe_b64encode(json.dumps({"binding":binding,"after":rows[limit-1][0]}).encode()).decode() if len(rows)>limit else None
    return {"schema_version": VERSION, "bundle_id": bundle_id, "scope": filters,
            "selection":{"mode":mode,"n":n,"ranking_metric":"abs_effect","ranking_version":"plot_rank.v1","tie_break":"feature_id_ascending","axis":track or "relative"},
            "universe_count":universe,
            "total_count": total, "returned_count": min(len(rows),limit), "unit": "feature" if kind=="features" else "membership" if kind=="members" else kind,
            "records": [json.loads(r[1]) for r in rows[:limit]], "next_cursor": next_cursor}
