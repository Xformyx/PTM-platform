"""Dedicated Celery application for offline locked benchmark scoring only."""

from __future__ import annotations

import os

from celery import Celery

app = Celery("ptm_benchmark_runner")
app.conf.broker_url = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/1")
app.conf.result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/2")
app.conf.task_routes = {"benchmarking.tasks.*": {"queue": "benchmark"}}
app.autodiscover_tasks(["benchmarking"])
