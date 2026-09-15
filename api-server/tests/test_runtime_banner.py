from datetime import datetime, timezone
from pathlib import Path

from app.core.runtime_banner import (
    format_kst,
    load_last_deploy,
    parse_docker_ts,
    pick_applied_at,
    short_label,
    summarize_runtime,
)


def test_parse_docker_nanoseconds():
    dt = parse_docker_ts("2026-09-15T00:58:12.123456789Z")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 9
    assert dt.day == 15
    assert format_kst(dt) == "2026-09-15 09:58:12"


def test_parse_zero_docker_timestamp_is_empty():
    assert parse_docker_ts("0001-01-01T00:00:00Z") is None
    assert parse_docker_ts("") is None


def test_short_labels():
    assert short_label("ptm-worker-report") == "Report"
    assert short_label("celery-worker-report") == "Report"
    assert short_label("frontend") == "UI"


def test_latest_restart_clusters_near_starts(tmp_path: Path):
    containers = [
        {
            "id": "ptm-worker-report",
            "short": "Report",
            "started_at": "2026-09-15T00:58:20Z",
            "image_created": "2026-09-14T10:00:00Z",
        },
        {
            "id": "ptm-worker-rag",
            "short": "RAG",
            "started_at": "2026-09-15T00:58:05Z",
            "image_created": "2026-09-14T10:00:00Z",
        },
        {
            "id": "ptm-frontend",
            "short": "UI",
            "started_at": "2026-09-13T01:00:00Z",
            "image_created": "2026-09-13T01:00:00Z",
        },
        {
            "id": "ptm-mysql",
            "short": "MySQL",
            "started_at": "2026-09-15T01:10:00Z",
            "image_created": "2026-01-01T00:00:00Z",
        },
    ]
    summary = summarize_runtime(containers)
    assert summary["latest_restart"]["labels"] == ["Report", "RAG"]
    assert summary["latest_restart"]["at_kst"] == "2026-09-15 09:58:20"
    # Newest app images belong to the workers; infra is excluded.
    assert summary["latest_image"]["labels"] == ["Report", "RAG"]
    assert "MySQL" not in summary["latest_image"]["labels"]


def test_load_last_deploy(tmp_path: Path):
    path = tmp_path / "event.json"
    path.write_text(
        '{"schema":"dev_deploy_event.v1","at":"2026-09-15T01:59:00+09:00",'
        '"kind":"dev-deploy","commit":"3555215","version":"2.5.1",'
        '"built":[],"restarted":["celery-worker-report"]}',
        encoding="utf-8",
    )
    event = load_last_deploy(path)
    assert event is not None
    assert event["restarted_labels"] == ["Report"]
    assert event["at_kst"] == "2026-09-15 01:59:00"
    assert event["commit"] == "3555215"


def test_format_kst_from_utc():
    dt = datetime(2026, 9, 14, 15, 30, 0, tzinfo=timezone.utc)
    assert format_kst(dt) == "2026-09-15 00:30:00"


def test_applied_at_prefers_live_restart_over_commit_clock():
    applied = pick_applied_at(
        last_deploy=None,
        latest_restart={"at_kst": "2026-09-15 10:59:50"},
        git_date="2026-09-15 00:30:38",
    )
    assert applied == "2026-09-15 10:59:50"


def test_applied_at_uses_newer_deploy_event():
    applied = pick_applied_at(
        last_deploy={"at": "2026-09-15T11:03:57+09:00", "at_kst": "2026-09-15 11:03:57"},
        latest_restart={"at_kst": "2026-09-15 10:59:50"},
        git_date="2026-09-15 00:30:38",
    )
    assert applied == "2026-09-15 11:03:57"
