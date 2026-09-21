"""Explorer parquet write must flatten jsonl without a global DuckDB sort."""
import json
from pathlib import Path

from ptm_shared.signaling_evidence_index import (
    EXPLORER_JSONL_CHUNK_BYTES,
    _copy_jsonl_to_parquet,
    explorer_record_parquet_files,
    split_jsonl_by_bytes,
    write_explorer_observation_jsonl,
)


def test_observation_jsonl_skips_non_numeric_and_non_features(tmp_path):
    records = tmp_path / "explorer_records.jsonl"
    records.write_text(
        json.dumps({
            "kind": "features",
            "record_id": "F1",
            "feature_id": "F1",
            "record_json": json.dumps({
                "trajectories": {
                    "relative": {"5min": 2.0, "bad": {"nested": 1}, "empty": None},
                    "unadjusted": {"5min": "1.5"},
                    "occupancy": {"5min": "nan"},
                }
            }),
        })
        + "\n"
        + json.dumps({
            "kind": "kinases",
            "record_id": "AKT",
            "feature_id": "",
            "record_json": json.dumps({"trajectories": {"relative": {"5min": 9}}}),
        })
        + "\n",
        encoding="utf-8",
    )
    dest = tmp_path / "obs.jsonl"
    assert write_explorer_observation_jsonl(records, dest) == 2
    rows = [json.loads(line) for line in dest.read_text(encoding="utf-8").splitlines()]
    assert {(r["track"], r["condition"], r["value"]) for r in rows} == {
        ("relative", "5min", 2.0),
        ("unadjusted", "5min", 1.5),
    }


def test_copy_jsonl_to_parquet_has_no_write_time_order_by():
    source = Path(__file__).resolve().parents[1] / "signaling_evidence_index.py"
    text = source.read_text(encoding="utf-8")
    write = text.split("def explorer_page", 1)[0]
    assert "COPY (SELECT * FROM src)" in write
    assert "ORDER BY kind,record_id" not in write
    assert "ORDER BY track,condition,feature_id" not in write
    assert "json_each(r.record_json,'$.trajectories" not in write


def test_copy_jsonl_to_parquet_roundtrip(tmp_path):
    jsonl = tmp_path / "obs.jsonl"
    jsonl.write_text(
        json.dumps({"feature_id": "F1", "track": "relative", "condition": "5min", "value": 2.0}) + "\n",
        encoding="utf-8",
    )
    parquet = tmp_path / "obs.parquet"
    _copy_jsonl_to_parquet(
        jsonl,
        parquet,
        {"feature_id": "VARCHAR", "track": "VARCHAR", "condition": "VARCHAR", "value": "DOUBLE"},
        spill=tmp_path / "spill",
    )
    assert parquet.is_file() and parquet.stat().st_size > 0


def test_split_jsonl_by_bytes_keeps_lines_intact(tmp_path):
    src = tmp_path / "records.jsonl"
    src.write_text("aa\nbbbb\ncc\n", encoding="utf-8")
    parts = split_jsonl_by_bytes(src, tmp_path / "parts", max_bytes=5)
    assert len(parts) == 3
    assert [p.read_text(encoding="utf-8") for p in parts] == ["aa\n", "bbbb\n", "cc\n"]


def test_chunked_copy_keeps_parts_and_layout(tmp_path, monkeypatch):
    import duckdb
    import ptm_shared.signaling_evidence_index as idx
    monkeypatch.setattr(idx, "EXPLORER_JSONL_CHUNK_BYTES", 20)
    jsonl = tmp_path / "explorer_records.jsonl"
    rows = [
        {"kind": "features", "record_id": f"F{i}", "feature_id": f"F{i}",
         "pathway_key": "", "kinase": "", "track": "relative",
         "record_json": json.dumps({"i": i})}
        for i in range(6)
    ]
    jsonl.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    parquet = tmp_path / "explorer_records.parquet"
    idx._copy_jsonl_to_parquet(
        jsonl,
        parquet,
        {k: "VARCHAR" for k in ("kind", "record_id", "feature_id", "pathway_key", "kinase", "track", "record_json")},
        spill=tmp_path / "spill",
    )
    parts = explorer_record_parquet_files(tmp_path)
    assert parquet.is_file()
    assert all(Path(p).name.startswith("explorer_records-part-") for p in parts)
    with duckdb.connect() as db:
        n = db.execute("SELECT COUNT(*) FROM read_parquet(?)", [str(tmp_path / "explorer_records-part-*.parquet")]).fetchone()[0]
        layout = db.execute("SELECT kind, record_id FROM read_parquet(?)", [str(parquet)]).fetchone()
    assert n == 6
    assert layout == ("layout", "parts")
    assert EXPLORER_JSONL_CHUNK_BYTES == 32 * 1024 * 1024
