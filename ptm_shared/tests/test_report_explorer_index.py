"""Report explorer index must not sort the full packet table in 256MB DuckDB."""
import json
from pathlib import Path

from ptm_shared.report_explorer_index import build_report_explorer_index
from ptm_shared.signaling_evidence_index import parquet_files_for_index


def test_report_explorer_index_source_has_no_write_time_order_by():
    text = Path(__file__).resolve().parents[1].joinpath("report_explorer_index.py").read_text(encoding="utf-8")
    assert "_copy_jsonl_to_parquet" in text
    assert "ORDER BY kind,record_id" not in text
    assert 'memory_limit":"256MB"' not in text


def test_build_report_explorer_index_writes_parts_when_chunked(tmp_path, monkeypatch):
    import duckdb
    import ptm_shared.signaling_evidence_index as idx

    monkeypatch.setattr(idx, "EXPLORER_JSONL_CHUNK_BYTES", 80)
    authoring = {
        "reader_cards": [
            {"feature_identity": {"feature_id": f"FEATURE-{i:04d}"}, "evidence_ids": [f"e{i}"]}
            for i in range(20)
        ]
    }
    (tmp_path / "authoring.json").write_text(json.dumps(authoring), encoding="utf-8")
    report = {
        "revision_id": "rev1",
        "artifacts": [{"role": "authoring_packet", "filename": "authoring.json", "sha256": "abc"}],
        "references": [],
        "release": {"status": "draft"},
    }
    destination = tmp_path / "records.parquet"
    result = build_report_explorer_index(tmp_path, report, destination)
    parts = parquet_files_for_index(destination)
    assert destination.is_file()
    assert all(Path(path).name.startswith("records-part-") for path in parts)
    with duckdb.connect() as db:
        n = db.execute(
            "SELECT COUNT(*) FROM read_parquet(?)",
            [str(tmp_path / "records-part-*.parquet")],
        ).fetchone()[0]
    assert n == result["record_count"]
    assert n >= 20
