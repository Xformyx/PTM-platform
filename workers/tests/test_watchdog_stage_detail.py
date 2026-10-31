"""Watchdog label for a live task with quiet order logs."""

from watchdog.tasks import stage_detail_for_quiet_order


def test_live_task_without_progress_logs_is_running_not_halted():
    detail = stage_detail_for_quiet_order(64, 50, True)
    assert detail.startswith("Running:")
    assert "Halted" not in detail
    assert "possible hang" not in detail.lower()
    assert "64 minutes" in detail
    assert "progress_pct unchanged at 50.0%" in detail


def test_changed_progress_omits_the_unchanged_clause():
    detail = stage_detail_for_quiet_order(90, 50, False)
    assert detail == "Running: Celery task is active with no progress log for 90 minutes"
