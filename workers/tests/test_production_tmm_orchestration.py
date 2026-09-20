"""Operational gates for production TMM wait — not measurement tests."""
from __future__ import annotations

from pathlib import Path

import pytest
from celery.exceptions import TimeoutError as CeleryTimeout

from common import production_analysis as pa


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "docker-compose.yml").is_file() and (parent / "scripts" / "dev-deploy.sh").is_file():
            return parent
    return here.parents[2]


ROOT = _repo_root()
DEPLOY = ROOT / "scripts" / "dev-deploy.sh"
PROD_DEPLOY = ROOT / "scripts" / "deploy.sh"
COMPOSE = ROOT / "docker-compose.yml"
OPS = ROOT / "docs" / "BUILD_AND_DEPLOY.md"


def test_declared_wait_constants_match_ops_doc() -> None:
    assert pa.CONSUMER_WAIT_SECONDS == 30
    assert pa.HEARTBEAT_SECONDS == 120
    assert pa.JOIN_TIMEOUT_SECONDS == 21780
    assert pa.HEARTBEAT_SECONDS < 60 * 60
    if not OPS.is_file():
        pytest.skip("BUILD_AND_DEPLOY.md is not mounted in the worker container")
    text = OPS.read_text(encoding="utf-8")
    assert "CONSUMER_WAIT_SECONDS" in text
    assert "HEARTBEAT_SECONDS" in text
    assert "`CONSUMER_WAIT_SECONDS` | 30" in text
    assert "`HEARTBEAT_SECONDS` | 120" in text


def test_queue_consumer_detects_production_tmm_name() -> None:
    class _Inspect:
        def active_queues(self):
            return {"production-tmm@host": [{"name": "production_tmm"}]}

    assert pa.production_tmm_queue_has_consumer(inspector=_Inspect()) is True


def test_queue_consumer_false_when_inspect_empty() -> None:
    class _Inspect:
        def active_queues(self):
            return {}

    assert pa.production_tmm_queue_has_consumer(inspector=_Inspect()) is False


def test_require_consumer_fails_closed_when_missing() -> None:
    with pytest.raises(RuntimeError, match="production_tmm_worker_unavailable"):
        pa.require_production_tmm_consumer(
            wait_seconds=0.01,
            poll_seconds=0.01,
            has_consumer=lambda: False,
        )


def test_require_consumer_returns_when_present() -> None:
    pa.require_production_tmm_consumer(
        wait_seconds=0.01,
        poll_seconds=0.01,
        has_consumer=lambda: True,
    )


def test_wait_publishes_heartbeat_then_returns(monkeypatch) -> None:
    heartbeats = []
    monkeypatch.setattr("common.run_control.abort_if_superseded", lambda _oid: None)
    monkeypatch.setattr(
        "common.progress.publish_progress",
        lambda *args, **kwargs: heartbeats.append(args),
    )
    monkeypatch.setattr(pa, "_tmm_wait_snapshot", lambda _oid: "job=running")

    class _Task:
        id = "task-1"
        def __init__(self):
            self.calls = 0

        def get(self, timeout=None, propagate=True):
            self.calls += 1
            if self.calls == 1:
                raise CeleryTimeout()
            return {"execution_status": "completed", "job_id": "j1"}

    result = pa.wait_for_production_tmm_result(
        _Task(),
        80,
        timeout=10,
        heartbeat_seconds=1,
        has_consumer=lambda: True,
    )
    assert result["job_id"] == "j1"
    assert heartbeats
    assert heartbeats[0][2] == "temporal_evidence_preparation"
    assert "Waiting for production TMM" in heartbeats[0][5]


def test_wait_fails_if_consumer_disappears(monkeypatch) -> None:
    monkeypatch.setattr("common.run_control.abort_if_superseded", lambda _oid: None)
    monkeypatch.setattr("common.progress.publish_progress", lambda *a, **k: None)
    monkeypatch.setattr(pa, "CONSUMER_WAIT_SECONDS", 1)

    class _Clock:
        def __init__(self):
            self.t = 0.0

        def __call__(self):
            return self.t

    clock = _Clock()

    class _Task:
        id = "task-2"

        def get(self, timeout=None, propagate=True):
            clock.t += float(timeout or 0)
            raise CeleryTimeout()

    with pytest.raises(RuntimeError, match="consumer disappeared"):
        pa.wait_for_production_tmm_result(
            _Task(),
            80,
            timeout=20,
            heartbeat_seconds=1,
            has_consumer=lambda: False,
            now=clock,
        )


def test_deploy_scripts_always_ensure_production_tmm_worker() -> None:
    if not DEPLOY.is_file():
        pytest.skip("deploy scripts are not mounted in the worker container")
    dev = DEPLOY.read_text(encoding="utf-8")
    prod = PROD_DEPLOY.read_text(encoding="utf-8")
    compose = COMPOSE.read_text(encoding="utf-8")
    assert "_ensure_production_tmm_worker" in dev
    assert "_ensure_production_tmm_worker" in prod
    assert "up -d production-tmm-worker" in dev
    assert "up -d production-tmm-worker" in prod
    assert "  production-tmm-worker:" in compose
    assert "-Q production_tmm" in compose
    no_change_tail = dev.split("변경 없음 (git/mtime)", 1)[1]
    assert "_ensure_production_tmm_worker" in no_change_tail.split("exit 0", 1)[0]
